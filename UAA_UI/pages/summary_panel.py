"""
Hardware Config Summary Panel
================================
แสดง status overview ของทุก device ใน Hardware Config
"""

import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QScrollArea, QPushButton
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider


class DeviceCard(QFrame):
    def __init__(self, name, icon, color):
        super().__init__()
        self._color = color
        self.setStyleSheet(
            f"QFrame{{background:#20242e;border:1px solid #3a4055;"
            f"border-radius:8px;}}")
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,12,14,12)
        layout.setSpacing(6)

        # Top row — icon + name
        top = QHBoxLayout(); top.setSpacing(8)
        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI",16))
        icon_lbl.setStyleSheet("background:transparent;")
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Segoe UI",12,600))
        name_lbl.setStyleSheet(f"color:#e2e8f0;background:transparent;")
        top.addWidget(icon_lbl); top.addWidget(name_lbl); top.addStretch()

        # Status dot
        self._dot = QFrame()
        self._dot.setFixedSize(10,10)
        self._set_dot("disconnected")
        top.addWidget(self._dot)
        layout.addLayout(top)

        # Info line
        self._info_lbl = QLabel("—")
        self._info_lbl.setFont(QFont("Consolas",10))
        self._info_lbl.setStyleSheet("color:#64748b;background:transparent;")
        layout.addWidget(self._info_lbl)

        # Status label
        self._status_lbl = QLabel("Disconnected")
        self._status_lbl.setFont(QFont("Segoe UI",10,600))
        self._status_lbl.setStyleSheet("color:#64748b;background:transparent;")
        layout.addWidget(self._status_lbl)

    def _set_dot(self, state):
        colors = {
            "connected":    "#22c55e",
            "disconnected": "#3d0a0a",
            "warning":      "#eab308",
            "error":        "#ef4444",
        }
        c = colors.get(state,"#3d0a0a")
        self._dot.setStyleSheet(
            f"QFrame{{background:{c};border-radius:5px;border:none;}}")

    def set_connected(self, ip="", port="", extra=""):
        self._set_dot("connected")
        self.setStyleSheet(
            f"QFrame{{background:#20242e;border:1px solid {self._color}44;"
            f"border-radius:8px;}}")
        info = f"{ip}:{port}" if ip else extra
        self._info_lbl.setText(info)
        self._info_lbl.setStyleSheet("color:#94a3b8;background:transparent;")
        self._status_lbl.setText("● Connected")
        self._status_lbl.setStyleSheet("color:#22c55e;background:transparent;font-weight:600;")

    def set_disconnected(self, info=""):
        self._set_dot("disconnected")
        self.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:8px;}")
        self._info_lbl.setText(info if info else "—")
        self._info_lbl.setStyleSheet("color:#64748b;background:transparent;")
        self._status_lbl.setText("○ Disconnected")
        self._status_lbl.setStyleSheet("color:#64748b;background:transparent;")

    def set_warning(self, msg=""):
        self._set_dot("warning")
        self._status_lbl.setText(f"⚠ {msg}")
        self._status_lbl.setStyleSheet("color:#eab308;background:transparent;font-weight:600;")


class SummaryPanel(QWidget):
    def __init__(self, settings_ref=None):
        super().__init__()
        self._settings = settings_ref or {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#1a1d24;border:none;")
        inner  = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16,14,16,14)
        layout.setSpacing(14)

        self._build_header(layout)
        self._build_cards(layout)
        layout.addWidget(divider())
        self._build_info(layout)
        layout.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(scroll)

        # Refresh timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _sh(self, layout, title):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(lbl(title,"#64748b",10,True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#3a4055;max-height:1px;")
        row.addWidget(line,1)
        layout.addLayout(row)

    def _build_header(self, layout):
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:8px;}")
        hv = QHBoxLayout(hdr); hv.setContentsMargins(16,14,16,14)

        left = QVBoxLayout(); left.setSpacing(4)
        title = QLabel("Hardware Configuration")
        title.setFont(QFont("Segoe UI",16,600))
        title.setStyleSheet("color:#e2e8f0;background:transparent;")
        self._ts_lbl = lbl("—","#64748b",11)
        left.addWidget(title); left.addWidget(self._ts_lbl)
        hv.addLayout(left,1)

        # Connected count
        right = QVBoxLayout(); right.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._conn_count = QLabel("0 / 7")
        self._conn_count.setFont(QFont("Consolas",22,700))
        self._conn_count.setStyleSheet("color:#4a9eff;background:transparent;")
        self._conn_lbl = lbl("devices connected","#64748b",10)
        self._conn_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._conn_count); right.addWidget(self._conn_lbl)
        hv.addLayout(right)
        layout.addWidget(hdr)

    def _build_cards(self, layout):
        self._sh(layout,"DEVICE STATUS")

        self._cards = {}
        devices = [
            ("psu",   "Power Supply",  "⚡", "#3b82f6"),
            ("hxp",   "Hexapod",       "🔬", "#4a9eff"),
            ("lin",   "Linear Stage",  "↔",  "#38bdf8"),
            ("cart",  "Cartesian XYZ", "🤖", "#4ade80"),
            ("smu",   "SMU 2602B",     "📊", "#22c55e"),
            ("wago",  "WAGO I/O",      "🔌", "#38bdf8"),
            ("cam",   "Camera",        "📷", "#f472b6"),
        ]

        grid = QGridLayout(); grid.setSpacing(10)
        for i, (key, name, icon, color) in enumerate(devices):
            card = DeviceCard(name, icon, color)
            self._cards[key] = card
            grid.addWidget(card, i//2, i%2)

        # ถ้าจำนวน device คี่ ให้ใส่ placeholder
        if len(devices) % 2 != 0:
            placeholder = QFrame()
            placeholder.setStyleSheet("QFrame{background:transparent;border:none;}")
            grid.addWidget(placeholder, len(devices)//2, 1)

        layout.addLayout(grid)

    def _build_info(self, layout):
        self._sh(layout,"SYSTEM INFO")
        info_frame = QFrame()
        info_frame.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        iv = QHBoxLayout(info_frame); iv.setContentsMargins(16,10,16,10); iv.setSpacing(32)

        for label, attr in [
            ("Python",     "python"),
            ("PyQt6",      "pyqt"),
            ("pypylon",    "pylon"),
            ("pymodbus",   "modbus"),
        ]:
            col = QVBoxLayout(); col.setSpacing(3)
            col.addWidget(lbl(label,"#64748b",9,True))
            val = lbl("checking...","#94a3b8",11)
            setattr(self, f"_{attr}_lbl", val)
            col.addWidget(val)
            iv.addLayout(col)

        iv.addStretch()
        layout.addWidget(info_frame)
        self._check_deps()

    def _check_deps(self):
        import sys
        getattr(self,"_python_lbl").setText(
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

        try:
            from PyQt6.QtCore import QT_VERSION_STR
            getattr(self,"_pyqt_lbl").setText(QT_VERSION_STR)
            getattr(self,"_pyqt_lbl").setStyleSheet("color:#22c55e;font-size:11px;")
        except:
            getattr(self,"_pyqt_lbl").setText("not found")
            getattr(self,"_pyqt_lbl").setStyleSheet("color:#ef4444;font-size:11px;")

        try:
            import pypylon
            getattr(self,"_pylon_lbl").setText("installed")
            getattr(self,"_pylon_lbl").setStyleSheet("color:#22c55e;font-size:11px;")
        except:
            getattr(self,"_pylon_lbl").setText("not installed")
            getattr(self,"_pylon_lbl").setStyleSheet("color:#eab308;font-size:11px;")

        try:
            import pymodbus
            getattr(self,"_modbus_lbl").setText(pymodbus.__version__)
            getattr(self,"_modbus_lbl").setStyleSheet("color:#22c55e;font-size:11px;")
        except:
            getattr(self,"_modbus_lbl").setText("not installed")
            getattr(self,"_modbus_lbl").setStyleSheet("color:#eab308;font-size:11px;")

    def _refresh(self):
        """อ่าน settings แล้ว update card status"""
        self._ts_lbl.setText(
            f"Last updated: {datetime.datetime.now().strftime('%H:%M:%S')}")

        connected = 0
        total = len(self._cards)

        # PSU
        psu_list = self._settings.get("power_supplies", [])
        if psu_list and psu_list[0].get("ip",""):
            self._cards["psu"].set_connected(
                psu_list[0].get("ip",""), psu_list[0].get("port",5025))
            connected += 1
        else:
            self._cards["psu"].set_disconnected("No IP configured")

        # Hexapod
        hxp = self._settings.get("hexapods", [{}])
        if hxp and hxp[0].get("ip",""):
            self._cards["hxp"].set_connected(
                hxp[0].get("ip",""), hxp[0].get("port",50000),
                hxp[0].get("orientation",""))
            connected += 1
        else:
            self._cards["hxp"].set_disconnected("No IP configured")

        # Linear Stage
        lin = self._settings.get("linear_stage", {})
        if lin.get("ip",""):
            self._cards["lin"].set_connected(lin.get("ip",""), lin.get("port",50000))
            connected += 1
        else:
            self._cards["lin"].set_disconnected("No IP configured")

        # Cartesian
        cart = self._settings.get("cartesian", {})
        if cart.get("ip",""):
            self._cards["cart"].set_connected(cart.get("ip",""), cart.get("port",50000))
            connected += 1
        else:
            self._cards["cart"].set_disconnected("No IP configured")

        # SMU
        smu = self._settings.get("smu", {})
        if smu.get("ip",""):
            self._cards["smu"].set_connected(smu.get("ip",""), smu.get("port",5025))
            connected += 1
        else:
            self._cards["smu"].set_disconnected("No IP configured")

        # WAGO
        wago = self._settings.get("wago", {})
        if wago.get("ip",""):
            self._cards["wago"].set_connected(wago.get("ip",""), wago.get("port",502))
            connected += 1
        else:
            self._cards["wago"].set_disconnected("No IP configured")

        # Camera
        cam = self._settings.get("camera", {})
        if cam.get("save_dir",""):
            self._cards["cam"].set_connected(extra=cam.get("save_dir",""))
            connected += 1
        else:
            self._cards["cam"].set_disconnected("Not configured")

        # Update count
        self._conn_count.setText(f"{connected} / {total}")
        color = "#22c55e" if connected == total else "#4a9eff" if connected > 0 else "#64748b"
        self._conn_count.setStyleSheet(f"color:{color};font-size:22px;font-weight:700;background:transparent;")
