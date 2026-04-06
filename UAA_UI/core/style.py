
# ── Color tokens ─────────────────────────────
# bg_page    = #1a1d24   main background (สว่างกว่าเดิม)
# bg_card    = #20242e   card / panel
# bg_input   = #2a2f3d   input field
# bg_hover   = #2e3447   hover state
# border     = #3a4055   border (ชัดขึ้น)
# text_main  = #e2e8f0   primary text (สว่างขึ้น)
# text_muted = #94a3b8   secondary text
# text_dim   = #64748b   dim/placeholder
# accent     = #4a9eff   blue accent

STYLE = """
QMainWindow, QWidget {
    background-color: #1a1d24;
    color: #e2e8f0;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QLabel { color: #e2e8f0; }
QLineEdit {
    background: #2a2f3d;
    border: 1px solid #3a4055;
    border-radius: 4px;
    color: #e2e8f0;
    padding: 5px 8px;
    font-size: 13px;
}
QLineEdit:focus  { border: 1px solid #4a9eff; }
QLineEdit:disabled { color: #64748b; background: #20242e; }
QPushButton {
    background: #252a38;
    border: 1px solid #3a4055;
    border-radius: 5px;
    color: #94a3b8;
    padding: 6px 14px;
    font-size: 12px;
}
QPushButton:hover   { border-color: #4a9eff; color: #4a9eff; background: #1e2d47; }
QPushButton:pressed { background: #161b2e; }
QPushButton:checked { background: #1e2d47; border-color: #4a9eff; color: #4a9eff; }
QPushButton:disabled { border-color: #3a4055; color: #3a4055; background: #1a1d24; }
QComboBox {
    background: #2a2f3d;
    border: 1px solid #3a4055;
    border-radius: 4px;
    color: #e2e8f0;
    padding: 4px 8px;
    font-size: 12px;
}
QComboBox::drop-down  { border: none; }
QComboBox QAbstractItemView {
    background: #20242e;
    border: 1px solid #3a4055;
    color: #e2e8f0;
    font-size: 12px;
    selection-background-color: #1e2d47;
}
QTabWidget::pane { border: 1px solid #3a4055; background: #1a1d24; }
QTabBar::tab {
    background: #20242e; color: #64748b;
    padding: 8px 20px;
    border: 1px solid #3a4055;
    font-size: 12px;
}
QTabBar::tab:selected {
    background: #1a1d24; color: #4a9eff;
    border-bottom: 2px solid #4a9eff;
}
QTabBar::tab:hover { color: #94a3b8; }
QScrollArea  { border: none; background: #1a1d24; }
QScrollBar:vertical {
    width: 6px; background: #20242e;
}
QScrollBar::handle:vertical {
    background: #3a4055; border-radius: 3px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #64748b; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTextEdit {
    background: #20242e;
    border: 1px solid #3a4055;
    border-radius: 4px;
    color: #e2e8f0;
    font-size: 12px;
}
QStatusBar {
    background: #14171e;
    color: #64748b;
    font-size: 11px;
    border-top: 1px solid #3a4055;
}
QDialog {
    background: #1a1d24;
}
QListWidget {
    background: #20242e;
    border: 1px solid #3a4055;
    color: #e2e8f0;
    font-size: 12px;
}
QListWidget::item:hover     { background: #252a38; }
QListWidget::item:selected  { background: #1e2d47; color: #4a9eff; }
QProgressBar {
    background: #2a2f3d;
    border-radius: 3px;
    border: none;
}
QProgressBar::chunk { background: #4a9eff; border-radius: 3px; }
"""
