"""Fail-closed E-I physical-training budget/lineage reconciliation (research only).

The input is an externally collected, source-sealed producer journal. Checking
hashes and counters is NOT proof that a model ran, that a ledger is authenticated,
or that any memory architecture is better. Keep separate evidence and FinalUse
owners. This audit grants no production authority.
"""
from __future__ import annotations

from memory_nine_arm_gate import (
    Refused, canonical, digest, distinct_strings, integer, keys, require, sha,
    validate_plan,
)

SCHEMA = "hepta.memory.a-i.physical-training-cost.v1"
TRAINED = "EFGHI"
PHASES = {
    "E": ("head",),
    "F": ("head",),
    "G": ("head", "router"),
    "H": ("head", "router", "graph"),
    "I": ("head", "router", "graph", "evolution"),
}
def verify_training_receipts(plan, package):
    """Recompute complete staged E-I work and fail on mismatched lineages.

    An accepted result is a *syntactic and arithmetic receipt check*, not a
    qualified experiment. Model origins, actual tensor forwards and signatures
    must be independently witnessed outside this module.
    """
    cases = validate_plan(plan)
    keys(package, ("schema", "plan_sha256", "arms"), "training package schema")
    require(package["schema"] == SCHEMA, "wrong physical-training schema")
    expected_plan_sha = sha(canonical(plan))
    require(package["plan_sha256"] == expected_plan_sha,
            "physical training is not bound to frozen A-I plan")
    require(type(package["arms"]) is list and len(package["arms"]) == len(TRAINED),
            "complete E-I training receipt census required")

    all_eval_roots = {r for c in cases.values() for r in c["source_roots"]}
    permitted = set(plan["common"]["training_roots"])
    denied = all_eval_roots | set(plan["common"]["calibration_roots"])
    source_frontier = plan["common"]["source_frontier_sha256"]
    forget_frontier = plan["common"]["forget_frontier_sha256"]
    encoder = plan["common"]["encoder_sha256"]
    seen, by_arm = set(), {}

    for record in package["arms"]:
        keys(record, (
            "arm", "artifact_sha256", "encoder_sha256", "source_frontier_sha256",
            "forget_frontier_sha256", "source_ancestor_roots",
            "replay_source_roots", "trained_head_tensor_digests",
            "weight_inventory_sha256", "journal_sha256",
            "observed_encoder_forwards", "artifact_bytes", "peak_rss_bytes",
            "parent_artifact_sha256", "evolution_operation_receipts", "events",
        ), "physical arm receipt")
        arm = record["arm"]
        require(type(arm) is str and arm in TRAINED and arm not in seen,
                "duplicate, missing or non-learning arm")
        seen.add(arm)
        bank = plan["arms"][arm]
        require(record["artifact_sha256"] == bank["artifact_sha256"]
                and record["encoder_sha256"] == encoder
                and record["source_frontier_sha256"] == source_frontier
                and record["forget_frontier_sha256"] == forget_frontier,
                "training artifact / Encoder / source or forget frontier drift")
        digest(record["weight_inventory_sha256"], "physical weight inventory")
        digest(record["journal_sha256"], "training journal")
        distinct_strings(record["source_ancestor_roots"], "training closure")
        distinct_strings(record["replay_source_roots"], "replay closure")
        ancestors = set(record["source_ancestor_roots"])
        replay = set(record["replay_source_roots"])
        require(ancestors and ancestors <= permitted and not ancestors & denied,
                "learned Head crosses train/evaluation/calibration boundary")
        require(replay <= ancestors, "replay source omitted from learned lineage")
        tensors = record["trained_head_tensor_digests"]
        require(type(tensors) is list and len(tensors) == bank["trained_heads"],
                "E-I true trained Head slot census")
        for token in tensors:
            digest(token, "trained tensor bytes")
        require(len(set(tensors)) == len(tensors), "aliased trained Head tensors")
        require(record["weight_inventory_sha256"] == sha(canonical(tensors)),
                "physical Head tensor inventory does not match stored digest")
        for field in ("observed_encoder_forwards", "artifact_bytes", "peak_rss_bytes"):
            integer(record[field], field, minimum=1, maximum=10**16)
        require(record["peak_rss_bytes"] <= bank["resident_budget_bytes"],
                "actual arm RSS exceeds precommitted resident budget")
        if arm == "I":
            require(record["parent_artifact_sha256"] == plan["arms"]["H"]["artifact_sha256"],
                    "evolution does not descend from frozen H parent")
            ops = record["evolution_operation_receipts"]
            require(type(ops) is dict and set(ops) == {"split", "merge"},
                    "both physical split and merge receipts required")
            for d in ops.values():
                digest(d, "topology transition receipt")
            require(ops["split"] != ops["merge"], "split/merge receipt aliased")
        else:
            require(record["parent_artifact_sha256"] is None
                    and record["evolution_operation_receipts"] == {},
                    "non-I arm cannot borrow evolution evidence")

        events = record["events"]
        require(type(events) is list and len(events) == len(PHASES[arm]),
                "physical per-phase work census incomplete")
        phases, work, total_cpu, head_steps, head_examples, forward_calls = (
            set(), 0, 0, 0, 0, 0,
        )
        for event in events:
            keys(event, (
                "arm", "phase", "source_roots", "optimizer_updates", "optimizer_examples",
                "work_units", "forward_calls", "cpu_ns", "before_sha256",
                "after_sha256", "record_sha256",
            ), "physical training event")
            phase = event["phase"]
            require(event["arm"] == arm,
                    "physical training event belongs to a different arm")
            require(type(phase) is str and phase in PHASES[arm]
                    and phase not in phases, "duplicate or unregistered work phase")
            phases.add(phase)
            distinct_strings(event["source_roots"], "per-phase source roots")
            require(event["source_roots"]
                    and set(event["source_roots"]) <= ancestors,
                    "per-phase work uses unregistered or withdrawn source")
            for field in ("optimizer_updates", "optimizer_examples",
                          "work_units", "forward_calls", "cpu_ns"):
                integer(event[field], field, minimum=1, maximum=10**16)
            for field in ("before_sha256", "after_sha256", "record_sha256"):
                digest(event[field], "physical event " + field)
            require(event["before_sha256"] != event["after_sha256"],
                    "work phase claims updates without changed tensor identity")
            recomputed = sha(canonical({k: v for k, v in event.items()
                                        if k != "record_sha256"}))
            require(event["record_sha256"] == recomputed,
                    "physical per-phase event modified after sealing")
            work += event["work_units"]
            total_cpu += event["cpu_ns"]
            forward_calls += event["forward_calls"]
            if phase == "head":
                head_steps += event["optimizer_updates"]
                head_examples += event["optimizer_examples"]
        require(phases == set(PHASES[arm]), "missing required actual learning phase")
        require(record["journal_sha256"] == sha(canonical(events)),
                "training journal event inventory does not match stored digest")
        require(bank["training_receipt_sha256"] == sha(canonical(record)),
                "physical complete E-I training receipt differs from plan")
        require(work == bank["total_training_budget_units"],
                "E-I optimizer and topology work not at equal frozen budget")
        require(head_steps == bank["head_optimizer_steps"]
                and head_examples == bank["head_optimizer_examples"],
                "actual Head steps/examples differ from source-first plan")
        require(forward_calls >= record["observed_encoder_forwards"],
                "impossible physical Encoder/Head forward accounting")
        by_arm[arm] = {
            "operator_work_units": work,
            "head_optimizer_steps": head_steps,
            "head_optimizer_examples": head_examples,
            "observed_cpu_ns": total_cpu,
            "observed_encoder_forwards": record["observed_encoder_forwards"],
            "event_count": len(events),
            "trained_head_count": len(tensors),
            "source_ancestor_count": len(ancestors),
            "weight_inventory_sha256": record["weight_inventory_sha256"],
        }

    require(seen == set(TRAINED), "one or more trained E-I arms not physically accounted")
    require(len({by_arm[a]["operator_work_units"] for a in TRAINED}) == 1,
            "learned arms trained under unequal observed work units")
    require(by_arm["H"]["head_optimizer_steps"] == by_arm["I"]["head_optimizer_steps"],
            "actual split-versus-static Head continuation not equal")
    return {
        "schema": SCHEMA + ".audit",
        "source_plan_sha256": expected_plan_sha,
        "receipt_sha256": sha(canonical(package)),
        "training_budget_reconciled": True,
        "actual_model_origin_independently_authenticated": False,
        "prospective_memory_superiority_established": False,
        "production_activation_allowed": False,
        "authority": "DENY_ALL",
        "by_arm": by_arm,
    }
