"""
Process Page
=============
- Load recipe from Recipe page
- Step navigator (left) — click to jump, skip, re-run
- Step detail + params (right)
- Run / Pause / Stop / Skip / Next / Back
- Realtime log
- Step states: Wait / Running / Done / Failed / Skipped
"""

import os, datetime, time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QScrollArea,
    QTextEdit, QSizePolicy, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl

# ── Step states ───────────────────────────────
WAIT    = "wait"
RUNNING = "running"
DONE    = "done"
FAILED  = "failed"
SKIPPED = "skipped"

STATE_COLOR = {
    WAIT:    "#64748b",
    RUNNING: "#4a9eff",
    DONE:    "#22c55e",
    FAILED:  "#ef4444",
    SKIPPED: "#3a4055",
}
STATE_ICON = {
    WAIT:    "○",
    RUNNING: "▶",
    DONE:    "✓",
    FAILED:  "✗",
    SKIPPED: "⊘",
}
STEP_ICONS = {
    "Coarse Scan":    "🔬",
    "Fine Align":     "🎯",
    "Tilt Correction":"↕",
    "Dispense":       "💧",
    "UV Cure":        "☀",
    "Verify":         "✅",
    "Move":           "🤖",
    "Wait":           "⏱",
    "Set TEC":        "🌡",
}


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def _btn(text, color="#4a9eff", h=30, w=None, enabled=True):
    b = QPushButton(text)
    if h: b.setFixedHeight(h)
    if w: b.setFixedWidth(w)
    bg = {"#4a9eff":"#1e2d47","#22c55e":"#1a3a1a",
          "#ef4444":"#2a0000","#eab308":"#1a1000",
          "#64748b":"#252a38","#a855f7":"#1a0d2e"}.get(color,"#252a38")
    b.setStyleSheet(
        f"QPushButton{{background:{bg};border:1px solid {color};"
        f"border-radius:4px;color:{color};font-size:11px;font-weight:600;padding:0 10px;}}"
        f"QPushButton:hover{{background:{color};color:#000;}}"
        f"QPushButton:disabled{{border-color:#3a4055;color:#3a4055;background:#20242e;}}")
    b.setEnabled(enabled)
    return b

def _hline():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("background:#3a4055;max-height:1px;"); return f


# ══════════════════════════════════════════════
# Step Runner (QThread)
# ══════════════════════════════════════════════

class StepRunner(QThread):
    log      = pyqtSignal(str, str)   # message, level
    done     = pyqtSignal(bool)       # success
    progress = pyqtSignal(int)        # 0-100

    def __init__(self, step, devices):
        super().__init__()
        self._step    = step
        self._devices = devices
        self._abort   = False

    def abort(self): self._abort = True

    def run(self):
        step_type = self._step.get("type","")
        params    = self._step.get("params",{})
        self.log.emit(f"Starting: {step_type}", "info")
        try:
            if step_type == "Call Recipe":
                self._run_call_recipe(params)
            else:
                fn = getattr(self,
                    f"_run_{step_type.lower().replace(' ','_').replace('/','_')}",
                    self._run_generic)
                fn(params)
            if not self._abort:
                self.log.emit(f"{step_type} — Done", "ok")
                self.done.emit(True)
            else:
                self.done.emit(False)
        except Exception as e:
            self.log.emit(f"{step_type} — Error: {e}", "error")
            self.done.emit(False)

    def _run_call_recipe(self, params):
        """
        Call Recipe — load recipe อื่นมารันแบบ inline
        ป้องกัน circular call ด้วย _call_stack
        """
        import json, os
        recipe_name = params.get("recipe_name","")
        on_fail     = params.get("on_fail","Stop")

        if not recipe_name:
            self.log.emit("Call Recipe: no recipe_name specified","error")
            return

        # ป้องกัน circular call
        call_stack = self._devices.get("_call_stack",[])
        if recipe_name in call_stack:
            self.log.emit(
                f"Call Recipe: circular call detected! "
                f"{' → '.join(call_stack)} → {recipe_name}","error")
            return

        # Load recipe จาก recipes.json
        recipe_file = "recipes.json"
        if not os.path.exists(recipe_file):
            self.log.emit(f"Call Recipe: recipes.json not found","error")
            return

        with open(recipe_file) as f:
            all_recipes = json.load(f)

        target = next(
            (r for r in all_recipes if r.get("name","") == recipe_name), None)
        if not target:
            self.log.emit(
                f"Call Recipe: '{recipe_name}' not found","error")
            return

        steps = [s for s in target.get("steps",[]) if s.get("enabled",True)]
        self.log.emit(
            f"Call Recipe: '{recipe_name}' ({len(steps)} steps)","info")

        # Push call stack
        self._devices["_call_stack"] = call_stack + [recipe_name]

        # รัน steps ของ recipe ที่เรียก
        for i, step in enumerate(steps):
            if self._abort: break
            stype = step.get("type","")
            sparams = step.get("params",{})
            self.log.emit(f"  [{i+1}/{len(steps)}] {stype}","info")
            self.progress.emit(int((i)/len(steps)*100))

            if stype == "Call Recipe":
                # recursive call
                self._run_call_recipe(sparams)
            else:
                fn = getattr(self,
                    f"_run_{stype.lower().replace(' ','_').replace('/','_')}",
                    self._run_generic)
                fn(sparams)

            if self._abort: break

        # Pop call stack
        self._devices["_call_stack"] = call_stack
        self.progress.emit(100)

    def _sim(self, steps=10, delay=0.1):
        for i in range(steps):
            if self._abort: return
            time.sleep(delay)
            self.progress.emit(int((i+1)/steps*100))

    def _run_generic(self, params):
        self._sim()
        self.log.emit("(Simulated — no hardware connected)", "warn")

    def _run_coarse_scan(self, params):
        self.log.emit(
            f"Coarse scan X±{params.get('range_x','0.5')} "
            f"Y±{params.get('range_y','0.5')} mm "
            f"step {params.get('step','0.05')} mm", "info")
        self._sim()

    def _run_fine_align(self, params):
        self.log.emit(
            f"Fine align step {params.get('step','0.001')} mm "
            f"tol {params.get('tolerance','0.01')} µA", "info")
        self._sim()

    def _run_tilt_correction(self, params):
        self.log.emit(
            f"Tilt correction axis {params.get('axis','U and V')} "
            f"step {params.get('step_deg','0.01')}°", "info")
        self._sim()

    def _run_dispense(self, params):
        self.log.emit(
            f"Dispense {params.get('program','P1')} "
            f"{params.get('pressure','50')}kPa "
            f"{params.get('time_ms','100')}ms", "info")
        self._sim(5, 0.1)

    def _run_uv_cure(self, params):
        t = float(params.get("time_s","5.0"))
        self.log.emit(
            f"UV Cure {t}s @ {params.get('intensity','100')}%", "info")
        steps = max(1, int(t * 4))
        self._sim(steps, t/steps)

    def _run_verify(self, params):
        self.log.emit(
            f"Verify min signal {params.get('min_signal','0.5')} µA", "info")
        self._sim()

    def _run_move(self, params):
        self.log.emit(
            f"Move {params.get('device','Cartesian')} "
            f"X:{params.get('x','0')} Y:{params.get('y','0')} Z:{params.get('z','0')} mm", "info")
        self._sim(5, 0.1)

    def _run_wait(self, params):
        t = float(params.get("time_s","1.0"))
        msg = params.get("message","")
        self.log.emit(f"Wait {t}s{f' — {msg}' if msg else ''}", "info")
        steps = max(1, int(t * 10))
        self._sim(steps, t/steps)

    def _run_set_tec(self, params):
        self.log.emit(
            f"Set TEC {params.get('setpoint','25')}°C "
            f"wait {params.get('wait_stable','10')}s", "info")
        self._sim(10, 0.2)

    def _run_wago_io(self, params):
        wago    = self._devices.get("wago")
        channel = params.get("channel","").strip()
        action  = params.get("action","ON").upper()
        pulse_ms = int(params.get("pulse_ms", 500))
        verify  = params.get("verify","Yes") == "Yes"

        if not channel:
            self.log.emit("WAGO IO: no channel specified","error")
            return

        self.log.emit(
            f"WAGO IO: {channel} → {action}"
            f"{f' {pulse_ms}ms' if action=='PULSE' else ''}", "info")

        if wago:
            try:
                if action == "ON":
                    wago.write_do_by_name(channel, True)
                elif action == "OFF":
                    wago.write_do_by_name(channel, False)
                elif action == "PULSE":
                    wago.write_do_by_name(channel, True)
                    self._sim(1, pulse_ms/1000.0)
                    wago.write_do_by_name(channel, False)

                if verify:
                    import time; time.sleep(0.05)
                    actual = wago.read_do_by_name(channel)
                    expected = True if action == "ON" else False if action == "OFF" else False
                    if action != "PULSE" and actual != expected:
                        self.log.emit(
                            f"WAGO IO verify failed: {channel} "
                            f"expected {expected} got {actual}","error")
                        return
                    self.log.emit(f"WAGO IO verify OK: {channel}","ok")

            except Exception as e:
                self.log.emit(f"WAGO IO error: {e}","error")
                return
        else:
            self.log.emit(
                f"WAGO IO (sim): {channel} → {action}","warn")
            if action == "PULSE":
                self._sim(1, pulse_ms/1000.0)

        self.progress.emit(100)


# ══════════════════════════════════════════════
# Step Nav Item  — layout สร้างครั้งเดียวใน __init__
# ══════════════════════════════════════════════

class StepNavItem(QPushButton):
    def __init__(self, idx, step):
        super().__init__()
        self._idx   = idx
        self._step  = step
        self._state = WAIT
        self.setCheckable(True)
        self.setFixedHeight(54)
        self.setText("")  # ไม่ใช้ default text

        # Layout สร้างครั้งเดียว
        v = QVBoxLayout(self)
        v.setContentsMargins(10,5,8,5); v.setSpacing(2)

        # Top row: num + icon + name + state
        top = QHBoxLayout(); top.setSpacing(6)

        self._num_lbl = QLabel()
        self._num_lbl.setFont(QFont("Consolas",9))
        self._num_lbl.setFixedWidth(22)
        self._num_lbl.setStyleSheet("background:transparent;")

        self._ic_lbl = QLabel()
        self._ic_lbl.setFixedWidth(20)
        self._ic_lbl.setStyleSheet("background:transparent;font-size:13px;")

        self._nm_lbl = QLabel()
        self._nm_lbl.setFont(QFont("Segoe UI",11,600))
        self._nm_lbl.setStyleSheet("background:transparent;")

        self._st_lbl = QLabel()
        self._st_lbl.setStyleSheet(
            "font-size:9px;font-weight:700;background:transparent;")

        top.addWidget(self._num_lbl)
        top.addWidget(self._ic_lbl)
        top.addWidget(self._nm_lbl, 1)
        top.addWidget(self._st_lbl)
        v.addLayout(top)

        # Params summary row
        self._ps_lbl = QLabel()
        self._ps_lbl.setStyleSheet(
            "color:#3a4055;font-size:9px;background:transparent;padding-left:42px;")
        v.addWidget(self._ps_lbl)

        self._update_style()

    def set_state(self, state):
        self._state = state
        self._update_style()

    def _update_style(self):
        s       = self._state
        color   = STATE_COLOR[s]
        icon    = STATE_ICON[s]
        name    = self._step.get("type","Step")
        enabled = self._step.get("enabled", True)
        params  = self._step.get("params", {})

        # Update label text & color
        self._num_lbl.setText(f"{self._idx+1:02d}")
        self._num_lbl.setStyleSheet(
            f"color:#64748b;background:transparent;")

        self._ic_lbl.setText(STEP_ICONS.get(name,"▸"))

        self._nm_lbl.setText(name)
        self._nm_lbl.setStyleSheet(
            f"color:{'#e2e8f0' if enabled else '#64748b'};"
            f"background:transparent;")

        self._st_lbl.setText(f"{icon}  {s.capitalize()}")
        self._st_lbl.setStyleSheet(
            f"color:{color};font-size:9px;font-weight:700;background:transparent;")

        # Params summary (first 2 params)
        parts = [f"{k}: {v}" for k,v in list(params.items())[:2]]
        self._ps_lbl.setText("  ·  ".join(parts))

        # Button stylesheet
        checked_bg = {
            WAIT:    "#1e2d47",
            RUNNING: "#1e2d47",
            DONE:    "#0d1a0d",
            FAILED:  "#2a0000",
            SKIPPED: "#252a38",
        }.get(s, "#252a38")

        opacity = "opacity: 0.5;" if not enabled else ""
        self.setStyleSheet(f"""
            QPushButton {{
                background: #20242e;
                border: none;
                border-bottom: 1px solid #3a4055;
                border-left: 3px solid transparent;
                text-align: left;
                padding: 0px;
                {opacity}
            }}
            QPushButton:checked {{
                background: {checked_bg};
                border-left: 3px solid {color};
            }}
            QPushButton:hover {{
                background: #2a2f3d;
            }}
        """)


# ══════════════════════════════════════════════
# Process Page
# ══════════════════════════════════════════════

class ProcessPage(QWidget):
    def __init__(self):
        super().__init__()
        self._recipe      = None
        self._steps       = []
        self._states      = []
        self._current     = -1
        self._runner      = None
        self._running     = False
        self._run_all_mode = False
        self._nav_items   = []

        root = QHBoxLayout(self)
        root.setContentsMargins(12,12,12,12); root.setSpacing(10)
        self._build_left(root)
        self._build_right(root)

    # ══════════════════════════════════════════
    # Left — Step navigator
    # ══════════════════════════════════════════

    def _build_left(self, layout):
        left = QFrame()
        left.setFixedWidth(260)
        left.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        v = QVBoxLayout(left); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame{background:#16191f;border:none;"
            "border-bottom:1px solid #3a4055;border-radius:6px 6px 0 0;}")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(12,8,12,8)
        self._recipe_lbl = QLabel("No recipe loaded")
        self._recipe_lbl.setFont(QFont("Segoe UI",11,600))
        self._recipe_lbl.setStyleSheet("color:#e2e8f0;background:transparent;")
        self._step_count_lbl = lbl("0 steps","#64748b",9)
        hh.addWidget(self._recipe_lbl,1)
        hh.addWidget(self._step_count_lbl)
        v.addWidget(hdr)

        # Step list
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:4px;background:#20242e;}"
            "QScrollBar::handle:vertical{background:#3a4055;border-radius:2px;}")
        self._nav_inner = QWidget()
        self._nav_inner.setStyleSheet("background:transparent;")
        self._nav_layout = QVBoxLayout(self._nav_inner)
        self._nav_layout.setContentsMargins(0,0,0,0)
        self._nav_layout.setSpacing(0)
        self._nav_layout.addStretch()
        scroll.setWidget(self._nav_inner)
        v.addWidget(scroll,1)

        # Progress footer
        prog = QFrame()
        prog.setStyleSheet(
            "QFrame{background:#16191f;border:none;"
            "border-top:1px solid #3a4055;border-radius:0 0 6px 6px;}")
        ph = QVBoxLayout(prog); ph.setContentsMargins(10,8,10,8); ph.setSpacing(4)
        self._prog_bar = QProgressBar()
        self._prog_bar.setFixedHeight(6); self._prog_bar.setTextVisible(False)
        self._prog_bar.setStyleSheet(
            "QProgressBar{background:#3a4055;border-radius:3px;border:none;}"
            "QProgressBar::chunk{background:#4a9eff;border-radius:3px;}")
        self._prog_bar.setValue(0)
        self._prog_summary = lbl("0 / 0 steps","#64748b",10)
        ph.addWidget(self._prog_bar)
        ph.addWidget(self._prog_summary)
        v.addWidget(prog)
        layout.addWidget(left)

    # ══════════════════════════════════════════
    # Right — Controls + Detail + Log
    # ══════════════════════════════════════════

    def _build_right(self, layout):
        right = QFrame()
        right.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        v = QVBoxLayout(right); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Control header
        ctrl = QFrame()
        ctrl.setStyleSheet(
            "QFrame{background:#16191f;border:none;"
            "border-bottom:1px solid #3a4055;border-radius:6px 6px 0 0;}")
        ch = QHBoxLayout(ctrl); ch.setContentsMargins(12,8,12,8); ch.setSpacing(6)

        self._cur_step_lbl = QLabel("— Load a recipe to start —")
        self._cur_step_lbl.setFont(QFont("Segoe UI",12,600))
        self._cur_step_lbl.setStyleSheet("color:#e2e8f0;background:transparent;")
        ch.addWidget(self._cur_step_lbl,1)

        self._back_btn    = _btn("◀ Back",   "#64748b", h=30, enabled=False)
        self._skip_btn    = _btn("⏭ Skip",   "#64748b", h=30, enabled=False)
        self._run_btn     = _btn("▶ Run",    "#22c55e", h=30, enabled=False)
        self._run_all_btn = _btn("▶▶ Run All","#a855f7", h=30, enabled=False)
        self._pause_btn   = _btn("⏸",        "#eab308", h=30, w=36, enabled=False)
        self._stop_btn    = _btn("⏹",        "#ef4444", h=30, w=36, enabled=False)
        self._next_btn    = _btn("Next ▶",   "#4a9eff", h=30, enabled=False)

        self._back_btn.clicked.connect(self._back)
        self._skip_btn.clicked.connect(self._skip)
        self._run_btn.clicked.connect(self._run_step)
        self._run_all_btn.clicked.connect(self._run_all)
        self._pause_btn.clicked.connect(self._pause)
        self._stop_btn.clicked.connect(self._stop)
        self._next_btn.clicked.connect(self._next)

        for b in [self._back_btn, self._skip_btn,
                  self._run_btn, self._run_all_btn,
                  self._pause_btn, self._stop_btn, self._next_btn]:
            ch.addWidget(b)
        v.addWidget(ctrl)

        # Body
        body = QHBoxLayout()
        body.setContentsMargins(12,10,12,10); body.setSpacing(10)

        # Step detail panel
        detail = QFrame()
        detail.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")
        df = QVBoxLayout(detail); df.setContentsMargins(12,10,12,10); df.setSpacing(8)

        self._detail_title = QLabel("Step Detail")
        self._detail_title.setFont(QFont("Segoe UI",12,600))
        self._detail_title.setStyleSheet("color:#e2e8f0;background:transparent;")
        df.addWidget(self._detail_title)
        df.addWidget(_hline())

        self._param_frame = QFrame()
        self._param_frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        self._param_layout = QGridLayout(self._param_frame)
        self._param_layout.setSpacing(8)
        df.addWidget(self._param_frame)
        df.addStretch()

        # Result
        res = QFrame()
        res.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:5px;}")
        rf = QVBoxLayout(res); rf.setContentsMargins(10,8,10,8); rf.setSpacing(4)
        rf.addWidget(lbl("RESULT","#64748b",9,True))
        self._result_lbl = QLabel("—")
        self._result_lbl.setFont(QFont("Consolas",13,700))
        self._result_lbl.setStyleSheet("color:#64748b;background:transparent;")
        self._step_prog = QProgressBar()
        self._step_prog.setFixedHeight(6); self._step_prog.setTextVisible(False)
        self._step_prog.setStyleSheet(
            "QProgressBar{background:#3a4055;border-radius:3px;border:none;}"
            "QProgressBar::chunk{background:#22c55e;border-radius:3px;}")
        self._step_prog.setValue(0)
        rf.addWidget(self._result_lbl); rf.addWidget(self._step_prog)
        df.addWidget(res)
        body.addWidget(detail,1)

        # Log panel
        log_frame = QFrame()
        log_frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        lf = QVBoxLayout(log_frame); lf.setContentsMargins(0,0,0,0); lf.setSpacing(4)
        lf.addWidget(lbl("RUN LOG","#64748b",9,True))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "QTextEdit{background:#16191f;border:1px solid #3a4055;"
            "border-radius:5px;color:#64748b;"
            "font-size:10px;font-family:Consolas,monospace;}")
        clr = _btn("Clear","#64748b",h=22)
        clr.clicked.connect(self._log.clear)
        lf.addWidget(self._log,1); lf.addWidget(clr)
        body.addWidget(log_frame,1)

        v.addLayout(body,1)
        layout.addWidget(right,1)

    # ══════════════════════════════════════════
    # Load Recipe
    # ══════════════════════════════════════════

    def load_recipe(self, recipe):
        self._recipe       = recipe
        self._steps        = recipe.get("steps",[])
        self._states       = [WAIT] * len(self._steps)
        self._current      = 0 if self._steps else -1
        self._run_all_mode = False

        name = recipe.get("name","Recipe")
        self._recipe_lbl.setText(name)
        self._step_count_lbl.setText(f"{len(self._steps)} steps")
        self._log_msg(
            f"Recipe loaded: {name} ({len(self._steps)} steps)","#4a9eff")

        self._rebuild_nav()
        self._update_progress()
        if self._steps:
            self._select_step(0)
            self._set_controls_idle()

    def _rebuild_nav(self):
        # ลบ items เก่า
        while self._nav_layout.count() > 1:
            item = self._nav_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._nav_items = []
        for i, step in enumerate(self._steps):
            item = StepNavItem(i, step)
            item.clicked.connect(lambda _, idx=i: self._select_step(idx))
            self._nav_layout.insertWidget(i, item)
            self._nav_items.append(item)
        self._update_nav_states()

    def _update_nav_states(self):
        for i, item in enumerate(self._nav_items):
            item.set_state(self._states[i])
            item.setChecked(i == self._current)

    def _select_step(self, idx):
        if idx < 0 or idx >= len(self._steps): return
        self._current = idx
        self._update_nav_states()
        self._show_step_detail(idx)
        self._update_controls()

    def _show_step_detail(self, idx):
        step   = self._steps[idx]
        state  = self._states[idx]
        stype  = step.get("type","")
        params = step.get("params",{})
        color  = STATE_COLOR[state]

        self._cur_step_lbl.setText(
            f"{idx+1:02d}.  {stype}   "
            f"{STATE_ICON[state]} {state.capitalize()}")
        self._cur_step_lbl.setStyleSheet(
            f"color:{color};font-size:12px;font-weight:600;background:transparent;")
        self._detail_title.setText(
            f"{STEP_ICONS.get(stype,'▸')}  {stype}")

        # Clear param grid
        while self._param_layout.count():
            item = self._param_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        COLS = 3
        for i,(key,val) in enumerate(params.items()):
            f = QFrame()
            f.setStyleSheet("QFrame{background:transparent;border:none;}")
            fv = QVBoxLayout(f); fv.setContentsMargins(0,0,0,0); fv.setSpacing(2)
            fv.addWidget(lbl(
                key.upper().replace("_"," "),"#64748b",9,True))
            vl = QLabel(str(val))
            vl.setFont(QFont("Consolas",11,700))
            vl.setStyleSheet("color:#e2e8f0;background:transparent;")
            fv.addWidget(vl)
            self._param_layout.addWidget(f, i//COLS, i%COLS)

        # Result label
        result_map = {
            DONE:    ("PASS",    "#22c55e"),
            FAILED:  ("FAIL",    "#ef4444"),
            SKIPPED: ("SKIPPED", "#3a4055"),
            RUNNING: ("Running...","#4a9eff"),
            WAIT:    ("—",       "#64748b"),
        }
        text, color = result_map.get(state, ("—","#64748b"))
        self._result_lbl.setText(text)
        self._result_lbl.setStyleSheet(
            f"color:{color};font-size:13px;font-weight:700;background:transparent;")
        self._step_prog.setValue(
            100 if state == DONE else 0)

    # ══════════════════════════════════════════
    # Controls state
    # ══════════════════════════════════════════

    def _set_controls_idle(self):
        has_steps = len(self._steps) > 0
        self._run_btn.setEnabled(has_steps)
        self._run_all_btn.setEnabled(has_steps)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._skip_btn.setEnabled(self._current >= 0)
        self._back_btn.setEnabled(self._current > 0)
        self._next_btn.setEnabled(
            self._current >= 0 and self._current < len(self._steps)-1)

    def _set_controls_running(self):
        self._run_btn.setEnabled(False)
        self._run_all_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._skip_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._next_btn.setEnabled(False)

    def _update_controls(self):
        if not self._running:
            self._set_controls_idle()

    def _update_progress(self):
        total = len(self._states)
        done  = sum(1 for s in self._states if s in (DONE, SKIPPED))
        self._prog_bar.setValue(int(done/total*100) if total else 0)
        self._prog_summary.setText(f"{done} / {total} steps")

    # ══════════════════════════════════════════
    # Run logic
    # ══════════════════════════════════════════

    def _run_step(self):
        idx = self._current
        if idx < 0 or idx >= len(self._steps): return
        step = self._steps[idx]
        if not step.get("enabled", True):
            self._log_msg(f"Step {idx+1} disabled — skipping","#64748b")
            self._skip(); return

        self._running = True
        self._states[idx] = RUNNING
        self._update_nav_states()
        self._show_step_detail(idx)
        self._set_controls_running()
        self._log_msg(
            f"▶  Step {idx+1}: {step.get('type','')}","#4a9eff")

        self._runner = StepRunner(step, {})
        self._runner.log.connect(self._on_step_log)
        self._runner.progress.connect(self._step_prog.setValue)
        self._runner.done.connect(self._on_step_done)
        self._runner.start()

    def _on_step_log(self, msg, level):
        colors = {
            "info":"#94a3b8","ok":"#22c55e",
            "warn":"#eab308","error":"#ef4444"}
        self._log_msg(f"  {msg}", colors.get(level,"#94a3b8"))

    def _on_step_done(self, success):
        idx = self._current
        self._states[idx] = DONE if success else FAILED
        self._running = False
        self._runner  = None
        self._step_prog.setValue(100 if success else 0)
        self._update_nav_states()
        self._show_step_detail(idx)
        self._update_progress()

        if success:
            self._log_msg(f"✓  Step {idx+1} done","#22c55e")
            if self._run_all_mode:
                QTimer.singleShot(300, self._next_auto)
        else:
            self._log_msg(f"✗  Step {idx+1} failed","#ef4444")
            self._run_all_mode = False

        self._set_controls_idle()

    def _pause(self):
        if self._runner: self._runner.abort()
        self._running = False
        self._run_all_mode = False
        self._log_msg("⏸  Paused","#eab308")
        self._set_controls_idle()

    def _stop(self):
        if self._runner: self._runner.abort()
        self._running = False
        self._run_all_mode = False
        idx = self._current
        if 0 <= idx < len(self._states) and self._states[idx] == RUNNING:
            self._states[idx] = WAIT
        self._update_nav_states()
        self._show_step_detail(idx) if idx >= 0 else None
        self._set_controls_idle()
        self._log_msg("⏹  Stopped","#ef4444")

    def _skip(self):
        idx = self._current
        if idx < 0 or idx >= len(self._steps): return
        self._states[idx] = SKIPPED
        self._update_nav_states()
        self._update_progress()
        self._log_msg(f"⊘  Step {idx+1} skipped","#3a4055")
        if idx < len(self._steps)-1:
            self._select_step(idx+1)

    def _back(self):
        if self._current > 0:
            self._select_step(self._current-1)

    def _next(self):
        if self._current < len(self._steps)-1:
            self._select_step(self._current+1)

    def _run_all(self):
        self._run_all_mode = True
        # หา step แรกที่ยังไม่ done/skipped
        for i, s in enumerate(self._states):
            if s not in (DONE, SKIPPED):
                self._select_step(i)
                self._run_step()
                return
        self._run_all_mode = False
        self._log_msg("✓✓  All steps complete","#22c55e")

    def _next_auto(self):
        next_idx = self._current + 1
        if next_idx >= len(self._steps):
            self._run_all_mode = False
            self._log_msg("✓✓  All steps complete","#22c55e")
            return
        self._select_step(next_idx)
        QTimer.singleShot(100, self._run_step)

    # ══════════════════════════════════════════
    # Log
    # ══════════════════════════════════════════

    def _log_msg(self, msg, color="#94a3b8"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:#3a4055;">[{ts}]</span> '
            f'<span style="color:{color};">{msg}</span>')