"""
Personal edit: slideshow start points.

Pure helper logic (no Qt) for:
  - parsing/formatting video bookmarks stored in a file note
  - choosing where a video/animation should start during a slideshow
  - mapping a timestamp to a frame index for the native animation renderer

Bookmark note format is forgiving: timestamps separated by commas, semicolons, spaces or new lines.
Each timestamp can be "SS", "SS.sss", "M:SS", "MM:SS.sss" or "H:MM:SS(.sss)".
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


def ParseBookmarksMS( text: str | None ) -> list[ int ]:

    if text is None:

        return []


    results = set()

    for token in _TOKEN_SPLIT_RE.split( text ):

        ms = ParseTimestampMS( token )

        if ms is not None:

            results.add( ms )



    return sorted( results )


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


def AddBookmarkToText( text: str | None, new_ms: int, merge_within_ms: int = 500 ) -> str:
    """
    Returns the new note text with the bookmark added. Bookmarks are rewritten as a sorted, comma-separated list.
    A new bookmark within merge_within_ms of an existing one is treated as a duplicate.
    """

    bookmarks = ParseBookmarksMS( text )

    if not any( abs( existing - new_ms ) <= merge_within_ms for existing in bookmarks ):

        bookmarks.append( int( new_ms ) )


    bookmarks.sort()

    return ', '.join( FormatTimestampMS( ms ) for ms in bookmarks )


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

