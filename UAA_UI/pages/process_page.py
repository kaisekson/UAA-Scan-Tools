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

import json, os, datetime, time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QScrollArea,
    QTextEdit, QSizePolicy, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

# Step states
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
    SKIPPED: "#64748b",
}
STATE_ICON = {
    WAIT:    "○",
    RUNNING: "▶",
    DONE:    "✓",
    FAILED:  "✗",
    SKIPPED: "⊘",
}


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def _btn(text, color="#4a9eff", h=30, w=None, enabled=True):
    b = QPushButton(text)
    if h: b.setFixedHeight(h)
    if w: b.setFixedWidth(w)
    bg = {"#4a9eff":"#1e2d47","#22c55e":"#1a3a1a",
          "#ef4444":"#1a0000","#eab308":"#1a1000",
          "#94a3b8":"#2a2f3d","#a855f7":"#1a0d2e"}.get(color,"#2a2f3d")
    b.setStyleSheet(
        f"QPushButton{{background:{bg};border:1px solid {color};"
        f"border-radius:4px;color:{color};font-size:11px;font-weight:600;padding:0 10px;}}"
        f"QPushButton:hover{{background:{color};color:#000;}}"
        f"QPushButton:disabled{{border-color:#3a4055;color:#64748b;background:#16191f;}}")
    b.setEnabled(enabled)
    return b

def _hline():
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("background:#3a4055;max-height:1px;"); return f


# ══════════════════════════════════════════════
# Step Runner (QThread per step)
# ══════════════════════════════════════════════

class StepRunner(QThread):
    log     = pyqtSignal(str, str)   # message, level (info/warn/error/ok)
    done    = pyqtSignal(bool)       # success
    progress = pyqtSignal(int)       # 0-100

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
            fn = getattr(self, f"_run_{step_type.lower().replace(' ','_')}",
                         self._run_generic)
            fn(params)
            if not self._abort:
                self.log.emit(f"{step_type} — Done", "ok")
                self.done.emit(True)
        except Exception as e:
            self.log.emit(f"{step_type} — Error: {e}", "error")
            self.done.emit(False)

    # ── Step implementations ───────────────────

    def _run_generic(self, params):
        """Placeholder — simulate with delay"""
        for i in range(10):
            if self._abort: break
            time.sleep(0.1)
            self.progress.emit((i+1)*10)
        self.log.emit("(Simulated — no hardware connected)", "warn")

    def _run_coarse_scan(self, params):
        self.log.emit(f"Coarse scan range X±{params.get('range_x','0.5')} "
                      f"Y±{params.get('range_y','0.5')} mm", "info")
        self._run_generic(params)

    def _run_fine_align(self, params):
        self.log.emit(f"Fine align step {params.get('step','0.001')} mm", "info")
        self._run_generic(params)

    def _run_tilt_correction(self, params):
        self.log.emit(f"Tilt correction axis {params.get('axis','U and V')}", "info")
        self._run_generic(params)

    def _run_dispense(self, params):
        self.log.emit(f"Dispense {params.get('program','P1')} "
                      f"{params.get('pressure','50')}kPa {params.get('time_ms','100')}ms", "info")
        self._run_generic(params)

    def _run_uv_cure(self, params):
        t = float(params.get("time_s","5.0"))
        self.log.emit(f"UV Cure {t}s @ {params.get('intensity','100')}%", "info")
        steps = max(1, int(t*2))
        for i in range(steps):
            if self._abort: break
            time.sleep(0.5/steps)
            self.progress.emit(int((i+1)/steps*100))

    def _run_verify(self, params):
        self.log.emit(f"Verify min signal {params.get('min_signal','0.5')} µA", "info")
        self._run_generic(params)

    def _run_move(self, params):
        dev = params.get("device","Cartesian")
        self.log.emit(f"Move {dev} to X:{params.get('x','0')} "
                      f"Y:{params.get('y','0')} Z:{params.get('z','0')} mm", "info")
        self._run_generic(params)

    def _run_wait(self, params):
        t = float(params.get("time_s","1.0"))
        msg = params.get("message","")
        self.log.emit(f"Wait {t}s {f'— {msg}' if msg else ''}", "info")
        steps = max(1, int(t*10))
        for i in range(steps):
            if self._abort: break
            time.sleep(t/steps)
            self.progress.emit(int((i+1)/steps*100))

    def _run_set_tec(self, params):
        self.log.emit(f"Set TEC {params.get('setpoint','25')}°C", "info")
        self._run_generic(params)


# ══════════════════════════════════════════════
# Step Nav Item
# ══════════════════════════════════════════════

class StepNavItem(QPushButton):
    def __init__(self, idx, step):
        super().__init__()
        self._idx   = idx
        self._step  = step
        self._state = WAIT
        self.setCheckable(True)
        self.setFixedHeight(52)
        self._update_style()

    def set_state(self, state):
        self._state = state
        self._update_style()

    def _update_style(self):
        s     = self._state
        color = STATE_COLOR[s]
        icon  = STATE_ICON[s]
        name  = self._step.get("type","Step")
        step_icon = {"Coarse Scan":"🔬","Fine Align":"🎯","Tilt Correction":"↕",
                     "Dispense":"💧","UV Cure":"☀","Verify":"✅",
                     "Move":"🤖","Wait":"⏱","Set TEC":"🌡"}.get(name,"▸")

        enabled = self._step.get("enabled",True)
        opacity = "opacity:0.4;" if not enabled else ""

        checked_bg = "#1e2d47" if s==WAIT else \
                     "#0d1a2e" if s==RUNNING else \
                     "#0d1a0d" if s==DONE else \
                     "#1a0000" if s==FAILED else "#2a2f3d"

        self.setStyleSheet(f"""
            QPushButton{{
                background:#20242e;
                border:none;border-bottom:1px solid #3a4055;
                border-left:3px solid transparent;
                text-align:left;padding:6px 10px;
                {opacity}
            }}
            QPushButton:checked{{
                background:{checked_bg};
                border-left:3px solid {color};
            }}
            QPushButton:hover{{background:#2a2f3d;}}
        """)

        # Build text layout manually via label overlay — use setText with rich
        self.setText("")
        # Use child labels
        for child in self.findChildren(QLabel):
            child.deleteLater()

        v = QVBoxLayout(self); v.setContentsMargins(8,4,8,4); v.setSpacing(1)
        v.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        top = QHBoxLayout(); top.setSpacing(6)
        num = QLabel(f"{self._idx+1:02d}")
        num.setFont(QFont("Consolas",9)); num.setFixedWidth(18)
        num.setStyleSheet(f"color:#64748b;background:transparent;")
        ic  = QLabel(step_icon); ic.setFixedWidth(18)
        ic.setStyleSheet("background:transparent;font-size:13px;")
        nm  = QLabel(name); nm.setFont(QFont("Segoe UI",11,600))
        nm.setStyleSheet(f"color:{'#e2e8f0' if enabled else '#64748b'};background:transparent;")
        st  = QLabel(f"{icon} {s.capitalize()}")
        st.setStyleSheet(f"color:{color};font-size:9px;font-weight:700;background:transparent;")
        top.addWidget(num); top.addWidget(ic); top.addWidget(nm,1); top.addWidget(st)
        v.addLayout(top)

        # Params summary
        params = self._step.get("params",{})
        parts  = [f"{k}:{v}" for k,v in list(params.items())[:2]]
        if parts:
            psum = QLabel("  ·  ".join(parts))
            psum.setStyleSheet("color:#64748b;font-size:9px;background:transparent;padding-left:36px;")
            v.addWidget(psum)


# ══════════════════════════════════════════════
# Process Page
# ══════════════════════════════════════════════

class ProcessPage(QWidget):
    def __init__(self):
        super().__init__()
        self._recipe  = None
        self._steps   = []
        self._states  = []
        self._current = -1
        self._runner  = None
        self._running = False
        self._paused  = False

        root = QHBoxLayout(self)
        root.setContentsMargins(12,12,12,12); root.setSpacing(10)

        self._build_left(root)
        self._build_right(root)

    # ══════════════════════════════════════════
    # Left — Step navigator
    # ══════════════════════════════════════════

    def _build_left(self, layout):
        left = QFrame()
        left.setFixedWidth(240)
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
        hh.addWidget(self._recipe_lbl,1); hh.addWidget(self._step_count_lbl)
        v.addWidget(hdr)

        # Step list scroll
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:4px;background:#16191f;}"
            "QScrollBar::handle:vertical{background:#3a4055;border-radius:2px;}")
        self._nav_inner = QWidget()
        self._nav_inner.setStyleSheet("background:transparent;")
        self._nav_layout = QVBoxLayout(self._nav_inner)
        self._nav_layout.setContentsMargins(0,0,0,0); self._nav_layout.setSpacing(0)
        self._nav_layout.addStretch()
        scroll.setWidget(self._nav_inner)
        v.addWidget(scroll,1)

        # Progress summary
        prog_frame = QFrame()
        prog_frame.setStyleSheet(
            "QFrame{background:#16191f;border:none;border-top:1px solid #3a4055;"
            "border-radius:0 0 6px 6px;}")
        ph = QVBoxLayout(prog_frame); ph.setContentsMargins(10,8,10,8); ph.setSpacing(4)
        self._prog_bar = QProgressBar()
        self._prog_bar.setFixedHeight(6)
        self._prog_bar.setTextVisible(False)
        self._prog_bar.setStyleSheet(
            "QProgressBar{background:#3a4055;border-radius:3px;border:none;}"
            "QProgressBar::chunk{background:#4a9eff;border-radius:3px;}")
        self._prog_bar.setValue(0)
        self._prog_summary = lbl("0 / 0 steps","#64748b",10)
        ph.addWidget(self._prog_bar)
        ph.addWidget(self._prog_summary)
        v.addWidget(prog_frame)

        layout.addWidget(left)

    # ══════════════════════════════════════════
    # Right — Detail + Controls + Log
    # ══════════════════════════════════════════

    def _build_right(self, layout):
        right = QFrame()
        right.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        v = QVBoxLayout(right); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Header controls
        ctrl = QFrame()
        ctrl.setStyleSheet(
            "QFrame{background:#16191f;border:none;"
            "border-bottom:1px solid #3a4055;border-radius:6px 6px 0 0;}")
        ch = QHBoxLayout(ctrl); ch.setContentsMargins(12,8,12,8); ch.setSpacing(8)

        self._cur_step_lbl = QLabel("— Load a recipe to start —")
        self._cur_step_lbl.setFont(QFont("Segoe UI",12,600))
        self._cur_step_lbl.setStyleSheet("color:#e2e8f0;background:transparent;")
        ch.addWidget(self._cur_step_lbl,1)

        # Control buttons
        self._run_btn   = _btn("▶ Run","#22c55e",h=30)
        self._pause_btn = _btn("⏸","#eab308",h=30,w=34,enabled=False)
        self._stop_btn  = _btn("⏹","#ef4444",h=30,w=34,enabled=False)
        self._skip_btn  = _btn("⏭ Skip","#64748b",h=30,enabled=False)
        self._back_btn  = _btn("◀ Back","#64748b",h=30,enabled=False)
        self._next_btn  = _btn("Next ▶","#4a9eff",h=30,enabled=False)
        self._run_all_btn = _btn("▶▶ Run All","#a855f7",h=30,enabled=False)

        self._run_btn.clicked.connect(self._run_step)
        self._pause_btn.clicked.connect(self._pause)
        self._stop_btn.clicked.connect(self._stop)
        self._skip_btn.clicked.connect(self._skip)
        self._back_btn.clicked.connect(self._back)
        self._next_btn.clicked.connect(self._next)
        self._run_all_btn.clicked.connect(self._run_all)

        for b in [self._back_btn, self._skip_btn,
                  self._run_btn, self._run_all_btn,
                  self._pause_btn, self._stop_btn, self._next_btn]:
            ch.addWidget(b)
        v.addWidget(ctrl)

        # Body: step detail + log
        body = QHBoxLayout(); body.setContentsMargins(12,10,12,10); body.setSpacing(10)

        # Step detail
        detail_frame = QFrame()
        detail_frame.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:6px;}")
        df = QVBoxLayout(detail_frame); df.setContentsMargins(12,10,12,10); df.setSpacing(8)
        self._detail_title = QLabel("Step Detail")
        self._detail_title.setFont(QFont("Segoe UI",12,600))
        self._detail_title.setStyleSheet("color:#e2e8f0;background:transparent;")
        df.addWidget(self._detail_title)
        df.addWidget(_hline())

        self._param_frame = QFrame()
        self._param_frame.setStyleSheet("QFrame{background:transparent;border:none;}")
        self._param_layout = QGridLayout(self._param_frame)
        self._param_layout.setSpacing(6)
        df.addWidget(self._param_frame)
        df.addStretch()

        # Step result
        self._result_frame = QFrame()
        self._result_frame.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:5px;}")
        rf = QVBoxLayout(self._result_frame); rf.setContentsMargins(10,8,10,8); rf.setSpacing(4)
        rf.addWidget(lbl("RESULT","#64748b",9,True))
        self._result_lbl = QLabel("—")
        self._result_lbl.setFont(QFont("Consolas",12,700))
        self._result_lbl.setStyleSheet("color:#64748b;background:transparent;")
        rf.addWidget(self._result_lbl)

        # Step progress bar
        self._step_prog = QProgressBar()
        self._step_prog.setFixedHeight(6); self._step_prog.setTextVisible(False)
        self._step_prog.setStyleSheet(
            "QProgressBar{background:#3a4055;border-radius:3px;border:none;}"
            "QProgressBar::chunk{background:#22c55e;border-radius:3px;}")
        self._step_prog.setValue(0)
        rf.addWidget(self._step_prog)
        df.addWidget(self._result_frame)

        body.addWidget(detail_frame,1)

        # Log
        log_frame = QFrame()
        log_frame.setStyleSheet(
            "QFrame{background:transparent;border:none;}")
        lf = QVBoxLayout(log_frame); lf.setContentsMargins(0,0,0,0); lf.setSpacing(4)
        lf.addWidget(lbl("RUN LOG","#64748b",9,True))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "QTextEdit{background:#16191f;border:1px solid #3a4055;border-radius:5px;"
            "color:#64748b;font-size:10px;font-family:Consolas,monospace;}")
        clr_btn = _btn("Clear","#64748b",h=22)
        clr_btn.clicked.connect(self._log.clear)
        lf.addWidget(self._log,1); lf.addWidget(clr_btn)
        body.addWidget(log_frame,1)

        v.addLayout(body,1)
        layout.addWidget(right,1)

    # ══════════════════════════════════════════
    # Load Recipe
    # ══════════════════════════════════════════

    def load_recipe(self, recipe):
        self._recipe  = recipe
        self._steps   = recipe.get("steps",[])
        self._states  = [WAIT]*len(self._steps)
        self._current = 0 if self._steps else -1

        name = recipe.get("name","Recipe")
        self._recipe_lbl.setText(name)
        self._step_count_lbl.setText(f"{len(self._steps)} steps")
        self._log_msg(f"Recipe loaded: {name} ({len(self._steps)} steps)","#4a9eff")

        self._rebuild_nav()
        self._update_progress()
        if self._steps:
            self._select_step(0)
            self._set_controls_idle()

    def _rebuild_nav(self):
        while self._nav_layout.count() > 1:
            item = self._nav_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._nav_items = []
        for i, step in enumerate(self._steps):
            item = StepNavItem(i, step)
            item.clicked.connect(lambda _,idx=i: self._select_step(idx))
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
            f"{idx+1:02d}.  {stype}  "
            f"<span style='color:{color};font-size:10px;'>"
            f"{STATE_ICON[state]} {state.capitalize()}</span>")
        self._detail_title.setText(stype)
        self._detail_title.setStyleSheet(f"color:#e2e8f0;background:transparent;")

        # Clear params
        while self._param_layout.count():
            item = self._param_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        COLS = 3
        for i,(key,val) in enumerate(params.items()):
            f = QFrame(); f.setStyleSheet("QFrame{background:transparent;border:none;}")
            fv = QVBoxLayout(f); fv.setContentsMargins(0,0,0,0); fv.setSpacing(2)
            fv.addWidget(lbl(key.upper().replace("_"," "),"#64748b",9,True))
            vl = QLabel(str(val)); vl.setFont(QFont("Consolas",11,700))
            vl.setStyleSheet("color:#e2e8f0;background:transparent;")
            fv.addWidget(vl)
            self._param_layout.addWidget(f, i//COLS, i%COLS)

        # Result
        if state == DONE:
            self._result_lbl.setText("PASS")
            self._result_lbl.setStyleSheet("color:#22c55e;font-size:13px;font-weight:700;background:transparent;")
        elif state == FAILED:
            self._result_lbl.setText("FAIL")
            self._result_lbl.setStyleSheet("color:#ef4444;font-size:13px;font-weight:700;background:transparent;")
        elif state == SKIPPED:
            self._result_lbl.setText("SKIPPED")
            self._result_lbl.setStyleSheet("color:#64748b;font-size:13px;font-weight:700;background:transparent;")
        elif state == RUNNING:
            self._result_lbl.setText("Running...")
            self._result_lbl.setStyleSheet("color:#4a9eff;font-size:13px;font-weight:700;background:transparent;")
        else:
            self._result_lbl.setText("—")
            self._result_lbl.setStyleSheet("color:#64748b;font-size:13px;background:transparent;")

        self._step_prog.setValue(0)

    # ══════════════════════════════════════════
    # Controls
    # ══════════════════════════════════════════

    def _set_controls_idle(self):
        self._run_btn.setEnabled(True)
        self._run_all_btn.setEnabled(True)
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
        done  = sum(1 for s in self._states if s in (DONE,SKIPPED))
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
        self._log_msg(f"▶ Step {idx+1}: {step.get('type','')}","#4a9eff")

        self._runner = StepRunner(step, {})
        self._runner.log.connect(self._on_step_log)
        self._runner.progress.connect(self._step_prog.setValue)
        self._runner.done.connect(self._on_step_done)
        self._runner.start()

    def _on_step_log(self, msg, level):
        colors = {"info":"#94a3b8","ok":"#22c55e","warn":"#eab308","error":"#ef4444"}
        self._log_msg(msg, colors.get(level,"#94a3b8"))

    def _on_step_done(self, success):
        idx = self._current
        self._states[idx] = DONE if success else FAILED
        self._running = False
        self._runner = None
        self._step_prog.setValue(100 if success else 0)
        self._update_nav_states()
        self._show_step_detail(idx)
        self._update_progress()

        if success:
            self._log_msg(f"✓ Step {idx+1} done","#22c55e")
            # auto advance if run_all
            if self._run_all_mode:
                self._next_auto()
        else:
            self._log_msg(f"✗ Step {idx+1} failed","#ef4444")
            self._run_all_mode = False

        self._set_controls_idle()

    def _pause(self):
        if self._runner: self._runner.abort()
        self._paused = True
        self._log_msg("⏸ Paused","#eab308")

    def _stop(self):
        if self._runner: self._runner.abort()
        self._running = False
        self._run_all_mode = False
        idx = self._current
        if 0 <= idx < len(self._states) and self._states[idx] == RUNNING:
            self._states[idx] = WAIT
        self._update_nav_states()
        self._set_controls_idle()
        self._log_msg("⏹ Stopped","#ef4444")

    def _skip(self):
        idx = self._current
        if idx < 0 or idx >= len(self._steps): return
        self._states[idx] = SKIPPED
        self._update_nav_states()
        self._update_progress()
        self._log_msg(f"⊘ Step {idx+1} skipped","#64748b")
        self._next()

    def _back(self):
        if self._current > 0:
            self._select_step(self._current-1)

    def _next(self):
        if self._current < len(self._steps)-1:
            self._select_step(self._current+1)

    _run_all_mode = False

    def _run_all(self):
        self._run_all_mode = True
        # Find first non-done step
        for i, s in enumerate(self._states):
            if s not in (DONE, SKIPPED):
                self._select_step(i)
                self._run_step()
                return
        self._log_msg("All steps complete","#22c55e")

    def _next_auto(self):
        """Auto advance after step done in run_all mode"""
        next_idx = self._current + 1
        if next_idx >= len(self._steps):
            self._run_all_mode = False
            self._log_msg("✓✓ All steps complete","#22c55e")
            return
        self._select_step(next_idx)
        QTimer.singleShot(200, self._run_step)

    # ══════════════════════════════════════════
    # Log
    # ══════════════════════════════════════════

    def _log_msg(self, msg, color="#94a3b8"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:#64748b;">[{ts}]</span> '
            f'<span style="color:{color};">{msg}</span>')
