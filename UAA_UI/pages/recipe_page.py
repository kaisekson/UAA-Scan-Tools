"""
Recipe Page
============
- Recipe list (left)
- Recipe editor (right): meta + steps
- Step params inline expand
- Save/Load JSON
- Engineer mode only (operator mode later)
"""

import json, os, datetime, copy
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QComboBox,
    QScrollArea, QSizePolicy, QDialog, QDialogButtonBox,
    QInputDialog, QMessageBox, QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from core.widgets import lbl, divider

RECIPE_FILE = "recipes.json"

# ── Step definitions ──────────────────────────
STEP_TYPES = {
    "Coarse Scan": {
        "icon": "🔬",
        "params": [
            ("range_x",    "Range X (mm)",   "0.500"),
            ("range_y",    "Range Y (mm)",   "0.500"),
            ("step",       "Step (mm)",      "0.050"),
            ("velocity",   "Velocity (mm/s)","2.000"),
            ("nplc",       "NPLC",           "1.0"),
        ]
    },
    "Fine Align": {
        "icon": "🎯",
        "params": [
            ("range_x",    "Range X (mm)",   "0.050"),
            ("range_y",    "Range Y (mm)",   "0.050"),
            ("step",       "Step (mm)",      "0.001"),
            ("velocity",   "Velocity (mm/s)","0.500"),
            ("tolerance",  "Tolerance (µA)", "0.010"),
            ("max_iter",   "Max iterations", "3"),
        ]
    },
    "Tilt Correction": {
        "icon": "↕",
        "params": [
            ("axis",       "Axis",           "U and V"),
            ("step_deg",   "Step (°)",       "0.010"),
            ("threshold",  "Threshold (µA)", "0.005"),
            ("max_iter",   "Max iterations", "5"),
            ("retry",      "Retry on fail",  "Yes"),
            ("timeout",    "Timeout (s)",    "30"),
        ]
    },
    "Dispense": {
        "icon": "💧",
        "params": [
            ("program",    "Program",        "P1"),
            ("pressure",   "Pressure (kPa)", "50"),
            ("time_ms",    "Time (ms)",      "100"),
            ("repeat",     "Repeat (×)",     "1"),
            ("wait_ms",    "Wait after (ms)","200"),
        ]
    },
    "UV Cure": {
        "icon": "☀",
        "params": [
            ("time_s",     "Cure time (s)",  "5.0"),
            ("intensity",  "Intensity (%)",  "100"),
            ("wait_s",     "Wait after (s)", "1.0"),
        ]
    },
    "Verify": {
        "icon": "✅",
        "params": [
            ("min_signal", "Min signal (µA)","0.500"),
            ("range",      "Scan range (mm)","0.100"),
            ("threshold",  "Pass threshold %","90"),
            ("fail_action","On fail",        "Stop"),
        ]
    },
    "Move": {
        "icon": "🤖",
        "params": [
            ("device",     "Device",         "Cartesian"),
            ("x",          "X (mm)",         "0.000"),
            ("y",          "Y (mm)",         "0.000"),
            ("z",          "Z (mm)",         "0.000"),
            ("velocity",   "Velocity (mm/s)","5.000"),
        ]
    },
    "Wait": {
        "icon": "⏱",
        "params": [
            ("time_s",     "Wait time (s)",  "1.0"),
            ("message",    "Message",        ""),
        ]
    },
    "Set TEC": {
        "icon": "🌡",
        "params": [
            ("setpoint",   "Setpoint (°C)",  "25.000"),
            ("wait_stable","Wait stable (s)","10"),
            ("tolerance",  "Tolerance (°C)", "0.100"),
        ]
    },
}

SELECT_PARAMS = {
    "axis":        ["U and V","U only","V only"],
    "retry":       ["Yes","No"],
    "fail_action": ["Stop","Continue","Retry"],
    "device":      ["Cartesian","Hexapod 1","Hexapod 2","Linear"],
}


def _default_step(step_type):
    defn = STEP_TYPES.get(step_type, {"icon":"?","params":[]})
    return {
        "type":    step_type,
        "enabled": True,
        "params":  {k: v for k,_,v in defn["params"]},
    }

def _load_recipes():
    if os.path.exists(RECIPE_FILE):
        try:
            with open(RECIPE_FILE) as f:
                return json.load(f)
        except: pass
    return []

def _save_recipes(recipes):
    with open(RECIPE_FILE,"w") as f:
        json.dump(recipes, f, indent=2)


# ══════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════

def _btn(text, color="#4a9eff", h=26, w=None):
    b = QPushButton(text)
    if h: b.setFixedHeight(h)
    if w: b.setFixedWidth(w)
    bg = {"#4a9eff":"#1e2d47","#22c55e":"#1a3a1a",
          "#ef4444":"#1a0000","#eab308":"#1a1000",
          "#94a3b8":"#2a2f3d"}.get(color,"#2a2f3d")
    b.setStyleSheet(
        f"QPushButton{{background:{bg};border:1px solid {color};"
        f"border-radius:4px;color:{color};font-size:11px;font-weight:600;padding:0 10px;}}"
        f"QPushButton:hover{{background:{color};color:#000;}}"
        f"QPushButton:disabled{{border-color:#3a4055;color:#64748b;background:#16191f;}}")
    return b

def _small_btn(text, color="#64748b", size=28):
    b = QPushButton(text)
    b.setFixedHeight(28)
    b.setMinimumWidth(54)
    b.setStyleSheet(
        f"QPushButton{{background:#252a38;border:1px solid #3a4055;"
        f"border-radius:4px;color:{color};font-size:11px;font-weight:600;"
        f"padding:0 8px;}}"
        f"QPushButton:hover{{border-color:{color};color:{color};background:#2e3447;}}")
    return b

def _field_input(val="", w=None):
    e = QLineEdit(val)
    if w: e.setFixedWidth(w)
    e.setFixedHeight(24)
    e.setStyleSheet(
        "background:#2a2f3d;border:1px solid #3a4055;border-radius:3px;"
        "color:#e2e8f0;padding:1px 6px;font-size:11px;font-family:monospace;")
    return e

def _field_combo(items, val=""):
    c = QComboBox(); c.addItems(items)
    c.setFixedHeight(24)
    c.setStyleSheet(
        "QComboBox{background:#2a2f3d;border:1px solid #3a4055;border-radius:3px;"
        "color:#e2e8f0;padding:0 5px;font-size:11px;}"
        "QComboBox::drop-down{border:none;}"
        "QComboBox QAbstractItemView{background:#20242e;color:#e2e8f0;font-size:11px;}")
    if val in items: c.setCurrentText(val)
    return c


# ══════════════════════════════════════════════
# Toggle Switch
# ══════════════════════════════════════════════

class ToggleSwitch(QFrame):
    toggled = pyqtSignal(bool)
    def __init__(self, on=True):
        super().__init__()
        self._on = on
        self.setFixedSize(36,20); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update()

    def _update(self):
        if self._on:
            self.setStyleSheet(
                "QFrame{background:#22c55e;border-radius:10px;border:none;}")
        else:
            self.setStyleSheet(
                "QFrame{background:#3a4055;border-radius:10px;border:none;}")

    def mousePressEvent(self, e):
        self._on = not self._on; self._update(); self.toggled.emit(self._on)

    def set_state(self, on):
        self._on = on; self._update()


# ══════════════════════════════════════════════
# Step Row Widget
# ══════════════════════════════════════════════

class StepRow(QFrame):
    edit_requested   = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    move_up          = pyqtSignal(int)
    move_down        = pyqtSignal(int)
    enabled_changed  = pyqtSignal(int, bool)

    def __init__(self, idx, step_data):
        super().__init__()
        self._idx  = idx
        self._data = step_data
        self._expanded = False
        self._param_widgets = {}

        self.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:5px;}")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Main row
        main = QFrame(); main.setStyleSheet("QFrame{background:transparent;border:none;}")
        h = QHBoxLayout(main); h.setContentsMargins(10,7,10,7); h.setSpacing(8)

        num_lbl = QLabel(f"{idx+1:02d}")
        num_lbl.setFixedWidth(20); num_lbl.setFont(QFont("Consolas",10))
        num_lbl.setStyleSheet("color:#64748b;background:transparent;")

        icon_lbl = QLabel(STEP_TYPES.get(step_data["type"],{}).get("icon","?"))
        icon_lbl.setFixedWidth(20)
        icon_lbl.setStyleSheet("background:transparent;font-size:14px;")

        info = QVBoxLayout(); info.setSpacing(1)
        self._name_lbl = QLabel(step_data["type"])
        self._name_lbl.setFont(QFont("Segoe UI",11,600))
        self._name_lbl.setStyleSheet("color:#e2e8f0;background:transparent;")
        self._param_lbl = QLabel(self._param_summary())
        self._param_lbl.setStyleSheet("color:#64748b;font-size:10px;background:transparent;")
        info.addWidget(self._name_lbl); info.addWidget(self._param_lbl)

        self._toggle = ToggleSwitch(step_data.get("enabled",True))
        self._toggle.toggled.connect(lambda s,i=idx: self.enabled_changed.emit(i,s))

        # Action buttons — ใช้ text ชัดเจน ไม่ใช้ symbol เดี่ยว
        up_btn = QPushButton("▲ Up"); up_btn.setFixedHeight(28); up_btn.setMinimumWidth(58)
        up_btn.setStyleSheet(
            "QPushButton{background:#252a38;border:1px solid #3a4055;border-radius:4px;"
            "color:#64748b;font-size:11px;font-weight:600;padding:0 8px;}"
            "QPushButton:hover{border-color:#94a3b8;color:#e2e8f0;background:#2e3447;}")
        up_btn.clicked.connect(lambda: self.move_up.emit(self._idx))

        dn_btn = QPushButton("▼ Dn"); dn_btn.setFixedHeight(28); dn_btn.setMinimumWidth(58)
        dn_btn.setStyleSheet(
            "QPushButton{background:#252a38;border:1px solid #3a4055;border-radius:4px;"
            "color:#64748b;font-size:11px;font-weight:600;padding:0 8px;}"
            "QPushButton:hover{border-color:#94a3b8;color:#e2e8f0;background:#2e3447;}")
        dn_btn.clicked.connect(lambda: self.move_down.emit(self._idx))

        edit_btn = QPushButton("✎ Edit"); edit_btn.setFixedHeight(28); edit_btn.setMinimumWidth(64)
        edit_btn.setStyleSheet(
            "QPushButton{background:#252a38;border:1px solid #3a4055;border-radius:4px;"
            "color:#eab308;font-size:11px;font-weight:600;padding:0 8px;}"
            "QPushButton:hover{border-color:#eab308;color:#eab308;background:#1a1000;}")
        edit_btn.clicked.connect(self._toggle_expand)

        del_btn = QPushButton("✕ Del"); del_btn.setFixedHeight(28); del_btn.setMinimumWidth(58)
        del_btn.setStyleSheet(
            "QPushButton{background:#252a38;border:1px solid #3a4055;border-radius:4px;"
            "color:#64748b;font-size:11px;font-weight:600;padding:0 8px;}"
            "QPushButton:hover{border-color:#ef4444;color:#ef4444;background:#2a0000;}")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._idx))

        h.addWidget(num_lbl); h.addWidget(icon_lbl)
        h.addLayout(info,1); h.addWidget(self._toggle)
        h.addWidget(up_btn); h.addWidget(dn_btn)
        h.addWidget(edit_btn); h.addWidget(del_btn)
        v.addWidget(main)

        # Param panel (hidden by default)
        self._param_frame = QFrame()
        self._param_frame.setStyleSheet(
            "QFrame{background:#20242e;border:none;"
            "border-top:1px solid #4a9eff44;border-radius:0 0 5px 5px;}")
        self._param_frame.setVisible(False)
        pv = QVBoxLayout(self._param_frame)
        pv.setContentsMargins(10,8,10,8); pv.setSpacing(6)
        self._build_params(pv)
        v.addWidget(self._param_frame)

    def _param_summary(self):
        params = self._data.get("params",{})
        defn   = STEP_TYPES.get(self._data["type"],{}).get("params",[])
        parts  = []
        for key, lbl_txt, _ in defn[:4]:
            val = params.get(key,"")
            if val: parts.append(f"{lbl_txt.split('(')[0].strip()}: {val}")
        return "  ·  ".join(parts)

    def _build_params(self, layout):
        defn   = STEP_TYPES.get(self._data["type"],{}).get("params",[])
        params = self._data.get("params",{})
        grid   = QGridLayout(); grid.setSpacing(6)
        COLS   = 3
        for i,(key,lbl_txt,default) in enumerate(defn):
            col_f = QFrame(); col_f.setStyleSheet("QFrame{background:transparent;border:none;}")
            cv = QVBoxLayout(col_f); cv.setContentsMargins(0,0,0,0); cv.setSpacing(2)
            cv.addWidget(lbl(lbl_txt,"#64748b",9,True))
            val = params.get(key, default)
            if key in SELECT_PARAMS:
                w = _field_combo(SELECT_PARAMS[key], val)
                w.currentTextChanged.connect(lambda v,k=key: self._on_param(k,v))
            else:
                w = _field_input(val)
                w.textChanged.connect(lambda v,k=key: self._on_param(k,v))
            self._param_widgets[key] = w
            cv.addWidget(w)
            grid.addWidget(col_f, i//COLS, i%COLS)
        layout.addLayout(grid)

        # Apply button
        apply_btn = _btn("Apply","#4a9eff",h=24)
        apply_btn.clicked.connect(self._apply_params)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(apply_btn)
        layout.addLayout(row)

    def _on_param(self, key, val):
        self._data["params"][key] = val

    def _apply_params(self):
        self._param_lbl.setText(self._param_summary())
        self.setStyleSheet(
            "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:5px;}")

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._param_frame.setVisible(self._expanded)
        if self._expanded:
            self.setStyleSheet(
                "QFrame{background:#16191f;border:1px solid #4a9eff;border-radius:5px;}")
        else:
            self.setStyleSheet(
                "QFrame{background:#16191f;border:1px solid #3a4055;border-radius:5px;}")

    def update_index(self, idx):
        self._idx = idx
        # update num label
        self.findChild(QLabel).setText(f"{idx+1:02d}")


# ══════════════════════════════════════════════
# Recipe Editor (right panel)
# ══════════════════════════════════════════════

class RecipeEditor(QFrame):
    recipe_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._recipe = None
        self._load_to_process_fn = None
        self._step_rows = []
        self.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame{background:#16191f;border:none;border-bottom:1px solid #3a4055;"
            "border-radius:6px 6px 0 0;}")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(12,8,12,8); hh.setSpacing(8)
        self._title_lbl = QLabel("— Select a recipe —")
        self._title_lbl.setFont(QFont("Segoe UI",13,600))
        self._title_lbl.setStyleSheet("color:#e2e8f0;background:transparent;")
        eng_badge = QLabel("Engineer")
        eng_badge.setStyleSheet(
            "color:#4a9eff;background:#1e2d47;border:1px solid #4a9eff;"
            "border-radius:10px;padding:1px 8px;font-size:10px;")
        self._dup_btn = _btn("Duplicate","#94a3b8",h=26)
        self._dup_btn.clicked.connect(self._duplicate)
        self._save_btn = _btn("💾 Save","#22c55e",h=26)
        self._save_btn.clicked.connect(self._save)
        self._del_btn  = _btn("Delete","#ef4444",h=26)
        self._del_btn.clicked.connect(self._delete)
        hh.addWidget(self._title_lbl,1); hh.addWidget(eng_badge)
        hh.addWidget(self._dup_btn); hh.addWidget(self._save_btn); hh.addWidget(self._del_btn)
        v.addWidget(hdr)

        # Body scroll
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{width:6px;background:#16191f;}"
            "QScrollBar::handle:vertical{background:#3a4055;border-radius:3px;}")
        inner = QWidget(); inner.setStyleSheet("background:transparent;")
        self._body = QVBoxLayout(inner)
        self._body.setContentsMargins(12,10,12,10); self._body.setSpacing(8)

        # Meta
        self._build_meta()
        self._body.addWidget(divider())
        self._build_steps_header()
        self._steps_container = QVBoxLayout()
        self._steps_container.setSpacing(4)
        self._body.addLayout(self._steps_container)
        self._body.addStretch()

        scroll.setWidget(inner); v.addWidget(scroll,1)

        # Footer
        ftr = QFrame()
        ftr.setStyleSheet(
            "QFrame{background:#16191f;border:none;border-top:1px solid #3a4055;"
            "border-radius:0 0 6px 6px;}")
        fh = QHBoxLayout(ftr); fh.setContentsMargins(12,7,12,7); fh.setSpacing(8)
        self._ts_lbl = lbl("No recipe loaded","#64748b",10)
        load_btn = _btn("▶ Load to Process","#eab308",h=28)
        load_btn.clicked.connect(self._load_to_process)
        fh.addWidget(self._ts_lbl,1); fh.addWidget(load_btn)
        v.addWidget(ftr)

        self._set_enabled(False)

    def _build_meta(self):
        grid = QGridLayout(); grid.setSpacing(8)
        fields = [
            ("_name_e",    "RECIPE NAME",  ""),
            ("_prod_e",    "PRODUCT ID",   ""),
            ("_ver_e",     "VERSION",      "1.0"),
            ("_desc_e",    "DESCRIPTION",  ""),
        ]
        for i,(attr,lbl_txt,default) in enumerate(fields):
            f = QFrame(); f.setStyleSheet("QFrame{background:transparent;border:none;}")
            fv = QVBoxLayout(f); fv.setContentsMargins(0,0,0,0); fv.setSpacing(2)
            fv.addWidget(lbl(lbl_txt,"#64748b",9,True))
            e = _field_input(default)
            e.textChanged.connect(self._on_meta_changed)
            setattr(self,attr,e); fv.addWidget(e)
            grid.addWidget(f, i//2, i%2)
        self._body.addLayout(grid)

    def _build_steps_header(self):
        row = QHBoxLayout(); row.setSpacing(6)
        row.addWidget(lbl("STEPS","#64748b",9,True))
        row.addStretch()
        add_btn = _btn("＋ Add Step","#94a3b8",h=24)
        add_btn.clicked.connect(self._add_step)
        row.addWidget(add_btn)
        self._body.addLayout(row)

    # ── Set recipe ────────────────────────────
    def set_recipe(self, recipe):
        self._recipe = recipe
        self._set_enabled(True)
        self._title_lbl.setText(recipe.get("name","Untitled"))
        self._name_e.setText(recipe.get("name",""))
        self._prod_e.setText(recipe.get("product_id",""))
        self._ver_e.setText(recipe.get("version","1.0"))
        self._desc_e.setText(recipe.get("description",""))
        ts = recipe.get("modified","—")
        self._ts_lbl.setText(f"Last saved: {ts}")
        self._rebuild_steps()

    def _set_enabled(self, on):
        for w in [self._dup_btn,self._save_btn,self._del_btn,
                  self._name_e,self._prod_e,self._ver_e,self._desc_e]:
            w.setEnabled(on)

    def _on_meta_changed(self):
        if not self._recipe: return
        self._recipe["name"]        = self._name_e.text()
        self._recipe["product_id"]  = self._prod_e.text()
        self._recipe["version"]     = self._ver_e.text()
        self._recipe["description"] = self._desc_e.text()
        self._title_lbl.setText(self._recipe["name"] or "Untitled")
        self.recipe_changed.emit()

    # ── Steps ─────────────────────────────────
    def _rebuild_steps(self):
        for r in self._step_rows:
            self._steps_container.removeWidget(r); r.deleteLater()
        self._step_rows.clear()
        if not self._recipe: return
        for i, step in enumerate(self._recipe.get("steps",[])):
            self._add_step_row(i, step)

    def _add_step_row(self, idx, step_data):
        row = StepRow(idx, step_data)
        row.edit_requested.connect(self._on_edit)
        row.delete_requested.connect(self._on_delete_step)
        row.move_up.connect(self._on_move_up)
        row.move_down.connect(self._on_move_down)
        row.enabled_changed.connect(self._on_enabled)
        self._steps_container.addWidget(row)
        self._step_rows.append(row)

    def _add_step(self):
        if not self._recipe: return
        items = list(STEP_TYPES.keys())
        dlg = QDialog(self); dlg.setWindowTitle("Add Step"); dlg.setFixedSize(280,360)
        v = QVBoxLayout(dlg)
        v.addWidget(lbl("Select step type:","#94a3b8",12))
        from PyQt6.QtWidgets import QListWidget
        lst = QListWidget()
        lst.setStyleSheet(
            "QListWidget{background:#20242e;border:1px solid #3a4055;color:#e2e8f0;"
            "font-size:12px;}"
            "QListWidget::item{padding:6px 10px;}"
            "QListWidget::item:selected{background:#1e2d47;color:#4a9eff;}")
        for item in items:
            icon = STEP_TYPES[item].get("icon","?")
            lst.addItem(f"{icon}  {item}")
        lst.setCurrentRow(0)
        v.addWidget(lst)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec():
            step_type = items[lst.currentRow()]
            step = _default_step(step_type)
            self._recipe["steps"].append(step)
            idx = len(self._recipe["steps"])-1
            self._add_step_row(idx, step)
            self.recipe_changed.emit()

    def _on_edit(self, idx): pass  # handled by StepRow toggle

    def _on_delete_step(self, idx):
        if not self._recipe: return
        if 0 <= idx < len(self._recipe["steps"]):
            self._recipe["steps"].pop(idx)
            self._rebuild_steps()
            self.recipe_changed.emit()

    def _on_move_up(self, idx):
        if not self._recipe or idx == 0: return
        steps = self._recipe["steps"]
        steps[idx-1], steps[idx] = steps[idx], steps[idx-1]
        self._rebuild_steps(); self.recipe_changed.emit()

    def _on_move_down(self, idx):
        if not self._recipe: return
        steps = self._recipe["steps"]
        if idx >= len(steps)-1: return
        steps[idx], steps[idx+1] = steps[idx+1], steps[idx]
        self._rebuild_steps(); self.recipe_changed.emit()

    def _on_enabled(self, idx, state):
        if not self._recipe: return
        if 0 <= idx < len(self._recipe["steps"]):
            self._recipe["steps"][idx]["enabled"] = state

    def _save(self):
        if not self._recipe: return
        self._recipe["modified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self._ts_lbl.setText(f"Last saved: {self._recipe['modified']}")
        self.recipe_changed.emit()

    def _duplicate(self):
        if not self._recipe: return
        new = copy.deepcopy(self._recipe)
        new["name"] += " (copy)"
        new["modified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.recipe_changed.emit()
        return new

    def _delete(self):
        if not self._recipe: return
        reply = QMessageBox.question(
            self, "Delete Recipe",
            f"Delete '{self._recipe['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._recipe["_delete"] = True
            self.recipe_changed.emit()

    def _load_to_process(self):
        if not self._recipe: return
        self._save()
        # ส่ง recipe ไปหน้า Process
        if hasattr(self, '_load_to_process_fn') and self._load_to_process_fn:
            self._load_to_process_fn(self._recipe)


# ══════════════════════════════════════════════
# Recipe List (left panel)
# ══════════════════════════════════════════════

class RecipeList(QFrame):
    selected = pyqtSignal(int)
    new_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._items = []
        self._active = -1
        self.setStyleSheet(
            "QFrame{background:#20242e;border:1px solid #3a4055;border-radius:6px;}")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame{background:#16191f;border:none;border-bottom:1px solid #3a4055;"
            "border-radius:6px 6px 0 0;}")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(12,8,12,8); hh.setSpacing(6)
        t = QLabel("📋 Recipes"); t.setFont(QFont("Segoe UI",11,600))
        t.setStyleSheet("color:#e2e8f0;background:transparent;")
        self._count_lbl = lbl("0","#64748b",9)
        hh.addWidget(t,1); hh.addWidget(self._count_lbl)
        v.addWidget(hdr)

        # List scroll
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._inner = QWidget(); self._inner.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._inner)
        self._list_layout.setContentsMargins(0,0,0,0); self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        scroll.setWidget(self._inner); v.addWidget(scroll,1)

        # Add button
        add = QFrame()
        add.setStyleSheet(
            "QFrame{background:transparent;border:none;"
            "border-top:1px dashed #3a4055;}")
        ah = QHBoxLayout(add); ah.setContentsMargins(12,8,12,8)
        add_btn = QPushButton("＋  New Recipe")
        add_btn.setFixedHeight(36)
        add_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "color:#64748b;font-size:11px;text-align:left;padding-left:12px;}"
            "QPushButton:hover{color:#22c55e;background:#2a2f3d;}")
        add_btn.clicked.connect(self.new_requested.emit)
        ah.addWidget(add_btn)
        v.addWidget(add)

    def rebuild(self, recipes, active_idx=-1):
        self._active = active_idx
        # Clear
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._count_lbl.setText(f"{len(recipes)}")
        for i, r in enumerate(recipes):
            self._list_layout.insertWidget(i, self._make_item(i, r, i==active_idx))

    def _make_item(self, idx, r, active):
        # ใช้ QPushButton ครอบ ทำ click ได้แน่นอน
        btn = QPushButton()
        btn.setFlat(True)
        border = "border-left:3px solid #4a9eff;" if active else "border-left:3px solid transparent;"
        bg = "#1e2d47" if active else "transparent"
        btn.setStyleSheet(f"""
            QPushButton{{
                background:{bg};{border}
                border-bottom:1px solid #3a4055;
                border-top:none;border-right:none;
                text-align:left;padding:8px 10px;
            }}
            QPushButton:hover{{background:#2a2f3d;}}
        """)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _,i=idx: self.selected.emit(i))

        # ใช้ layout ใน widget ที่ crop ลงใน button
        inner = QWidget(); inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.setStyleSheet("background:transparent;")
        # Sek แก้ความสูงทับ Font
        v = QVBoxLayout(inner); v.setContentsMargins(0,0,0,0); v.setSpacing(4)
        btn.setMinimumHeight(64)
        name_lbl = QLabel(r.get("name","Untitled"))
        name_lbl.setFont(QFont("Segoe UI",11,600))
        name_lbl.setStyleSheet(f"color:{'#4a9eff' if active else '#e2e8f0'};background:transparent;")
        prod_lbl = QLabel(f"Product: {r.get('product_id','—')}")
        prod_lbl.setStyleSheet("color:#64748b;font-size:10px;background:transparent;")
        n_steps = len(r.get("steps",[]))
        mod = r.get("modified","—")
        info_lbl = QLabel(f"{n_steps} steps · {mod}")
        info_lbl.setStyleSheet("color:#64748b;font-size:9px;background:transparent;")
        v.addWidget(name_lbl); v.addWidget(prod_lbl); v.addWidget(info_lbl)

        bl = QVBoxLayout(btn); bl.setContentsMargins(0,0,0,0)
        bl.addWidget(inner)
        return btn


# ══════════════════════════════════════════════
# Recipe Page
# ══════════════════════════════════════════════

class RecipePage(QWidget):
    def __init__(self):
        super().__init__()
        self._recipes = _load_recipes()
        self._active  = 0 if self._recipes else -1

        root = QHBoxLayout(self)
        root.setContentsMargins(12,12,12,12); root.setSpacing(10)

        # Left list
        self._list = RecipeList()
        self._list.setFixedWidth(220)
        self._list.selected.connect(self._select)
        self._list.new_requested.connect(self._new_recipe)
        root.addWidget(self._list)

        # Right editor
        self._editor = RecipeEditor()
        self._editor.recipe_changed.connect(self._on_changed)
        root.addWidget(self._editor,1)

        self._refresh()
        if self._recipes:
            self._select(0)

    def _refresh(self):
        self._list.rebuild(self._recipes, self._active)

    def _select(self, idx):
        self._active = idx
        self._refresh()
        if 0 <= idx < len(self._recipes):
            self._editor.set_recipe(self._recipes[idx])

    def _new_recipe(self):
        new = {
            "name":        "New Recipe",
            "product_id":  "",
            "version":     "1.0",
            "description": "",
            "modified":    datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "steps":       [],
        }
        self._recipes.append(new)
        self._active = len(self._recipes)-1
        self._refresh()
        self._editor.set_recipe(new)
        _save_recipes(self._recipes)

    def _on_changed(self):
        # check delete flag
        if self._active >= 0 and self._active < len(self._recipes):
            r = self._recipes[self._active]
            if r.get("_delete"):
                self._recipes.pop(self._active)
                self._active = max(0, self._active-1)
                self._refresh()
                if self._recipes:
                    self._editor.set_recipe(self._recipes[self._active])
                else:
                    self._editor.set_recipe(None)
                _save_recipes(self._recipes)
                return
        _save_recipes(self._recipes)
        self._refresh()
