"""
2D Raster Scan: PI Hexapod + Keithley 2602B
============================================
Fix X, Y left→right, Z boustrophedon (สลับทิศทางทุก Y line)

- Config จาก scan_config.json
- Stop Z line ถ้า |I| >= stop_current_ua
- Real-time line plot I vs Z (update ทุก 200ms)
- บันทึก CSV ทุก point

Requirements:
    pip install pipython matplotlib
"""

import json
import os
import csv
import time
import socket
import threading
import datetime
import sys

import matplotlib.pyplot as plt
import matplotlib.animation as animation

try:
    from pipython import GCSDevice, pitools
except ImportError:
    print("[ERROR] pip install pipython")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════
# Load config
# ══════════════════════════════════════════════════════════════════════

CONFIG_FILE = "scan_config.json"

def load_config(path: str) -> dict:
    if not os.path.exists(path):
        print(f"[ERROR] Config file not found: {path}")
        sys.exit(1)
    with open(path, "r") as f:
        cfg = json.load(f)
    print(f"[CFG] Loaded {path}")
    return cfg


# ══════════════════════════════════════════════════════════════════════
# Keithley 2602B Driver
# ══════════════════════════════════════════════════════════════════════

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
        raw = self.query(f"print(smu{self._ch}.measure.iv())")
        parts = raw.replace(",", " ").split()
        if len(parts) >= 2:
            return float(parts[1]), float(parts[0])   # V, I
        raise ValueError(f"SMU parse error: {raw!r}")


# ══════════════════════════════════════════════════════════════════════
# Shared scan data
# ══════════════════════════════════════════════════════════════════════

class ScanData:
    def __init__(self):
        self.lock         = threading.Lock()
        # Current Z line data (reset ทุก Y line)
        self.z_current    = []    # µm
        self.i_current    = []    # µA
        # Current Y line index & value
        self.y_index      = 0
        self.y_um         = 0.0
        self.y_total      = 0
        # Status
        self.status_text  = "Initializing..."
        self.done         = False
        self.stop_z       = None   # Z ที่ stop condition เกิด (ถ้ามี)


# ══════════════════════════════════════════════════════════════════════
# Scan thread
# ══════════════════════════════════════════════════════════════════════

def make_points(start, end, step):
    pts = []
    v = start
    if step == 0:
        return pts
    while (step < 0 and v >= end) or (step > 0 and v <= end):
        pts.append(round(v, 4))
        v += step
    return pts


def scan_thread_fn(cfg: dict, data: ScanData, csv_path: str):
    sc  = cfg["scan"]
    hxp = cfg["hexapod"]
    smu_cfg = cfg["smu"]

    y_points     = make_points(sc["y_start_um"], sc["y_end_um"], sc["y_step_um"])
    z_points_fwd = make_points(sc["z_start_um"], sc["z_end_um"], sc["z_step_um"])
    z_points_rev = list(reversed(z_points_fwd))
    stop_a       = sc["stop_current_ua"] * 1e-6

    with data.lock:
        data.y_total = len(y_points)

    print(f"[SCAN] Y: {len(y_points)} lines   Z: {len(z_points_fwd)} points/line")
    print(f"[SCAN] Stop if |I| >= {sc['stop_current_ua']} µA")

    # ── Connect Hexapod ──────────────────────────────────────────────
    hexapod = GCSDevice("C-887")
    hexapod.ConnectTCPIP(ipaddress=hxp["ip"], ipport=hxp["port"])
    print(f"[HXP] {hexapod.qIDN().strip()}")

    if not all(hexapod.qFRF().values()):
        print("[HXP] Referencing...")
        hexapod.FRF()
        pitools.waitontarget(hexapod)

    hexapod.SVO("Y", 1)
    hexapod.SVO("Z", 1)

    # ── Connect SMU ──────────────────────────────────────────────────
    smu = Keithley2602B(smu_cfg["ip"], smu_cfg["port"])
    smu.connect()
    smu.reset()
    smu.setup_source_v(
        channel       = smu_cfg["channel"],
        voltage       = smu_cfg["voltage"],
        current_limit = smu_cfg["current_limit_a"],
        nplc          = smu_cfg["nplc"],
    )
    smu.output_on()

    # ── Open CSV ─────────────────────────────────────────────────────
    csv_file = open(csv_path, "w", newline="")
    writer   = csv.writer(csv_file)
    writer.writerow(["Y_um", "Z_um", "Current_A"])

    try:
        for yi, y_um in enumerate(y_points):

            # Move Y
            hexapod.MOV("Y", y_um / 1000.0)
            pitools.waitontarget(hexapod, axes="Y")
            time.sleep(sc["settle_time_s"])

            # Reset Z line buffer
            with data.lock:
                data.z_current = []
                data.i_current = []
                data.y_index   = yi + 1
                data.y_um      = y_um
                data.stop_z    = None
                data.status_text = f"Y line {yi+1}/{len(y_points)}  Y={y_um:.1f} µm  scanning Z..."

            # สลับทิศ Z ทุก Y line (boustrophedon)
            z_line = z_points_fwd if yi % 2 == 0 else z_points_rev
            z_dir  = "down" if yi % 2 == 0 else "up"
            print(f"\n[Y {yi+1}/{len(y_points)}] Y = {y_um:.1f} um  Z {z_dir}")

            # ── Z sweep ──────────────────────────────────────────────
            for z_um in z_line:

                hexapod.MOV("Z", z_um / 1000.0)
                pitools.waitontarget(hexapod, axes="Z")
                time.sleep(sc["settle_time_s"])

                _, i_a = smu.measure_iv()
                i_ua   = i_a * 1e6

                writer.writerow([y_um, z_um, i_a])
                csv_file.flush()

                with data.lock:
                    data.z_current.append(z_um)
                    data.i_current.append(i_ua)

                # Stop condition
                if abs(i_a) >= stop_a:
                    with data.lock:
                        data.stop_z      = z_um
                        data.status_text = (
                            f"Y={y_um:.1f} µm  STOP at Z={z_um:.1f} µm  "
                            f"|I|={abs(i_ua):.4f} µA >= {sc['stop_current_ua']} µA"
                        )
                    print(f"  [STOP] Z={z_um:.1f} µm  |I|={abs(i_ua):.4f} µA")
                    break

            # boustrophedon: ไม่ต้องถอย Z กลับ เริ่ม line ถัดไปจากตำแหน่งปัจจุบัน

    except KeyboardInterrupt:
        print("\n[!] Interrupted.")

    finally:
        smu.output_off()
        smu.disconnect()
        csv_file.close()
        hexapod.CloseConnection()
        print(f"\n[CSV] Saved → {csv_path}")
        print("[SMU] Output OFF.  [HXP] Disconnected.")

    with data.lock:
        data.done        = True
        data.status_text = f"Scan complete — saved to {os.path.basename(csv_path)}"


# ══════════════════════════════════════════════════════════════════════
# Real-time plot  (main thread)
# ══════════════════════════════════════════════════════════════════════

def run_plot(cfg: dict, data: ScanData):
    sc        = cfg["scan"]
    stop_ua   = sc["stop_current_ua"]
    z_start   = sc["z_start_um"]
    z_end     = sc["z_end_um"]

    fig, ax = plt.subplots(figsize=(13, 5))
    fig.patch.set_facecolor("#1e1e2e")
    ax.set_facecolor("#1e1e2e")
    fig.canvas.manager.set_window_title("2D Scan — Real-time I vs Z")

    line,        = ax.plot([], [], color="#89dceb", lw=1.2)
    thresh_line    = ax.axhline(y=stop_ua, color="#f38ba8",
                                lw=1.0, ls="--",
                                label=f"Stop {stop_ua} µA")
    stop_vline   = ax.axvline(x=0, color="#fab387", lw=1.5,
                               ls=":", visible=False)

    ax.set_xlabel("Z position (µm)", color="#cdd6f4", fontsize=11)
    ax.set_ylabel("Current (µA)",    color="#cdd6f4", fontsize=11)
    ax.set_title("I vs Z  —  real-time", color="#cdd6f4", fontsize=13)
    ax.tick_params(colors="#cdd6f4")
    for spine in ax.spines.values():
        spine.set_edgecolor("#45475a")
    ax.set_xlim(z_start, z_end)
    ax.set_ylim(-0.05, stop_ua * 3)
    ax.legend(facecolor="#313244", labelcolor="#cdd6f4", fontsize=9)

    title_txt  = ax.text(0.01, 0.97, "",
                          transform=ax.transAxes,
                          color="#cdd6f4", fontsize=10,
                          va="top", fontfamily="monospace")
    status_txt = ax.text(0.01, 0.88, "",
                          transform=ax.transAxes,
                          color="#a6e3a1", fontsize=9,
                          va="top", fontfamily="monospace")
    fig.tight_layout()

    def update(_frame):
        with data.lock:
            zz     = list(data.z_current)
            ii     = list(data.i_current)
            status = data.status_text
            stop_z = data.stop_z
            yi     = data.y_index
            y_um   = data.y_um
            ytotal = data.y_total
            done   = data.done

        line.set_data(zz, ii)

        if ii:
            ymax = max(abs(v) for v in ii)
            ymax = max(ymax * 1.4, stop_ua * 2)
            ax.set_ylim(-ymax * 0.1, ymax)

        if stop_z is not None:
            stop_vline.set_xdata([stop_z, stop_z])
            stop_vline.set_visible(True)
            status_txt.set_color("#f38ba8")
        else:
            stop_vline.set_visible(False)
            status_txt.set_color("#a6e3a1" if not done else "#a6e3a1")

        title_txt.set_text(f"Y line {yi}/{ytotal}   Y = {y_um:.1f} µm")
        status_txt.set_text(status)
        fig.canvas.draw_idle()

    ani = animation.FuncAnimation(
        fig, update,
        interval=200,
        cache_frame_data=False,
    )

    plt.show()

    while not data.done:
        time.sleep(0.2)


# ══════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cfg = load_config(CONFIG_FILE)

    # Prepare output dir
    out_dir = cfg["output"]["csv_dir"]
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(
        out_dir,
        f"scan_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
    )

    shared = ScanData()

    t = threading.Thread(
        target=scan_thread_fn,
        args=(cfg, shared, csv_path),
        daemon=True,
    )
    t.start()

    run_plot(cfg, shared)

    t.join()
    print("\n[All done]")
