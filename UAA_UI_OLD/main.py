"""
UAA Machine Control System
===========================
รันไฟล์นี้อย่างเดียว:  py main.py

Requirements:
    pip install PyQt6
"""

import sys, datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QStackedWidget,
    QPushButton, QLabel, QStatusBar, QFrame
)
from PyQt6.QtCore import QTimer, Qt

from core.style import STYLE
from core.widgets import lbl, divider, SidebarIcon
from pages.home_page import HomePage
from pages.hardware_config_page import HardwareConfigPage
from pages.blank_page import BlankPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UAA Machine Control System")
        self.setMinimumSize(1100, 660)
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ══ Sidebar (icon only) ═══════════════════════
        sidebar = QWidget()
        sidebar.setFixedWidth(58)
        sidebar.setStyleSheet(
            "background:#0a0c10; border-right:1px solid #1e2433;"
        )
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(7, 14, 7, 14)
        sb.setSpacing(4)
        sb.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.nav_btns = []
        navs = [
            ("⌂",  "Home",            "#4a9eff"),
            ("≡",  "Recipe",          "#3b82f6"),
            ("⚙",  "Hardware Config", "#4a9eff"),
            ("⊞",  "Database Setup",  "#a855f7"),
            ("◎",  "Scan Monitor",    "#eab308"),
            ("▤",  "Data Log",        "#22c55e"),
        ]
        for i, (icon, tip, color) in enumerate(navs):
            btn = SidebarIcon(icon, tip, color)
            btn.clicked.connect(lambda _, idx=i: self.go(idx))
            sb.addWidget(btn)
            self.nav_btns.append(btn)

        sb.addStretch()

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background:#1e2433;")
        sb.addWidget(div)
        sb.addSpacing(4)

        # E-Stop
        estop = SidebarIcon("⊗", "E-STOP", "#ef4444")
        estop.setStyleSheet("""
            QPushButton {
                background: #1a0000;
                border: 1px solid #3d0a0a;
                border-radius: 8px;
                color: #3d0a0a;
                font-size: 18px;
            }
            QPushButton:hover { background: #ef4444; color: #fff; border-color: #ef4444; }
        """)
        sb.addWidget(estop)
        root.addWidget(sidebar)

        # ══ Right side: breadcrumb + pages ════════════
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Breadcrumb bar
        self.breadcrumb = QLabel("Home")
        self.breadcrumb.setFixedHeight(34)
        self.breadcrumb.setStyleSheet("""
            QLabel {
                background: #0a0c10;
                border-bottom: 1px solid #1e2433;
                color: #4a5568;
                font-size: 11px;
                padding-left: 18px;
                letter-spacing: 0.5px;
            }
        """)
        right_layout.addWidget(self.breadcrumb)

        # Pages
        self.stack = QStackedWidget()

        self.home = HomePage()
        self.home.navigate.connect(self.go)

        self.stack.addWidget(self.home)                           # 0
        self.stack.addWidget(BlankPage("Recipe",         "📋"))  # 1
        self.stack.addWidget(HardwareConfigPage())                # 2
        self.stack.addWidget(BlankPage("Database Setup", "🗄️")) # 3
        self.stack.addWidget(BlankPage("Scan Monitor",   "📡"))  # 4
        self.stack.addWidget(BlankPage("Data Log",       "📊"))  # 5

        right_layout.addWidget(self.stack)
        root.addWidget(right)

        # ══ Status bar ════════════════════════════════
        sb2 = QStatusBar()
        self.setStatusBar(sb2)
        sb2.showMessage("UAA Machine Control  |  PyQt6 / Python 3.12  |  v0.1.0-dev")
        self.clk_lbl = QLabel()
        self.clk_lbl.setStyleSheet(
            "color:#2a3444; font-size:11px; padding-right:10px;"
        )
        sb2.addPermanentWidget(self.clk_lbl)

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)
        self._tick()

        self._page_names = [
            "Home", "Recipe", "Hardware Config",
            "Database Setup", "Scan Monitor", "Data Log"
        ]
        self.go(0)

    def go(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == idx)
        name = self._page_names[idx] if idx < len(self._page_names) else ""
        crumb = f"Home  ›  {name}" if idx > 0 else "Home"
        self.breadcrumb.setText("  " + crumb)

    def _tick(self):
        self.clk_lbl.setText(
            datetime.datetime.now().strftime("%Y-%m-%d   %H:%M:%S")
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
