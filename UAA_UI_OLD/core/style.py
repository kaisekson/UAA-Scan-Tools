STYLE = """
QMainWindow, QWidget {
    background-color: #111318;
    color: #c5cdd9;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QLabel  { color: #c5cdd9; }
QLineEdit {
    background: #0d0f14;
    border: 1px solid #1e2433;
    border-radius: 4px;
    color: #c5cdd9;
    padding: 5px 8px;
    font-size: 13px;
}
QLineEdit:focus { border: 1px solid #4a9eff; }
QPushButton {
    background: #1a1f2e;
    border: 1px solid #1e2433;
    border-radius: 5px;
    color: #8892a4;
    padding: 6px 14px;
    font-size: 12px;
}
QPushButton:hover  { border-color: #4a9eff; color: #4a9eff; background: #0d1520; }
QPushButton:pressed { background: #0a0c10; }
QTabWidget::pane   { border: 1px solid #1e2433; background: #111318; }
QTabBar::tab {
    background: #0d0f14; color: #4a5568;
    padding: 8px 20px; border: 1px solid #1e2433;
    font-size: 12px;
}
QTabBar::tab:selected { background: #111318; color: #4a9eff; border-bottom: 2px solid #4a9eff; }
QScrollArea  { border: none; background: #111318; }
QStatusBar   { background: #0a0c10; color: #2a3444; font-size: 11px; border-top: 1px solid #1e2433; }
"""
