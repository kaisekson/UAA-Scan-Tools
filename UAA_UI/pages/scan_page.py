"""
Scan Page
==========
- 2D boustrophedon scan via CoarseScanBlock
- Real-time heatmap (pyqtgraph ImageView)
- Signal trace (pyqtgraph PlotWidget)
- Scan params config
- Peak XY / signal summary
"""

import numpy as np
import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QComboBox, QLineEdit,
    QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

try:
    import pyqtgraph as pg
    import pyqtgraph.exporters
    HAS_PG = True
except ImportError:
    HAS_PG = False


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def _btn(text, color="#4a9eff", h=28, w=None, enabled=True):
    b = QPushButton(text)
    if h: b.setFixedHeight(h)
    if w: b.setFixedWidth(w)
    bg = {"#4a9eff":"#1e2d47","#22c55e":"#1a3a1a",
          "#ef4444":"#2a0000","#64748b":"#252a38",
          "#eab308":"#1a1000"}.get(color,"#252a38")
    b.setStyleSheet(
        f"QPushButton{{background:{bg};border:1px solid {color};"
        f"border-radius:4px;color:{color};font-size:11px;font-weight:600;padding:0 10px;}}"
        f"QPushButton:hover{{background:{color};color:#000;}}"
        f"QPushButton:disabled{{border-color:#3a4055;color:#3a4055;background:#20242e;}}")
    b.setEnabled(enabled)
    return b

def _nin(val="0.000", w=80):
    e = QLineEdit(val); e.setFixedHeight(22)
    if w: e.setFixedWidth(w)
    e.setStyleSheet(
        "background:#2a2f3d;border:1px solid #3a4055;border-radius:3px;"
        "color:#e2e8f0;padding:1px 5px;font-size:10px;font-family:monospace;")
    return e

def _combo(items, w=120):
    c = QComboBox(); c.addItems(items)
    c.setFixedHeight(22)
    if w: c.setFixedWidth(w)
    c.setStyleSheet(
        "QComboBox{background:#2a2f3d;border:1px solid #3a4055;border-radius:3px;"
        "color:#e2e8f0;padding:0 5px;font-size:10px;}"
        "QComboBox::drop-down{border:none;}"
        "QComboBox QAbstractItemView{background:#20242e;color:#e2e8f0;font-size:10px;}")
    return c

def _hline():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("background:#3a4055;max-height:1px;"); return f

def _panel_hdr(title, color, model=""):
    hdr = QFrame()
    hdr.setStyleSheet(
        "QFrame{background:#16191f;border:none;"
        "border-bottom:1px solid #3a4055;border-radius:6px 6px 0 0;}")
    hh = QHBoxLayout(hdr); hh.setContentsMargins(10,7,10,7); hh.setSpacing(8)
    dot = QFrame(); dot.setFixedSize(8,8)
    dot.setStyleSheet(f"QFrame{{background:{color};border-radius:4px;border:none;}}")
    t = QLabel(title); t.setFont(QFont("Segoe UI",10,700))
    t.setStyleSheet(f"color:{color};background:transparent;")
    hh.addWidget(dot); hh.addWidget(t)
    if model:
        hh.addStretch()
        hh.addWidget(lbl(model,"#3a4055",10))
    return hdr


# ══════════════════════════════════════════════
# Scan Worker
# ══════════════════════════════════════════════

class ScanWorker(QThread):
    point_done = pyqtSignal(int, int, float)   # xi, yi, signal
    log        = pyqtSignal(str, str)
    finished   = pyqtSignal(bool)

    def __init__(self, params, devices):
        super().__init__()
        self._params  = params
        self._devices = devices
        self._abort   = False

    def abort(self): self._abort = True

    def run(self):
        import time
        from core.blocks import CoarseScanBlock

        block = CoarseScanBlock()
        params = self._params

        rx   = float(params.get("range_x",  0.5))
        ry   = float(params.get("range_y",  0.5))
        step = float(params.get("step",     0.05))
        vel  = float(params.get("velocity", 2.0))
        nplc = float(params.get("nplc",     1.0))

        cart = self._devices.get("cart")
        smu  = self._devices.get("smu")

        xs = np.arange(-rx, rx + step/2, step)
        ys = np.arange(-ry, ry + step/2, step)
        total = len(xs) * len(ys)

        self.log.emit(
            f"Scan {len(xs)}×{len(ys)} = {total} pts  "
            f"step={step}mm  vel={vel}mm/s", "info")

        # Origin
        origin_x, origin_y = 0.0, 0.0
        if cart:
            try:
                pos = cart.pos()
                origin_x = pos.get("X",0.0)
                origin_y = pos.get("Y",0.0)
                self.log.emit(
                    f"Origin: X={origin_x:.4f} Y={origin_y:.4f} mm","info")
            except: pass

        if smu:
            try: smu.set_nplc("A", nplc)
            except: pass

        n = 0
        for yi, y_rel in enumerate(ys):
            if self._abort: break
            row_xs = xs if yi%2==0 else xs[::-1]
            for x_rel in row_xs:
                if self._abort: break

                abs_x = origin_x + x_rel
                abs_y = origin_y + y_rel

                if cart:
                    try:
                        cart.vel_all(vel)
                        cart.mov_xy(abs_x, abs_y)
                        time.sleep(0.01)
                    except Exception as e:
                        self.log.emit(f"Move error: {e}","error"); continue

                if smu:
                    try:
                        signal = abs(smu.measure_i("A"))
                    except Exception as e:
                        self.log.emit(f"SMU error: {e}","warn")
                        signal = 0.0
                else:
                    # Simulate
                    cx = len(xs)//2 + 1.5
                    cy = len(ys)//2 - 1
                    sx, sy = len(xs)/6, len(ys)/6
                    signal = 1.2e-6 * np.exp(
                        -((n%len(xs) - cx)**2/(2*sx**2) +
                          (yi - cy)**2/(2*sy**2)))
                    signal += np.random.normal(0, 2e-10)
                    signal = max(0.0, signal)

                # xi index in full grid
                xi_full = int((x_rel + rx) / step + 0.5)
                xi_full = max(0, min(len(xs)-1, xi_full))
                self.point_done.emit(xi_full, yi, signal)
                n += 1

        if self._abort:
            self.log.emit("Scan aborted","warn")
            self.finished.emit(False)
        else:
            self.log.emit("Scan complete","ok")
            self.finished.emit(True)


# ══════════════════════════════════════════════
# Stat Card
# ══════════════════════════════════════════════

class StatCard(QFrame):
    def __init__(self, label, color="#e2e8f0"):
        super().__init__()
        self._color = color
        self.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:4px;}")
        v = QVBoxLayout(self); v.setContentsMargins(8,5,8,5); v.setSpacing(2)
        v.addWidget(lbl(label,"#64748b",9,True))
        self._val = QLabel("—")
        self._val.setFont(QFont("Consolas",12,700))
        self._val.setStyleSheet(f"color:{color};background:transparent;")
        v.addWidget(self._val)

    def set_val(self, text):
        self._val.setText(text)


# ══════════════════════════════════════════════
# Heatmap Widget (pyqtgraph or fallback)
# ══════════════════════════════════════════════

class HeatmapWidget(QFrame):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(
            "QFrame{background:#0d1015;border:none;border-radius:0;}")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        self._grid = None
        self._W = self._H = 21

        if HAS_PG:
            pg.setConfigOption("background","#0d1015")
            pg.setConfigOption("foreground","#64748b")
            self._view = pg.ImageView()
            self._view.ui.histogram.hide()
            self._view.ui.roiBtn.hide()
            self._view.ui.menuBtn.hide()
            self._view.setColorMap(self._colormap())
            v.addWidget(self._view)
            self._peak_arrow = None
        else:
            self._lbl = QLabel("pyqtgraph not installed\npip install pyqtgraph")
            self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lbl.setStyleSheet("color:#64748b;font-size:12px;background:transparent;")
            v.addWidget(self._lbl)

    def _colormap(self):
        cm = pg.ColorMap(
            pos   = [0.0,  0.25, 0.5,  0.75, 1.0],
            color = [(13,16,21),(0,0,180),(0,180,0),(255,200,0),(255,50,0)])
        return cm

    def init_grid(self, W, H):
        self._W = W; self._H = H
        self._grid = np.zeros((W, H), dtype=np.float32)
        if HAS_PG:
            self._view.setImage(self._grid, autoLevels=True)

    def update_point(self, xi, yi, val):
        if self._grid is None: return
        self._grid[xi, yi] = val
        if HAS_PG:
            self._view.setImage(
                self._grid, autoLevels=True,
                autoHistogramRange=False)

    def reset(self):
        if self._grid is not None:
            self._grid[:] = 0
            if HAS_PG:
                self._view.setImage(self._grid, autoLevels=True)


# ══════════════════════════════════════════════
# Trace Widget
# ══════════════════════════════════════════════

class TraceWidget(QFrame):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(
            "QFrame{background:#0d1015;border:none;}")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0)
        self._pts = []

        if HAS_PG:
            pg.setConfigOption("background","#0d1015")
            pg.setConfigOption("foreground","#64748b")
            self._plot = pg.PlotWidget()
            self._plot.setLabel("left","Signal","A")
            self._plot.setLabel("bottom","Scan point","")
            self._plot.showGrid(x=True, y=True, alpha=0.2)
            self._curve = self._plot.plot(
                pen=pg.mkPen("#eab308", width=1.5))
            v.addWidget(self._plot)
        else:
            self._lbl = QLabel("pyqtgraph not installed")
            self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lbl.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
            v.addWidget(self._lbl)

    def add_point(self, val):
        self._pts.append(val)
        if HAS_PG:
            self._curve.setData(self._pts)

    def reset(self):
        self._pts = []
        if HAS_PG:
            self._curve.setData([])


# ══════════════════════════════════════════════
# Scan Page
# ══════════════════════════════════════════════

class ScanPage(QWidget):
    def __init__(self):
        super().__init__()
        self._cart_drv = [None]
        self._smu_drv  = [None]
        self._worker   = None
        self._scanning = False
        self._grid_w   = 21
        self._grid_h   = 21
        self._peak_sig = 0.0
        self._peak_xi  = 0
        self._peak_yi  = 0
        self._n_pts    = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(12,12,12,12); root.setSpacing(10)

        self._build_left(root)
        self._build_right(root)

    # ── Left: config + controls ───────────────
    def _build_left(self, layout):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(280)
        scroll.setStyleSheet(
            "QScrollArea{background:#20242e;border:1px solid #3a4055;"
            "border-radius:6px;}"
            "QScrollBar:vertical{width:4px;background:#20242e;}"
            "QScrollBar::handle:vertical{background:#3a4055;border-radius:2px;}")

        inner = QWidget(); inner.setStyleSheet("background:transparent;")
        v = QVBoxLayout(inner); v.setContentsMargins(12,10,12,10); v.setSpacing(6)

        # Device
        v.addWidget(lbl("DEVICE","#64748b",9,True))
        dr = QHBoxLayout(); dr.setSpacing(6)
        dr.addWidget(lbl("Motion","#64748b",9))
        self._dev_combo = _combo(["Cartesian","Hexapod 1","Hexapod 2"],w=130)
        dr.addWidget(self._dev_combo)
        v.addLayout(dr)

        sr = QHBoxLayout(); sr.setSpacing(6)
        sr.addWidget(lbl("SMU Ch","#64748b",9))
        self._smu_combo = _combo(["Channel A","Channel B"],w=130)
        sr.addWidget(self._smu_combo)
        v.addLayout(sr)

        v.addWidget(_hline())

        # Scan params
        v.addWidget(lbl("SCAN RANGE","#64748b",9,True))
        g = QGridLayout(); g.setSpacing(5)
        params = [
            ("Range X (mm)", "_rx",  "0.500"),
            ("Range Y (mm)", "_ry",  "0.500"),
            ("Step (mm)",    "_stp", "0.050"),
            ("Velocity",     "_vel", "2.000"),
        ]
        for i,(lbl_txt, attr, default) in enumerate(params):
            g.addWidget(lbl(lbl_txt,"#64748b",9), i, 0)
            e = _nin(default, 80); setattr(self, attr, e)
            g.addWidget(e, i, 1)
        v.addLayout(g)

        v.addWidget(_hline())

        # SMU params
        v.addWidget(lbl("SMU","#64748b",9,True))
        g2 = QGridLayout(); g2.setSpacing(5)
        smu_params = [
            ("NPLC",        "_nplc",  "1.0"),
            ("Compliance µA","_comp", "100"),
        ]
        for i,(lbl_txt,attr,default) in enumerate(smu_params):
            g2.addWidget(lbl(lbl_txt,"#64748b",9), i, 0)
            e = _nin(default, 80); setattr(self, attr, e)
            g2.addWidget(e, i, 1)
        v.addLayout(g2)

        v.addWidget(_hline())

        # Stats
        v.addWidget(lbl("RESULT","#64748b",9,True))
        sg = QGridLayout(); sg.setSpacing(5)
        self._stat_sig  = StatCard("PEAK SIGNAL", "#22c55e")
        self._stat_x    = StatCard("PEAK X",      "#4a9eff")
        self._stat_y    = StatCard("PEAK Y",      "#22c55e")
        self._stat_prog = StatCard("PROGRESS",    "#e2e8f0")
        sg.addWidget(self._stat_sig,  0, 0)
        sg.addWidget(self._stat_x,    0, 1)
        sg.addWidget(self._stat_y,    1, 0)
        sg.addWidget(self._stat_prog, 1, 1)
        v.addLayout(sg)

        v.addWidget(_hline())

        # Log
        v.addWidget(lbl("LOG","#64748b",9,True))
        from PyQt6.QtWidgets import QTextEdit
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(100)
        self._log.setStyleSheet(
            "QTextEdit{background:#16191f;border:1px solid #3a4055;"
            "border-radius:4px;color:#64748b;"
            "font-size:10px;font-family:Consolas;}")
        v.addWidget(self._log)
        v.addStretch()

        scroll.setWidget(inner)
        layout.addWidget(scroll)

        # Control buttons (outside scroll)
        left_outer = QFrame()
        left_outer.setStyleSheet("QFrame{background:transparent;border:none;}")
        lo = QVBoxLayout(left_outer); lo.setContentsMargins(0,0,0,0); lo.setSpacing(6)
        lo.addWidget(scroll, 1)

        btn_row = QHBoxLayout(); btn_row.setSpacing(5)
        self._start_btn = _btn("▶ Start Scan","#22c55e",h=32)
        self._stop_btn  = _btn("⏹ Stop",      "#ef4444",h=32,enabled=False)
        self._reset_btn = _btn("Reset",        "#64748b",h=32)
        self._start_btn.clicked.connect(self._start)
        self._stop_btn.clicked.connect(self._stop)
        self._reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self._start_btn,2)
        btn_row.addWidget(self._stop_btn,1)
        btn_row.addWidget(self._reset_btn,1)
        lo.addLayout(btn_row)

        layout.addWidget(left_outer)

    # ── Right: heatmap + trace ────────────────
    def _build_right(self, layout):
        right = QVBoxLayout(); right.setSpacing(8)

        # Heatmap panel
        hmap_frame = QFrame()
        hmap_frame.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        hv = QVBoxLayout(hmap_frame); hv.setContentsMargins(0,0,0,0); hv.setSpacing(0)
        hmap_hdr = _panel_hdr("2D SCAN MAP","#22c55e")
        hv.addWidget(hmap_hdr)
        self._hmap = HeatmapWidget()
        self._hmap.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        hv.addWidget(self._hmap, 1)
        right.addWidget(hmap_frame, 3)

        # Trace panel
        trace_frame = QFrame()
        trace_frame.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        tv = QVBoxLayout(trace_frame); tv.setContentsMargins(0,0,0,0); tv.setSpacing(0)
        trace_hdr = _panel_hdr("SIGNAL TRACE","#eab308")
        tv.addWidget(trace_hdr)
        self._trace = TraceWidget()
        self._trace.setFixedHeight(140)
        tv.addWidget(self._trace)
        right.addWidget(trace_frame)

        layout.addLayout(right, 1)

    # ── Scan control ──────────────────────────
    def _get_params(self):
        return {
            "range_x":  float(self._rx.text()  or 0.5),
            "range_y":  float(self._ry.text()  or 0.5),
            "step":     float(self._stp.text() or 0.05),
            "velocity": float(self._vel.text() or 2.0),
            "nplc":     float(self._nplc.text()or 1.0),
        }

    def _start(self):
        if self._scanning: return
        params = self._get_params()
        rx   = params["range_x"]; ry = params["range_y"]
        step = params["step"]
        W = max(2, int(rx*2/step)+1)
        H = max(2, int(ry*2/step)+1)
        self._grid_w = W; self._grid_h = H
        self._n_pts  = 0
        self._peak_sig = 0.0

        self._hmap.init_grid(W, H)
        self._trace.reset()
        self._stat_sig.set_val("—")
        self._stat_x.set_val("—")
        self._stat_y.set_val("—")
        self._stat_prog.set_val("0%")

        devices = {
            "cart": self._cart_drv[0],
            "smu":  self._smu_drv[0],
        }

        self._scanning = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        self._worker = ScanWorker(params, devices)
        self._worker.point_done.connect(self._on_point)
        self._worker.log.connect(self._log_msg)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

        self._log_msg(
            f"Start scan {W}×{H} = {W*H} pts","#4a9eff")

    def _on_point(self, xi, yi, signal):
        self._hmap.update_point(xi, yi, signal)
        self._trace.add_point(signal)
        self._n_pts += 1
        total = self._grid_w * self._grid_h

        if signal > self._peak_sig:
            self._peak_sig = signal
            self._peak_xi  = xi
            self._peak_yi  = yi

        # Update stats
        rx = float(self._rx.text() or 0.5)
        ry = float(self._ry.text() or 0.5)
        step = float(self._stp.text() or 0.05)
        px = -rx + self._peak_xi * step
        py = -ry + self._peak_yi * step
        pct = int(self._n_pts / total * 100)

        self._stat_sig.set_val(f"{self._peak_sig*1e6:.3f} µA")
        self._stat_x.set_val(f"{px:.4f} mm")
        self._stat_y.set_val(f"{py:.4f} mm")
        self._stat_prog.set_val(f"{pct}%")

    def _on_done(self, success):
        self._scanning = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._stat_prog.set_val("100%")
        self._log_msg(
            "Scan complete" if success else "Scan stopped",
            "#22c55e" if success else "#eab308")

    def _stop(self):
        if self._worker: self._worker.abort()

    def _reset(self):
        self._stop()
        self._hmap.reset()
        self._trace.reset()
        self._stat_sig.set_val("—")
        self._stat_x.set_val("—")
        self._stat_y.set_val("—")
        self._stat_prog.set_val("0%")
        self._log.clear()

    def _log_msg(self, msg, color="#64748b"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:#3a4055;">[{ts}]</span> '
            f'<span style="color:{color};">{msg}</span>')

    # ── Set drivers ───────────────────────────
    def set_cart_driver(self, drv): self._cart_drv[0] = drv
    def set_smu_driver(self, drv):  self._smu_drv[0]  = drv
