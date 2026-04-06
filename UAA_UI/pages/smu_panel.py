"""
Keithley 2602B SMU Panel
==========================
- Connect via TCP/TSP (port 5025)
- Channel A & B independent config
- Source V/I, compliance, range, NPLC
- Readback V, I (auto-unit pA/nA/µA/mA), Power
- Compliance warning
- Statistics: Min/Max/Avg
- [Collapsible] Sweep + IV plot
- [Collapsible] TSP Script load/run
- [Collapsible] TSP Console
"""

import socket, time, os, csv, datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QComboBox,
    QScrollArea, QTextEdit, QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False


# ══════════════════════════════════════════════
# Auto-unit formatter
# ══════════════════════════════════════════════

def auto_unit(val):
    """แปลง A → pA/nA/µA/mA/A อัตโนมัติ"""
    abs_val = abs(val)
    if abs_val == 0:    return "0.000", "A"
    if abs_val < 1e-9:  return f"{val*1e12:.3f}", "pA"
    if abs_val < 1e-6:  return f"{val*1e9:.3f}",  "nA"
    if abs_val < 1e-3:  return f"{val*1e6:.3f}",  "µA"
    if abs_val < 1.0:   return f"{val*1e3:.3f}",  "mA"
    return f"{val:.4f}", "A"


# ══════════════════════════════════════════════
# TSP Driver
# ══════════════════════════════════════════════

class SMUDriver:
    def __init__(self, ip, port=5025, timeout=3.0):
        self.ip=ip; self.port=port; self.timeout=timeout
        self._sock=None

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.ip, self.port))
        time.sleep(0.1)

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    def send(self, cmd):
        self._sock.sendall((cmd+"\n").encode())
        time.sleep(0.05)

    def query(self, cmd):
        self._sock.sendall((cmd+"\n").encode())
        time.sleep(0.05)
        data = b""
        self._sock.settimeout(self.timeout)
        try:
            while True:
                chunk = self._sock.recv(4096); data += chunk
                if data.endswith(b"\n"): break
        except socket.timeout: pass
        return data.decode().strip()

    def idn(self): return self.query("*IDN?")

    def setup_channel(self, ch, func, level, compliance, nplc):
        """ch = 'a' หรือ 'b'"""
        smu = f"smu{ch}"
        if func == "Voltage":
            self.send(f"{smu}.source.func = {smu}.OUTPUT_DCVOLTS")
            self.send(f"{smu}.source.levelv = {level}")
            self.send(f"{smu}.source.limiti = {compliance}")
        else:
            self.send(f"{smu}.source.func = {smu}.OUTPUT_DCAMPS")
            self.send(f"{smu}.source.leveli = {level}")
            self.send(f"{smu}.source.limitv = {compliance}")
        self.send(f"{smu}.source.autorangev = {smu}.AUTORANGE_ON")
        self.send(f"{smu}.measure.autorangei = {smu}.AUTORANGE_ON")
        self.send(f"{smu}.measure.nplc = {nplc}")

    def output_on(self, ch):
        self.send(f"smu{ch}.source.output = smu{ch}.OUTPUT_ON")

    def output_off(self, ch):
        self.send(f"smu{ch}.source.output = smu{ch}.OUTPUT_OFF")

    def measure_iv(self, ch):
        resp = self.query(f"print(smu{ch}.measure.iv())")
        parts = resp.split(",")
        if len(parts) >= 2:
            return float(parts[0]), float(parts[1])
        return 0.0, 0.0

    def compliance_hit(self, ch):
        resp = self.query(f"print(smu{ch}.source.compliance)")
        return resp.strip().lower() == "true"

    def reset(self):
        self.send("reset()")

    def send_tsp(self, cmd):
        return self.query(f"print({cmd})" if not cmd.startswith("print") else cmd)

    def load_script(self, name, code):
        self.send(f"loadscript {name}")
        for line in code.split("\n"):
            self.send(line)
        self.send("endscript")

    def run_script(self, name):
        self.send(f"{name}()")

    def sweep_v(self, ch, start, stop, step, delay_ms):
        """ทำ V sweep อ่าน I กลับมา"""
        import numpy as np
        points = []
        v = start
        while (step > 0 and v <= stop+1e-9) or (step < 0 and v >= stop-1e-9):
            points.append(round(v, 9))
            v += step
        results = []
        smu = f"smu{ch}"
        self.send(f"{smu}.source.func = {smu}.OUTPUT_DCVOLTS")
        self.send(f"{smu}.measure.autorangei = {smu}.AUTORANGE_ON")
        self.send(f"{smu}.source.output = {smu}.OUTPUT_ON")
        for vp in points:
            self.send(f"{smu}.source.levelv = {vp}")
            time.sleep(delay_ms/1000.0)
            i_str = self.query(f"print({smu}.measure.i())")
            try: i_val = float(i_str)
            except: i_val = 0.0
            results.append((vp, i_val))
        self.send(f"{smu}.source.output = {smu}.OUTPUT_OFF")
        return results


# ══════════════════════════════════════════════
# Workers
# ══════════════════════════════════════════════

class ConnectWorker(QThread):
    success = pyqtSignal(str)
    failed  = pyqtSignal(str)
    def __init__(self, ip, port):
        super().__init__(); self.ip=ip; self.port=port
    def run(self):
        try:
            d = SMUDriver(self.ip, self.port)
            d.connect(); idn = d.idn(); d.disconnect()
            self.success.emit(idn)
        except Exception as e: self.failed.emit(str(e))


class MeasureWorker(QThread):
    result = pyqtSignal(float, float, bool)   # V, I, compliance
    error  = pyqtSignal(str)
    def __init__(self, drv, ch):
        super().__init__(); self._drv=drv; self._ch=ch
    def run(self):
        try:
            v, i = self._drv.measure_iv(self._ch)
            comp = self._drv.compliance_hit(self._ch)
            self.result.emit(v, i, comp)
        except Exception as e: self.error.emit(str(e))


class SweepWorker(QThread):
    progress = pyqtSignal(int, int)           # done, total
    point    = pyqtSignal(float, float)       # V, I
    finished = pyqtSignal(list)               # [(V,I), ...]
    error    = pyqtSignal(str)
    def __init__(self, drv, ch, start, stop, step, delay):
        super().__init__()
        self._drv=drv; self._ch=ch
        self._start=start; self._stop=stop
        self._step=step; self._delay=delay
        self._abort=False
    def abort(self): self._abort=True
    def run(self):
        try:
            points = []
            v = self._start
            while (self._step>0 and v<=self._stop+1e-9) or \
                  (self._step<0 and v>=self._stop-1e-9):
                points.append(round(v,9)); v+=self._step
            results = []
            smu = f"smu{self._ch}"
            self._drv.send(f"{smu}.source.func = {smu}.OUTPUT_DCVOLTS")
            self._drv.send(f"{smu}.measure.autorangei = {smu}.AUTORANGE_ON")
            self._drv.send(f"{smu}.source.output = {smu}.OUTPUT_ON")
            for idx, vp in enumerate(points):
                if self._abort: break
                self._drv.send(f"{smu}.source.levelv = {vp}")
                time.sleep(self._delay/1000.0)
                i_str = self._drv.query(f"print({smu}.measure.i())")
                try: i_val = float(i_str)
                except: i_val = 0.0
                results.append((vp, i_val))
                self.point.emit(vp, i_val)
                self.progress.emit(idx+1, len(points))
            self._drv.send(f"{smu}.source.output = {smu}.OUTPUT_OFF")
            self.finished.emit(results)
        except Exception as e: self.error.emit(str(e))


# ══════════════════════════════════════════════
# Collapsible Section
# ══════════════════════════════════════════════

class CollapsibleSection(QFrame):
    def __init__(self, title, color="#64748b"):
        super().__init__()
        self.setStyleSheet("QFrame{background:transparent;border:none;}")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0,0,0,0)
        self._layout.setSpacing(0)

        # Header button
        self._btn = QPushButton(f"▶  {title}")
        self._btn.setCheckable(True)
        self._btn.setFixedHeight(30)
        self._btn.setStyleSheet(f"""
            QPushButton{{
                background:#20242e;border:1px solid #3a4055;
                border-radius:5px;color:{color};
                font-size:11px;font-weight:600;
                text-align:left;padding-left:12px;
            }}
            QPushButton:checked{{
                background:#1a1d24;border-color:{color};
                border-radius:5px 5px 0 0;
            }}
            QPushButton:hover{{border-color:{color};}}
        """)
        self._btn.clicked.connect(self._toggle)
        self._layout.addWidget(self._btn)

        # Content frame
        self._content = QFrame()
        self._content.setStyleSheet(
            f"QFrame{{background:#20242e;border:1px solid #3a4055;"
            f"border-top:none;border-radius:0 0 5px 5px;}}")
        self._content.setVisible(False)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12,10,12,10)
        self._content_layout.setSpacing(8)
        self._layout.addWidget(self._content)

    def _toggle(self, checked):
        self._content.setVisible(checked)
        label = self._btn.text()[3:]
        self._btn.setText(("▼  " if checked else "▶  ") + label)

    def add_widget(self, w):
        self._content_layout.addWidget(w)

    def add_layout(self, l):
        self._content_layout.addLayout(l)


# ══════════════════════════════════════════════
# Channel Panel
# ══════════════════════════════════════════════

class ChannelPanel(QFrame):
    def __init__(self, ch_label, drv_ref):
        super().__init__()
        self._ch   = ch_label.lower()
        self._drv  = drv_ref
        self._auto = False
        self._stats = {"min": None, "max": None, "sum": 0.0, "n": 0}
        self.setStyleSheet(
            "QFrame{background:#20242e;"
            "border-left:1px solid #3a4055;"
            "border-right:1px solid #3a4055;"
            "border-bottom:1px solid #3a4055;"
            "border-top:none;"
            "border-radius:0 0 6px 6px;}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,12,14,12)
        layout.setSpacing(10)

        # Source + Readback
        grid = QHBoxLayout(); grid.setSpacing(14)

        # Source
        src = QFrame()
        src.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")
        sv  = QVBoxLayout(src); sv.setContentsMargins(12,10,12,10); sv.setSpacing(8)
        sv.addWidget(lbl("SOURCE","#64748b",10,True))
        sv.addWidget(self._hline())

        self._level_unit_lbl = None
        self._comp_unit_lbl  = None

        for attr, label_txt, default, unit, options in [
            ("func_cb",    "Function",   None,    "",  ["Voltage","Current"]),
            ("level_edit", "Level",      "2.000", "V", None),
            ("comp_edit",  "Compliance", "0.001", "A", None),
            ("range_cb",   "Meas range", None,    "",  ["Auto","1mA","100µA","10µA","1µA","100nA"]),
            ("nplc_edit",  "NPLC",       "1.0",   "",  None),
        ]:
            row = QHBoxLayout(); row.setSpacing(6)
            lw = lbl(label_txt,"#64748b",10); lw.setFixedWidth(88)
            row.addWidget(lw)
            if options:
                w = QComboBox(); w.addItems(options)
                w.setFixedHeight(26); w.setFixedWidth(110)
                w.setStyleSheet(
                    "QComboBox{background:#2a2f3d;border:1px solid #3a4055;"
                    "border-radius:4px;color:#e2e8f0;padding:2px 6px;font-size:11px;}"
                    "QComboBox::drop-down{border:none;}"
                    "QComboBox QAbstractItemView{background:#20242e;border:1px solid #3a4055;color:#e2e8f0;}")
            else:
                w = QLineEdit(default)
                w.setFixedWidth(90)
                w.setStyleSheet(
                    "background:#2a2f3d;border:1px solid #3a4055;border-radius:4px;"
                    "color:#e2e8f0;padding:4px 6px;font-size:11px;font-family:monospace;")
            setattr(self, attr, w)
            row.addWidget(w)
            if unit:
                ul = lbl(unit,"#64748b",9); ul.setFixedWidth(20)
                row.addWidget(ul)
                if attr == "level_edit": self._level_unit_lbl = ul
                if attr == "comp_edit":  self._comp_unit_lbl  = ul
            row.addStretch()
            sv.addLayout(row)

        # connect func change → update labels
        self.func_cb.currentTextChanged.connect(self._on_func_change)
        # trigger ทันทีตอน init
        self._on_func_change(self.func_cb.currentText())
        grid.addWidget(src, 1)

        # Readback
        rb = QFrame()
        rb.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")
        rv = QVBoxLayout(rb); rv.setContentsMargins(12,10,12,10); rv.setSpacing(6)
        rv.addWidget(lbl("READBACK","#64748b",10,True))
        rv.addWidget(self._hline())

        # V card
        self._v_card = self._rb_card()
        self._v_lbl  = lbl("VOLTAGE","#64748b",9,True)
        self._v_val  = QLabel("—")
        self._v_val.setFont(QFont("Consolas",18,700))
        self._v_val.setStyleSheet("color:#4a9eff;background:transparent;")
        self._v_unit = lbl("V","#64748b",10)
        vr = QHBoxLayout(); vr.addWidget(self._v_val); vr.addWidget(self._v_unit); vr.addStretch()
        self._v_card.layout().addWidget(self._v_lbl)
        self._v_card.layout().addLayout(vr)
        rv.addWidget(self._v_card)

        # I card
        self._i_card = self._rb_card()
        self._i_lbl  = lbl("CURRENT","#64748b",9,True)
        self._i_val  = QLabel("—")
        self._i_val.setFont(QFont("Consolas",18,700))
        self._i_val.setStyleSheet("color:#22c55e;background:transparent;")
        self._i_unit = lbl("A","#22c55e",10)
        ir = QHBoxLayout(); ir.addWidget(self._i_val); ir.addWidget(self._i_unit); ir.addStretch()
        self._i_card.layout().addWidget(self._i_lbl)
        self._i_card.layout().addLayout(ir)
        rv.addWidget(self._i_card)

        # Compliance card
        self._comp_card = self._rb_card()
        self._comp_lbl  = lbl("COMPLIANCE","#64748b",9,True)
        self._comp_val  = lbl("OK","#22c55e",13,True)
        self._comp_val.setFont(QFont("Consolas",13,700))
        self._comp_card.layout().addWidget(self._comp_lbl)
        self._comp_card.layout().addWidget(self._comp_val)
        rv.addWidget(self._comp_card)
        grid.addWidget(rb, 1)
        layout.addLayout(grid)

        # Stats
        stat_row = QHBoxLayout(); stat_row.setSpacing(6)
        self._stat_cards = {}
        for name in ["MIN","MAX","AVG"]:
            f = QFrame()
            f.setStyleSheet(
                "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:5px;}")
            fv = QVBoxLayout(f); fv.setContentsMargins(8,5,8,5); fv.setSpacing(2)
            fv.addWidget(lbl(name,"#64748b",9,True))
            vl = QLabel("—"); vl.setFont(QFont("Consolas",12,700))
            vl.setStyleSheet("color:#94a3b8;background:transparent;")
            fv.addWidget(vl); self._stat_cards[name] = vl
            stat_row.addWidget(f)
        layout.addLayout(stat_row)

        layout.addWidget(divider())

        # Output controls — อยู่ใน border
        out_frame = QFrame()
        out_frame.setStyleSheet(
            "QFrame{background:#16191f;border:none;"
            "border-radius:0 0 6px 6px;padding:2px;}")
        of = QHBoxLayout(out_frame); of.setContentsMargins(8,6,8,6); of.setSpacing(8)

        self.onoff_btn = QPushButton("OFF")
        self.onoff_btn.setFixedSize(70,34)
        self._set_onoff_style(False)
        self.onoff_btn.clicked.connect(self._toggle_output)
        self._out_on = False

        self.status_lbl = lbl("Output OFF","#64748b",11)
        of.addWidget(self.onoff_btn)
        of.addWidget(self.status_lbl)
        of.addStretch()

        for label, fn in [
            ("Apply",        self._apply),
            ("Measure once", self._measure_once),
            ("⟳ Auto",       self._toggle_auto),
            ("Reset stats",  self._reset_stats),
        ]:
            b = QPushButton(label); b.setFixedHeight(28)
            b.setStyleSheet(
                "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
                "border-radius:4px;color:#94a3b8;font-size:11px;padding:0 10px;}"
                "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
            b.clicked.connect(fn); of.addWidget(b)
        layout.addWidget(out_frame)

        # Auto timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._measure_once)
        self._timer.start(1000)

    def _on_func_change(self, func):
        """เปลี่ยน unit label ตาม source function เท่านั้น ไม่แตะค่า"""
        if func == "Voltage":
            if self._level_unit_lbl: self._level_unit_lbl.setText("V")
            if self._comp_unit_lbl:  self._comp_unit_lbl.setText("A")
        else:
            if self._level_unit_lbl: self._level_unit_lbl.setText("A")
            if self._comp_unit_lbl:  self._comp_unit_lbl.setText("V")

    def _hline(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("background:#3a4055;max-height:1px;"); return f

    def _rb_card(self):
        f = QFrame()
        f.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")
        QVBoxLayout(f).setContentsMargins(10,6,10,6)
        return f

    def _set_onoff_style(self, on):
        if on:
            self.onoff_btn.setText("ON")
            self.onoff_btn.setStyleSheet(
                "QPushButton{background:#1a3a1a;border:2px solid #22c55e;"
                "border-radius:6px;color:#22c55e;font-size:13px;font-weight:700;}"
                "QPushButton:hover{background:#22c55e;color:#000;}")
        else:
            self.onoff_btn.setText("OFF")
            self.onoff_btn.setStyleSheet(
                "QPushButton{background:#1a0000;border:2px solid #3d0a0a;"
                "border-radius:6px;color:#64748b;font-size:13px;font-weight:700;}"
                "QPushButton:hover{background:#3d0a0a;color:#ef4444;}")

    def set_connected(self, ok):
        if not ok:
            self._v_val.setText("—"); self._i_val.setText("—")
            self._out_on=False; self._set_onoff_style(False)

    def _apply(self):
        drv = self._drv[0]
        if not drv: return
        try:
            drv.setup_channel(
                self._ch,
                self.func_cb.currentText(),
                float(self.level_edit.text()),
                float(self.comp_edit.text()),
                float(self.nplc_edit.text()),
            )
        except Exception as e: print(f"[SMU] apply: {e}")

    def _toggle_output(self):
        drv = self._drv[0]
        if not drv: return
        try:
            if self._out_on:
                drv.output_off(self._ch); self._out_on=False
            else:
                drv.output_on(self._ch);  self._out_on=True
            self._set_onoff_style(self._out_on)
            self.status_lbl.setText("Output ON" if self._out_on else "Output OFF")
            self.status_lbl.setStyleSheet(
                f"color:{'#22c55e' if self._out_on else '#64748b'};font-size:11px;")
        except Exception as e: print(f"[SMU] output: {e}")

    def _measure_once(self):
        drv = self._drv[0]
        if not drv or not self._out_on: return
        worker = MeasureWorker(drv, self._ch)
        worker.result.connect(self._on_result)
        worker.start(); self._mw = worker

    def _on_result(self, v, i, comp):
        self._v_val.setText(f"{v:.4f}")
        iv, iu = auto_unit(i)
        self._i_val.setText(iv); self._i_unit.setText(iu)
        self._i_unit.setStyleSheet(f"color:#22c55e;font-size:10px;")

        # Compliance
        if comp:
            self._comp_val.setText("⚠ HIT")
            self._comp_val.setStyleSheet("color:#eab308;font-size:13px;font-weight:700;")
            self._comp_card.setStyleSheet(
                "QFrame{background:#1a0e00;border:1px solid #854f0b;border-radius:6px;}")
        else:
            self._comp_val.setText("OK")
            self._comp_val.setStyleSheet("color:#22c55e;font-size:13px;font-weight:700;")
            self._comp_card.setStyleSheet(
                "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")

        # Stats
        self._stats["n"]   += 1
        self._stats["sum"] += i
        if self._stats["min"] is None or i < self._stats["min"]:
            self._stats["min"] = i
        if self._stats["max"] is None or i > self._stats["max"]:
            self._stats["max"] = i
        mn,_ = auto_unit(self._stats["min"])
        mx,_ = auto_unit(self._stats["max"])
        av,_ = auto_unit(self._stats["sum"]/self._stats["n"])
        self._stat_cards["MIN"].setText(mn)
        self._stat_cards["MAX"].setText(mx)
        self._stat_cards["AVG"].setText(av)

    def _toggle_auto(self):
        self._auto = not self._auto
        if self._auto: self._timer.start(1000)
        else:          self._timer.stop()

    def _reset_stats(self):
        self._stats = {"min":None,"max":None,"sum":0.0,"n":0}
        for v in self._stat_cards.values(): v.setText("—")


# ══════════════════════════════════════════════
# SMU Panel
# ══════════════════════════════════════════════

class SMUPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._drv  = [None]
        self._sweep_results = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#1a1d24;border:none;")
        inner  = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16,14,16,14)
        layout.setSpacing(10)

        self._build_connection(layout)
        self._build_channels(layout)

        # Collapsible sections
        self._build_sweep_section(layout)
        self._build_script_section(layout)
        self._build_console_section(layout)
        layout.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(scroll)

    def _sh(self, layout, title, extra=None):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(lbl(title,"#64748b",10,True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#3a4055;max-height:1px;")
        row.addWidget(line,1)
        if extra: row.addWidget(extra)
        layout.addLayout(row)

    def _log_msg(self, msg, color="#22c55e"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:{color};">[{ts}]</span> '
            f'<span style="color:#94a3b8;">{msg}</span>')

    # ── Connection ────────────────────────────
    def _build_connection(self, layout):
        self._sh(layout,"CONNECTION")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(8)
        row = QHBoxLayout(); row.setSpacing(10)
        for attr, lbl_txt, default, w in [
            ("ip_edit",   "IP Address", "10.0.0.80", 2),
            ("port_edit", "Port",       "5025",      1),
        ]:
            f  = QFrame(); fv = QVBoxLayout(f)
            fv.setContentsMargins(0,0,0,0); fv.setSpacing(3)
            fv.addWidget(lbl(lbl_txt,"#64748b",10))
            e  = QLineEdit(default)
            e.setStyleSheet(
                "border-left:2px solid #22c55e;background:#2a2f3d;"
                "border-top:1px solid #3a4055;border-right:1px solid #3a4055;"
                "border-bottom:1px solid #3a4055;border-radius:4px;"
                "color:#e2e8f0;padding:5px 8px;font-size:12px;")
            setattr(self,attr,e); fv.addWidget(e); row.addWidget(f,w)
        v.addLayout(row)
        cr = QHBoxLayout(); cr.setSpacing(10)
        self.conn_btn = QPushButton("⟳  Connect")
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(
            "QPushButton{background:#0d2010;border:1px solid #22c55e;"
            "border-radius:5px;color:#22c55e;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#22c55e;color:#000;}"
            "QPushButton:disabled{border-color:#3a4055;color:#64748b;background:#16191f;}")
        self.conn_btn.clicked.connect(self._connect)
        self.status_lbl = lbl("○  Disconnected","#64748b",12)
        self.idn_lbl    = lbl("IDN: —","#64748b",11)
        cr.addWidget(self.conn_btn); cr.addWidget(self.status_lbl)
        cr.addStretch(); cr.addWidget(self.idn_lbl)
        v.addLayout(cr)
        layout.addWidget(card)

    # ── Channels ──────────────────────────────
    def _build_channels(self, layout):
        self._sh(layout,"CHANNEL CONFIG")
        tabs_row = QHBoxLayout(); tabs_row.setSpacing(3); tabs_row.setContentsMargins(0,0,0,0)
        self._ch_tabs = []
        for i, name in enumerate(["SMU A","SMU B"]):
            btn = QPushButton(name); btn.setCheckable(True); btn.setFixedHeight(30)
            btn.setStyleSheet("""
                QPushButton{
                    background:#20242e;
                    border:1px solid #3a4055;
                    border-bottom:none;
                    border-radius:5px 5px 0 0;
                    color:#64748b;font-size:12px;font-weight:600;padding:0 20px;
                }
                QPushButton:checked{
                    background:#20242e;
                    border-top:2px solid #22c55e;
                    border-left:1px solid #3a4055;
                    border-right:1px solid #3a4055;
                    border-bottom:2px solid #20242e;
                    color:#22c55e;
                }
                QPushButton:hover{color:#94a3b8;}
            """)
            btn.clicked.connect(lambda _, idx=i: self._switch_ch(idx))
            tabs_row.addWidget(btn); self._ch_tabs.append(btn)
        tabs_row.addStretch()
        layout.addLayout(tabs_row)

        from PyQt6.QtWidgets import QStackedWidget
        self._ch_stack = QStackedWidget()
        self._ch_stack.setStyleSheet("QStackedWidget{background:transparent;border:none;}")
        self._ch_panels = []
        for ch in ["a","b"]:
            panel = ChannelPanel(ch, self._drv)
            self._ch_panels.append(panel)
            self._ch_stack.addWidget(panel)
        layout.addWidget(self._ch_stack)
        # init tabs
        for btn in self._ch_tabs: btn.setChecked(False)
        self._ch_tabs[0].setChecked(True)
        self._ch_stack.setCurrentIndex(0)

    def _switch_ch(self, idx):
        self._ch_stack.setCurrentIndex(idx)
        for i,btn in enumerate(self._ch_tabs):
            btn.setChecked(i==idx)

    # ── Sweep section ─────────────────────────
    def _build_sweep_section(self, layout):
        self._sweep_sec = CollapsibleSection("SWEEP", "#eab308")

        # Params
        params = QFrame()
        params.setStyleSheet("QFrame{background:transparent;border:none;}")
        pv = QHBoxLayout(params); pv.setContentsMargins(0,0,0,0); pv.setSpacing(10)
        self._sweep_fields = {}
        for key, lbl_txt, default in [
            ("start", "Start (V)", "-1.000"),
            ("stop",  "Stop (V)",  "1.000"),
            ("step",  "Step (V)",  "0.100"),
            ("delay", "Delay (ms)","10"),
        ]:
            col = QVBoxLayout(); col.setSpacing(3)
            col.addWidget(lbl(lbl_txt,"#64748b",10))
            e = QLineEdit(default)
            e.setStyleSheet(
                "background:#2a2f3d;border:1px solid #3a4055;border-radius:4px;"
                "color:#e2e8f0;padding:4px 6px;font-size:11px;font-family:monospace;")
            self._sweep_fields[key] = e; col.addWidget(e); pv.addLayout(col)

        ch_col = QVBoxLayout(); ch_col.setSpacing(3)
        ch_col.addWidget(lbl("Channel","#64748b",10))
        self._sweep_ch = QComboBox(); self._sweep_ch.addItems(["a","b"])
        self._sweep_ch.setStyleSheet(
            "QComboBox{background:#2a2f3d;border:1px solid #3a4055;border-radius:4px;"
            "color:#e2e8f0;padding:3px 6px;font-size:11px;}"
            "QComboBox::drop-down{border:none;}"
            "QComboBox QAbstractItemView{background:#20242e;color:#e2e8f0;}")
        ch_col.addWidget(self._sweep_ch); pv.addLayout(ch_col)
        self._sweep_sec.add_widget(params)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        self._sweep_run_btn = QPushButton("▶  Run Sweep")
        self._sweep_run_btn.setFixedHeight(30)
        self._sweep_run_btn.setStyleSheet(
            "QPushButton{background:#1a1000;border:1px solid #eab308;"
            "border-radius:5px;color:#eab308;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#eab308;color:#000;}")
        self._sweep_run_btn.clicked.connect(self._run_sweep)
        self._sweep_stop_btn = QPushButton("■ Stop")
        self._sweep_stop_btn.setFixedHeight(30)
        self._sweep_stop_btn.setStyleSheet(
            "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
            "border-radius:5px;color:#94a3b8;font-size:12px;padding:0 12px;}"
            "QPushButton:hover{border-color:#ef4444;color:#ef4444;}")
        self._sweep_stop_btn.clicked.connect(self._stop_sweep)
        self._sweep_export_btn = QPushButton("Export CSV")
        self._sweep_export_btn.setFixedHeight(30)
        self._sweep_export_btn.setStyleSheet(
            "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
            "border-radius:5px;color:#94a3b8;font-size:12px;padding:0 12px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        self._sweep_export_btn.clicked.connect(self._export_sweep)
        self._sweep_prog = lbl("0 / 0 points","#64748b",10)
        btn_row.addWidget(self._sweep_run_btn)
        btn_row.addWidget(self._sweep_stop_btn)
        btn_row.addWidget(self._sweep_export_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._sweep_prog)
        self._sweep_sec.add_layout(btn_row)

        # Plot
        if HAS_PG:
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setFixedHeight(140)
            self._plot_widget.setBackground("#16191f")
            self._plot_widget.getAxis("left").setLabel("I (A)")
            self._plot_widget.getAxis("bottom").setLabel("V (V)")
            self._plot_curve = self._plot_widget.plot(pen=pg.mkPen("#22c55e",width=2))
            self._sweep_sec.add_widget(self._plot_widget)
        else:
            ph = QFrame()
            ph.setFixedHeight(100)
            ph.setStyleSheet(
                "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")
            pl = QLabel("pyqtgraph not installed — pip install pyqtgraph")
            pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pl.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
            QVBoxLayout(ph).addWidget(pl)
            self._sweep_sec.add_widget(ph)

        layout.addWidget(self._sweep_sec)

    # ── Script section ────────────────────────
    def _build_script_section(self, layout):
        self._script_sec = CollapsibleSection("TSP SCRIPT", "#a855f7")
        self._script_path = ""

        file_row = QHBoxLayout(); file_row.setSpacing(6)
        self._script_lbl = QLabel("No file selected")
        self._script_lbl.setStyleSheet(
            "background:#16191f;border:1px solid #3a4055;border-radius:4px;"
            "color:#64748b;font-size:11px;padding:5px 10px;font-family:monospace;")
        browse_btn = QPushButton("📂 Browse")
        browse_btn.setFixedHeight(28)
        browse_btn.setStyleSheet(
            "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
            "border-radius:4px;color:#94a3b8;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        browse_btn.clicked.connect(self._browse_script)
        load_btn = QPushButton("Load")
        load_btn.setFixedHeight(28)
        load_btn.setStyleSheet(
            "QPushButton{background:#1e2d47;border:1px solid #4a9eff;"
            "border-radius:4px;color:#4a9eff;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}")
        load_btn.clicked.connect(self._load_script)
        run_btn = QPushButton("▶ Run")
        run_btn.setFixedHeight(28)
        run_btn.setStyleSheet(
            "QPushButton{background:#1a3a1a;border:1px solid #22c55e;"
            "border-radius:4px;color:#22c55e;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{background:#22c55e;color:#000;}")
        run_btn.clicked.connect(self._run_script)
        stop_btn = QPushButton("■ Stop")
        stop_btn.setFixedHeight(28)
        stop_btn.setStyleSheet(
            "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
            "border-radius:4px;color:#94a3b8;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{border-color:#ef4444;color:#ef4444;}")
        self._script_status = lbl("Ready","#64748b",10)
        file_row.addWidget(self._script_lbl,1)
        file_row.addWidget(browse_btn)
        file_row.addWidget(load_btn)
        file_row.addWidget(run_btn)
        file_row.addWidget(stop_btn)
        file_row.addWidget(self._script_status)
        self._script_sec.add_layout(file_row)
        layout.addWidget(self._script_sec)

    # ── Console section ───────────────────────
    def _build_console_section(self, layout):
        self._console_sec = CollapsibleSection("TSP CONSOLE", "#4a9eff")

        input_row = QHBoxLayout(); input_row.setSpacing(6)
        self._cmd_edit = QLineEdit()
        self._cmd_edit.setPlaceholderText("smua.measure.i()")
        self._cmd_edit.setStyleSheet(
            "background:#16191f;border:1px solid #3a4055;border-radius:4px;"
            "color:#e2e8f0;padding:6px 10px;font-size:12px;font-family:Consolas,monospace;")
        self._cmd_edit.returnPressed.connect(self._send_tsp)
        send_btn = QPushButton("Send"); send_btn.setFixedHeight(32)
        send_btn.setStyleSheet(
            "QPushButton{background:#1e2d47;border:1px solid #4a9eff;"
            "border-radius:4px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}")
        send_btn.clicked.connect(self._send_tsp)
        input_row.addWidget(self._cmd_edit,1); input_row.addWidget(send_btn)
        self._console_sec.add_layout(input_row)

        self._log = QTextEdit()
        self._log.setReadOnly(True); self._log.setFixedHeight(80)
        self._log.setStyleSheet(
            "QTextEdit{background:#16191f;border:1px solid #3a4055;border-radius:5px;"
            "color:#64748b;font-size:11px;font-family:Consolas,monospace;}")
        self._console_sec.add_widget(self._log)
        layout.addWidget(self._console_sec)

    # ── Connect ───────────────────────────────
    def _connect(self):
        ip   = self.ip_edit.text().strip()
        port = int(self.port_edit.text() or 5025)
        if not ip:
            self.status_lbl.setText("✗  Enter IP")
            self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;"); return
        self.conn_btn.setEnabled(False)
        self.status_lbl.setText("○  Connecting...")
        self.status_lbl.setStyleSheet("color:#eab308;font-size:12px;")
        self._worker = ConnectWorker(ip, port)
        self._worker.success.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, idn):
        ip   = self.ip_edit.text().strip()
        port = int(self.port_edit.text() or 5025)
        drv  = SMUDriver(ip, port)
        try: drv.connect(); self._drv[0] = drv
        except Exception as e:
            self._log_msg(str(e),"#ef4444"); return
        self.status_lbl.setText("●  Connected")
        self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.idn_lbl.setText(f"IDN: {idn}")
        self.idn_lbl.setStyleSheet("color:#94a3b8;font-size:11px;")
        self.conn_btn.setText("✗  Disconnect"); self.conn_btn.setEnabled(True)
        self.conn_btn.clicked.disconnect()
        self.conn_btn.clicked.connect(self._disconnect)
        self._log_msg(f"Connected → {idn}")

    def _on_fail(self, err):
        self.status_lbl.setText(f"✗  {err}")
        self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;")
        self.conn_btn.setEnabled(True)
        self._log_msg(f"Failed: {err}","#ef4444")

    def _disconnect(self):
        if self._drv[0]:
            try: self._drv[0].disconnect()
            except: pass
            self._drv[0] = None
        for p in self._ch_panels: p.set_connected(False)
        self.status_lbl.setText("○  Disconnected")
        self.status_lbl.setStyleSheet("color:#64748b;font-size:12px;")
        self.idn_lbl.setText("IDN: —")
        self.conn_btn.setText("⟳  Connect")
        self.conn_btn.clicked.disconnect()
        self.conn_btn.clicked.connect(self._connect)
        self._log_msg("Disconnected","#64748b")

    # ── Sweep ─────────────────────────────────
    def _run_sweep(self):
        if not self._drv[0]: self._log_msg("Not connected","#ef4444"); return
        try:
            start = float(self._sweep_fields["start"].text())
            stop  = float(self._sweep_fields["stop"].text())
            step  = float(self._sweep_fields["step"].text())
            delay = float(self._sweep_fields["delay"].text())
            ch    = self._sweep_ch.currentText()
        except: self._log_msg("Invalid sweep params","#ef4444"); return

        self._sweep_results = []
        if HAS_PG: self._plot_curve.setData([],[])

        self._sw = SweepWorker(self._drv[0], ch, start, stop, step, delay)
        self._sw.progress.connect(
            lambda d,t: self._sweep_prog.setText(f"{d} / {t} points"))
        self._sw.point.connect(self._on_sweep_point)
        self._sw.finished.connect(self._on_sweep_done)
        self._sw.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        self._sw.start()
        self._log_msg(f"Sweep start: {start}V → {stop}V, step {step}V")

    def _on_sweep_point(self, v, i):
        self._sweep_results.append((v,i))
        if HAS_PG:
            xs = [r[0] for r in self._sweep_results]
            ys = [r[1] for r in self._sweep_results]
            self._plot_curve.setData(xs, ys)

    def _on_sweep_done(self, results):
        self._sweep_results = results
        self._log_msg(f"Sweep done — {len(results)} points")

    def _stop_sweep(self):
        if hasattr(self,"_sw"): self._sw.abort()

    def _export_sweep(self):
        if not self._sweep_results: return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "sweep.csv", "CSV files (*.csv)")
        if path:
            with open(path,"w",newline="") as f:
                w = csv.writer(f); w.writerow(["V","I"])
                w.writerows(self._sweep_results)
            self._log_msg(f"Exported → {path}")

    # ── Script ────────────────────────────────
    def _browse_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select TSP Script", "", "TSP files (*.tsp);;All files (*)")
        if path:
            self._script_path = path
            self._script_lbl.setText(os.path.basename(path))
            self._script_lbl.setStyleSheet(
                "background:#16191f;border:1px solid #3a4055;border-radius:4px;"
                "color:#e2e8f0;font-size:11px;padding:5px 10px;font-family:monospace;")

    def _load_script(self):
        if not self._drv[0] or not self._script_path: return
        try:
            with open(self._script_path) as f: code = f.read()
            name = os.path.splitext(os.path.basename(self._script_path))[0]
            self._drv[0].load_script(name, code)
            self._script_name = name
            self._script_status.setText("Loaded")
            self._script_status.setStyleSheet("color:#22c55e;font-size:10px;")
            self._log_msg(f"Script loaded: {name}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _run_script(self):
        if not self._drv[0]: return
        try:
            self._drv[0].run_script(self._script_name)
            self._script_status.setText("Running")
            self._script_status.setStyleSheet("color:#eab308;font-size:10px;")
            self._log_msg(f"Running: {self._script_name}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    # ── Console ───────────────────────────────
    def _send_tsp(self):
        cmd = self._cmd_edit.text().strip()
        if not cmd: return
        if not self._drv[0]: self._log_msg("Not connected","#ef4444"); return
        try:
            resp = self._drv[0].send_tsp(cmd)
            self._log_msg(f"{cmd} → {resp}")
        except Exception as e: self._log_msg(str(e),"#ef4444")
        self._cmd_edit.clear()

    # ── Save / Load ───────────────────────────
    def get_settings(self):
        return {
            "ip":   self.ip_edit.text().strip(),
            "port": int(self.port_edit.text() or 5025),
        }

    def load_settings(self, data):
        self.ip_edit.setText(data.get("ip",""))
        self.port_edit.setText(str(data.get("port",5025)))
