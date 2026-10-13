"""Read-only host observations with explicit scope and missingness.

Linux ru_maxrss is a PROCESS-LIFETIME high water mark, not a request's own peak.
RAPL is a PACKAGE/ZONE counter, not attributable process energy. No sum of parent
and child zones and no write/reset to counters. A supplied power bound only
supports a conditional single-wrap check; it is not verified by this reader.
"""
from __future__ import annotations

import math
import platform
import resource
from pathlib import Path


def process_peak_rss_bytes():
    if platform.system() != "Linux":
        return None
    try:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value) * 1024 if value > 0 else None
    except (OSError, ValueError):
        return None


def rapl_snapshot(zone):
    if zone is None:
        return None
    try:
        root = Path(zone).resolve(strict=True)
        allowed = (Path('/sys/devices/virtual/powercap'), Path('/sys/class/powercap'))
        if not any(root.is_relative_to(p) for p in allowed):
            return None
        name = (root / 'name').read_text().strip()
        total = int((root / 'max_energy_range_uj').read_text())
        energy = int((root / 'energy_uj').read_text())
        if not name or total <= 0 or not 0 <= energy < total:
            return None
        return {'zone': str(root), 'name': name, 'range_uj': total, 'energy_uj': energy}
    except (OSError, ValueError, RuntimeError):
        return None


def rapl_delta(before, after, elapsed_ns, max_power_watts):
    """Observed interval under a declared power bound; never process attribution."""
    if before is None or after is None:
        return {'joules': None, 'reason': 'counter_unavailable', 'scope': 'rapl_zone'}
    fields = {'zone', 'name', 'range_uj', 'energy_uj'}
    if (set(before) != fields or set(after) != fields
            or any(before[k] != after[k] for k in ('zone', 'name', 'range_uj'))):
        return {'joules': None, 'reason': 'counter_identity_changed', 'scope': 'rapl_zone'}
    if (type(elapsed_ns) is not int or elapsed_ns <= 0
            or type(max_power_watts) not in (int, float)
            or not math.isfinite(max_power_watts) or max_power_watts <= 0):
        return {'joules': None, 'reason': 'power_bound_unavailable', 'scope': 'rapl_zone'}
    modulus = before['range_uj']
    if (type(modulus) is not int or modulus <= 0
            or any(type(v['energy_uj']) is not int or not 0 <= v['energy_uj'] < modulus for v in (before, after))):
        return {'joules': None, 'reason': 'invalid_counter', 'scope': 'rapl_zone'}
    possible_uj = max_power_watts * elapsed_ns / 1000
    if possible_uj >= modulus:
        return {'joules': None, 'reason': 'multiple_wrap_ambiguity', 'scope': 'rapl_zone'}
    delta = (after['energy_uj'] - before['energy_uj']) % modulus
    if delta > possible_uj:
        return {'joules': None, 'reason': 'power_bound_or_counter_reset', 'scope': 'rapl_zone'}
    return {'joules': delta / 1e6, 'reason': 'observed_under_declared_power_bound',
            'scope': 'rapl_zone', 'zone': before['zone'], 'name': before['name'],
            'power_bound_verified': False, 'process_attribution_established': False}
