"""Look and feel: dark "liquid glass" over an animated background.

Everything is built from three user colours (Settings → Appearance):
  primary   - buttons, sliders, checkmarks, highlights
  secondary - gradients and the background
  tertiary  - gradients and the background
"""

from PySide6.QtGui import QColor

TEXT = "#f2f4f1"
MUTED = "rgba(235, 240, 235, 0.62)"
RED = "#ff6b6b"

PRESETS = {
    "Greentext": ("#8fc43f", "#2fc4a0", "#7a5cff"),
    "Synthwave": ("#ff4fd8", "#7a5cff", "#2de2e6"),
    "Ember": ("#ff7a1a", "#ff3d5a", "#ffc23d"),
    "Ocean": ("#3da5ff", "#2de2c4", "#5b4bff"),
    "Blood Moon": ("#ff3048", "#8a1cff", "#ff8a5c"),
    "Mono": ("#e8ebe6", "#8c948f", "#4a5257"),
}
DEFAULT_COLORS = PRESETS["Greentext"]

# Current colours (updated by apply_colors); widgets read these when painting.
COLORS = {"primary": DEFAULT_COLORS[0], "secondary": DEFAULT_COLORS[1],
          "tertiary": DEFAULT_COLORS[2]}


def color(name: str) -> QColor:
    return QColor(COLORS[name])


def primary() -> str:
    return COLORS["primary"]


def _rgba(c: QColor, a: float) -> str:
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {a:.3f})"


def _on(c: QColor) -> str:
    """Black or white text, whichever reads better on this colour."""
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return "#0b0d0a" if lum > 0.55 else "#ffffff"


def build_style() -> str:
    p = color("primary")
    s = color("secondary")
    light = p.lighter(118)
    on_p = _on(p)
    glass = "rgba(255, 255, 255, 0.07)"
    edge = "rgba(255, 255, 255, 0.14)"
    field = "rgba(8, 10, 14, 0.42)"
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 10.5pt;
     color: {TEXT}; }}
QMainWindow, QStackedWidget, QWidget#Page, QWidget#Transparent {{ background: transparent; }}
QDialog, QMessageBox, QColorDialog {{ background: #121418; }}
QLabel {{ background: transparent; }}
QLabel#Title {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 22pt;
    font-weight: 700; }}
QLabel#Subtitle {{ color: {MUTED}; font-size: 11pt; }}
QLabel#Logo {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 14pt;
    font-weight: 800; letter-spacing: 1px; }}
QLabel#Muted, QLabel#Hint {{ color: {MUTED}; }}
QLabel#Hint {{ font-size: 9.5pt; }}
QLabel#Error {{ color: {RED}; }}
QLabel#Section {{ font-size: 11.5pt; font-weight: 600; }}

QPushButton {{
    background: {glass}; border: 1px solid {edge}; border-radius: 12px; padding: 9px 18px;
}}
QPushButton:disabled {{ color: rgba(255, 255, 255, 0.32); border-color: rgba(255, 255, 255, 0.06); }}
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {light.name()}, stop:1 {p.name()});
    color: {on_p}; border: 1px solid rgba(255, 255, 255, 0.30); font-weight: 700;
    padding: 10px 26px;
}}
QPushButton#Primary:disabled {{ background: {_rgba(p, 0.22)}; color: rgba(255, 255, 255, 0.40);
    border-color: rgba(255, 255, 255, 0.08); }}
QPushButton#Link {{ background: transparent; border: none; color: {light.name()}; padding: 2px; }}
QPushButton#Icon {{ padding: 6px 12px; font-size: 12pt; }}
QPushButton#Spot {{ padding: 0; border-radius: 7px; color: rgba(255, 255, 255, 0.55);
    background: rgba(255, 255, 255, 0.06); font-size: 13pt; }}
QPushButton#Spot:hover {{ background: {_rgba(p, 0.30)}; color: white; border-color: {p.name()}; }}
QPushButton#PostTab {{ padding: 6px 12px; border-radius: 10px; }}
QPushButton#PostTab:checked {{ background: {_rgba(p, 0.22)}; border: 1px solid {p.name()}; color: white; }}
QPushButton#Swatch {{ border-radius: 10px; border: 2px solid rgba(255, 255, 255, 0.35); padding: 0; }}

QPushButton#Step {{
    background: {glass}; border: 1px solid {edge}; border-radius: 14px; padding: 5px 15px;
    min-height: 18px; color: {MUTED};
}}
QPushButton#Step[state="current"] {{ background: {_rgba(p, 0.22)}; border: 1px solid {p.name()};
    color: {TEXT}; font-weight: 700; }}
QPushButton#Step[state="done"] {{ color: {light.name()}; border-color: {_rgba(p, 0.55)}; }}
QLabel#StepLine {{ color: rgba(255, 255, 255, 0.18); }}

QLineEdit, QPlainTextEdit, QComboBox, QTableWidget, QSpinBox, QTimeEdit, QListWidget {{
    background: {field}; border: 1px solid {edge}; border-radius: 12px; padding: 7px 9px;
    selection-background-color: {_rgba(p, 0.55)};
}}
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{
    width: 18px; border: none; background: transparent; }}
QListWidget::item {{ padding: 4px 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {_rgba(p, 0.30)}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {p.name()}; }}
QPlainTextEdit {{ font-size: 11pt; }}
QComboBox QAbstractItemView {{ background: #15181c; border: 1px solid {edge};
    selection-background-color: {_rgba(p, 0.35)}; outline: none; padding: 4px; }}
QTableWidget {{ gridline-color: rgba(255, 255, 255, 0.07); padding: 0; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: rgba(255, 255, 255, 0.05); border: none;
    border-bottom: 1px solid {edge}; padding: 7px; font-weight: 600; color: {MUTED}; }}
QTableWidget::item:selected {{ background: {_rgba(p, 0.25)}; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

QSlider::groove:horizontal {{ height: 6px; background: rgba(255, 255, 255, 0.12); border-radius: 3px; }}
QSlider::sub-page:horizontal {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {s.name()}, stop:1 {p.name()}); }}
QSlider::handle:horizontal {{ background: #ffffff; width: 18px; margin: -6px 0; border-radius: 9px;
    border: 1px solid rgba(0, 0, 0, 0.2); }}
QSlider::sub-page:horizontal:disabled {{ background: rgba(255, 255, 255, 0.15); }}

QProgressBar {{ background: rgba(255, 255, 255, 0.10); border: none; border-radius: 7px;
    height: 14px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {s.name()}, stop:1 {p.name()}); }}

QCheckBox {{ spacing: 9px; background: transparent; }}
QCheckBox::indicator {{ width: 20px; height: 20px; border: 1px solid {edge}; border-radius: 6px;
    background: {field}; }}
QCheckBox::indicator:checked {{ background: {p.name()}; border-color: {p.name()}; }}

QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; padding: 9px 18px; color: {MUTED}; border-radius: 10px;
    margin-right: 4px; }}
QTabBar::tab:selected {{ color: {TEXT}; background: rgba(255, 255, 255, 0.10); }}
QTabBar::tab:hover:!selected {{ background: rgba(255, 255, 255, 0.05); }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: rgba(255, 255, 255, 0.22); border-radius: 3px;
    min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0; background: transparent; }}
QToolTip {{ background: #15181c; color: {TEXT}; border: 1px solid {edge}; border-radius: 6px; }}
"""


def apply_colors(app, primary_c: str, secondary_c: str, tertiary_c: str):
    for k, v in zip(("primary", "secondary", "tertiary"), (primary_c, secondary_c, tertiary_c)):
        if QColor(v).isValid():
            COLORS[k] = QColor(v).name()
    app.setStyleSheet(build_style())
