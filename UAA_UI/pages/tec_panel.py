"""
Thorlabs TED4015 TEC Controller Panel
=======================================
- Connect via pyvisa (USBTMC over USB)
- Temperature setpoint / readback
- TEC output ON/OFF
- Current / Voltage monitor
- PID settings (collapsible)
- Auto poll every 1s
"""

import datetime
try:
    import pyvisa
    HAS_VISA = True
except ImportError:
    HAS_VISA = False

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame,
    QScrollArea, QTextEdit, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider


# ══════════════════════════════════════════════
# Driver
# ══════════════════════════════════════════════

class TECDriver:
    def __init__(self, resource_name):
        self._res  = None
        self._name = resource_name

    def connect(self):
        if not HAS_VISA:
            raise RuntimeError("pyvisa not installed — pip install pyvisa pyvisa-py")
        rm = pyvisa.ResourceManager()
        self._res = rm.open_resource(self._name)
        self._res.timeout = 3000
        self._res.write_termination  = "\n"
        self._res.read_termination   = "\n"

    def disconnect(self):
        if self._res:
            try: self._res.close()
            except: pass
            self._res = None

    def idn(self):       return self._res.query("*IDN?").strip()
    def rst(self):       self._res.write("*RST")

    # Temperature
    def set_temp(self, t):  self._res.write(f"SOUR:TEMP {t:.3f}")
    def get_setpoint(self): return float(self._res.query("SOUR:TEMP?"))
    def get_temp(self):     return float(self._res.query("MEAS:TEMP?"))

    # Output
    def output_on(self):    self._res.write("OUTP ON")
    def output_off(self):   self._res.write("OUTP OFF")
    def get_output(self):   return self._res.query("OUTP?").strip()

    # Measurements
    def get_current(self):  return float(self._res.query("MEAS:CURR?"))
    def get_voltage(self):  return float(self._res.query("MEAS:VOLT?"))

    # PID
    def set_pid(self, p, i, d):
        self._res.write(f"SOUR:TEMP:LPROP {p:.4f}")
        self._res.write(f"SOUR:TEMP:LINT  {i:.4f}")
        self._res.write(f"SOUR:TEMP:LDERIV {d:.4f}")

    def get_pid(self):
        p = float(self._res.query("SOUR:TEMP:LPROP?"))
        i = float(self._res.query("SOUR:TEMP:LINT?"))
        d = float(self._res.query("SOUR:TEMP:LDERIV?"))
        return p, i, d

    def auto_pid(self):
        self._res.write("SOUR:TEMP:LPROP:AUTO ONCE")

    def query(self, cmd): return self._res.query(cmd).strip()
    def write(self, cmd): self._res.write(cmd)


# ══════════════════════════════════════════════
# Workers
# ══════════════════════════════════════════════

class ConnectWorker(QThread):
    success = pyqtSignal(str)
    failed  = pyqtSignal(str)
    def __init__(self, resource):
        super().__init__(); self._resource = resource
    def run(self):
        try:
            d = TECDriver(self._resource)
            d.connect(); idn = d.idn(); d.disconnect()
            self.success.emit(idn)
        except Exception as e: self.failed.emit(str(e))


class PollWorker(QThread):
    result = pyqtSignal(float, float, float, float, str)  # actual, setpoint, curr, volt, outp
    error  = pyqtSignal(str)
    def __init__(self, drv):
        super().__init__(); self._drv = drv
    def run(self):
        try:
            actual   = self._drv.get_temp()
            setpoint = self._drv.get_setpoint()
            curr     = self._drv.get_current()
            volt     = self._drv.get_voltage()
            outp     = self._drv.get_output()
            self.result.emit(actual, setpoint, curr, volt, outp)
        except Exception as e: self.error.emit(str(e))


# ══════════════════════════════════════════════
# Collapsible Section
# ══════════════════════════════════════════════

class CollapsibleSection(QFrame):
    def __init__(self, title, color="#4a5568"):
        super().__init__()
        self.setStyleSheet("QFrame{background:transparent;border:none;}")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0,0,0,0)
        self._layout.setSpacing(0)

        self._btn = QPushButton(f"▶  {title}")
        self._btn.setCheckable(True)
        self._btn.setFixedHeight(30)
        self._btn.setStyleSheet(f"""
            QPushButton{{background:#0d0f14;border:1px solid #1e2433;
                border-radius:5px;color:{color};font-size:11px;font-weight:600;
                text-align:left;padding-left:12px;}}
            QPushButton:checked{{background:#111318;border-color:{color};
                border-radius:5px 5px 0 0;}}
            QPushButton:hover{{border-color:{color};}}
        """)
        self._btn.clicked.connect(self._toggle)
        self._layout.addWidget(self._btn)

        self._content = QFrame()
        self._content.setStyleSheet(
            f"QFrame{{background:#0d0f14;border:1px solid #1e2433;"
            f"border-top:none;border-radius:0 0 5px 5px;}}")
        self._content.setVisible(False)
        self._cl = QVBoxLayout(self._content)
        self._cl.setContentsMargins(12,10,12,10)
        self._cl.setSpacing(8)
        self._layout.addWidget(self._content)

    def _toggle(self, checked):
        self._content.setVisible(checked)
        label = self._btn.text()[3:]
        self._btn.setText(("▼  " if checked else "▶  ") + label)

    def add_widget(self, w): self._cl.addWidget(w)
    def add_layout(self, l): self._cl.addLayout(l)


# ══════════════════════════════════════════════
# Readback Card
# ══════════════════════════════════════════════

class ReadCard(QFrame):
    def __init__(self, label, unit, color, big=False):
        super().__init__()
        self.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(12,8,12,8); v.setSpacing(3)
        v.addWidget(lbl(label,"#4a5568",9,True))
        row = QHBoxLayout(); row.setSpacing(6)
        size = 24 if big else 18
        self._val = QLabel("—")
        self._val.setFont(QFont("Consolas",size,700))
        self._val.setStyleSheet(f"color:{color};background:transparent;")
        self._unit = lbl(unit,color,11)
        row.addWidget(self._val); row.addWidget(self._unit); row.addStretch()
        v.addLayout(row)

    def set_value(self, v, fmt=".3f"):
        self._val.setText(format(v, fmt))

    def set_warning(self, on):
        if on:
            self.setStyleSheet(
                "QFrame{background:#1a0e00;border:1px solid #854f0b;border-radius:6px;}")
        else:
            self.setStyleSheet(
                "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")


# ══════════════════════════════════════════════
# TEC Panel
# ══════════════════════════════════════════════

class TECPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._drv      = None
        self._out_on   = False

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#111318;border:none;")
        inner  = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16,14,16,14)
        layout.setSpacing(10)

        self._build_connection(layout)
        self._build_temp(layout)
        self._build_monitor(layout)
        self._build_pid(layout)
        layout.addWidget(divider())
        self._build_log(layout)
        layout.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(scroll)

        # Poll timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)

    # ── Helpers ───────────────────────────────
    def _sh(self, layout, title, extra=None):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(lbl(title,"#4a5568",10,True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#1e2433;max-height:1px;")
        row.addWidget(line,1)
        if extra: row.addWidget(extra)
        layout.addLayout(row)

    def _log_msg(self, msg, color="#4a9eff"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:{color};">[{ts}]</span> '
            f'<span style="color:#8892a4;">{msg}</span>')

    def _input_style(self, color="#4a9eff"):
        return (f"border-left:2px solid {color};background:#161b22;"
                "border-top:1px solid #1e2433;border-right:1px solid #1e2433;"
                "border-bottom:1px solid #1e2433;border-radius:4px;"
                "color:#c5cdd9;padding:5px 8px;font-size:12px;font-family:monospace;")

    # ── Connection ────────────────────────────
    def _build_connection(self, layout):
        self._sh(layout,"CONNECTION")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(8)

        # Resource selector
        row = QHBoxLayout(); row.setSpacing(10)
        f = QFrame(); fv = QVBoxLayout(f)
        fv.setContentsMargins(0,0,0,0); fv.setSpacing(3)
        fv.addWidget(lbl("USB Resource","#4a5568",10))
        self._res_combo = QComboBox()
        self._res_combo.setEditable(True)
        self._res_combo.setStyleSheet(
            "QComboBox{background:#161b22;border:1px solid #1e2433;"
            "border-left:2px solid #4a9eff;border-radius:4px;"
            "color:#c5cdd9;padding:4px 8px;font-size:12px;}"
            "QComboBox::drop-down{border:none;}"
            "QComboBox QAbstractItemView{background:#0d0f14;color:#c5cdd9;}")
        fv.addWidget(self._res_combo)
        row.addWidget(f,1)

        scan_btn = QPushButton("⟳ Scan")
        scan_btn.setFixedSize(70,30)
        scan_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#8892a4;font-size:11px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        scan_btn.clicked.connect(self._scan)
        row.addWidget(scan_btn)
        v.addLayout(row)

        cr = QHBoxLayout(); cr.setSpacing(10)
        self.conn_btn = QPushButton("⟳  Connect")
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(
            "QPushButton{background:#0d1520;border:1px solid #4a9eff;"
            "border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}"
            "QPushButton:disabled{border-color:#1e2433;color:#2a3444;background:#0a0c10;}")
        self.conn_btn.clicked.connect(self._connect)
        self.status_lbl = lbl("○  Disconnected","#4a5568",12)
        self.idn_lbl    = lbl("IDN: —","#2a3444",11)
        cr.addWidget(self.conn_btn); cr.addWidget(self.status_lbl)
        cr.addStretch(); cr.addWidget(self.idn_lbl)
        v.addLayout(cr)
        layout.addWidget(card)

        # Auto scan
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(300, self._scan)

    # ── Temperature control ───────────────────
    def _build_temp(self, layout):
        self._sh(layout,"TEMPERATURE CONTROL")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(14,12,14,12); v.setSpacing(10)

        # Setpoint row
        sp_row = QHBoxLayout(); sp_row.setSpacing(10)
        sp_row.addWidget(lbl("Setpoint","#4a5568",10))
        self._setpoint_edit = QLineEdit("25.000")
        self._setpoint_edit.setFixedWidth(100)
        self._setpoint_edit.setStyleSheet(self._input_style("#4a9eff"))
        sp_row.addWidget(self._setpoint_edit)
        sp_row.addWidget(lbl("°C","#2a3444",11))
        set_btn = QPushButton("Set")
        set_btn.setFixedHeight(30)
        set_btn.setStyleSheet(
            "QPushButton{background:#0d1520;border:1px solid #4a9eff;"
            "border-radius:4px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}")
        set_btn.clicked.connect(self._set_temp)
        sp_row.addWidget(set_btn)
        sp_row.addStretch()

        # Output ON/OFF
        self._out_btn = QPushButton("TEC OFF")
        self._out_btn.setFixedSize(90,34)
        self._set_out_style(False)
        self._out_btn.clicked.connect(self._toggle_output)
        sp_row.addWidget(self._out_btn)
        v.addLayout(sp_row)

        v.addWidget(divider())

        # Readback cards
        cards_row = QHBoxLayout(); cards_row.setSpacing(10)
        self._actual_card  = ReadCard("ACTUAL TEMP",   "°C", "#4a9eff", big=True)
        self._sp_card      = ReadCard("SETPOINT",      "°C", "#8892a4")
        self._delta_card   = ReadCard("DELTA",         "°C", "#cba6f7")
        cards_row.addWidget(self._actual_card, 2)
        cards_row.addWidget(self._sp_card,    1)
        cards_row.addWidget(self._delta_card, 1)
        v.addLayout(cards_row)
        layout.addWidget(card)

    # ── Monitor ───────────────────────────────
    def _build_monitor(self, layout):
        self._sh(layout,"TEC MONITOR")
        mon_row = QHBoxLayout(); mon_row.setSpacing(10)
        self._curr_card = ReadCard("TEC CURRENT", "A", "#22c55e")
        self._volt_card = ReadCard("TEC VOLTAGE", "V", "#eab308")
        self._outp_card = ReadCard("OUTPUT",      "",  "#4a5568")
        self._outp_card._val.setFont(QFont("Consolas",14,700))
        mon_row.addWidget(self._curr_card)
        mon_row.addWidget(self._volt_card)
        mon_row.addWidget(self._outp_card)
        layout.addLayout(mon_row)

    # ── PID (collapsible) ─────────────────────
    def _build_pid(self, layout):
        self._pid_sec = CollapsibleSection("PID SETTINGS","#cba6f7")

        pid_row = QHBoxLayout(); pid_row.setSpacing(12)
        self._pid_edits = {}
        for key, lbl_txt, default in [
            ("p", "P (Proportional)", "10.0"),
            ("i", "I (Integral)",     "5.0"),
            ("d", "D (Derivative)",   "0.0"),
        ]:
            col = QVBoxLayout(); col.setSpacing(4)
            col.addWidget(lbl(lbl_txt,"#4a5568",10))
            e = QLineEdit(default)
            e.setStyleSheet(self._input_style("#cba6f7"))
            self._pid_edits[key] = e
            col.addWidget(e)
            pid_row.addLayout(col)
        self._pid_sec.add_layout(pid_row)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        apply_btn = QPushButton("Apply PID")
        apply_btn.setFixedHeight(28)
        apply_btn.setStyleSheet(
            "QPushButton{background:#1a0d2e;border:1px solid #cba6f7;"
            "border-radius:4px;color:#cba6f7;font-size:11px;font-weight:600;padding:0 12px;}"
            "QPushButton:hover{background:#cba6f7;color:#000;}")
        apply_btn.clicked.connect(self._apply_pid)

        read_btn = QPushButton("Read PID")
        read_btn.setFixedHeight(28)
        read_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#8892a4;font-size:11px;padding:0 12px;}"
            "QPushButton:hover{border-color:#cba6f7;color:#cba6f7;}")
        read_btn.clicked.connect(self._read_pid)

        auto_btn = QPushButton("Auto PID")
        auto_btn.setFixedHeight(28)
        auto_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #1e2433;"
            "border-radius:4px;color:#8892a4;font-size:11px;padding:0 12px;}"
            "QPushButton:hover{border-color:#22c55e;color:#22c55e;}")
        auto_btn.clicked.connect(self._auto_pid)

        btn_row.addWidget(apply_btn); btn_row.addWidget(read_btn)
        btn_row.addWidget(auto_btn); btn_row.addStretch()
        self._pid_sec.add_layout(btn_row)
        layout.addWidget(self._pid_sec)

    # ── Log ───────────────────────────────────
    def _build_log(self, layout):
        self._sh(layout,"RESPONSE LOG")
        self._log = QTextEdit()
        self._log.setReadOnly(True); self._log.setFixedHeight(80)
        self._log.setStyleSheet(
            "QTextEdit{background:#0a0c10;border:1px solid #1e2433;border-radius:5px;"
            "color:#4a5568;font-size:11px;font-family:Consolas,monospace;}")
        layout.addWidget(self._log)

    # ── Scan ──────────────────────────────────
    def _scan(self):
        if not HAS_VISA:
            self._res_combo.addItem("pyvisa not installed")
            return
        try:
            rm   = pyvisa.ResourceManager()
            devs = rm.list_resources()
            self._res_combo.clear()
            ted  = [d for d in devs if "1313" in d or "TED" in d.upper()]
            all_usb = [d for d in devs if "USB" in d]
            items = ted if ted else all_usb
            for d in items: self._res_combo.addItem(d)
            if items: self._log_msg(f"Found {len(items)} USB resource(s)")
            else: self._log_msg("No USB devices found","#eab308")
        except Exception as e:
            self._log_msg(str(e),"#ef4444")

    # ── Connect ───────────────────────────────
    def _connect(self):
        resource = self._res_combo.currentText().strip()
        if not resource: return
        self.conn_btn.setEnabled(False)
        self.status_lbl.setText("○  Connecting...")
        self.status_lbl.setStyleSheet("color:#eab308;font-size:12px;")
        self._worker = ConnectWorker(resource)
        self._worker.success.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, idn):
        resource = self._res_combo.currentText().strip()
        drv = TECDriver(resource)
        try: drv.connect(); self._drv = drv
        except Exception as e:
            self._log_msg(str(e),"#ef4444"); return
        self.status_lbl.setText("●  Connected")
        self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.idn_lbl.setText(f"IDN: {idn[:50]}")
        self.idn_lbl.setStyleSheet("color:#8892a4;font-size:11px;")
        self.conn_btn.setText("✗  Disconnect")
        self.conn_btn.setEnabled(True)
        self.conn_btn.clicked.disconnect()
        self.conn_btn.clicked.connect(self._disconnect)
        self._log_msg(f"Connected → {idn[:60]}")
        self._poll_timer.start(1000)

    def _on_fail(self, err):
        self.status_lbl.setText(f"✗  {err}")
        self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;")
        self.conn_btn.setEnabled(True)
        self._log_msg(f"Failed: {err}","#ef4444")

    def _disconnect(self):
        self._poll_timer.stop()
        if self._drv:
            try: self._drv.disconnect()
            except: pass
            self._drv = None
        self.status_lbl.setText("○  Disconnected")
        self.status_lbl.setStyleSheet("color:#4a5568;font-size:12px;")
        self.idn_lbl.setText("IDN: —")
        self.conn_btn.setText("⟳  Connect")
        self.conn_btn.clicked.disconnect()
        self.conn_btn.clicked.connect(self._connect)
        self._log_msg("Disconnected","#4a5568")

    # ── Output ────────────────────────────────
    def _set_out_style(self, on):
        if on:
            self._out_btn.setText("TEC ON")
            self._out_btn.setStyleSheet(
                "QPushButton{background:#22c55e;border:2px solid #22c55e;"
                "border-radius:6px;color:#000;font-size:12px;font-weight:700;}"
                "QPushButton:hover{background:#16a34a;}")
        else:
            self._out_btn.setText("TEC OFF")
            self._out_btn.setStyleSheet(
                "QPushButton{background:#1a0000;border:1px solid #3d0a0a;"
                "border-radius:6px;color:#4a5568;font-size:12px;font-weight:700;}"
                "QPushButton:hover{background:#3d0a0a;color:#ef4444;}")

    def _toggle_output(self):
        if not self._drv: return
        try:
            if self._out_on:
                self._drv.output_off(); self._out_on = False
            else:
                self._drv.output_on();  self._out_on = True
            self._set_out_style(self._out_on)
            self._log_msg(f"TEC Output → {'ON' if self._out_on else 'OFF'}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    # ── Set temp ──────────────────────────────
    def _set_temp(self):
        if not self._drv: return
        try:
            t = float(self._setpoint_edit.text())
            self._drv.set_temp(t)
            self._log_msg(f"Setpoint → {t:.3f} °C")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    # ── Poll ──────────────────────────────────
    def _poll(self):
        if not self._drv: return
        worker = PollWorker(self._drv)
        worker.result.connect(self._on_poll)
        worker.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        worker.start(); self._pw = worker

    def _on_poll(self, actual, setpoint, curr, volt, outp):
        self._actual_card.set_value(actual)
        self._sp_card.set_value(setpoint)
        delta = actual - setpoint
        self._delta_card.set_value(delta)
        # warning ถ้า delta > 1°C
        self._delta_card.set_warning(abs(delta) > 1.0)

        self._curr_card.set_value(curr, ".3f")
        self._volt_card.set_value(volt, ".3f")

        out_on = outp.upper() in ("1","ON")
        self._out_on = out_on
        self._set_out_style(out_on)
        self._outp_card._val.setText("ON" if out_on else "OFF")
        self._outp_card._val.setStyleSheet(
            f"color:{'#22c55e' if out_on else '#4a5568'};background:transparent;")

    # ── PID ───────────────────────────────────
    def _apply_pid(self):
        if not self._drv: return
        try:
            p = float(self._pid_edits["p"].text())
            i = float(self._pid_edits["i"].text())
            d = float(self._pid_edits["d"].text())
            self._drv.set_pid(p, i, d)
            self._log_msg(f"PID set → P={p} I={i} D={d}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _read_pid(self):
        if not self._drv: return
        try:
            p, i, d = self._drv.get_pid()
            self._pid_edits["p"].setText(f"{p:.4f}")
            self._pid_edits["i"].setText(f"{i:.4f}")
            self._pid_edits["d"].setText(f"{d:.4f}")
            self._log_msg(f"PID read → P={p:.4f} I={i:.4f} D={d:.4f}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _auto_pid(self):
        if not self._drv: return
        try:
            self._drv.auto_pid()
            self._log_msg("Auto PID triggered")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    # ── Settings ──────────────────────────────
    def get_settings(self):
        return {"resource": self._res_combo.currentText()}

    def load_settings(self, data):
        if data.get("resource"):
            self._res_combo.setCurrentText(data["resource"])
