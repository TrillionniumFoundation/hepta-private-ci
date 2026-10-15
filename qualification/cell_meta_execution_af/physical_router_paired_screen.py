#!/usr/bin/env python3
"""Independent cross-seed, same-source paired Cell comparison; NEVER selection.

One source case is ONE case even when three training seeds reuse it. This
stdlib-only retrospective diagnostic replays all five arms through the original
independent reviewers before assembling source-paired Brier differences. The
within-panel row bootstrap is conditional/descriptive, NOT a confidence bound
for source-family generalization, future utility, or NDU admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as audit
from qualification.cell_meta_execution_af import physical_router_fivearm_review as five
from qualification.cell_meta_execution_af import physical_router_frozen_review as frozen_audit
from qualification.cell_meta_execution_af import physical_router_hard_review as hard_audit
from qualification.cell_meta_execution_af import physical_router_top1_review as top1_audit

SCHEMA = "hepta.cell-meta-paired-original-source.v1"
SEEDS = (41, 47, 53)
PARTS = ("old_retention", "future_1", "future_2")
CONTRASTS = (
    ("adaptive_minus_fixed", "adaptive_split", "fixed_router"),
    ("adaptive_minus_unsplit_continued", "adaptive_split", "unsplit_continued_update"),
    ("adaptive_minus_truly_frozen", "adaptive_split", "frozen_stage1_no_second_phase_learning"),
)
REPEATS = 1024
# Multiplicity declaration: 3 fixed contrasts across 2 retrospective test slices.
MULTIPLICITY = len(CONTRASTS) * 2
FAMILY_ALPHA = 0.05


class PairedScreenDenied(ValueError):
    """Input is incomplete, unpaired, altered, or claims unsupported evidence."""


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PairedScreenDenied(message)


def fp_number(value: Any, name: str) -> float:
    require(type(value) is float and math.isfinite(value) and 0 < value < 1,
            name + ": finite probability strictly in (0,1) required")
    return value


def copy_free_source(panel: dict[str, Any]) -> dict[str, Any]:
    """Only seed may vary. Source identity, labels, features and split stay fixed."""
    return {"source": {k: v for k, v in panel["source"].items() if k != "seed"},
            "partitions": panel["partitions"]}


def group_rows(panel: dict[str, Any], report: dict[str, Any], arm_name: str,
               part: str) -> list[tuple[str, str, float]]:
    rows = panel["partitions"][part]
    if arm_name == "frozen_stage1_no_second_phase_learning":
        predictions = report["frozen"]["predictions"][part]
    else:
        index = {"unsplit_continued_update": 0, "fixed_router": 1,
                 "learned_router": 2, "adaptive_split": 3}[arm_name]
        predictions = report["hard"]["results"][index]["predictions"][part]
    require(len(rows) == len(predictions), "predicted row count mismatch")
    out = []
    for row, pred in zip(rows, predictions, strict=True):
        require(pred["id"] == row["id"], "paired original row identity mismatch")
        p = fp_number(pred["probability"], "predicted posterior")
        require(type(row["label"]) is int and row["label"] in (0, 1),
                "invalid original outcome")
        out.append((row["id"], row["source_group"], (p-row["label"]) ** 2))
    return out


def bootstrap(values: list[float], *, part: str, contrast: str) -> dict[str, float | int | str]:
    """Deterministic conditional row-resampling; no independent-family claim."""
    n = len(values)
    require(16 <= n <= 256 and all(math.isfinite(v) and -1 <= v <= 1 for v in values),
            "bounded finite paired group table required")
    outputs = []
    # A SHA counter stream fixes the bootstrap across runners/interpreters.
    # Draws for a group are shared by all training seeds: NEVER bootstrap seeds
    # as though they were fresh human cases. Modulo bias is negligible here but
    # is not used as a basis for inferential calibration.
    label = ("hepta.original-source-bootstrap.v1|"+part+"|"+contrast).encode()
    for rep in range(REPEATS):
        s = 0.0
        for draw in range(n):
            raw = hashlib.sha256(label + rep.to_bytes(4, "big") + draw.to_bytes(4, "big")).digest()
            s += values[int.from_bytes(raw[:8], "big") % n]
        outputs.append(s/n)
    outputs.sort()
    alpha = FAMILY_ALPHA/MULTIPLICITY
    lo = int((alpha/2) * REPEATS)
    hi = int((1-alpha/2)*REPEATS)
    return {"paired_source_count": n,
            "mean_brier_delta": round(sum(values)/n, 9),
            "descriptive_conditional_resample_lower": round(outputs[lo], 9),
            "descriptive_conditional_resample_upper": round(outputs[hi], 9),
            "resamples": REPEATS,
            "family_alpha_display_only": FAMILY_ALPHA,
            "registered_comparisons": MULTIPLICITY,
            "original_family_independence_verified": False,
            "interval_is_valid_future_effect_CI": False,
            "conditional_bootstrap_interpretation": "same_source_retrospective_only"}


def screen(bundles: dict[int, dict[str, Any]]) -> dict[str, Any]:
    require(type(bundles) is dict and set(bundles) == set(SEEDS),
            "require exact three preregistered training seeds")
    common = None
    by_seed = {}
    validated = {}
    for seed in SEEDS:
        entry = bundles[seed]
        require(type(entry) is dict and set(entry) ==
                {"panel", "soft", "posthoc", "hard", "frozen", "five"},
                "missing/extra seed-scoped evidence members")
        panel = entry["panel"]
        require(type(panel) is dict and panel["source"]["seed"] == seed,
                "training seed must bind its original panel")
        # Independent numeric replay rejects tampered routes, parent weight,
        # altered Head logits, fabricated readout or OOD / future permissions.
        derived = five.descriptive(panel, entry["soft"], entry["posthoc"],
                                   entry["hard"], entry["frozen"])
        require(derived == entry["five"], "five-arm report does not independently replay")
        require(derived["authority_posture"] == "DENY_ALL" and
                derived["complete_lifecycle_compute_matched"] is False and
                derived["retrospective_not_prospective"] is True and
                derived["statistical_winner_certified"] is False,
                "invalid nonauthorizing five-arm posture")
        source = copy_free_source(panel)
        if common is None:
            common = source
        require(source == common,
                "three seeds must reuse exactly the SAME original source/labels/features; "
                "otherwise no cross-seed paired observation")
        by_seed[seed] = {"five_report_sha256": audit.digest(entry["five"]),
                         "panel_sha256": audit.digest(panel)}
        validated[seed] = entry

    reference = bundles[SEEDS[0]]["panel"]
    descriptive = {}
    unique_group_inventory = set()
    for part in PARTS:
        source_rows = reference["partitions"][part]
        groups = [row["source_group"] for row in source_rows]
        require(len(set(groups)) == len(groups), "repeated group inside a partition")
        require(not (unique_group_inventory & set(groups)),
                "one original source group reused across partitions")
        unique_group_inventory |= set(groups)
        comparisons = {}
        for key, treated, comparator in CONTRASTS:
            values = []
            seed_means = {}
            for seed in SEEDS:
                bundle = validated[seed]
                treat = group_rows(bundle["panel"], bundle, treated, part)
                control = group_rows(bundle["panel"], bundle, comparator, part)
                require(len(treat) == len(control) == len(source_rows),
                        "incomplete seed/source paired row")
                deltas = []
                for j, (t, c) in enumerate(zip(treat, control, strict=True)):
                    require(t[:2] == c[:2] == (source_rows[j]["id"],source_rows[j]["source_group"]),
                            "source group row or order changed across candidate/control")
                    delta = t[2]-c[2]
                    deltas.append(delta)
                seed_means[str(seed)] = round(sum(deltas)/len(deltas), 9)
                values.append(deltas)
            # Collapse *correlated* training seeds within each SAME article first.
            case_averaged = [sum(v[j] for v in values)/len(SEEDS)
                             for j in range(len(source_rows))]
            stats = bootstrap(case_averaged, part=part, contrast=key)
            stats["seed_conditioned_means"] = seed_means
            comparisons[key] = stats
        descriptive[part] = {"original_source_groups": len(groups),
                             "comparisons": comparisons}
    return {"schema": SCHEMA,
            "source_kind": reference["source"]["kind"],
            "source_rule": reference["source"]["rule"],
            "reused_original_source_rows": sum(len(x) for x in reference["partitions"].values()),
            "seed_count_not_independent_source_multiplier": len(SEEDS),
            "seed_inventories": by_seed,
            "retrospective_paired": descriptive,
            "three_seeds_reuse_same_source_material": True,
            "independent_original_source_family_count_authenticated": False,
            "prospective_calendar_outcome_verified": False,
            "source_lineage_independently_signed": False,
            "matched_complete_lifecycle_compute": False,
            "valid_independent_effect_confidence_bound": False,
            "selection_approved": False,
            "ndu_accepted": False,
            "physical_cell_split_permitted": False,
            "production_admission": "BLOCKED",
            "authority_posture": "DENY_ALL"}


def read_bundles(root: Path) -> dict[int, dict[str, Any]]:
    require(root.is_dir() and not root.is_symlink(), "trusted existing evidence directory required")
    names = {"panel": "trial-panel", "soft": "trial-report",
             "posthoc": "top1-report", "hard": "hard-train-report",
             "frozen": "frozen-report", "five": "fivearm-report"}
    return {seed: {name: audit.load(root / f"{seed}-{suffix}.json")
                   for name, suffix in names.items()} for seed in SEEDS}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        report = screen(read_bundles(args.bundle_dir))
        payload = audit.canonical(report)+b"\n"
        require(len(payload) < 128*1024, "output exceeds bounded descriptive receipt")
        with args.out.open("xb") as f:
            f.write(payload)
        print(json.dumps({"out":str(args.out),"schema":SCHEMA,
                          "authority_posture":"DENY_ALL","scientific_qualification":False}))
        return 0
    except (PairedScreenDenied, five.FiveArmDenied, frozen_audit.FrozenReviewDenied,
            hard_audit.HardReplayDenied, audit.AuditError, top1_audit.Top1AuditError,
            KeyError, IndexError, TypeError, ValueError, OSError,
            OverflowError, RecursionError) as exc:
        print("PAIRED SOURCE SCREEN BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
