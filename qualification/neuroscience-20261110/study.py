#!/usr/bin/env python3
"""Read-only Hepta neuroscience mechanism qualification.

Reference-only math and evidence gates; no StageOwner, weights, I/O effects,
training, adoption, signatures, or production authority.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path
from typing import Iterable

LINEAGES = frozenset({"PERC", "MEM", "PRED", "CTRL", "VERIFY", "ACT", "LEARN"})
MEMORY_KINDS = ("fact", "episode", "skill", "recovery")
ARMS = ("routed", "shuffled", "scalar", "no_eligibility")
SCHEMA = "hepta.neuroscience.shadow.v1"


class ContractError(ValueError):
    """Invalid input or unqualified experiment, never a model error."""


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def _valid_hash(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def _finite(value: object) -> bool:
    if type(value) not in (float, int):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


@dataclass(frozen=True)
class Eligibility:
    action_id: str
    source_digest: str
    sequence: int
    values: tuple[float, ...]
    split: str = "train"


@dataclass(frozen=True)
class Feedback:
    receipt_digest: str
    action_id: str
    available_sequence: int
    modulator: tuple[float, ...]


@dataclass(frozen=True)
class CreditReceipt:
    arm: str
    deltas: tuple[float, ...]
    matched: int
    expired: int
    future_withheld: int
    # Full-audit only. Receipts supplied after cutoff are known to this audit,
    # not to a frozen selection caller. Do not export this count as a feature.
    unobserved_action_count: int
    transcript_digest: str
    # Frozen candidate identity excludes feedback unavailable at the cutoff.
    # This is a self-declared digest, not an owner-attested witness.
    causal_training_digest: str
    authority: str = "DENY_ALL"
    qualification: str = "SHADOW_ONLY"


@dataclass(frozen=True)
class FrozenCreditView:
    """Candidate-facing, shadow-only projection of a full forensic receipt.

    Never exports fields that depend on feedback unavailable at the cutoff:
    future_withheld, unobserved_action_count, or transcript_digest. This
    cannot authenticate source, feedback, model ownership or actual effects.
    """
    arm: str
    deltas: tuple[float, ...]
    matched: int
    expired: int
    causal_training_digest: str
    authority: str = "DENY_ALL"
    qualification: str = "SHADOW_ONLY"


def frozen_credit_view(full_audit: CreditReceipt) -> FrozenCreditView:
    """Redact hindsight-bearing forensic metadata before frozen selection.

    Only receipts produced by the separate time-aligned shadow audit should
    be passed here. The type guard is not cryptographic attestation.
    """
    if type(full_audit) is not CreditReceipt:
        raise ContractError("invalid shadow credit audit receipt")
    return FrozenCreditView(
        arm=full_audit.arm,
        deltas=full_audit.deltas,
        matched=full_audit.matched,
        expired=full_audit.expired,
        causal_training_digest=full_audit.causal_training_digest,
    )


def time_aligned_credit(
    actions: Iterable[Eligibility],
    feedback: Iterable[Feedback],
    *,
    arm: str,
    cutoff_sequence: int,
    decay: float,
    max_lag: int,
    per_group_limit: float = 0.5,
    global_l1_limit: float = 1.0,
) -> CreditReceipt:
    """Link every feedback to its *past* action; never use future feedback.

    Four arms receive identical feedback vectors; scalar deliberately uses a
    coarser projection and thus is NOT an information-matched routing control.
    Routed and shuffled are information-matched routing controls.
    """
    action_list, feedback_list = list(actions), list(feedback)
    if arm not in ARMS or not action_list:
        raise ContractError("unknown arm or empty action trace")
    # An empty feedback trace is a legitimate sparse/delayed observation:
    # zero measured outcomes is not a successful zero-valued outcome.
    if type(cutoff_sequence) is not int or cutoff_sequence < 0:
        raise ContractError("invalid training cutoff")
    if not _finite(decay) or not 0 <= decay <= 1:
        raise ContractError("invalid decay")
    if type(max_lag) is not int or max_lag < 0:
        raise ContractError("invalid lag window")
    if not all(_finite(x) and x > 0 for x in (per_group_limit, global_l1_limit)):
        raise ContractError("invalid trust region")
    if len(action_list) > 65_536 or len(feedback_list) > 65_536:
        raise ContractError("trace size limit")
    groups = len(action_list[0].values)
    if groups < 1 or groups > 64 or (arm == "shuffled" and groups < 2):
        raise ContractError("invalid number of groups for requested arm")

    action_by_id: dict[str, Eligibility] = {}
    for action in action_list:
        if (not action.action_id or action.action_id in action_by_id
                or not _valid_hash(action.source_digest) or action.split != "train"
                or type(action.sequence) is not int or action.sequence < 0
                or action.sequence > cutoff_sequence
                or len(action.values) != groups
                or any(not _finite(e) or abs(e) > 1 for e in action.values)
                or sum(abs(e) for e in action.values) > 4):
            raise ContractError("invalid, duplicate or evaluation eligibility")
        action_by_id[action.action_id] = action

    receipts: set[str] = set()
    target_ids: set[str] = set()
    accum = [0.0] * groups
    matched = expired = future_withheld = 0
    for fb in feedback_list:
        if (not _valid_hash(fb.receipt_digest) or fb.receipt_digest in receipts
                or fb.action_id in target_ids
                or fb.action_id not in action_by_id
                or type(fb.available_sequence) is not int
                or len(fb.modulator) != groups
                or any(not _finite(m) or abs(m) > 1 for m in fb.modulator)):
            raise ContractError("invalid feedback source, target, dimensionality or duplicate")
        receipts.add(fb.receipt_digest)
        target_ids.add(fb.action_id)
        action = action_by_id[fb.action_id]
        lag = fb.available_sequence - action.sequence
        if lag < 0:
            raise ContractError("feedback arrived before its action")
        if fb.available_sequence > cutoff_sequence:
            future_withheld += 1
            continue
        if lag > max_lag:
            expired += 1
            continue
        matched += 1
        attenuation = decay ** lag
        for index, eligibility in enumerate(action.values):
            if arm == "routed":
                modulator = fb.modulator[index]
            elif arm == "shuffled":
                modulator = fb.modulator[(index + 1) % groups]
            elif arm == "scalar":
                modulator = sum(fb.modulator) / groups
            else:
                modulator = 0.0
            accum[index] += attenuation * eligibility * modulator

    # Exact same declared projection envelope for every arm, including ablations.
    projected = [min(per_group_limit, max(-per_group_limit, x)) for x in accum]
    norm = sum(abs(x) for x in projected)
    if norm > global_l1_limit:
        projected = [x * global_l1_limit / norm for x in projected]
    canonical_input = {
        "schema": SCHEMA,
        "actions": [asdict(a) for a in sorted(action_list, key=lambda a: a.action_id)],
        "feedback": [asdict(f) for f in sorted(feedback_list, key=lambda f: f.receipt_digest)],
        "arm": arm,
        "cutoff": cutoff_sequence,
        "decay": decay,
        "max_lag": max_lag,
        "per_group_limit": per_group_limit,
        "global_l1_limit": global_l1_limit,
    }
    # A complete-input audit contains future feedback. It MUST NOT be used
    # as a model-selection, training, or evaluator feature at this cutoff.
    # The separate frozen-prefix identity depends only on feedback whose
    # availability sequence is no later than the cutoff, independent of how
    # many subsequent labels are appended or how their content changes.
    causal_input = {
        **canonical_input,
        "feedback": [asdict(f) for f in sorted(
            (f for f in feedback_list if f.available_sequence <= cutoff_sequence),
            key=lambda f: f.receipt_digest)],
    }
    return CreditReceipt(arm, tuple(projected), matched, expired,
                         future_withheld, len(action_by_id) - len(target_ids),
                         _digest(canonical_input),
                         _digest(causal_input))


@dataclass(frozen=True)
class UpdateOpportunity:
    lineage: str
    sequence: int
    candidate_generation: int
    evaluation_independent: bool
    preregistered_gate_passed: bool


def cadence_gate(events: Iterable[UpdateOpportunity], gaps: dict[str, int]
                 ) -> tuple[dict, ...]:
    """Declare candidate update opportunities only; NEVER auto-adopt a model."""
    if set(gaps) != LINEAGES or any(type(x) is not int or x < 1 for x in gaps.values()):
        raise ContractError("all seven lineage clocks must be explicit positive integers")
    last: dict[str, int] = {}
    # The last admitted clock slot is not the last observed event. A clock-denied
    # event still advances the per-lineage event-time frontier. Otherwise an
    # earlier candidate may be processed after a later denied opportunity.
    last_seen_sequence: dict[str, int] = {}
    # Track observed candidate generations separately from admitted clock slots.
    # A denied opportunity must not permit a stale generation to reappear.
    last_generation: dict[str, int] = {}
    outputs = []
    for ev in events:
        if (ev.lineage not in LINEAGES or type(ev.sequence) is not int
                or ev.sequence < 0 or type(ev.candidate_generation) is not int
                or ev.candidate_generation < 1
                or type(ev.evaluation_independent) is not bool
                or type(ev.preregistered_gate_passed) is not bool):
            raise ContractError("invalid update opportunity")
        if (ev.lineage in last_seen_sequence
                and ev.sequence < last_seen_sequence[ev.lineage]):
            raise ContractError("clock regression")
        last_seen_sequence[ev.lineage] = ev.sequence
        prior_generation = last_generation.get(ev.lineage)
        if (prior_generation is not None
                and ev.candidate_generation < prior_generation):
            raise ContractError("candidate generation regression")
        last_generation[ev.lineage] = ev.candidate_generation
        previous = last.get(ev.lineage)
        allowed = previous is None or ev.sequence - previous >= gaps[ev.lineage]
        if allowed:
            last[ev.lineage] = ev.sequence
        qualified = allowed and ev.evaluation_independent and ev.preregistered_gate_passed
        outputs.append({
            "lineage": ev.lineage,
            "sequence": ev.sequence,
            "candidate_generation": ev.candidate_generation,
            "status": "REVIEW_CANDIDATE" if qualified else "NO_UPDATE",
            "reason": ("review_only" if qualified else
                       "clock_gate" if not allowed else "evidence_gate"),
            "authority": "DENY_ALL",
        })
    return tuple(outputs)


@dataclass(frozen=True)
class MemoryRecord:
    event_id: str
    kind: str
    key: str
    source_digest: str
    observed_sequence: int
    tombstoned: bool = False
    rights_revoked: bool = False
    # Same owner-declared logical object across corrections/tombstones. A bare
    # event_id means an independent object, never an inferred same-key erase.
    logical_id: str | None = None


def select_replay(records: Iterable[MemoryRecord], *, policy: str, query_key: str,
                  now_sequence: int, max_items: int, seed: str) -> tuple[str, ...]:
    """Reference selector: exact-key RAG, uniform or stratified per-kind replay."""
    if policy not in ("exact", "uniform", "stratified"):
        raise ContractError("invalid memory baseline")
    if type(now_sequence) is not int or now_sequence < 0 or not (
            type(max_items) is int and 1 <= max_items <= 256):
        raise ContractError("invalid memory window or budget")
    entries = list(records)
    if len(entries) > 65_536 or len({e.event_id for e in entries}) != len(entries):
        raise ContractError("duplicate memory identities or oversized records")
    for e in entries:
        if (not isinstance(e.event_id, str) or not e.event_id
                or not isinstance(e.key, str) or not e.key
                or not _valid_hash(e.source_digest)
                or e.kind not in MEMORY_KINDS or type(e.observed_sequence) is not int
                or e.observed_sequence < 0 or type(e.tombstoned) is not bool
                or type(e.rights_revoked) is not bool
                or (e.logical_id is not None and
                    (not isinstance(e.logical_id, str) or not e.logical_id))):
            raise ContractError("invalid memory event")
    # Visible revisions must be evaluated together. Filtering each tombstone
    # individually can resurrect an older revision from the same logical object.
    # A shared query key alone is NOT an identity: unrelated sources may share it.
    # Explicit logical IDs and implicit per-event IDs are distinct namespaces.
    # Otherwise a self-declared tombstone for logical_id == another event_id
    # could suppress an unrelated record that never opted into that identity.
    by_logical_id: dict[tuple[str, str], list[MemoryRecord]] = {}
    for e in entries:
        if e.observed_sequence <= now_sequence:
            identity = (("logical", e.logical_id) if e.logical_id is not None
                        else ("event", e.event_id))
            by_logical_id.setdefault(identity, []).append(e)
    eligible = []
    for versions in by_logical_id.values():
        if (len({e.observed_sequence for e in versions}) != len(versions)
                or len({(e.key, e.kind) for e in versions}) != 1):
            raise ContractError("ambiguous logical revision or identity drift")
        # Revocation / deletion is sticky within this declared logical object.
        # No unsigned later 'active' revision may grant restoration authority.
        if any(e.tombstoned or e.rights_revoked for e in versions):
            continue
        eligible.append(max(versions, key=lambda e: e.observed_sequence))
    if policy == "exact":
        ordered = sorted((e for e in eligible if e.key == query_key),
                         key=lambda e: (-e.observed_sequence, e.event_id))
    elif policy == "uniform":
        ordered = sorted(eligible, key=lambda e: _digest([seed, e.event_id]))
    else:
        bins = {kind: sorted((e for e in eligible if e.kind == kind),
                            key=lambda e: _digest([seed, e.event_id]))
                for kind in MEMORY_KINDS}
        ordered = []
        while any(bins.values()) and len(ordered) < max_items:
            for kind in MEMORY_KINDS:
                if bins[kind]:
                    ordered.append(bins[kind].pop(0))
    return tuple(e.event_id for e in ordered[:max_items])


@dataclass(frozen=True)
class TrialRow:
    episode_id: str
    seed: int
    family: str
    arm: str
    workload_digest: str
    ability_digest: str
    evaluator_digest: str
    feedback_budget_bits: int
    query_budget: int
    training_budget: int
    compute_budget_us: int
    gross_value: float
    full_cost: float
    retention_value: float | None
    evaluator_independent: bool
    outcome_receipt_digest: str


def paired_evidence(rows: Iterable[TrialRow]) -> dict:
    """Audit complete paired rows; statistics do not grant independent authority."""
    data = list(rows)
    if not data:
        raise ContractError("empty evaluation")
    keys: dict[tuple[str, int, str], dict[str, TrialRow]] = {}
    for row in data:
        if (not row.episode_id or not row.family or row.arm not in ARMS
                or type(row.seed) is not int or row.seed < 0
                or any(not _valid_hash(v) for v in (
                    row.workload_digest, row.ability_digest, row.evaluator_digest,
                    row.outcome_receipt_digest))
                or any(type(v) is not int or v < 0 for v in (
                    row.feedback_budget_bits, row.query_budget, row.training_budget,
                    row.compute_budget_us))
                or any(not _finite(v) for v in (row.gross_value, row.full_cost))
                or row.full_cost < 0 or (row.retention_value is not None and
                                          not _finite(row.retention_value))
                or type(row.evaluator_independent) is not bool):
            raise ContractError("invalid measured row")
        key = (row.episode_id, row.seed, row.family)
        block = keys.setdefault(key, {})
        if row.arm in block:
            raise ContractError("duplicate arm in matched block")
        block[row.arm] = row
    if len(keys) > 100_000:
        raise ContractError("too many matched evaluation blocks")
    # Prospective seed clusters must have the same family-by-episode roster.
    # Complete individual arm blocks alone do not make seed means comparable.
    roster_by_seed: dict[int, dict[str, int]] = {}
    for (_, seed, family) in keys:
        roster = roster_by_seed.setdefault(seed, {})
        roster[family] = roster.get(family, 0) + 1
    if len({tuple(sorted(r.items())) for r in roster_by_seed.values()}) != 1:
        raise ContractError("unequal family/episode roster across seed clusters")
    net_diffs_by_seed: dict[int, list[float]] = {}
    cost_diffs_by_seed: dict[int, list[float]] = {}
    retention_diffs_by_seed: dict[int, list[float]] = {}
    seen_receipts: set[str] = set()
    all_independent = True
    # The evaluator and offered resource ceilings are pre-registered once per
    # task family. Within-arm matching alone cannot prevent each new training
    # seed or episode from silently switching the scoring rule or opportunity.
    # Different task families may use different locked contracts; trained
    # model/ability digests may legitimately differ between seeds.
    frozen_evaluators: dict[str, str] = {}
    frozen_opportunities: dict[str, tuple[int, int, int, int]] = {}
    for (episode_id, seed, family), block in keys.items():
        if set(block) != set(ARMS):
            raise ContractError("missing matched arm")
        ref = block["routed"]
        for row in block.values():
            if (row.workload_digest != ref.workload_digest
                    or row.ability_digest != ref.ability_digest
                    or row.evaluator_digest != ref.evaluator_digest
                    or (row.query_budget, row.training_budget, row.compute_budget_us,
                        row.feedback_budget_bits) !=
                    (ref.query_budget, ref.training_budget, ref.compute_budget_us,
                     ref.feedback_budget_bits)):
                raise ContractError("unequal workload, model, feedback or resource opportunity")
        for row in block.values():
            if row.outcome_receipt_digest in seen_receipts:
                raise ContractError("reused outcome receipt across trial arms or blocks")
            seen_receipts.add(row.outcome_receipt_digest)
        evaluator = ref.evaluator_digest
        if family in frozen_evaluators and evaluator != frozen_evaluators[family]:
            raise ContractError("unfrozen evaluator within task family")
        frozen_evaluators[family] = evaluator
        opportunity = (ref.feedback_budget_bits, ref.query_budget,
                       ref.training_budget, ref.compute_budget_us)
        if (family in frozen_opportunities
                and opportunity != frozen_opportunities[family]):
            raise ContractError("unfrozen resource opportunity within task family")
        frozen_opportunities[family] = opportunity
        all_independent &= all(row.evaluator_independent for row in block.values())
        shuffled = block["shuffled"]
        net_diffs_by_seed.setdefault(seed, []).append(
            (ref.gross_value - ref.full_cost) -
            (shuffled.gross_value - shuffled.full_cost))
        cost_diffs_by_seed.setdefault(seed, []).append(
            ref.full_cost - shuffled.full_cost)
        # A full four-arm retention panel cannot be inferred from primary arms.
        if all(row.retention_value is not None for row in block.values()):
            retention_diffs_by_seed.setdefault(seed, []).append(
                ref.retention_value - shuffled.retention_value)
    # A seed reused across task families is ONE randomization unit, not
    # independent repeated evidence for each episode.
    net_diffs = [sum(v) / len(v) for _, v in sorted(net_diffs_by_seed.items())]
    cost_diffs = [sum(v) / len(v) for _, v in sorted(cost_diffs_by_seed.items())]
    retention_complete = sum(map(len, retention_diffs_by_seed.values())) == len(keys)
    retention_diffs = [
        sum(retention_diffs_by_seed[seed]) / len(retention_diffs_by_seed[seed])
        for seed in sorted(net_diffs_by_seed)
    ] if retention_complete else []
    p = _exact_one_sided_signflip_p(net_diffs) if len(net_diffs) <= 16 else None
    return {
        "schema": SCHEMA,
        "blocks": len(keys),
        "seed_clusters": len(net_diffs),
        "comparison": "routed minus shuffled (information and budget matched)",
        "mean_net_difference": sum(net_diffs) / len(net_diffs),
        "mean_cost_difference": sum(cost_diffs) / len(cost_diffs),
        "mean_retention_difference": (sum(retention_diffs) / len(retention_diffs)
                                       if retention_complete else None),
        "one_sided_exact_signflip_p": p,
        "evaluation_claimed_independent": all_independent,
        "research_posture": "HOLD_NO_PRODUCTION_AUTHORITY",
        "qualification": "RECEIPTS_NOT_EXTERNALLY_ATTESTED",
        "input_digest": _digest([asdict(x) for x in sorted(data, key=lambda x:
                                   (x.episode_id, x.seed, x.family, x.arm))]),
    }


def _exact_one_sided_signflip_p(differences: list[float]) -> float:
    observed = sum(differences)
    # Enumeration is only used for <=16 paired units. Every zero remains a unit.
    count = sum(1 for signs in product((-1, 1), repeat=len(differences))
                if sum(x * sign for x, sign in zip(differences, signs)) >=
                observed - 1e-12)
    return count / (2 ** len(differences))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, required=True,
                        help="JSONL of independent, full-cost paired TrialRow records")
    args = parser.parse_args()
    with args.trials.open(encoding="utf-8") as stream:
        rows = [TrialRow(**json.loads(line)) for line in stream if line.strip()]
    print(json.dumps(paired_evidence(rows), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
