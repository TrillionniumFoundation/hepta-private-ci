"""Actual process/descendant CPU and bounded next-operation admission.

The complete clock starts at process birth, not after imports. Reservations are
forecasts; overruns remain failures. Publication analysis is outside this ledger.
"""

import resource
import time
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class AdmissionRefused(BudgetExceeded):
    """A forecast does not fit; the actual cap is still intact."""


def cpu_ns():
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time_ns() + round((child.ru_utime + child.ru_stime) * 1e9)


def rss_bytes():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


class Budget:
    def __init__(self, output, *, clock=cpu_ns, memory=rss_bytes,
                 total_ns=1800_000_000_000, byte_cap=2**31, rss_cap=2**31):
        self.output = Path(output)
        self.clock, self.memory = clock, memory
        self.total_ns, self.byte_cap, self.rss_cap = total_ns, byte_cap, rss_cap
        self.rows = []

    def used_bytes(self):
        return sum(p.stat().st_size for p in self.output.rglob("*") if p.is_file())

    def check(self, quote_ns=0, *, start_ns=0, phase_ns=None, tail_ns=0,
              phase_tail_ns=0, extra_bytes=0):
        values = (quote_ns, tail_ns, phase_tail_ns, extra_bytes)
        if any(type(v) is not int or v < 0 for v in values):
            raise ValueError("nonnegative integer reservations required")
        now = self.clock()
        if now > self.total_ns:
            raise BudgetExceeded("actual complete CPU cap exceeded")
        if phase_ns is not None and now - start_ns > phase_ns:
            raise BudgetExceeded("actual phase CPU cap exceeded")
        if self.memory() > self.rss_cap:
            raise BudgetExceeded("RSS cap exceeded")
        if self.used_bytes() > self.byte_cap:
            raise BudgetExceeded("retained payload cap exceeded")
        if now + quote_ns + tail_ns > self.total_ns:
            raise AdmissionRefused("complete CPU forecast refused")
        if phase_ns is not None and now - start_ns + quote_ns + phase_tail_ns > phase_ns:
            raise AdmissionRefused("phase CPU forecast refused")
        if self.used_bytes() + extra_bytes > self.byte_cap:
            raise AdmissionRefused("retained payload forecast refused")
        return now

    def row(self, name, before, **details):
        after = self.check()
        record = {"stage": name, "start_cpu_ns": before,
                  "end_cpu_ns": after, "cpu_ns": after - before, **details}
        self.rows.append(record)
        return record

    def snapshot(self):
        return {"process_plus_descendant_CPU_ns": self.clock(),
                "peak_RSS_bytes": self.memory(), "retained_bytes": self.used_bytes(),
                "cap_CPU_ns": self.total_ns, "cap_RSS_bytes": self.rss_cap,
                "cap_retained_bytes": self.byte_cap, "stages": self.rows,
                "boundary": "Whole process since birth plus reaped descendants; method imports, receipt and export are charged. Outer supervisor adds its own CPU separately."}
