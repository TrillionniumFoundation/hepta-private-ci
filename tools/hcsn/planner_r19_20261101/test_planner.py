"""Independent frozen-input differential and read-only ownership contracts."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..planner_fastpath_r18_20261101.planner import BatchedPlanner
from .planner import OwnedPlanner


def run():
    started = time.process_time()
    law = Law()
    cases = []
    rng = np.random.default_rng(190119)
    beliefs = [law.prior.copy(), np.eye(40)[0], np.eye(40)[35]]
    beliefs += [rng.dirichlet(np.ones(40)) for _ in range(5)]
    for projection, anchored in (("full", False), ("block", True)):
        for dt in (.25, .35, .5, .65, .75, .95):
            for fee in (0., .025, .1):
                old = BatchedPlanner(law, dt, fee, 2 * fee, projection=projection, anchored=anchored)
                new = OwnedPlanner(law, dt, fee, 2 * fee, projection=projection, anchored=anchored)
                for belief_index, p in enumerate(beliefs):
                    p.setflags(write=False)
                    before = p.tobytes()
                    for remaining in range(4):
                        a, b = old.values(p, remaining), new.values(p, remaining)
                        if a != b or p.tobytes() != before:
                            raise AssertionError((projection, dt, fee, belief_index, remaining))
                        cases.append(dict(projection=projection, dt=dt, fee=fee,
                                          belief=belief_index, remaining=remaining,
                                          exact_values=a, input_sha256=hashlib.sha256(before).hexdigest()))
    # Probability failures must remain failures, including the original tiny
    # negative allowance in full mode and strict block nonnegativity.
    controls = []
    for projection in ("full", "block"):
        old = BatchedPlanner(law, .5, projection=projection)
        new = OwnedPlanner(law, .5, projection=projection)
        for kind in ("nan", "inf", "negative", "sum", "width", "tiny_negative"):
            p = law.prior.copy()
            if kind in ("nan", "inf"):
                p[0] = float(kind)
            elif kind == "negative":
                p[0] = -.01
            elif kind == "sum":
                p *= .99
            elif kind == "width":
                p = p[:-1]
            else:
                p[0] = -1e-14
                p[1] += 1e-14
            outcomes = []
            for planner in (old, new):
                try:
                    planner._project_many([p.reshape(1, -1)])
                    outcomes.append("accepted")
                except ValueError:
                    outcomes.append("rejected")
            assert outcomes[0] == outcomes[1]
            controls.append(dict(projection=projection, kind=kind, outcomes=outcomes))
    return dict(passed=True, cases=cases, controls=controls,
                measured_body_cpu_seconds=time.process_time() - started,
                scope="Deterministic engineering differential against unchanged R18; actual immutable inputs and rejection controls. Not independent efficacy worlds or new numerical reference.")


if __name__ == "__main__":
    import argparse
    import gzip

    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = json.dumps(run(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with args.output.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0))
