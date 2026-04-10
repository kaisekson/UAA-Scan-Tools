"""
PI Hexapod Panel
=================
- รองรับ 2 ตัว (tab)
- Mounting orientation: Vertical / Horizontal Left / Horizontal Right
- Position readback X Y Z U V W
- Jog control: Step / Continuous + step/velocity preset
- Command console + autocomplete จาก gcs_commands.json
- Response log
"""

import os, json, datetime, time, socket
try:
    from pipython import GCSDevice, pitools
    HAS_PIPYTHON = True
except ImportError:
    HAS_PIPYTHON = False
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame,
    QTabWidget, QScrollArea, QListWidget, QListWidgetItem,
    QTextEdit, QSizePolicy, QButtonGroup
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

MAX_HXP = 2
CMD_FILE = "config/gcs_commands.json"

ORIENTATIONS = {
    "Vertical": {
        "map": {"X": "Left / Right", "Y": "Front / Back", "Z": "Up / Down",
                "U": "Pitch", "V": "Roll", "W": "Yaw"},
        "jog_x": ("X", "◀", "▶"),
        "jog_y": ("Y", "▼", "▲"),
        "jog_z": ("Z", "▼", "▲"),
    },
    "Horizontal Left": {
        "map": {"X": "Up / Down", "Y": "Front / Back", "Z": "Left / Right",
                "U": "Pitch", "V": "Roll", "W": "Yaw"},
        "jog_x": ("Z", "◀", "▶"),
        "jog_y": ("Y", "▼", "▲"),
        "jog_z": ("X", "▼", "▲"),
    },
    "Horizontal Right": {
        "map": {"X": "Up / Down", "Y": "Front / Back", "Z": "Right / Left",
                "U": "Pitch", "V": "Roll", "W": "Yaw"},
        "jog_x": ("Z", "▶", "◀"),
        "jog_y": ("Y", "▼", "▲"),
        "jog_z": ("X", "▼", "▲"),
    },
}

STEP_PRESETS = [
    ("0.1µm",  0.0001),
    ("0.5µm",  0.0005),
    ("1µm",    0.001),
    ("2µm",    0.002),
    ("5µm",    0.005),
    ("10µm",   0.010),
    ("20µm",   0.020),
    ("50µm",   0.050),
    ("100µm",  0.100),
    ("200µm",  0.200),
    ("250µm",  0.250),
    ("500µm",  0.500),
    ("1000µm", 1.000),
    ("2000µm", 2.000),
    ("5000µm", 5.000),
]
VEL_PRESETS = [
    ("Slow",  0.1),
    ("Med",   1.0),
    ("Fast",  5.0),
    ("Max",   10.0),
]


# ══════════════════════════════════════════════
# Axis mapping per mounting orientation
# User กด axis ไหน → controller ส่ง axis อะไร
# ══════════════════════════════════════════════
AXIS_MAP = {
    "Vertical": {
        "X": ("X",  1), "Y": ("Y",  1), "Z": ("Z",  1),
        "U": ("U",  1), "V": ("V",  1), "W": ("W",  1),
    },
    "Horizontal Left": {
        "X": ("Z",  1), "Y": ("Y", -1), "Z": ("X",  1),
        "U": ("V",  1), "V": ("U",  1), "W": ("W",  1),
    },
    "Horizontal Right": {
        "X": ("Z", -1), "Y": ("Y",  1), "Z": ("X",  1),
        "U": ("V", -1), "V": ("U", -1), "W": ("W", -1),
    },
}

ORIENT_WARNING = {
    "Vertical":
        "Vertical mounting — standard axis mapping.",
    "Horizontal Left":
        "⚠ Horizontal Left — axis mapping changed!\n"
        "X→Z  Y→Y  Z→X  U→V  V→U  W→W\n"
        "Verify direction before moving. Stay clear of limits.",
    "Horizontal Right":
        "⚠ Horizontal Right — axis mapping changed + reversed!\n"
        "X→Z(-) Y→Y Z→X(-) U→V(-) V→U(-) W→W(-)\n"
        "Verify direction before moving. Stay clear of limits.",
}


class JogWorker(QThread):
    """รัน jog command — fire and forget ไม่ wait_target"""
    finished = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, drv, axis, delta, vel):
        super().__init__()
        self._drv   = drv
        self._axis  = axis
        self._delta = delta
        self._vel   = vel

    def run(self):
        try:
            self._drv.vel(self._axis, self._vel)
            self._drv.mov_relative(self._axis, self._delta)
            # ไม่ wait_target — ส่งแล้วจบ
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


def load_commands():
    if os.path.exists(CMD_FILE):
        with open(CMD_FILE) as f:
            return json.load(f).get("commands", [])
    return ["POS?", "FRF", "ONT?", "ERR?", "*IDN?"]


# ══════════════════════════════════════════════
# GCS Driver
# ══════════════════════════════════════════════

class GCSDriver:
    """PI Hexapod driver — raw TCP socket (เหมือน Hercules)"""
    BUFFER  = 4096
    TIMEOUT = 5.0

    def __init__(self, ip, port=50000):
        self.ip   = ip
        self.port = port
        self._sock = None
        self._axes = []   # cache axis names

    # ── Low-level socket ──────────────────────

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.TIMEOUT)
        self._sock.connect((self.ip, self.port))
        time.sleep(0.2)
        # flush greeting ถ้ามี
        self._sock.settimeout(0.3)
        try: self._sock.recv(self.BUFFER)
        except: pass
        self._sock.settimeout(self.TIMEOUT)
        # cache axis list
        try:
            resp = self.query_raw("SAI?")
            self._axes = [a.strip() for a in resp.strip().split("\n") if a.strip()]
        except:
            self._axes = ["1","2","3","4","5","6"]

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    def send_raw(self, cmd):
        """ส่ง command ดิบ + LF"""
        self._sock.sendall((cmd.strip() + "\n").encode())
        time.sleep(0.02)

    def query_raw(self, cmd):
        """ส่ง query + LF แล้วรับ response"""
        self._sock.sendall((cmd.strip() + "\n").encode())
        time.sleep(0.02)
        self._sock.settimeout(0.5)
        data = b""
        try:
            data = self._sock.recv(self.BUFFER)
        except: pass
        self._sock.settimeout(self.TIMEOUT)
        return data.decode().strip()

    # ── High-level commands ───────────────────

    def idn(self):
        return self.query_raw("*IDN?")

    def pos(self):
        """คืน dict {axis: float}"""
        resp = self.query_raw("POS?")
        result = {}
        for line in resp.strip().split("\n"):
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                try: result[k.strip()] = float(v.strip())
                except: pass
        return result

    def ont(self):
        return self.query_raw("ONT?")

    def err(self):
        return self.query_raw("ERR?")

    def mov(self, axis, val):
        self.send_raw(f"MOV {axis} {val}")

    def mov_relative(self, axis, delta):
        """MVR = move relative โดยตรง ไม่ต้อง query POS ก่อน"""
        self.send_raw(f"MVR {axis} {delta}")

    def wait_target(self, axes=None, timeout=10):
        """Poll ONT? จนทุก axis on target"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self.query_raw("ONT?")
            vals = {}
            for line in resp.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    try: vals[k.strip()] = int(v.strip())
                    except: pass
            check = list(axes) if axes else self._axes
            if all(vals.get(a, 0) == 1 for a in check):
                return
            time.sleep(0.05)
        raise TimeoutError("wait_target timeout")

    def vel(self, axis, v):
        self.send_raw(f"VEL {axis} {v}")

    def halt(self):
        self.send_raw("HLT")

    def svo_on(self):
        for a in self._axes:
            self.send_raw(f"SVO {a} 1")

    def svo_off(self):
        for a in self._axes:
            self.send_raw(f"SVO {a} 0")

    def frf(self):
        for a in self._axes:
            self.send_raw(f"FRF {a}")
        self.wait_target(timeout=60)

    def home(self):
        for a in self._axes:
            self.send_raw(f"MOV {a} 0")


class ConnectWorker(QThread):
    success = pyqtSignal(str, object)  # idn, driver
    failed  = pyqtSignal(str)
    def __init__(self, ip, port):
        super().__init__(); self.ip=ip; self.port=port
    def run(self):
        try:
            d = GCSDriver(self.ip, self.port)
            d.connect()
            idn = d.idn()
            self.success.emit(idn, d)  # ส่ง driver กลับมาเลย ไม่ disconnect
        except Exception as e:
            self.failed.emit(str(e))


# ══════════════════════════════════════════════
# Position card
# ══════════════════════════════════════════════

class PosCard(QFrame):
    def __init__(self, axis, unit="mm", color="#4a9eff"):
        super().__init__()
        self.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:4px;}")
        self.setFixedHeight(56)
        h = QHBoxLayout(self); h.setContentsMargins(8,4,8,4); h.setSpacing(4)
        ax_lbl = lbl(axis, "#4a5568", 12, True)
        ax_lbl.setFixedWidth(18)
        self._val = QLabel("0.0000")
        self._val.setFont(QFont("Consolas", 15, 700))
        self._val.setStyleSheet(f"color:{color};background:transparent;")
        self._unit = lbl(unit, "#2a3444", 10)
        h.addWidget(ax_lbl)
        h.addWidget(self._val, 1)
        h.addWidget(self._unit)

    def set_value(self, v): self._val.setText(f"{v:.4f}")


# ══════════════════════════════════════════════
# Jog button
# ══════════════════════════════════════════════

class JogBtn(QPushButton):
    def __init__(self, text, color="#4a9eff"):
        super().__init__(text)
        self.setFixedSize(34,34)
        self._color=color
        self.setStyleSheet(f"""
            QPushButton{{background:#161b22;border:1px solid #1e2433;
                border-radius:4px;color:#8892a4;font-size:13px;}}
            QPushButton:hover{{border-color:{color};color:{color};background:#0d1520;}}
            QPushButton:pressed{{background:{color}33;}}
        """)


# ══════════════════════════════════════════════
# Single Hexapod Widget
# ══════════════════════════════════════════════

class SingleHexapodWidget(QWidget):
    def __init__(self, index):
        super().__init__()
        self._drv      = None
        self._index    = index
        self._orient   = "Vertical"
        self._jog_mode = "Step"
        self._step     = 0.010
        self._vel      = 1.0
        self._cmds     = load_commands()
        self._continuous_axis = None
        self._continuous_dir  = 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,12,14,12)
        layout.setSpacing(10)

        # ── Connection ──────────────────────────
        self._build_connection(layout)

        # ── Orientation ─────────────────────────
        self._build_orientation(layout)

        # ── Position ────────────────────────────
        self._build_position(layout)

        # ── Jog ─────────────────────────────────
        self._build_jog(layout)
        layout.addWidget(divider())

        # ── Command console ──────────────────────
        self._build_console(layout)
        layout.addWidget(divider())

        # ── Log ─────────────────────────────────
        self._build_log(layout)
        layout.addStretch()

        # Timers
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._refresh_pos)
        self._pos_timer.start(500)

        self._cont_timer = QTimer(self)
        self._cont_timer.timeout.connect(self._continuous_step)
        self._cont_timer.setInterval(100)

    # ── Connection ───────────────────────────────
    def _build_connection(self, layout):
        self._sh(layout, "CONNECTION")
        card = QFrame(); card.setStyleSheet("QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(8)

        row = QHBoxLayout(); row.setSpacing(10)
        ip_f = QFrame(); ip_v = QVBoxLayout(ip_f); ip_v.setContentsMargins(0,0,0,0); ip_v.setSpacing(3)
        ip_v.addWidget(lbl("IP Address","#4a5568",10))
        self.ip_edit = QLineEdit(); self.ip_edit.setPlaceholderText("192.168.1.10")
        self.ip_edit.setStyleSheet("border-left:2px solid #4a9eff;background:#161b22;border-top:1px solid #1e2433;border-right:1px solid #1e2433;border-bottom:1px solid #1e2433;border-radius:4px;color:#c5cdd9;padding:5px 8px;font-size:12px;")
        ip_v.addWidget(self.ip_edit); row.addWidget(ip_f,2)

        pt_f = QFrame(); pt_v = QVBoxLayout(pt_f); pt_v.setContentsMargins(0,0,0,0); pt_v.setSpacing(3)
        pt_v.addWidget(lbl("Port","#4a5568",10))
        self.port_edit = QLineEdit("50000")
        self.port_edit.setStyleSheet("border-left:2px solid #4a9eff;background:#161b22;border-top:1px solid #1e2433;border-right:1px solid #1e2433;border-bottom:1px solid #1e2433;border-radius:4px;color:#c5cdd9;padding:5px 8px;font-size:12px;")
        pt_v.addWidget(self.port_edit); row.addWidget(pt_f,1)
        v.addLayout(row)

        conn_row = QHBoxLayout(); conn_row.setSpacing(10)
        self.conn_btn = QPushButton("⟳  Connect"); self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet("QPushButton{background:#0d1520;border:1px solid #4a9eff;border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}QPushButton:hover{background:#4a9eff;color:#000;}")
        self.conn_btn.clicked.connect(self._connect)
        self.status_lbl = lbl("○  Disconnected","#4a5568",12)
        self.idn_lbl    = lbl("IDN: —","#2a3444",11)
        conn_row.addWidget(self.conn_btn); conn_row.addWidget(self.status_lbl)
        conn_row.addStretch(); conn_row.addWidget(self.idn_lbl)
        v.addLayout(conn_row)
        layout.addWidget(card)

    # ── Orientation ──────────────────────────────
    def _build_orientation(self, layout):
        self._sh(layout,"MOUNTING ORIENTATION")
        card = QFrame(); card.setStyleSheet("QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(8)

        orient_row = QHBoxLayout(); orient_row.setSpacing(6)
        orient_row.addWidget(lbl("Orientation","#4a5568",10))
        self._orient_btns = {}
        for name in ORIENTATIONS:
            btn = QPushButton(name); btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setStyleSheet("""
                QPushButton{background:#161b22;border:1px solid #1e2433;border-radius:4px;color:#8892a4;font-size:11px;padding:0 10px;}
                QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}
                QPushButton:checked{background:#0d1520;border-color:#4a9eff;color:#4a9eff;font-weight:600;}
            """)
            btn.clicked.connect(lambda _, n=name: self._set_orient(n, show_warning=True))
            self._orient_btns[name] = btn
            orient_row.addWidget(btn)
        orient_row.addStretch()
        v.addLayout(orient_row)

        self._orient_map_lbl = QLabel()
        self._orient_map_lbl.setStyleSheet("background:#0a0c10;border:1px solid #1e2433;border-radius:4px;color:#8892a4;font-size:11px;padding:6px 10px;")
        self._orient_map_lbl.setWordWrap(True)
        v.addWidget(self._orient_map_lbl)

        # Warning frame — ปุ่ม Close ชัดเจน
        self._warn_frame = QFrame()
        self._warn_frame.setStyleSheet(
            "QFrame{background:#1a0e00;border:1px solid #854f0b;"
            "border-left:3px solid #ef9f27;border-radius:4px;}")
        self._warn_frame.setVisible(False)
        warn_row = QHBoxLayout(self._warn_frame)
        warn_row.setContentsMargins(10,8,8,8); warn_row.setSpacing(8)
        self._warn_lbl = QLabel()
        self._warn_lbl.setStyleSheet(
            "background:transparent;border:none;color:#ef9f27;font-size:11px;")
        self._warn_lbl.setWordWrap(True)
        close_btn = QPushButton("✕  Close")
        close_btn.setFixedWidth(70); close_btn.setFixedHeight(26)
        close_btn.setStyleSheet(
            "QPushButton{background:#2a1400;border:1px solid #854f0b;"
            "border-radius:4px;color:#ef9f27;font-size:11px;padding:0 8px;}"
            "QPushButton:hover{background:#854f0b;color:#fff;}")
        close_btn.clicked.connect(lambda: self._warn_frame.setVisible(False))
        warn_row.addWidget(self._warn_lbl, 1)
        warn_row.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(self._warn_frame)

        layout.addWidget(card)
        self._set_orient("Vertical", show_warning=False)

    def _set_orient(self, name, show_warning=False):
        self._orient = name
        for n, btn in self._orient_btns.items():
            btn.setChecked(n == name)

        # แสดง axis mapping ครบ 6 แกน
        mapping = AXIS_MAP[name]
        parts = []
        for user_ax, (ctrl_ax, d) in mapping.items():
            sign  = "+" if d > 0 else "−"
            color = "#4a9eff" if user_ax in "XYZ" else "#cba6f7"
            parts.append(
                f"<span style='color:{color};font-weight:700;'>{user_ax}+</span>"
                f"<span style='color:#4a5568;'> → </span>"
                f"<span style='color:#c5cdd9;'>MOV {ctrl_ax}{sign}</span>"
            )
        self._orient_map_lbl.setText("&nbsp;&nbsp;".join(parts))
        self._orient_map_lbl.setTextFormat(Qt.TextFormat.RichText)

        # แสดง warning เฉพาะตอน user กดเปลี่ยนเท่านั้น
        if show_warning and name != "Vertical":
            warn = ORIENT_WARNING.get(name, "")
            self._warn_lbl.setText(warn)
            self._warn_frame.setVisible(True)
        elif show_warning and name == "Vertical":
            self._warn_frame.setVisible(False)

    # ── Position ─────────────────────────────────
    def _build_position(self, layout):
        sh_row = QHBoxLayout(); sh_row.setSpacing(8)
        sh_row.addWidget(lbl("POSITION","#4a5568",10,True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#1e2433;max-height:1px;")
        sh_row.addWidget(line,1)
        ref_btn = QPushButton("⟳"); ref_btn.setFixedSize(26,22)
        ref_btn.setStyleSheet(
            "QPushButton{background:#1a1f2e;border:1px solid #1e2433;"
            "border-radius:3px;color:#8892a4;font-size:10px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        ref_btn.clicked.connect(self._refresh_pos)
        sh_row.addWidget(ref_btn); layout.addLayout(sh_row)

        pos_frame = QFrame()
        pos_frame.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        pv = QVBoxLayout(pos_frame); pv.setContentsMargins(10,6,10,6); pv.setSpacing(4)

        # แถวเดียว USER | PI
        row = QHBoxLayout(); row.setSpacing(8)

        # USER coordinates
        user_lbl = lbl("USER","#22c55e",9,True); user_lbl.setFixedWidth(36)
        row.addWidget(user_lbl)
        self._user_pos_lbls = {}
        for ax in ["X","Y","Z","U","V","W"]:
            color = "#22c55e" if ax in "XYZ" else "#a3f0c4"
            unit  = "mm" if ax in "XYZ" else "°"
            f = QFrame(); f.setStyleSheet("QFrame{background:transparent;border:none;}")
            fh = QHBoxLayout(f); fh.setContentsMargins(0,0,0,0); fh.setSpacing(2)
            fh.addWidget(lbl(ax, "#4a5568", 11, True))
            v = QLabel("0.0000"); v.setFont(QFont("Consolas",14,700))
            v.setStyleSheet(f"color:{color};background:transparent;")
            fh.addWidget(v)
            fh.addWidget(lbl(unit,"#2a3444",9))
            self._user_pos_lbls[ax] = v
            row.addWidget(f)

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet("background:#3a4055;max-width:1px;")
        row.addWidget(div)

        # PI coordinates
        pi_lbl = lbl("PI","#4a9eff",9,True); pi_lbl.setFixedWidth(20)
        row.addWidget(pi_lbl)
        self._pos_cards = {}
        for ax, color in [("X","#4a9eff"),("Y","#4a9eff"),("Z","#4a9eff"),
                           ("U","#cba6f7"),("V","#cba6f7"),("W","#cba6f7")]:
            unit = "mm" if ax in "XYZ" else "°"
            f = QFrame(); f.setStyleSheet("QFrame{background:transparent;border:none;}")
            fh = QHBoxLayout(f); fh.setContentsMargins(0,0,0,0); fh.setSpacing(2)
            fh.addWidget(lbl(ax,"#4a5568",10,True))
            v = QLabel("0.0000"); v.setFont(QFont("Consolas",13,700))
            v.setStyleSheet(f"color:{color};background:transparent;")
            fh.addWidget(v)
            fh.addWidget(lbl(unit,"#2a3444",9))
            self._pos_cards[ax] = v
            row.addWidget(f)

        pv.addLayout(row)
        layout.addWidget(pos_frame)

    # ── Jog ──────────────────────────────────────
    def _build_jog(self, layout):
        self._sh(layout, "JOG CONTROL")

        # ── แถวบน: D-pad | Z | Rotation | Settings ──
        top = QHBoxLayout(); top.setSpacing(16)
        top.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # D-pad XY
        dpad_w = QFrame()
        dpad_w.setStyleSheet("QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        dv = QVBoxLayout(dpad_w); dv.setContentsMargins(10,8,10,8); dv.setSpacing(4)
        dv.addWidget(lbl("XY","#4a5568",9,True))
        dpad_grid = QGridLayout(); dpad_grid.setSpacing(4)
        self._jog_up    = JogBtn("▲"); self._jog_down  = JogBtn("▼")
        self._jog_left  = JogBtn("◀"); self._jog_right = JogBtn("▶")
        ctr = QPushButton(); ctr.setFixedSize(38,38)
        ctr.setStyleSheet("QPushButton{background:#111318;border:1px solid #1e2433;border-radius:4px;}")
        dpad_grid.addWidget(self._jog_up,   0,1)
        dpad_grid.addWidget(self._jog_left, 1,0)
        dpad_grid.addWidget(ctr,            1,1)
        dpad_grid.addWidget(self._jog_right,1,2)
        dpad_grid.addWidget(self._jog_down, 2,1)
        dv.addLayout(dpad_grid)
        top.addWidget(dpad_w)

        # Z up/down
        z_w = QFrame()
        z_w.setStyleSheet("QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        zv = QVBoxLayout(z_w); zv.setContentsMargins(10,8,10,8); zv.setSpacing(4)
        zv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zv.addWidget(lbl("Z","#4a5568",9,True))
        self._jog_zup   = JogBtn("▲"); self._jog_zup.setFixedSize(42,38)
        self._jog_zdown = JogBtn("▼"); self._jog_zdown.setFixedSize(42,38)
        zv.addWidget(self._jog_zup)
        zv.addSpacing(4)
        zv.addWidget(self._jog_zdown)
        top.addWidget(z_w)

        # Rotation UVW
        rot_w = QFrame()
        rot_w.setStyleSheet("QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        rv = QVBoxLayout(rot_w); rv.setContentsMargins(10,8,10,8); rv.setSpacing(6)
        rv.addWidget(lbl("ROTATION","#4a5568",9,True))
        self._rot_btns = {}
        for ax, color in [("U","#cba6f7"),("V","#cba6f7"),("W","#cba6f7")]:
            row = QHBoxLayout(); row.setSpacing(5)
            row.addWidget(lbl(ax, color, 12, True))
            bm = JogBtn("−", color); bm.setFixedSize(38,34)
            bp = JogBtn("+", color); bp.setFixedSize(38,34)
            bm.clicked.connect(lambda _, a=ax: self._jog(a,-1))
            bp.clicked.connect(lambda _, a=ax: self._jog(a, 1))
            self._rot_btns[ax] = (bm, bp)
            row.addWidget(bm); row.addWidget(bp)
            rv.addLayout(row)
        top.addWidget(rot_w)

        # Settings panel
        set_w = QFrame()
        set_w.setStyleSheet("QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        sv = QVBoxLayout(set_w); sv.setContentsMargins(12,8,12,8); sv.setSpacing(6)

        # Mode
        mode_row = QHBoxLayout(); mode_row.setSpacing(5)
        mode_row.addWidget(lbl("Mode","#4a5568",10))
        self._mode_step = QPushButton("Step"); self._mode_step.setCheckable(True); self._mode_step.setChecked(True)
        self._mode_cont = QPushButton("Continuous"); self._mode_cont.setCheckable(True)
        MODE_OFF = "QPushButton{background:#161b22;border:1px solid #1e2433;border-radius:4px;color:#4a5568;font-size:11px;padding:0 10px;}"
        MODE_ON  = "QPushButton{background:#0d1520;border:1px solid #22c55e;border-radius:4px;color:#22c55e;font-size:11px;font-weight:600;padding:0 10px;}"
        for b in [self._mode_step, self._mode_cont]:
            b.setFixedHeight(26); b.setCheckable(False)
            b.setStyleSheet(MODE_OFF)
        self._mode_step.setStyleSheet(MODE_ON)
        self._MODE_ON  = MODE_ON
        self._MODE_OFF = MODE_OFF
        self._mode_step.clicked.connect(lambda: self._set_mode("Step"))
        self._mode_cont.clicked.connect(lambda: self._set_mode("Continuous"))
        mode_row.addWidget(self._mode_step); mode_row.addWidget(self._mode_cont); mode_row.addStretch()
        sv.addLayout(mode_row)

        # Step size + preset
        step_row = QHBoxLayout(); step_row.setSpacing(5)
        step_row.addWidget(lbl("Step","#4a5568",10))
        self._step_edit = QLineEdit("0.010"); self._step_edit.setFixedWidth(64)
        self._step_edit.setStyleSheet("background:#161b22;border:1px solid #1e2433;border-radius:4px;color:#c5cdd9;padding:4px 6px;font-size:11px;font-family:monospace;")
        self._step_edit.textChanged.connect(lambda v: setattr(self,"_step",float(v) if v else 0.010))
        step_row.addWidget(self._step_edit); step_row.addWidget(lbl("mm","#4a5568",9))
        from PyQt6.QtWidgets import QComboBox
        self._step_combo = QComboBox()
        for label, _ in STEP_PRESETS:
            self._step_combo.addItem(label)
        self._step_combo.setCurrentText("10µm")
        self._step_combo.setFixedHeight(26)
        self._step_combo.setStyleSheet("""
            QComboBox{background:#161b22;border:1px solid #1e2433;border-radius:4px;
                color:#c5cdd9;padding:2px 6px;font-size:11px;}
            QComboBox::drop-down{border:none;}
            QComboBox QAbstractItemView{background:#0d0f14;border:1px solid #1e2433;color:#c5cdd9;font-size:11px;}
        """)
        self._step_combo.currentTextChanged.connect(self._on_step_combo)
        step_row.addWidget(self._step_combo)
        sv.addLayout(step_row)

        # Velocity + preset
        vel_row = QHBoxLayout(); vel_row.setSpacing(5)
        vel_row.addWidget(lbl("Vel","#4a5568",10))
        self._vel_edit = QLineEdit("1.000"); self._vel_edit.setFixedWidth(64)
        self._vel_edit.setStyleSheet("background:#161b22;border:1px solid #1e2433;border-radius:4px;color:#c5cdd9;padding:4px 6px;font-size:11px;font-family:monospace;")
        self._vel_edit.textChanged.connect(lambda v: setattr(self,"_vel",float(v) if v else 1.0))
        vel_row.addWidget(self._vel_edit); vel_row.addWidget(lbl("mm/s","#4a5568",9))
        for label, val in VEL_PRESETS:
            b = QPushButton(label); b.setFixedHeight(24)
            b.setStyleSheet("QPushButton{background:#161b22;border:1px solid #1e2433;border-radius:3px;color:#8892a4;font-size:10px;padding:0 5px;}QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
            b.clicked.connect(lambda _, v=val: self._set_vel(v))
            vel_row.addWidget(b)
        sv.addLayout(vel_row)
        # Quick commands — grid 2 คอลัมน์
        qcmd_w = QFrame()
        qcmd_w.setStyleSheet("QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        qv = QVBoxLayout(qcmd_w); qv.setContentsMargins(10,8,10,8); qv.setSpacing(5)
        qv.addWidget(lbl("COMMANDS","#4a5568",9,True))
        qgrid = QGridLayout(); qgrid.setSpacing(4)
        cmds = [
            ("Home",      self._home,    "#4a9eff"),
            ("FRF",       self._frf,     "#4a9eff"),
            ("POS?",      self._pos_cmd, "#4a9eff"),
            ("ONT?",      self._ont,     "#4a9eff"),
            ("ERR?",      self._err_cmd, "#4a9eff"),
            ("Servo ON",  self._svo_on,  "#22c55e"),
            ("Servo OFF", self._svo_off, "#eab308"),
            ("HALT",      self._halt,    "#ef4444"),
        ]
        for i, (label, fn, color) in enumerate(cmds):
            b = QPushButton(label); b.setFixedHeight(28)
            b.setStyleSheet(f"QPushButton{{background:#161b22;border:1px solid #1e2433;border-radius:4px;color:#4a5568;font-size:11px;padding:0 8px;}}QPushButton:hover{{border-color:{color};color:{color};}}")
            b.clicked.connect(fn)
            qgrid.addWidget(b, i//2, i%2)
        qv.addLayout(qgrid)
        top.addWidget(qcmd_w)

        top.addWidget(set_w, 1)
        layout.addLayout(top)

        # Connect D-pad
        self._jog_up.clicked.connect(lambda: self._jog("Y", 1))
        self._jog_down.clicked.connect(lambda: self._jog("Y",-1))
        self._jog_left.clicked.connect(lambda: self._jog("X",-1))
        self._jog_right.clicked.connect(lambda: self._jog("X", 1))
        self._jog_zup.clicked.connect(lambda: self._jog("Z", 1))
        self._jog_zdown.clicked.connect(lambda: self._jog("Z",-1))

    # ── Command console ───────────────────────────
    def _build_console(self, layout):
        self._sh(layout,"COMMAND CONSOLE")

        input_row = QHBoxLayout(); input_row.setSpacing(6)
        self._cmd_edit = QLineEdit()
        self._cmd_edit.setPlaceholderText("Type GCS command...")
        self._cmd_edit.setStyleSheet("background:#0a0c10;border:1px solid #1e2433;border-radius:4px;color:#c5cdd9;padding:6px 10px;font-size:12px;font-family:Consolas,monospace;")
        self._cmd_edit.textChanged.connect(self._update_autocomplete)
        self._cmd_edit.returnPressed.connect(self._send_cmd)
        send_btn = QPushButton("Send"); send_btn.setFixedHeight(32)
        send_btn.setStyleSheet("QPushButton{background:#0d1520;border:1px solid #4a9eff;border-radius:4px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}QPushButton:hover{background:#4a9eff;color:#000;}")
        send_btn.clicked.connect(self._send_cmd)
        input_row.addWidget(self._cmd_edit,1); input_row.addWidget(send_btn)
        layout.addLayout(input_row)

        self._ac_list = QListWidget()
        self._ac_list.setFixedHeight(72)
        self._ac_list.setStyleSheet("QListWidget{background:#0a0c10;border:1px solid #1e2433;border-radius:4px;color:#8892a4;font-size:11px;font-family:Consolas,monospace;}QListWidget::item:hover{background:#1e2433;color:#4a9eff;}QListWidget::item:selected{background:#0d1520;color:#4a9eff;}")
        self._ac_list.itemClicked.connect(lambda item: self._cmd_edit.setText(item.text()))
        self._ac_list.setVisible(False)
        layout.addWidget(self._ac_list)

    # ── Log ──────────────────────────────────────
    def _build_log(self, layout):
        self._sh(layout,"RESPONSE LOG")
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(80)
        self._log.setStyleSheet("QTextEdit{background:#0a0c10;border:1px solid #1e2433;border-radius:5px;color:#4a5568;font-size:11px;font-family:Consolas,monospace;}")
        layout.addWidget(self._log)

    # ── Section header ────────────────────────────
    def _sh(self, layout, title):
        row = QHBoxLayout(); row.setSpacing(8)
        row.addWidget(lbl(title,"#4a5568",10,True))
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#1e2433;max-height:1px;"); row.addWidget(line,1)
        layout.addLayout(row)

    # ── Log helper ────────────────────────────────
    def _log_msg(self, msg, color="#22c55e"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(f'<span style="color:{color};">[{ts}]</span> <span style="color:#8892a4;">{msg}</span>')

    # ── Connect ───────────────────────────────────
    def _connect(self):
        ip   = self.ip_edit.text().strip()
        port = int(self.port_edit.text() or 50000)
        if not ip:
            self.status_lbl.setText("✗  Enter IP"); self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;"); return
        self.conn_btn.setEnabled(False)
        self.status_lbl.setText("○  Connecting..."); self.status_lbl.setStyleSheet("color:#eab308;font-size:12px;")
        self._worker = ConnectWorker(ip, port)
        self._worker.success.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, idn, drv):
        self._drv = drv  # รับ driver ที่ connect แล้วมาเลย ไม่ต้อง connect ใหม่
        self.status_lbl.setText("●  Connected"); self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.idn_lbl.setText(f"IDN: {idn}"); self.idn_lbl.setStyleSheet("color:#8892a4;font-size:11px;")
        self.conn_btn.setText("✗  Disconnect"); self.conn_btn.setEnabled(True)
        self.conn_btn.clicked.disconnect(); self.conn_btn.clicked.connect(self._disconnect)
        self._log_msg(f"Connected → {idn}")

    def _on_fail(self, err):
        self.status_lbl.setText(f"✗  {err}"); self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;")
        self.conn_btn.setEnabled(True); self._log_msg(f"Failed: {err}","#ef4444")

    def _disconnect(self):
        if self._drv:
            try: self._drv.disconnect()
            except: pass
            self._drv = None
        self.status_lbl.setText("○  Disconnected"); self.status_lbl.setStyleSheet("color:#4a5568;font-size:12px;")
        self.idn_lbl.setText("IDN: —")
        self.conn_btn.setText("⟳  Connect")
        self.conn_btn.clicked.disconnect(); self.conn_btn.clicked.connect(self._connect)
        self._log_msg("Disconnected","#4a5568")

    # ── Position ──────────────────────────────────
    def _refresh_pos(self):
        if not self._drv: return
        try:
            pos = self._drv.pos()
            # PI coordinates
            for ax, val in pos.items():
                if ax in self._pos_cards:
                    self._pos_cards[ax].setText(f"{float(val):.4f}")

            # USER coordinates — แปลงตาม AXIS_MAP
            mapping = AXIS_MAP[self._orient]
            for user_ax, (pi_ax, mult) in mapping.items():
                if user_ax in self._user_pos_lbls and pi_ax in pos:
                    user_val = float(pos[pi_ax]) * mult
                    self._user_pos_lbls[user_ax].setText(f"{user_val:.4f}")
        except: pass

    # ── Jog ──────────────────────────────────────
    def _set_mode(self, mode):
        self._jog_mode = mode
        self._mode_step.setStyleSheet(self._MODE_ON  if mode=="Step"       else self._MODE_OFF)
        self._mode_cont.setStyleSheet(self._MODE_ON  if mode=="Continuous" else self._MODE_OFF)
        if mode == "Step": self._cont_timer.stop()

    def _on_step_combo(self, label):
        for lb, val in STEP_PRESETS:
            if lb == label:
                self._set_step(val, lb); break

    def _set_step(self, val, label):
        self._step = val
        self._step_edit.setText(f"{val:.4f}")

    def _set_vel(self, val):
        self._vel = val
        self._vel_edit.setText(f"{val:.3f}")

    def _jog(self, axis, direction):
        if not self._drv:
            self._log_msg("Not connected","#ef4444"); return
        ctrl_axis, mult = AXIS_MAP[self._orient].get(axis, (axis, 1))
        delta = mult * direction * self._step
        self._log_msg(
            f"JOG {axis}{'+' if direction>0 else '-'}  →  "
            f"MVR {ctrl_axis} {delta:+.4f} mm  [{self._orient}]"
        )
        worker = JogWorker(self._drv, ctrl_axis, delta, self._vel)
        worker.finished.connect(self._refresh_pos)
        worker.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        worker.start()
        self._jog_worker = worker

    def _pos_val(self, axis):
        try: return float(self._pos_cards[axis]._val.text())
        except: return 0.0

    # ── Quick commands ────────────────────────────
    def _send_raw(self, cmd):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try:
            if cmd.strip().endswith("?"):
                resp = self._drv.query_raw(cmd)
                self._log_msg(f"{cmd} → {resp}")
            else:
                self._drv.send_raw(cmd)
                self._log_msg(cmd)
            self._refresh_pos()
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _home(self):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try:
            self._drv.home()
            self._log_msg("MOV all axes → 0")
            self._drv.wait_target(timeout=15)
            self._refresh_pos()
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _frf(self):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try:
            self._log_msg("FRF — Referencing all axes...")
            self._drv.frf()
            self._drv.wait_target(timeout=60)
            self._log_msg("FRF done")
            self._refresh_pos()
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _ont(self):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try: self._log_msg(f"ONT? → {self._drv.ont()}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _err_cmd(self):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try: self._log_msg(f"ERR? → {self._drv.err()}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _pos_cmd(self):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try:
            pos = self._drv.pos()
            msg = "  ".join([f"{k}={v:.4f}" for k,v in pos.items()])
            self._log_msg(f"POS? → {msg}")
            self._refresh_pos()
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _svo_on(self):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try: self._drv.svo_on(); self._log_msg("Servo ON")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _svo_off(self):
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try: self._drv.svo_off(); self._log_msg("Servo OFF","#eab308")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _halt(self):
        if not self._drv: return
        try: self._drv.halt(); self._log_msg("HALT","#ef4444")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _continuous_step(self):
        if self._continuous_axis and self._drv:
            self._jog(self._continuous_axis, self._continuous_dir)

    # ── Autocomplete ─────────────────────────────
    def _update_autocomplete(self, text):
        if not text:
            self._ac_list.setVisible(False); return
        matches = [c for c in self._cmds if text.upper() in c.upper()][:8]
        self._ac_list.clear()
        for m in matches:
            self._ac_list.addItem(m)
        self._ac_list.setVisible(bool(matches))

    def _send_cmd(self):
        cmd = self._cmd_edit.text().strip()
        if not cmd: return
        self._send_raw(cmd)
        self._cmd_edit.clear()
        self._ac_list.setVisible(False)

    # ── Save / Load ───────────────────────────────
    def get_settings(self):
        return {
            "ip":          self.ip_edit.text().strip(),
            "port":        int(self.port_edit.text() or 50000),
            "orientation": self._orient,
            "step":        self._step,
            "velocity":    self._vel,
        }

    def load_settings(self, data):
        self.ip_edit.setText(data.get("ip",""))
        self.port_edit.setText(str(data.get("port",50000)))
        self._set_orient(data.get("orientation","Vertical"), show_warning=False)
        self._set_step(data.get("step",0.010),"custom")
        self._set_vel(data.get("velocity",1.0))


# ══════════════════════════════════════════════
# Hexapod Panel (multi)
# ══════════════════════════════════════════════

class HexapodPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._count = 0
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane{border:none;background:#111318;}
            QTabBar::tab{background:#0d0f14;color:#4a5568;padding:8px 20px;border:1px solid #1e2433;font-size:12px;min-width:90px;}
            QTabBar::tab:selected{background:#111318;color:#4a9eff;border-bottom:2px solid #4a9eff;}
            QTabBar::tab:hover{color:#8892a4;}
        """)
        self.tabs.tabBarClicked.connect(self._tab_clicked)
        layout.addWidget(self.tabs)

        self._add_hxp()
        self._refresh_add_tab()

    def _add_hxp(self):
        if self._count >= MAX_HXP: return
        self._count += 1
        widget = SingleHexapodWidget(self._count)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#111318;"); scroll.setWidget(widget)
        insert_at = self.tabs.count()
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "＋": insert_at=i; break
        self.tabs.insertTab(insert_at, scroll, f"Hexapod {self._count}")
        self.tabs.setCurrentIndex(insert_at)

    def _refresh_add_tab(self):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "＋": self.tabs.removeTab(i); break
        if self._count < MAX_HXP:
            self.tabs.addTab(QWidget(), "＋")

    def _tab_clicked(self, idx):
        if self.tabs.tabText(idx) == "＋":
            self._add_hxp(); self._refresh_add_tab()

    def get_all_settings(self):
        result = []
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "＋": continue
            w = self.tabs.widget(i).widget()
            result.append(w.get_settings())
        return result

    def load_all_settings(self, data_list):
        if not data_list: return
        while self._count > 0:
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) != "＋":
                    self.tabs.removeTab(i); self._count-=1; break
            else: break
        for d in data_list[:MAX_HXP]:
            self._add_hxp()
            w = self.tabs.widget(self._count-1).widget()
            w.load_settings(d)
        self._refresh_add_tab()