"""Paired retrospective damage census on exact original source and numerical receipts.

Never a future-window evaluation, NDU verifier, model selector or production gate.
The independent original evaluator first checks complete physical logits and publisher CAL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from v18_original_independent_review import ARCHIVE_SHA, ARMS, Invalid, verify

SCHEMA = "hepta.stem.v18.paired-damage.v1"
SEEDS = (41, 47, 53)


def stats_from_logits(base_logits, candidate_logits, labels):
    """Only paired single-cohort retrospective comparisons; no CI/significance claim."""
    a = np.asarray(base_logits, dtype=np.float64)
    b = np.asarray(candidate_logits, dtype=np.float64)
    y = np.asarray(labels)
    if (a.ndim != 2 or a.shape[1] != 4 or a.shape != b.shape
            or y.shape != (len(a),) or len(a) < 1 or not np.isfinite(a).all()
            or not np.isfinite(b).all() or not np.issubdtype(y.dtype, np.integer)
            or np.any(y < 0) or np.any(y >= 4)):
        raise Invalid("aligned original finite logits and four-class labels required")
    pa, pb = a.argmax(1), b.argmax(1)
    old_good, new_good = pa == y, pb == y
    rescues = int((~old_good & new_good).sum())
    harmed = int((old_good & ~new_good).sum())
    def brier(logits):
        # FP64 independent stable softmax; no training/gradient imports.
        z = logits - logits.max(axis=1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(axis=1, keepdims=True)
        return np.square(p - np.eye(4, dtype=np.float64)[y]).sum(1)
    diff = brier(b) - brier(a)
    return {
        "cases": len(a), "rescued_baseline_errors": rescues,
        "damaged_baseline_correct": harmed,
        "net_correct_change": rescues - harmed,
        "same_correctness": int(len(a) - rescues - harmed),
        "mean_brier_delta_candidate_minus_baseline": round(float(diff.mean()), 9),
        "historical_gate_would_pass": bool(diff.mean() < -0.01 and harmed <= rescues),
    }


def audit(original_zip: Path, physical: Path, private_logits: Path):
    verified = verify(original_zip, physical, private_logits)
    if verified["decision"] != "RECOUNT_CONSISTENT_RESEARCH_NO_GO":
        raise Invalid("independent original source review required")
    report = json.loads(physical.read_text())
    traces = json.loads(private_logits.read_text())
    with ZipFile(original_zip) as z:
        source = z.read("hepta-public-study/dataset.jsonl")
    calibration = [json.loads(b)["label"] for b in source.splitlines()
                   if json.loads(b)["split"] == "calibration"]
    if len(calibration) != 32 or any(type(v) is not int or v not in range(4) for v in calibration):
        raise Invalid("32 publisher-labelled historical CAL cases required")
    traces_by_key = {(r["seed"], r["arm"]): r for r in traces["records"]}
    if len(traces_by_key) != len(traces["records"]) or len(traces_by_key) != len(SEEDS) * len(ARMS):
        raise Invalid("complete nonduplicate source-bound inference required")
    out = {}
    for seed in SEEDS:
        panel = report["seeds"][SEEDS.index(seed)]
        if panel["seed"] != seed:
            raise Invalid("seed-order drift")
        baseline = traces_by_key[(seed, "no_change")]["logits"]["calibration"]
        outcomes = {}
        for arm in sorted(ARMS - {"no_change"}):
            raw = traces_by_key[(seed, arm)]["logits"]["calibration"]
            stats = stats_from_logits(baseline, raw, calibration)
            claimed = panel["arms"][arm]
            if claimed["train_steps"] != 160 or claimed["owned_extra_params"] <= 0:
                raise Invalid("actual extra Head training and parameter cost required")
            for phase in ("extra_training_cpu_ns", "inference_cpu_ns"):
                v = claimed[phase]
                if type(v) is not int or v <= 0:
                    raise Invalid("physical positive per-phase CPU receipt required")
            stats["extra_head_train_cpu_ms"] = round(claimed["extra_training_cpu_ns"] / 1e6, 4)
            stats["additional_parameter_scalars"] = claimed["owned_extra_params"]
            outcomes[arm] = stats
        out[str(seed)] = outcomes
    # The original record contains only one previously exposed public dataset family;
    # repeating seeds/questions does not produce independent families/windows.
    return {
        "schema": SCHEMA,
        "original_source_zip_sha256": ARCHIVE_SHA,
        "original_report_sha256": hashlib.sha256(physical.read_bytes()).hexdigest(),
        "original_private_logit_sha256": hashlib.sha256(private_logits.read_bytes()).hexdigest(),
        "original_calibration_cases_per_seed": 32,
        "independent_dataset_families_observed": 1,
        "prospective_windows_observed": 0,
        "scored_blind_cases": 0,
        "per_seed_paired_damage": out,
        "research_only": True, "production_authorized": False,
        "future_utility_verified": False, "cell_split_authorized": False,
        "decision": "NO_INVEST_FROM_EXPOSED_HISTORICAL_CALIBRATION",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--physical", type=Path, required=True)
    p.add_argument("--private-logits", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = audit(args.archive, args.physical, args.private_logits)
    with args.output.open("x") as f:
        json.dump(result, f, sort_keys=True, indent=2, allow_nan=False)
    print(result["decision"])


if __name__ == "__main__":
    main()
