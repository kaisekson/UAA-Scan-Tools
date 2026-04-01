from PyQt6.QtWidgets import QLabel, QFrame, QPushButton, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt


def lbl(text, color="#c5cdd9", size=13, bold=False):
    w = QLabel(text)
    w.setStyleSheet(
        f"color:{color}; font-size:{size}px;"
        + (" font-weight:600;" if bold else "")
    )
    return w


def divider():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("background:#1e2433; border:none; max-height:1px;")
    line.setFixedHeight(1)
    return line


class SidebarIcon(QPushButton):
    """Icon-only sidebar button"""
    def __init__(self, icon, tooltip, color="#4a9eff"):
        super().__init__(icon)
        self.setToolTip(tooltip)
        self.setFixedSize(44, 44)
        self.setCheckable(True)
        self._color = color
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #4a5568;
                font-size: 18px;
            }}
            QPushButton:hover  {{ background: #1e2433; color: #8892a4; }}
            QPushButton:checked {{
                background: #0d1520;
                color: {color};
                border: 1px solid #1a2744;
            }}
        """)


class MenuCard(QPushButton):
    def __init__(self, icon, title, subtitle, color="#4a9eff", enabled=True):
        super().__init__()
        self.setFixedHeight(68)
        self.setEnabled(enabled)
        self.setStyleSheet(f"""
            QPushButton {{
                background: #0d0f14;
                border: 1px solid #1e2433;
                border-radius: 6px;
                text-align: left;
                padding: 0 14px;
            }}
            QPushButton:hover  {{ border-color: {color}; background: {color}0d; }}
            QPushButton:disabled {{ opacity: 0.3; }}
        """)
        layout = QVBoxLayout(self)  # dummy — draw via labels
        layout.setContentsMargins(0, 0, 0, 0)

        from PyQt6.QtWidgets import QHBoxLayout
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(12)

        ico = QLabel(icon)
        ico.setFixedSize(36, 36)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(f"font-size:18px; background:{color}18; border-radius:6px;")

        txt_w = QWidget()
        txt_w.setStyleSheet("background:transparent;")
        tv = QVBoxLayout(txt_w)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(2)
        t1 = QLabel(title)
        t1.setStyleSheet("color:#c5cdd9; font-size:13px; font-weight:600; background:transparent;")
        t2 = QLabel(subtitle)
        t2.setStyleSheet("color:#4a5568; font-size:10px; background:transparent;")
        tv.addWidget(t1); tv.addWidget(t2)

        h.addWidget(ico)
        h.addWidget(txt_w)
        h.addStretch()
