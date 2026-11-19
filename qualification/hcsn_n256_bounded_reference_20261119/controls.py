"""Small exact synthetic checks only; never opens the authentic N256 inputs."""

from fractions import Fraction as F
import json
from pathlib import Path
import resource
import time

from interval import require, rounded_fraction, uniformization


def check():
    tests = 0
    conversions = [(F(0), 0), (F(1), 0x3ff0000000000000),
        (F(1)+F(1, 2**53), 0x3ff0000000000000),
        (F(1)+F(3, 2**53), 0x3ff0000000000002),
        (F(1, 2**1075), 0), (F(3, 2**1075), 2),
        (F(1, 2**1022)-F(1, 2**1075), 0x0010000000000000)]
    for value, wanted in conversions:
        require(rounded_fraction(value) == wanted, "positive rounding control")
        tests += 1
        if value:
            require(rounded_fraction(-value) == (wanted | (1 << 63)), "negative rounding control")
            tests += 1
    try:
        rounded_fraction(F((1 << 54)-1)*(1 << 970))
    except ValueError:
        tests += 1
    else:
        raise ValueError("overflow was admitted")
    vectors = [[F(1), -F(1, 4)], [-F(1), F(1, 4)], [F(0), F(0)],
               [F(3, 4), F(1, 2)], [F(0), -F(2)]]
    for rows, reference in (([{}, {}], vectors),
            ([{1: F(2)}, {}], [[a, b+2*a] for a, b in vectors])):
        result, _ = uniformization(rows, vectors, 128, 96)
        for vector, expected in zip(result, reference):
            for (lo, hi), exact in zip(vector, expected):
                require(lo <= exact <= hi, "exact polynomial containment")
                tests += 1
    # Independently formed all-rational analytic enclosure of e^-1.
    term = total = F(1)
    for k in range(1, 181):
        term /= k
        total += term
    rest = term/F(181)/(1-F(1, 182))
    exp_bounds = (1/(total+rest), 1/total)
    result, _ = uniformization([{0: -F(1), 1: F(2)}, {}], vectors, 128, 192)
    for vector, (a, b) in zip(result, vectors):
        exact_first = sorted(a*x for x in exp_bounds)
        exact_second = sorted(b+2*a*(1-x) for x in exp_bounds)
        for (lo, hi), (a, b) in zip(vector, (exact_first, exact_second)):
            require(lo <= a <= b <= hi, "independent analytic interval containment")
            tests += 1
    return {"checks": tests, "synthetic_matrix_actions": 3, "authentic_n256_actions": 0,
            "model_calls": 0, "optimizer_calls": 0, "passed": True}


if __name__ == "__main__":
    start, cpu = time.perf_counter(), time.process_time()
    report = check()
    report.update(body_wall_seconds=time.perf_counter()-start, body_cpu_seconds=time.process_time()-cpu,
                  whole_process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  timer_scope="body excludes interpreter imports; full process is recorded separately")
    print(json.dumps(report), flush=True)
