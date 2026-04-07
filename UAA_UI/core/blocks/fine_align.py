"""
FineAlignBlock
===============
Spiral fine search จาก coarse peak position
ใช้ gradient ascent หา true peak
"""

import time
import numpy as np
from .base_block import BaseBlock


class FineAlignBlock(BaseBlock):
    name     = "Fine Align"
    icon     = "🎯"
    category = "Optical"

    def default_params(self):
        return {
            "range_x":   0.050,   # mm
            "range_y":   0.050,   # mm
            "step":      0.001,   # mm
            "velocity":  0.500,   # mm/s
            "tolerance": 0.010,   # µA — convergence threshold
            "max_iter":  3,       # max refinement iterations
        }

    def validate(self, params):
        if float(params.get("step", 0)) <= 0:
            return False, "step must be > 0"
        if float(params.get("tolerance", 0)) <= 0:
            return False, "tolerance must be > 0"
        return True, ""

    def run(self, params, devices, progress_cb, log_cb):
        cart = self._check_device(devices, "cart", log_cb)
        smu  = self._check_device(devices, "smu",  log_cb)

        rx      = float(params.get("range_x",   0.05))
        ry      = float(params.get("range_y",   0.05))
        step    = float(params.get("step",      0.001))
        vel     = float(params.get("velocity",  0.5))
        tol     = float(params.get("tolerance", 0.01)) * 1e-6
        max_iter = int(params.get("max_iter",   3))

        # Get start position from coarse scan result or current pos
        scan_result = devices.get("_scan_result", {})
        start_x = scan_result.get("peak_x", 0.0)
        start_y = scan_result.get("peak_y", 0.0)
        prev_signal = scan_result.get("peak_signal", 0.0)

        if cart and not scan_result:
            try:
                pos = cart.pos()
                start_x = pos.get("X", 0.0)
                start_y = pos.get("Y", 0.0)
            except: pass

        log_cb(
            f"Fine align from X={start_x:.4f} Y={start_y:.4f} mm  "
            f"range X±{rx} Y±{ry} step={step} mm", "info")

        best_x, best_y = start_x, start_y
        best_signal = prev_signal

        for iteration in range(max_iter):
            if self.is_aborted(): break
            log_cb(f"Iteration {iteration+1}/{max_iter}", "info")

            # Spiral scan around current best
            xs = np.arange(-rx, rx + step/2, step)
            ys = np.arange(-ry, ry + step/2, step)
            total = len(xs) * len(ys)
            n = 0

            iter_best_x, iter_best_y = best_x, best_y
            iter_best_sig = best_signal

            for yi, y_rel in enumerate(ys):
                if self.is_aborted(): break
                row_xs = xs if yi % 2 == 0 else xs[::-1]

                for x_rel in row_xs:
                    if self.is_aborted(): break

                    abs_x = best_x + x_rel
                    abs_y = best_y + y_rel

                    if cart:
                        try:
                            cart.vel_all(vel)
                            cart.mov_xy(abs_x, abs_y)
                            time.sleep(0.005)
                        except Exception as e:
                            log_cb(f"Move error: {e}", "error")
                            continue

                    signal = 0.0
                    if smu:
                        try:
                            signal = abs(smu.measure_i("A"))
                        except Exception as e:
                            log_cb(f"SMU error: {e}", "warn")
                    else:
                        signal = self._sim_signal(abs_x, abs_y)

                    if signal > iter_best_sig:
                        iter_best_sig = signal
                        iter_best_x, iter_best_y = abs_x, abs_y

                    n += 1
                    prog = int(
                        (iteration * total + n) / (max_iter * total) * 100)
                    progress_cb(prog)

            # Check convergence
            delta = iter_best_sig - best_signal
            best_x, best_y = iter_best_x, iter_best_y
            best_signal = iter_best_sig

            log_cb(
                f"Iter {iteration+1}: peak X={best_x:.4f} Y={best_y:.4f} "
                f"signal={best_signal*1e6:.3f} µA  Δ={delta*1e6:.4f} µA", "info")

            if delta < tol and iteration > 0:
                log_cb("Converged", "ok")
                break

            # Shrink search range for next iteration
            rx *= 0.4; ry *= 0.4
            step *= 0.5
            step = max(step, 0.0001)

        if self.is_aborted():
            log_cb("Fine align aborted", "warn")
            return False

        # Move to final peak
        if cart:
            try:
                cart.vel_all(vel)
                cart.mov_xy(best_x, best_y)
            except Exception as e:
                log_cb(f"Move to peak error: {e}", "error")
                return False

        log_cb(
            f"Fine align done: X={best_x:.4f} Y={best_y:.4f}  "
            f"signal={best_signal*1e6:.4f} µA", "ok")

        # Store result
        devices["_align_result"] = {
            "peak_x":      best_x,
            "peak_y":      best_y,
            "peak_signal": best_signal,
        }

        progress_cb(100)
        return True

    def _sim_signal(self, x, y, cx=0.0012, cy=-0.0008, sigma=0.012):
        signal = 1.4e-6 * np.exp(
            -((x - cx)**2 + (y - cy)**2) / (2 * sigma**2))
        noise = np.random.normal(0, 1e-10)
        return max(0.0, signal + noise)
