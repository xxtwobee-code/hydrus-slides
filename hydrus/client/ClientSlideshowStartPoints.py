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
"""

import random
import re

BOOKMARK_MODE_OFF = 0
BOOKMARK_MODE_FIRST = 1
BOOKMARK_MODE_RANDOM = 2

# if there is no max play time cap, do not pick a random start right at the very end of the file
RANDOM_START_NO_CAP_MAX_FRACTION = 0.9

_TOKEN_SPLIT_RE = re.compile( r'[,;\s]+' )
_JOINER_SPACE_RE = re.compile( r'\s*([+\-])\s*' ) # '3:10 + 45' -> '3:10+45'
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


def ParseBookmarks( text: str | None ) -> list[ tuple[ int, int | None ] ]:
    """
    Returns sorted ( start_ms, play_length_ms or None ) pairs. If the same start appears twice, the first one written wins.
    """

    if text is None:

        return []


    text = _JOINER_SPACE_RE.sub( r'\1', text )

    starts_to_lengths = {}

    for token in _TOKEN_SPLIT_RE.split( text ):

        bookmark = ParseBookmarkToken( token )

        if bookmark is not None:

            ( start_ms, length_ms ) = bookmark

            if start_ms not in starts_to_lengths:

                starts_to_lengths[ start_ms ] = length_ms




    return sorted( starts_to_lengths.items() )


def ParseBookmarksMS( text: str | None ) -> list[ int ]:

    return [ start_ms for ( start_ms, length_ms ) in ParseBookmarks( text ) ]


def FormatBookmark( start_ms: int, length_ms: int | None ) -> str:

    result = FormatTimestampMS( start_ms )

    if length_ms is not None:

        result += '+' + FormatTimestampMS( length_ms )


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
    """

    bookmarks = ParseBookmarks( text )

    if not any( abs( existing_ms - new_ms ) <= merge_within_ms for ( existing_ms, length_ms ) in bookmarks ):

        bookmarks.append( ( int( new_ms ), None ) )


    bookmarks.sort()

    return ', '.join( FormatBookmark( start_ms, length_ms ) for ( start_ms, length_ms ) in bookmarks )


def ChooseStartPoint(
    duration_ms: int | None,
    bookmarks: list,
    bookmark_mode: int,
    random_start_min_duration_s: int | None,
    max_play_s: int | None,
    rng: random.Random | None = None
) -> tuple[ int, int | None ] | None:
    """
    Like ChooseStartPositionMS, but bookmarks are ( start_ms, play_length_ms or None ) pairs (plain ints are fine too).
    Returns ( start_ms, play_length_ms from the chosen bookmark or None ), or None for 'start at the beginning as normal'.
    """

    if rng is None:

        rng = random


    if duration_ms is None or duration_ms <= 0:

        return None


    normalised = [ b if isinstance( b, tuple ) else ( b, None ) for b in bookmarks ]

    if bookmark_mode in ( BOOKMARK_MODE_FIRST, BOOKMARK_MODE_RANDOM ):

        valid_bookmarks = [ b for b in normalised if 0 <= b[0] < duration_ms ]

        if len( valid_bookmarks ) > 0:

            if bookmark_mode == BOOKMARK_MODE_FIRST:

                return min( valid_bookmarks, key = lambda b: b[0] )

            else:

                return rng.choice( valid_bookmarks )




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

