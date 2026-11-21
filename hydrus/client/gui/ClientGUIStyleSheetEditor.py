"""
Personal edit: a colour editor for QSS stylesheets.

Opens a stylesheet, lists every colour in it (plus hydrus's own custom-widget colours from default_hydrus.qss),
lets you change them with a colour picker, by colour (everywhere it is used) or by element (one place only),
previews the result live on the whole program, and saves it as a new stylesheet in db_dir/static/qss.
"""

import collections
import os
import re

from qtpy import QtCore as QC
from qtpy import QtGui as QG
from qtpy import QtWidgets as QW

from hydrus.core import HydrusData
from hydrus.core import HydrusExceptions
from hydrus.core import HydrusStaticDir

from hydrus.client import ClientGlobals as CG
from hydrus.client.gui import ClientGUIDialogsMessage
from hydrus.client.gui import ClientGUIDialogsQuick
from hydrus.client.gui import ClientGUIStyle

# ----------------------------------------------------------------------
# parsing

SOURCE_STYLESHEET = 'stylesheet'
SOURCE_HYDRUS_DEFAULT = 'hydrus default'

EDITOR_BLOCK_COMMENT = '/* added by the stylesheet colour editor: hydrus custom widget colours */'

_COMMENT_RE = re.compile( r'/\*.*?\*/', re.DOTALL )
_URL_RE = re.compile( r'url\([^)]*\)', re.IGNORECASE )
_COLOUR_TOKEN_RE = re.compile(
    r'#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])'
    r'|\b(?:rgba?|hsla?|hsva?)\s*\([^)]*\)'
    r'|\bpalette\s*\(\s*[a-zA-Z-]+\s*\)'
    r'|\b[a-zA-Z]+\b',
    re.IGNORECASE
)

# words that are valid QColor names but are never meant as colours in a stylesheet value
_NOT_COLOUR_WORDS = { 'none', 'qlineargradient', 'qradialgradient', 'qconicalgradient', 'stop', 'spread', 'pad', 'repeat', 'reflect', 'url', 'solid', 'dashed', 'dotted', 'double', 'groove', 'ridge', 'inset', 'outset', 'hidden' }

PALETTE_ROLES = {
    'window' : QG.QPalette.ColorRole.Window,
    'windowtext' : QG.QPalette.ColorRole.WindowText,
    'base' : QG.QPalette.ColorRole.Base,
    'alternate-base' : QG.QPalette.ColorRole.AlternateBase,
    'tooltipbase' : QG.QPalette.ColorRole.ToolTipBase,
    'tooltiptext' : QG.QPalette.ColorRole.ToolTipText,
    'text' : QG.QPalette.ColorRole.Text,
    'button' : QG.QPalette.ColorRole.Button,
    'buttontext' : QG.QPalette.ColorRole.ButtonText,
    'brighttext' : QG.QPalette.ColorRole.BrightText,
    'light' : QG.QPalette.ColorRole.Light,
    'midlight' : QG.QPalette.ColorRole.Midlight,
    'dark' : QG.QPalette.ColorRole.Dark,
    'mid' : QG.QPalette.ColorRole.Mid,
    'shadow' : QG.QPalette.ColorRole.Shadow,
    'highlight' : QG.QPalette.ColorRole.Highlight,
    'highlightedtext' : QG.QPalette.ColorRole.HighlightedText,
    'link' : QG.QPalette.ColorRole.Link,
    'linkvisited' : QG.QPalette.ColorRole.LinkVisited,
    'placeholder-text' : QG.QPalette.ColorRole.PlaceholderText,
}

ColourOccurrence = collections.namedtuple( 'ColourOccurrence', [ 'start', 'end', 'token', 'selector', 'property', 'source', 'index_in_rule' ] )

def _PropertyCanHoldColour( prop: str ) -> bool:

    prop = prop.lower()

    return (
        'color' in prop
        or 'colour' in prop
        or 'background' in prop
        or prop.startswith( 'border' )
        or prop.startswith( 'outline' )
        or prop.startswith( 'qproperty-' )
        or prop.startswith( 'selection-' )
    )


def _CleanSelector( selector: str ) -> str:

    return ' '.join( selector.split() )


def _TokenIsColour( token: str ) -> bool:

    lower = token.lower()

    if lower.startswith( '#' ):

        return True


    if re.match( r'(rgba?|hsla?|hsva?|palette)\s*\(', lower ):

        return True


    if lower in _NOT_COLOUR_WORDS:

        return False


    return QG.QColor.isValidColorName( lower )


def ParseColourOccurrences( text: str, source = SOURCE_STYLESHEET ) -> list:
    """
    Finds every colour in a QSS document, with its exact position, the selector and property it belongs to.
    Comments and url(...) contents are ignored.
    """

    masked = _COMMENT_RE.sub( lambda m: re.sub( r'[^\n]', ' ', m.group() ), text )

    results = []

    position = 0

    selector_counts = collections.Counter()

    while True:

        open_brace = masked.find( '{', position )

        if open_brace == -1:

            break


        close_brace = masked.find( '}', open_brace )

        if close_brace == -1:

            break


        selector = _CleanSelector( masked[ position : open_brace ] )

        body_start = open_brace + 1

        declaration_start = body_start

        for declaration_end in [ m.start() for m in re.finditer( ';', masked[ body_start : close_brace ] ) ] + [ close_brace - body_start ]:

            declaration_end += body_start

            declaration = masked[ declaration_start : declaration_end ]

            colon = declaration.find( ':' )

            if colon != -1:

                prop = declaration[ : colon ].strip()

                if _PropertyCanHoldColour( prop ):

                    value_start = declaration_start + colon + 1
                    value_text = masked[ value_start : declaration_end ]

                    # blank out url(...) so file names like 'red.svg' are not read as colours
                    value_text = _URL_RE.sub( lambda m: ' ' * len( m.group() ), value_text )

                    for m in _COLOUR_TOKEN_RE.finditer( value_text ):

                        token = m.group()

                        if _TokenIsColour( token ):

                            key = ( selector, prop.lower() )

                            results.append( ColourOccurrence( value_start + m.start(), value_start + m.end(), text[ value_start + m.start() : value_start + m.end() ], selector, prop.lower(), source, selector_counts[ key ] ) )

                            selector_counts[ key ] += 1





            declaration_start = declaration_end + 1


        position = close_brace + 1


    return results


def _Clamp( v, lo = 0, hi = 255 ):

    return max( lo, min( hi, int( round( v ) ) ) )


def TokenToQColor( token: str ) -> QG.QColor | None:

    lower = token.strip().lower()

    m = re.match( r'palette\s*\(\s*([a-z-]+)\s*\)', lower )

    if m is not None:

        role = PALETTE_ROLES.get( m.group( 1 ), None )

        app = QW.QApplication.instance()

        if role is None or app is None:

            return None


        return QG.QColor( app.palette().color( role ) )


    m = re.match( r'(rgba?|hsla?|hsva?)\s*\(([^)]*)\)', lower )

    if m is not None:

        ( func, args ) = m.groups()

        parts = [ p.strip() for p in re.split( r'[,\s/]+', args.strip() ) if p.strip() != '' ]

        def to_number( p, scale_pct ):

            if p.endswith( '%' ):

                return float( p[ : -1 ] ) * scale_pct / 100


            return float( p )


        try:

            if func.startswith( 'rgb' ):

                ( r, g, b ) = ( to_number( p, 255 ) for p in parts[ : 3 ] )

                colour = QG.QColor( _Clamp( r ), _Clamp( g ), _Clamp( b ) )

            elif func.startswith( 'hsl' ):

                h = to_number( parts[0], 360 )
                ( s, l ) = ( to_number( p, 255 ) for p in parts[ 1 : 3 ] )

                colour = QG.QColor.fromHsl( _Clamp( h, 0, 359 ), _Clamp( s ), _Clamp( l ) )

            else:

                h = to_number( parts[0], 360 )
                ( s, v ) = ( to_number( p, 255 ) for p in parts[ 1 : 3 ] )

                colour = QG.QColor.fromHsv( _Clamp( h, 0, 359 ), _Clamp( s ), _Clamp( v ) )


            if len( parts ) >= 4:

                a_text = parts[3]

                if a_text.endswith( '%' ):

                    a = float( a_text[ : -1 ] ) * 255 / 100

                else:

                    a = float( a_text )

                    if '.' in a_text and a <= 1:

                        a = a * 255



                colour.setAlpha( _Clamp( a ) )


            return colour

        except Exception as e:

            return None



    colour = QG.QColor( lower )

    if not colour.isValid():

        return None


    return colour


def ColourGroupKey( token: str ) -> str:

    lower = ' '.join( token.lower().split() )

    if lower.startswith( 'palette' ):

        return lower.replace( ' ', '' )


    colour = TokenToQColor( token )

    if colour is None:

        return lower


    return colour.name( QG.QColor.NameFormat.HexArgb )


def QColorToToken( colour: QG.QColor ) -> str:

    if colour.alpha() == 255:

        return colour.name( QG.QColor.NameFormat.HexRgb )


    return f'rgba({colour.red()}, {colour.green()}, {colour.blue()}, {colour.alpha()})'


def GetEffectiveHydrusDefaultOccurrences( stylesheet_text: str, hydrus_default_text: str ) -> list:
    """
    The default_hydrus.qss colours that the stylesheet does not already set for the same selector and property.
    """

    overridden = { ( o.selector, o.property ) for o in ParseColourOccurrences( stylesheet_text ) }

    return [ o for o in ParseColourOccurrences( hydrus_default_text, source = SOURCE_HYDRUS_DEFAULT ) if ( o.selector, o.property ) not in overridden ]


def ApplyColourChanges( stylesheet_text: str, hydrus_default_text: str, changes: list ) -> str:
    """
    changes is a list of ( ColourOccurrence, new_token ).
    Stylesheet occurrences are replaced in place. Hydrus default occurrences are written as override rules at the end.
    """

    stylesheet_changes = sorted( [ ( o, t ) for ( o, t ) in changes if o.source == SOURCE_STYLESHEET ], key = lambda c: c[0].start, reverse = True )
    hydrus_changes = [ ( o, t ) for ( o, t ) in changes if o.source == SOURCE_HYDRUS_DEFAULT ]

    text = stylesheet_text

    for ( o, new_token ) in stylesheet_changes:

        # some themes write 'solid#6c7086'; keep the new token separate from the word before it
        if o.start > 0 and ( text[ o.start - 1 ].isalnum() or text[ o.start - 1 ] == ')' ):

            new_token = ' ' + new_token


        text = text[ : o.start ] + new_token + text[ o.end : ]


    if len( hydrus_changes ) > 0:

        # rewrite each touched declaration with its whole value, so multi-colour values (rare in default_hydrus) stay intact
        by_declaration = collections.defaultdict( list )

        for ( o, new_token ) in hydrus_changes:

            by_declaration[ ( o.selector, o.property ) ].append( ( o, new_token ) )


        all_default_occurrences = ParseColourOccurrences( hydrus_default_text, source = SOURCE_HYDRUS_DEFAULT )

        by_selector = collections.defaultdict( list )

        for ( ( selector, prop ), these_changes ) in by_declaration.items():

            original = [ o for o in all_default_occurrences if o.selector == selector and o.property == prop ]

            changes_by_index = { o.index_in_rule : t for ( o, t ) in these_changes }

            value = ' '.join( changes_by_index.get( o.index_in_rule, o.token ) for o in original )

            by_selector[ selector ].append( ( prop, value ) )


        blocks = []

        for ( selector, declarations ) in by_selector.items():

            lines = '\n'.join( f'    {prop}: {value};' for ( prop, value ) in declarations )

            blocks.append( f'{selector}\n{{\n{lines}\n}}' )


        if EDITOR_BLOCK_COMMENT not in text:

            text = text.rstrip() + '\n\n' + EDITOR_BLOCK_COMMENT + '\n'


        text = text.rstrip() + '\n\n' + '\n\n'.join( blocks ) + '\n'


    return text


def SanitiseFilename( name: str ) -> str:

    name = re.sub( r'[\\/:*?"<>|]', '', name ).strip().strip( '.' )

    if name.lower().endswith( '.qss' ) or name.lower().endswith( '.css' ):

        name = name[ : -4 ]


    return name.strip()


def GetUserQSSDir() -> str:

    return os.path.join( CG.client_controller.GetDBDir(), 'static', 'qss' )


# ----------------------------------------------------------------------
# ui

def _MakeSwatch( colour: QG.QColor | None, size = 16 ) -> QG.QIcon:

    pixmap = QG.QPixmap( size, size )

    pixmap.fill( QG.QColor( 255, 255, 255 ) )

    painter = QG.QPainter( pixmap )

    # little checkerboard so transparent colours are visible
    painter.fillRect( 0, 0, size // 2, size // 2, QG.QColor( 200, 200, 200 ) )
    painter.fillRect( size // 2, size // 2, size // 2, size // 2, QG.QColor( 200, 200, 200 ) )

    if colour is not None:

        painter.fillRect( 0, 0, size, size, colour )


    painter.setPen( QG.QColor( 0, 0, 0 ) )
    painter.drawRect( 0, 0, size - 1, size - 1 )

    painter.end()

    return QG.QIcon( pixmap )


class StyleSheetColourEditor( QW.QDialog ):

    def __init__( self, parent, starting_filename: str | None ):

        super().__init__( parent )

        self.setWindowTitle( 'edit stylesheet colours' )

        self.setWindowFlag( QC.Qt.WindowType.WindowMaximizeButtonHint, True )

        self._saved_filename = None

        self._hydrus_default_text = ClientGUIStyle.DEFAULT_HYDRUS_STYLESHEET
        self._hydrus_default_text_for_this_base = self._hydrus_default_text
        self._restore_callable = None

        self._base_filename = None
        self._base_path = None
        self._original_text = ''
        self._text = ''
        self._history = []

        self._stylesheet_occurrences = []
        self._hydrus_occurrences = []

        self._preview_timer = QC.QTimer( self )
        self._preview_timer.setSingleShot( True )
        self._preview_timer.setInterval( 350 )
        self._preview_timer.timeout.connect( self._ApplyPreview )

        #

        help_text = 'Double-click a colour to change it. "By colour" changes every place that colour is used. "By element" changes one place only. The whole program previews your changes live. Nothing is written until you hit "save as". Colours ticked as overrides in options->colours beat anything here.'

        help_label = QW.QLabel( help_text, self )
        help_label.setWordWrap( True )

        self._base_choice = QW.QComboBox( self )

        names = ClientGUIStyle.GetAvailableStyleSheets()

        for name in names:

            self._base_choice.addItem( name, name )


        if starting_filename is None or starting_filename not in names:

            starting_filename = 'default_hydrus.qss' if 'default_hydrus.qss' in names else ( names[0] if len( names ) > 0 else None )


        self._filter = QW.QLineEdit( self )
        self._filter.setPlaceholderText( 'filter by widget, property or colour, e.g. "menu", "tab", "background", "#1e1e1e"' )
        self._filter.textChanged.connect( self._ApplyFilter )

        self._tabs = QW.QTabWidget( self )

        self._colour_tree = QW.QTreeWidget( self._tabs )
        self._colour_tree.setHeaderLabels( [ 'colour', 'uses', 'used by' ] )
        self._colour_tree.setRootIsDecorated( False )
        self._colour_tree.setUniformRowHeights( True )
        self._colour_tree.itemDoubleClicked.connect( self._EditColourItem )

        self._element_tree = QW.QTreeWidget( self._tabs )
        self._element_tree.setHeaderLabels( [ 'widget / property', 'colour', 'from' ] )
        self._element_tree.setUniformRowHeights( True )
        self._element_tree.itemDoubleClicked.connect( self._EditElementItem )

        text_panel = QW.QWidget( self._tabs )

        self._text_edit = QW.QPlainTextEdit( text_panel )
        self._text_edit.setLineWrapMode( QW.QPlainTextEdit.LineWrapMode.NoWrap )

        font = QG.QFontDatabase.systemFont( QG.QFontDatabase.SystemFont.FixedFont )

        self._text_edit.setFont( font )

        self._apply_text_button = QW.QPushButton( 'apply text edits', text_panel )
        self._apply_text_button.clicked.connect( self._ApplyTextEdits )

        text_vbox = QW.QVBoxLayout( text_panel )
        text_vbox.setContentsMargins( 0, 0, 0, 0 )
        text_vbox.addWidget( self._text_edit )
        text_vbox.addWidget( self._apply_text_button, 0, QC.Qt.AlignmentFlag.AlignRight )

        self._tabs.addTab( self._colour_tree, 'by colour' )
        self._tabs.addTab( self._element_tree, 'by element' )
        self._tabs.addTab( text_panel, 'stylesheet text' )

        self._change_button = QW.QPushButton( 'change colour' + '…', self )
        self._change_button.clicked.connect( self._ChangeSelected )

        self._live_preview = QW.QCheckBox( 'live preview', self )
        self._live_preview.setChecked( True )
        self._live_preview.toggled.connect( self._LivePreviewToggled )

        self._undo_button = QW.QPushButton( 'undo', self )
        self._undo_button.clicked.connect( self._Undo )

        self._reset_button = QW.QPushButton( 'reset to base', self )
        self._reset_button.clicked.connect( self._Reset )

        self._save_button = QW.QPushButton( 'save as' + '…', self )
        self._save_button.setObjectName( 'HydrusAccept' )
        self._save_button.clicked.connect( self._SaveAs )

        self._close_button = QW.QPushButton( 'close without saving', self )
        self._close_button.setObjectName( 'HydrusCancel' )
        self._close_button.clicked.connect( self.reject )

        self._status = QW.QLabel( self )

        #

        top = QW.QHBoxLayout()
        top.addWidget( QW.QLabel( 'base stylesheet:', self ) )
        top.addWidget( self._base_choice, 1 )

        buttons = QW.QHBoxLayout()
        buttons.addWidget( self._change_button )
        buttons.addWidget( self._undo_button )
        buttons.addWidget( self._reset_button )
        buttons.addWidget( self._live_preview )
        buttons.addStretch( 1 )
        buttons.addWidget( self._save_button )
        buttons.addWidget( self._close_button )

        vbox = QW.QVBoxLayout( self )
        vbox.addWidget( help_label )
        vbox.addLayout( top )
        vbox.addWidget( self._filter )
        vbox.addWidget( self._tabs, 1 )
        vbox.addWidget( self._status )
        vbox.addLayout( buttons )

        self.resize( 980, 720 )

        #

        if starting_filename is not None:

            self._base_choice.setCurrentIndex( self._base_choice.findData( starting_filename ) )

            self._LoadBase( starting_filename )


        self._base_choice.currentIndexChanged.connect( self._BaseChanged )


    # --- loading

    def _LoadBase( self, filename: str ):

        path = HydrusStaticDir.GetStaticPath( os.path.join( 'qss', filename ) )

        try:

            with open( path, 'r', encoding = 'utf-8' ) as f:

                text = f.read()


        except Exception as e:

            ClientGUIDialogsMessage.ShowWarning( self, f'Could not read that stylesheet: {e}' )

            return


        # default_hydrus.qss is already prepended to everything, so do not list its colours twice
        if filename == 'default_hydrus.qss':

            self._hydrus_default_text_for_this_base = ''

        else:

            self._hydrus_default_text_for_this_base = self._hydrus_default_text


        self._base_filename = filename
        self._base_path = path
        self._original_text = text
        self._history = []

        self._SetText( text, record_history = False )


    def _BaseChanged( self ):

        filename = self._base_choice.currentData()

        if filename == self._base_filename:

            return


        if self._text != self._original_text:

            result = ClientGUIDialogsQuick.GetYesNo( self, 'Switching the base stylesheet throws away your unsaved changes. Continue?' )

            if result != QW.QDialog.DialogCode.Accepted:

                self._base_choice.blockSignals( True )
                self._base_choice.setCurrentIndex( self._base_choice.findData( self._base_filename ) )
                self._base_choice.blockSignals( False )

                return



        self._LoadBase( filename )


    # --- state

    def _SetText( self, text: str, record_history = True ):

        if record_history and text != self._text:

            self._history.append( self._text )


        self._text = text

        self._stylesheet_occurrences = ParseColourOccurrences( self._text )
        self._hydrus_occurrences = GetEffectiveHydrusDefaultOccurrences( self._text, self._hydrus_default_text_for_this_base )

        if self._text_edit.toPlainText() != self._text:

            self._text_edit.setPlainText( self._text )


        self._PopulateTrees()

        self._undo_button.setEnabled( len( self._history ) > 0 )

        changed = self._text != self._original_text

        self._status.setText( f'{len( self._stylesheet_occurrences ) + len( self._hydrus_occurrences )} colour uses, {self._colour_tree.topLevelItemCount()} distinct colours' + ( ' — unsaved changes' if changed else '' ) )

        self._SchedulePreview()


    def _AllOccurrences( self ):

        return self._stylesheet_occurrences + self._hydrus_occurrences


    def _PopulateTrees( self ):

        colour_scroll = self._colour_tree.verticalScrollBar().value()
        element_scroll = self._element_tree.verticalScrollBar().value()

        expanded = set()

        for i in range( self._element_tree.topLevelItemCount() ):

            item = self._element_tree.topLevelItem( i )

            if item.isExpanded():

                expanded.add( item.text( 0 ) )



        # by colour

        groups = collections.OrderedDict()

        for o in self._AllOccurrences():

            groups.setdefault( ColourGroupKey( o.token ), [] ).append( o )


        self._colour_tree.clear()

        for ( key, occurrences ) in sorted( groups.items(), key = lambda kv: -len( kv[1] ) ):

            colour = TokenToQColor( occurrences[0].token )

            pretty_value = key if key.startswith( 'palette' ) else QColorToToken( colour ) if colour is not None else key

            used_by = sorted( { f'{o.selector} › {o.property}' for o in occurrences } )

            used_by_text = '; '.join( used_by[ : 4 ] ) + ( f'; +{len( used_by ) - 4} more' if len( used_by ) > 4 else '' )

            item = QW.QTreeWidgetItem( [ pretty_value, str( len( occurrences ) ), used_by_text ] )

            item.setIcon( 0, _MakeSwatch( colour ) )
            item.setToolTip( 2, '\n'.join( used_by ) )
            item.setData( 0, QC.Qt.ItemDataRole.UserRole, occurrences )
            item.setData( 1, QC.Qt.ItemDataRole.UserRole, ' '.join( [ pretty_value, key ] + used_by ).lower() )

            self._colour_tree.addTopLevelItem( item )


        # by element

        self._element_tree.clear()

        by_selector = collections.OrderedDict()

        for o in self._AllOccurrences():

            by_selector.setdefault( o.selector, [] ).append( o )


        for ( selector, occurrences ) in by_selector.items():

            parent = QW.QTreeWidgetItem( [ selector, '', '' ] )

            parent.setToolTip( 0, selector )

            search_text = [ selector ]

            for o in occurrences:

                colour = TokenToQColor( o.token )

                child = QW.QTreeWidgetItem( [ o.property, o.token, 'hydrus default' if o.source == SOURCE_HYDRUS_DEFAULT else '' ] )

                child.setIcon( 1, _MakeSwatch( colour ) )
                child.setData( 0, QC.Qt.ItemDataRole.UserRole, o )

                parent.addChild( child )

                search_text.extend( [ o.property, o.token, ColourGroupKey( o.token ) ] )


            parent.setData( 1, QC.Qt.ItemDataRole.UserRole, ' '.join( search_text ).lower() )

            self._element_tree.addTopLevelItem( parent )

            if selector in expanded:

                parent.setExpanded( True )



        for tree in ( self._colour_tree, self._element_tree ):

            tree.resizeColumnToContents( 0 )
            tree.resizeColumnToContents( 1 )

            # long selectors would push the colours off screen; they are still in the tooltip
            tree.setColumnWidth( 0, min( tree.columnWidth( 0 ), 460 ) )

            # collapsed groups do not count towards the content width, so make sure colours like 'rgba(255, 255, 255, 128)' fit
            tree.setColumnWidth( 1, max( tree.columnWidth( 1 ), 190 ) )


        self._ApplyFilter()

        self._colour_tree.verticalScrollBar().setValue( colour_scroll )
        self._element_tree.verticalScrollBar().setValue( element_scroll )


    def _ApplyFilter( self ):

        needle = self._filter.text().strip().lower()

        for tree in ( self._colour_tree, self._element_tree ):

            for i in range( tree.topLevelItemCount() ):

                item = tree.topLevelItem( i )

                haystack = item.data( 1, QC.Qt.ItemDataRole.UserRole ) or ''

                item.setHidden( needle != '' and needle not in haystack )

                if tree is self._element_tree and needle != '' and needle not in item.text( 0 ).lower():

                    # when the match is on a property or colour, show the matching children

                    any_child = False

                    for c in range( item.childCount() ):

                        child = item.child( c )

                        child_match = needle in ' '.join( [ child.text( 0 ), child.text( 1 ), ColourGroupKey( child.text( 1 ) ) ] ).lower()

                        child.setHidden( not child_match )

                        any_child = any_child or child_match


                    if any_child:

                        item.setExpanded( True )


                else:

                    for c in range( item.childCount() ):

                        item.child( c ).setHidden( False )






    # --- editing

    def _PickColour( self, initial: QG.QColor | None, title: str ) -> QG.QColor | None:

        if initial is None:

            initial = QG.QColor( 128, 128, 128 )


        # preview inside the picker as you drag, without spamming the whole-app restyle
        colour = QW.QColorDialog.getColor( initial, self, title, QW.QColorDialog.ColorDialogOption.ShowAlphaChannel )

        if not colour.isValid():

            return None


        return colour


    def _ApplyChanges( self, changes ):

        if len( changes ) == 0:

            return


        new_text = ApplyColourChanges( self._text, self._hydrus_default_text_for_this_base, changes )

        self._SetText( new_text )


    def _EditColourItem( self, item, column = 0 ):

        occurrences = item.data( 0, QC.Qt.ItemDataRole.UserRole )

        if not occurrences:

            return


        colour = self._PickColour( TokenToQColor( occurrences[0].token ), f'change {item.text( 0 )} everywhere ({len( occurrences )} uses)' )

        if colour is None:

            return


        new_token = QColorToToken( colour )

        self._ApplyChanges( [ ( o, new_token ) for o in occurrences ] )


    def _EditElementItem( self, item, column = 0 ):

        o = item.data( 0, QC.Qt.ItemDataRole.UserRole )

        if o is None:

            item.setExpanded( not item.isExpanded() )

            return


        colour = self._PickColour( TokenToQColor( o.token ), f'change {o.selector} › {o.property}' )

        if colour is None:

            return


        self._ApplyChanges( [ ( o, QColorToToken( colour ) ) ] )


    def _ChangeSelected( self ):

        tree = self._colour_tree if self._tabs.currentIndex() == 0 else self._element_tree

        items = tree.selectedItems()

        if len( items ) == 0:

            ClientGUIDialogsMessage.ShowInformation( self, 'Select a colour or an element property first.' )

            return


        if tree is self._colour_tree:

            self._EditColourItem( items[0] )

        else:

            self._EditElementItem( items[0] )



    def _ApplyTextEdits( self ):

        self._SetText( self._text_edit.toPlainText() )


    def _Undo( self ):

        if len( self._history ) == 0:

            return


        text = self._history.pop()

        self._SetText( text, record_history = False )


    def _Reset( self ):

        if self._text == self._original_text:

            return


        self._SetText( self._original_text )


    # --- preview

    def _LivePreviewToggled( self, checked ):

        if checked:

            self._SchedulePreview()

        else:

            self._RestoreProgramStyle()



    def _SchedulePreview( self ):

        if self._live_preview.isChecked():

            self._preview_timer.start()



    def _ApplyPreview( self ):

        if not self._live_preview.isChecked() or self._base_path is None:

            return


        try:

            qss = ClientGUIStyle.ConvertRelativeQSSPathsToAbsolute( self._text, self._base_path )

            ClientGUIStyle.SetStyleSheet( qss, None )

        except Exception as e:

            HydrusData.PrintException( e )



    def _RestoreProgramStyle( self ):

        # put back whatever the options page currently has selected
        if self._restore_callable is not None:

            self._restore_callable()



    def SetRestoreCallable( self, func ):

        self._restore_callable = func


    # --- saving

    def _SaveAs( self ):

        base_stem = os.path.splitext( self._base_filename or 'custom' )[0]

        default_name = base_stem if base_stem.endswith( '(custom)' ) or self._BaseIsUserFile() else f'{base_stem} (custom)'

        try:

            name = ClientGUIDialogsQuick.EnterText( self, 'Name for your stylesheet. It will be saved in your db folder under static/qss and selected in the style options.', default = default_name, min_char_width = 40 )

        except HydrusExceptions.CancelledException:

            return


        name = SanitiseFilename( name )

        if name == '':

            ClientGUIDialogsMessage.ShowWarning( self, 'That name has no usable characters!' )

            return


        filename = name + '.qss'

        qss_dir = GetUserQSSDir()

        path = os.path.join( qss_dir, filename )

        if os.path.exists( path ):

            result = ClientGUIDialogsQuick.GetYesNo( self, f'"{filename}" already exists in your custom stylesheets. Overwrite it?' )

            if result != QW.QDialog.DialogCode.Accepted:

                return



        text = self._text

        if not self._BaseIsUserFile():

            # images in bundled themes live in the install folder, so point at them directly
            text = ClientGUIStyle.ConvertRelativeQSSPathsToAbsolute( text, self._base_path )


        header = f'/* made with the hydrus stylesheet colour editor, based on "{self._base_filename}" */\n\n'

        if not text.startswith( '/* made with the hydrus stylesheet colour editor' ):

            text = header + text


        try:

            os.makedirs( qss_dir, exist_ok = True )

            with open( path, 'w', encoding = 'utf-8' ) as f:

                f.write( text )


        except Exception as e:

            ClientGUIDialogsMessage.ShowCritical( self, 'Could not save!', f'Could not write "{path}": {e}' )

            return


        self._saved_filename = filename

        self._preview_timer.stop()

        self.accept()


    def _BaseIsUserFile( self ) -> bool:

        if self._base_path is None:

            return False


        try:

            return os.path.normcase( os.path.abspath( self._base_path ) ).startswith( os.path.normcase( os.path.abspath( GetUserQSSDir() ) ) )

        except Exception as e:

            return False



    def GetSavedFilename( self ) -> str | None:

        return self._saved_filename


    def reject( self ):

        if self._text != self._original_text:

            result = ClientGUIDialogsQuick.GetYesNo( self, 'Close without saving your colour changes?' )

            if result != QW.QDialog.DialogCode.Accepted:

                return



        self._preview_timer.stop()

        super().reject()


