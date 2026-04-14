"""
PI Linear Stage Panel — L-812 (Single Axis)
=============================================
- Connect via raw TCP socket (เหมือน Hercules)
- Position readback
- Jog: Step / Continuous + presets
- Go to position
- Command console + autocomplete
- Response log
"""

import os, json, datetime, time, socket
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame,
    QScrollArea, QTextEdit, QListWidget, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

CMD_FILE = "config/gcs_commands.json"

STEP_PRESETS = [
    ("0.1µm", 0.0001), ("1µm",  0.001), ("5µm",  0.005),
    ("10µm",  0.010),  ("50µm", 0.050), ("100µm",0.100),
    ("500µm", 0.500),  ("1mm",  1.000), ("5mm",  5.000),
]
VEL_PRESETS = [
    ("Slow", 0.1), ("Med", 1.0), ("Fast", 5.0), ("Max", 10.0),
]


def load_commands():
    if os.path.exists(CMD_FILE):
        with open(CMD_FILE) as f:
            return json.load(f).get("commands", [])
    return ["POS?","FRF","ONT?","ERR?","*IDN?","HLT","TMN?","TMX?","MVR"]


# ══════════════════════════════════════════════
# Driver — raw TCP socket
# ══════════════════════════════════════════════

class StageDriver:
    BUFFER  = 4096
    TIMEOUT = 5.0

    def __init__(self, ip, port=50000):
        self.ip    = ip
        self.port  = port
        self._sock = None
        self._axis = "1"  # cache axis name

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.TIMEOUT)
        self._sock.connect((self.ip, self.port))
        time.sleep(0.2)
        # flush greeting
        self._sock.settimeout(0.3)
        try: self._sock.recv(self.BUFFER)
        except: pass
        self._sock.settimeout(self.TIMEOUT)
        # ACS SPiiPlus ใช้ axis index number (0, 1, 2...)
        self._axis = "0"

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    def send_raw(self, cmd):
        """ส่ง command + CR (ACS SPiiPlus)"""
        self._sock.sendall((cmd.strip() + "\r").encode())
        time.sleep(0.02)

    def query_raw(self, cmd):
        """ส่ง query + CR แล้วรับ response"""
        self._sock.sendall((cmd.strip() + "\r").encode())
        time.sleep(0.05)
        self._sock.settimeout(0.5)
        data = b""
        try: data = self._sock.recv(self.BUFFER)
        except: pass
        self._sock.settimeout(self.TIMEOUT)
        return data.decode().strip()

    def idn(self):
        return self.query_raw("?VR")

    def pos(self):
        resp = self.query_raw("?FPOS0")
        # response format: "?FPOS0    186.01 ::"
        parts = resp.replace("::", "").split()
        for p in parts:
            try: return float(p)
            except: pass
        return 0.0

    def ont(self):  return self.query_raw("ONT?")
    def err(self):  return self.query_raw("ERR?")

    def tmn(self):
        resp = self.query_raw(f"?SLLIMIT({self._axis})")
        parts = resp.replace("::", "").split()
        for p in parts:
            try: return float(p)
            except: pass
        return 0.0

    def tmx(self):
        resp = self.query_raw(f"?SRLIMIT({self._axis})")
        parts = resp.replace("::", "").split()
        for p in parts:
            try: return float(p)
            except: pass
        return 0.0

    def mov(self, pos):
        """PTP absolute move"""
        self.send_raw(f"PTP {self._axis}, {pos}")

    def mov_relative(self, delta):
        """PTP relative move — query pos ก่อนแล้วบวก delta"""
        cur = self.pos()
        self.send_raw(f"PTP {self._axis}, {cur + delta}")

    def vel(self, v):
        """Set velocity VEL(axis) = v"""
        self.send_raw(f"VEL({self._axis}) = {v}")

    def halt(self):
        self.send_raw("HALT 0")

    def frf(self):
        """Reference — ACS ใช้ HOM หรือ SET"""
        self.send_raw(f"HOME {self._axis}")

    def wait_target(self, timeout=15):
        """Poll MST ดู bit MOVE ครับ"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self.query_raw(f"?MST({self._axis})")
            parts = resp.replace("::", "").split()
            for p in parts:
                try:
                    mst = int(p)
                    # bit 0 = MOVE, ถ้า 0 = หยุดแล้ว
                    if not (mst & 1):
                        return
                except: pass
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
            d = StageDriver(self.ip, self.port)
            d.connect()
            idn = d.idn()
            self.success.emit(idn, d)
        except Exception as e:
            self.failed.emit(str(e))


class MoveWorker(QThread):
    finished = pyqtSignal()
    error    = pyqtSignal(str)
    def __init__(self, drv, delta=None, absolute=None, vel=1.0):
        super().__init__()
        self._drv = drv; self._delta = delta
        self._abs = absolute; self._vel = vel
    def run(self):
        try:
            self._drv.vel(self._vel)
            if self._abs is not None:
                self._drv.mov(self._abs)
            else:
                self._drv.mov_relative(self._delta)
            # fire and forget — ไม่ wait_target
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


# ══════════════════════════════════════════════
# Main Panel
# ══════════════════════════════════════════════

class LinearStagePanel(QWidget):
    def __init__(self):
        super().__init__()
        self._drv    = None
        self._step   = 0.010
        self._vel    = 1.0
        self._cmds   = load_commands()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#111318;border:none;")

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16,14,16,14)
        layout.setSpacing(10)

        self._build_connection(layout)
        self._build_position(layout)
        self._build_jog(layout)
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

    def _vline(self):
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
        for attr, label, default in [
            ("ip_edit",   "IP Address", "192.168.1.10"),
            ("port_edit", "Port",       "50000"),
        ]:
            f = QFrame(); fv = QVBoxLayout(f)
            fv.setContentsMargins(0,0,0,0); fv.setSpacing(3)
            fv.addWidget(lbl(label,"#4a5568",10))
            e = QLineEdit(default)
            e.setStyleSheet(
                "border-left:2px solid #4a9eff;background:#161b22;"
                "border-top:1px solid #1e2433;border-right:1px solid #1e2433;"
                "border-bottom:1px solid #1e2433;border-radius:4px;"
                "color:#c5cdd9;padding:5px 8px;font-size:12px;")
            setattr(self, attr, e); fv.addWidget(e)
            row.addWidget(f, 2 if attr=="ip_edit" else 1)
        v.addLayout(row)

        conn_row = QHBoxLayout(); conn_row.setSpacing(10)
        self.conn_btn = QPushButton("⟳  Connect")
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(
            "QPushButton{background:#0d1520;border:1px solid #4a9eff;"
            "border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}")
        self.conn_btn.clicked.connect(self._connect)
        self.status_lbl = lbl("○  Disconnected","#4a5568",12)
        self.idn_lbl    = lbl("IDN: —","#2a3444",11)
        conn_row.addWidget(self.conn_btn)
        conn_row.addWidget(self.status_lbl)
        conn_row.addStretch()
        conn_row.addWidget(self.idn_lbl)
        v.addLayout(conn_row)
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

        pos_card = QFrame()
        pos_card.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        ph = QHBoxLayout(pos_card)
        ph.setContentsMargins(16,10,16,10); ph.setSpacing(16)

        left = QVBoxLayout(); left.setSpacing(2)
        left.addWidget(lbl("CURRENT POSITION","#4a5568",9,True))
        val_row = QHBoxLayout(); val_row.setSpacing(8)
        self._pos_val = QLabel("0.0000")
        self._pos_val.setFont(QFont("Consolas",28,700))
        self._pos_val.setStyleSheet("color:#4a9eff;background:transparent;")
        val_row.addWidget(self._pos_val)
        val_row.addWidget(lbl("mm","#2a3444",13))
        val_row.addStretch()
        left.addLayout(val_row)
        ph.addLayout(left,1)

        right = QVBoxLayout()
        right.setSpacing(4)
        right.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(lbl("Travel limits","#4a5568",9))
        self._lim_lbl = lbl("MIN: —   MAX: —","#8892a4",11)
        self._lim_lbl.setFont(QFont("Consolas",11))
        right.addWidget(self._lim_lbl)
        ph.addLayout(right)
        layout.addWidget(pos_card)

    # ── Jog ───────────────────────────────────
    def _build_jog(self, layout):
        self._sh(layout,"JOG CONTROL")
        jog_card = QFrame()
        jog_card.setStyleSheet(
            "QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        jv = QVBoxLayout(jog_card)
        jv.setContentsMargins(12,10,12,10); jv.setSpacing(8)

        top = QHBoxLayout(); top.setSpacing(10)

        def jbtn(text, big=False):
            b = QPushButton(text)
            b.setFixedSize(52 if big else 44, 44)
            b.setStyleSheet(
                "QPushButton{background:#161b22;border:1px solid #1e2433;"
                "border-radius:5px;color:#8892a4;font-size:15px;}"
                "QPushButton:hover{border-color:#4a9eff;color:#4a9eff;background:#0d1520;}"
                "QPushButton:pressed{background:#4a9eff22;}")
            return b

        self._btn_ll = jbtn("◀◀", True)
        self._btn_l  = jbtn("◀")
        self._btn_r  = jbtn("▶")
        self._btn_rr = jbtn("▶▶", True)
        self._btn_ll.clicked.connect(lambda: self._jog(-10))
        self._btn_l.clicked.connect( lambda: self._jog(-1))
        self._btn_r.clicked.connect( lambda: self._jog( 1))
        self._btn_rr.clicked.connect(lambda: self._jog(10))

        top.addWidget(self._btn_ll); top.addWidget(self._btn_l)

        mid = QVBoxLayout(); mid.setSpacing(6)

        # Step
        sr = QHBoxLayout(); sr.setSpacing(6)
        sr.addWidget(lbl("Step","#4a5568",10))
        self._step_edit = QLineEdit("0.0100"); self._step_edit.setFixedWidth(72)
        self._step_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:4px 6px;font-size:11px;font-family:monospace;")
        self._step_edit.textChanged.connect(
            lambda v: setattr(self,"_step",float(v) if v else 0.010))
        sr.addWidget(self._step_edit)
        sr.addWidget(lbl("mm","#4a5568",9))
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
        sr.addWidget(self._step_combo); sr.addStretch()
        mid.addLayout(sr)

        # Velocity
        vr = QHBoxLayout(); vr.setSpacing(6)
        vr.addWidget(lbl("Velocity","#4a5568",10))
        self._vel_edit = QLineEdit("1.000"); self._vel_edit.setFixedWidth(72)
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
        mid.addLayout(vr)

        top.addLayout(mid, 1)
        top.addWidget(self._btn_r); top.addWidget(self._btn_rr)
        jv.addLayout(top)
        jv.addWidget(divider())

        # Go to + quick commands
        bot = QHBoxLayout(); bot.setSpacing(8)
        bot.addWidget(lbl("Go to","#4a5568",10))
        self._goto_edit = QLineEdit("0.000"); self._goto_edit.setFixedWidth(90)
        self._goto_edit.setStyleSheet(
            "background:#161b22;border:1px solid #1e2433;border-radius:4px;"
            "color:#c5cdd9;padding:5px 8px;font-size:12px;font-family:monospace;")
        bot.addWidget(self._goto_edit)
        bot.addWidget(lbl("mm","#4a5568",9))
        go_btn = QPushButton("Go"); go_btn.setFixedHeight(30)
        go_btn.setStyleSheet(
            "QPushButton{background:#1a3a1a;border:1px solid #22c55e;"
            "border-radius:4px;color:#22c55e;font-size:12px;font-weight:600;padding:0 14px;}"
            "QPushButton:hover{background:#22c55e;color:#000;}")
        go_btn.clicked.connect(self._goto)
        bot.addWidget(go_btn)
        bot.addWidget(self._vline())

        for label, fn, color in [
            ("POS?",      self._pos_cmd, "#4a9eff"),
            ("Reference", self._frf,     "#4a9eff"),
            ("ONT?",      self._ont,     "#4a9eff"),
            ("ERR?",      self._err,     "#4a9eff"),
            ("HALT",      self._halt,    "#ef4444"),
        ]:
            b = QPushButton(label); b.setFixedHeight(30)
            is_halt = label == "HALT"
            b.setStyleSheet(
                f"QPushButton{{background:{'#1a0000' if is_halt else '#161b22'};"
                f"border:1px solid {'#3d0a0a' if is_halt else '#1e2433'};"
                f"border-radius:4px;color:#4a5568;font-size:11px;padding:0 10px;}}"
                f"QPushButton:hover{{border-color:{color};color:{color};}}")
            b.clicked.connect(fn); bot.addWidget(b)
        bot.addStretch()
        jv.addLayout(bot)
        layout.addWidget(jog_card)

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

        self._ac = QListWidget(); self._ac.setFixedHeight(64)
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
        self._log = QTextEdit(); self._log.setReadOnly(True)
        self._log.setFixedHeight(80)
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
        try:
            mn = drv.tmn(); mx = drv.tmx()
            self._lim_lbl.setText(f"MIN: {mn:.3f}   MAX: {mx:.3f} mm")
        except: pass
        self.status_lbl.setText("●  Connected")
        self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.idn_lbl.setText(f"IDN: {idn}")
        self.idn_lbl.setStyleSheet("color:#8892a4;font-size:11px;")
        self.conn_btn.setText("✗  Disconnect")
        self.conn_btn.setEnabled(True)
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
            self._pos_val.setText(f"{pos:.4f}")
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

    def _jog(self, multiplier):
        if not self._drv:
            self._log_msg("Not connected","#ef4444"); return
        delta = multiplier * self._step
        self._log_msg(f"MVR {'+' if delta>0 else ''}{delta:.4f} mm")
        worker = MoveWorker(self._drv, delta=delta, vel=self._vel)
        worker.finished.connect(self._refresh_pos)
        worker.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        worker.start()
        self._move_worker = worker

    def _goto(self):
        if not self._drv:
            self._log_msg("Not connected","#ef4444"); return
        try:
            pos = float(self._goto_edit.text())
        except:
            self._log_msg("Invalid position","#ef4444"); return
        self._log_msg(f"MOV → {pos:.4f} mm")
        worker = MoveWorker(self._drv, absolute=pos, vel=self._vel)
        worker.finished.connect(self._refresh_pos)
        worker.error.connect(lambda e: self._log_msg(e,"#ef4444"))
        worker.start()
        self._move_worker = worker

    # ── Quick commands ────────────────────────
    def _pos_cmd(self):
        if not self._drv: return
        try:
            pos = self._drv.pos()
            self._log_msg(f"POS? → {pos:.4f} mm")
            self._pos_val.setText(f"{pos:.4f}")
        except Exception as e: self._log_msg(str(e),"#ef4444")

    def _frf(self):
        if not self._drv: return
        try:
            self._drv.frf()
            self._log_msg("FRF — Referencing... (PI will move!)")
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
        if not self._drv: self._log_msg("Not connected","#ef4444"); return
        try:
            if cmd.strip().endswith("?") or cmd.strip().startswith("*") or cmd.strip().startswith("?"):
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

    def set_driver(self, drv):
        self._drv = drv