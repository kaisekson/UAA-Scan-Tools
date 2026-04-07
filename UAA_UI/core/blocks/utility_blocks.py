"""
Utility Blocks
===============
Dispense / UV Cure / Verify / Move / Wait / Set TEC
"""

import time
import numpy as np
from .base_block import BaseBlock


# ══════════════════════════════════════════════
class DispenseBlock(BaseBlock):
    name     = "Dispense"
    icon     = "💧"
    category = "IO"

    def default_params(self):
        return {
            "program":  "P1",
            "pressure": 50,      # kPa
            "time_ms":  100,     # ms
            "repeat":   1,
            "wait_ms":  200,     # ms after dispense
        }

    def run(self, params, devices, progress_cb, log_cb):
        wago = self._check_device(devices, "wago", log_cb)

        program  = params.get("program",  "P1")
        pressure = params.get("pressure", 50)
        time_ms  = int(params.get("time_ms", 100))
        repeat   = int(params.get("repeat",  1))
        wait_ms  = int(params.get("wait_ms", 200))

        log_cb(
            f"Dispense {program}  {pressure}kPa  {time_ms}ms  ×{repeat}", "info")

        for i in range(repeat):
            if self.is_aborted(): break
            if wago:
                try:
                    # Trigger dispense DO
                    wago.write_do_by_name("DISPENSE_TRIGGER", True)
                    time.sleep(time_ms / 1000.0)
                    wago.write_do_by_name("DISPENSE_TRIGGER", False)
                except Exception as e:
                    log_cb(f"WAGO dispense error: {e}", "error")
                    return False
            else:
                log_cb(f"  Shot {i+1}: simulated {time_ms}ms", "info")
                self._sleep(time_ms / 1000.0)

            if i < repeat - 1:
                self._sleep(wait_ms / 1000.0)
            progress_cb(int((i+1)/repeat*100))

        if self.is_aborted():
            log_cb("Dispense aborted", "warn")
            return False

        self._sleep(wait_ms / 1000.0)
        log_cb("Dispense done", "ok")
        progress_cb(100)
        return True


# ══════════════════════════════════════════════
class UVCureBlock(BaseBlock):
    name     = "UV Cure"
    icon     = "☀"
    category = "IO"

    def default_params(self):
        return {
            "time_s":    5.0,
            "intensity": 100,    # %
            "wait_s":    1.0,
        }

    def run(self, params, devices, progress_cb, log_cb):
        wago  = devices.get("wago")
        time_s = float(params.get("time_s",    5.0))
        wait_s = float(params.get("wait_s",    1.0))
        intens = params.get("intensity", 100)

        log_cb(f"UV Cure {time_s}s @ {intens}%", "info")

        if wago:
            try:
                wago.write_do_by_name("UV_ENABLE", True)
            except Exception as e:
                log_cb(f"UV enable error: {e}", "error")
                return False

        # Count down
        steps = max(10, int(time_s * 10))
        for i in range(steps):
            if self.is_aborted(): break
            time.sleep(time_s / steps)
            progress_cb(int((i+1)/steps*100))
            remaining = time_s - (i+1)*(time_s/steps)
            if i % 10 == 0:
                log_cb(f"  UV Cure: {remaining:.1f}s remaining", "info")

        if wago:
            try:
                wago.write_do_by_name("UV_ENABLE", False)
            except Exception as e:
                log_cb(f"UV disable error: {e}", "warn")

        if self.is_aborted():
            log_cb("UV Cure aborted", "warn")
            return False

        self._sleep(wait_s)
        log_cb("UV Cure done", "ok")
        return True


# ══════════════════════════════════════════════
class VerifyBlock(BaseBlock):
    name     = "Verify"
    icon     = "✅"
    category = "Optical"

    def default_params(self):
        return {
            "min_signal":  0.500,  # µA
            "range":       0.100,  # mm scan range
            "threshold":   90,     # % of pre-cure signal
            "fail_action": "Stop",
        }

    def run(self, params, devices, progress_cb, log_cb):
        smu  = self._check_device(devices, "smu",  log_cb)
        cart = devices.get("cart")

        min_signal   = float(params.get("min_signal",  0.5)) * 1e-6
        scan_range   = float(params.get("range",       0.1))
        threshold_pct = float(params.get("threshold",  90))
        fail_action  = params.get("fail_action", "Stop")

        log_cb(
            f"Verify: min={min_signal*1e6:.3f}µA  range={scan_range}mm  "
            f"threshold={threshold_pct}%", "info")

        # Quick 3×3 scan ตรงกลาง
        offsets = [-scan_range/2, 0, scan_range/2]
        signals = []
        total = len(offsets)**2
        n = 0

        # Get current position
        cx, cy = 0.0, 0.0
        if cart:
            try:
                pos = cart.pos()
                cx = pos.get("X", 0.0)
                cy = pos.get("Y", 0.0)
            except: pass

        for dx in offsets:
            for dy in offsets:
                if self.is_aborted(): break
                if cart:
                    try:
                        cart.mov_xy(cx+dx, cy+dy)
                        time.sleep(0.01)
                    except: pass

                sig = 0.0
                if smu:
                    try: sig = abs(smu.measure_i("A"))
                    except: pass
                else:
                    sig = 1.2e-6 * np.exp(
                        -((dx)**2+(dy)**2)/(2*0.05**2)) + np.random.normal(0,1e-10)
                    sig = max(0, sig)

                signals.append(sig)
                n += 1
                progress_cb(int(n/total*100))

        if self.is_aborted():
            log_cb("Verify aborted", "warn")
            return False

        # Move back to center
        if cart:
            try: cart.mov_xy(cx, cy)
            except: pass

        if not signals:
            log_cb("No measurements taken", "error")
            return False

        peak = max(signals)
        log_cb(f"Peak signal: {peak*1e6:.4f} µA", "info")

        # Check min signal
        if peak < min_signal:
            log_cb(
                f"FAIL: signal {peak*1e6:.4f} µA < min {min_signal*1e6:.3f} µA",
                "error")
            if fail_action == "Stop":
                return False

        # Check vs pre-cure signal
        align_result = devices.get("_align_result", {})
        pre_signal = align_result.get("peak_signal", 0)
        if pre_signal > 0:
            pct = peak / pre_signal * 100
            log_cb(f"Signal retention: {pct:.1f}% (threshold {threshold_pct}%)", "info")
            if pct < threshold_pct:
                log_cb(f"FAIL: retention {pct:.1f}% < {threshold_pct}%", "error")
                if fail_action == "Stop":
                    return False

        devices["_verify_result"] = {"peak": peak, "signals": signals}
        log_cb(f"Verify PASS  peak={peak*1e6:.4f} µA", "ok")
        progress_cb(100)
        return True


# ══════════════════════════════════════════════
class MoveBlock(BaseBlock):
    name     = "Move"
    icon     = "🤖"
    category = "Motion"

    def default_params(self):
        return {
            "device":   "Cartesian",
            "x":        0.000,
            "y":        0.000,
            "z":        0.000,
            "velocity": 5.000,
        }

    def run(self, params, devices, progress_cb, log_cb):
        dev_name = params.get("device", "Cartesian")
        x   = float(params.get("x",        0.0))
        y   = float(params.get("y",        0.0))
        z   = float(params.get("z",        0.0))
        vel = float(params.get("velocity", 5.0))

        dev_key = {
            "Cartesian":  "cart",
            "Hexapod 1":  "hxp1",
            "Hexapod 2":  "hxp2",
            "Linear":     "lin",
        }.get(dev_name, "cart")

        drv = devices.get(dev_key)
        log_cb(
            f"Move {dev_name}: X={x:.3f} Y={y:.3f} Z={z:.3f} mm  vel={vel}", "info")

        if drv:
            try:
                if dev_name == "Cartesian":
                    drv.vel_all(vel)
                    drv.mov_xyz(x, y, z)
                elif dev_name in ("Hexapod 1","Hexapod 2"):
                    axes = sorted(drv.axes)
                    cmd = {}
                    for i, ax_val in enumerate([(x,0),(y,1),(z,2)]):
                        if i < len(axes): cmd[axes[ax_val[1]]] = ax_val[0]
                    drv.MOV(cmd)
                elif dev_name == "Linear":
                    drv.vel(vel); drv.mov(x)
                # Wait for motion
                time.sleep(0.2)
                progress_cb(100)
                log_cb(f"Move {dev_name} done", "ok")
            except Exception as e:
                log_cb(f"Move error: {e}", "error")
                return False
        else:
            log_cb(f"Move {dev_name}: simulated X={x} Y={y} Z={z}", "info")
            self._sleep(0.5)
            progress_cb(100)

        return True


# ══════════════════════════════════════════════
class WaitBlock(BaseBlock):
    name     = "Wait"
    icon     = "⏱"
    category = "Utility"

    def default_params(self):
        return {
            "time_s":  1.0,
            "message": "",
        }

    def run(self, params, devices, progress_cb, log_cb):
        t   = float(params.get("time_s",  1.0))
        msg = params.get("message", "")

        log_cb(f"Wait {t}s{f'  — {msg}' if msg else ''}", "info")

        steps = max(10, int(t * 10))
        for i in range(steps):
            if self.is_aborted(): break
            time.sleep(t / steps)
            progress_cb(int((i+1)/steps*100))

        if self.is_aborted():
            log_cb("Wait aborted", "warn")
            return False

        log_cb("Wait done", "ok")
        return True


# ══════════════════════════════════════════════
class SetTECBlock(BaseBlock):
    name     = "Set TEC"
    icon     = "🌡"
    category = "Utility"

    def default_params(self):
        return {
            "setpoint":    25.000,
            "wait_stable": 10,
            "tolerance":   0.100,
        }

    def run(self, params, devices, progress_cb, log_cb):
        tec = self._check_device(devices, "tec", log_cb)

        setpoint  = float(params.get("setpoint",    25.0))
        wait_s    = float(params.get("wait_stable", 10))
        tolerance = float(params.get("tolerance",   0.1))

        log_cb(
            f"Set TEC {setpoint:.3f}°C  wait={wait_s}s  tol=±{tolerance}°C", "info")

        if tec:
            try:
                tec.set_temp(setpoint)
                tec.output_on()
                log_cb(f"TEC setpoint → {setpoint:.3f}°C", "info")
            except Exception as e:
                log_cb(f"TEC set error: {e}", "error")
                return False

        # Wait for stable
        deadline = time.time() + wait_s
        steps = max(10, int(wait_s * 2))
        step_t = wait_s / steps

        for i in range(steps):
            if self.is_aborted(): break
            self._sleep(step_t)
            progress_cb(int((i+1)/steps*100))

            if tec:
                try:
                    actual = tec.get_temp()
                    delta  = abs(actual - setpoint)
                    log_cb(
                        f"  TEC: {actual:.3f}°C  Δ={delta:.3f}°C", "info")
                    if delta <= tolerance:
                        log_cb(f"TEC stable at {actual:.3f}°C", "ok")
                        break
                except: pass
            else:
                # Simulate ramp
                simulated = setpoint + (25.0 - setpoint) * np.exp(
                    -(i+1) / (steps * 0.3))
                log_cb(f"  TEC (sim): {simulated:.3f}°C", "info")
                if abs(simulated - setpoint) < tolerance:
                    log_cb(f"TEC stable (simulated)", "ok")
                    break

        if self.is_aborted():
            log_cb("Set TEC aborted", "warn")
            return False

        progress_cb(100)
        log_cb(f"Set TEC done", "ok")
        return True


# ══════════════════════════════════════════════
class WagoIOBlock(BaseBlock):
    name     = "WAGO IO"
    icon     = "⚡"
    category = "IO"

    def default_params(self):
        return {
            "channel":  "",
            "action":   "ON",
            "pulse_ms": 500,
            "verify":   "Yes",
        }

    def run(self, params, devices, progress_cb, log_cb):
        import time
        wago    = devices.get("wago")
        channel = params.get("channel","").strip()
        action  = params.get("action","ON").upper()
        pulse_ms = int(params.get("pulse_ms", 500))
        verify  = params.get("verify","Yes") == "Yes"

        if not channel:
            log_cb("WAGO IO: no channel specified","error")
            return False

        log_cb(
            f"WAGO IO: {channel} → {action}"
            f"{f' {pulse_ms}ms' if action=='PULSE' else ''}","info")

        if wago:
            try:
                if action == "ON":
                    wago.write_do_by_name(channel, True)
                elif action == "OFF":
                    wago.write_do_by_name(channel, False)
                elif action == "PULSE":
                    wago.write_do_by_name(channel, True)
                    self._sleep(pulse_ms/1000.0)
                    wago.write_do_by_name(channel, False)

                if verify and action != "PULSE":
                    time.sleep(0.05)
                    actual   = wago.read_do_by_name(channel)
                    expected = action == "ON"
                    if actual != expected:
                        log_cb(
                            f"WAGO IO verify failed: {channel} "
                            f"expected {expected} got {actual}","error")
                        return False
                    log_cb(f"WAGO IO verify OK: {channel}","ok")

            except Exception as e:
                log_cb(f"WAGO IO error: {e}","error")
                return False
        else:
            log_cb(f"WAGO IO (sim): {channel} → {action}","warn")
            if action == "PULSE":
                self._sleep(pulse_ms/1000.0)

        progress_cb(100)
        return True
