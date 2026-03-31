"""
Power Supply Panel — Multi PSU (สูงสุด 4 ตัว)
================================================
- แต่ละตัวเลือก model ได้อิสระ (E36103B=1ch, E36441A=4ch)
- กด + tab เพิ่ม PSU ได้ถึง 4 ตัว
- Connect, ON/OFF per channel, Readback V/I
- แสดงรูปอุปกรณ์จาก assets/instruments/
"""

import socket, time, os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QFrame, QTabWidget, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from core.widgets import lbl, divider

MAX_PSU = 4

MODELS = {
    "E36103B": {"brand":"Keysight","channels":1,"v_max":20.0,"i_max":3.0, "image":"assets/instruments/e36103b.png"},
    "E36105B": {"brand":"Keysight","channels":1,"v_max":35.0,"i_max":1.5, "image":"assets/instruments/e36103b.png"},
    "E36106B": {"brand":"Keysight","channels":1,"v_max":60.0,"i_max":1.0, "image":"assets/instruments/e36103b.png"},
    "E36231A": {"brand":"Keysight","channels":2,"v_max":25.0,"i_max":1.0, "image":""},
    "E36311A": {"brand":"Keysight","channels":3,"v_max":25.0,"i_max":1.0, "image":""},
    "E36441A": {"brand":"Keysight","channels":4,"v_max":20.0,"i_max":1.0, "image":"assets/instruments/e36441a.png"},
}


class PSUDriver:
    def __init__(self, ip, port=5025, timeout=3.0):
        self.ip=ip; self.port=port; self.timeout=timeout; self._sock=None

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.ip, self.port)); time.sleep(0.1)

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    def send(self, cmd):
        self._sock.sendall((cmd+"\n").encode()); time.sleep(0.05)

    def query(self, cmd):
        self._sock.sendall((cmd+"\n").encode()); time.sleep(0.05)
        data=b""
        self._sock.settimeout(self.timeout)
        try:
            while True:
                chunk=self._sock.recv(4096); data+=chunk
                if data.endswith(b"\n"): break
        except socket.timeout: pass
        return data.decode().strip()

    def idn(self):               return self.query("*IDN?")
    def set_voltage(self,ch,v):  self.send(f"INST:NSEL {ch}"); self.send(f"VOLT {v}")
    def set_current(self,ch,i):  self.send(f"INST:NSEL {ch}"); self.send(f"CURR {i}")
    def output_on(self,ch):      self.send(f"INST:NSEL {ch}"); self.send("OUTP ON")
    def output_off(self,ch):     self.send(f"INST:NSEL {ch}"); self.send("OUTP OFF")
    def measure_v(self,ch):      self.send(f"INST:NSEL {ch}"); return float(self.query("MEAS:VOLT?"))
    def measure_i(self,ch):      self.send(f"INST:NSEL {ch}"); return float(self.query("MEAS:CURR?"))


class ConnectWorker(QThread):
    success = pyqtSignal(str)
    failed  = pyqtSignal(str)
    def __init__(self,ip,port,timeout):
        super().__init__(); self.ip=ip; self.port=port; self.timeout=timeout
    def run(self):
        try:
            drv=PSUDriver(self.ip,self.port,self.timeout); drv.connect()
            idn=drv.idn(); drv.disconnect(); self.success.emit(idn)
        except Exception as e: self.failed.emit(str(e))


class ChannelRow(QFrame):
    def __init__(self, ch, drv_ref):
        super().__init__()
        self._ch=ch; self._drv=drv_ref; self._on=False
        self.setStyleSheet("QFrame{background:#0a0c10;border:1px solid #1e2433;border-radius:6px;}")
        row=QHBoxLayout(self); row.setContentsMargins(12,8,12,8); row.setSpacing(12)

        row.addWidget(lbl(f"CH {ch}","#4a9eff",12,True))
        row.addWidget(self._vl())

        for attr,label_txt,color in [("v_edit","Set V","#3b82f6"),("i_edit","Set I (A)","#22c55e")]:
            col=QVBoxLayout(); col.setSpacing(2)
            col.addWidget(lbl(label_txt,"#4a5568",9))
            e=QLineEdit("0.00"); e.setFixedWidth(72)
            e.setStyleSheet(f"border-left:2px solid {color};background:#111318;"
                "border-top:1px solid #1e2433;border-right:1px solid #1e2433;"
                "border-bottom:1px solid #1e2433;border-radius:4px;"
                "color:#c5cdd9;padding:4px 6px;font-size:12px;")
            setattr(self,attr,e); col.addWidget(e); row.addLayout(col)

        row.addWidget(self._vl())

        for attr,label_txt,color in [("rv","Read V","#4a9eff"),("ri","Read I","#22c55e")]:
            col=QVBoxLayout(); col.setSpacing(2)
            col.addWidget(lbl(label_txt,"#4a5568",9))
            w=lbl("—",color,13,True); setattr(self,attr,w)
            col.addWidget(w); row.addLayout(col)

        row.addStretch()

        self.apply_btn=QPushButton("Apply"); self.apply_btn.setFixedSize(64,30)
        self.apply_btn.setEnabled(False); self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn)

        self.onoff_btn=QPushButton("OFF"); self.onoff_btn.setFixedSize(56,30)
        self.onoff_btn.setEnabled(False); self.onoff_btn.clicked.connect(self._toggle)
        self._set_style(False); row.addWidget(self.onoff_btn)

    def _vl(self):
        f=QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet("color:#1e2433;"); f.setFixedWidth(1); return f

    def _set_style(self,on):
        if on:
            self.onoff_btn.setText("ON")
            self.onoff_btn.setStyleSheet(
                "QPushButton{background:#1a3a1a;border:1px solid #22c55e;"
                "border-radius:5px;color:#22c55e;font-weight:600;}"
                "QPushButton:hover{background:#22c55e;color:#000;}")
        else:
            self.onoff_btn.setText("OFF")
            self.onoff_btn.setStyleSheet(
                "QPushButton{background:#1a0000;border:1px solid #3d0a0a;"
                "border-radius:5px;color:#4a5568;font-weight:600;}"
                "QPushButton:hover{background:#3d0a0a;color:#ef4444;}")

    def set_connected(self,ok):
        self.apply_btn.setEnabled(ok); self.onoff_btn.setEnabled(ok)
        if not ok:
            self.rv.setText("—"); self.ri.setText("—")
            self._on=False; self._set_style(False)

    def _toggle(self):
        drv=self._drv[0]
        if not drv: return
        try:
            if self._on: drv.output_off(self._ch); self._on=False
            else:        drv.output_on(self._ch);  self._on=True
            self._set_style(self._on)
        except Exception as e: print(f"[PSU ch{self._ch}] toggle: {e}")

    def _apply(self):
        drv=self._drv[0]
        if not drv: return
        try:
            drv.set_voltage(self._ch,float(self.v_edit.text()))
            drv.set_current(self._ch,float(self.i_edit.text()))
        except Exception as e: print(f"[PSU ch{self._ch}] apply: {e}")

    def update_readback(self):
        drv=self._drv[0]
        if not drv or not self._on: return
        try:
            self.rv.setText(f"{drv.measure_v(self._ch):.3f} V")
            self.ri.setText(f"{drv.measure_i(self._ch):.4f} A")
        except: pass


class SinglePSUWidget(QWidget):
    def __init__(self, index):
        super().__init__()
        self._drv=[None]; self._ch_rows=[]; self._index=index
        layout=QVBoxLayout(self); layout.setContentsMargins(16,14,16,14); layout.setSpacing(12)

        # Top: image + config
        top=QHBoxLayout(); top.setSpacing(16)
        self.img_lbl=QLabel("No image"); self.img_lbl.setFixedSize(180,110)
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setStyleSheet("background:#0a0c10;border:1px solid #1e2433;border-radius:6px;color:#2a3444;font-size:12px;")
        top.addWidget(self.img_lbl)

        grid=QGridLayout(); grid.setSpacing(8); grid.setColumnStretch(1,1)

        grid.addWidget(lbl("Model","#4a5568",10),0,0)
        self.model_cb=QComboBox()
        self.model_cb.addItems(list(MODELS.keys()))
        self.model_cb.setStyleSheet("QComboBox{background:#0d0f14;border:1px solid #1e2433;border-radius:4px;color:#c5cdd9;padding:5px 8px;font-size:13px;}"
            "QComboBox::drop-down{border:none;}"
            "QComboBox QAbstractItemView{background:#0d0f14;border:1px solid #1e2433;color:#c5cdd9;}")
        self.model_cb.currentTextChanged.connect(self._on_model)
        grid.addWidget(self.model_cb,0,1)

        grid.addWidget(lbl("Brand","#4a5568",10),1,0)
        self.brand_lbl=lbl("Keysight","#8892a4",12); grid.addWidget(self.brand_lbl,1,1)

        grid.addWidget(lbl("IP Address","#4a5568",10),2,0)
        self.ip_edit=QLineEdit(); self.ip_edit.setPlaceholderText("e.g. 192.168.1.20")
        grid.addWidget(self.ip_edit,2,1)

        pt=QHBoxLayout()
        self.port_edit=QLineEdit("5025"); self.port_edit.setFixedWidth(70)
        self.tmo_edit=QLineEdit("3");     self.tmo_edit.setFixedWidth(50)
        pt.addWidget(self.port_edit)
        pt.addWidget(lbl("Timeout (s)","#4a5568",10))
        pt.addWidget(self.tmo_edit); pt.addStretch()
        grid.addWidget(lbl("Port","#4a5568",10),3,0)
        grid.addLayout(pt,3,1)

        top.addLayout(grid,1); layout.addLayout(top)
        layout.addWidget(divider())

        # Connection
        conn=QHBoxLayout(); conn.setSpacing(12)
        self.conn_btn=QPushButton("⟳  Connect"); self.conn_btn.setFixedHeight(32)
        self.conn_btn.setStyleSheet("QPushButton{background:#0d1520;border:1px solid #4a9eff;border-radius:5px;color:#4a9eff;font-size:12px;font-weight:600;padding:0 16px;}"
            "QPushButton:hover{background:#4a9eff;color:#000;}"
            "QPushButton:disabled{border-color:#1e2433;color:#2a3444;background:#0a0c10;}")
        self.conn_btn.clicked.connect(self._connect)
        # Remove button
        self.remove_btn=QPushButton("✕  Remove"); self.remove_btn.setFixedHeight(32)
        self.remove_btn.setStyleSheet("QPushButton{background:#1a0000;border:1px solid #3d0a0a;border-radius:5px;color:#4a5568;font-size:12px;padding:0 12px;}"
            "QPushButton:hover{background:#3d0a0a;color:#ef4444;border-color:#ef4444;}")
        self.remove_btn.clicked.connect(self._remove)
        conn.addWidget(self.remove_btn)
        self.status_lbl=lbl("○  Disconnected","#4a5568",12)
        self.idn_lbl=lbl("IDN: —","#2a3444",11)
        conn.addWidget(self.conn_btn); conn.addWidget(self.status_lbl)
        conn.addStretch(); conn.addWidget(self.idn_lbl)
        layout.addLayout(conn); layout.addWidget(divider())
        self._remove_cb = None   # callback จาก parent

        # Channels
        layout.addWidget(lbl("CHANNELS","#4a5568",10,True))
        self.ch_layout=QVBoxLayout(); self.ch_layout.setSpacing(6)
        layout.addLayout(self.ch_layout); layout.addStretch()

        self._timer=QTimer(self); self._timer.timeout.connect(self._readback); self._timer.start(1000)
        self._on_model(self.model_cb.currentText())

    def set_remove_callback(self, cb):
        self._remove_cb = cb

    def _on_model(self,model):
        info=MODELS.get(model,{})
        self.brand_lbl.setText(info.get("brand","—"))
        img=info.get("image","")
        if img and os.path.exists(img):
            px=QPixmap(img).scaled(178,108,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self.img_lbl.setPixmap(px); self.img_lbl.setText("")
        else:
            self.img_lbl.setPixmap(QPixmap()); self.img_lbl.setText(f"[ {model} ]")
        while self.ch_layout.count():
            w=self.ch_layout.takeAt(0).widget()
            if w: w.deleteLater()
        self._ch_rows.clear()
        for ch in range(1,info.get("channels",1)+1):
            row=ChannelRow(ch,self._drv); self._ch_rows.append(row); self.ch_layout.addWidget(row)

    def _remove(self):
        if self._remove_cb:
            self._remove_cb()

    def _connect(self):
        ip=self.ip_edit.text().strip()
        if not ip:
            self.status_lbl.setText("✗  Enter IP"); self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;"); return
        self.conn_btn.setEnabled(False)
        self.status_lbl.setText("○  Connecting..."); self.status_lbl.setStyleSheet("color:#eab308;font-size:12px;")
        self._worker=ConnectWorker(ip,int(self.port_edit.text() or 5025),float(self.tmo_edit.text() or 3))
        self._worker.success.connect(self._on_ok); self._worker.failed.connect(self._on_fail); self._worker.start()

    def _on_ok(self,idn):
        ip=self.ip_edit.text().strip()
        drv=PSUDriver(ip,int(self.port_edit.text() or 5025),float(self.tmo_edit.text() or 3))
        try: drv.connect(); self._drv[0]=drv
        except: pass
        self.status_lbl.setText("●  Connected"); self.status_lbl.setStyleSheet("color:#22c55e;font-size:12px;font-weight:600;")
        self.idn_lbl.setText(f"IDN: {idn}"); self.idn_lbl.setStyleSheet("color:#8892a4;font-size:11px;")
        self.conn_btn.setText("✗  Disconnect"); self.conn_btn.setEnabled(True)
        self.conn_btn.clicked.disconnect(); self.conn_btn.clicked.connect(self._disconnect)
        for r in self._ch_rows: r.set_connected(True)

    def _on_fail(self,err):
        self.status_lbl.setText(f"✗  {err}"); self.status_lbl.setStyleSheet("color:#ef4444;font-size:12px;")
        self.conn_btn.setEnabled(True); self._drv[0]=None

    def _disconnect(self):
        if self._drv[0]:
            try: self._drv[0].disconnect()
            except: pass
            self._drv[0]=None
        for r in self._ch_rows: r.set_connected(False)
        self.status_lbl.setText("○  Disconnected"); self.status_lbl.setStyleSheet("color:#4a5568;font-size:12px;")
        self.idn_lbl.setText("IDN: —")
        self.conn_btn.setText("⟳  Connect")
        self.conn_btn.clicked.disconnect(); self.conn_btn.clicked.connect(self._connect)

    def _readback(self):
        for r in self._ch_rows: r.update_readback()


class PowerSupplyPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._count=0
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)

        self.tabs=QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane{border:none;background:#111318;}
            QTabBar::tab{background:#0d0f14;color:#4a5568;padding:8px 20px;border:1px solid #1e2433;font-size:12px;min-width:80px;}
            QTabBar::tab:selected{background:#111318;color:#4a9eff;border-bottom:2px solid #4a9eff;}
            QTabBar::tab:hover{color:#8892a4;}
        """)
        self.tabs.tabBarClicked.connect(self._tab_clicked)
        layout.addWidget(self.tabs)

        self._add_psu()   # เริ่มด้วย PSU 1 เสมอ
        self._refresh_add_tab()

    def _add_psu(self):
        if self._count >= MAX_PSU: return
        self._count += 1
        psu_widget = SinglePSUWidget(self._count)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#111318;")
        scroll.setWidget(psu_widget)
        # แทรกก่อน + tab
        insert_at = self.tabs.count()
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "＋":
                insert_at = i; break
        tab_name = f"PSU {self._count}"
        psu_widget.set_remove_callback(lambda tn=tab_name: self._remove_psu(
            next((j for j in range(self.tabs.count()) if self.tabs.tabText(j)==tn), -1)
        ))
        self.tabs.insertTab(insert_at, scroll, tab_name)
        self.tabs.setCurrentIndex(insert_at)

    def _refresh_add_tab(self):
        # ลบ + tab เก่า
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "＋":
                self.tabs.removeTab(i); break
        # เพิ่มใหม่ถ้ายังไม่ครบ
        if self._count < MAX_PSU:
            self.tabs.addTab(QWidget(), "＋")

    def _tab_clicked(self, idx):
        if self.tabs.tabText(idx) == "＋":
            self._add_psu()
            self._refresh_add_tab()

    def _remove_psu(self, idx):
        if self._count <= 1:
            return   # ต้องมีอย่างน้อย 1 ตัว
        self.tabs.removeTab(idx)
        self._count -= 1
        # rename tabs ให้ถูกต้อง
        n = 1
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) != "＋":
                self.tabs.setTabText(i, f"PSU {n}")
                n += 1
        self._refresh_add_tab()

    def _remove_psu(self, idx):
        if self._count <= 1:
            return   # ต้องมีอย่างน้อย 1 ตัว
        self.tabs.removeTab(idx)
        self._count -= 1
        # rename tabs ให้ถูกต้อง
        n = 1
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) != "＋":
                self.tabs.setTabText(i, f"PSU {n}")
                n += 1
        self._refresh_add_tab()
