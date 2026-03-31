"""
UAA Machine Control System — Main UI
=====================================
PyQt6 - Main Page + Hardware Config Page
ใช้ settings.json เก็บค่า

Requirements:
    pip install PyQt6
"""

import sys
import json
import os
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QGridLayout,
    QLineEdit, QFormLayout, QScrollArea, QTabWidget, QSizePolicy,
    QSpacerItem, QStatusBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "smu": {
        "ip": "10.0.0.80", "port": 5025,
        "channel": "a", "voltage": 2.0,
        "current_limit": 0.001, "nplc": 1.0,
        "stop_threshold_ua": 1.0
    },
    "hexapod": {
        "ip": "192.168.1.10", "port": 50000,
        "y_start_um": 0.0, "y_end_um": 200.0, "y_step_um": 25.0,
        "z_start_um": 0.0, "z_end_um": -1100.0, "z_step_um": -1.0,
        "settle_time_s": 0.05
    },
    "dc_supply_1": {
        "name": "E36103B", "ip": "192.168.1.20", "port": 5025,
        "voltage": 0.0, "current": 0.0, "channel": 1
    },
    "dc_supply_2": {
        "name": "E36441A", "ip": "192.168.1.21", "port": 5025,
        "voltage": 0.0, "current": 0.0, "channel": 1
    },
    "dispenser_musashi": {
        "ip": "192.168.1.30", "port": 23,
        "dispense_time_ms": 100, "pressure_kpa": 50, "program": 1
    },
    "dispenser_dymax": {
        "ip": "192.168.1.40", "port": 10001,
        "intensity_pct": 100, "cure_time_s": 5.0, "port_no": 1
    },
    "output": {
        "csv_dir": "./results"
    }
}

# ══════════════════════════════════════════════
# Style
# ══════════════════════════════════════════════

STYLE = """
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: 'Consolas', 'Courier New', monospace;
}
QLabel { color: #e6edf3; }
QLineEdit {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #e6edf3;
    padding: 5px 8px;
    font-family: 'Consolas', monospace;
    font-size: 12px;
}
QLineEdit:focus { border: 1px solid #58a6ff; }
QPushButton {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    padding: 8px 16px;
    font-family: 'Consolas', monospace;
    font-size: 12px;
}
QPushButton:hover { background: #30363d; border-color: #58a6ff; color: #58a6ff; }
QPushButton:pressed { background: #161b22; }
QTabWidget::pane { border: 1px solid #21262d; background: #0d1117; }
QTabBar::tab {
    background: #161b22; color: #8b949e;
    padding: 8px 16px; border: 1px solid #21262d;
    font-family: 'Consolas', monospace; font-size: 11px;
}
QTabBar::tab:selected { background: #0d1117; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
QScrollArea { border: none; }
QStatusBar { background: #161b22; color: #8b949e; font-size: 11px; }
"""


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_SETTINGS.copy()


def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def make_label(text, color="#8b949e", size=10, bold=False):
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{color}; font-size:{size}px;"
        + (" font-weight:bold;" if bold else "")
    )
    return lbl


def make_divider():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #21262d;")
    return line


# ══════════════════════════════════════════════
# Status Card (หน้า main)
# ══════════════════════════════════════════════

class StatusCard(QFrame):
    def __init__(self, name, color="#f85149"):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame {{
                background: #161b22;
                border: 1px solid #21262d;
                border-radius: 8px;
                padding: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{color}; font-size:10px;")
        layout.addWidget(self.dot)

        vbox = QVBoxLayout()
        vbox.setSpacing(2)
        self.name_lbl = make_label(name, "#8b949e", 9)
        self.val_lbl  = make_label("OFFLINE", "#e6edf3", 11, True)
        vbox.addWidget(self.name_lbl)
        vbox.addWidget(self.val_lbl)
        layout.addLayout(vbox)
        layout.addStretch()

    def set_status(self, text, color):
        self.dot.setStyleSheet(f"color:{color}; font-size:10px;")
        self.val_lbl.setStyleSheet(f"color:{color}; font-size:11px; font-weight:bold;")
        self.val_lbl.setText(text)


# ══════════════════════════════════════════════
# Menu Card (หน้า main)
# ══════════════════════════════════════════════

class MenuCard(QPushButton):
    def __init__(self, icon, title, subtitle, color="#1f6feb", enabled=True):
        super().__init__()
        self.setFixedHeight(110)
        self.setEnabled(enabled)
        alpha = "33"
        self.setStyleSheet(f"""
            QPushButton {{
                background: #161b22;
                border: 1px solid #21262d;
                border-radius: 10px;
                text-align: center;
            }}
            QPushButton:hover {{
                border: 1px solid {color};
                background: {color}{alpha};
            }}
            QPushButton:disabled {{ opacity: 0.4; }}
        """)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"font-size:22px; background:transparent; border:none;")

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet("color:#e6edf3; font-size:12px; font-weight:bold; background:transparent; border:none;")

        sub_lbl = QLabel(subtitle)
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setStyleSheet("color:#8b949e; font-size:9px; background:transparent; border:none;")

        layout.addWidget(icon_lbl)
        layout.addWidget(title_lbl)
        layout.addWidget(sub_lbl)


# ══════════════════════════════════════════════
# Sidebar Button
# ══════════════════════════════════════════════

class SidebarBtn(QPushButton):
    def __init__(self, icon, label, color="#58a6ff"):
        super().__init__()
        self.setFixedHeight(40)
        self._color = color
        self.setCheckable(True)
        self.setText(f"  {icon}  {label}")
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-left: 2px solid transparent;
                color: #8b949e;
                font-size: 12px;
                text-align: left;
                padding-left: 12px;
            }}
            QPushButton:hover {{ background: #21262d; color: #c9d1d9; }}
            QPushButton:checked {{
                background: #1f6feb22;
                border-left: 2px solid {color};
                color: {color};
            }}
        """)


# ══════════════════════════════════════════════
# Page: Home
# ══════════════════════════════════════════════

class HomePage(QWidget):
    navigate = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Welcome
        now = datetime.datetime.now()
        hour = now.hour
        greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        welcome = make_label(f"{greet}, Kai", "#e6edf3", 16, True)
        sub     = make_label("UAA M3  —  Newark CA  |  Session started", "#8b949e", 10)
        layout.addWidget(welcome)
        layout.addWidget(sub)

        # Status bar
        status_lbl = make_label("DEVICE STATUS", "#8b949e", 9, True)
        layout.addWidget(status_lbl)

        status_grid = QHBoxLayout()
        status_grid.setSpacing(8)
        devices = [
            ("SMU 2602B",   "#f85149"),
            ("PI Hexapod",  "#f85149"),
            ("DC Supply 1", "#f85149"),
            ("DC Supply 2", "#f85149"),
            ("Musashi",     "#f85149"),
            ("DYMAX QX4",   "#f85149"),
        ]
        for name, color in devices:
            card = StatusCard(name, color)
            status_grid.addWidget(card)
        layout.addLayout(status_grid)

        # Menu grid
        menu_lbl = make_label("MODULES", "#8b949e", 9, True)
        layout.addWidget(menu_lbl)

        grid = QGridLayout()
        grid.setSpacing(12)

        menus = [
            ("📋", "Recipe",          "Load / Edit\nprocess recipe",   "#3fb950", True,  1),
            ("⚙️", "Hardware Config", "IP, Port &\ndevice parameters", "#58a6ff", True,  2),
            ("🗄️", "Database Setup",  "Connection &\ntable config",    "#bc8cff", True,  3),
            ("📡", "Scan Monitor",    "Y-Z scan &\nrealtime plot",     "#d29922", True,  4),
            ("📊", "Data Log",        "History &\nexport CSV",         "#39d353", False, 5),
            ("🔬", "Alignment",       "Coming soon",                   "#8b949e", False, 0),
            ("💉", "Dispense",        "Coming soon",                   "#8b949e", False, 0),
        ]

        for i, (icon, title, sub, color, enabled, page_idx) in enumerate(menus):
            card = MenuCard(icon, title, sub, color, enabled)
            if enabled and page_idx > 0:
                idx = page_idx
                card.clicked.connect(lambda _, p=idx: self.navigate.emit(p))
            grid.addWidget(card, i // 4, i % 4)

        # Add module button
        add_btn = QPushButton("＋  Add Module")
        add_btn.setFixedHeight(110)
        add_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px dashed #30363d;
                border-radius: 10px;
                color: #8b949e; font-size: 12px;
            }
            QPushButton:hover { border-color: #58a6ff; color: #58a6ff; }
        """)
        grid.addWidget(add_btn, (len(menus)) // 4, (len(menus)) % 4)

        layout.addLayout(grid)
        layout.addStretch()


# ══════════════════════════════════════════════
# Page: Hardware Config
# ══════════════════════════════════════════════

class FieldRow(QWidget):
    def __init__(self, label, value, color="#58a6ff"):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        lbl = make_label(label, "#8b949e", 9)
        self.edit = QLineEdit(str(value))
        self.edit.setStyleSheet(
            f"background:#161b22; border:1px solid #30363d; "
            f"border-left:2px solid {color}; border-radius:4px; "
            f"color:#e6edf3; padding:5px 8px; font-size:11px;"
        )
        layout.addWidget(lbl)
        layout.addWidget(self.edit)

    def value(self):
        return self.edit.text()


class DeviceSection(QWidget):
    def __init__(self, title, dot_color, fields):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        dot = make_label("●", dot_color, 10)
        ttl = make_label(title, "#e6edf3", 12, True)
        ping_btn = QPushButton("⟳ Ping")
        ping_btn.setFixedSize(70, 28)
        header.addWidget(dot)
        header.addWidget(ttl)
        header.addStretch()
        header.addWidget(ping_btn)
        layout.addLayout(header)
        layout.addWidget(make_divider())

        # Fields grid
        self.field_widgets = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (key, label, val, color) in enumerate(fields):
            fw = FieldRow(label, val, color)
            self.field_widgets[key] = fw
            grid.addWidget(fw, i // 2, i % 2)
        layout.addLayout(grid)

    def get_values(self):
        return {k: v.value() for k, v in self.field_widgets.items()}


class HardwareConfigPage(QWidget):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Title + Save
        top = QHBoxLayout()
        top.addWidget(make_label("HARDWARE CONFIGURATION", "#e6edf3", 14, True))
        top.addStretch()
        save_btn = QPushButton("💾  Save All")
        save_btn.setStyleSheet("""
            QPushButton {
                background: #238636; border: none; border-radius: 6px;
                color: #fff; padding: 8px 20px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: #2ea043; }
        """)
        save_btn.clicked.connect(self.save_all)
        top.addWidget(save_btn)
        layout.addLayout(top)
        layout.addWidget(make_divider())

        # Tabs per device
        tabs = QTabWidget()
        s = self.settings

        self.sections = {}

        # SMU
        smu_w = DeviceSection("Keithley 2602B", "#3fb950", [
            ("ip",                "IP ADDRESS",          s["smu"]["ip"],                 "#3fb950"),
            ("port",              "PORT",                s["smu"]["port"],               "#3fb950"),
            ("channel",           "CHANNEL",             s["smu"]["channel"],            "#3fb950"),
            ("nplc",              "NPLC",                s["smu"]["nplc"],               "#3fb950"),
            ("voltage",           "SOURCE VOLTAGE (V)",  s["smu"]["voltage"],            "#3fb950"),
            ("current_limit",     "CURRENT LIMIT (A)",   s["smu"]["current_limit"],      "#3fb950"),
            ("stop_threshold_ua", "STOP THRESHOLD (µA)", s["smu"]["stop_threshold_ua"],  "#3fb950"),
        ])
        self.sections["smu"] = smu_w
        tabs.addTab(self._wrap(smu_w), "📗 SMU 2602B")

        # Hexapod
        hxp_w = DeviceSection("PI Hexapod C-887", "#58a6ff", [
            ("ip",           "IP ADDRESS",    s["hexapod"]["ip"],           "#58a6ff"),
            ("port",         "PORT",          s["hexapod"]["port"],         "#58a6ff"),
            ("y_start_um",   "Y START (µm)",  s["hexapod"]["y_start_um"],   "#58a6ff"),
            ("y_end_um",     "Y END (µm)",    s["hexapod"]["y_end_um"],     "#58a6ff"),
            ("y_step_um",    "Y STEP (µm)",   s["hexapod"]["y_step_um"],    "#58a6ff"),
            ("z_start_um",   "Z START (µm)",  s["hexapod"]["z_start_um"],   "#58a6ff"),
            ("z_end_um",     "Z END (µm)",    s["hexapod"]["z_end_um"],     "#58a6ff"),
            ("z_step_um",    "Z STEP (µm)",   s["hexapod"]["z_step_um"],    "#58a6ff"),
            ("settle_time_s","SETTLE TIME (s)",s["hexapod"]["settle_time_s"],"#58a6ff"),
        ])
        self.sections["hexapod"] = hxp_w
        tabs.addTab(self._wrap(hxp_w), "📘 PI Hexapod")

        # DC Supply 1
        dc1_w = DeviceSection("Keysight E36103B", "#d29922", [
            ("ip",      "IP ADDRESS",          s["dc_supply_1"]["ip"],      "#d29922"),
            ("port",    "PORT",                s["dc_supply_1"]["port"],    "#d29922"),
            ("voltage", "VOLTAGE (V)",         s["dc_supply_1"]["voltage"], "#d29922"),
            ("current", "CURRENT LIMIT (A)",   s["dc_supply_1"]["current"], "#d29922"),
            ("channel", "OUTPUT CHANNEL",      s["dc_supply_1"]["channel"], "#d29922"),
        ])
        self.sections["dc_supply_1"] = dc1_w
        tabs.addTab(self._wrap(dc1_w), "📙 DC Supply 1")

        # DC Supply 2
        dc2_w = DeviceSection("Keysight E36441A", "#d29922", [
            ("ip",      "IP ADDRESS",          s["dc_supply_2"]["ip"],      "#d29922"),
            ("port",    "PORT",                s["dc_supply_2"]["port"],    "#d29922"),
            ("voltage", "VOLTAGE (V)",         s["dc_supply_2"]["voltage"], "#d29922"),
            ("current", "CURRENT LIMIT (A)",   s["dc_supply_2"]["current"], "#d29922"),
            ("channel", "OUTPUT CHANNEL",      s["dc_supply_2"]["channel"], "#d29922"),
        ])
        self.sections["dc_supply_2"] = dc2_w
        tabs.addTab(self._wrap(dc2_w), "📙 DC Supply 2")

        # Musashi
        mus_w = DeviceSection("Musashi ML-6000X", "#bc8cff", [
            ("ip",               "IP ADDRESS",         s["dispenser_musashi"]["ip"],               "#bc8cff"),
            ("port",             "PORT",               s["dispenser_musashi"]["port"],             "#bc8cff"),
            ("dispense_time_ms", "DISPENSE TIME (ms)", s["dispenser_musashi"]["dispense_time_ms"], "#bc8cff"),
            ("pressure_kpa",     "PRESSURE (kPa)",     s["dispenser_musashi"]["pressure_kpa"],     "#bc8cff"),
            ("program",          "PROGRAM NO.",        s["dispenser_musashi"]["program"],          "#bc8cff"),
        ])
        self.sections["dispenser_musashi"] = mus_w
        tabs.addTab(self._wrap(mus_w), "📓 Musashi")

        # DYMAX
        dym_w = DeviceSection("DYMAX Bluewave QX4", "#39d353", [
            ("ip",            "IP ADDRESS",     s["dispenser_dymax"]["ip"],            "#39d353"),
            ("port",          "PORT",           s["dispenser_dymax"]["port"],          "#39d353"),
            ("intensity_pct", "INTENSITY (%)",  s["dispenser_dymax"]["intensity_pct"], "#39d353"),
            ("cure_time_s",   "CURE TIME (s)",  s["dispenser_dymax"]["cure_time_s"],   "#39d353"),
            ("port_no",       "OUTPUT PORT",    s["dispenser_dymax"]["port_no"],       "#39d353"),
        ])
        self.sections["dispenser_dymax"] = dym_w
        tabs.addTab(self._wrap(dym_w), "📗 DYMAX QX4")

        layout.addWidget(tabs)

    def _wrap(self, widget):
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#0d1117;")
        return scroll

    def save_all(self):
        for key, section in self.sections.items():
            vals = section.get_values()
            for field, raw in vals.items():
                try:
                    orig = self.settings[key][field]
                    if isinstance(orig, int):
                        self.settings[key][field] = int(raw)
                    elif isinstance(orig, float):
                        self.settings[key][field] = float(raw)
                    else:
                        self.settings[key][field] = raw
                except (ValueError, KeyError):
                    self.settings[key][field] = raw
        save_settings(self.settings)
        print(f"[Settings] Saved to {SETTINGS_FILE}")


# ══════════════════════════════════════════════
# Placeholder pages
# ══════════════════════════════════════════════

class PlaceholderPage(QWidget):
    def __init__(self, title, icon):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icon  = make_label(icon, "#8b949e", 48)
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title = make_label(title, "#8b949e", 16, True)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub   = make_label("Coming soon", "#30363d", 12)
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_icon)
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_sub)


# ══════════════════════════════════════════════
# Main Window
# ══════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle("UAA Machine Control System")
        self.setMinimumSize(1100, 680)
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(190)
        sidebar.setStyleSheet("background:#161b22; border-right:1px solid #21262d;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(8, 16, 8, 16)
        sb_layout.setSpacing(2)

        # Logo
        logo_lbl = make_label("UAA CONTROL", "#e6edf3", 12, True)
        logo_sub = make_label("Machine System", "#8b949e", 9)
        sb_layout.addWidget(logo_lbl)
        sb_layout.addWidget(logo_sub)
        sb_layout.addSpacing(12)
        sb_layout.addWidget(make_divider())
        sb_layout.addSpacing(8)

        nav_lbl = make_label("NAVIGATION", "#8b949e", 9)
        sb_layout.addWidget(nav_lbl)
        sb_layout.addSpacing(4)

        self.nav_btns = []
        navs = [
            ("🏠", "Home",            "#58a6ff"),
            ("📋", "Recipe",          "#3fb950"),
            ("⚙️", "Hardware Config", "#58a6ff"),
            ("🗄️", "Database Setup",  "#bc8cff"),
            ("📡", "Scan Monitor",    "#d29922"),
            ("📊", "Data Log",        "#39d353"),
        ]
        for i, (icon, label, color) in enumerate(navs):
            btn = SidebarBtn(icon, label, color)
            btn.clicked.connect(lambda _, idx=i: self.switch_page(idx))
            sb_layout.addWidget(btn)
            self.nav_btns.append(btn)

        sb_layout.addStretch()
        sb_layout.addWidget(make_divider())

        # E-Stop
        estop = QPushButton("⛔  E-STOP")
        estop.setFixedHeight(40)
        estop.setStyleSheet("""
            QPushButton {
                background: #3d0000; border: 1px solid #f85149;
                border-radius: 6px; color: #f85149;
                font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: #f85149; color: #fff; }
        """)
        sb_layout.addWidget(estop)

        root.addWidget(sidebar)

        # ── Pages ────────────────────────────────
        self.stack = QStackedWidget()
        self.home_page = HomePage()
        self.home_page.navigate.connect(self.switch_page)

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(PlaceholderPage("Recipe", "📋"))
        self.stack.addWidget(HardwareConfigPage(self.settings))
        self.stack.addWidget(PlaceholderPage("Database Setup", "🗄️"))
        self.stack.addWidget(PlaceholderPage("Scan Monitor", "📡"))
        self.stack.addWidget(PlaceholderPage("Data Log", "📊"))

        root.addWidget(self.stack)

        # ── Status bar ───────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("UAA Machine Control  |  Python 3.12  |  v0.1.0-dev")

        # Clock
        self.clock_lbl = QLabel()
        self.clock_lbl.setStyleSheet("color:#8b949e; font-size:11px; padding-right:8px;")
        self.status_bar.addPermanentWidget(self.clock_lbl)
        timer = QTimer(self)
        timer.timeout.connect(self.update_clock)
        timer.start(1000)
        self.update_clock()

        # Init
        self.switch_page(0)

    def switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == idx)

    def update_clock(self):
        self.clock_lbl.setText(datetime.datetime.now().strftime("%H:%M:%S"))


# ══════════════════════════════════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
