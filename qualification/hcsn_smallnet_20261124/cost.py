"""Process cost and hardware-energy availability without substituting estimates."""

import glob
import os
from pathlib import Path
import sys
import time

try:
    import resource
except ImportError:
    resource = None


class CostMeter:
    def __init__(self, scope='operation_body'):
        self.wall = time.perf_counter()
        self.cpu = time.process_time()
        self.energy = self._energy()
        self.scope = scope

    @staticmethod
    def _energy():
        records = {}
        for name in glob.glob('/sys/class/powercap/intel-rapl:*/energy_uj'):
            p = Path(name)
            try:
                records[name] = {'microjoules': int(p.read_text()),
                                 'range': int((p.parent / 'max_energy_range_uj').read_text())}
            except (OSError, ValueError):
                continue
        return records

    def snapshot(self):
        current = self._energy()
        packages = {}
        for path, before in self.energy.items():
            if path in current and before['range'] > 0:
                packages[path] = ((current[path]['microjoules'] - before['microjoules'])
                                  % before['range']) / 1e6
        peak_rss_kib = None
        if resource is not None:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_rss_kib = peak / 1024 if sys.platform == 'darwin' else peak
        return {'wall_seconds': time.perf_counter() - self.wall,
                'cpu_seconds': time.process_time() - self.cpu,
                'scope': self.scope,
                'clock_boundary': 'meter construction through snapshot; imports before construction and final receipt serialization excluded',
                'complete_worker_cost': False,
                'process_max_rss_kib': peak_rss_kib,
                'rss_scope': 'process lifetime peak, including imports; unavailable on platforms without resource',
                'pid': os.getpid(), 'energy_joules_process': None,
                'package_energy_joules': packages or None,
                'energy_scope': ('shared package counters; other host work may overlap'
                                 if packages else 'no readable hardware energy counter'),
                'energy_multiple_wraps_resolved': False}
