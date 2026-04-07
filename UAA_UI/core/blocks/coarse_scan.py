"""
CoarseScanBlock
================
Boustrophedon 2D scan ด้วย Cartesian + SMU
หา peak signal position
"""

import time
import numpy as np
from .base_block import BaseBlock


class CoarseScanBlock(BaseBlock):
    name     = "Coarse Scan"
    icon     = "🔬"
    category = "Optical"

    def default_params(self):
        return {
            "range_x":  0.500,   # mm
            "range_y":  0.500,   # mm
            "step":     0.050,   # mm
            "velocity": 2.000,   # mm/s
            "nplc":     1.0,     # SMU integration time
        }

    def validate(self, params):
        if float(params.get("step", 0)) <= 0:
            return False, "step must be > 0"
        if float(params.get("range_x", 0)) <= 0:
            return False, "range_x must be > 0"
        if float(params.get("range_y", 0)) <= 0:
            return False, "range_y must be > 0"
        return True, ""

    def run(self, params, devices, progress_cb, log_cb):
        cart = self._check_device(devices, "cart", log_cb)
        smu  = self._check_device(devices, "smu",  log_cb)

        rx   = float(params.get("range_x",  0.5))
        ry   = float(params.get("range_y",  0.5))
        step = float(params.get("step",     0.05))
        vel  = float(params.get("velocity", 2.0))
        nplc = float(params.get("nplc",     1.0))

        # Build scan grid
        xs = np.arange(-rx, rx + step/2, step)
        ys = np.arange(-ry, ry + step/2, step)
        total = len(xs) * len(ys)

        log_cb(
            f"Coarse scan: X±{rx} Y±{ry} mm  step={step} mm  "
            f"{len(xs)}×{len(ys)} = {total} pts", "info")

        # Get current position as origin
        origin_x, origin_y = 0.0, 0.0
        if cart:
            try:
                pos = cart.pos()
                origin_x = pos.get("X", 0.0)
                origin_y = pos.get("Y", 0.0)
                log_cb(f"Origin: X={origin_x:.4f} Y={origin_y:.4f} mm", "info")
            except Exception as e:
                log_cb(f"Cannot read position: {e}", "warn")

        # Configure SMU
        if smu:
            try:
                smu.set_nplc("A", nplc)
                log_cb(f"SMU NPLC={nplc}", "info")
            except Exception as e:
                log_cb(f"SMU config warning: {e}", "warn")

        # Scan
        results = []
        peak_signal = 0.0
        peak_x, peak_y = origin_x, origin_y
        n = 0

        for yi, y_rel in enumerate(ys):
            if self.is_aborted(): break
            # Boustrophedon — สลับทิศทาง X ทุก row
            row_xs = xs if yi % 2 == 0 else xs[::-1]

            for x_rel in row_xs:
                if self.is_aborted(): break

                abs_x = origin_x + x_rel
                abs_y = origin_y + y_rel

                # Move
                if cart:
                    try:
                        cart.vel_all(vel)
                        cart.mov_xy(abs_x, abs_y)
                        # Wait settle
                        time.sleep(0.01)
                    except Exception as e:
                        log_cb(f"Move error: {e}", "error")
                        continue

                # Measure
                signal = 0.0
                if smu:
                    try:
                        signal = abs(smu.measure_i("A"))
                    except Exception as e:
                        log_cb(f"SMU measure error: {e}", "warn")
                else:
                    # Simulate — Gaussian peak at (0.01, -0.02)
                    signal = self._sim_signal(x_rel, y_rel)

                results.append((abs_x, abs_y, signal))

                if signal > peak_signal:
                    peak_signal = signal
                    peak_x, peak_y = abs_x, abs_y

                n += 1
                progress_cb(int(n / total * 100))

        if self.is_aborted():
            log_cb("Coarse scan aborted", "warn")
            return False

        # Move to peak
        log_cb(
            f"Peak found: X={peak_x:.4f} Y={peak_y:.4f} mm  "
            f"signal={peak_signal*1e6:.3f} µA", "ok")

        if cart and peak_signal > 0:
            try:
                cart.vel_all(vel)
                cart.mov_xy(peak_x, peak_y)
                log_cb(f"Moved to peak position", "ok")
            except Exception as e:
                log_cb(f"Move to peak error: {e}", "error")
                return False

        # Store result for next block
        devices["_scan_result"] = {
            "peak_x":      peak_x,
            "peak_y":      peak_y,
            "peak_signal": peak_signal,
            "scan_data":   results,
        }

        return True

    def _sim_signal(self, x, y, cx=0.01, cy=-0.02, sigma=0.08):
        """Simulate Gaussian optical signal"""
        signal = 1.2e-6 * np.exp(
            -((x - cx)**2 + (y - cy)**2) / (2 * sigma**2))
        noise = np.random.normal(0, 2e-10)
        return max(0.0, signal + noise)
