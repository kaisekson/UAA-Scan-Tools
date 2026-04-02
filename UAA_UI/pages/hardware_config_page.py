from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.widgets import lbl, divider
from pages.power_supply_panel import PowerSupplyPanel
from pages.hexapod_panel import HexapodPanel
from pages.linear_stage_panel import LinearStagePanel
from pages.cartesian_panel import CartesianPanel
from pages.smu_panel import SMUPanel
from core import settings as cfg


# ── Tab button (left sidebar style) ──────────────

class DeviceTab(QPushButton):
    def __init__(self, dot_color, name):
        super().__init__()
        self.setFixedHeight(44)
        self.setCheckable(True)
        self._color = dot_color
        self._name  = name
        self._update_style(False)
        self.toggled.connect(self._update_style)

    def _update_style(self, checked):
        c = self._color
        self.setStyleSheet(f"""
            QPushButton {{
                background: {'#0d1520' if checked else '#0d0f14'};
                border: 1px solid {''+c if checked else '#1e2433'};
                border-radius: 6px;
                text-align: left;
                padding-left: 14px;
                color: {''+c if checked else '#8892a4'};
                font-size: 13px;
                font-weight: {'600' if checked else '400'};
            }}
            QPushButton:hover {{ border-color: {c}; color: {c}; background: #0d1520; }}
        """)
        dot = "● " if checked else "○ "
        self.setText(dot + self._name)


# ── Empty panel (content placeholder) ────────────

class EmptyPanel(QWidget):
    def __init__(self, title, color):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        ico = lbl("⚙", color, 36)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ttl = lbl(title, "#2a3444", 14, True)
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = lbl("Configuration panel — coming soon", "#1e2433", 11)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(ico)
        layout.addWidget(ttl)
        layout.addWidget(sub)


# ── Hardware Config Page ──────────────────────────

class HardwareConfigPage(QWidget):
    def __init__(self):
        super().__init__()
        self.data = cfg.load()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Title + Save
        top = QHBoxLayout()
        top.addWidget(lbl("HARDWARE CONFIGURATION", "#c5cdd9", 14, True))
        top.addStretch()
        save_btn = QPushButton("💾   Save All")
        save_btn.setFixedHeight(32)
        save_btn.setStyleSheet("""
            QPushButton {
                background:#1a3a1a; border:1px solid #22c55e;
                border-radius:5px; color:#22c55e;
                font-size:12px; font-weight:600; padding:0 18px;
            }
            QPushButton:hover { background:#22c55e; color:#000; }
        """)
        save_btn.clicked.connect(self.save_all)
        top.addWidget(save_btn)
        layout.addLayout(top)
        layout.addWidget(divider())

        # Body: tab list left + panel right
        body = QHBoxLayout()
        body.setSpacing(12)

        # ── Tab list ─────────────────────────────
        tab_col = QVBoxLayout()
        tab_col.setSpacing(4)
        tab_col.setContentsMargins(0, 0, 0, 0)

        self._tabs   = []
        self._panels = []

        devices = [
            ("Power Supply", "#3b82f6", True,  "psu"),
            ("Hexapod",      "#4a9eff", True,  "hxp"),
            ("Linear Stage",  "#38bdf8", True,  "lin"),
            ("Cartesian XYZ", "#4ade80", True,  "cart"),
            ("SMU",           "#22c55e", True,  "smu"),
            ("Dispense",     "#a855f7", False, ""),
            ("UV Cure",      "#eab308", False, ""),
        ]

        from PyQt6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("""
            QStackedWidget {
                background: #0d0f14;
                border: 1px solid #1e2433;
                border-radius: 6px;
            }
        """)

        for item in devices:
            name     = item[0]; color = item[1]
            use_real = item[2] if len(item) > 2 else False
            key      = item[3] if len(item) > 3 else ""
            tab = DeviceTab(color, name)
            tab.clicked.connect(lambda _, n=name, c=color: self._select(n, c))
            self._tabs.append((name, tab))
            tab_col.addWidget(tab)

            if use_real and key == "psu":
                panel = PowerSupplyPanel()
                self._psu_panel = panel
            elif use_real and key == "hxp":
                panel = HexapodPanel()
                self._hxp_panel = panel
            elif use_real and key == "lin":
                panel = LinearStagePanel()
                self._lin_panel = panel
            elif use_real and key == "cart":
                panel = CartesianPanel()
                self._cart_panel = panel
            elif use_real and key == "smu":
                panel = SMUPanel()
                self._smu_panel = panel
            else:
                panel = EmptyPanel(name, color)
            self.stack.addWidget(panel)

        tab_col.addSpacing(8)

        # Add Device button
        add_btn = QPushButton("＋   Add Device")
        add_btn.setFixedHeight(38)
        add_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px dashed #1e2433;
                border-radius: 6px;
                color: #4a5568; font-size: 12px;
            }
            QPushButton:hover { border-color: #4a9eff; color: #4a9eff; }
        """)
        tab_col.addWidget(add_btn)
        tab_col.addStretch()

        tab_widget = QWidget()
        tab_widget.setFixedWidth(160)
        tab_widget.setLayout(tab_col)

        body.addWidget(tab_widget)
        body.addWidget(self.stack, 1)
        layout.addLayout(body)

        # โหลด PSU settings ที่บันทึกไว้
        if "power_supplies" in self.data and self.data["power_supplies"]:
            self._psu_panel.load_all_settings(self.data["power_supplies"])
        if "hexapods" in self.data and self.data["hexapods"]:
            self._hxp_panel.load_all_settings(self.data["hexapods"])
        if "linear_stage" in self.data and self.data["linear_stage"]:
            self._lin_panel.load_settings(self.data["linear_stage"])
        if "cartesian" in self.data and self.data["cartesian"]:
            self._cart_panel.load_settings(self.data["cartesian"])
        if "smu" in self.data and self.data["smu"]:
            self._smu_panel.load_settings(self.data["smu"])

        # Select first tab by default
        if self._tabs:
            self._tabs[0][1].setChecked(True)
            self.stack.setCurrentIndex(0)

    def _select(self, name, color):
        for n, tab in self._tabs:
            tab.setChecked(n == name)
        idx = [n for n, _ in self._tabs].index(name)
        self.stack.setCurrentIndex(idx)

    def save_all(self):
        # เก็บ PSU settings
        self.data["power_supplies"] = self._psu_panel.get_all_settings()
        self.data["hexapods"] = self._hxp_panel.get_all_settings()
        self.data["linear_stage"] = self._lin_panel.get_settings()
        self.data["cartesian"] = self._cart_panel.get_settings()
        self.data["smu"] = self._smu_panel.get_settings()
        cfg.save(self.data)
        print("[Config] Saved power supply settings")
