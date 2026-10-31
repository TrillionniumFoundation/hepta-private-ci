"""Freeze the exact-execution candidate and predeclared paired comparisons."""

import argparse
import json
from pathlib import Path
import time

from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.control.registry import asset_pins
from .run import POLICIES


HERE = Path(__file__).resolve().parent


def freeze(asset, output, *, development=False, allocation=None, cache=None, pairs=512):
    base = HERE.parents[1]
    paths = list(HERE.glob("*.py"))
    for group in ("abc_recovery", "abc_next", "abc_followup/control", "v6", "v7", "closure_20261025/control"):
        paths.extend((base / group).glob("*.py"))
    paths.append(base / "abc_followup/control/PROTOCOL-v2.json")
    fixed = {str(p.resolve()): file_sha(p) for p in sorted(set(paths))}
    fixed.update(asset_pins(asset))
    fixed[str(asset / "abc2-runs/source-recovery-001/source-manifest.json")] = file_sha(asset / "abc2-runs/source-recovery-001/source-manifest.json")
    source = {"kind": "historical_development", "role": "forecast_calibration", "offset": 448, "pairs": pairs}
    if not development:
        if allocation is None or cache is None: raise ValueError("Fresh source allocation required")
        source = {"kind": "prospective_qmnist", "role": "next_control", "offset": 0, "pairs": pairs,
                  "cache": str(cache.resolve()), "allocation": str(allocation.resolve())}
        fixed[str(allocation.resolve())] = file_sha(allocation)
        fixed[str(HERE.parent / "sources.py")] = file_sha(HERE.parent / "sources.py")
    record = {"schema": "hepta.next.exact-control-protocol.v1", "registered_unix_ns": time.time_ns(),
        "study": "control", "frozen_sha256": fixed, "frozen_candidate_sha256": fixed,
        "source_allocation_sha256": file_sha(allocation) if allocation else None,
        "source": source, "seeds": [17] if development else [17, 29, 43], "draws": 1 if development else 2,
        "policies": list(POLICIES), "training_performed": False,
        "candidate": "Frozen tensor graph of the unchanged old conditional-moment teacher; near-tie original fallback at 1e-5",
        "evaluation": {"initial_namespace": "next-exact-initial-v1", "future_namespace": "next-exact-future-v1",
                       "observation_namespace": "next-exact-observation-v1", "order_seed": 202610251401},
        "inference": {"gamma": 2., "replicates": 4000, "bootstrap_seed": 202610251402,
            "level": .975, "noninferiority_CE": -.005, "noninferiority_success": -.005,
            "prices": [0., .001, .002, .005], "failures": "retain all attempts and costs; any missing actual result blocks quality inference",
            "primary_comparisons": ["compiled_teacher minus cached_teacher: exact output parity and original CE/success NI plus actual mean-wall saving",
                                    "fresh_feedback minus stale_feedback: CE superiority and exact-success noninferiority at zero margin"],
            "secondary_comparisons": ["cached_teacher minus strong_nonfeedback", "cached_teacher minus fixed_allocation"],
            "feedback_scope": "Identical teacher and root action; both branches read current draft and execute both current/delayed moment evaluations. Only H1 choice differs. Delayed inputs may be outside the fit distribution; not an optimal value-of-information theorem.",
            "cost_scope": "Actual request includes input/sensor/features/head, generations, durable choice and terminal readback; compilation/loading/diagnostic archives/scoring included in process receipt separately",
            "clusters": "QMNIST writer identity, with all source pairs/views/draws and fixed trained-seed panel kept together"}}
    if output.exists(): raise FileExistsError("Never overwrite a frozen protocol")
    write_json(output, record)
    print(json.dumps({"path": str(output), "sha256": file_sha(output), "source": source}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--development", action="store_true")
    p.add_argument("--allocation", type=Path)
    p.add_argument("--cache", type=Path)
    p.add_argument("--pairs", type=int, default=512)
    a = p.parse_args(); freeze(a.asset_root, a.output, development=a.development, allocation=a.allocation, cache=a.cache, pairs=a.pairs)
