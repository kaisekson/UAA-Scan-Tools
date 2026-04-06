import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
from core.widgets import lbl, divider, MenuCard
from core import settings as cfg


class DeviceStatusBar(QFrame):
    details_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QFrame {
                background: #20242e;
                border: 1px solid #3a4055;
                border-radius: 6px;
            }
        """)
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(20)

        self._total   = lbl("● 0 devices", "#94a3b8", 12)
        self._online  = lbl("✓ 0 online",  "#22c55e", 12)
        self._offline = lbl("✗ 0 offline", "#ef4444", 12)

        details_btn = QPushButton("Details →")
        details_btn.setFixedHeight(26)
        details_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid #3a4055;
                border-radius: 4px; color: #4a9eff;
                font-size: 11px; padding: 0 10px;
            }
            QPushButton:hover { border-color: #4a9eff; background: #1e2d47; }
        """)
        details_btn.clicked.connect(self.details_clicked.emit)

        layout.addWidget(self._total)
        layout.addWidget(self._offline)  # แสดง offline ก่อน ให้สังเกตง่าย
        layout.addWidget(self._online)
        layout.addStretch()
        layout.addWidget(details_btn)

    def update_status(self, total, online, offline):
        self._total.setText(f"● {total} devices")
        self._online.setText(f"✓ {online} online")
        self._offline.setText(f"✗ {offline} offline")
        self._offline.setStyleSheet(
            f"color:{'#ef4444' if offline > 0 else '#64748b'}; font-size:12px;"
        )


class HomePage(QWidget):
    navigate = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Greeting
        hour   = datetime.datetime.now().hour
        greet  = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        layout.addWidget(lbl(f"{greet}, Kai", "#e2e8f0", 16, True))
        layout.addWidget(lbl("UAA M3  —  Newark CA", "#64748b", 11))
        layout.addWidget(divider())

        # Device status bar
        self.status_bar = DeviceStatusBar()
        self.status_bar.details_clicked.connect(lambda: self.navigate.emit(2))
        self._refresh_status()
        layout.addWidget(self.status_bar)

        layout.addWidget(divider())

        # Section label
        layout.addWidget(lbl("MODULES", "#64748b", 10, True))

        # Menu grid 3 columns
        grid = QGridLayout()
        grid.setSpacing(10)

        menus = [
            ("📋", "Recipe",          "Load / edit process recipe",  "#3b82f6", True,  1),
            ("⚙️", "Hardware Config", "Device IP & parameters",      "#4a9eff", True,  2),
            ("🗄️", "Database Setup",  "Connection & table config",   "#a855f7", True,  3),
            ("📡", "Scan Monitor",    "Y-Z scan & realtime plot",    "#eab308", True,  4),
            ("📊", "Data Log",        "History & export CSV",        "#22c55e", True,  5),
            ("＋", "Add Module",      "Extend system",               "#64748b", False, 0),
        ]

        for i, (icon, title, sub, color, enabled, idx) in enumerate(menus):
            card = MenuCard(icon, title, sub, color, enabled)
            if enabled and idx > 0:
                card.clicked.connect(lambda _, p=idx: self.navigate.emit(p))
            grid.addWidget(card, i // 3, i % 3)

        layout.addLayout(grid)
        layout.addStretch()

    def _refresh_status(self):
        data    = cfg.load()
        devices = data.get("devices", {})
        total   = len(devices)
        online  = 0   # TODO: ping จริงทีหลัง
        offline = total - online
        self.status_bar.update_status(total, online, offline)
