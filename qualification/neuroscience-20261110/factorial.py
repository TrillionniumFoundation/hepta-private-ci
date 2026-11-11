#!/usr/bin/env python3
"""Fail-closed, untrusted-data preflight for a factorial Core x NDU study.

Input rows, values, time indices and hashes are caller assertions, not owner
attestations. Never use this to authorize a Q24 update, adopt or external effect.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from study import ContractError, _digest, _exact_one_sided_signflip_p, _finite, _valid_hash

SCHEMA = "hepta.neuroscience.core-ndu-preflight.v1"
ARMS = ("A", "B", "C", "D")
DENSITIES = ("sparse", "dense")
# Four exact requested contrasts; not four independently established mechanisms.
CONTRASTS = ("B_minus_A", "D_minus_C", "D_minus_B", "interaction")
MAX_ROWS = 100_000


@dataclass(frozen=True)
class FactorialTrialRow:
    episode_id: str
    seed: int
    family: str
    feedback_density: str
    arm: str                         # A ordinary; B ordinary+NDU; C Hepta; D Hepta+NDU
    split: str                       # must be future_B
    source_task_digest: str          # actual training task A (declared only)
    workload_digest: str             # future evaluation B, distinct from A
    shared_base_digest: str
    capacity_envelope_digest: str    # matched opportunity, not proven equivalence
    evaluator_digest: str
    training_seed_digest: str
    evaluation_seed_digest: str
    feedback_budget_bits: int
    query_budget: int
    training_budget: int
    compute_budget_us: int
    actual_cpu_us: int               # declared measurement, includes retries
    actual_wall_us: int
    peak_rss_bytes: int
    failed_attempts: int
    gross_value: float
    full_cost: float
    old_task_score: float | None
    ood_score: float | None
    evaluator_independent: bool      # self-declared, does not establish independence
    outcome_receipt_digest: str     # self-declared, not a signature


def _validate(row: FactorialTrialRow) -> None:
    if (not isinstance(row.episode_id, str) or not row.episode_id
            or not isinstance(row.family, str) or not row.family
            or row.arm not in ARMS or row.feedback_density not in DENSITIES
            or row.split != "future_B"
            or type(row.seed) is not int or row.seed < 0
            or type(row.evaluator_independent) is not bool):
        raise ContractError("invalid arm, split, family, seed or independence field")
    hashes = (row.source_task_digest, row.workload_digest, row.shared_base_digest,
              row.capacity_envelope_digest, row.evaluator_digest,
              row.training_seed_digest, row.evaluation_seed_digest,
              row.outcome_receipt_digest)
    if not all(_valid_hash(value) for value in hashes):
        raise ContractError("noncanonical or absent declared digest")
    if (row.source_task_digest == row.workload_digest
            or row.training_seed_digest == row.evaluation_seed_digest):
        raise ContractError("training A and future B must have distinct task and seed labels")
    for value in (row.feedback_budget_bits, row.query_budget, row.training_budget,
                  row.compute_budget_us, row.actual_cpu_us, row.actual_wall_us,
                  row.peak_rss_bytes, row.failed_attempts):
        if type(value) is not int or value < 0:
            raise ContractError("invalid integer resource record")
    if (row.feedback_budget_bits == 0 or row.query_budget == 0
            or row.training_budget == 0 or row.compute_budget_us == 0
            or row.actual_cpu_us == 0 or row.actual_wall_us == 0
            or row.peak_rss_bytes == 0
            or row.actual_cpu_us > row.compute_budget_us):
        raise ContractError("resource evidence incomplete or out of declared budget")
    for value in (row.gross_value, row.full_cost, row.old_task_score, row.ood_score):
        if value is not None and not _finite(value):
            raise ContractError("nonfinite or nonnumeric value")
    if row.full_cost < 0:
        raise ContractError("negative purported complete cost")


def _differences(values: dict[str, float]) -> dict[str, float]:
    return {
        "B_minus_A": values["B"] - values["A"],
        "D_minus_C": values["D"] - values["C"],
        "D_minus_B": values["D"] - values["B"],
        "interaction": (values["D"] - values["C"]) - (values["B"] - values["A"]),
    }


def _holm(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    if any(value is None for value in pvalues.values()):
        return dict.fromkeys(pvalues, None)
    ranked = sorted(pvalues, key=lambda name: (pvalues[name], name))
    result = {}
    previous = 0.0
    for rank, name in enumerate(ranked):
        adjusted = min(1.0, (len(ranked) - rank) * pvalues[name])
        previous = max(previous, adjusted)
        result[name] = previous
    return {name: result[name] for name in pvalues}


def evaluate_core_ndu(rows: list[FactorialTrialRow], *,
                      required_cells: list[tuple[str, str]]) -> dict:
    """Exact arm/cell/seed coverage and clustered *exploratory* contrasts.

    All metrics are caller-supplied; even favorable statistics remain HOLD.
    Equal weighting: per episode matched block -> cell -> seed -> grand mean.
    This avoids a dense task family's extra episodes silently dominating a seed.
    """
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ContractError("empty or oversized row set")
    if (not isinstance(required_cells, list) or not required_cells
            or len(required_cells) > 64):
        raise ContractError("preregister a bounded nonempty family/density matrix")
    registered: set[tuple[str, str]] = set()
    for cell in required_cells:
        if (not isinstance(cell, tuple) or len(cell) != 2
                or not isinstance(cell[0], str) or not cell[0]
                or cell[1] not in DENSITIES or cell in registered):
            raise ContractError("invalid, repeated or missing registered task cell")
        registered.add(cell)

    blocks: dict[tuple[int, str, str, str], dict[str, FactorialTrialRow]] = {}
    receipts: set[str] = set()
    # Declared labels may be reused to manufacture fictitious independent
    # seed clusters. These are consistency checks, NOT actual seed custody.
    seed_training: dict[int, str] = {}
    training_owner: dict[str, int] = {}
    evaluation_owner: dict[str, int] = {}
    training_task_digests: set[str] = set()
    future_task_digests: set[str] = set()
    for row in rows:
        _validate(row)
        # A task used for training anywhere in the panel cannot be a future-B
        # evaluation elsewhere (including another seed or episode). Comparing
        # each row with itself misses this cross-partition exposure.
        training_task_digests.add(row.source_task_digest)
        future_task_digests.add(row.workload_digest)
        previous_training = seed_training.setdefault(row.seed, row.training_seed_digest)
        if previous_training != row.training_seed_digest:
            raise ContractError("training seed identity changed within one seed cluster")
        training_seed_owner = training_owner.setdefault(row.training_seed_digest, row.seed)
        if training_seed_owner != row.seed:
            raise ContractError("training seed identity reused by different seed labels")
        evaluation_seed_owner = evaluation_owner.setdefault(row.evaluation_seed_digest, row.seed)
        if evaluation_seed_owner != row.seed:
            raise ContractError("evaluation seed identity reused by different seed labels")
        if (row.family, row.feedback_density) not in registered:
            raise ContractError("unregistered task family or feedback density")
        if row.outcome_receipt_digest in receipts:
            raise ContractError("reused outcome receipt between arms or episodes")
        receipts.add(row.outcome_receipt_digest)
        key = (row.seed, row.family, row.feedback_density, row.episode_id)
        arm_rows = blocks.setdefault(key, {})
        if row.arm in arm_rows:
            raise ContractError("duplicate arm within matched episode")
        arm_rows[row.arm] = row
    if training_task_digests & future_task_digests:
        raise ContractError("training/evaluation task identity reused across partitions")
    if training_owner.keys() & evaluation_owner.keys():
        raise ContractError("training/evaluation seed identity reused across partitions")

    fields = (
        "source_task_digest", "workload_digest", "shared_base_digest",
        "capacity_envelope_digest", "evaluator_digest", "training_seed_digest",
        "evaluation_seed_digest", "feedback_budget_bits", "query_budget",
        "training_budget", "compute_budget_us",
    )
    # A paired episode is insufficient if a later seed or episode silently
    # changes its evaluator or opportunity. Freeze the cell-scoped declared
    # contract without freezing legitimate per-seed training/evaluation IDs.
    frozen_cell_fields = (
        "shared_base_digest", "capacity_envelope_digest", "evaluator_digest",
        "feedback_budget_bits", "query_budget", "training_budget",
        "compute_budget_us",
    )
    frozen_cell_contracts: dict[tuple[str, str], tuple[object, ...]] = {}
    per_seed_cell: dict[tuple[int, str, str], list[dict[str, float]]] = defaultdict(list)
    incomplete_retention = False
    incomplete_ood = False
    claimed_independent = True
    resources = {arm: {"cpu_us": [], "wall_us": [], "peak_rss_bytes": [],
                       "failed_attempts": [], "full_cost": []} for arm in ARMS}
    for (seed, family, density, _episode), block in sorted(blocks.items()):
        if set(block) != set(ARMS):
            raise ContractError("missing required Core x NDU factorial arm")
        ref = block["A"]
        for row in block.values():
            if any(getattr(ref, field) != getattr(row, field) for field in fields):
                raise ContractError("unmatched task, evaluator, seeds or resource opportunity")
            claimed_independent &= row.evaluator_independent
            series = resources[row.arm]
            for name in series:
                series[name].append(getattr(row, {"cpu_us": "actual_cpu_us", "wall_us": "actual_wall_us"}.get(name, name)))
        cell = (family, density)
        signature = tuple(getattr(ref, name) for name in frozen_cell_fields)
        previous = frozen_cell_contracts.setdefault(cell, signature)
        if signature != previous:
            raise ContractError("frozen cell evaluator or opportunity drift")
        values = {arm: block[arm].gross_value - block[arm].full_cost for arm in ARMS}
        contrasts = _differences(values)
        if any(row.old_task_score is None for row in block.values()):
            incomplete_retention = True
        else:
            contrasts.update({"retention:" + name: value for name, value in
                              _differences({arm: block[arm].old_task_score for arm in ARMS}).items()})
        if any(row.ood_score is None for row in block.values()):
            incomplete_ood = True
        else:
            contrasts.update({"ood:" + name: value for name, value in
                              _differences({arm: block[arm].ood_score for arm in ARMS}).items()})
        per_seed_cell[(seed, family, density)].append(contrasts)

    seeds = {key[0] for key in per_seed_cell}
    for seed in seeds:
        cells = {(family, density) for s, family, density in per_seed_cell if s == seed}
        if cells != registered:
            raise ContractError("seed missing registered sparse/dense or family cell")
    # Do not silently turn unequal, selectively retained per-seed episode
    # cohorts into exchangeable seed clusters. Cell counts may differ across
    # task families, but each training seed must receive the same opportunity.
    for cell in registered:
        counts = {len(per_seed_cell[(seed, *cell)]) for seed in seeds}
        if len(counts) != 1:
            raise ContractError("unequal seed episode opportunity within cell")

    # Equal weight to registered cells per independent training seed.
    by_seed: dict[int, dict[str, list[float]]] = {}
    by_cell = {}
    for cell in sorted(registered):
        cell_seed_diffs = {}
        for seed in sorted(seeds):
            examples = per_seed_cell[(seed, *cell)]
            cell_seed_diffs[seed] = {
                name: sum(e[name] for e in examples) / len(examples)
                for name in CONTRASTS
            }
        by_cell["/".join(cell)] = {
            "seed_clusters": len(cell_seed_diffs),
            "blocks": sum(len(per_seed_cell[(seed, *cell)]) for seed in seeds),
            "mean_net": {name: sum(x[name] for x in cell_seed_diffs.values()) / len(seeds)
                         for name in CONTRASTS},
        }
        for seed, contrasts in cell_seed_diffs.items():
            s = by_seed.setdefault(seed, {name: [] for name in CONTRASTS})
            for name in CONTRASTS:
                s[name].append(contrasts[name])

    seed_contrasts = {name: [sum(by_seed[seed][name]) / len(registered)
                              for seed in sorted(seeds)] for name in CONTRASTS}
    pvalues = {name: (_exact_one_sided_signflip_p(values)
                      if len(values) <= 16 else None)
               for name, values in seed_contrasts.items()}
    adjusted = _holm(pvalues)

    def secondary(prefix: str, missing: bool):
        if missing:
            return None
        return {
            name: sum(
                sum(
                    sum(example[prefix + name] for example in per_seed_cell[(seed, *cell)])
                    / len(per_seed_cell[(seed, *cell)])
                    for cell in registered
                ) / len(registered)
                for seed in seeds
            ) / len(seeds) for name in CONTRASTS
        }

    return {
        "schema": SCHEMA,
        "research_posture": "HOLD_NO_GO",
        "authority": "DENY_ALL",
        "owner_attestation": "NOT_VERIFIED",
        "evaluator_independence": "SELF_DECLARED" if claimed_independent else "MISSING",
        "coverage": {
            "complete_for_declared_matrix": True,
            "registered_cells": [list(c) for c in sorted(registered)],
            "seed_clusters": len(seeds), "matched_blocks": len(blocks),
            "equal_episode_opportunities_per_seed": True,
            "frozen_cell_contract": "SELF_DECLARED_ONLY",
            "declared_seed_identity_alias_guard": "SELF_DECLARED_ONLY",
            "declared_train_eval_task_disjointness": "SELF_DECLARED_ONLY",
        },
        "net_contrasts": {
            name: {
                "mean": sum(values) / len(values),
                "one_sided_signflip_p_unadjusted": pvalues[name],
                "holm_p_four_contrasts": adjusted[name],
            } for name, values in seed_contrasts.items()
        },
        "by_cell": by_cell,
        "retention_contrasts": secondary("retention:", incomplete_retention),
        "ood_contrasts": secondary("ood:", incomplete_ood),
        "reported_resource_means_by_arm": {
            arm: {name: sum(values) / len(values) for name, values in series.items()}
            for arm, series in resources.items()
        },
        "report_digest": _digest([asdict(row) for row in sorted(
            rows, key=lambda x: (x.seed, x.family, x.feedback_density,
                                x.episode_id, x.arm))]),
        "limitations": [
            "Input receipts and evaluator independence were not authenticated",
            "Complete cost and train/eval partition are self-declared",
            "Seed exchangeability, preregistration and family-wise research gate not proven",
            "No owner selection, NoUpdate/Adopt, task C or cold recovery executed",
        ],
    }


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON field")
        result[key] = value
    return result


def _strict_json(line: str) -> object:
    return json.loads(line, object_pairs_hook=_reject_duplicate_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ContractError("nonfinite JSON constant")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--required-cells", type=Path, required=True,
                        help="JSON array of [family, sparse|dense] pairs frozen before evaluation")
    args = parser.parse_args()
    if args.trials.stat().st_size > 50_000_000:
        raise ContractError("oversized trial file")
    with args.trials.open(encoding="utf-8") as stream:
        lines = [line for line in stream if line.strip()]
    if len(lines) > MAX_ROWS:
        raise ContractError("oversized trial file")
    try:
        rows = [FactorialTrialRow(**_strict_json(line)) for line in lines]
    except TypeError as error:
        raise ContractError("invalid trial row shape") from error
    cells = _strict_json(args.required_cells.read_text(encoding="utf-8"))
    if not isinstance(cells, list):
        raise ContractError("invalid required-cell manifest")
    print(json.dumps(evaluate_core_ndu(rows, required_cells=[tuple(c) for c in cells]),
                     sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

