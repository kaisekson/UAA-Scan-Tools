"""
PI Hexapod — Y-Z Scan Test (ไม่มี SMU)
========================================
ทดสอบการเคลื่อนที่ Y และ Z scan pattern
boustrophedon (งูเลื้อย) เหมือน scan จริง
อ่านค่า position จริงจาก controller ทุก step
บันทึก CSV

Requirements:
    pip install pipython
"""

import time
import csv
import datetime
import sys

try:
    from pipython import GCSDevice, pitools
except ImportError:
    print("[ERROR] pip install pipython")
    sys.exit(1)

# ══════════════════════════════════════════════
# CONFIG — แก้ค่าตรงนี้
# ══════════════════════════════════════════════

HEXAPOD_IP   = "192.168.1.10"   # IP ของ C-887
HEXAPOD_PORT = 50000

Y_START_UM   = 0.0
Y_END_UM     = 200.0
Y_STEP_UM    = 25.0

Z_START_UM   = 0.0
Z_END_UM     = -500.0
Z_STEP_UM    = -10.0

SETTLE_TIME  = 0.05             # วินาที รอหลัง move

OUTPUT_CSV   = f"hexapod_scan_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"

# ══════════════════════════════════════════════


def make_points(start, end, step):
    pts = []
    v = start
    while (step < 0 and v >= end) or (step > 0 and v <= end):
        pts.append(round(v, 4))
        v += step
    return pts


def um_to_mm(um):
    return um / 1000.0


def run_scan():
    y_points = make_points(Y_START_UM, Y_END_UM, Y_STEP_UM)
    z_points = make_points(Z_START_UM, Z_END_UM, Z_STEP_UM)
    total    = len(y_points) * len(z_points)

    print("=" * 55)
    print(f"  Hexapod Y-Z Scan Test")
    print(f"  Y: {Y_START_UM} → {Y_END_UM} µm  step {Y_STEP_UM} µm  ({len(y_points)} lines)")
    print(f"  Z: {Z_START_UM} → {Z_END_UM} µm  step {Z_STEP_UM} µm  ({len(z_points)} steps/line)")
    print(f"  Total: {total} points")
    print(f"  Output: {OUTPUT_CSV}")
    print("=" * 55)

    # ── Connect ────────────────────────────────
    hexapod = GCSDevice("C-887")
    hexapod.ConnectTCPIP(ipaddress=HEXAPOD_IP, ipport=HEXAPOD_PORT)
    print(f"\n[HXP] {hexapod.qIDN().strip()}")

    # Reference ถ้ายังไม่ได้ทำ
    if not all(hexapod.qFRF().values()):
        print("[HXP] Referencing...")
        hexapod.FRF()
        pitools.waitontarget(hexapod)
        print("[HXP] Reference done.")

    # Enable servo
    hexapod.SVO("Y", 1)
    hexapod.SVO("Z", 1)

    # Move to start position
    print(f"\n[HXP] Moving to start Y={Y_START_UM}µm Z={Z_START_UM}µm ...")
    hexapod.MOV({"Y": um_to_mm(Y_START_UM), "Z": um_to_mm(Z_START_UM)})
    pitools.waitontarget(hexapod, axes=["Y", "Z"])
    print("[HXP] At start position.")

    results = []
    t_start = time.time()

    try:
        for yi, y_um in enumerate(y_points):

            # Move Y
            hexapod.MOV("Y", um_to_mm(y_um))
            pitools.waitontarget(hexapod, axes="Y")
            time.sleep(SETTLE_TIME)

            # boustrophedon: สลับทิศ Z ทุก Y line
            z_line = z_points if yi % 2 == 0 else list(reversed(z_points))
            z_dir  = "↓" if yi % 2 == 0 else "↑"

            print(f"\n[Y {yi+1:2d}/{len(y_points)}] Y = {y_um:+7.1f} µm  Z {z_dir}")

            for zi, z_um in enumerate(z_line):

                # Move Z
                hexapod.MOV("Z", um_to_mm(z_um))
                pitools.waitontarget(hexapod, axes="Z")
                time.sleep(SETTLE_TIME)

                # อ่าน position จริง
                pos   = hexapod.qPOS(["Y", "Z"])
                y_act = pos["Y"] * 1000.0   # mm → µm
                z_act = pos["Z"] * 1000.0

                results.append((yi, zi, y_um, z_um, y_act, z_act))

                # Progress ทุก step
                elapsed = time.time() - t_start
                done    = yi * len(z_points) + zi + 1
                eta     = (elapsed / done) * (total - done) if done else 0
                print(
                    f"  [Y={y_um:+7.1f} Z={z_um:+7.1f}µm]  "
                    f"act Y={y_act:+7.2f} Z={z_act:+7.2f}µm  "
                    f"[{done}/{total}] ETA {eta:.0f}s"
                )

    except KeyboardInterrupt:
        print("\n[!] Interrupted.")

    finally:
        # Return home
        print("\n[HXP] Returning to home Y=0 Z=0 ...")
        hexapod.MOV({"Y": 0.0, "Z": 0.0})
        pitools.waitontarget(hexapod, axes=["Y", "Z"])
        hexapod.CloseConnection()
        print("[HXP] Disconnected.")

    # Save CSV
    if results:
        with open(OUTPUT_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Y_line", "Z_step",
                        "Y_cmd_um", "Z_cmd_um",
                        "Y_act_um", "Z_act_um",
                        "Y_err_um", "Z_err_um"])
            for yi, zi, yc, zc, ya, za in results:
                w.writerow([yi, zi, yc, zc,
                            round(ya, 3), round(za, 3),
                            round(ya - yc, 3), round(za - zc, 3)])
        elapsed = time.time() - t_start
        print(f"\n[CSV] {len(results)} points in {elapsed:.1f}s → {OUTPUT_CSV}")
    else:
        print("[!] No data.")


# ══════════════════════════════════════════════
if __name__ == "__main__":
    run_scan()
