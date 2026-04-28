"""
CCS PD3-10024-8-EI Lighting Controller Panel
==============================================
- Connect via Ethernet TCP/IP
- 4 channel control (intensity 0-255 per channel)
- Channel name + enable toggle
- All ON / All OFF quick actions
- Read back channel values from controller
- Command log

Protocol: CCS ASCII over TCP
  Set: "LS {ch},{val}\\r\\n"   ch=1-8, val=0-255
  Get: "LG {ch}\\r\\n"
  All off: "LOFF\\r\\n"
  All on:  "LON\\r\\n"
  Response: "OK\\r\\n" or "NG\\r\\n"

NOTE: Exact command set varies by firmware.
      Adjust CMD_SET / CMD_GET if your unit differs.
"""

import socket
import time
import datetime
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame,
    QScrollArea, QTextEdit, QSlider, QSpinBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider


# ══════════════════════════════════════════════
# Driver
# ══════════════════════════════════════════════

class CCSDriver:
    CMD_SET = "LS {ch},{val}\r\n"
    CMD_GET = "LG {ch}\r\n"
    CMD_OFF = "LOFF\r\n"
    CMD_ON  = "LON\r\n"
    TIMEOUT = 2.0

    def __init__(self, ip="192.168.0.10", port=10001):
        self.ip   = ip
        self.port = port
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.TIMEOUT)
        self._sock.connect((self.ip, self.port))

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    @property
    def is_connected(self): return self._sock is not None

    def _send(self, cmd: str) -> str:
        if not self._sock:
            raise ConnectionError("Not connected")
        with self._lock:
            self._sock.sendall(cmd.encode())
            resp = b""
            deadline = time.time() + self.TIMEOUT
            while b"\n" not in resp:
                if time.time() > deadline:
                    raise TimeoutError("No response")
                chunk = self._sock.recv(64)
                if not chunk:
                    raise ConnectionError("Connection closed")
                resp += chunk
            return resp.decode(errors="replace").strip()

    def set_intensity(self, ch: int, val: int) -> bool:
        resp = self._send(self.CMD_SET.format(ch=ch, val=val))
        return resp.upper().startswith("OK")

    def get_intensity(self, ch: int) -> int:
        resp = self._send(self.CMD_GET.format(ch=ch))
        try: return int(resp.split(",")[-1])
        except: return -1

    def all_off(self) -> bool:
        return self._send(self.CMD_OFF).upper().startswith("OK")

    def all_on(self) -> bool:
        return self._send(self.CMD_ON).upper().startswith("OK")

    def ping(self) -> bool:
        try: self.get_intensity(1); return True
        except: return False


# ══════════════════════════════════════════════
# Workers
# ══════════════════════════════════════════════

class ConnectWorker(QThread):
    success = pyqtSignal(object)
    failed  = pyqtSignal(str)

    def __init__(self, ip, port):
        super().__init__()
        self.ip = ip; self.port = port

    def run(self):
        try:
            d = CCSDriver(self.ip, self.port)
            d.connect()
            d.ping()
            self.success.emit(d)
        except Exception as e:
            self.failed.emit(str(e))


class SetIntensityWorker(QThread):
    done  = pyqtSignal(int, int, bool)   # ch, val, ok
    error = pyqtSignal(str)

    def __init__(self, drv, ch, val):
        super().__init__()
        self._drv = drv; self._ch = ch; self._val = val

    def run(self):
        try:
            ok = self._drv.set_intensity(self._ch, self._val)
            self.done.emit(self._ch, self._val, ok)
        except Exception as e:
            self.error.emit(str(e))


# ══════════════════════════════════════════════
# Channel Widget (1 channel strip)
# ══════════════════════════════════════════════

CHANNEL_DEFAULTS = [
    ("White",    True,  120),
    ("Red",      False,   0),
    ("Green",    False,   0),
    ("Blue",     False,   0),
]


class ChannelStrip(QFrame):
    intensityChanged = pyqtSignal(int, int)   # ch (1-based), value

    def __init__(self, ch_index: int, label: str, default_on: bool, default_val: int):
        super().__init__()
        self._ch_index  = ch_index   # 0-based
        self._updating  = False

        self.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        self.setFixedWidth(148)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        # Channel label
        ch_lbl = QLabel(f"CH {ch_index + 1}")
        ch_lbl.setFont(QFont("Consolas", 9))
        ch_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ch_lbl.setStyleSheet("color:#4a5568;background:transparent;")
        v.addWidget(ch_lbl)

        # Color name
        name_lbl = QLabel(label)
        name_lbl.setFont(QFont("Segoe UI", 11, 600))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("color:#c5cdd9;background:transparent;")
        v.addWidget(name_lbl)

        # Vertical slider
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 255)
        self.slider.setValue(default_val if default_on else 0)
        self.slider.setFixedHeight(150)
        self.slider.setStyleSheet("""
            QSlider::groove:vertical {
                background: #1e2433; width: 6px; border-radius: 3px;
            }
            QSlider::handle:vertical {
                background: #4a9eff; width: 16px; height: 16px;
                border-radius: 8px; margin: 0 -5px;
            }
            QSlider::sub-page:vertical {
                background: #4a9eff; border-radius: 3px;
            }
        """)
        self.slider.valueChanged.connect(self._on_slider)
        v.addWidget(self.slider, alignment=Qt.AlignmentFlag.AlignCenter)

        # Value spinbox
        self.spinbox = QSpinBox()
        self.spinbox.setRange(0, 255)
        self.spinbox.setValue(default_val if default_on else 0)
        self.spinbox.setStyleSheet(
            "QSpinBox{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#c5cdd9;padding:3px 5px;"
            "font-size:11px;font-family:Consolas;}"
            "QSpinBox::up-button,QSpinBox::down-button{width:14px;}")
        self.spinbox.valueChanged.connect(self._on_spin)
        v.addWidget(self.spinbox)

        # Enable checkbox
        self.enable_cb = QCheckBox("Enable")
        self.enable_cb.setChecked(default_on)
        self.enable_cb.setStyleSheet(
            "QCheckBox{color:#8892a4;font-size:11px;background:transparent;}"
            "QCheckBox::indicator{width:14px;height:14px;border:1px solid #3a4055;"
            "border-radius:3px;background:#161b22;}"
            "QCheckBox::indicator:checked{background:#4a9eff;border-color:#4a9eff;}")
        self.enable_cb.stateChanged.connect(self._on_enable)
        v.addWidget(self.enable_cb, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status dot
        self._status = QLabel("○")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color:#4a5568;font-size:11px;background:transparent;")
        v.addWidget(self._status)

    # ── internal sync ─────────────────────────

    def _on_slider(self, val: int):
        if self._updating: return
        self._updating = True
        self.spinbox.setValue(val)
        self._updating = False
        if self.enable_cb.isChecked():
            self.intensityChanged.emit(self._ch_index + 1, val)

    def _on_spin(self, val: int):
        if self._updating: return
        self._updating = True
        self.slider.setValue(val)
        self._updating = False
        if self.enable_cb.isChecked():
            self.intensityChanged.emit(self._ch_index + 1, val)

    def _on_enable(self, state):
        enabled = state == Qt.CheckState.Checked.value
        val = self.slider.value() if enabled else 0
        self.intensityChanged.emit(self._ch_index + 1, val)

    # ── public API ────────────────────────────

    def set_value(self, val: int, emit=False):
        self._updating = True
        self.slider.setValue(val)
        self.spinbox.setValue(val)
        self._updating = False
        if emit:
            self.intensityChanged.emit(self._ch_index + 1, val)

    def value(self) -> int:
        return self.slider.value()

    def is_enabled(self) -> bool:
        return self.enable_cb.isChecked()

    def set_status(self, ok: bool | None):
        if ok is None:
            self._status.setText("○")
            self._status.setStyleSheet("color:#4a5568;font-size:11px;background:transparent;")
        elif ok:
            self._status.setText("✓")
            self._status.setStyleSheet("color:#22c55e;font-size:11px;background:transparent;font-weight:700;")
        else:
            self._status.setText("✗")
            self._status.setStyleSheet("color:#ef4444;font-size:11px;background:transparent;font-weight:700;")


# ══════════════════════════════════════════════
# CCS Lighting Panel
# ══════════════════════════════════════════════

class CCSLightingPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._drv: CCSDriver | None = None
        self._ch_strips: list[ChannelStrip] = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#111318;border:none;")
        inner  = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self._build_connection(layout)
        self._build_channels(layout)
        self._build_actions(layout)
        layout.addWidget(divider())
        self._build_log(layout)
        layout.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    # ── section header helper ─────────────────

    def _sh(self, layout, title, extra=None):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(lbl(title, "#4a5568", 10, True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#1e2433;max-height:1px;")
        row.addWidget(line, 1)
        if extra: row.addWidget(extra)
        layout.addLayout(row)

    def _log_msg(self, msg: str, color="#22c55e"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:{color};">[{ts}]</span> '
            f'<span style="color:#8892a4;">{msg}</span>')

    # ── Connection ────────────────────────────

    def _build_connection(self, layout):
        self._sh(layout, "CONNECTION")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(8)

        # IP / Port / Model row
        row = QHBoxLayout(); row.setSpacing(10)

        ip_f  = QFrame(); ip_v = QVBoxLayout(ip_f)
        ip_v.setContentsMargins(0,0,0,0); ip_v.setSpacing(3)
        ip_v.addWidget(lbl("IP Address", "#4a5568", 10))
        self.ip_edit = QLineEdit("192.168.0.10")
        self.ip_edit.setStyleSheet(
            "border-left:2px solid #4a9eff;background:#161b22;"
            "border-top:1px solid #1e2433;border-right:1px solid #1e2433;"
            "border-bottom:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:5px 8px;font-size:12px;")
        ip_v.addWidget(self.ip_edit); row.addWidget(ip_f, 3)

        pt_f  = QFrame(); pt_v = QVBoxLayout(pt_f)
        pt_v.setContentsMargins(0,0,0,0); pt_v.setSpacing(3)
        pt_v.addWidget(lbl("Port", "#4a5568", 10))
        self.port_edit = QLineEdit("10001")
        self.port_edit.setStyleSheet(
            "border-left:2px solid #4a9eff;background:#161b22;"
            "border-top:1px solid #1e2433;border-right:1px solid #1e2433;"
            "border-bottom:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:5px 8px;font-size:12px;")
        pt_v.addWidget(self.port_edit); row.addWidget(pt_f, 1)

        mdl_f = QFrame(); mdl_v = QVBoxLayout(mdl_f)
        mdl_v.setContentsMargins(0,0,0,0); mdl_v.setSpacing(3)
        mdl_v.addWidget(lbl("Model", "#4a5568", 10))
        self.model_lbl = lbl("PD3-10024-8-EI", "#8892a4", 11)
        self.model_lbl.setFont(QFont("Consolas", 10))
        mdl_v.addWidget(self.model_lbl); row.addWidget(mdl_f, 2)

        v.addLayout(row)

        # Connect row
        cr = QHBoxLayout(); cr.setSpacing(10)
        self.conn_btn = QPushButton("⟳  Connect")
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(
            "QPushButton{background:#0d1520;border:1px solid #4a9eff;"
            "border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}"
            "QPushButton:disabled{border-color:#1e2433;color:#2a3444;background:#0a0c10;}")
        self.conn_btn.clicked.connect(self._connect)

        self.ping_btn = QPushButton("Ping")
        self.ping_btn.setFixedHeight(30)
        self.ping_btn.setFixedWidth(60)
        self.ping_btn.setEnabled(False)
        self.ping_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#8892a4;font-size:11px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}"
            "QPushButton:disabled{color:#2a3444;border-color:#1e2433;}")
        self.ping_btn.clicked.connect(self._ping)

        self.status_lbl = lbl("○  Disconnected", "#4a5568", 12)

        cr.addWidget(self.conn_btn)
        cr.addWidget(self.ping_btn)
        cr.addWidget(self.status_lbl)
        cr.addStretch()
        v.addLayout(cr)
        layout.addWidget(card)

    # ── Channel strips ────────────────────────

    def _build_channels(self, layout):
        self._sh(layout, "CHANNELS  (4 ch)")
        ch_row = QHBoxLayout(); ch_row.setSpacing(8)
        ch_row.setAlignment(Qt.AlignmentFlag.AlignLeft)

        for i, (name, default_on, default_val) in enumerate(CHANNEL_DEFAULTS):
            strip = ChannelStrip(i, name, default_on, default_val)
            strip.intensityChanged.connect(self._on_intensity_changed)
            ch_row.addWidget(strip)
            self._ch_strips.append(strip)

        layout.addLayout(ch_row)

    # ── Quick actions ─────────────────────────

    def _build_actions(self, layout):
        self._sh(layout, "QUICK ACTIONS")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        h = QHBoxLayout(card); h.setContentsMargins(12, 8, 12, 8); h.setSpacing(8)

        def _ab(text, color):
            b = QPushButton(text); b.setFixedHeight(30)
            bg = {"#22c55e": "#1a3a1a", "#ef4444": "#1a0000",
                  "#4a9eff": "#0d1520", "#eab308": "#1a1000"}.get(color, "#161b22")
            b.setStyleSheet(
                f"QPushButton{{background:{bg};border:1px solid {color};"
                f"border-radius:5px;color:{color};font-size:12px;font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{color};color:#000;}}"
                f"QPushButton:disabled{{border-color:#1e2433;color:#2a3444;background:#0a0c10;}}")
            return b

        self.all_off_btn  = _ab("All OFF",    "#ef4444")
        self.all_on_btn   = _ab("All ON",     "#22c55e")
        self.read_all_btn = _ab("Read All",   "#4a9eff")

        self.all_off_btn.clicked.connect(self._all_off)
        self.all_on_btn.clicked.connect(self._all_on)
        self.read_all_btn.clicked.connect(self._read_all)

        for b in [self.all_off_btn, self.all_on_btn, self.read_all_btn]:
            b.setEnabled(False)
            h.addWidget(b)
        h.addStretch()
        layout.addWidget(card)

    # ── Log ───────────────────────────────────

    def _build_log(self, layout):
        self._sh(layout, "RESPONSE LOG")
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(80)
        self._log.setStyleSheet(
            "QTextEdit{background:#0a0c10;border:1px solid #1e2433;"
            "border-radius:5px;color:#4a5568;"
            "font-size:11px;font-family:Consolas,monospace;}")
        layout.addWidget(self._log)

    # ── Connect / Disconnect ──────────────────

    def _set_controls_enabled(self, ok: bool):
        self.ping_btn.setEnabled(ok)
        for b in [self.all_off_btn, self.all_on_btn, self.read_all_btn]:
            b.setEnabled(ok)
        for s in self._ch_strips:
            s.setEnabled(ok)

    def _connect(self):
        if self._drv and self._drv.is_connected:
            self._drv.disconnect()
            self._drv = None
            self.conn_btn.setText("⟳  Connect")
            self.conn_btn.clicked.disconnect()
            self.conn_btn.clicked.connect(self._connect)
            self.status_lbl.setText("○  Disconnected")
            self.status_lbl.setStyleSheet("color:#4a5568;font-size:12px;")
            self._set_controls_enabled(False)
            self._log_msg("Disconnected", "#4a5568")
            return

        ip   = self.ip_edit.text().strip()
        port = int(self.port_edit.text() or "10001")
        self.conn_btn.setEnabled(False)
        self.status_lbl.setText("○  Connecting...")
        self.status_lbl.setStyleSheet("color:#eab308;font-size:12px;")

        self._cw = ConnectWorker(ip, port)
        self._cw.success.connect(self._on_connected)
        self._cw.failed.connect(self._on_connect_failed)
        self._cw.start()

    def _on_connected(self, drv: CCSDriver):
        self._drv = drv
        self.status_lbl.setText(f"●  Connected — {drv.ip}:{drv.port}")
        self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.conn_btn.setText("✗  Disconnect")
        self.conn_btn.setEnabled(True)
        self._set_controls_enabled(True)
        self._log_msg(f"Connected → {drv.ip}:{drv.port}")
        # reset all strip status dots
        for s in self._ch_strips:
            s.set_status(None)

    def _on_connect_failed(self, err: str):
        self.status_lbl.setText(f"✗  {err}")
        self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;")
        self.conn_btn.setEnabled(True)
        self._log_msg(f"Failed: {err}", "#ef4444")

    def _ping(self):
        if not self._drv: return
        ok = self._drv.ping()
        self._log_msg("Ping OK" if ok else "Ping failed", "#22c55e" if ok else "#ef4444")

    # ── Channel intensity event ───────────────

    def _on_intensity_changed(self, ch: int, val: int):
        if not self._drv: return
        strip = self._ch_strips[ch - 1]
        strip.set_status(None)
        try:
            ok = self._drv.set_intensity(ch, val)
            strip.set_status(ok)
            self._log_msg(f"CH{ch} = {val}  {'OK' if ok else 'NG'}", "#22c55e" if ok else "#ef4444")
        except Exception as e:
            strip.set_status(False)
            self._log_msg(str(e), "#ef4444")

    # ── Quick actions ─────────────────────────

    def _all_off(self):
        for s in self._ch_strips:
            s.set_value(0)
        if not self._drv: return
        try:
            ok = self._drv.all_off()
            self._log_msg("All channels OFF" if ok else "All OFF NG", "#22c55e" if ok else "#ef4444")
        except Exception as e:
            self._log_msg(str(e), "#ef4444")

    def _all_on(self):
        for s in self._ch_strips:
            if s.is_enabled():
                s.set_value(255)
        if not self._drv: return
        try:
            ok = self._drv.all_on()
            self._log_msg("All channels ON" if ok else "All ON NG", "#22c55e" if ok else "#ef4444")
        except Exception as e:
            self._log_msg(str(e), "#ef4444")

    def _read_all(self):
        if not self._drv: return
        for i, s in enumerate(self._ch_strips):
            try:
                val = self._drv.get_intensity(i + 1)
                if val >= 0:
                    s.set_value(val)
                    s.set_status(True)
            except Exception as e:
                s.set_status(False)
        self._log_msg("Read all channels OK")

    # ── Save / Load settings ──────────────────

    def get_settings(self):
        return {
            "ip":       self.ip_edit.text().strip(),
            "port":     int(self.port_edit.text() or "10001"),
            "channels": [
                {"name": CHANNEL_DEFAULTS[i][0], "value": s.value(), "enabled": s.is_enabled()}
                for i, s in enumerate(self._ch_strips)
            ],
        }

    def load_settings(self, data: dict):
        self.ip_edit.setText(data.get("ip", "192.168.0.10"))
        self.port_edit.setText(str(data.get("port", 10001)))
        for i, ch in enumerate(data.get("channels", [])):
            if i < len(self._ch_strips):
                s = self._ch_strips[i]
                s.set_value(ch.get("value", 0))
                s.enable_cb.setChecked(ch.get("enabled", False))
