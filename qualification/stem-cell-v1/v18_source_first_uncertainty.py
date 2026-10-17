"""Source-first, retrospective V17 paired uncertainty; never an NDU/FinalUse gate.

Authenticates the previously executed model tensors through the independent V17
NumPy reviewer, then treats each original CAL case as ONE resampling unit across
all three correlated seeds. No held labels, prospective cases or training.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import stem_identity_alignment_v17_review as predecessor

SCHEMA = "hepta.stem.v18.source-first-uncertainty.research"
SEEDS = ("41", "47", "53")
REFERENCE = "extra_continued"
ARMS = (
    "continued", "centroid", "constant0", "constant1", "v15_oof_gate",
    "v16_final_loss_gate", "unaligned_oof", "geo_aligned_oof",
    "geo_aligned_swapped", "geo_aligned_shuffled",
    "logit_aligned_oof", "logit_aligned_swapped",
)
RESAMPLES = 4096
RNG_SEED = 20261016
BASE_V17 = "hepta.stem.identity-alignment.v17.research"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def cases_from_validated_inputs(inputs):
    meta = predecessor.jread(Path(inputs) / "input.json")
    require(sha(predecessor.checked(Path(inputs) / "input.json")) == predecessor.INPUT,
            "wrong original input identity")
    parts = meta["partitions"]
    require(set(parts) == {"train", "calibration", "holdout"}, "unexpected source partitions")
    require([len(parts[x]) for x in ("train", "calibration", "holdout")] == [64, 32, 32],
            "source partition cardinality drift")
    require(sorted(sum((parts[x] for x in ("train", "calibration", "holdout")), [])) == list(range(128)),
            "overlapping original source partitions")
    require(set(meta["labels"]) == {str(i) for x in ("train", "calibration") for i in parts[x]},
            "held labels must be unavailable")
    roster = meta["roster"]
    require(len(roster) == 128 and len({r["case_id"] for r in roster}) == 128,
            "case identity collision")
    # Groups are publisher case metadata; they are not necessarily distinct
    # independent source-family roots (e.g. journal, author, conversation).
    train_ids = {roster[i]["case_id"] for i in parts["train"]}
    cal_ids = [roster[i]["case_id"] for i in parts["calibration"]]
    require(not train_ids.intersection(cal_ids) and len(set(cal_ids)) == 32,
            "case-level source collision")
    label = np.asarray([meta["labels"][str(i)] for i in parts["calibration"]], dtype=np.int64)
    require(label.shape == (32,) and np.all((label >= 0) & (label < 4)), "invalid CAL source labels")
    return label, sha(canonical(cal_ids)), meta


def bounded_probabilities(value):
    arr = np.asarray(value, dtype=np.float64)
    require(arr.shape == (32, 4) and np.isfinite(arr).all()
            and np.all((arr >= 0) & (arr <= 1))
            and np.allclose(arr.sum(1), 1, rtol=0, atol=1e-6), "invalid archived CAL predictions")
    return arr


def per_case_brier(prob, gold):
    return np.square(prob - np.eye(4, dtype=np.float64)[gold]).sum(1)


def paired_interval(case_values, matrix):
    require(case_values.shape == (32,), "the original CAL case is the resampling unit")
    boot = case_values[matrix].mean(1)
    # Descriptive only: previously exposed, tuning-contaminated CAL, correlated
    # source families unverified, multiple arms/seeds. Not a confidence claim.
    q = np.quantile(boot, [0.025, 0.975, 0.05 / (2 * len(ARMS)),
                           1 - 0.05 / (2 * len(ARMS))])
    return {"case_mean": float(case_values.mean()),
            "raw_descriptive_95": [float(q[0]), float(q[1])],
            "multiplicity_adjusted_descriptive_95": [float(q[2]), float(q[3])],
            "case_mean_gains": int((case_values > 0).sum()),
            "case_mean_losses": int((case_values < 0).sum()),
            "case_mean_ties": int((case_values == 0).sum())}


def audit(inputs, v15, v16, v17):
    inputs, v15, v16, v17 = (Path(x) for x in (inputs, v15, v16, v17))
    # First independently re-forward/read back all genuine saved tensors.
    earlier = predecessor.review(inputs, v15, v16, v17)
    require(earlier["model_files_total_verified"] == 82
            and earlier["independent_future_cases"] == 0
            and earlier["production_authorized"] is False
            and earlier["held_labels_read"] is False,
            "prior independent model/source reviewer did not attest inventory")
    gold, case_roster_sha, meta = cases_from_validated_inputs(inputs)
    rec = predecessor.jread(v17 / "sealed.json")
    require(rec["schema"] == BASE_V17 and set(rec["seeds"]) == set(SEEDS)
            and rec["held_scores"] is None and rec["held_labels_read"] is False,
            "wrong historic or unblinded producer")
    k = np.arange(32, dtype=np.int64)
    draws = np.random.default_rng(RNG_SEED).integers(0, 32, (RESAMPLES, 32))
    matrices = {}
    baseline = {}
    for seed in SEEDS:
        row = rec["seeds"][seed]
        require(set(row["calibration_probabilities"]) == set(predecessor.ARMS),
                "missing or extra source-bound retrospective arm")
        prob = {name: bounded_probabilities(p) for name, p in row["calibration_probabilities"].items()}
        baseline[seed] = per_case_brier(prob[REFERENCE], gold)
        matrices[seed] = {name: per_case_brier(v, gold) for name, v in prob.items()}
        for name, expected in earlier["seeds"][seed]["calibration_brier"].items():
            require(np.isclose(float(matrices[seed][name].mean()), float(expected), atol=5e-5, rtol=0),
                    "archived outcome and independent scorer differ")
        require(row["selected_research_candidate"] == REFERENCE,
                "archived selection does not preserve unsplit comparator")
    arm_evidence = {}
    for name in ARMS:
        across_seed = np.stack([baseline[s] - matrices[s][name] for s in SEEDS])
        case_mean = across_seed.mean(0)  # 32 units, not 3 * 32 independent units
        arm_evidence[name] = {**paired_interval(case_mean, draws),
            "seed_descriptive_mean": {s: float(across_seed[i].mean()) for i, s in enumerate(SEEDS)}}
    # The after-label oracle is an infeasible upper bound. Compute it from
    # actual archived expert probabilities, but never offer it as a model arm.
    oracle = np.stack([baseline[s] - np.minimum(
        matrices[s]["constant0"], matrices[s]["constant1"]) for s in SEEDS]).mean(0)
    upper = {**paired_interval(oracle, draws), "deployable": False, "uses_calibration_labels": True}
    return {
        "schema": SCHEMA,
        "status": "RETROSPECTIVE_CLUSTERED_CALIBRATION_ONLY",
        "source_v17_sha256": rec["source_sha256"],
        "original_archive_sha256": predecessor.ARCHIVE,
        "v17_sealed_sha256": sha(predecessor.checked(v17 / "sealed.json")),
        "independent_model_bytes_verified": earlier["model_files_total_verified"],
        "calibration_case_roster_sha256": case_roster_sha,
        "distinct_original_calibration_cases": 32,
        "correlated_training_seeds": list(SEEDS),
        "resampling_units": 32,
        "source_family_independence_authenticated": False,
        "prospective_outcomes": 0,
        "frozen_comparator": REFERENCE,
        "candidate_arm_count": len(ARMS),
        "bootstrap_draws": RESAMPLES,
        "bootstrap_seed": RNG_SEED,
        "direction": "positive gain means lower Brier versus extra-trained single Head",
        "interpretation": "exploratory descriptive bootstrap on previously exposed CAL, not inferential confidence",
        "arms": arm_evidence,
        "infeasible_oracle": upper,
        "negative_transfer_independently_verified": None,
        "future_utility_gain": None,
        "target_host_4096_qualified": False,
        "production_authorized": False,
        "scientific_promotion_authorized": False,
        "model_selected": None,
        "no_change_reference_preserved": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("inputs", "v15", "v16", "v17", "output"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    result = audit(args.inputs, args.v15, args.v16, args.v17)
    path = Path(args.output)
    require(path.parent.is_dir() and not path.parent.is_symlink(), "real output parent required")
    with path.open("xb") as stream:
        stream.write(canonical(result))
        stream.flush()
    return result


if __name__ == "__main__":
    main()
