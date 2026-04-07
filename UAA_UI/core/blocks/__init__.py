"""
Block Registry
===============
Import ทุก block แล้ว register ใน BLOCK_REGISTRY
Engineer เพิ่ม block ใหม่ที่นี่ที่เดียว
"""

from .base_block       import BaseBlock
from .coarse_scan      import CoarseScanBlock
from .fine_align       import FineAlignBlock
from .tilt_correction  import TiltCorrectionBlock
from .utility_blocks   import (
    DispenseBlock,
    UVCureBlock,
    VerifyBlock,
    MoveBlock,
    WaitBlock,
    SetTECBlock,
    WagoIOBlock,
)

# Registry: ชื่อ step → block instance
BLOCK_REGISTRY: dict[str, BaseBlock] = {
    b.name: b() for b in [
        CoarseScanBlock,
        FineAlignBlock,
        TiltCorrectionBlock,
        DispenseBlock,
        UVCureBlock,
        VerifyBlock,
        MoveBlock,
        WaitBlock,
        SetTECBlock,
        WagoIOBlock,
    ]
}

__all__ = [
    "BaseBlock",
    "BLOCK_REGISTRY",
    "CoarseScanBlock",
    "FineAlignBlock",
    "TiltCorrectionBlock",
    "DispenseBlock",
    "UVCureBlock",
    "VerifyBlock",
    "MoveBlock",
    "WaitBlock",
    "SetTECBlock",
    "WagoIOBlock",
]
