"""
Keithley 2602B SMU - Python Driver
Interface : Ethernet (TCP/IP) port 5025
Protocol  : TSP (Test Script Processor)
Function  : Source Voltage / Measure Current (Channel A)

Requirements:
    pip install (none - uses built-in socket only)

Usage:
    smu = Keithley2602B("192.168.1.100")
    smu.connect()
    smu.setup_source_v_measure_i(
        channel="a",
        voltage=5.0,
        current_limit=0.1,
        nplc=1.0
    )
    smu.output_on()
    v, i = smu.measure()
    print(f"V = {v:.6f} V,  I = {i:.9f} A")
    smu.output_off()
    smu.disconnect()
"""

import socket
import time
import csv
import datetime


class Keithley2602B:
    """Driver for Keithley 2602B Dual-Channel SMU via Ethernet (TSP)."""

    DEFAULT_PORT    = 5025
    BUFFER_SIZE     = 4096
    RECV_TIMEOUT    = 5.0   # seconds

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = RECV_TIMEOUT):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self._sock   = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        """Open TCP connection to the instrument."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        time.sleep(0.2)
        # Flush any welcome banner
        self._sock.settimeout(0.5)
        try:
            self._sock.recv(self.BUFFER_SIZE)
        except socket.timeout:
            pass
        self._sock.settimeout(self.timeout)
        print(f"[2602B] Connected to {self.host}:{self.port}")
        idn = self.query("print(localnode.description)")
        print(f"[2602B] {idn.strip()}")

    def disconnect(self):
        """Close TCP connection."""
        if self._sock:
            self._sock.close()
            self._sock = None
            print("[2602B] Disconnected.")

    # ------------------------------------------------------------------
    # Low-level send / query
    # ------------------------------------------------------------------

    def send(self, cmd: str):
        """Send a TSP command (no response expected)."""
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.02)

    def query(self, cmd: str) -> str:
        """Send a TSP print() command and return the response string."""
        self._sock.sendall((cmd + "\n").encode())
        time.sleep(0.05)
        data = b""
        self._sock.settimeout(self.timeout)
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
        """Reset both channels to factory defaults."""
        self.send("reset()")
        time.sleep(0.5)
        print("[2602B] Reset complete.")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_source_v_measure_i(
        self,
        channel: str   = "a",
        voltage: float = 0.0,
        current_limit: float = 0.1,
        nplc: float    = 1.0,
        autorange_i: bool = True,
        sense_4wire: bool = False,
    ):
        """
        Configure one channel for Source-V / Measure-I.

        Parameters
        ----------
        channel       : "a" or "b"
        voltage       : source voltage (V)
        current_limit : compliance current (A)
        nplc          : integration time in power-line cycles (0.001 – 25)
        autorange_i   : True = auto-range current measurement
        sense_4wire   : True = 4-wire (Kelvin) remote sense
        """
        ch = channel.lower()
        if ch not in ("a", "b"):
            raise ValueError("channel must be 'a' or 'b'")

        sm = f"smu{ch}"

        cmds = [
            f"{sm}.reset()",
            # Source
            f"{sm}.source.func             = {sm}.OUTPUT_DCVOLTS",
            f"{sm}.source.levelv           = {voltage}",
            f"{sm}.source.limiti           = {current_limit}",
            f"{sm}.source.autorangev       = {sm}.AUTORANGE_ON",
            # Measure
            f"{sm}.measure.func            = {sm}.OHM_SENSE_NONE",   # V+I together
            f"{sm}.measure.nplc            = {nplc}",
        ]

        if autorange_i:
            cmds.append(f"{sm}.measure.autorangei = {sm}.AUTORANGE_ON")
        else:
            cmds.append(f"{sm}.measure.autorangei = {sm}.AUTORANGE_OFF")

        if sense_4wire:
            cmds.append(f"{sm}.sense = {sm}.SENSE_REMOTE")
        else:
            cmds.append(f"{sm}.sense = {sm}.SENSE_LOCAL")

        for cmd in cmds:
            self.send(cmd)

        self._channel = ch
        print(
            f"[2602B] Channel {ch.upper()} setup: "
            f"Source V={voltage} V, Ilimit={current_limit} A, "
            f"NPLC={nplc}, 4W={'ON' if sense_4wire else 'OFF'}"
        )

    # ------------------------------------------------------------------
    # Output control
    # ------------------------------------------------------------------

    def output_on(self, channel: str = None):
        ch = channel.lower() if channel else self._channel
        self.send(f"smu{ch}.source.output = smu{ch}.OUTPUT_ON")
        time.sleep(0.1)
        print(f"[2602B] Channel {ch.upper()} OUTPUT ON")

    def output_off(self, channel: str = None):
        ch = channel.lower() if channel else self._channel
        self.send(f"smu{ch}.source.output = smu{ch}.OUTPUT_OFF")
        print(f"[2602B] Channel {ch.upper()} OUTPUT OFF")

    def set_voltage(self, voltage: float, channel: str = None):
        """Change source voltage on-the-fly (output must be ON)."""
        ch = channel.lower() if channel else self._channel
        self.send(f"smu{ch}.source.levelv = {voltage}")

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------

    def measure(self, channel: str = None) -> tuple[float, float]:
        """
        Trigger one measurement and return (voltage, current).

        Returns
        -------
        (V, I) as floats
        """
        ch = channel.lower() if channel else self._channel
        raw = self.query(
            f"print(smu{ch}.measure.iv())"
        )
        # Response: "i_value\tv_value\n"  (TSP returns I first, then V)
        parts = raw.replace(",", "\t").split()
        if len(parts) >= 2:
            i_val = float(parts[0])
            v_val = float(parts[1])
        else:
            raise ValueError(f"Unexpected response: {raw!r}")
        return v_val, i_val

    # ------------------------------------------------------------------
    # Sweep
    # ------------------------------------------------------------------

    def voltage_sweep(
        self,
        v_start: float,
        v_stop: float,
        v_step: float,
        current_limit: float = 0.1,
        nplc: float = 1.0,
        delay: float = 0.05,
        channel: str = None,
        save_csv: bool = False,
        csv_path: str = None,
    ) -> list[tuple[float, float]]:
        """
        Perform a linear voltage sweep and collect I-V data.

        Returns list of (V_actual, I_measured) tuples.
        Optionally saves to CSV.
        """
        ch = channel.lower() if channel else self._channel

        # Build voltage list
        import math
        steps = max(1, round(abs(v_stop - v_start) / abs(v_step)))
        direction = 1 if v_stop >= v_start else -1
        voltages = [v_start + direction * v_step * i for i in range(steps + 1)]

        self.setup_source_v_measure_i(
            channel=ch,
            voltage=voltages[0],
            current_limit=current_limit,
            nplc=nplc,
        )
        self.output_on(ch)

        results = []
        print(f"[2602B] Sweep {v_start}V → {v_stop}V  ({len(voltages)} points)")

        for v in voltages:
            self.set_voltage(v, ch)
            time.sleep(delay)
            v_meas, i_meas = self.measure(ch)
            results.append((v_meas, i_meas))
            print(f"  V={v_meas:+.6f} V   I={i_meas:+.3e} A")

        self.output_off(ch)

        if save_csv:
            path = csv_path or f"iv_sweep_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Voltage_V", "Current_A"])
                writer.writerows(results)
            print(f"[2602B] Saved to {path}")

        return results


# ======================================================================
# Example usage
# ======================================================================
if __name__ == "__main__":

    SMU_IP = "192.168.1.100"   # <-- แก้ IP ให้ตรงกับเครื่อง

    smu = Keithley2602B(SMU_IP)

    try:
        smu.connect()
        smu.reset()

        # --- Single-point measurement ---
        smu.setup_source_v_measure_i(
            channel       = "a",
            voltage       = 5.0,
            current_limit = 0.01,    # 10 mA compliance
            nplc          = 1.0,
            sense_4wire   = False,
        )
        smu.output_on()
        v, i = smu.measure()
        print(f"\nResult: V = {v:.6f} V,  I = {i:.6e} A\n")
        smu.output_off()

        # --- Voltage sweep (uncomment to use) ---
        # data = smu.voltage_sweep(
        #     v_start=0.0, v_stop=5.0, v_step=0.5,
        #     current_limit=0.01,
        #     save_csv=True,
        # )

    finally:
        smu.output_off()
        smu.disconnect()
