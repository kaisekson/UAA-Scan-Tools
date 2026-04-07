"""
TiltCorrectionBlock
====================
ปรับ U/V ของ Hexapod เพื่อหา max signal
"""

import time
import numpy as np
from .base_block import BaseBlock


class TiltCorrectionBlock(BaseBlock):
    name     = "Tilt Correction"
    icon     = "↕"
    category = "Optical"

    def default_params(self):
        return {
            "axis":      "U and V",
            "step_deg":  0.010,
            "threshold": 0.005,   # µA convergence
            "max_iter":  5,
            "retry":     "Yes",
            "timeout":   30,
        }

    def run(self, params, devices, progress_cb, log_cb):
        hxp = devices.get("hxp1") or devices.get("hxp2")
        smu = self._check_device(devices, "smu", log_cb)

        if not hxp:
            log_cb("Tilt Correction: no hexapod connected — simulating", "warn")

        axis    = params.get("axis", "U and V")
        step    = float(params.get("step_deg",  0.010))
        thr     = float(params.get("threshold", 0.005)) * 1e-6
        max_iter = int(params.get("max_iter",   5))
        axes_to_tune = []
        if "U" in axis: axes_to_tune.append("U")
        if "V" in axis: axes_to_tune.append("V")

        log_cb(f"Tilt correction axes={axes_to_tune} step={step}°", "info")

        best_signal = 0.0
        if smu:
            try: best_signal = abs(smu.measure_i("A"))
            except: pass
        else:
            best_signal = self._sim_signal(0, 0)

        for iteration in range(max_iter):
            if self.is_aborted(): break
            improved = False

            for ax in axes_to_tune:
                if self.is_aborted(): break
                # Try +step and -step
                for sign in [1, -1]:
                    if self.is_aborted(): break
                    if hxp:
                        try:
                            axes = sorted(hxp.axes)
                            ax_map = {"U":3,"V":4,"W":5}
                            idx = ax_map.get(ax, 3)
                            if idx < len(axes):
                                cur = hxp.qPOS(axes[idx])[axes[idx]]
                                hxp.MOV(axes[idx], cur + sign * step)
                                time.sleep(0.05)
                        except Exception as e:
                            log_cb(f"Hexapod error: {e}", "warn")

                    signal = 0.0
                    if smu:
                        try: signal = abs(smu.measure_i("A"))
                        except: pass
                    else:
                        signal = self._sim_signal(
                            iteration * 0.001 * sign,
                            iteration * 0.001 * sign)

                    if signal > best_signal + thr:
                        best_signal = signal
                        improved = True
                        log_cb(
                            f"  {ax}{'+' if sign>0 else '-'}: "
                            f"signal={signal*1e6:.4f} µA ↑", "info")
                    else:
                        # Revert
                        if hxp:
                            try:
                                axes = sorted(hxp.axes)
                                ax_map = {"U":3,"V":4,"W":5}
                                idx = ax_map.get(ax, 3)
                                if idx < len(axes):
                                    cur = hxp.qPOS(axes[idx])[axes[idx]]
                                    hxp.MOV(axes[idx], cur - sign*step)
                            except: pass

            progress_cb(int((iteration+1)/max_iter*100))
            if not improved:
                log_cb(f"No improvement at iter {iteration+1} — converged", "ok")
                break
            step *= 0.7  # shrink step

        if self.is_aborted():
            log_cb("Tilt correction aborted", "warn")
            return False

        log_cb(
            f"Tilt correction done  signal={best_signal*1e6:.4f} µA", "ok")
        devices["_tilt_result"] = {"signal": best_signal}
        progress_cb(100)
        return True

    def _sim_signal(self, u, v):
        s = 1.3e-6 * np.exp(-((u)**2 + (v)**2) / (2 * 0.05**2))
        return max(0.0, s + np.random.normal(0, 1e-10))
