"""
Personal edit: slideshow start points.

Pure helper logic (no Qt) for:
  - parsing/formatting video bookmarks stored in a file note
  - choosing where a video/animation should start during a slideshow
  - mapping a timestamp to a frame index for the native animation renderer

Bookmark note format is forgiving: timestamps separated by commas, semicolons, spaces or new lines.
Each timestamp can be "SS", "SS.sss", "M:SS", "MM:SS.sss" or "H:MM:SS(.sss)".
A bookmark can carry its own play length:
  "3:10+45" or "3:10+0:45" - start at 3:10, play for 45 seconds
  "3:10-3:55"              - start at 3:10, play until 3:55
Anything that does not parse is ignored, so you can leave comments in the note.

Bookmarks are favourite spots. They carry no tags.

Tag marks are a separate feature, stored in their own note. They use the same format, but each one carries tags in
square brackets right after it, separated by commas, and is meant to be a whole section:
  "3:10-3:55 [samus aran, character:samus aran, blue hair]"
When the slideshow is set to use tag marks and the search has a matching tag, it starts at a matching tag mark.
"""

import collections
import fnmatch
import random
import re

BOOKMARK_MODE_OFF = 0
BOOKMARK_MODE_FIRST = 1
BOOKMARK_MODE_RANDOM = 2
_LEGACY_BOOKMARK_MODE_SEARCH_TAGS = 3 # an old saved option from when bookmarks had tags. it now just means 'random bookmark'

TAG_MARK_MODE_OFF = 0
TAG_MARK_MODE_SEARCH = 1 # start at a random tag mark that matches the search; if none match, fall back to the bookmark/random rules

Bookmark = collections.namedtuple( 'Bookmark', [ 'start_ms', 'length_ms' ] )
TagMark = collections.namedtuple( 'TagMark', [ 'start_ms', 'length_ms', 'tags' ] )

# if there is no max play time cap, do not pick a random start right at the very end of the file
RANDOM_START_NO_CAP_MAX_FRACTION = 0.9

_TOKEN_SPLIT_RE = re.compile( r'[,;\s]+' )
_JOINER_SPACE_RE = re.compile( r'\s*([+\-])\s*' ) # '3:10 + 45' -> '3:10+45'
_BOOKMARK_PIECE_RE = re.compile( r'\[[^\]]*\]|[^\s,;\[\]]+' ) # a [tag group] or a bookmark token
_TIMESTAMP_RE = re.compile( r'^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$' )

def ParseTimestampMS( token: str ) -> int | None:

    token = token.strip()

    if token == '':

        return None


    match = _TIMESTAMP_RE.match( token )

    if match is None:

        return None


    ( a, b, seconds ) = match.groups()

    hours = 0
    minutes = 0

    if a is not None and b is not None:

        hours = int( a )
        minutes = int( b )

    elif a is not None:

        minutes = int( a )


    seconds = float( seconds )

    if ( a is not None ) and seconds >= 60:

        return None # "1:75" is not a valid timestamp


    if hours > 0 and minutes >= 60:

        return None


    return int( round( ( ( hours * 3600 ) + ( minutes * 60 ) + seconds ) * 1000 ) )


def ParseBookmarkToken( token: str ) -> tuple[ int, int | None ] | None:
    """
    Parses one bookmark: "3:10", "3:10+45" or "3:10-3:55". Returns ( start_ms, play_length_ms or None ), or None if it is not a bookmark.
    A length that does not parse, or a range that ends before it starts, gives a bookmark with no length.
    """

    token = token.strip()

    for ( joiner, is_range ) in ( ( '+', False ), ( '-', True ) ):

        if joiner in token:

            ( start_text, extra_text ) = token.split( joiner, 1 )

            start_ms = ParseTimestampMS( start_text )

            if start_ms is None:

                return None


            extra_ms = ParseTimestampMS( extra_text )

            length_ms = None

            if extra_ms is not None:

                length_ms = ( extra_ms - start_ms ) if is_range else extra_ms

                if length_ms <= 0:

                    length_ms = None



            return ( start_ms, length_ms )



    start_ms = ParseTimestampMS( token )

    if start_ms is None:

        return None


    return ( start_ms, None )


def CleanTag( tag: str ) -> str:
    
    return ' '.join( tag.strip().lower().split() )
    

def ParseTagGroup( group: str ) -> tuple:
    
    return ParseTagText( group.strip()[ 1 : -1 ] )
    

def ParseTagText( text: str ) -> tuple:
    
    inner = text
    
    tags = []
    
    for tag in re.split( r'[,;]', inner ):
        
        tag = CleanTag( tag )
        
        if tag != '' and tag not in tags:
            
            tags.append( tag )
            
        
    
    return tuple( tags )
    

def _ParseMarks( text: str | None ) -> list:
    """
    Returns sorted TagMark( start_ms, length_ms or None, tags ) tuples, tags being empty for a plain bookmark.
    If the same start appears twice, the first one written wins.
    A [tag, group] right after an entry belongs to it; a tag group with no entry before it is ignored.
    """
    
    if text is None:
        
        return []
        
    
    # join '3:10 + 45' -> '3:10+45', but leave the insides of [tag groups] alone
    pieces = re.split( r'(\[[^\]]*\])', text )
    
    text = ''.join( p if p.startswith( '[' ) else _JOINER_SPACE_RE.sub( r'\1', p ) for p in pieces )
    
    bookmarks = collections.OrderedDict()
    
    last_start_ms = None
    
    for m in _BOOKMARK_PIECE_RE.finditer( text ):
        
        piece = m.group()
        
        if piece.startswith( '[' ):
            
            if last_start_ms is not None and bookmarks[ last_start_ms ].tags == ():
                
                bookmarks[ last_start_ms ] = bookmarks[ last_start_ms ]._replace( tags = ParseTagGroup( piece ) )
                
            
            last_start_ms = None
            
            continue
            
        
        bookmark = ParseBookmarkToken( piece )
        
        if bookmark is None:
            
            last_start_ms = None
            
            continue
            
        
        ( start_ms, length_ms ) = bookmark
        
        if start_ms in bookmarks:
            
            last_start_ms = None # a duplicate; first one written wins, so its tags do not count either
            
        else:
            
            bookmarks[ start_ms ] = TagMark( start_ms, length_ms, () )
            
            last_start_ms = start_ms
            
        
    
    return sorted( bookmarks.values() )


def ParseBookmarks( text: str | None ) -> list:
    """
    Returns sorted Bookmark( start_ms, length_ms or None ) tuples from the bookmarks note.
    Bookmarks have no tags. Any [tag group] in the note (from before tag marks existed) is ignored.
    """
    
    return [ Bookmark( m.start_ms, m.length_ms ) for m in _ParseMarks( text ) ]
    

def ParseTagMarks( text: str | None ) -> list:
    """
    Returns sorted TagMark( start_ms, length_ms or None, tags ) tuples from the tag marks note.
    An entry with no tags is not a tag mark and is skipped.
    """
    
    return [ m for m in _ParseMarks( text ) if len( m.tags ) > 0 ]
    

def ParseBookmarksMS( text: str | None ) -> list[ int ]:

    return [ b.start_ms for b in ParseBookmarks( text ) ]


def FormatBookmark( start_ms: int, length_ms: int | None ) -> str:
    
    return FormatTagMark( start_ms, length_ms, () )
    

def FormatTagMark( start_ms: int, length_ms: int | None, tags = () ) -> str:
    
    result = FormatTimestampMS( start_ms )
    
    if length_ms is not None:
        
        result += '+' + FormatTimestampMS( length_ms )
        
    
    if len( tags ) > 0:
        
        result += ' [' + ', '.join( tags ) + ']'
        
    
    return result


def FormatTimestampMS( ms: int ) -> str:

    ms = max( 0, int( round( ms ) ) )

    ( total_seconds, remainder_ms ) = divmod( ms, 1000 )
    ( total_minutes, seconds ) = divmod( total_seconds, 60 )
    ( hours, minutes ) = divmod( total_minutes, 60 )

    if hours > 0:

        result = f'{hours}:{minutes:02}:{seconds:02}'

    else:

        result = f'{minutes}:{seconds:02}'


    if remainder_ms > 0:

        result += f'.{remainder_ms:03}'.rstrip( '0' )


    return result


def ParseDurationListS( text: str | None ) -> list[ int ]:
    """
    Parses a preset list like "30, 60, 2:00, 5:00" into sorted unique whole seconds. Zero and junk are dropped.
    """

    results = set()

    if text is None:

        return []


    for token in _TOKEN_SPLIT_RE.split( text ):

        ms = ParseTimestampMS( token )

        if ms is None:

            continue


        s = int( round( ms / 1000 ) )

        if s > 0:

            results.add( s )



    return sorted( results )


def ParseSingleDurationS( text: str | None ) -> int | None:

    if text is None:

        return None


    ms = ParseTimestampMS( text )

    if ms is None:

        return None


    s = int( round( ms / 1000 ) )

    return s if s > 0 else None


def FormatDurationS( seconds: int ) -> str:

    seconds = int( seconds )

    if seconds < 60:

        return f'{seconds}s'


    ( hours, remainder ) = divmod( seconds, 3600 )
    ( minutes, secs ) = divmod( remainder, 60 )

    parts = []

    if hours > 0:

        parts.append( f'{hours}h' )


    if minutes > 0:

        parts.append( f'{minutes}m' )


    if secs > 0:

        parts.append( f'{secs}s' )


    return ' '.join( parts )


def AddBookmarkToText( text: str | None, new_ms: int, merge_within_ms: int = 500 ) -> str:
    """
    Returns the new note text with the bookmark added. Bookmarks are rewritten as a sorted, comma-separated list.
    A new bookmark within merge_within_ms of an existing one is treated as a duplicate.
    Anything already in the note, including old tag groups, is kept as it was.
    """

    marks = _ParseMarks( text )
    
    if not any( abs( m.start_ms - new_ms ) <= merge_within_ms for m in marks ):
        
        marks.append( TagMark( int( new_ms ), None, () ) )
        
    
    marks.sort()
    
    return ', '.join( FormatTagMark( m.start_ms, m.length_ms, m.tags ) for m in marks )
    

def AddTagMarkToText( text: str | None, new_ms: int, tags, length_ms: int | None = None, merge_within_ms: int = 500 ) -> str:
    """
    Returns the new note text with the tag mark added. A tag mark within merge_within_ms of the new one is replaced by it.
    """
    
    marks = [ m for m in _ParseMarks( text ) if abs( m.start_ms - new_ms ) > merge_within_ms ]
    
    marks.append( TagMark( int( new_ms ), length_ms, tuple( tags ) ) )
    
    marks.sort()
    
    return ', '.join( FormatTagMark( m.start_ms, m.length_ms, m.tags ) for m in marks )
    

class SearchTagMatcher( object ):
    """
    What a file search is looking for, boiled down for bookmark matching.
    Unnamespaced tags match any namespace either way round, so 'samus aran' and 'character:samus aran' match each other.
    Wildcards like 'samus*' or 'character:*' work too.
    """
    
    def __init__( self, included_tags = (), excluded_tags = (), included_patterns = (), excluded_patterns = () ):
        
        self._included_tags = { CleanTag( t ) for t in included_tags }
        self._excluded_tags = { CleanTag( t ) for t in excluded_tags }
        self._included_patterns = [ CleanTag( p ) for p in included_patterns ]
        self._excluded_patterns = [ CleanTag( p ) for p in excluded_patterns ]
        
    
    @staticmethod
    def _Subtag( tag: str ) -> str:
        
        return tag.split( ':', 1 )[1] if ':' in tag else tag
        
    
    @classmethod
    def _TagMatchesTag( cls, bookmark_tag: str, search_tag: str ) -> bool:
        
        if bookmark_tag == search_tag:
            
            return True
            
        
        if ':' not in search_tag and cls._Subtag( bookmark_tag ) == search_tag:
            
            return True
            
        
        if ':' not in bookmark_tag and cls._Subtag( search_tag ) == bookmark_tag:
            
            return True
            
        
        return False
        
    
    @classmethod
    def _TagMatchesPattern( cls, bookmark_tag: str, pattern: str ) -> bool:
        
        if fnmatch.fnmatchcase( bookmark_tag, pattern ):
            
            return True
            
        
        if ':' not in pattern and fnmatch.fnmatchcase( cls._Subtag( bookmark_tag ), pattern ):
            
            return True
            
        
        return False
        
    
    def IsEmpty( self ) -> bool:
        
        return len( self._included_tags ) + len( self._included_patterns ) == 0
        
    
    def TagIsWanted( self, tag: str ) -> bool:
        
        tag = CleanTag( tag )
        
        return any( self._TagMatchesTag( tag, t ) for t in self._included_tags ) or any( self._TagMatchesPattern( tag, p ) for p in self._included_patterns )
        
    
    def TagIsExcluded( self, tag: str ) -> bool:
        
        tag = CleanTag( tag )
        
        return any( self._TagMatchesTag( tag, t ) for t in self._excluded_tags ) or any( self._TagMatchesPattern( tag, p ) for p in self._excluded_patterns )
        
    
    def TagMarkIsWanted( self, tag_mark ) -> bool:
        
        return any( self.TagIsWanted( t ) for t in tag_mark.tags )
        
    
    def TagMarkIsExcluded( self, tag_mark ) -> bool:
        
        return any( self.TagIsExcluded( t ) for t in tag_mark.tags )
        


def ChooseTagMark(
    duration_ms: int | None,
    tag_marks: list,
    tag_mark_mode: int,
    search_tag_matcher: SearchTagMatcher | None,
    rng: random.Random | None = None
) -> TagMark | None:
    """
    Picks a random tag mark that has a tag the search is looking for (and none it excludes). None if tag marks are off,
    the search has no tags to match, or nothing matches.
    """
    
    if rng is None:
        
        rng = random
        
    
    if tag_mark_mode != TAG_MARK_MODE_SEARCH or search_tag_matcher is None or search_tag_matcher.IsEmpty():
        
        return None
        
    
    if duration_ms is None or duration_ms <= 0:
        
        return None
        
    
    candidates = [
        m for m in tag_marks
        if 0 <= m.start_ms < duration_ms and search_tag_matcher.TagMarkIsWanted( m ) and not search_tag_matcher.TagMarkIsExcluded( m )
    ]
    
    if len( candidates ) == 0:
        
        return None
        
    
    return rng.choice( candidates )
    

def ChooseStartWithinTagMark( duration_ms: int, tag_mark: TagMark, max_play_s: int | None, rng: random.Random | None = None ) -> tuple[ int, int | None ]:
    """
    If the tag mark's section is longer than the clip length, returns a random start inside it with the clip length as the play length,
    so the whole clip stays within the section. Otherwise returns the tag mark's own ( start_ms, length_ms ).
    """
    
    if rng is None:
        
        rng = random
        
    
    start_ms = tag_mark.start_ms
    length_ms = tag_mark.length_ms
    
    if length_ms is None or max_play_s is None or max_play_s <= 0:
        
        return ( start_ms, length_ms )
        
    
    clip_ms = int( max_play_s * 1000 )
    
    section_end_ms = min( start_ms + length_ms, duration_ms )
    
    available_ms = section_end_ms - start_ms
    
    if available_ms > clip_ms:
        
        return ( start_ms + rng.randint( 0, available_ms - clip_ms ), clip_ms )
        
    
    return ( start_ms, length_ms )
    

def ChooseStartPoint(
    duration_ms: int | None,
    bookmarks: list,
    bookmark_mode: int,
    random_start_min_duration_s: int | None,
    max_play_s: int | None,
    rng: random.Random | None = None,
    search_tag_matcher: SearchTagMatcher | None = None,
    tag_marks: list | tuple = (),
    tag_mark_mode: int = TAG_MARK_MODE_OFF
) -> tuple[ int, int | None ] | None:
    """
    Like ChooseStartPositionMS, but bookmarks are ( start_ms, play_length_ms or None ) pairs (plain ints are fine too).
    Returns ( start_ms, play_length_ms from the chosen bookmark/tag mark or None ), or None for 'start at the beginning as normal'.
    
    Priority: a tag mark matching the search (if tag mark mode is on) > bookmarks (if the mode is on and the file has valid ones) > random start > beginning.
    
    A tag mark section longer than the clip length (max_play_s) is not played from its start: a random clip-length window inside the section is chosen instead.
    A tag mark with no length, or with no clip length set to compare against, starts at its own start as normal.
    """

    if rng is None:

        rng = random


    if duration_ms is None or duration_ms <= 0:

        return None


    chosen_tag_mark = ChooseTagMark( duration_ms, tag_marks, tag_mark_mode, search_tag_matcher, rng = rng )
    
    if chosen_tag_mark is not None:
        
        return ChooseStartWithinTagMark( duration_ms, chosen_tag_mark, max_play_s, rng = rng )
        
    
    if bookmark_mode == _LEGACY_BOOKMARK_MODE_SEARCH_TAGS:
        
        bookmark_mode = BOOKMARK_MODE_RANDOM
        
    
    normalised = []
    
    for b in bookmarks:
        
        if isinstance( b, Bookmark ):
            
            normalised.append( b )
            
        elif isinstance( b, tuple ):
            
            normalised.append( Bookmark( b[0], b[1] if len( b ) > 1 else None ) )
            
        else:
            
            normalised.append( Bookmark( b, None ) )
            
        
    
    if bookmark_mode in ( BOOKMARK_MODE_FIRST, BOOKMARK_MODE_RANDOM ):
        
        valid_bookmarks = [ b for b in normalised if 0 <= b.start_ms < duration_ms ]
        
        if len( valid_bookmarks ) > 0:
            
            if bookmark_mode == BOOKMARK_MODE_FIRST:
                
                chosen = min( valid_bookmarks, key = lambda b: b.start_ms )
                
            else:
                
                chosen = rng.choice( valid_bookmarks )
                
            
            return ( chosen.start_ms, chosen.length_ms )




    start_ms = ChooseStartPositionMS( duration_ms, [], BOOKMARK_MODE_OFF, random_start_min_duration_s, max_play_s, rng = rng )

    if start_ms is None:

        return None


    return ( start_ms, None )


def ChooseStartPositionMS(
    duration_ms: int | None,
    bookmarks_ms: list[ int ],
    bookmark_mode: int,
    random_start_min_duration_s: int | None,
    max_play_s: int | None,
    rng: random.Random | None = None
) -> int | None:
    """
    Decides where a duration-having media should start in a slideshow. None means 'start at the beginning as normal'.

    Priority: bookmarks (if the mode is on and the file has valid ones) > random start (if the file is long enough) > beginning.
    """

    if rng is None:

        rng = random


    if duration_ms is None or duration_ms <= 0:

        return None


    if bookmark_mode in ( BOOKMARK_MODE_FIRST, BOOKMARK_MODE_RANDOM ):

        valid_bookmarks = [ ms for ms in bookmarks_ms if 0 <= ms < duration_ms ]

        if len( valid_bookmarks ) > 0:

            if bookmark_mode == BOOKMARK_MODE_FIRST:

                return min( valid_bookmarks )

            else:

                return rng.choice( valid_bookmarks )




    if random_start_min_duration_s is not None and duration_ms >= random_start_min_duration_s * 1000:

        if max_play_s is not None:

            # make sure the whole capped window fits before the end
            latest_start_ms = duration_ms - ( max_play_s * 1000 )

        else:

            latest_start_ms = duration_ms * RANDOM_START_NO_CAP_MAX_FRACTION


        if latest_start_ms <= 0:

            return None


        return int( rng.uniform( 0, latest_start_ms ) )


    return None


def GetFrameIndexForTimestamp( timestamp_ms: int, num_frames: int, duration_ms: int | None, frame_durations_ms: list[ int ] | None = None ) -> int:

    if num_frames is None or num_frames <= 1:

        return 0


    if frame_durations_ms is not None and len( frame_durations_ms ) > 0:

        running_ms = 0

        for ( index, frame_duration_ms ) in enumerate( frame_durations_ms ):

            if running_ms + frame_duration_ms > timestamp_ms:

                return min( index, num_frames - 1 )


            running_ms += frame_duration_ms


        return num_frames - 1


    if duration_ms is None or duration_ms <= 0:

        return 0


    index = int( num_frames * ( timestamp_ms / duration_ms ) )

    return max( 0, min( index, num_frames - 1 ) )

