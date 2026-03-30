"""
Z-Scan: PI Hexapod H-811/H-840 (C-887) + Keithley 2602B SMU
============================================================
- Hexapod เดิน Z: 0 µm → -1100 µm  ทีละ 1 µm
- SMU: Source V / Measure I  ทุก step
- หยุดอัตโนมัติถ้า |I| >= STOP_CURRENT_A (1 µA)
- Real-time plot แสดง I vs Z ระหว่าง scan
- บันทึก CSV เมื่อจบ (ปกติหรือ stop-condition)

Requirements:
    pip install pipython matplotlib
"""

import time
import csv
import datetime
import socket
import sys
import threading

import matplotlib.pyplot as plt
import matplotlib.animation as animation

try:
    from pipython import GCSDevice, pitools
except ImportError:
    print("[ERROR] pip install pipython")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════
# CONFIG  — แก้ค่าตรงนี้
# ══════════════════════════════════════════════════════════════════════

HEXAPOD_IP      = "192.168.1.10"
HEXAPOD_PORT    = 50000
HEXAPOD_AXIS    = "Z"

SMU_IP          = "192.168.1.100"
SMU_PORT        = 5025
SMU_CHANNEL     = "a"
SMU_VOLTAGE     = 5.0       # V
SMU_ILIMIT      = 0.001     # 1 mA compliance
SMU_NPLC        = 1.0

Z_START_UM      = 0.0       # µm
Z_END_UM        = -1100.0   # µm
Z_STEP_UM       = -1.0      # µm/step (ลบ = ลงล่าง)

SETTLE_TIME_S   = 0.05      # วินาที รอหลัง move
STOP_CURRENT_A  = 1e-6      # หยุดเมื่อ |I| >= 1 µA

OUTPUT_CSV      = f"zscan_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"

# ══════════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────
# Keithley 2602B Driver
# ─────────────────────────────────────────────

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

    def setup_source_v(self, channel="a", voltage=0.0,
                       current_limit=0.1, nplc=1.0):
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
        ]:
            self.send(cmd)

    def output_on(self):
        sm = f"smu{self._ch}"
        self.send(f"{sm}.source.output = {sm}.OUTPUT_ON")
        time.sleep(0.1)

    def output_off(self):
        sm = f"smu{self._ch}"
        self.send(f"{sm}.source.output = {sm}.OUTPUT_OFF")

    def measure_iv(self):
        """Return (voltage_V, current_A)  — TSP returns I, V"""
        raw = self.query(f"print(smu{self._ch}.measure.iv())")
        parts = raw.replace(",", " ").split()
        if len(parts) >= 2:
            return float(parts[1]), float(parts[0])
        raise ValueError(f"SMU parse error: {raw!r}")


# ─────────────────────────────────────────────
# Shared data  (scan thread ↔ plot thread)
# ─────────────────────────────────────────────

class ScanData:
    def __init__(self):
        self.z_um    = []      # Z command µm
        self.i_ua    = []      # Current µA
        self.lock    = threading.Lock()
        self.done    = False
        self.stopped = False   # หยุดเพราะ threshold
        self.stop_z  = None


# ─────────────────────────────────────────────
# Scan thread
# ─────────────────────────────────────────────

def scan_thread_fn(data: ScanData):

    # Build Z list
    z_points = []
    z = Z_START_UM
    while z >= Z_END_UM:
        z_points.append(round(z, 4))
        z += Z_STEP_UM
    total = len(z_points)
    print(f"[SCAN] {total} points  ({Z_START_UM} → {Z_END_UM} µm  step {Z_STEP_UM} µm)")

    # ── Connect Hexapod ─────────────────────────
    hexapod = GCSDevice("C-887")
    hexapod.ConnectTCPIP(ipaddress=HEXAPOD_IP, ipport=HEXAPOD_PORT)
    print(f"[HXP] {hexapod.qIDN().strip()}")

    if not all(hexapod.qFRF().values()):
        print("[HXP] Referencing all axes...")
        hexapod.FRF()
        pitools.waitontarget(hexapod)
        print("[HXP] Reference done.")

    hexapod.SVO(HEXAPOD_AXIS, 1)
    print("[HXP] Moving to Z=0 ...")
    hexapod.MOV(HEXAPOD_AXIS, 0.0)
    pitools.waitontarget(hexapod, axes=HEXAPOD_AXIS)

    # ── Connect SMU ─────────────────────────────
    smu = Keithley2602B(SMU_IP, SMU_PORT)
    smu.connect()
    smu.reset()
    smu.setup_source_v(
        channel       = SMU_CHANNEL,
        voltage       = SMU_VOLTAGE,
        current_limit = SMU_ILIMIT,
        nplc          = SMU_NPLC,
    )
    smu.output_on()
    print(f"[SMU] Output ON  V={SMU_VOLTAGE}V  Ilimit={SMU_ILIMIT*1e3:.1f}mA")
    print(f"[SCAN] Start — stop if |I| >= {STOP_CURRENT_A*1e6:.1f} µA\n")

    results = []

    try:
        for idx, z_um in enumerate(z_points):

            # Move hexapod
            hexapod.MOV(HEXAPOD_AXIS, z_um / 1000.0)
            pitools.waitontarget(hexapod, axes=HEXAPOD_AXIS)
            time.sleep(SETTLE_TIME_S)

            # Measure
            _, i_a = smu.measure_iv()
            i_ua   = i_a * 1e6

            results.append((idx, z_um, i_a))

            with data.lock:
                data.z_um.append(z_um)
                data.i_ua.append(i_ua)

            # ── Stop condition ───────────────────
            if abs(i_a) >= STOP_CURRENT_A:
                with data.lock:
                    data.stopped = True
                    data.stop_z  = z_um
                print(f"\n{'='*50}")
                print(f"  STOP CONDITION MET")
                print(f"  Z = {z_um:.1f} µm   |I| = {abs(i_ua):.4f} µA  >= {STOP_CURRENT_A*1e6:.1f} µA")
                print(f"{'='*50}\n")
                break

            # Progress log ทุก 50 steps
            if idx % 50 == 0 or idx == total - 1:
                print(
                    f"  [{idx+1:4d}/{total}]  "
                    f"Z = {z_um:+8.1f} µm   "
                    f"I = {i_ua:+.4f} µA"
                )

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")

    finally:
        smu.output_off()
        smu.disconnect()
        hexapod.CloseConnection()
        print("[SMU] Output OFF.  [HXP] Disconnected.")

    # ── Save CSV ────────────────────────────────
    if results:
        with open(OUTPUT_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Index", "Z_cmd_um", "Current_A"])
            w.writerows(results)
        print(f"[CSV] {len(results)} points saved → {OUTPUT_CSV}")

    with data.lock:
        data.done = True


# ─────────────────────────────────────────────
# Real-time plot  (main thread)
# ─────────────────────────────────────────────

def run_realtime_plot(data: ScanData):

    fig, ax = plt.subplots(figsize=(13, 5))
    fig.patch.set_facecolor("#1e1e2e")
    ax.set_facecolor("#1e1e2e")
    fig.canvas.manager.set_window_title("Z-Scan  —  Real-time I vs Z")

    # Lines
    line,      = ax.plot([], [], color="#89dceb", lw=1.2, label="I measured (µA)")
    threshold_line = ax.axhline(
        y  = STOP_CURRENT_A * 1e6,
        color="#f38ba8", lw=1.0, ls="--",
        label=f"Stop threshold  {STOP_CURRENT_A*1e6:.1f} µA",
    )
    stop_vline = ax.axvline(x=0, color="#fab387", lw=1.8, ls=":", visible=False,
                             label="Stop position")

    # Axes style
    ax.set_xlabel("Z position (µm)", color="#cdd6f4", fontsize=11)
    ax.set_ylabel("Current (µA)",    color="#cdd6f4", fontsize=11)
    ax.set_title("Z-Scan  —  I vs Z  (real-time)", color="#cdd6f4", fontsize=13)
    ax.tick_params(colors="#cdd6f4")
    for spine in ax.spines.values():
        spine.set_edgecolor("#45475a")
    ax.set_xlim(Z_START_UM, Z_END_UM)
    ax.set_ylim(-0.05, STOP_CURRENT_A * 1e6 * 3)

    legend = ax.legend(facecolor="#313244", labelcolor="#cdd6f4", fontsize=9,
                        loc="upper right")

    status_txt = ax.text(0.01, 0.97, "Initializing...",
                          transform=ax.transAxes,
                          color="#a6e3a1", fontsize=9, va="top",
                          fontfamily="monospace")

    fig.tight_layout()

    def update(_frame):
        with data.lock:
            zz      = list(data.z_um)
            ii      = list(data.i_ua)
            done    = data.done
            stopped = data.stopped
            stop_z  = data.stop_z

        if not zz:
            return

        line.set_data(zz, ii)

        # Auto-scale Y
        ymax = max(abs(v) for v in ii) if ii else 0.1
        ymax = max(ymax * 1.3, STOP_CURRENT_A * 1e6 * 2)
        ax.set_ylim(-ymax * 0.1, ymax)

        # Stop marker
        if stopped and stop_z is not None:
            stop_vline.set_xdata([stop_z, stop_z])
            stop_vline.set_visible(True)
            status_txt.set_text(
                f"⛔ STOPPED  Z = {stop_z:.1f} µm   "
                f"|I| ≥ {STOP_CURRENT_A*1e6:.1f} µA   "
                f"({len(zz)} pts collected)"
            )
            status_txt.set_color("#f38ba8")
        elif done:
            status_txt.set_text(f"✔ Scan complete — {len(zz)} points")
            status_txt.set_color("#a6e3a1")
        else:
            if zz:
                status_txt.set_text(
                    f"▶ Z = {zz[-1]:+.1f} µm    "
                    f"I = {ii[-1]:+.4f} µA    "
                    f"[{len(zz)}/{int((Z_START_UM - Z_END_UM) / abs(Z_STEP_UM)) + 1}]"
                )

        fig.canvas.draw_idle()

    ani = animation.FuncAnimation(
        fig, update,
        interval=150,          # refresh ทุก 150 ms
        cache_frame_data=False,
    )

    plt.show()

    # รอ scan thread เสร็จก่อน exit
    while not data.done:
        time.sleep(0.2)


# ══════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    shared = ScanData()

    # Scan ใน background thread
    t = threading.Thread(target=scan_thread_fn, args=(shared,), daemon=True)
    t.start()

    # Plot ใน main thread (matplotlib requirement)
    run_realtime_plot(shared)

    t.join()
    print("\n[All done]")
