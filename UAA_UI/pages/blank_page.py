from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
from core.widgets import lbl


class BlankPage(QWidget):
    def __init__(self, title, icon="🚧"):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        for text, color, size, bold in [
            (icon,                "#1e2433", 40, False),
            (title,               "#2a3444", 15, True),
            ("Under construction", "#1e2433", 11, False),
        ]:
            w = lbl(text, color, size, bold)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(w)
