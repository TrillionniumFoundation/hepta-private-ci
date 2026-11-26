"""Versioned R20 branch-and-bound with stable frontier node identities.

Only the frozen v1 interval arithmetic and bisection are reused.  The v1 solver,
its seven-source qualification, and its archived frontier bytes stay unchanged.
"""

import argparse
from fractions import Fraction as F
import hashlib
from heapq import heappop, heappush
import json
import os
from pathlib import Path
import time
from types import ModuleType


LEGACY_SHA256 = "6e2e53fa05fd43e5f76d980beabaa765c0e88eb8dce27c682c7b42b507c5c1cc"
LEGACY_GIT_BLOB = "e6639540484b4259464e0fdbe1a5f775b31581ec"
SCHEMA = "hepta.ndu.r20.direct-interval-global-bnb.v2"


def _load_legacy(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    if digest != LEGACY_SHA256 or blob != LEGACY_GIT_BLOB:
        raise ValueError("frozen R20 interval source mismatch: " + digest + "/" + blob)
    module = ModuleType("_hepta_r20_frozen_interval_arithmetic")
    module.__file__ = str(path)
    # Compile the bytes just verified; do not reread a mutable path for import.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


_LEGACY_PATH = os.environ.get(
    "NDU_R20_LEGACY_SOURCE",
    str(Path(__file__).resolve().parent.parent / "direct_interval" / "global_interval.py"),
)
_LEGACY = _load_legacy(_LEGACY_PATH)
cost_bounds = _LEGACY.cost_bounds
bisect = _LEGACY.bisect
DOMAIN = _LEGACY.DOMAIN


def bnb(a, b, extra=True, threshold=F(1, 100), node_cap=50000, store_frontier=None):
    if node_cap <= 0 or threshold <= 0:
        raise ValueError("cap")
    t0 = time.perf_counter()
    candidate_box = (F(a), F(a), F(b), F(b))
    c_lower, c_upper = cost_bounds(candidate_box, extra)
    if c_upper >= F(9, 4):
        raise ValueError("outside box not excluded")
    root = (-DOMAIN, DOMAIN, -DOMAIN, DOMAIN)
    root_bound = cost_bounds(root, extra)[0]
    queue = [(float(root_bound), 0, root_bound, root)]
    seq = 0
    split = 0
    while queue and split < node_cap:
        node = heappop(queue)
        _, _, bound, box = node
        if c_upper - bound <= threshold:
            # This is the same node, not a new allocation.  Keep its entire tuple.
            heappush(queue, node)
            break
        for newbox in bisect(box):
            lo = cost_bounds(newbox, extra)[0]
            if lo >= c_upper:
                continue
            seq += 1
            heappush(queue, (float(lo), seq, lo, newbox))
        split += 1
    if len({row[1] for row in queue}) != len(queue):
        raise ValueError("duplicate frontier node identity")
    lb = min((row[2] for row in queue), default=c_lower)
    lb = min(lb, c_lower)
    gap = max(F(0), c_upper - lb)
    receipt = dict(
        schema=SCHEMA,
        arithmetic_source_sha256=LEGACY_SHA256,
        arithmetic_source_git_blob=LEGACY_GIT_BLOB,
        frontier_id_policy="creation-sequence-preserved-on-stop",
        candidate_a=str(F(a)),
        candidate_b=str(F(b)),
        extra_coupling=extra,
        candidate_cost_lower=str(c_lower),
        candidate_cost_rigorous_upper=str(c_upper),
        global_cost_lower=str(lb),
        global_regret_upper=str(gap),
        threshold=str(threshold),
        passes_frozen_global_threshold=gap <= threshold,
        bnb_node_cap=node_cap,
        nodes_split=split,
        frontier_count=len(queue),
        full_domain_covered=True,
        outside_box_lower="9/4",
        generic_parameter_space_convexity_assumed=False,
        strong_convex_auxiliary_used=False,
        nested_risk_lower="logcosh z >= max(0,z^2/2-z^4/12)",
        nested_risk_upper="logcosh z <= z^2/2",
        exact_arithmetic="Python Fraction",
        priority_only_uses_float=True,
        unique_optimum_proven=False,
        wall=time.perf_counter() - t0,
    )
    if store_frontier:
        path = Path(store_frontier)
        with path.open("x") as handle:
            for _, node_id, lower, box in sorted(queue, key=lambda row: row[1]):
                row = dict(id=node_id, lower=str(lower), box=list(map(str, box)))
                handle.write(json.dumps(row) + "\n")
        receipt["frontier_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frontier", type=Path)
    parser.add_argument("--a", default="1.64")
    parser.add_argument("--b", default=".42")
    parser.add_argument("--control", action="store_true")
    parser.add_argument("--threshold", default="1/100")
    parser.add_argument("--cap", type=int, default=50000)
    args = parser.parse_args()
    result = bnb(F(args.a), F(args.b), not args.control, F(args.threshold), args.cap, args.frontier)
    with args.out.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print({key: result[key] for key in (
        "schema", "nodes_split", "frontier_count", "global_regret_upper",
        "passes_frozen_global_threshold", "wall",
    )})
