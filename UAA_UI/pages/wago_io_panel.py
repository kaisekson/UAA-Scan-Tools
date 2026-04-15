"""
WAGO I/O Panel — Modbus TCP
=============================
- DI / DO side by side
- Config channel name + description
- DO: Force toggle ON/OFF
- DI: Poll state auto
- Save/Load config JSON
"""

import json, os, datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame,
    QScrollArea, QTextEdit, QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

try:
    from pymodbus.client import ModbusTcpClient
    HAS_MODBUS = True
except ImportError:
    try:
        from pymodbus.client.sync import ModbusTcpClient
        HAS_MODBUS = True
    except ImportError:
        HAS_MODBUS = False


# ══════════════════════════════════════════════
# Modbus Driver
# ══════════════════════════════════════════════

class WAGODriver:
    def __init__(self, ip, port=502, unit=1, do_read_offset=512):
        self.ip=ip; self.port=port; self.unit=unit
        self.do_read_offset = do_read_offset
        self._client=None

    def connect(self):
        if not HAS_MODBUS:
            raise RuntimeError("pymodbus not installed — pip install pymodbus")
        self._client = ModbusTcpClient(self.ip, port=self.port)
        if not self._client.connect():
            raise ConnectionError(f"Cannot connect to {self.ip}:{self.port}")

    def disconnect(self):
        if self._client:
            try: self._client.close()
            except: pass
            self._client = None

    def read_di(self, addr, count=1):
        """อ่าน DI — Discrete Input (coil read 1x)"""
        r = self._client.read_discrete_inputs(addr-1, count=count, device_id=self.unit)
        if r.isError(): return [False]*count
        return list(r.bits[:count])

    def read_do(self, addr, count=1):
        """อ่าน DO state — Read Coil (0x) ด้วย offset"""
        r = self._client.read_coils(addr - 1 + self.do_read_offset, count=count, device_id=self.unit)
        if r.isError(): return [False]*count
        return list(r.bits[:count])

    def write_do(self, addr, state):
        """เขียน DO — Write Single Coil"""
        self._client.write_coil(addr-1, state, device_id=self.unit)


class ConnectWorker(QThread):
    success = pyqtSignal()
    failed  = pyqtSignal(str)
    def __init__(self, ip, port, unit, do_read_offset=512):
        super().__init__()
        self.ip=ip; self.port=port; self.unit=unit
        self.do_read_offset=do_read_offset
    def run(self):
        try:
            d = WAGODriver(self.ip, self.port, self.unit, self.do_read_offset)
            d.connect(); d.disconnect()
            self.success.emit()
        except Exception as e: self.failed.emit(str(e))


# ══════════════════════════════════════════════
# Channel Row — DO
# ══════════════════════════════════════════════

class DORow(QFrame):
    def __init__(self, addr, name="", desc="", drv_ref=None, log_fn=None):
        super().__init__()
        self._addr   = addr
        self._drv    = drv_ref
        self._state  = False
        self._log_fn = log_fn
        self.setStyleSheet(
            "QFrame{background:#0a0c10;border:none;"
            "border-top:1px solid #1e2433;}")

        row = QHBoxLayout(self)
        row.setContentsMargins(10,5,10,5); row.setSpacing(8)

        # Address
        addr_lbl = QLabel(f"{addr:05d}")
        addr_lbl.setFixedWidth(48)
        addr_lbl.setFont(QFont("Consolas",10))
        addr_lbl.setStyleSheet("color:#4a5568;background:transparent;")
        row.addWidget(addr_lbl)

        # Name + Desc
        info = QVBoxLayout(); info.setSpacing(2)
        self.name_edit = QLineEdit(name if name else f"DO_{addr:05d}")
        self.name_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:3px;"
            "color:#c5cdd9;padding:2px 6px;font-size:11px;font-weight:600;")
        self.desc_edit = QLineEdit(desc)
        self.desc_edit.setPlaceholderText("description...")
        self.desc_edit.setStyleSheet(
            "background:transparent;border:none;"
            "color:#4a5568;padding:1px 6px;font-size:10px;")
        info.addWidget(self.name_edit)
        info.addWidget(self.desc_edit)
        row.addLayout(info, 1)

        # LED indicator
        self._led = QPushButton()
        self._led.setFixedSize(32,32)
        self._led.clicked.connect(self._toggle)
        self._set_led(False)
        row.addWidget(self._led)

        # Force button
        force_btn = QPushButton("  Force")
        force_btn.setFixedSize(64,28)
        force_btn.setStyleSheet(
            "QPushButton{background:#1a1000;border:1px solid #854f0b;"
            "border-radius:4px;color:#eab308;font-size:11px;font-weight:600;"
            "text-align:center;padding:0 8px;}"
            "QPushButton:hover{background:#eab308;color:#000;}")
        force_btn.clicked.connect(self._toggle)

        self._status_lbl = QLabel("")
        self._status_lbl.setFixedWidth(20)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("font-size:12px;background:transparent;")

        row.addWidget(force_btn)
        row.addWidget(self._status_lbl)

    def _set_led(self, on):
        self._state = on
        if on:
            self._led.setStyleSheet(
                "QPushButton{background:#22c55e;border:2px solid #22c55e;"
                "border-radius:6px;color:#000;font-size:10px;font-weight:700;}"
                "QPushButton:hover{background:#16a34a;}")
            self._led.setText("ON")
        else:
            self._led.setStyleSheet(
                "QPushButton{background:#1a0000;border:1px solid #3d0a0a;"
                "border-radius:6px;color:#4a5568;font-size:10px;font-weight:700;}"
                "QPushButton:hover{background:#3d0a0a;color:#ef4444;}")
            self._led.setText("OFF")

    def _toggle(self):
        drv = self._drv[0] if self._drv else None
        if not drv:
            self._set_status("✗","#ef4444")
            if self._log_fn: self._log_fn(f"DO {self._addr:05d} {self.name_edit.text()} — Not connected","#ef4444")
            return
        new_state = not self._state
        self._set_status("⟳","#eab308")
        try:
            drv.write_do(self._addr, new_state)
            actual = drv.read_do(self._addr, 1)[0]
            self._set_led(actual)
            if actual == new_state:
                self._set_status("✓","#22c55e")
                if self._log_fn:
                    state_str = "ON" if actual else "OFF"
                    self._log_fn(f"DO {self._addr:05d} {self.name_edit.text()} → {state_str} ✓")
            else:
                self._set_status("✗","#ef4444")
                if self._log_fn:
                    self._log_fn(
                        f"DO {self._addr:05d} {self.name_edit.text()} verify failed — "
                        f"wrote {'ON' if new_state else 'OFF'} got {'ON' if actual else 'OFF'}",
                        "#ef4444")
        except Exception as e:
            self._set_status("✗","#ef4444")
            if self._log_fn: self._log_fn(f"DO {self._addr:05d} error: {e}","#ef4444")

    def _set_status(self, symbol, color):
        self._status_lbl.setText(symbol)
        self._status_lbl.setStyleSheet(f"font-size:12px;color:{color};background:transparent;font-weight:700;")

    def set_state(self, state):
        self._set_led(state)

    def get_config(self):
        return {
            "addr": self._addr,
            "name": self.name_edit.text(),
            "desc": self.desc_edit.text(),
        }


# ══════════════════════════════════════════════
# Channel Row — DI
# ══════════════════════════════════════════════

class DIRow(QFrame):
    def __init__(self, addr, name="", desc=""):
        super().__init__()
        self._addr  = addr
        self._state = False
        self.setStyleSheet(
            "QFrame{background:#0a0c10;border:none;"
            "border-top:1px solid #1e2433;}")

        row = QHBoxLayout(self)
        row.setContentsMargins(10,5,10,5); row.setSpacing(8)

        # Address
        addr_lbl = QLabel(f"{addr:05d}")
        addr_lbl.setFixedWidth(48)
        addr_lbl.setFont(QFont("Consolas",10))
        addr_lbl.setStyleSheet("color:#4a5568;background:transparent;")
        row.addWidget(addr_lbl)

        # Name + Desc
        info = QVBoxLayout(); info.setSpacing(2)
        self.name_edit = QLineEdit(name if name else f"DI_{addr:05d}")
        self.name_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:3px;"
            "color:#c5cdd9;padding:2px 6px;font-size:11px;font-weight:600;")
        self.desc_edit = QLineEdit(desc)
        self.desc_edit.setPlaceholderText("description...")
        self.desc_edit.setStyleSheet(
            "background:transparent;border:none;"
            "color:#4a5568;padding:1px 6px;font-size:10px;")
        info.addWidget(self.name_edit)
        info.addWidget(self.desc_edit)
        row.addLayout(info, 1)

        # LED indicator (read only)
        self._led = QFrame()
        self._led.setFixedSize(32,32)
        self._led.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        row.addWidget(self._led)

        # State label
        self._state_lbl = lbl("LOW","#4a5568",9,True)
        self._state_lbl.setFixedWidth(32)
        row.addWidget(self._state_lbl)

    def set_state(self, state):
        self._state = state
        if state:
            self._led.setStyleSheet(
                "QFrame{background:#4a9eff;border:2px solid #4a9eff;border-radius:6px;}")
            self._state_lbl.setText("HIGH")
            self._state_lbl.setStyleSheet("color:#4a9eff;font-size:10px;font-weight:700;")
        else:
            self._led.setStyleSheet(
                "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
            self._state_lbl.setText("LOW")
            self._state_lbl.setStyleSheet("color:#4a5568;font-size:10px;font-weight:700;")

    def get_config(self):
        return {
            "addr": self._addr,
            "name": self.name_edit.text(),
            "desc": self.desc_edit.text(),
        }


# ══════════════════════════════════════════════
# IO Box (container)
# ══════════════════════════════════════════════

class IOBox(QFrame):
    def __init__(self, title, color, is_do=True, drv_ref=None, log_fn=None):
        super().__init__()
        self._is_do  = is_do
        self._color  = color
        self._drv    = drv_ref
        self._log_fn = log_fn
        self._rows   = []
        self.setStyleSheet(
            f"QFrame{{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(12,8,12,8)
        dot = QFrame(); dot.setFixedSize(8,8)
        dot.setStyleSheet(f"QFrame{{background:{color};border-radius:4px;border:none;}}")
        title_lbl = lbl(title, color, 11, True)
        self._count_lbl = lbl("0 channels","#4a5568",9)
        self._count_lbl.setStyleSheet(
            f"color:{color};font-size:9px;background:{color}18;"
            f"border:1px solid {color}44;border-radius:8px;padding:2px 8px;")
        hdr.addWidget(dot); hdr.addWidget(title_lbl)
        hdr.addStretch(); hdr.addWidget(self._count_lbl)
        hdr_frame = QFrame()
        hdr_frame.setStyleSheet(
            "QFrame{background:#0a0c10;border:none;border-radius:6px 6px 0 0;"
            "border-bottom:1px solid #1e2433;}")
        hdr_frame.setLayout(hdr)
        layout.addWidget(hdr_frame)

        # Column header
        col_hdr = QFrame()
        col_hdr.setStyleSheet(
            "QFrame{background:#0a0c10;border:none;border-bottom:1px solid #1e2433;}")
        ch = QHBoxLayout(col_hdr); ch.setContentsMargins(10,4,10,4); ch.setSpacing(8)
        ch.addWidget(lbl("ADDR","#4a5568",9,True)); ch.setSpacing(8)
        lbl2 = lbl("NAME / DESC","#4a5568",9,True)
        ch.addWidget(lbl2,1)
        ch.addWidget(lbl("STATE","#4a5568",9,True))
        ch.addWidget(lbl("","#4a5568",9,True))
        layout.addWidget(col_hdr)

        # Rows container
        self._rows_widget = QWidget()
        self._rows_widget.setStyleSheet("background:transparent;")
        self._rows_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0,0,0,0); self._rows_layout.setSpacing(0)
        layout.addWidget(self._rows_widget)
        layout.addStretch()

        # Footer — add/remove
        footer = QFrame()
        footer.setStyleSheet(
            "QFrame{background:#0a0c10;border:none;"
            "border-top:1px solid #1e2433;border-radius:0 0 6px 6px;}")
        fl = QHBoxLayout(footer); fl.setContentsMargins(10,6,10,6); fl.setSpacing(6)
        fl.addWidget(lbl("Add addr:","#4a5568",10))
        self._add_edit = QLineEdit("1")
        self._add_edit.setFixedWidth(64)
        self._add_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:3px 6px;font-size:11px;font-family:monospace;")
        add_btn = QPushButton("＋  Add")
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(
            "QPushButton{background:#0d1a0d;border:1px solid #22c55e;"
            "border-radius:4px;color:#22c55e;font-size:11px;font-weight:600;padding:0 10px;}"
            "QPushButton:hover{background:#22c55e;color:#000;}")
        add_btn.clicked.connect(lambda: self._add_channel())
        rem_btn = QPushButton("✕  Remove")
        rem_btn.setFixedHeight(28)
        rem_btn.setStyleSheet(
            "QPushButton{background:#1a0000;border:1px solid #3d0a0a;"
            "border-radius:4px;color:#4a5568;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{border-color:#ef4444;color:#ef4444;background:#3d0a0a;}")
        rem_btn.clicked.connect(self._remove_last)
        fl.addWidget(self._add_edit); fl.addWidget(add_btn); fl.addWidget(rem_btn)
        fl.addStretch()
        layout.addWidget(footer)

    def _add_channel(self, addr=None, name="", desc=""):
        if addr is None:
            try: addr = int(self._add_edit.text())
            except: return
        if self._is_do:
            row = DORow(addr, name, desc, self._drv, log_fn=self._log_fn)
        else:
            row = DIRow(addr, name, desc)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._count_lbl.setText(f"{len(self._rows)} channels")
        self._update_add_hint()

    def _remove_last(self):
        if not self._rows: return
        row = self._rows.pop()
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self._count_lbl.setText(f"{len(self._rows)} channels")
        self._update_add_hint()

    def _update_add_hint(self):
        if self._rows:
            last = self._rows[-1]._addr
            self._add_edit.setText(str(last + 1))

    def poll(self, drv):
        """อ่านค่าทุก channel"""
        for row in self._rows:
            try:
                if self._is_do:
                    states = drv.read_do(row._addr, 1)
                    row.set_state(states[0])
                else:
                    states = drv.read_di(row._addr, 1)
                    row.set_state(states[0])
            except: pass

    def get_config(self):
        return [r.get_config() for r in self._rows]

    def load_config(self, channels):
        # clear all existing rows
        for row in list(self._rows):
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._count_lbl.setText("0 channels")
        # add from config
        for ch in channels:
            self._add_channel(
                ch.get("addr", 1),
                ch.get("name", ""),
                ch.get("desc", ""))


# ══════════════════════════════════════════════
# WAGO IO Panel
# ══════════════════════════════════════════════

class WAGOIOPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._drv = [None]

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#111318;border:none;")
        inner  = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16,14,16,14); layout.setSpacing(10)

        self._build_connection(layout)
        self._build_io(layout)
        layout.addWidget(divider())
        self._build_log(layout)
        layout.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(scroll)

        self._config_path = ""

        # Poll timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)

        # Auto load config จาก settings.json
        self._auto_load()

    def _auto_load(self):
        """โหลด wago config อัตโนมัติจาก path ที่บันทึกไว้"""
        try:
            if os.path.exists("settings.json"):
                with open("settings.json") as f:
                    data = json.load(f)
                path = data.get("wago_config_path","")
                if path and os.path.exists(path):
                    self._config_path = path
                    self._load_from_path(path)
        except: pass

    def _sh(self, layout, title, extra=None):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(lbl(title,"#4a5568",10,True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#1e2433;max-height:1px;")
        row.addWidget(line,1)
        if extra: row.addWidget(extra)
        layout.addLayout(row)

    def _log_msg(self, msg, color="#22c55e"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:{color};">[{ts}]</span> '
            f'<span style="color:#8892a4;">{msg}</span>')

    # ── Connection ────────────────────────────
    def _build_connection(self, layout):
        self._sh(layout,"CONNECTION")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(8)

        grid = QHBoxLayout(); grid.setSpacing(10)
        for attr, lbl_txt, default, w in [
            ("ip_edit",     "IP Address",     "192.168.1.50", 3),
            ("port_edit",   "Port",           "502",          1),
            ("unit_edit",   "Unit ID",        "1",            1),
            ("offset_edit", "DO Read Offset", "512",          1),
        ]:
            f  = QFrame(); fv = QVBoxLayout(f)
            fv.setContentsMargins(0,0,0,0); fv.setSpacing(3)
            fv.addWidget(lbl(lbl_txt,"#4a5568",10))
            e  = QLineEdit(default)
            e.setStyleSheet(
                "border-left:2px solid #4a9eff;background:#161b22;"
                "border-top:1px solid #1e2433;border-right:1px solid #1e2433;"
                "border-bottom:1px solid #1e2433;border-radius:4px;"
                "color:#c5cdd9;padding:5px 8px;font-size:12px;")
            setattr(self,attr,e); fv.addWidget(e); grid.addWidget(f,w)
        v.addLayout(grid)

        cr = QHBoxLayout(); cr.setSpacing(8)
        self.conn_btn = QPushButton("⟳  Connect")
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(
            "QPushButton{background:#0d1520;border:1px solid #4a9eff;"
            "border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}"
            "QPushButton:disabled{border-color:#1e2433;color:#2a3444;background:#0a0c10;}")
        self.conn_btn.clicked.connect(self._connect)
        self.status_lbl = lbl("○  Disconnected","#4a5568",12)
        cr.addWidget(self.conn_btn); cr.addWidget(self.status_lbl)

        # Poll controls
        cr.addStretch()
        poll_btn = QPushButton("⟳ Poll all")
        poll_btn.setFixedHeight(28)
        poll_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#8892a4;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        poll_btn.clicked.connect(self._poll)
        cr.addWidget(poll_btn)
        cr.addWidget(lbl("Interval","#4a5568",10))
        self.poll_edit = QLineEdit("500"); self.poll_edit.setFixedWidth(50)
        self.poll_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:3px 6px;font-size:11px;font-family:monospace;")
        cr.addWidget(self.poll_edit)
        cr.addWidget(lbl("ms","#4a5568",10))

        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet("color:#1e2433;"); f.setFixedWidth(1)
        cr.addWidget(f)

        save_btn = QPushButton("💾 Save")
        save_btn.setFixedHeight(28)
        save_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#8892a4;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{border-color:#22c55e;color:#22c55e;}")
        save_btn.clicked.connect(self._save_config)

        load_btn = QPushButton("📂 Load")
        load_btn.setFixedHeight(28)
        load_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#8892a4;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        load_btn.clicked.connect(self._load_config)
        cr.addWidget(save_btn); cr.addWidget(load_btn)
        v.addLayout(cr)
        layout.addWidget(card)

    # ── IO Boxes ──────────────────────────────
    def _build_io(self, layout):
        self._sh(layout,"I/O CHANNELS")
        row = QHBoxLayout(); row.setSpacing(12)
        self._do_box = IOBox("DIGITAL OUTPUT", "#22c55e", is_do=True,  drv_ref=self._drv, log_fn=self._log_msg)
        self._di_box = IOBox("DIGITAL INPUT",  "#4a9eff", is_do=False, drv_ref=self._drv, log_fn=self._log_msg)
        row.addWidget(self._do_box)
        row.addWidget(self._di_box)
        layout.addLayout(row)

    # ── Log ───────────────────────────────────
    def _build_log(self, layout):
        self._sh(layout,"RESPONSE LOG")
        self._log = QTextEdit()
        self._log.setReadOnly(True); self._log.setFixedHeight(70)
        self._log.setStyleSheet(
            "QTextEdit{background:#0a0c10;border:1px solid #1e2433;border-radius:5px;"
            "color:#4a5568;font-size:11px;font-family:Consolas,monospace;}")
        layout.addWidget(self._log)

    # ── Connect ───────────────────────────────
    def _connect(self):
        ip     = self.ip_edit.text().strip()
        port   = int(self.port_edit.text() or 502)
        unit   = int(self.unit_edit.text() or 1)
        offset = int(self.offset_edit.text() or 512)
        if not ip:
            self.status_lbl.setText("✗  Enter IP")
            self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;"); return
        self.conn_btn.setEnabled(False)
        self.status_lbl.setText("○  Connecting...")
        self.status_lbl.setStyleSheet("color:#eab308;font-size:12px;")
        self._worker = ConnectWorker(ip, port, unit, offset)
        self._worker.success.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self):
        ip     = self.ip_edit.text().strip()
        port   = int(self.port_edit.text() or 502)
        unit   = int(self.unit_edit.text() or 1)
        offset = int(self.offset_edit.text() or 512)
        drv    = WAGODriver(ip, port, unit, offset)
        try: drv.connect(); self._drv[0] = drv
        except Exception as e:
            self._log_msg(str(e),"#ef4444"); return
        self.status_lbl.setText("●  Connected")
        self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.conn_btn.setText("✗  Disconnect"); self.conn_btn.setEnabled(True)
        self.conn_btn.clicked.disconnect()
        self.conn_btn.clicked.connect(self._disconnect)
        self._log_msg(f"Connected → WAGO Modbus TCP {ip}:{port}")
        # Start poll timer
        interval = int(self.poll_edit.text() or 500)
        self._poll_timer.start(interval)

    def _on_fail(self, err):
        self.status_lbl.setText(f"✗  {err}")
        self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;")
        self.conn_btn.setEnabled(True)
        self._log_msg(f"Failed: {err}","#ef4444")

    def _disconnect(self):
        self._poll_timer.stop()
        if self._drv[0]:
            try: self._drv[0].disconnect()
            except: pass
            self._drv[0] = None
        self.status_lbl.setText("○  Disconnected")
        self.status_lbl.setStyleSheet("color:#4a5568;font-size:12px;")
        self.conn_btn.setText("⟳  Connect")
        self.conn_btn.clicked.disconnect()
        self.conn_btn.clicked.connect(self._connect)
        self._log_msg("Disconnected","#4a5568")

    # ── Poll ─────────────────────────────────
    def _poll(self):
        drv = self._drv[0]
        if not drv: return
        try:
            self._do_box.poll(drv)
            self._di_box.poll(drv)
        except Exception as e:
            self._log_msg(str(e),"#ef4444")

    # ── Save/Load config ──────────────────────
    def _save_config(self):
        default = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "wago_io.json")
        path, _ = QFileDialog.getSaveFileName(
            self,"Save IO Config", default, "JSON (*.json)")
        if not path: return
        data = {
            "ip":             self.ip_edit.text().strip(),
            "port":           int(self.port_edit.text() or 502),
            "unit":           int(self.unit_edit.text() or 1),
            "do_read_offset": int(self.offset_edit.text() or 512),
            "poll_interval":  int(self.poll_edit.text() or 500),
            "do": self._do_box.get_config(),
            "di": self._di_box.get_config(),
        }
        with open(path,"w") as f: json.dump(data,f,indent=2)
        self._config_path = path
        # บันทึก path ลง settings.json
        self._save_path_to_settings(path)
        self._log_msg(f"Config saved → {os.path.basename(path)}")

    def _load_config(self):
        default = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "wago_io.json")
        path, _ = QFileDialog.getOpenFileName(
            self,"Load IO Config", default, "JSON (*.json)")
        if not path: return
        self._load_from_path(path)
        self._config_path = path
        self._save_path_to_settings(path)

    def _load_from_path(self, path):
        """โหลด config จาก path โดยตรง ใช้ได้ทั้ง manual และ auto load"""
        if not path or not os.path.exists(path): return
        try:
            with open(path) as f: data = json.load(f)
            self.ip_edit.setText(data.get("ip",""))
            self.port_edit.setText(str(data.get("port",502)))
            self.unit_edit.setText(str(data.get("unit",1)))
            self.offset_edit.setText(str(data.get("do_read_offset",512)))
            self.poll_edit.setText(str(data.get("poll_interval",500)))
            do_list = data.get("do",[])
            di_list = data.get("di",[])
            self._do_box.load_config(do_list)
            self._di_box.load_config(di_list)
            self._log_msg(
                f"Config loaded ← {os.path.basename(path)} "
                f"({len(do_list)} DO, {len(di_list)} DI)")
        except Exception as e:
            self._log_msg(f"Load failed: {e}","#ef4444")

    def _save_path_to_settings(self, path):
        """บันทึก path ของ wago config ลง settings.json"""
        try:
            cfg_path = "settings.json"
            data = {}
            if os.path.exists(cfg_path):
                with open(cfg_path) as f: data = json.load(f)
            data["wago_config_path"] = path
            with open(cfg_path,"w") as f: json.dump(data,f,indent=2)
        except: pass

    # ── Settings ──────────────────────────────
    def get_settings(self):
        return {
            "ip":   self.ip_edit.text().strip(),
            "port": int(self.port_edit.text() or 502),
            "unit": int(self.unit_edit.text() or 1),
        }

    def load_settings(self, data):
        self.ip_edit.setText(data.get("ip",""))
        self.port_edit.setText(str(data.get("port",502)))
        self.unit_edit.setText(str(data.get("unit",1)))