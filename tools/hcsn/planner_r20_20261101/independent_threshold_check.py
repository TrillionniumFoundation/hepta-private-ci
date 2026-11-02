"""Representable row masses straddling the unchanged probability tolerance."""

import hashlib
import json
import os
from pathlib import Path
import time

os.sched_setaffinity(0, {1})
started = time.process_time()
import numpy as np
from ..addressed_decision_r15_20261101.law import Law
from ..planner_fastpath_r18_20261101.planner import BatchedPlanner
from .planner import BatchOwnedPlanner

law, rows = Law(), []
for projection in ("full", "block"):
    planners = [kind(law, .5, projection=projection) for kind in (BatchedPlanner, BatchOwnedPlanner)]
    for count in (1, 3):
        for direction in (-np.inf, np.inf):
            p = np.zeros(40)
            p[0] = np.nextafter(1. + 2e-11, direction)
            error = float(abs(p.sum() - 1.))
            expected = error <= 2e-11
            outcomes = []
            for planner in planners:
                try:
                    planner._project_many([p[None, :]] * count)
                    outcomes.append(True)
                except ValueError:
                    outcomes.append(False)
            assert outcomes == [expected, expected]
            rows.append(dict(projection=projection, frames=count, row_sum=float(p.sum()),
                             actual_row_error=error, expected=expected, outcomes=outcomes))
assert {row["expected"] for row in rows} == {True, False}
result = dict(passed=True, cases=rows, measured_body_cpu_seconds=time.process_time() - started,
              reviewer_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              note="Supplement: nominal nextafter(2e-11) deltas in INDEPENDENT_NUMERIC_REVIEW round to the same row-sum side after addition to0.025. These cases instead nextafter the complete1+2e-11 mass and verify actual computed errors straddle the threshold. Original cases remain preserved.")
with Path(__file__).with_name("INDEPENDENT_THRESHOLD_REVIEW.json").open("x") as stream:
    json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
