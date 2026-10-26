from qtpy import QtWidgets as QW

from hydrus.core import HydrusTime

from hydrus.client import ClientApplicationCommand as CAC
from hydrus.client import ClientGlobals as CG
from hydrus.client import ClientSlideshowStartPoints
from hydrus.client.gui import ClientGUIMenus

def _AppendSlideshowStartPointsMenu( win: CAC.ApplicationCommandProcessorMixin, menu: QW.QMenu, slideshow_start_settings ):
    
    # personal edit: per-window clip length, random start length and bookmark mode
    
    ( play_length_s, random_start_min_s, bookmark_mode ) = slideshow_start_settings
    
    new_options = CG.client_controller.new_options
    
    def append_duration_choices( action, current_s, presets, none_label, none_description, custom_description, item_description_template ):
        
        ClientGUIMenus.AppendMenuCheckItem( menu, none_label, none_description, current_s is None, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( action, 0 ) )
        
        for preset_s in presets:
            
            pretty = ClientSlideshowStartPoints.FormatDurationS( preset_s )
            
            ClientGUIMenus.AppendMenuCheckItem( menu, pretty, item_description_template.format( pretty ), current_s == preset_s, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( action, preset_s ) )
            
        
        if current_s is not None and current_s not in presets:
            
            pretty = ClientSlideshowStartPoints.FormatDurationS( current_s )
            
            ClientGUIMenus.AppendMenuCheckItem( menu, f'custom: {pretty}', item_description_template.format( pretty ), True, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( action, current_s ) )
            
        
        ClientGUIMenus.AppendMenuItem( menu, 'custom' + '\u2026', custom_description, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( action, -1 ) )
        
    
    ClientGUIMenus.AppendMenuLabel( menu, 'clip length for bookmark/random starts:', no_copy = True )
    
    append_duration_choices(
        CAC.SIMPLE_SET_THISWINDOW_SLIDESHOW_START_PLAY_LENGTH,
        play_length_s,
        new_options.GetIntegerList( 'slideshow_start_play_length_presets' ),
        'no limit',
        'Videos that start at a bookmark or random point follow the normal slideshow rules.',
        'Enter a custom clip length for this window.',
        'Videos that start at a bookmark or random point move on after {}.'
    )
    
    ClientGUIMenus.AppendSeparator( menu )
    
    ClientGUIMenus.AppendMenuLabel( menu, 'random start for videos at least:', no_copy = True )
    
    append_duration_choices(
        CAC.SIMPLE_SET_THISWINDOW_SLIDESHOW_RANDOM_START_MIN_DURATION,
        random_start_min_s,
        new_options.GetIntegerList( 'slideshow_random_start_min_duration_presets' ),
        'off',
        'Videos without bookmarks always start at the beginning.',
        'Enter a custom minimum length for random starts in this window.',
        'Videos at least {} long start at a random point.'
    )
    
    ClientGUIMenus.AppendSeparator( menu )
    
    ClientGUIMenus.AppendMenuLabel( menu, 'bookmark start point:', no_copy = True )
    
    for ( mode, label, description ) in [
        ( ClientSlideshowStartPoints.BOOKMARK_MODE_OFF, 'do not use bookmarks', 'Ignore bookmarks in this window.' ),
        ( ClientSlideshowStartPoints.BOOKMARK_MODE_FIRST, 'start at the first bookmark', 'Videos with bookmarks start at their earliest one.' ),
        ( ClientSlideshowStartPoints.BOOKMARK_MODE_RANDOM, 'start at a random bookmark', 'Videos with bookmarks start at a random one.' )
    ]:
        
        ClientGUIMenus.AppendMenuCheckItem( menu, label, description, bookmark_mode == mode, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_SET_THISWINDOW_SLIDESHOW_BOOKMARK_START_MODE, mode ) )
        
    
    ClientGUIMenus.AppendSeparator( menu )
    
    ClientGUIMenus.AppendMenuItem( menu, 'bookmark current video position', 'Add the current playback position of this video/animation to its bookmarks note, for slideshow start points.', win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_BOOKMARK_CURRENT_MEDIA_POSITION ) )
    

def AppendSlideshowMenu( win: CAC.ApplicationCommandProcessorMixin, menu: QW.QMenu, slideshow_is_running: bool, do_submenu = True, slideshow_duration = None, slideshow_is_shuffling = False, slideshow_is_playing_once_through = False, slideshow_start_settings = None ):
    
    if slideshow_duration == 0.0:
        
        slideshow_duration = None
        
    
    slideshow_menu_label = 'slideshow running' if slideshow_is_running else 'start slideshow'
    
    if do_submenu:
        
        slideshow_menu = ClientGUIMenus.GenerateMenu( menu )
        
        ClientGUIMenus.AppendMenu( menu, slideshow_menu, slideshow_menu_label )
        
    else:
        
        slideshow_menu = menu
        
    
    slideshow_durations = CG.client_controller.new_options.GetSlideshowDurations()
    
    if slideshow_is_running:
        
        ClientGUIMenus.AppendMenuItem( slideshow_menu, 'stop' + ( '' if slideshow_duration is None else ( ' (' + HydrusTime.TimeDeltaToPrettyTimeDelta( slideshow_duration ) + ')' ) ), 'Stop the current slideshow.', win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_PAUSE_PLAY_SLIDESHOW ) )
        
    else:
        
        if slideshow_duration is not None:
            
            ClientGUIMenus.AppendMenuItem( slideshow_menu, 'resume at ' + HydrusTime.TimeDeltaToPrettyTimeDelta( slideshow_duration ), 'Resume at the previous slideshow period.', win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_PAUSE_PLAY_SLIDESHOW ) )
            
        
    
    ClientGUIMenus.AppendSeparator( slideshow_menu )
    
    for slideshow_duration in slideshow_durations:
        
        pretty_duration = HydrusTime.TimeDeltaToPrettyTimeDelta( slideshow_duration )
        
        ClientGUIMenus.AppendMenuItem( slideshow_menu, pretty_duration, f'Start a slideshow that changes media every {pretty_duration}.', win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_START_SLIDESHOW, slideshow_duration ) )
        
    
    ClientGUIMenus.AppendMenuItem( slideshow_menu, 'very fast', 'Start a very fast slideshow.', win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_START_SLIDESHOW, 0.08 ) )
    ClientGUIMenus.AppendMenuItem( slideshow_menu, 'custom interval', 'Start a slideshow with a custom interval.', win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_START_SLIDESHOW ) )
    
    ClientGUIMenus.AppendSeparator( slideshow_menu )
    
    initial_thiswindow_value = slideshow_is_shuffling
    initial_newoptions_value = CG.client_controller.new_options.GetBoolean( 'slideshows_progress_randomly' )
    
    ClientGUIMenus.AppendMenuCheckItem( slideshow_menu, 'shuffle this slideshow', 'Check this to progress randomly through the slideshow.', initial_thiswindow_value, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_FLIP_THISWINDOW_SLIDESHOW_SHUFFLE ) )
    ClientGUIMenus.AppendMenuCheckItem( slideshow_menu, 'all slideshows shuffle', 'Toggle whether new windows start with random slideshows on.', initial_newoptions_value, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_FLIP_GLOBAL_SLIDESHOW_SHUFFLE ) )
    
    ClientGUIMenus.AppendSeparator( slideshow_menu )
    
    ClientGUIMenus.AppendMenuCheckItem( slideshow_menu, 'this slideshow plays media once through', 'Override the \'always play media once through\' behaviour for this window only. New windows will still use the global option.', slideshow_is_playing_once_through, win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_FLIP_THISWINDOW_SLIDESHOW_ALWAYS_PLAY_DURATION_MEDIA_ONCE_THROUGH ) )
    ClientGUIMenus.AppendMenuCheckItem( slideshow_menu, 'always play media once through', 'Check this to always play the complete media duration at least once before moving on.', CG.client_controller.new_options.GetBoolean( 'slideshow_always_play_duration_media_once_through' ), win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_FLIP_GLOBAL_SLIDESHOW_ALWAYS_PLAY_DURATION_MEDIA_ONCE_THROUGH ) )
    
    # personal edit
    ClientGUIMenus.AppendSeparator( slideshow_menu )
    
    if slideshow_start_settings is None:
        
        ClientGUIMenus.AppendMenuItem( slideshow_menu, 'bookmark current video position', 'Add the current playback position of this video/animation to its bookmarks note, for slideshow start points.', win.ProcessApplicationCommand, CAC.ApplicationCommand.STATICCreateSimpleCommand( CAC.SIMPLE_BOOKMARK_CURRENT_MEDIA_POSITION ) )
        
    else:
        
        start_points_menu = ClientGUIMenus.GenerateMenu( slideshow_menu )
        
        _AppendSlideshowStartPointsMenu( win, start_points_menu, slideshow_start_settings )
        
        ClientGUIMenus.AppendMenu( slideshow_menu, start_points_menu, 'bookmark/random start points' )
        
    
