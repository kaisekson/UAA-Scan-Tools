"""
Motion Control Page — Unified Control v2
=========================================
- Device selector: Cartesian / Hexapod 1 / Hexapod 2 / Linear
- D-pad XYZ + UVW (Hexapod only)
- Go to → popup dialog
- Quick IO as button grid
- Camera full height right
"""

import json, os, datetime
import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QComboBox,
    QScrollArea, QSizePolicy, QDialog, QListWidget,
    QListWidgetItem, QDialogButtonBox, QFormLayout
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap, QPainter, QPen, QColor
from core.widgets import lbl, divider


# ══════════════════════════════════════════════
# Style helpers
# ══════════════════════════════════════════════

def _btn(text, color="#4a9eff", h=26, w=None):
    b = QPushButton(text)
    if h: b.setFixedHeight(h)
    if w: b.setFixedWidth(w)
    bg = {"#4a9eff":"#1e2d47","#22c55e":"#1a3a1a",
          "#ef4444":"#1a0000","#eab308":"#1a1000"}.get(color,"#2a2f3d")
    b.setStyleSheet(
        f"QPushButton{{background:{bg};border:1px solid {color};"
        f"border-radius:4px;color:{color};font-size:11px;font-weight:600;padding:0 8px;}}"
        f"QPushButton:hover{{background:{color};color:#000;}}"
        f"QPushButton:disabled{{border-color:#3a4055;color:#64748b;background:#16191f;}}")
    return b

def _jb(text, size=34, color="#4a9eff"):
    b = QPushButton(text); b.setFixedSize(size, size)
    b.setStyleSheet(
        f"QPushButton{{background:#2a2f3d;border:1px solid #3a4055;"
        f"border-radius:4px;color:#94a3b8;font-size:14px;}}"
        f"QPushButton:hover{{border-color:{color};color:{color};background:#1e2d47;}}"
        f"QPushButton:pressed{{background:{color}33;}}")
    return b

def _nin(val="0.000", w=64):
    e = QLineEdit(val); e.setFixedWidth(w); e.setFixedHeight(22)
    e.setStyleSheet(
        "background:#2a2f3d;border:1px solid #3a4055;border-radius:3px;"
        "color:#e2e8f0;padding:1px 4px;font-size:10px;font-family:monospace;")
    return e

def _combo(items, w=80):
    c = QComboBox(); c.addItems(items)
    c.setFixedWidth(w); c.setFixedHeight(22)
    c.setStyleSheet(
        "QComboBox{background:#2a2f3d;border:1px solid #3a4055;border-radius:3px;"
        "color:#e2e8f0;padding:0px 4px;font-size:10px;}"
        "QComboBox::drop-down{border:none;}"
        "QComboBox QAbstractItemView{background:#20242e;color:#e2e8f0;font-size:10px;}")
    return c

def _hline():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("background:#3a4055;max-height:1px;"); return f

def _vline():
    f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet("color:#3a4055;"); f.setFixedWidth(1); return f


STEP_MAP = {
    "0.1µm":0.0001,"1µm":0.001,"5µm":0.005,
    "10µm":0.010,"50µm":0.050,"100µm":0.100,
    "500µm":0.500,"1mm":1.0,"5mm":5.0
}
VEL_MAP  = {"Slow":0.1,"Med":1.0,"Fast":5.0,"Max":10.0}
AXIS_COLORS = {
    "X":"#4a9eff","Y":"#22c55e","Z":"#cba6f7",
    "U":"#f87171","V":"#fb923c","W":"#facc15","—":"#38bdf8",
}
DEVICE_AXES = {
    "Cartesian": ["X","Y","Z"],
    "Hexapod 1": ["X","Y","Z","U","V","W"],
    "Hexapod 2": ["X","Y","Z","U","V","W"],
    "Linear":    ["—"],
}


# ══════════════════════════════════════════════
# Pos inline
# ══════════════════════════════════════════════

class PosInline(QFrame):
    def __init__(self, axis, color, unit="mm"):
        super().__init__()
        self.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:3px;}")
        h = QHBoxLayout(self); h.setContentsMargins(6,3,6,3); h.setSpacing(3)
        al = QLabel(axis); al.setFont(QFont("Consolas",9,700))
        al.setStyleSheet(f"color:{color};background:transparent;"); al.setFixedWidth(12)
        self._v = QLabel("0.0000"); self._v.setFont(QFont("Consolas",11,700))
        self._v.setStyleSheet(f"color:{color};background:transparent;")
        ul = lbl(unit,"#64748b",8)
        h.addWidget(al); h.addWidget(self._v,1); h.addWidget(ul)

    def set_val(self, v, fmt=".4f"):
        self._v.setText(format(v, fmt))


# ══════════════════════════════════════════════
# Go To Dialog
# ══════════════════════════════════════════════

class GoToDialog(QDialog):
    def __init__(self, axes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go To Position")
        self.setFixedWidth(300)
        self._axes = axes
        v = QVBoxLayout(self); v.setSpacing(10)
        v.addWidget(lbl("Enter target position:","#94a3b8",12))

        self._edits = {}
        form = QFormLayout(); form.setSpacing(8)
        for ax in axes:
            color = AXIS_COLORS.get(ax,"#e2e8f0")
            lbl_w = QLabel(ax); lbl_w.setFont(QFont("Consolas",11,700))
            lbl_w.setStyleSheet(f"color:{color};")
            e = QLineEdit("0.000")
            e.setStyleSheet(
                f"border-left:2px solid {color};background:#2a2f3d;"
                "border-top:1px solid #3a4055;border-right:1px solid #3a4055;"
                "border-bottom:1px solid #3a4055;border-radius:4px;"
                "color:#e2e8f0;padding:5px 8px;font-size:12px;font-family:monospace;")
            self._edits[ax] = e
            unit = "mm" if ax in "XYZ—" else "°"
            unit_lbl = lbl(unit,"#64748b",10)
            row = QHBoxLayout()
            row.addWidget(e,1); row.addWidget(unit_lbl)
            form.addRow(lbl_w, row)
        v.addLayout(form)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Go")
        bb.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            "QPushButton{background:#1a3a1a;border:1px solid #22c55e;"
            "border-radius:4px;color:#22c55e;font-weight:600;padding:5px 16px;}"
            "QPushButton:hover{background:#22c55e;color:#000;}")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def get_values(self):
        result = {}
        for ax, e in self._edits.items():
            try: result[ax] = float(e.text())
            except: result[ax] = 0.0
        return result


# ══════════════════════════════════════════════
# Camera label
# ══════════════════════════════════════════════

class CamLabel(QLabel):
    clicked    = pyqtSignal(float, float)
    mouse_move = pyqtSignal(float, float)

    def __init__(self):
        super().__init__(); self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(
                e.position().x()/max(self.width(),1),
                e.position().y()/max(self.height(),1))

    def mouseMoveEvent(self, e):
        self.mouse_move.emit(
            e.position().x()/max(self.width(),1),
            e.position().y()/max(self.height(),1))


# ══════════════════════════════════════════════
# Camera Widget
# ══════════════════════════════════════════════

class CameraWidget(QFrame):
    def __init__(self, cam_ref, cart_drv, hxp_drvs):
        super().__init__()
        self._cam      = cam_ref
        self._cart_drv = cart_drv
        self._hxp_drvs = hxp_drvs
        self._ch_x     = 0.5; self._ch_y = 0.5
        self._ch_style = "cross"
        self._img_w    = 1920; self._img_h = 1080
        self._fps_n    = 0

        self.setStyleSheet("QFrame{background:transparent;border:none;}")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame{background:#16191f;border:none;border-bottom:1px solid #3a4055;}")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(10,6,10,6); hh.setSpacing(8)
        self._dot = QFrame(); self._dot.setFixedSize(8,8)
        self._dot.setStyleSheet(
            "QFrame{background:#3d0a0a;border-radius:4px;border:none;}")
        self._sig = lbl("No signal","#64748b",11)
        hh.addWidget(self._dot); hh.addWidget(self._sig); hh.addStretch()
        hh.addWidget(lbl("Crosshair","#64748b",9))
        self._ch_cb = _combo(["Cross","Dot","Full+circle","None"],w=100)
        self._ch_cb.currentTextChanged.connect(
            lambda t: setattr(self,"_ch_style",t.lower()))
        hh.addWidget(self._ch_cb)
        live_btn = _btn("▶ Live","#22c55e",h=26)
        live_btn.clicked.connect(self._toggle_live)
        stop_btn = _btn("■","#ef4444",h=26,w=28)
        stop_btn.clicked.connect(self._stop)
        cap_btn  = _btn("📸","#4a9eff",h=26,w=32)
        cap_btn.clicked.connect(self._capture)
        hh.addWidget(live_btn); hh.addWidget(stop_btn); hh.addWidget(cap_btn)
        v.addWidget(hdr)

        # View
        self._view = CamLabel()
        self._view.setMinimumHeight(360)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view.setStyleSheet("background:#16191f;color:#64748b;font-size:13px;")
        self._view.setText("📷  Camera not connected\nClick to set crosshair")
        self._view.clicked.connect(self._on_click)
        self._view.mouse_move.connect(self._on_mouse)
        v.addWidget(self._view,1)

        # Bottom bar
        bot = QFrame()
        bot.setStyleSheet(
            "QFrame{background:#16191f;border:none;border-top:1px solid #3a4055;}")
        bh = QHBoxLayout(bot); bh.setContentsMargins(10,4,10,4); bh.setSpacing(8)
        self._ch_lbl   = lbl("960,540 px","#4a9eff",10)
        self._m_lbl    = lbl("—,— px","#64748b",10)
        self._cart_lbl = lbl("X:— Y:— Z:—","#64748b",10)
        self._hxp_lbl  = lbl("X:— Y:—","#64748b",10)
        self._fps_lbl  = lbl("— fps","#22c55e",10)
        for f in [self._ch_lbl,self._m_lbl,self._cart_lbl,self._hxp_lbl]:
            f.setFont(QFont("Consolas",10))
        bh.addWidget(lbl("⊕","#4a9eff",11,True)); bh.addWidget(self._ch_lbl)
        bh.addWidget(_vline())
        bh.addWidget(lbl("Mouse","#64748b",9)); bh.addWidget(self._m_lbl)
        bh.addWidget(_vline())
        bh.addWidget(lbl("Cart","#64748b",9)); bh.addWidget(self._cart_lbl)
        bh.addWidget(_vline())
        bh.addWidget(lbl("Hxp","#64748b",9)); bh.addWidget(self._hxp_lbl)
        bh.addWidget(_vline())
        bh.addWidget(self._fps_lbl)
        bh.addStretch()
        bh.addWidget(lbl("Exp µs","#64748b",9))
        self._exp_e = _nin("10000",60); bh.addWidget(self._exp_e)
        bh.addWidget(lbl("Gain","#64748b",9))
        self._gain_e = _nin("0.0",40); bh.addWidget(self._gain_e)
        ab = _btn("Apply","#64748b",h=22); ab.clicked.connect(self._apply)
        bh.addWidget(ab)
        v.addWidget(bot)

        QTimer(self, timeout=self._refresh_pos, interval=500).start()
        QTimer(self, timeout=self._upd_fps, interval=1000).start()

    def _on_click(self, rx, ry):
        self._ch_x = max(0.0, min(1.0, rx))
        self._ch_y = max(0.0, min(1.0, ry))
        px = int(self._ch_x*self._img_w); py = int(self._ch_y*self._img_h)
        self._ch_lbl.setText(f"{px},{py} px")

    def _on_mouse(self, rx, ry):
        px = int(max(0,min(1,rx))*self._img_w)
        py = int(max(0,min(1,ry))*self._img_h)
        self._m_lbl.setText(f"{px},{py} px")

    def set_frame(self, arr):
        try:
            if arr.ndim == 2:
                h,w = arr.shape; self._img_w,self._img_h = w,h
                if arr.dtype == np.uint16: arr=(arr>>4).astype(np.uint8)
                qi = QImage(arr.data,w,h,w,QImage.Format.Format_Grayscale8)
            else:
                h,w,c = arr.shape; self._img_w,self._img_h = w,h
                qi = QImage(arr.data,w,h,w*c,QImage.Format.Format_BGR888)
            px = QPixmap.fromImage(qi).scaled(
                self._view.width(), self._view.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation)
            self._view.setPixmap(self._draw_ch(px))
            self._fps_n += 1
        except: pass

    def _draw_ch(self, px):
        style = self._ch_style
        if "none" in style: return px
        w,h = px.width(),px.height()
        cx,cy = int(self._ch_x*w),int(self._ch_y*h)
        col = QColor(74,158,255,200)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(col,1))
        if "cross" in style or "full" in style:
            p.drawLine(0,cy,w,cy); p.drawLine(cx,0,cx,h)
        p.setBrush(QColor("#4a9eff"))
        p.drawEllipse(cx-4,cy-4,8,8)
        if "full" in style or "circle" in style:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx-20,cy-20,40,40)
        p.setFont(QFont("Consolas",9))
        p.setPen(QColor("#4a9eff"))
        pxi=int(self._ch_x*self._img_w); pyi=int(self._ch_y*self._img_h)
        tx=cx+6 if cx<w-90 else cx-90; ty=cy-5 if cy>14 else cy+14
        p.drawText(tx,ty,f"{pxi},{pyi}px")
        p.end(); return px

    def _upd_fps(self):
        self._fps_lbl.setText(f"{self._fps_n} fps"); self._fps_n=0

    def _refresh_pos(self):
        drv = self._cart_drv[0] if self._cart_drv else None
        if drv:
            try:
                pos=drv.pos()
                x=pos.get("X",0);y=pos.get("Y",0);z=pos.get("Z",0)
                self._cart_lbl.setText(f"X:{x:.3f} Y:{y:.3f} Z:{z:.3f}")
                self._cart_lbl.setStyleSheet("color:#4a9eff;font-size:10px;font-family:Consolas;")
            except: pass
        if self._hxp_drvs and self._hxp_drvs[0][0]:
            try:
                drv=self._hxp_drvs[0][0]; pos=drv.qPOS(); keys=sorted(pos.keys())
                x=pos[keys[0]] if keys else 0
                y=pos[keys[1]] if len(keys)>1 else 0
                self._hxp_lbl.setText(f"X:{x:.4f} Y:{y:.4f}")
                self._hxp_lbl.setStyleSheet("color:#22c55e;font-size:10px;font-family:Consolas;")
            except: pass

    def _toggle_live(self):
        self._dot.setStyleSheet("QFrame{background:#ef4444;border-radius:4px;border:none;}")
        self._sig.setText("● LIVE"); self._sig.setStyleSheet("color:#ef4444;font-size:11px;font-weight:700;")

    def _stop(self):
        self._dot.setStyleSheet("QFrame{background:#22c55e;border-radius:4px;border:none;}")
        self._sig.setText("Connected"); self._sig.setStyleSheet("color:#22c55e;font-size:11px;")

    def _capture(self):
        cam = self._cam[0] if self._cam else None
        if not cam: return
        try:
            from pypylon import pylon; import cv2
            result = cam.GrabOne(5000)
            if result.GrabSucceeded():
                os.makedirs("./capture",exist_ok=True)
                ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(f"./capture/capture_{ts}.png",result.Array)
        except: pass

    def _apply(self):
        cam = self._cam[0] if self._cam else None
        if not cam: return
        try:
            cam.ExposureTime.SetValue(float(self._exp_e.text()))
            cam.Gain.SetValue(float(self._gain_e.text()))
        except: pass


# ══════════════════════════════════════════════
# Quick IO Button Grid
# ══════════════════════════════════════════════

class QuickIOWidget(QWidget):
    def __init__(self, wago_drv):
        super().__init__()
        self._drv  = wago_drv
        self._chs  = []
        self._btns = []
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(4)

        hr = QHBoxLayout()
        hr.addWidget(lbl("QUICK I/O","#64748b",9,True))
        hr.addStretch()
        cfg = _btn("⚙","#64748b",h=20,w=24)
        cfg.clicked.connect(self._cfg); hr.addWidget(cfg)
        v.addLayout(hr)

        self._grid_w = QWidget()
        self._grid   = QGridLayout(self._grid_w)
        self._grid.setSpacing(4)
        v.addWidget(self._grid_w)
        self._no_lbl = lbl("No channels — ⚙ to configure","#64748b",9)
        self._no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._no_lbl)

        self._load()
        QTimer(self, timeout=self._poll, interval=500).start()

    def _load(self):
        try:
            if not os.path.exists("settings.json"): return
            with open("settings.json") as f: data=json.load(f)
            chs = data.get("quick_io_channels",[])
            if chs: self._chs=chs; self._rebuild()
        except: pass

    def _rebuild(self):
        for b in self._btns:
            self._grid.removeWidget(b); b.deleteLater()
        self._btns.clear()
        self._no_lbl.setVisible(not self._chs)
        COLS = 3
        for i, ch in enumerate(self._chs):
            is_do = ch.get("type","do") == "do"
            name  = ch.get("name",f"CH_{ch.get('addr',0):05d}")
            short = name[:10] + ("…" if len(name)>10 else "")
            color = "#22c55e" if is_do else "#4a9eff"
            state = False
            b = QPushButton(f"{'●' if state else '○'}  {short}")
            b.setFixedHeight(28)
            b.setStyleSheet(
                f"QPushButton{{background:#20242e;border:1px solid #3a4055;"
                f"border-radius:4px;color:#64748b;font-size:10px;font-weight:600;"
                f"text-align:left;padding:0 6px;}}"
                f"QPushButton:hover{{border-color:{color};color:{color};}}")
            b._ch = ch; b._is_do = is_do; b._state = False
            if is_do:
                b.clicked.connect(lambda _,btn=b: self._toggle(btn))
            self._grid.addWidget(b, i//COLS, i%COLS)
            self._btns.append(b)

    def _toggle(self, btn):
        drv = self._drv[0] if self._drv else None
        if not drv: return
        try:
            new = not btn._state
            drv.write_do(btn._ch["addr"], new)
            actual = drv.read_do(btn._ch["addr"],1)[0]
            self._set_btn(btn, actual)
        except: pass

    def _set_btn(self, btn, on):
        btn._state = on
        is_do = btn._is_do
        color = "#22c55e" if is_do else "#4a9eff"
        name  = btn._ch.get("name","")[:10]
        icon  = "●" if on else "○"
        btn.setText(f"{icon}  {name}")
        if on:
            btn.setStyleSheet(
                f"QPushButton{{background:{color}22;border:1px solid {color};"
                f"border-radius:4px;color:{color};font-size:10px;font-weight:600;"
                f"text-align:left;padding:0 6px;}}")
        else:
            btn.setStyleSheet(
                f"QPushButton{{background:#20242e;border:1px solid #3a4055;"
                f"border-radius:4px;color:#64748b;font-size:10px;font-weight:600;"
                f"text-align:left;padding:0 6px;}}"
                f"QPushButton:hover{{border-color:{color};color:{color};}}")

    def _poll(self):
        drv = self._drv[0] if self._drv else None
        if not drv: return
        for btn in self._btns:
            try:
                s = drv.read_do(btn._ch["addr"],1)[0] if btn._is_do \
                    else drv.read_di(btn._ch["addr"],1)[0]
                self._set_btn(btn, s)
            except: pass

    def _cfg(self):
        wago_path = ""
        try:
            with open("settings.json") as f:
                wago_path = json.load(f).get("wago_config_path","")
        except: pass
        all_chs = []
        if wago_path and os.path.exists(wago_path):
            try:
                with open(wago_path) as f: wd=json.load(f)
                for c in wd.get("do",[]): all_chs.append({**c,"type":"do"})
                for c in wd.get("di",[]): all_chs.append({**c,"type":"di"})
            except: pass
        if not all_chs: return
        dlg = QDialog(); dlg.setWindowTitle("Select I/O Channels"); dlg.setFixedSize(380,360)
        v = QVBoxLayout(dlg)
        v.addWidget(lbl("Select channels to show:","#94a3b8",11))
        lst = QListWidget()
        lst.setStyleSheet(
            "QListWidget{background:#20242e;border:1px solid #3a4055;color:#e2e8f0;}"
            "QListWidget::item{padding:4px 8px;}")
        for ch in all_chs:
            txt=f"[{ch['type'].upper()}] {ch.get('addr',0):05d}  {ch.get('name','')}"
            item=QListWidgetItem(txt)
            item.setCheckState(
                Qt.CheckState.Checked if any(
                    s.get("addr")==ch.get("addr") and s.get("type")==ch.get("type")
                    for s in self._chs) else Qt.CheckState.Unchecked)
            lst.addItem(item)
        v.addWidget(lst)
        bb=QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec():
            self._chs=[all_chs[i] for i in range(lst.count())
                       if lst.item(i).checkState()==Qt.CheckState.Checked]
            self._rebuild()
            try:
                with open("settings.json") as f: cfg=json.load(f)
                cfg["quick_io_channels"]=self._chs
                with open("settings.json","w") as f: json.dump(cfg,f,indent=2)
            except: pass


# ══════════════════════════════════════════════
# Unified Control Widget
# ══════════════════════════════════════════════

class UnifiedControl(QFrame):
    def __init__(self, cart_drv, hxp_drvs, lin_drv):
        super().__init__()
        self._cart = cart_drv
        self._hxps = hxp_drvs
        self._lin  = lin_drv
        self._step = 0.010
        self._vel  = 1.0
        self._dev  = "Cartesian"
        self._axes = ["X","Y","Z"]
        self._ax_ud = "Y"; self._ax_lr = "X"; self._ax_sd = "Z"
        # UVW jog buttons (shown only for Hexapod)
        self._uvw_btns = []

        self.setStyleSheet("QFrame{background:transparent;border:none;}")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(6)

        self._build_dev_sel(v)
        self._build_pos(v)
        v.addWidget(_hline())
        self._build_jog(v)
        v.addWidget(_hline())
        self._build_cmds(v)

        QTimer(self, timeout=self._refresh_pos, interval=500).start()

    # ── Device selector ───────────────────────
    def _build_dev_sel(self, v):
        v.addWidget(lbl("DEVICE","#64748b",9,True))
        row = QHBoxLayout(); row.setSpacing(3)
        self._dev_btns = {}
        for name,color in [("Cartesian","#4ade80"),("Hexapod 1","#4a9eff"),
                            ("Hexapod 2","#4a9eff"),("Linear","#38bdf8")]:
            b = QPushButton(name); b.setCheckable(True); b.setFixedHeight(26)
            b.setStyleSheet(f"""
                QPushButton{{background:#20242e;border:1px solid #3a4055;
                    border-radius:4px;color:#64748b;font-size:10px;font-weight:600;padding:0 6px;}}
                QPushButton:checked{{background:#1e2d47;border-color:{color};color:{color};}}
                QPushButton:hover{{color:{color};}}
            """)
            b.clicked.connect(lambda _,n=name: self._set_device(n))
            self._dev_btns[name]=b; row.addWidget(b)
        v.addLayout(row)
        self._dev_btns["Cartesian"].setChecked(True)
        self._map_lbl = lbl("▲▼=Y  ◀▶=X  ↕=Z","#64748b",9)
        v.addWidget(self._map_lbl)

    def _set_device(self, name):
        self._dev = name
        for n,b in self._dev_btns.items(): b.setChecked(n==name)
        self._axes = DEVICE_AXES.get(name,["X","Y","Z"])
        if name=="Linear":
            self._ax_ud="—"; self._ax_lr="—"; self._ax_sd="—"
        else:
            self._ax_ud="Y"; self._ax_lr="X"; self._ax_sd="Z"
        self._update_map_lbl()
        self._update_pos_cards()
        # Show/hide UVW row
        is_hxp = name in ("Hexapod 1","Hexapod 2")
        self._uvw_frame.setVisible(is_hxp)

    # ── Position ──────────────────────────────
    def _build_pos(self, v):
        v.addWidget(lbl("POSITION","#64748b",9,True))
        self._pos_frame = QFrame()
        self._pos_frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        self._pos_layout = QVBoxLayout(self._pos_frame)
        self._pos_layout.setContentsMargins(0,0,0,0); self._pos_layout.setSpacing(2)
        v.addWidget(self._pos_frame)
        self._pos_cards = {}
        for ax,color in [("X","#4a9eff"),("Y","#22c55e"),("Z","#cba6f7"),
                          ("U","#f87171"),("V","#fb923c"),("W","#facc15"),("—","#38bdf8")]:
            unit = "mm" if ax not in ("U","V","W") else "°"
            self._pos_cards[ax] = PosInline(ax,color,unit)
        self._update_pos_cards()

    def _update_pos_cards(self):
        for i in reversed(range(self._pos_layout.count())):
            item = self._pos_layout.itemAt(i)
            if item.widget(): item.widget().setParent(None)
            elif item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w: w.setParent(None)
                self._pos_layout.removeItem(item)
        axes = self._axes
        COLS = 3
        row = None
        for i,ax in enumerate(axes):
            if i%COLS==0:
                row = QHBoxLayout(); row.setSpacing(3)
                self._pos_layout.addLayout(row)
            row.addWidget(self._pos_cards[ax])

    def _refresh_pos(self):
        drv = self._get_drv()
        if not drv: return
        try:
            if self._dev=="Linear":
                self._pos_cards["—"].set_val(drv.pos())
            elif self._dev in ("Hexapod 1","Hexapod 2"):
                pos=drv.qPOS(); keys=sorted(pos.keys())
                for i,ax in enumerate(["X","Y","Z","U","V","W"]):
                    if i<len(keys):
                        fmt=".4f" if ax in "XYZ" else ".3f"
                        self._pos_cards[ax].set_val(pos[keys[i]],fmt)
            else:
                pos=drv.pos()
                for ax,val in pos.items():
                    if ax in self._pos_cards: self._pos_cards[ax].set_val(val)
        except: pass

    # ── Jog ───────────────────────────────────
    def _build_jog(self, v):
        v.addWidget(lbl("JOG","#64748b",9,True))

        # XYZ dpad row
        xyz_row = QHBoxLayout(); xyz_row.setSpacing(8)
        dpad = QGridLayout(); dpad.setSpacing(3)
        self._j_up = _jb("▲"); self._j_dn = _jb("▼")
        self._j_lt = _jb("◀"); self._j_rt = _jb("▶")
        ctr = QFrame(); ctr.setFixedSize(34,34)
        ctr.setStyleSheet(
            "QFrame{background:#1a1d24;border:1px solid #3a4055;border-radius:4px;}")
        dpad.addWidget(self._j_up,0,1)
        dpad.addWidget(self._j_lt,1,0)
        dpad.addWidget(ctr,1,1)
        dpad.addWidget(self._j_rt,1,2)
        dpad.addWidget(self._j_dn,2,1)
        xyz_row.addLayout(dpad)

        # Side Z column
        side = QVBoxLayout(); side.setSpacing(2)
        side.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._j_zu = _jb("▲",34,"#cba6f7"); self._j_zu.setFixedHeight(28)
        self._j_zd = _jb("▼",34,"#cba6f7"); self._j_zd.setFixedHeight(28)
        self._sd_lbl = lbl("Z","#cba6f7",8,True)
        self._sd_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self._j_zu); side.addWidget(self._sd_lbl); side.addWidget(self._j_zd)
        xyz_row.addLayout(side)

        # Step + Velocity
        sv = QVBoxLayout(); sv.setSpacing(4)
        r1 = QHBoxLayout(); r1.setSpacing(4)
        r1.addWidget(lbl("Step","#64748b",9))
        self._step_e = _nin("0.010",56)
        self._step_e.textChanged.connect(
            lambda t: setattr(self,"_step",float(t) if t else 0.010))
        self._step_cb = _combo(list(STEP_MAP.keys()),w=72)
        self._step_cb.setCurrentText("10µm")
        self._step_cb.currentTextChanged.connect(self._on_step)
        r1.addWidget(self._step_e); r1.addWidget(self._step_cb)
        sv.addLayout(r1)
        r2 = QHBoxLayout(); r2.setSpacing(4)
        r2.addWidget(lbl("Vel","#64748b",9))
        self._vel_e = _nin("1.000",56)
        self._vel_e.textChanged.connect(
            lambda t: setattr(self,"_vel",float(t) if t else 1.0))
        self._vel_cb = _combo(["Slow","Med","Fast","Max"],w=72)
        self._vel_cb.setCurrentText("Med")
        self._vel_cb.currentTextChanged.connect(self._on_vel)
        r2.addWidget(self._vel_e); r2.addWidget(self._vel_cb)
        sv.addLayout(r2)
        xyz_row.addLayout(sv,1)
        v.addLayout(xyz_row)

        # UVW row — hidden by default, shown for Hexapod
        self._uvw_frame = QFrame()
        self._uvw_frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        uf = QVBoxLayout(self._uvw_frame); uf.setContentsMargins(0,4,0,0); uf.setSpacing(4)
        uf.addWidget(_hline())
        uf.addWidget(lbl("U / V / W  (rotation)","#64748b",9,True))
        uvw_btns = QHBoxLayout(); uvw_btns.setSpacing(4)
        for ax,color in [("U","#f87171"),("V","#fb923c"),("W","#facc15")]:
            bm = QPushButton(f"◀ {ax}"); bp = QPushButton(f"{ax} ▶")
            for b,d in [(bm,-1),(bp,1)]:
                b.setFixedHeight(28)
                b.setStyleSheet(
                    f"QPushButton{{background:#2a2f3d;border:1px solid {color}33;"
                    f"border-radius:4px;color:{color};font-size:11px;font-weight:600;padding:0 6px;}}"
                    f"QPushButton:hover{{background:{color};color:#000;}}"
                    f"QPushButton:pressed{{background:{color}55;}}")
                b.clicked.connect(lambda _,a=ax,dd=d: self._jog(a,dd))
                uvw_btns.addWidget(b)
        uvw_btns.addStretch()
        uf.addLayout(uvw_btns)
        self._uvw_frame.setVisible(False)
        v.addWidget(self._uvw_frame)

        # Connect dpad
        self._j_up.clicked.connect(lambda: self._jog(self._ax_ud, 1))
        self._j_dn.clicked.connect(lambda: self._jog(self._ax_ud,-1))
        self._j_lt.clicked.connect(lambda: self._jog(self._ax_lr,-1))
        self._j_rt.clicked.connect(lambda: self._jog(self._ax_lr, 1))
        self._j_zu.clicked.connect(lambda: self._jog(self._ax_sd, 1))
        self._j_zd.clicked.connect(lambda: self._jog(self._ax_sd,-1))

    def _update_map_lbl(self):
        ud=self._ax_ud; lr=self._ax_lr; sd=self._ax_sd
        self._map_lbl.setText(f"▲▼={ud}  ◀▶={lr}  ↕={sd}")
        self._sd_lbl.setText(sd)
        col=AXIS_COLORS.get(sd,"#cba6f7")
        self._sd_lbl.setStyleSheet(
            f"color:{col};font-size:8px;font-weight:700;background:transparent;")

    def _on_step(self, t):
        if t in STEP_MAP:
            self._step=STEP_MAP[t]; self._step_e.setText(f"{self._step:.4f}")

    def _on_vel(self, t):
        if t in VEL_MAP:
            self._vel=VEL_MAP[t]; self._vel_e.setText(f"{self._vel:.3f}")

    def _jog(self, axis, direction):
        if axis=="—": return
        drv=self._get_drv()
        if not drv: return
        try:
            if self._dev=="Linear":
                drv.vel(self._vel); drv.mov_relative(direction*self._step)
            elif self._dev in ("Hexapod 1","Hexapod 2"):
                axes=sorted(drv.axes)
                ax_map={"X":0,"Y":1,"Z":2,"U":3,"V":4,"W":5}
                idx=ax_map.get(axis,0)
                if idx>=len(axes): return
                cur=drv.qPOS(axes[idx])[axes[idx]]
                drv.MOV(axes[idx], cur+direction*self._step)
            else:
                drv.vel_all(self._vel)
                drv.mov_relative(axis, direction*self._step)
        except: pass

    # ── Commands ──────────────────────────────
    def _build_cmds(self, v):
        row = QHBoxLayout(); row.setSpacing(4)
        goto_btn = _btn("📍 Go to...","#eab308",h=26)
        goto_btn.clicked.connect(self._goto_popup)
        row.addWidget(goto_btn)
        for t,fn,c in [("Home",self._home,"#4a9eff"),
                        ("FRF",self._frf,"#4a9eff"),
                        ("ONT?",self._ont,"#4a9eff"),
                        ("HALT",self._halt,"#ef4444")]:
            b=_btn(t,c,h=26); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); v.addLayout(row)

    def _goto_popup(self):
        dlg=GoToDialog(self._axes, self.window())
        if dlg.exec():
            vals=dlg.get_values(); drv=self._get_drv()
            if not drv: return
            try:
                if self._dev=="Linear":
                    pos=vals.get("—",0.0)
                    drv.vel(self._vel); drv.mov(pos)
                elif self._dev in ("Hexapod 1","Hexapod 2"):
                    axes=sorted(drv.axes)
                    ax_map={"X":0,"Y":1,"Z":2,"U":3,"V":4,"W":5}
                    cmd={axes[ax_map[ax]]:v for ax,v in vals.items()
                         if ax in ax_map and ax_map[ax]<len(axes)}
                    drv.MOV(cmd)
                else:
                    x=vals.get("X",0); y=vals.get("Y",0); z=vals.get("Z",0)
                    drv.vel_all(self._vel); drv.mov_xyz(x,y,z)
            except: pass

    def _home(self):
        drv=self._get_drv()
        if not drv: return
        try:
            if self._dev=="Linear": drv.vel(self._vel); drv.mov(0.0)
            elif self._dev in ("Hexapod 1","Hexapod 2"): drv.MOV({a:0.0 for a in drv.axes})
            else: drv.vel_all(self._vel); drv.home()
        except: pass

    def _frf(self):
        drv=self._get_drv()
        if not drv: return
        try:
            if self._dev=="Linear": drv.frf()
            else: drv.FRF(list(drv.axes))
        except: pass

    def _ont(self):
        drv=self._get_drv()
        if not drv: return
        try:
            if self._dev in ("Hexapod 1","Hexapod 2"): drv.qONT()
            else: drv.ont()
        except: pass

    def _halt(self):
        drv=self._get_drv()
        if not drv: return
        try:
            if self._dev=="Linear": drv.halt()
            elif self._dev in ("Hexapod 1","Hexapod 2"): drv.HLT()
            else: drv.halt()
        except: pass

    def _get_drv(self):
        if self._dev=="Cartesian": return self._cart[0] if self._cart else None
        if self._dev=="Hexapod 1": return self._hxps[0][0] if self._hxps else None
        if self._dev=="Hexapod 2": return self._hxps[1][0] if len(self._hxps)>1 else None
        if self._dev=="Linear":    return self._lin[0] if self._lin else None


# ══════════════════════════════════════════════
# Motion Control Page
# ══════════════════════════════════════════════

class MotionControlPage(QWidget):
    def __init__(self):
        super().__init__()
        self._cart_drv = [None]
        self._hxp_drvs = [[None],[None]]
        self._lin_drv  = [None]
        self._cam_ref  = [None]
        self._wago_drv = [None]

        root = QHBoxLayout(self)
        root.setContentsMargins(12,12,12,12); root.setSpacing(10)

        # ── Left scroll panel ─────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(400)
        scroll.setStyleSheet(
            "QScrollArea{background:#20242e;border:1px solid #3a4055;border-radius:6px;}"
            "QScrollBar:vertical{width:6px;background:#16191f;}"
            "QScrollBar::handle:vertical{background:#3a4055;border-radius:3px;}")
        inner = QWidget(); inner.setStyleSheet("background:transparent;")
        sv = QVBoxLayout(inner); sv.setContentsMargins(12,12,12,12); sv.setSpacing(8)

        # Status bar
        self._build_status(sv)
        sv.addWidget(_hline())

        # Unified motion control
        self._ctrl = UnifiedControl(self._cart_drv, self._hxp_drvs, self._lin_drv)
        sv.addWidget(self._ctrl)
        sv.addWidget(_hline())

        # Quick IO
        self._qio = QuickIOWidget(self._wago_drv)
        sv.addWidget(self._qio)
        sv.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll)

        # ── Right: Camera ─────────────────────
        cam_frame = QFrame()
        cam_frame.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        cv = QVBoxLayout(cam_frame); cv.setContentsMargins(0,0,0,0); cv.setSpacing(0)
        self._cam_w = CameraWidget(self._cam_ref, self._cart_drv, self._hxp_drvs)
        cv.addWidget(self._cam_w)
        root.addWidget(cam_frame,1)

    def _build_status(self, layout):
        bar = QHBoxLayout(); bar.setSpacing(5)
        devs=[("Cartesian","#4ade80"),("Hexapod 1","#4a9eff"),
              ("Hexapod 2","#4a9eff"),("Linear","#38bdf8"),
              ("Camera","#eab308"),("WAGO","#38bdf8")]
        for name,color in devs:
            f=QFrame()
            f.setStyleSheet("QFrame{background:#16191f;border:1px solid #3a4055;border-radius:4px;}")
            h=QHBoxLayout(f); h.setContentsMargins(5,3,5,3); h.setSpacing(4)
            dot=QFrame(); dot.setFixedSize(7,7)
            dot.setStyleSheet("QFrame{background:#3d0a0a;border-radius:3px;border:none;}")
            h.addWidget(dot); h.addWidget(lbl(name,"#64748b",9))
            bar.addWidget(f)
        bar.addStretch()
        halt=QPushButton("⛔ HALT ALL"); halt.setFixedHeight(28)
        halt.setStyleSheet(
            "QPushButton{background:#2a0000;border:1px solid #ef4444;"
            "border-radius:4px;color:#ef4444;font-size:11px;font-weight:700;padding:0 10px;}"
            "QPushButton:hover{background:#ef4444;color:#fff;}")
        halt.clicked.connect(self._halt_all)
        bar.addWidget(halt)
        layout.addLayout(bar)

    def _halt_all(self):
        for drv in [self._cart_drv]+self._hxp_drvs+[self._lin_drv]:
            if drv[0]:
                try:
                    if hasattr(drv[0],"halt"): drv[0].halt()
                    elif hasattr(drv[0],"HLT"): drv[0].HLT()
                except: pass

    def set_cart_driver(self, drv):    self._cart_drv[0]=drv
    def set_hxp_driver(self, drv, i): self._hxp_drvs[i][0]=drv
    def set_lin_driver(self, drv):     self._lin_drv[0]=drv
    def set_cam(self, cam):            self._cam_ref[0]=cam
    def set_wago_driver(self, drv):    self._wago_drv[0]=drv
