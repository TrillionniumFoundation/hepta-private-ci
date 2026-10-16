"""Fail-closed source-only paired Head investment audit; never a production authorizer."""
import hashlib
import json
import math
from collections import defaultdict

SCHEMA = "hepta.stem.learning-investment.v18"
ARMS = ("no_change", "linear", "gated_residual", "continued_single", "split_router")
PHASES = ("encoder", "feature_cache", "head_train", "head_infer", "router", "reader", "evaluation", "persistence", "recovery")

class Invalid(ValueError):
    pass

def _nonnegative(x):
    if type(x) not in (int, float) or not math.isfinite(x) or x < 0:
        raise Invalid("finite nonnegative cost required")
    return float(x)

def _sha(x):
    if not isinstance(x, str) or len(x) != 64 or any(c not in "0123456789abcdef" for c in x):
        raise Invalid("sha256 required")

def audit(p):
    if not isinstance(p, dict) or set(p) != {"schema", "source_sha256", "model_sha256", "registration_sha256", "observations", "costs", "authority"} or p["schema"] != SCHEMA:
        raise Invalid("exact research schema required")
    for k in ("source_sha256", "model_sha256", "registration_sha256"):
        _sha(p[k])
    if p["authority"] != {"production_authorized": False, "source_attested": False, "final_use_authorized": False}:
        raise Invalid("no attestation or authorization may be asserted")
    rows = p["observations"]
    if not isinstance(rows, list) or not rows:
        raise Invalid("paired observations required")
    seen, cases, identity, roots = set(), defaultdict(dict), {}, defaultdict(set)
    for r in rows:
        if not isinstance(r, dict) or set(r) != {"arm", "case_id", "root_id", "cohort", "correct", "old_task"}:
            raise Invalid("exact row fields required")
        a, c, root, cohort = r["arm"], r["case_id"], r["root_id"], r["cohort"]
        if a not in ARMS or any(not isinstance(s, str) or not s or len(s) > 128 for s in (c, root)) or cohort not in ("train", "calibration") or type(r["correct"]) is not bool or type(r["old_task"]) is not bool:
            raise Invalid("invalid row identity or unverified future cohort")
        if (a, c) in seen:
            raise Invalid("duplicate row")
        seen.add((a, c))
        key = (root, cohort, r["old_task"])
        if c in identity and identity[c] != key:
            raise Invalid("case attribution drift")
        identity[c] = key
        cases[c][a] = r["correct"]
        roots[cohort].add(root)
    if any(set(v) != set(ARMS) for v in cases.values()):
        raise Invalid("unpaired arms")
    costs = p["costs"]
    if not isinstance(costs, dict) or set(costs) != set(ARMS):
        raise Invalid("complete arm cost matrix required")
    totals = {}
    for a, phases in costs.items():
        if not isinstance(phases, dict) or set(phases) != set(PHASES):
            raise Invalid("complete lifecycle cost phases required")
        totals[a] = sum(_nonnegative(phases[k]) for k in PHASES)
    future = [v for c, v in cases.items() if identity[c][1] == "future"]
    old = [v for c, v in cases.items() if identity[c][2]]
    comparison = {}
    for a in ARMS[1:]:
        comparison[a] = {
            "future_paired_net_correct": sum(int(v[a])-int(v["no_change"]) for v in future),
            "old_task_lost_correct": sum(int(v["no_change"] and not v[a]) for v in old),
            "incremental_cpu_seconds": round(totals[a] - totals["no_change"], 9)
        }
    digest = hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"schema": SCHEMA, "packet_sha256": digest, "root_counts": {k: len(roots[k]) for k in ("train", "calibration", "future")}, "future_case_count": len(future), "comparisons": comparison, "research_only": True, "production_authorized": False, "model_selection_authorized": False, "cell_split_authorized": False, "decision": "DENY_ALL_UNATTESTED_RESEARCH"}
