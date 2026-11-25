"""Independent train-only forward/backward equivalence check of operator reuse."""
import argparse
from dataclasses import asdict
import itertools
from pathlib import Path
import time

from common import (FIELDS, data, dump, forward, make_model, select, sha, torch, utc, validate_sources)
from optimized import CachedSmallHCSN


def observation(model, batch):
    model.zero_grad(set_to_none=True)
    start = time.perf_counter()
    logits, features, state = forward(model, batch)
    objective = logits.square().mean() + .01 * features.square().mean() + .001 * state.density.square().mean()
    objective.backward()
    elapsed = time.perf_counter() - start
    gradients = {name: p.grad.detach().clone() for name, p in model.named_parameters() if p.grad is not None}
    return {"logits": logits.detach(), "features": features.detach(),
            **{name: getattr(state, name).detach() for name in FIELDS}}, gradients, elapsed


def run(output):
    out = Path(output)
    out.mkdir(exist_ok=False)
    dump(out / "PROTOCOL.json", {"scope": "train-only differentiable operator cache equivalence",
        "registered_utc": utc(), "source": validate_sources(), "source_sha256": sha(__file__),
        "optimized_sha256": sha(Path(__file__).with_name("optimized.py")),
        "forward_abs_tolerance": 1e-12, "gradient_abs_scaled_tolerance": 1e-9,
        "test_created": False})
    batch = select(data("train"), range(2))
    rows = []
    for width, bank, message in itertools.product((8, 16, 32, 64), ("value_risk", "tanh"), ("boundary", "flow", "full")):
        base = make_model(width, 1701, bank, message)
        cached = CachedSmallHCSN(base.config)
        cached.load_state_dict(base.state_dict())
        a, ga, ta = observation(base, batch)
        b, gb, tb = observation(cached, batch)
        errors = {name: float((a[name] - b[name]).abs().max()) for name in a}
        gradients = {name: float((ga[name] - gb[name]).abs().max()) for name in ga}
        scaled = {name: gradients[name] / max(1., float(ga[name].abs().max())) for name in ga}
        rows.append({"width": width, "bank": bank, "message": message,
                     "forward_errors": errors, "gradient_errors": gradients,
                     "gradient_scaled_errors": scaled, "gradient_names_equal": sorted(ga) == sorted(gb),
                     "base_forward_backward_wall_s": ta, "cached_forward_backward_wall_s": tb,
                     "dense_matrix_exp_evaluations": cached.operator_evaluations,
                     "operator_reuses": cached.operator_cache_hits,
                     "passed": max(errors.values()) <= 1e-12 and max(scaled.values()) <= 1e-9 and sorted(ga) == sorted(gb)})
    result = {"scope": "24 small train-only forward/backward comparisons, not exhaustive equivalence proof",
              "protocol_sha256": sha(out / "PROTOCOL.json"), "rows": rows,
              "passed": all(row["passed"] for row in rows), "test_created": False}
    dump(out / "RESULT.json", result)
    print({"passed": result["passed"], "rows": len(rows),
           "max_forward_error": max(max(r["forward_errors"].values()) for r in rows),
           "max_gradient_error": max(max(r["gradient_errors"].values()) for r in rows)})
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    raise SystemExit(run(p.parse_args().out))
