"""
Basler Camera Panel
====================
- Auto detect USB + GigE cameras via pypylon
- Live view with QTimer
- Capture + save PNG/TIFF/BMP/JPEG
- Camera settings: exposure, gain, fps, pixel format, resolution
"""

import os, datetime
import numpy as np

try:
    from pypylon import pylon
    HAS_PYLON = True
except ImportError:
    HAS_PYLON = False

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame,
    QScrollArea, QTextEdit, QFileDialog, QComboBox,
    QListWidget, QListWidgetItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap
from core.widgets import lbl, divider


# ══════════════════════════════════════════════
# Grab Worker
# ══════════════════════════════════════════════

class GrabWorker(QThread):
    frame = pyqtSignal(np.ndarray)
    error = pyqtSignal(str)

    def __init__(self, camera):
        super().__init__()
        self._cam    = camera
        self._active = True

    def stop(self):
        self._active = False

    def run(self):
        try:
            self._cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            while self._active and self._cam.IsGrabbing():
                result = self._cam.RetrieveResult(
                    2000, pylon.TimeoutHandling_ThrowException)
                if result.GrabSucceeded():
                    img = result.Array.copy()
                    self.frame.emit(img)
                result.Release()
        except Exception as e:
            if self._active:
                self.error.emit(str(e))
        finally:
            try: self._cam.StopGrabbing()
            except: pass


# ══════════════════════════════════════════════
# Camera Panel
# ══════════════════════════════════════════════

class CameraPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._camera    = None
        self._grabber   = None
        self._live      = False
        self._save_dir  = "./capture"
        self._devices   = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#1a1d24;border:none;")
        inner  = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16,14,16,14)
        layout.setSpacing(10)

        self._build_detect(layout)

        body = QHBoxLayout(); body.setSpacing(12)
        self._build_preview(body)
        self._build_settings(body)
        layout.addLayout(body)

        layout.addWidget(divider())
        self._build_log(layout)
        layout.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(scroll)

    # ── helpers ───────────────────────────────
    def _sh(self, layout, title, extra=None):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(lbl(title,"#64748b",10,True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#3a4055;max-height:1px;")
        row.addWidget(line,1)
        if extra: row.addWidget(extra)
        layout.addLayout(row)

    def _log_msg(self, msg, color="#4a9eff"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:{color};">[{ts}]</span> '
            f'<span style="color:#94a3b8;">{msg}</span>')

    # ── Detect ────────────────────────────────
    def _build_detect(self, layout):
        scan_btn = QPushButton("⟳ Scan")
        scan_btn.setFixedHeight(24)
        scan_btn.setStyleSheet(
            "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
            "border-radius:4px;color:#94a3b8;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        scan_btn.clicked.connect(self._scan)
        self._sh(layout,"CAMERAS DETECTED", scan_btn)

        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        self._cam_list = QListWidget()
        self._cam_list.setFixedHeight(90)
        self._cam_list.setStyleSheet(
            "QListWidget{background:transparent;border:none;color:#e2e8f0;font-size:12px;}"
            "QListWidget::item{padding:4px 8px;border-radius:4px;border:1px solid #3a4055;"
            "background:#16191f;margin-bottom:3px;}"
            "QListWidget::item:selected{background:#1e2d47;border-color:#4a9eff;color:#4a9eff;}")
        v.addWidget(self._cam_list)

        cr = QHBoxLayout(); cr.setSpacing(8)
        self.conn_btn = QPushButton("⟳  Connect")
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(
            "QPushButton{background:#1e2d47;border:1px solid #4a9eff;"
            "border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}")
        self.conn_btn.clicked.connect(self._connect)
        self.status_lbl = lbl("○  Not connected","#64748b",12)
        cr.addWidget(self.conn_btn); cr.addWidget(self.status_lbl); cr.addStretch()
        v.addLayout(cr)
        layout.addWidget(card)

        # Auto scan on startup
        QTimer.singleShot(500, self._scan)

    # ── Preview ───────────────────────────────
    def _build_preview(self, layout):
        col = QVBoxLayout(); col.setSpacing(8)
        self._sh(col,"LIVE VIEW")

        preview_frame = QFrame()
        preview_frame.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")
        pv = QVBoxLayout(preview_frame); pv.setContentsMargins(0,0,0,0); pv.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame{background:#16191f;border:none;"
            "border-bottom:1px solid #3a4055;border-radius:6px 6px 0 0;}")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(10,6,10,6); hh.setSpacing(8)
        self._live_dot = QFrame(); self._live_dot.setFixedSize(8,8)
        self._live_dot.setStyleSheet("QFrame{background:#3d0a0a;border-radius:4px;border:none;}")
        self._live_lbl = lbl("No signal","#64748b",11)
        live_btn = QPushButton("▶  Live"); live_btn.setFixedHeight(26)
        live_btn.setStyleSheet(
            "QPushButton{background:#1a3a1a;border:1px solid #22c55e;"
            "border-radius:4px;color:#22c55e;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{background:#22c55e;color:#000;}")
        live_btn.clicked.connect(self._start_live)
        stop_btn = QPushButton("■  Stop"); stop_btn.setFixedHeight(26)
        stop_btn.setStyleSheet(
            "QPushButton{background:#1a0000;border:1px solid #ef4444;"
            "border-radius:4px;color:#ef4444;font-size:11px;padding:0 10px;}"
            "QPushButton:hover{background:#ef4444;color:#fff;}")
        stop_btn.clicked.connect(self._stop_live)
        hh.addWidget(self._live_dot); hh.addWidget(self._live_lbl)
        hh.addStretch(); hh.addWidget(live_btn); hh.addWidget(stop_btn)
        pv.addWidget(hdr)

        # Image area
        self._img_lbl = QLabel()
        self._img_lbl.setFixedHeight(220)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background:#16191f;color:#64748b;font-size:12px;")
        self._img_lbl.setText("📷  Camera not connected")
        pv.addWidget(self._img_lbl)
        col.addWidget(preview_frame)

        # Capture row
        cap_row = QHBoxLayout(); cap_row.setSpacing(6)
        cap_btn = QPushButton("📸  Capture"); cap_btn.setFixedHeight(32)
        cap_btn.setStyleSheet(
            "QPushButton{background:#1e2d47;border:1px solid #4a9eff;"
            "border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}")
        cap_btn.clicked.connect(self._capture)
        self._path_lbl = QLabel(self._save_dir)
        self._path_lbl.setStyleSheet(
            "background:#16191f;border:1px solid #3a4055;border-radius:4px;"
            "color:#64748b;font-size:11px;padding:5px 10px;font-family:monospace;")
        browse_btn = QPushButton("📂"); browse_btn.setFixedSize(32,32)
        browse_btn.setStyleSheet(
            "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
            "border-radius:4px;color:#94a3b8;font-size:13px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        browse_btn.clicked.connect(self._browse_dir)
        cap_row.addWidget(cap_btn); cap_row.addWidget(self._path_lbl,1); cap_row.addWidget(browse_btn)
        col.addLayout(cap_row)
        layout.addLayout(col, 1)

    # ── Settings ──────────────────────────────
    def _build_settings(self, layout):
        col = QVBoxLayout(); col.setSpacing(8)
        self._sh(col,"CAMERA SETTINGS")

        settings_frame = QFrame()
        settings_frame.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        sv = QVBoxLayout(settings_frame); sv.setContentsMargins(12,10,12,10); sv.setSpacing(8)

        # Param grid
        pgrid = QGridLayout(); pgrid.setSpacing(8)
        self._params = {}
        fields = [
            ("exposure",  "EXPOSURE (µs)", "10000",  None),
            ("gain",      "GAIN (dB)",     "0.0",    None),
            ("fps",       "FPS LIMIT",     "30",     None),
            ("pxformat",  "PIXEL FORMAT",  None,     ["Mono8","Mono12","BGR8","RGB8"]),
            ("width",     "WIDTH (px)",    "1920",   None),
            ("height",    "HEIGHT (px)",   "1080",   None),
        ]
        for i, (key, lbl_txt, default, options) in enumerate(fields):
            f = QFrame(); f.setStyleSheet(
                "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:5px;}")
            fv = QVBoxLayout(f); fv.setContentsMargins(8,6,8,6); fv.setSpacing(3)
            fv.addWidget(lbl(lbl_txt,"#64748b",9,True))
            if options:
                w = QComboBox(); w.addItems(options)
                w.setStyleSheet(
                    "QComboBox{background:#2a2f3d;border:1px solid #3a4055;border-radius:4px;"
                    "color:#e2e8f0;padding:3px 6px;font-size:11px;}"
                    "QComboBox::drop-down{border:none;}"
                    "QComboBox QAbstractItemView{background:#20242e;color:#e2e8f0;}")
            else:
                w = QLineEdit(default)
                w.setStyleSheet(
                    "background:#2a2f3d;border:1px solid #3a4055;border-radius:4px;"
                    "color:#e2e8f0;padding:4px 6px;font-size:12px;font-family:monospace;")
            self._params[key] = w
            fv.addWidget(w)
            pgrid.addWidget(f, i//2, i%2)
        sv.addLayout(pgrid)

        apply_btn = QPushButton("Apply settings")
        apply_btn.setFixedHeight(30)
        apply_btn.setStyleSheet(
            "QPushButton{background:#2a2f3d;border:1px solid #3a4055;"
            "border-radius:5px;color:#94a3b8;font-size:12px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        apply_btn.clicked.connect(self._apply_settings)
        sv.addWidget(apply_btn)
        sv.addWidget(divider())

        # Capture settings
        sv.addWidget(lbl("CAPTURE","#64748b",10,True))
        for attr, lbl_txt, default, options in [
            ("prefix_edit", "Filename prefix", "capture_", None),
            ("format_cb",   "Format",          None,       ["PNG","TIFF","BMP","JPEG"]),
            ("ts_cb",       "Auto-timestamp",  None,       ["ON","OFF"]),
        ]:
            row = QHBoxLayout(); row.setSpacing(6)
            row.addWidget(lbl(lbl_txt,"#64748b",10))
            if options:
                w = QComboBox(); w.addItems(options)
                w.setStyleSheet(
                    "QComboBox{background:#2a2f3d;border:1px solid #3a4055;border-radius:4px;"
                    "color:#e2e8f0;padding:3px 6px;font-size:11px;}"
                    "QComboBox::drop-down{border:none;}"
                    "QComboBox QAbstractItemView{background:#20242e;color:#e2e8f0;}")
            else:
                w = QLineEdit(default)
                w.setStyleSheet(
                    "background:#2a2f3d;border:1px solid #3a4055;border-radius:4px;"
                    "color:#e2e8f0;padding:4px 6px;font-size:11px;font-family:monospace;")
            setattr(self, attr, w); row.addWidget(w,1)
            sv.addLayout(row)

        col.addWidget(settings_frame)
        col.addStretch()
        layout.addLayout(col, 1)

    # ── Log ───────────────────────────────────
    def _build_log(self, layout):
        self._sh(layout,"RESPONSE LOG")
        self._log = QTextEdit()
        self._log.setReadOnly(True); self._log.setFixedHeight(70)
        self._log.setStyleSheet(
            "QTextEdit{background:#16191f;border:1px solid #3a4055;border-radius:5px;"
            "color:#64748b;font-size:11px;font-family:Consolas,monospace;}")
        layout.addWidget(self._log)

    # ── Scan ──────────────────────────────────
    def _scan(self):
        self._cam_list.clear()
        self._devices = []
        if not HAS_PYLON:
            self._log_msg("pypylon not installed — pip install pypylon","#ef4444")
            item = QListWidgetItem("⚠  pypylon not installed")
            self._cam_list.addItem(item)
            return
        try:
            tl = pylon.TlFactory.GetInstance()
            devs = tl.EnumerateDevices()
            self._devices = list(devs)
            if not devs:
                item = QListWidgetItem("No cameras found")
                self._cam_list.addItem(item)
                self._log_msg("No cameras found","#eab308")
                return
            for d in devs:
                model  = d.GetModelName()
                sn     = d.GetSerialNumber()
                iface  = d.GetDeviceClass()
                label  = f"{model}  |  SN:{sn}  |  {iface}"
                item   = QListWidgetItem(label)
                self._cam_list.addItem(item)
            self._cam_list.setCurrentRow(0)
            self._log_msg(f"Found {len(devs)} camera(s)")
        except Exception as e:
            self._log_msg(str(e),"#ef4444")

    # ── Connect ───────────────────────────────
    def _connect(self):
        if not HAS_PYLON: return
        idx = self._cam_list.currentRow()
        if idx < 0 or idx >= len(self._devices): return
        try:
            if self._camera:
                self._stop_live()
                self._camera.Close()
            tl  = pylon.TlFactory.GetInstance()
            dev = tl.CreateDevice(self._devices[idx])
            self._camera = pylon.InstantCamera(dev)
            self._camera.Open()
            model = self._devices[idx].GetModelName()
            self.status_lbl.setText(f"●  {model}")
            self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
            self.conn_btn.setText("✗  Disconnect")
            self.conn_btn.clicked.disconnect()
            self.conn_btn.clicked.connect(self._disconnect)
            self._live_dot.setStyleSheet("QFrame{background:#22c55e;border-radius:4px;border:none;}")
            self._live_lbl.setText("Connected")
            self._img_lbl.setText("▶ Press Live to start")
            self._log_msg(f"Connected → {model} SN:{self._devices[idx].GetSerialNumber()}")
        except Exception as e:
            self._log_msg(str(e),"#ef4444")

    def _disconnect(self):
        self._stop_live()
        if self._camera:
            try: self._camera.Close()
            except: pass
            self._camera = None
        self.status_lbl.setText("○  Not connected")
        self.status_lbl.setStyleSheet("color:#64748b;font-size:12px;")
        self.conn_btn.setText("⟳  Connect")
        self.conn_btn.clicked.disconnect()
        self.conn_btn.clicked.connect(self._connect)
        self._live_dot.setStyleSheet("QFrame{background:#3d0a0a;border-radius:4px;border:none;}")
        self._live_lbl.setText("No signal")
        self._img_lbl.setText("📷  Camera not connected")
        self._log_msg("Disconnected","#64748b")

    # ── Live ──────────────────────────────────
    def _start_live(self):
        if not self._camera or self._live: return
        self._live = True
        self._live_dot.setStyleSheet("QFrame{background:#ef4444;border-radius:4px;border:none;}")
        self._live_lbl.setText("● LIVE")
        self._grabber = GrabWorker(self._camera)
        self._grabber.frame.connect(self._on_frame)
        self._grabber.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        self._grabber.start()
        self._log_msg("Live view started")

    def _stop_live(self):
        if not self._live: return
        self._live = False
        if self._grabber:
            self._grabber.stop()
            self._grabber.wait(2000)
            self._grabber = None
        self._live_dot.setStyleSheet("QFrame{background:#22c55e;border-radius:4px;border:none;}")
        self._live_lbl.setText("Connected")
        self._log_msg("Live view stopped","#64748b")

    def _on_frame(self, arr):
        """แปลง numpy array → QPixmap แสดงใน label"""
        try:
            if arr.ndim == 2:
                h, w = arr.shape
                if arr.dtype == np.uint16:
                    arr = (arr >> 4).astype(np.uint8)
                qi = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8)
            else:
                h, w, c = arr.shape
                qi = QImage(arr.data, w, h, w*c, QImage.Format.Format_BGR888)
            px = QPixmap.fromImage(qi).scaled(
                self._img_lbl.width(), self._img_lbl.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation)
            self._img_lbl.setPixmap(px)
        except: pass

    # ── Apply settings ────────────────────────
    def _apply_settings(self):
        if not self._camera: self._log_msg("Not connected","#ef4444"); return
        try:
            cam = self._camera
            cam.ExposureTime.SetValue(float(self._params["exposure"].text()))
            cam.Gain.SetValue(float(self._params["gain"].text()))
            cam.AcquisitionFrameRateEnable.SetValue(True)
            cam.AcquisitionFrameRate.SetValue(float(self._params["fps"].text()))
            fmt = self._params["pxformat"].currentText()
            cam.PixelFormat.SetValue(fmt)
            self._log_msg(f"Settings applied — Exp:{self._params['exposure'].text()}µs "
                         f"Gain:{self._params['gain'].text()}dB FPS:{self._params['fps'].text()}")
        except Exception as e:
            self._log_msg(str(e),"#ef4444")

    # ── Capture ───────────────────────────────
    def _capture(self):
        if not self._camera: self._log_msg("Not connected","#ef4444"); return
        try:
            os.makedirs(self._save_dir, exist_ok=True)
            prefix = self.prefix_edit.text()
            fmt    = self.format_cb.currentText().lower()
            use_ts = self.ts_cb.currentText() == "ON"
            ts     = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") if use_ts else ""
            fname  = f"{prefix}{ts}.{fmt}"
            fpath  = os.path.join(self._save_dir, fname)

            # grab 1 frame
            result = self._camera.GrabOne(5000)
            if result.GrabSucceeded():
                converter = pylon.ImageFormatConverter()
                converter.OutputPixelFormat = pylon.PixelType_BGR8packed
                converted = converter.Convert(result)
                img = converted.GetArray()
                import cv2
                cv2.imwrite(fpath, img)
                self._log_msg(f"Capture saved → {fname}")
            else:
                self._log_msg("Grab failed","#ef4444")
        except Exception as e:
            self._log_msg(str(e),"#ef4444")

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self,"Select save folder","./")
        if path:
            self._save_dir = path
            self._path_lbl.setText(path)

    # ── Settings save/load ────────────────────
    def get_settings(self):
        return {
            "save_dir": self._save_dir,
            "exposure": self._params["exposure"].text(),
            "gain":     self._params["gain"].text(),
            "fps":      self._params["fps"].text(),
        }

    def load_settings(self, data):
        self._save_dir = data.get("save_dir","./capture")
        self._path_lbl.setText(self._save_dir)
        if "exposure" in data: self._params["exposure"].setText(data["exposure"])
        if "gain"     in data: self._params["gain"].setText(data["gain"])
        if "fps"      in data: self._params["fps"].setText(data["fps"])
