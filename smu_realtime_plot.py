"""
Keithley 2602B — Source V=2V / Read I  (real-time plot)
========================================================
- Source voltage = 2V fixed
- อ่าน I ต่อเนื่อง real-time
- แสดงกราฟ I vs Time
- กด Ctrl+C หรือปิด window เพื่อหยุด

Requirements:
    pip install matplotlib
"""

import socket
import time
import threading
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════

SMU_IP       = "10.0.0.80"
SMU_PORT     = 5025
SMU_CHANNEL  = "a"
SOURCE_V     = 2.0          # V
CURRENT_LIMIT = 0.01        # 10mA compliance
NPLC          = 1.0
SAMPLE_INTERVAL = 0.1       # วินาที ระหว่าง sample
MAX_POINTS    = 300         # จำนวน point ที่แสดงบน graph

# ══════════════════════════════════════════════


class Keithley2602B:
    BUFFER_SIZE = 4096

    def __init__(self, host, port=5025, timeout=5.0):
        self.host     = host
        self.port     = port
        self._sock    = None
        self._ch      = "a"
        self._timeout = timeout

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self._timeout)
        self._sock.connect((self.host, self.port))
        time.sleep(0.2)
        self._sock.settimeout(0.5)
        try:
            self._sock.recv(self.BUFFER_SIZE)
        except socket.timeout:
            pass
        self._sock.settimeout(self._timeout)
        print(f"[SMU] Connected {self.host}:{self.port}")

    def disconnect(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def send(self, cmd):
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.02)

    def query(self, cmd):
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)
        data = b""
        self._sock.settimeout(self._timeout)
        try:
            while True:
                chunk = self._sock.recv(self.BUFFER_SIZE)
                data += chunk
                if data.endswith(b"\n"):
                    break
        except socket.timeout:
            pass
        return data.decode().strip()

    def reset(self):
        self.send("reset()")
        time.sleep(0.5)

    def setup_source_v(self, channel="a", voltage=2.0,
                       current_limit=0.01, nplc=1.0):
        self._ch = channel
        sm = f"smu{channel}"
        for cmd in [
            f"{sm}.reset()",
            f"{sm}.source.func        = {sm}.OUTPUT_DCVOLTS",
            f"{sm}.source.levelv      = {voltage}",
            f"{sm}.source.limiti      = {current_limit}",
            f"{sm}.source.autorangev  = {sm}.AUTORANGE_ON",
            f"{sm}.measure.nplc       = {nplc}",
            f"{sm}.measure.autorangei = {sm}.AUTORANGE_ON",
            f"{sm}.sense              = {sm}.SENSE_LOCAL",
            f"{sm}.measure.filter.count  = 4",
            f"{sm}.measure.filter.type   = {sm}.FILTER_MOVING_AVG",
            f"{sm}.measure.filter.enable = {sm}.FILTER_ON",
        ]:
            self.send(cmd)
        print(f"[SMU] Setup: V={voltage}V  Ilimit={current_limit*1e3:.1f}mA  NPLC={nplc}")

    def output_on(self):
        sm = f"smu{self._ch}"
        self.send(f"{sm}.source.output = {sm}.OUTPUT_ON")
        time.sleep(0.1)
        print("[SMU] Output ON")

    def output_off(self):
        sm = f"smu{self._ch}"
        self.send(f"{sm}.source.output = {sm}.OUTPUT_OFF")
        print("[SMU] Output OFF")

    def read_i(self):
        """อ่าน I เท่านั้น (เร็วกว่า iv())"""
        raw = self.query(f"print(smu{self._ch}.measure.i())")
        return float(raw)

    def is_compliance(self):
        raw = self.query(f"print(smu{self._ch}.source.compliance)")
        return raw.strip().lower() == "true"


# ══════════════════════════════════════════════
# Shared data
# ══════════════════════════════════════════════

class LiveData:
    def __init__(self, maxlen):
        self.lock       = threading.Lock()
        self.times      = deque(maxlen=maxlen)   # วินาทีจาก start
        self.currents   = deque(maxlen=maxlen)   # µA
        self.compliance = False
        self.done       = False
        self.last_i_ua  = 0.0


# ══════════════════════════════════════════════
# Measure thread
# ══════════════════════════════════════════════

def measure_thread_fn(data: LiveData):
    smu = Keithley2602B(SMU_IP, SMU_PORT)
    try:
        smu.connect()
        smu.reset()
        smu.setup_source_v(
            channel       = SMU_CHANNEL,
            voltage       = SOURCE_V,
            current_limit = CURRENT_LIMIT,
            nplc          = NPLC,
        )
        smu.output_on()

        t0 = time.time()
        print("[MEAS] Sampling... (ปิด window หรือ Ctrl+C เพื่อหยุด)")

        while not data.done:
            t_now = time.time() - t0
            i_a   = smu.read_i()
            i_ua  = i_a  # เก็บหน่วย A ดิบ แปลง unit ตอน plot
            comp  = smu.is_compliance()

            with data.lock:
                data.times.append(round(t_now, 3))
                data.currents.append(i_ua)   # A ดิบ
                data.compliance = comp
                data.last_i_ua  = i_ua

            if comp:
                print(f"  [!] COMPLIANCE at t={t_now:.1f}s  I={i_ua*1e6:.4f} µA")

            time.sleep(SAMPLE_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        if smu._sock is not None:
            try:
                smu.output_off()
            except Exception:
                pass
            smu.disconnect()

    with data.lock:
        data.done = True


# ══════════════════════════════════════════════
# Real-time plot
# ══════════════════════════════════════════════

def auto_unit(vals_a):
    """เลือก unit ที่เหมาะสมจาก list ค่า A"""
    if not vals_a:
        return 1e12, "pA"
    mx = max(abs(v) for v in vals_a)
    if mx >= 1e-3:   return 1e3,  "mA"
    if mx >= 1e-6:   return 1e6,  "µA"
    if mx >= 1e-9:   return 1e9,  "nA"
    return 1e12, "pA"

def run_plot(data: LiveData):
    fig = plt.figure(figsize=(13, 7), facecolor="#1e1e2e")
    fig.canvas.manager.set_window_title(f"SMU Real-time  —  V = {SOURCE_V}V")

    # Layout: digital display บน, กราฟล่าง
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 2.5], hspace=0.35)

    # ── Digital display panel ──────────────────────────────
    ax_disp = fig.add_subplot(gs[0])
    ax_disp.set_facecolor("#0d0d1a")
    ax_disp.set_xticks([])
    ax_disp.set_yticks([])
    for sp in ax_disp.spines.values():
        sp.set_edgecolor("#45475a")

    # Label เล็กบนซ้าย
    ax_disp.text(0.02, 0.82, "CURRENT", transform=ax_disp.transAxes,
                 color="#6c7086", fontsize=11, va="top", fontfamily="monospace")
    ax_disp.text(0.02, 0.55, f"V source = {SOURCE_V} V", transform=ax_disp.transAxes,
                 color="#6c7086", fontsize=9, va="top", fontfamily="monospace")

    # ตัวเลขใหญ่ (digital meter style)
    disp_val  = ax_disp.text(0.5, 0.52, "--- ---", transform=ax_disp.transAxes,
                              color="#00ff9f", fontsize=52, fontweight="bold",
                              ha="center", va="center", fontfamily="monospace")
    disp_unit = ax_disp.text(0.88, 0.52, "pA", transform=ax_disp.transAxes,
                              color="#00cc7a", fontsize=22, fontweight="bold",
                              ha="center", va="center", fontfamily="monospace")
    disp_status = ax_disp.text(0.98, 0.15, "■ NORMAL", transform=ax_disp.transAxes,
                                color="#a6e3a1", fontsize=10,
                                ha="right", va="bottom", fontfamily="monospace")

    # ── Graph panel ───────────────────────────────────────
    ax = fig.add_subplot(gs[1])
    ax.set_facecolor("#1e1e2e")

    line,     = ax.plot([], [], color="#89dceb", lw=1.5, label="I measured")
    ax.axhline(y=0, color="#f38ba8", lw=1.0, ls="--",
               label=f"Compliance {CURRENT_LIMIT*1e3:.0f} mA")

    ax.set_xlabel("Time (s)",       color="#cdd6f4", fontsize=11)
    ax.set_ylabel("Current I",      color="#cdd6f4", fontsize=11)
    ax.set_title("Real-time waveform", color="#9399b2", fontsize=10)
    ax.tick_params(colors="#cdd6f4")
    for sp in ax.spines.values():
        sp.set_edgecolor("#45475a")
    ax.legend(facecolor="#313244", labelcolor="#cdd6f4", fontsize=9)

    fig.subplots_adjust(left=0.08, right=0.97, top=0.95, bottom=0.08, hspace=0.4)

    def update(_frame):
        with data.lock:
            tt   = list(data.times)
            ii   = list(data.currents)
            comp = data.compliance
            last = data.last_i_ua

        scale, unit = auto_unit(ii if ii else [last])
        ii_scaled = [v * scale for v in ii]
        last_scaled = last * scale

        # ── update digital display ──
        disp_val.set_text(f"{last_scaled:>10.4f}")
        disp_unit.set_text(unit)
        if comp:
            disp_val.set_color("#ff5555")
            disp_status.set_text("■ COMPLIANCE!")
            disp_status.set_color("#f38ba8")
        else:
            disp_val.set_color("#00ff9f")
            disp_status.set_text("■ NORMAL")
            disp_status.set_color("#a6e3a1")

        # ── update graph ──
        if tt:
            line.set_data(tt, ii_scaled)
            ax.set_xlim(max(0, tt[-1] - MAX_POINTS * SAMPLE_INTERVAL), tt[-1] + 1)
            ax.set_ylabel(f"Current I ({unit})", color="#cdd6f4", fontsize=11)
            if ii_scaled:
                span = max(ii_scaled) - min(ii_scaled)
                pad  = span * 0.2 + 0.01
                ax.set_ylim(min(ii_scaled) - pad, max(ii_scaled) + pad)

        fig.canvas.draw_idle()

    ani = animation.FuncAnimation(
        fig, update,
        interval=150,
        cache_frame_data=False,
    )

    plt.show()

    with data.lock:
        data.done = True

    while not data.done:
        time.sleep(0.1)


# ══════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════

if __name__ == "__main__":
    shared = LiveData(maxlen=MAX_POINTS)

    t = threading.Thread(
        target=measure_thread_fn,
        args=(shared,),
        daemon=True,
    )
    t.start()

    run_plot(shared)

    t.join()
    print("\n[Done]")
