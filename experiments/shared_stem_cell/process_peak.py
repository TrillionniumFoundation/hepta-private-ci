"""Measured Linux whole-process RSS high-water, never a per-arm peak estimate.

ru_maxrss is KiB on Linux, process lifetime maximum including imports, model
loading, training, concurrent candidate retention and previous work in process.
Its value cannot be assigned to an individual Head arm or isolated phase.
"""
from __future__ import annotations

import sys


def linux_lifetime_peak_rss_bytes():
    if sys.platform != "linux":
        return None
    try:
        import resource
        peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, AttributeError, OSError):
        return None
    if (type(peak_kib) not in (int, float) or not (0 < peak_kib < 2**53)
            or int(peak_kib) != peak_kib):
        return None
    return int(peak_kib) * 1024
