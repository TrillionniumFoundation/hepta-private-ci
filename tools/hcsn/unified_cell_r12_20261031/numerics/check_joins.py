"""Independent checks at the new integral/blend/subdivision boundaries."""

import json
from pathlib import Path

import numpy as np

import experiment as ex
import stable32

root = Path(__file__).resolve().parent
rows = []
for name, edits in (("baseline", {}), ("short", {6: .01}),
                    ("extension", {6: 1e-4}), ("joint", {2: .08, 5: 1e-4, 6: .01})):
    theta = stable32.k.BASE.copy()
    for i, v in edits.items():
        theta[i] = v
    theta = theta.astype(np.float32).astype(float)
    model = stable32.StableHX([stable32.k.Dual(v, np.eye(10)[i]) for i, v in enumerate(theta)])
    limit = min(.5, 1 / model.eta.v)
    cuts = [.8 * limit, limit]
    if 8 * model.s.v < .8 * limit:
        cuts.append(8 * model.s.v)
    for cut in cuts:
        for factor in (.999999, 1., 1.000001):
            rows.append(dict(case=name, theta=theta.tolist(), state=float(np.float32(cut * factor))))
ex.write(root / "JOIN_PROTOCOL.json", dict(rows=rows, candidate_sha256=ex.sha(root / "stable32.py"),
          gates=dict(value32=8e-7, value64=2e-8, jacobian=2e-5),
          scope="Concrete new-branch risk after candidate freeze; not a held-out performance campaign"))
result = []
for row in rows:
    theta, state = row["theta"], row["state"]
    expected = np.asarray(ex.fields(theta, state, "log_distance"), float)
    tangent = ex.jac(theta, state, "log_distance", "1e-18")
    for mode in ("float32", "float64"):
        v, j = stable32.evaluate(theta, state, mode=mode, diagnostic_outside_box=True)
        ve, je = ex.error(v, expected), ex.error(j, tangent)
        result.append(dict(**row, mode=mode, actual=v.tolist(), reference=expected.tolist(),
                           jacobian=j.tolist(), reference_jacobian=tangent.tolist(),
                           value_error=ve, jacobian_error=je,
                           passed=bool(ve <= (8e-7 if mode == "float32" else 2e-8) and je <= 2e-5)))
summary = {m: dict(passed=sum(x["passed"] for x in result if x["mode"] == m), rows=len(rows),
                  max_value_error=max(x["value_error"] for x in result if x["mode"] == m),
                  max_jacobian_error=max(x["jacobian_error"] for x in result if x["mode"] == m))
           for m in ("float32", "float64")}
ex.write(root / "JOIN_RESULTS.json", dict(rows=result, summary=summary,
          candidate_sha256=ex.sha(root / "stable32.py"), protocol_sha256=ex.sha(root / "JOIN_PROTOCOL.json")))
print(json.dumps(summary, indent=2))
