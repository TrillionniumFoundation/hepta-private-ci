"""Fresh reviewer-selected eight-fit exact-layout and boundary controls."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import time

os.sched_setaffinity(0, {1})
started = time.process_time()
import numpy as np
from ..planner_fastpath_r18_20261101.planner import BatchedPlanner
from ..support_retention_r16_20261101.compression import BlockLaw
from .planner import BatchOwnedPlanner

HERE = Path(__file__).resolve().parent
protocol = json.loads((HERE / "PROTOCOL.json").read_text())
rows, controls, checks = [], [], 0
for fit in protocol["fits"]:
    path = HERE.parent / f"addressed_decision_r15_20261101/run_01/training/{fit}.json.gz"
    models = json.loads(gzip.decompress(path.read_bytes()))["calibration"]["models"]
    for model in protocol["models"]:
        law = BlockLaw.from_payload(models[model]["payload"])
        rng = np.random.default_rng([2001431, fit, len(model)])
        beliefs = [law.prior.copy(), np.eye(40)[32], rng.dirichlet(np.full(40, .1))]
        for projection in ("full", "block"):
            for dt in (.25, .95):
                old = BatchedPlanner(law, dt, 0., 0., projection=projection, anchored=projection == "block")
                new = BatchOwnedPlanner(law, dt, 0., 0., projection=projection, anchored=projection == "block")
                for belief_index, p in enumerate(beliefs):
                    p.flags.writeable = False
                    before = p.tobytes()
                    for remaining in (1, 2, 3):
                        a, b = old.values(p, remaining), new.values(p, remaining)
                        assert a == b and p.tobytes() == before
                        assert max(a, key=a.get) == max(b, key=b.get)
                        assert old.answer(p, remaining) == new.answer(p, remaining)
                        rows.append(dict(fit=fit, model=model, projection=projection, dt=dt,
                                         belief=belief_index, remaining=remaining, values=a))
                        checks += 4
            # Every predicate is compared on either side of original boundaries.
            for count in (1, 3):
                for kind in ("finite", "nan", "negative_below", "negative_above", "mass_below", "mass_above", "positive_underflow"):
                    p = np.full(40, 1 / 40)
                    if kind == "nan":
                        p[0] = np.nan
                    elif kind.startswith("negative"):
                        p[0] = np.nextafter(-1e-13, -np.inf if kind.endswith("below") else np.inf)
                        p[1] += 1 / 40 - p[0]
                    elif kind.startswith("mass"):
                        p[0] += np.nextafter(2e-11, -np.inf if kind.endswith("below") else np.inf)
                    elif kind == "positive_underflow":
                        p[:] = 0.
                        p[0], p[1] = np.nextafter(0., 1.), 1.
                    outcomes = []
                    for planner in (old, new):
                        try:
                            result = planner._project_many([p[None, :]] * count)
                            outcomes.append([r.tolist() for r in result])
                        except ValueError:
                            outcomes.append("ValueError")
                    assert outcomes[0] == outcomes[1]
                    controls.append(dict(fit=fit, model=model, projection=projection,
                                         frames=count, kind=kind, accepted=outcomes[0] != "ValueError"))
                    checks += 1
result = dict(passed=True, value_cases=len(rows), predicate_controls=len(controls), checks=checks,
              rows=rows, controls=controls, measured_body_cpu_seconds=time.process_time() - started,
              reviewer_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              frozen_manifest_sha256=hashlib.sha256((HERE / "SOURCE_MANIFEST.json").read_bytes()).hexdigest(),
              scope="Independent reviewer-selected sparse/recovery/read-only and near-boundary controls across all eight fitted seeds. Exact R18 differential; not a new numerical generator reference or efficacy experiment.")
raw = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
with (HERE / "INDEPENDENT_NUMERIC_REVIEW.json.gz").open("xb") as stream:
    stream.write(gzip.compress(raw, mtime=0))
