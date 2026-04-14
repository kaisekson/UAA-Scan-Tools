"""
PI Cartesian XYZ Panel — Motion Only
======================================
- Connect via raw TCP socket (เหมือน Hercules)
- Position readback X Y Z
- Jog: D-pad XY + Z up/down, Step/Continuous
- Go to XYZ position
- Command console + autocomplete
- Response log
"""

import os, json, datetime, time, socket
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame,
    QScrollArea, QTextEdit, QListWidget, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

CMD_FILE = "config/gcs_commands.json"

STEP_PRESETS = [
    ("0.1µm", 0.0001), ("1µm",  0.001),  ("5µm",   0.005),
    ("10µm",  0.010),  ("50µm", 0.050),  ("100µm", 0.100),
    ("500µm", 0.500),  ("1mm",  1.000),  ("5mm",   5.000),
]
VEL_PRESETS = [
    ("Slow", 0.1), ("Med", 1.0), ("Fast", 5.0), ("Max", 10.0),
]


def load_commands():
    if os.path.exists(CMD_FILE):
        with open(CMD_FILE) as f:
            return json.load(f).get("commands", [])
    return ["POS?", "FRF", "ONT?", "ERR?", "*IDN?", "HLT", "TMN?", "TMX?"]


# ══════════════════════════════════════════════
# Driver — raw TCP socket
# ══════════════════════════════════════════════

class CartesianDriver:
    BUFFER  = 4096
    TIMEOUT = 5.0

    def __init__(self, ip, port=50000):
        self.ip    = ip
        self.port  = port
        self._sock = None
        self._axes = ["1","2","3"]  # cache axis names

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.TIMEOUT)
        self._sock.connect((self.ip, self.port))
        time.sleep(0.2)
        self._sock.settimeout(0.3)
        try: self._sock.recv(self.BUFFER)
        except: pass
        self._sock.settimeout(self.TIMEOUT)
        # get axis names
        try:
            resp = self.query_raw("SAI?")
            axes = [a.strip() for a in resp.strip().split("\n") if a.strip()]
            if axes: self._axes = axes[:3]
        except:
            self._axes = ["1","2","3"]

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    def send_raw(self, cmd):
        self._sock.sendall((cmd.strip() + "\n").encode())
        time.sleep(0.02)

    def query_raw(self, cmd):
        self._sock.sendall((cmd.strip() + "\n").encode())
        time.sleep(0.02)
        self._sock.settimeout(0.5)
        data = b""
        try: data = self._sock.recv(self.BUFFER)
        except: pass
        self._sock.settimeout(self.TIMEOUT)
        return data.decode().strip()

    def idn(self):
        return self.query_raw("*IDN?")

    def pos(self):
        """คืน dict {X: val, Y: val, Z: val}"""
        resp = self.query_raw("POS?")
        result = {}
        labels = ["X","Y","Z"]
        for i, line in enumerate(resp.strip().split("\n")):
            if "=" in line and i < 3:
                try:
                    result[labels[i]] = float(line.split("=")[1].strip())
                except: pass
        return result

    def ont(self):  return self.query_raw("ONT?")
    def err(self):  return self.query_raw("ERR?")

    def mov_xyz(self, x=None, y=None, z=None):
        vals = [(x,0),(y,1),(z,2)]
        for val, idx in vals:
            if val is not None and idx < len(self._axes):
                self.send_raw(f"MOV {self._axes[idx]} {val}")

    def mov_relative(self, axis_label, delta):
        idx = {"X":0,"Y":1,"Z":2}.get(axis_label, 0)
        if idx >= len(self._axes): return
        ax = self._axes[idx]
        resp = self.query_raw(f"POS? {ax}")
        cur = 0.0
        if "=" in resp:
            try: cur = float(resp.split("=")[1].strip())
            except: pass
        self.send_raw(f"MVR {ax} {delta}")

    def vel_all(self, v):
        for ax in self._axes:
            self.send_raw(f"VEL {ax} {v}")

    def halt(self):
        self.send_raw("HLT")

    def home(self):
        for ax in self._axes:
            self.send_raw(f"MOV {ax} 0")

    def frf(self):
        for ax in self._axes:
            self.send_raw(f"FRF {ax}")

    def wait_target(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self.query_raw("ONT?")
            vals = {}
            for line in resp.strip().split("\n"):
                if "=" in line:
                    try:
                        k, v = line.split("=", 1)
                        vals[k.strip()] = int(v.strip())
                    except: pass
            if all(vals.get(a, 0) == 1 for a in self._axes):
                return
            time.sleep(0.05)


# ══════════════════════════════════════════════
# Workers
# ══════════════════════════════════════════════

class ConnectWorker(QThread):
    success = pyqtSignal(str, object)
    failed  = pyqtSignal(str)
    def __init__(self, ip, port):
        super().__init__(); self.ip=ip; self.port=port
    def run(self):
        try:
            d = CartesianDriver(self.ip, self.port)
            d.connect()
            idn = d.idn()
            self.success.emit(idn, d)
        except Exception as e:
            self.failed.emit(str(e))


class MoveWorker(QThread):
    finished = pyqtSignal()
    error    = pyqtSignal(str)
    def __init__(self, drv, fn, vel=1.0):
        super().__init__()
        self._drv = drv; self._fn = fn; self._vel = vel
    def run(self):
        try:
            self._drv.vel_all(self._vel)
            self._fn()
            # fire and forget — ไม่ wait_target
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


# ══════════════════════════════════════════════
# Position Card
# ══════════════════════════════════════════════

class PosCard(QFrame):
    def __init__(self, axis, color):
        super().__init__()
        self.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        self.setFixedHeight(52)
        h = QHBoxLayout(self)
        h.setContentsMargins(12,6,12,6); h.setSpacing(8)
        ax = QLabel(axis)
        ax.setFont(QFont("Consolas",12,700))
        ax.setStyleSheet(f"color:{color};background:transparent;")
        ax.setFixedWidth(16)
        self._val = QLabel("0.0000")
        self._val.setFont(QFont("Consolas",20,700))
        self._val.setStyleSheet(f"color:{color};background:transparent;")
        unit = lbl("mm","#2a3444",10)
        h.addWidget(ax); h.addWidget(self._val,1); h.addWidget(unit)

    def set_value(self, v): self._val.setText(f"{v:.4f}")


# ══════════════════════════════════════════════
# Jog Button
# ══════════════════════════════════════════════

class JogBtn(QPushButton):
    def __init__(self, text, color="#4a9eff"):
        super().__init__(text)
        self.setFixedSize(38,38)
        self.setStyleSheet(f"""
            QPushButton{{background:#161b22;border:1px solid #1e2433;
                border-radius:4px;color:#8892a4;font-size:14px;}}
            QPushButton:hover{{border-color:{color};color:{color};background:#0d1520;}}
            QPushButton:pressed{{background:{color}33;}}
        """)


# ══════════════════════════════════════════════
# Main Panel
# ══════════════════════════════════════════════

class CartesianPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._drv   = None
        self._step  = 0.010
        self._vel   = 1.0
        self._cmds  = load_commands()
        self._MODE_ON  = ("QPushButton{background:#0d1520;border:1px solid #22c55e;"
                          "border-radius:4px;color:#22c55e;font-size:11px;font-weight:600;padding:0 10px;}")
        self._MODE_OFF = ("QPushButton{background:#161b22;border:1px solid #1e2433;"
                          "border-radius:4px;color:#4a5568;font-size:11px;padding:0 10px;}")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#111318;border:none;")
        inner  = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16,14,16,14)
        layout.setSpacing(10)

        self._build_connection(layout)
        self._build_position(layout)
        self._build_jog(layout)
        self._build_goto(layout)
        layout.addWidget(divider())
        self._build_console(layout)
        layout.addWidget(divider())
        self._build_log(layout)
        layout.addStretch()

        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(scroll)

        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._refresh_pos)
        self._pos_timer.start(500)

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

    def _vl(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet("color:#1e2433;"); f.setFixedWidth(1); return f

    # ── Connection ────────────────────────────
    def _build_connection(self, layout):
        self._sh(layout,"CONNECTION")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(8)

        row = QHBoxLayout(); row.setSpacing(10)
        for attr, lbl_txt, default, w in [
            ("ip_edit",   "IP Address", "192.168.1.10", 2),
            ("port_edit", "Port",       "50000",        1),
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
            setattr(self, attr, e); fv.addWidget(e); row.addWidget(f, w)
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

    # ── Position ──────────────────────────────
    def _build_position(self, layout):
        ref_btn = QPushButton("⟳")
        ref_btn.setFixedSize(26,22)
        ref_btn.setStyleSheet(
            "QPushButton{background:#1a1f2e;border:1px solid #1e2433;"
            "border-radius:3px;color:#8892a4;font-size:10px;}"
            "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
        ref_btn.clicked.connect(self._refresh_pos)
        self._sh(layout,"POSITION", ref_btn)

        pos_row = QHBoxLayout(); pos_row.setSpacing(8)
        self._pos_cards = {}
        for ax, color in [("X","#4a9eff"),("Y","#22c55e"),("Z","#cba6f7")]:
            card = PosCard(ax, color)
            self._pos_cards[ax] = card
            pos_row.addWidget(card)
        layout.addLayout(pos_row)

    # ── Jog ───────────────────────────────────
    def _build_jog(self, layout):
        self._sh(layout,"JOG CONTROL")
        jog_row = QHBoxLayout(); jog_row.setSpacing(14)
        jog_row.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # D-pad XY
        dpad_w = QFrame()
        dpad_w.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        dv = QVBoxLayout(dpad_w); dv.setContentsMargins(10,8,10,8); dv.setSpacing(5)
        dv.addWidget(lbl("XY","#4a5568",9,True))
        dpad = QGridLayout(); dpad.setSpacing(4)
        self._jog_up    = JogBtn("▲","#4a9eff")
        self._jog_down  = JogBtn("▼","#4a9eff")
        self._jog_left  = JogBtn("◀","#4a9eff")
        self._jog_right = JogBtn("▶","#4a9eff")
        ctr = QPushButton(); ctr.setFixedSize(38,38)
        ctr.setStyleSheet(
            "QPushButton{background:#111318;border:1px solid #1e2433;border-radius:4px;}")
        dpad.addWidget(self._jog_up,   0,1)
        dpad.addWidget(self._jog_left, 1,0)
        dpad.addWidget(ctr,            1,1)
        dpad.addWidget(self._jog_right,1,2)
        dpad.addWidget(self._jog_down, 2,1)
        dv.addLayout(dpad)
        jog_row.addWidget(dpad_w)

        # Z axis
        z_w = QFrame()
        z_w.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        zv = QVBoxLayout(z_w); zv.setContentsMargins(10,8,10,8); zv.setSpacing(5)
        zv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zv.addWidget(lbl("Z","#4a5568",9,True))
        self._jog_zup   = JogBtn("▲","#cba6f7"); self._jog_zup.setFixedSize(40,36)
        self._jog_zdown = JogBtn("▼","#cba6f7"); self._jog_zdown.setFixedSize(40,36)
        zv.addWidget(self._jog_zup); zv.addSpacing(4); zv.addWidget(self._jog_zdown)
        jog_row.addWidget(z_w)

        # Controls
        ctrl_w = QFrame()
        ctrl_w.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        cv = QVBoxLayout(ctrl_w); cv.setContentsMargins(12,8,12,8); cv.setSpacing(7)

        # Mode
        mr = QHBoxLayout(); mr.setSpacing(6)
        mr.addWidget(lbl("Mode","#4a5568",10))
        self._mode_step = QPushButton("Step")
        self._mode_cont = QPushButton("Continuous")
        for b in [self._mode_step, self._mode_cont]:
            b.setFixedHeight(26); b.setStyleSheet(self._MODE_OFF)
        self._mode_step.setStyleSheet(self._MODE_ON)
        self._mode_step.clicked.connect(lambda: self._set_mode("Step"))
        self._mode_cont.clicked.connect(lambda: self._set_mode("Continuous"))
        mr.addWidget(self._mode_step); mr.addWidget(self._mode_cont); mr.addStretch()
        cv.addLayout(mr)

        # Step
        sr = QHBoxLayout(); sr.setSpacing(6)
        sr.addWidget(lbl("Step","#4a5568",10))
        self._step_edit = QLineEdit("0.0100"); self._step_edit.setFixedWidth(70)
        self._step_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:4px 6px;font-size:11px;font-family:monospace;")
        self._step_edit.textChanged.connect(
            lambda v: setattr(self,"_step",float(v) if v else 0.010))
        self._step_combo = QComboBox()
        for lb, _ in STEP_PRESETS: self._step_combo.addItem(lb)
        self._step_combo.setCurrentText("10µm")
        self._step_combo.setFixedHeight(26)
        self._step_combo.setStyleSheet(
            "QComboBox{background:#161b22;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:2px 6px;font-size:11px;}"
            "QComboBox::drop-down{border:none;}"
            "QComboBox QAbstractItemView{background:#0d0f14;border:1px solid #1e2433;"
            "color:#c5cdd9;font-size:11px;}")
        self._step_combo.currentTextChanged.connect(self._on_step_combo)
        sr.addWidget(self._step_edit)
        sr.addWidget(lbl("mm","#4a5568",9))
        sr.addWidget(self._step_combo); sr.addStretch()
        cv.addLayout(sr)

        # Velocity
        vr = QHBoxLayout(); vr.setSpacing(6)
        vr.addWidget(lbl("Velocity","#4a5568",10))
        self._vel_edit = QLineEdit("1.000"); self._vel_edit.setFixedWidth(70)
        self._vel_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:4px 6px;font-size:11px;font-family:monospace;")
        self._vel_edit.textChanged.connect(
            lambda v: setattr(self,"_vel",float(v) if v else 1.0))
        vr.addWidget(self._vel_edit)
        vr.addWidget(lbl("mm/s","#4a5568",9))
        for lb, val in VEL_PRESETS:
            b = QPushButton(lb); b.setFixedHeight(24)
            b.setStyleSheet(
                "QPushButton{background:#161b22;border:1px solid #1e2433;"
                "border-radius:3px;color:#8892a4;font-size:10px;padding:0 6px;}"
                "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;}")
            b.clicked.connect(lambda _, v=val: self._set_vel(v))
            vr.addWidget(b)
        vr.addStretch()
        cv.addLayout(vr)
        jog_row.addWidget(ctrl_w, 1)
        layout.addLayout(jog_row)

        # Connect buttons
        self._jog_up.clicked.connect(   lambda: self._jog("Y", 1))
        self._jog_down.clicked.connect( lambda: self._jog("Y",-1))
        self._jog_left.clicked.connect( lambda: self._jog("X",-1))
        self._jog_right.clicked.connect(lambda: self._jog("X", 1))
        self._jog_zup.clicked.connect(  lambda: self._jog("Z", 1))
        self._jog_zdown.clicked.connect(lambda: self._jog("Z",-1))

    # ── Go to ─────────────────────────────────
    def _build_goto(self, layout):
        self._sh(layout,"GO TO POSITION")
        card = QFrame()
        card.setStyleSheet(
            "QFrame{background:#0d0f14;border:1px solid #1e2433;border-radius:6px;}")
        v = QVBoxLayout(card); v.setContentsMargins(12,10,12,10); v.setSpacing(8)

        goto_row = QHBoxLayout(); goto_row.setSpacing(8)
        self._goto = {}
        for ax, color in [("X","#4a9eff"),("Y","#22c55e"),("Z","#cba6f7")]:
            goto_row.addWidget(lbl(ax, color, 12, True))
            e = QLineEdit("0.000"); e.setFixedWidth(88)
            e.setStyleSheet(
                f"border-left:2px solid {color};background:#161b22;"
                "border-top:1px solid #1e2433;border-right:1px solid #1e2433;"
                "border-bottom:1px solid #1e2433;border-radius:4px;"
                "color:#c5cdd9;padding:5px 8px;font-size:12px;font-family:monospace;")
            self._goto[ax] = e; goto_row.addWidget(e)
        goto_row.addWidget(lbl("mm","#4a5568",9))
        go_btn = QPushButton("Go XYZ"); go_btn.setFixedHeight(32)
        go_btn.setStyleSheet(
            "QPushButton{background:#1a3a1a;border:1px solid #22c55e;"
            "border-radius:5px;color:#22c55e;font-size:12px;font-weight:600;padding:0 16px;}"
            "QPushButton:hover{background:#22c55e;color:#000;}")
        go_btn.clicked.connect(self._goto_xyz)
        goto_row.addWidget(go_btn)
        v.addLayout(goto_row)

        v.addWidget(divider())

        # Quick commands
        cmd_row = QHBoxLayout(); cmd_row.setSpacing(6)
        for label, fn, color in [
            ("POS?",  self._pos_cmd, "#4a9eff"),
            ("Home",  self._home,    "#4a9eff"),
            ("FRF",   self._frf,     "#4a9eff"),
            ("ONT?",  self._ont,     "#4a9eff"),
            ("ERR?",  self._err,     "#4a9eff"),
        ]:
            b = QPushButton(label); b.setFixedHeight(28)
            b.setStyleSheet(
                f"QPushButton{{background:#161b22;border:1px solid #1e2433;"
                f"border-radius:4px;color:#4a5568;font-size:11px;padding:0 10px;}}"
                f"QPushButton:hover{{border-color:{color};color:{color};}}")
            b.clicked.connect(fn); cmd_row.addWidget(b)
        halt_btn = QPushButton("HALT"); halt_btn.setFixedHeight(28)
        halt_btn.setStyleSheet(
            "QPushButton{background:#1a0000;border:1px solid #3d0a0a;"
            "border-radius:4px;color:#4a5568;font-size:11px;font-weight:600;padding:0 12px;}"
            "QPushButton:hover{border-color:#ef4444;color:#ef4444;background:#3d0a0a;}")
        halt_btn.clicked.connect(self._halt)
        cmd_row.addWidget(halt_btn); cmd_row.addStretch()
        v.addLayout(cmd_row)
        layout.addWidget(card)

    # ── Console ───────────────────────────────
    def _build_console(self, layout):
        self._sh(layout,"COMMAND CONSOLE")
        row = QHBoxLayout(); row.setSpacing(6)
        self._cmd_edit = QLineEdit()
        self._cmd_edit.setPlaceholderText("Type GCS command...")
        self._cmd_edit.setStyleSheet(
            "background:#0a0c10;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:6px 10px;font-size:12px;font-family:Consolas,monospace;")
        self._cmd_edit.textChanged.connect(self._update_ac)
        self._cmd_edit.returnPressed.connect(self._send_cmd)
        send_btn = QPushButton("Send"); send_btn.setFixedHeight(32)
        send_btn.setStyleSheet(
            "QPushButton{background:#0d1520;border:1px solid #4a9eff;"
            "border-radius:4px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}")
        send_btn.clicked.connect(self._send_cmd)
        row.addWidget(self._cmd_edit,1); row.addWidget(send_btn)
        layout.addLayout(row)
        self._ac = QListWidget()
        self._ac.setFixedHeight(64)
        self._ac.setStyleSheet(
            "QListWidget{background:#0a0c10;border:1px solid #1e2433;border-radius:4px;"
            "color:#8892a4;font-size:11px;font-family:Consolas,monospace;}"
            "QListWidget::item:hover{background:#1e2433;color:#4a9eff;}"
            "QListWidget::item:selected{background:#0d1520;color:#4a9eff;}")
        self._ac.itemClicked.connect(lambda i: self._cmd_edit.setText(i.text()))
        self._ac.setVisible(False)
        layout.addWidget(self._ac)

    # ── Log ───────────────────────────────────
    def _build_log(self, layout):
        self._sh(layout,"RESPONSE LOG")
        self._log = QTextEdit()
        self._log.setReadOnly(True); self._log.setFixedHeight(80)
        self._log.setStyleSheet(
            "QTextEdit{background:#0a0c10;border:1px solid #1e2433;border-radius:5px;"
            "color:#4a5568;font-size:11px;font-family:Consolas,monospace;}")
        layout.addWidget(self._log)

    # ── Connect ───────────────────────────────
    def _connect(self):
        ip   = self.ip_edit.text().strip()
        port = int(self.port_edit.text() or 50000)
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

    def _on_ok(self, idn, drv):
        self._drv = drv
        self.status_lbl.setText("●  Connected")
        self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.idn_lbl.setText(f"IDN: {idn}")
        self.idn_lbl.setStyleSheet("color:#8892a4;font-size:11px;")
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

    # ── Position ──────────────────────────────
    def _refresh_pos(self):
        if not self._drv: return
        try:
            pos = self._drv.pos()
            for ax, val in pos.items():
                if ax in self._pos_cards:
                    self._pos_cards[ax].set_value(val)
        except: pass

    # ── Jog ───────────────────────────────────
    def _on_step_combo(self, label):
        for lb, val in STEP_PRESETS:
            if lb == label:
                self._step = val
                self._step_edit.setText(f"{val:.4f}"); break

    def _set_vel(self, val):
        self._vel = val
        self._vel_edit.setText(f"{val:.3f}")

    def _set_mode(self, mode):
        self._mode_step.setStyleSheet(
            self._MODE_ON  if mode=="Step"       else self._MODE_OFF)
        self._mode_cont.setStyleSheet(
            self._MODE_ON  if mode=="Continuous" else self._MODE_OFF)

    def _jog(self, axis, direction):
        if not self._drv:
            self._log_msg("Not connected","#ef4444"); return
        delta = direction * self._step
        self._log_msg(f"JOG {axis} {'+' if delta>0 else ''}{delta:.4f} mm")
        fn = lambda: self._drv.mov_relative(axis, delta)
        worker = MoveWorker(self._drv, fn, self._vel)
        worker.finished.connect(self._refresh_pos)
        worker.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        worker.start(); self._jog_worker = worker

    # ── Go to XYZ ─────────────────────────────
    def _goto_xyz(self):
        if not self._drv:
            self._log_msg("Not connected","#ef4444"); return
        try:
            x = float(self._goto["X"].text())
            y = float(self._goto["Y"].text())
            z = float(self._goto["Z"].text())
        except:
            self._log_msg("Invalid position","#ef4444"); return
        self._log_msg(f"MOV X={x:.3f} Y={y:.3f} Z={z:.3f}")
        fn = lambda: self._drv.mov_xyz(x, y, z)
        worker = MoveWorker(self._drv, fn, self._vel)
        worker.finished.connect(self._refresh_pos)
        worker.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        worker.start(); self._goto_worker = worker

    # ── Quick commands ────────────────────────
    def _pos_cmd(self):
        if not self._drv: return
        try:
            pos = self._drv.pos()
            msg = "  ".join([f"{k}={v:.4f}" for k,v in pos.items()])
            self._log_msg(f"POS? → {msg}")
            self._refresh_pos()
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _home(self):
        if not self._drv: return
        self._log_msg("Home → X=0 Y=0 Z=0")
        worker = MoveWorker(self._drv, self._drv.home, self._vel)
        worker.finished.connect(self._refresh_pos)
        worker.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        worker.start(); self._home_worker = worker

    def _frf(self):
        if not self._drv: return
        try: self._drv.frf(); self._log_msg("FRF — Referencing...")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _ont(self):
        if not self._drv: return
        try: self._log_msg(f"ONT? → {self._drv.ont()}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _err(self):
        if not self._drv: return
        try: self._log_msg(f"ERR? → {self._drv.err()}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _halt(self):
        if not self._drv: return
        try: self._drv.halt(); self._log_msg("HALT","#ef4444")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    # ── Console ───────────────────────────────
    def _update_ac(self, text):
        if not text: self._ac.setVisible(False); return
        matches = [c for c in self._cmds if text.upper() in c.upper()][:6]
        self._ac.clear()
        for m in matches: self._ac.addItem(m)
        self._ac.setVisible(bool(matches))

    def _send_cmd(self):
        cmd = self._cmd_edit.text().strip()
        if not cmd: return
        if not self._drv:
            self._log_msg("Not connected","#ef4444"); return
        try:
            if cmd.strip().endswith("?") or cmd.strip().startswith("*"):
                resp = self._drv.query_raw(cmd)
                self._log_msg(f"{cmd} → {resp}")
            else:
                self._drv.send_raw(cmd)
                self._log_msg(cmd)
            self._refresh_pos()
        except Exception as e: self._log_msg(str(e),"#ef4444")
        self._cmd_edit.clear(); self._ac.setVisible(False)

    # ── Save / Load ───────────────────────────
    def get_settings(self):
        return {
            "ip":       self.ip_edit.text().strip(),
            "port":     int(self.port_edit.text() or 50000),
            "step":     self._step,
            "velocity": self._vel,
        }

    def load_settings(self, data):
        self.ip_edit.setText(data.get("ip",""))
        self.port_edit.setText(str(data.get("port",50000)))
        self._step = data.get("step",0.010)
        self._step_edit.setText(f"{self._step:.4f}")
        self._vel  = data.get("velocity",1.0)
        self._vel_edit.setText(f"{self._vel:.3f}")

    def set_cart_driver(self, drv):
        self._drv = drv