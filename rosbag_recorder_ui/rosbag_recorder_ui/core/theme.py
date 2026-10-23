"""
The single source of truth for how the dashboard looks.
property that the stylesheet below turns into a colour, 
so a theme change is one edit in one file.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """
    Greys carry the layout;

      accent (cyan)  - what you picked and what you can press
      success (green)- a check that passed, a bag that closed cleanly
      warning (amber)- look at this before it becomes a problem
      danger (red)   - live recording, and anything that lost data

    Everything else is one hue of grey. Nothing is coloured for decoration.
    """

    # Surfaces, as an elevation ladder rather than arbitrary greys:
    # sunken (sidebar, log, inputs) < panel (docked panes) < base (page) <
    # surface (cards) < raised (controls) < hover < active.
    #
    # The steps are deliberately wide. An earlier version used ~4% lightness
    # between planes, which a pixel probe could tell apart and a human sitting
    # at the screen could not. Roughly 5% lightness per step is the point where
    # the hierarchy actually reads on a normal monitor in a lit room.
    #
    # The greys are a low-saturation gunmetal (hue ~205, ~20% saturation)
    # rather than the heavily blue slate they used to be. Draining the blue out
    # of the furniture is what lets a single cyan accent read as 'colour' at
    # all; against blue-grey it just looked like more of the same.
    bg_sunken: str = '#060a0c'
    bg_panel: str = '#0f1418'
    bg_base: str = '#192025'
    bg_surface: str = '#252e35'
    bg_raised: str = '#313d45'
    bg_hover: str = '#3d4a54'
    bg_active: str = '#495763'

    border: str = '#2b353d'
    border_strong: str = '#404e59'
    border_focus: str = '#2bb7c6'

    text: str = '#e7ebef'
    text_muted: str = '#92a0aa'
    text_dim: str = '#72808b'
    text_inverse: str = '#060a0c'

    # Each hue carries four tokens: the colour itself, a hover step, a dim
    # tint for filled backgrounds, and the ink to write on top of the solid
    # fill. Solid colour always takes dark ink - white on cyan is 2.4:1 and
    # unreadable, dark on cyan is 7.6:1.
    accent: str = '#2bb7c6'
    accent_hover: str = '#4ccedb'
    accent_dim: str = '#142e31'
    on_accent: str = '#092225'

    success: str = '#56c271'
    success_hover: str = '#6bcf83'
    success_dim: str = '#14311b'
    on_success: str = '#092510'

    warning: str = '#e0a032'
    warning_hover: str = '#eeb352'
    warning_dim: str = '#312614'
    on_warning: str = '#251b09'

    danger: str = '#ff5b57'
    danger_hover: str = '#ff7671'
    danger_dim: str = '#3a1715'
    on_danger: str = '#250a09'

    # Recording is the same red as danger, on purpose. Red means exactly one
    # thing here - 'this is live, or this lost you data' - and two subtly
    # different reds for those two ideas taught the operator nothing.
    recording: str = '#ff5b57'
    recording_dim: str = '#3a1715'

    info: str = '#2bb7c6'
    neutral: str = '#7b8993'

    # Semantic colours for the topic table. Cyan is 'chosen', red is 'live or
    # losing data', amber is 'was fine, now is not', grey is 'not involved'.
    topic_recording: str = '#ff5b57'
    topic_selected: str = '#2bb7c6'
    topic_excluded: str = '#92a0aa'
    topic_failed: str = '#ff5b57'
    topic_lost: str = '#e0a032'
    topic_unselected: str = '#72808b'

    def state_color(self, key):
        """Colour for a recorder or topic state name."""
        return {
            'idle': self.neutral,
            'preparing': self.warning,
            'recording': self.recording,
            'stopping': self.warning,
            'error': self.danger,
            'ok': self.success,
            'success': self.success,
            'warning': self.warning,
            'danger': self.danger,
            'info': self.info,
            'accent': self.accent,
            'muted': self.text_muted,
        }.get(key, self.neutral)

    def ink_for(self, key):
        """Readable ink to place on top of a solid fill of *key*."""
        return {
            'accent': self.on_accent,
            'success': self.on_success,
            'warning': self.on_warning,
            'danger': self.on_danger,
            'recording': self.on_danger,
            'error': self.on_danger,
        }.get(key, self.text)


PALETTE = Palette()

# Spacing scale. Every margin and gap in the app is one of these.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 14
SPACE_LG = 20
SPACE_XL = 28

RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12

FONT_STACK = '"Inter", "Ubuntu", "Cantarell", "Noto Sans", sans-serif'
MONO_STACK = '"JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono", monospace'


def stylesheet(palette=PALETTE, assets=None):
    """
    Build the application-wide QSS from the palette tokens.

    *assets* maps a few names ('check', 'chevron_down', 'search') to SVG files
    on disk; QSS can only reference images by url(), never inline. When an
    asset is missing the rule is simply dropped, so the app still styles
    correctly, just without that one glyph.
    """
    p = palette
    assets = assets or {}
    check_image = (f'image: url({assets["check"]});' if 'check' in assets else '')
    chevron_image = (f'image: url({assets["chevron_down"]}); width: 12px; height: 12px;'
                     if 'chevron_down' in assets else '')
    search_image = (f'background-image: url({assets["search"]});'
                    'background-repeat: no-repeat;'
                    'background-position: left 10px center;'
                    if 'search' in assets else '')
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {p.text};
    outline: none;
}}

QWidget#Root, QMainWindow {{
    background: {p.bg_base};
}}

QToolTip {{
    background: {p.bg_raised};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_SM}px;
    padding: 6px 8px;
}}

/* ---------------------------------------------------------------- cards */

QFrame#Card {{
    background: {p.bg_surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_LG}px;
}}
QFrame#Card[emphasis="true"] {{
    border: 1px solid {p.border_strong};
}}
QFrame#Card[tone="recording"] {{
    background: {p.recording_dim};
    border: 1px solid {p.recording};
}}
QFrame#Card[tone="danger"] {{
    background: {p.danger_dim};
    border: 1px solid {p.danger};
}}
QFrame#Card[tone="warning"] {{
    background: {p.warning_dim};
    border: 1px solid {p.warning};
}}
QFrame#Card[tone="success"] {{
    background: {p.success_dim};
    border: 1px solid {p.success};
}}
/* A card that sits directly on a docked pane. The pane already supplies the
   surface, so drawing a second one on top just muddies the hierarchy. */
QFrame#Card[tone="flush"] {{
    background: transparent;
    border: none;
}}

/* Docked panes. A pane that is attached to an edge sits on its own plane and
   is separated by a hairline, so the eye reads it as furniture rather than as
   more page content. */

QWidget#SidePanel {{
    background: {p.bg_panel};
    border-left: 1px solid {p.border};
}}
QWidget#BottomPanel {{
    background: {p.bg_panel};
    border-top: 1px solid {p.border};
}}

QFrame#Divider {{
    background: {p.border};
    max-height: 1px;
    border: none;
}}
QFrame#VDivider {{
    background: {p.border};
    max-width: 1px;
    border: none;
}}

/* ------------------------------------------------------------ typography */

QLabel#PageTitle    {{ font-size: 22px; font-weight: 600; }}
QLabel#PageSubtitle {{ font-size: 13px; color: {p.text_muted}; }}
QLabel#SectionTitle {{ font-size: 12px; font-weight: 700; color: {p.text_muted};
                       letter-spacing: 1.2px; }}
QLabel#CardLabel    {{ font-size: 11px; font-weight: 600; color: {p.text_dim};
                       letter-spacing: 1.1px; }}
QLabel#CardValue    {{ font-size: 26px; font-weight: 600; font-family: {MONO_STACK}; }}
QLabel#CardValueSm  {{ font-size: 17px; font-weight: 600; font-family: {MONO_STACK}; }}
QLabel#CardHint     {{ font-size: 11px; color: {p.text_dim}; }}
QLabel#Muted        {{ color: {p.text_muted}; }}
QLabel#Dim          {{ color: {p.text_dim}; }}
QLabel#Mono         {{ font-family: {MONO_STACK}; }}
QLabel#EmptyTitle   {{ font-size: 15px; font-weight: 600; color: {p.text_muted}; }}
QLabel#EmptyBody    {{ font-size: 12px; color: {p.text_dim}; }}

/* --------------------------------------------------------------- sidebar */

QWidget#Sidebar {{
    background: {p.bg_sunken};
    border-right: 1px solid {p.border};
}}
QLabel#BrandTitle {{ font-size: 14px; font-weight: 700; letter-spacing: 0.3px; }}
QLabel#BrandSub   {{ font-size: 10px; color: {p.text_dim}; letter-spacing: 1.4px; }}

QPushButton#NavItem {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_MD}px;
    padding: 9px 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    color: {p.text_muted};
}}
QPushButton#NavItem:hover  {{ background: {p.bg_raised}; color: {p.text}; }}
QPushButton#NavItem:checked {{
    background: {p.accent_dim};
    color: {p.text};
    font-weight: 600;
}}
QLabel#NavBadge {{
    background: {p.danger};
    color: {p.on_danger};
    border-radius: 7px;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
}}

/* ---------------------------------------------------------------- topbar */

QWidget#TopBar {{
    background: {p.bg_surface};
    border-bottom: 1px solid {p.border};
}}

/* --------------------------------------------------------------- buttons */

QPushButton {{
    background: {p.bg_raised};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_MD}px;
    padding: 8px 14px;
    font-weight: 500;
}}
QPushButton:hover   {{ background: {p.bg_hover}; }}
QPushButton:pressed {{ background: {p.bg_active}; }}
QPushButton:disabled {{
    background: {p.bg_surface};
    color: {p.text_dim};
    border-color: {p.border};
}}

QPushButton[variant="primary"] {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: {p.on_accent};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover   {{ background: {p.accent_hover}; }}
QPushButton[variant="primary"]:disabled {{
    background: {p.accent_dim}; border-color: {p.accent_dim}; color: {p.text_dim};
}}

QPushButton[variant="record"] {{
    background: {p.success};
    border: 1px solid {p.success};
    color: {p.on_success};
    font-size: 14px;
    font-weight: 700;
    padding: 13px 22px;
    letter-spacing: 0.6px;
}}
QPushButton[variant="record"]:hover {{ background: {p.success_hover}; }}
QPushButton[variant="record"]:disabled {{
    background: {p.bg_raised}; border-color: {p.border}; color: {p.text_dim};
}}

QPushButton[variant="stop"] {{
    background: {p.danger};
    border: 1px solid {p.danger};
    color: {p.on_danger};
    font-size: 14px;
    font-weight: 700;
    padding: 13px 22px;
    letter-spacing: 0.6px;
}}
QPushButton[variant="stop"]:hover {{ background: {p.danger_hover}; }}
QPushButton[variant="stop"]:disabled {{
    background: {p.bg_raised}; border-color: {p.border}; color: {p.text_dim};
}}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {p.text_muted};
    padding: 6px 10px;
}}
QPushButton[variant="ghost"]:hover {{ background: {p.bg_raised}; color: {p.text}; }}
QPushButton[variant="ghost"]:checked {{
    background: {p.bg_active}; color: {p.text}; border-color: {p.border_strong};
}}

QPushButton[variant="subtle"] {{
    background: {p.bg_surface};
    border: 1px solid {p.border};
}}
QPushButton[variant="subtle"]:hover {{ background: {p.bg_raised}; }}

/* ------------------------------------------------------------ text input */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p.bg_sunken};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: 8px 10px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {p.border_focus};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{
    color: {p.text_dim}; background: {p.bg_surface};
}}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{
    border: 1px solid {p.danger};
}}
QLineEdit#Search {{
    padding-left: 32px;
    border-radius: {RADIUS_MD}px;
    {search_image}
}}

QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ {chevron_image} }}
QComboBox QAbstractItemView {{
    background: {p.bg_raised};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_MD}px;
    selection-background-color: {p.accent_dim};
    padding: 4px;
}}

/* ------------------------------------------------------------- checkboxes */

QCheckBox, QRadioButton {{ spacing: 9px; padding: 3px 0; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {p.border_strong};
    background: {p.bg_sunken};
}}
QCheckBox::indicator {{ border-radius: {RADIUS_SM}px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    {check_image}
}}
QCheckBox::indicator:disabled {{
    background: {p.bg_surface};
    border-color: {p.border};
}}
/* A thick border plus a radius is where Qt's box model gives up and paints a
   square, so a checked radio is simply a filled disc, like the checkbox. */
QRadioButton::indicator:checked {{
    background: {p.accent};
    border: 1px solid {p.accent};
    border-radius: 9px;
}}
QRadioButton::indicator:checked:hover {{ background: {p.accent_hover};
                                         border-color: {p.accent_hover}; }}

/* ----------------------------------------------------------------- tables */

QTableView, QTreeWidget, QListWidget {{
    background: {p.bg_surface};
    alternate-background-color: {p.bg_surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    gridline-color: {p.border};
    selection-background-color: {p.accent_dim};
    selection-color: {p.text};
}}
QTableView::item, QTreeWidget::item, QListWidget::item {{
    padding: 7px 6px;
    border: none;
    border-bottom: 1px solid {p.border};
}}
QTableView::item:hover, QTreeWidget::item:hover {{ background: {p.bg_raised}; }}
QTableView::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {p.accent_dim};
}}

QHeaderView::section {{
    background: {p.bg_sunken};
    color: {p.text_dim};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 9px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.7px;
}}
QHeaderView::section:hover {{ color: {p.text_muted}; }}
QTableCornerButton::section {{ background: {p.bg_sunken}; border: none; }}

/* ------------------------------------------------------------- scrollbars */

QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.bg_active}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.border_strong}; }}
QScrollBar:horizontal {{
    background: transparent; height: 11px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p.bg_active}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.border_strong}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* -------------------------------------------------------------- progress */

QProgressBar {{
    background: {p.bg_sunken};
    border: none;
    border-radius: 4px;
    height: 7px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
QProgressBar[tone="warning"]::chunk {{ background: {p.warning}; }}
QProgressBar[tone="danger"]::chunk  {{ background: {p.danger}; }}
QProgressBar[tone="success"]::chunk {{ background: {p.success}; }}

/* --------------------------------------------------------------- splitter */

QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ----------------------------------------------------------------- dialog */

QDialog {{ background: {p.bg_base}; }}
QMessageBox {{ background: {p.bg_surface}; }}

/* ------------------------------------------------------------------ misc */

QGroupBox {{
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    margin-top: 10px;
    padding-top: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {p.text_muted};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
"""
