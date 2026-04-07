"""
BaseBlock — Abstract base class for all process blocks
========================================================
Engineer สร้าง block ใหม่ได้โดย inherit class นี้
แล้ว implement 3 methods: default_params, validate, run
"""

import threading
from abc import ABC, abstractmethod
from typing import Callable, Dict, Any, Tuple


class BaseBlock(ABC):
    """
    Abstract base สำหรับทุก process block

    Usage:
        class MyBlock(BaseBlock):
            name = "My Step"
            icon = "🔧"

            def default_params(self):
                return {"speed": 1.0, "distance": 0.5}

            def validate(self, params):
                if params["speed"] <= 0:
                    return False, "speed must be > 0"
                return True, ""

            def run(self, params, devices, progress_cb, log_cb):
                log_cb("Starting...", "info")
                # do work
                progress_cb(100)
    """

    # ── Class attributes (override ใน subclass) ──
    name: str = "Base Block"
    icon: str = "▸"
    category: str = "General"   # Motion / Optical / IO / Utility

    def __init__(self):
        self._abort_event = threading.Event()

    # ── Abstract methods ──────────────────────────

    @abstractmethod
    def default_params(self) -> Dict[str, Any]:
        """Return default parameter dict"""
        ...

    @abstractmethod
    def run(self,
            params:      Dict[str, Any],
            devices:     Dict[str, Any],
            progress_cb: Callable[[int], None],
            log_cb:      Callable[[str, str], None]) -> bool:
        """
        Execute the block

        Args:
            params:      parameter dict จาก recipe
            devices:     driver references {
                            "cart":  cartesian driver,
                            "hxp1":  hexapod 1 driver,
                            "hxp2":  hexapod 2 driver,
                            "lin":   linear stage driver,
                            "smu":   SMU driver,
                            "wago":  WAGO modbus driver,
                            "tec":   TEC driver,
                            "cam":   camera object,
                         }
            progress_cb: call with int 0-100
            log_cb:      call with (message, level)
                         level: "info" / "ok" / "warn" / "error"

        Returns:
            True = success, False = failed
        """
        ...

    # ── Optional override ─────────────────────────

    def validate(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate params before run
        Returns (is_valid, error_message)
        Default: always valid
        """
        return True, ""

    def param_hints(self) -> Dict[str, dict]:
        """
        Optional: hints สำหรับ recipe editor
        {
          "range_x": {
              "label": "Range X (mm)",
              "type": "float",
              "min": 0.001, "max": 10.0,
              "step": 0.001,
          }
        }
        """
        return {}

    # ── Abort control ─────────────────────────────

    def abort(self):
        """Request abort — block ควร check is_aborted() บ่อยๆ"""
        self._abort_event.set()

    def reset_abort(self):
        self._abort_event.clear()

    def is_aborted(self) -> bool:
        return self._abort_event.is_set()

    # ── Helpers สำหรับใช้ใน subclass ─────────────

    def _check_device(self, devices, key, log_cb) -> Any:
        """ตรวจ device มีไหม ถ้าไม่มี log warning แล้ว return None"""
        drv = devices.get(key)
        if drv is None:
            log_cb(f"{self.name}: device '{key}' not connected — skipping", "warn")
        return drv

    def _sleep(self, seconds: float):
        """Sleep ที่ abort-aware ทุก 50ms"""
        import time
        steps = max(1, int(seconds / 0.05))
        for _ in range(steps):
            if self.is_aborted(): return
            time.sleep(seconds / steps)
