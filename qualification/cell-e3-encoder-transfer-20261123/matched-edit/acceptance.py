"""Fail-closed checks over E5 design/readiness outputs; this tool grants no authority."""
import argparse
import hashlib
import json
import math
from pathlib import Path

CURVES = ("fixed_total", "fixed_per_user", "fixed_data_workers")
ARMS = ("learned", "fixed", "random", "single_equal_budget", "edge_deleted", "message_shuffled")
RESOURCES = {"training_cpu_ns", "verification_cpu_ns", "serving_cpu_ns", "network_bytes",
             "accelerator_ns", "training_macs"}
COMMON = ("parent", "runtime", "hardware_pool", "evaluation_panel", "quality_gate", "seed")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resources(value):
    require(set(value) == RESOURCES and all(type(v) is int and v >= 0 for v in value.values())
            and sum(value.values()) > 0, "complete numeric resource vector required")
    return value


def scale_pair(curve, before, after):
    """Validate the intervention, never infer authenticated users from worker counts."""
    require(curve in CURVES, "unknown curve")
    for row in (before, after):
        require(row["curve"] == curve, "curve relabeling")
        require(all(type(row[k]) is int and row[k] > 0 for k in ("users", "workers")), "invalid axis")
        caps, used = resources(row["budget"]), resources(row["used"])
        require(all(used[k] <= caps[k] for k in caps), "budget exceeded")
        require(all(row[k] is not None for k in COMMON), "unbound common condition")
    require(all(before[k] == after[k] for k in COMMON), "comparison condition changed")
    if curve == "fixed_data_workers":
        require(before["users"] == after["users"] and before["workers"] < after["workers"], "worker axis differs")
        require(before["data_sha256"] == after["data_sha256"] and before["data_sha256"]
                and before["roster_sha256"] == after["roster_sha256"] and before["roster_sha256"], "data or roster changed")
        require(before["budget"] == after["budget"], "fixed data budget changed")
    else:
        require(before["users"] < after["users"] and before["workers"] == after["workers"], "user axis differs")
        if curve == "fixed_total":
            require(before["budget"] == after["budget"], "total budget changed")
        else:
            require(all(before["budget"][k] * after["users"] == after["budget"][k] * before["users"]
                        for k in RESOURCES), "per-user budget changed")
    return {"curve": curve, "intervention_consistent": True,
            "authenticated_user_growth_verified": False, "adopted_improvements_per_total_cost": None}


def circuit_controls(arms):
    """Complement readiness_v3: require missing comparator types and message intervention."""
    missing = sorted(set(ARMS) - set(arms))
    if missing:
        return {"status": "BLOCKED", "missing": missing, "learned_advantage": False}
    require(set(arms) == set(ARMS), "undeclared control arm")
    learned = arms["learned"]
    reasons = []
    ablation = learned.get("ablation_receipt", {})
    if ablation.get("schema") != "hepta.ablation-metrics.v3" or ablation.get("declared_ablations_complete") is not True:
        reasons.append("missing_complete_readiness_v3_ablation_inventory")
    for name, arm in arms.items():
        require(all(arm[k] == learned[k] and arm[k] is not None for k in COMMON), "control condition changed")
        require(resources(arm["budget"]) == resources(learned["budget"]), "unequal control budget")
        used = resources(arm["used"])
        require(all(used[k] <= arm["budget"][k] for k in used), "control exceeds budget")
        require(set(arm["outcomes"]) == set(learned["outcomes"]) and bool(arm["outcomes"])
                and all(type(v) is bool for v in arm["outcomes"].values()), "unpaired outcome panel")
        require(type(arm["old_parent_passes_lost"]) is int and arm["old_parent_passes_lost"] >= 0,
                "missing original retention losses")
        if arm["old_parent_passes_lost"]:
            reasons.append(name + ":retention_regressed")
        if not arm.get("original_receipts_sha256"):
            reasons.append(name + ":missing_original_receipts")
    score = lambda name: sum(arms[name]["outcomes"].values())
    for name in ARMS[1:]:
        if score("learned") <= score(name):
            reasons.append(name + ":no_strict_advantage")
    return {"status": "BLOCKED" if reasons else "READY_FOR_ORIGINAL_VERIFICATION",
            "missing": [], "reasons": reasons, "learned_advantage": not reasons,
            "scientific_qualification": "UNVERIFIED", "learning_reward_authorized": False}


def adopted_rate(readbacks, verify_original=None):
    """Only an external original-authority verifier can unlock the site-scoped metric."""
    if not readbacks or verify_original is None:
        return None
    ids, total, unit = set(), 0, None
    for row in readbacks:
        if verify_original(row) is not True or row.get("complete_total_cost") is not True:
            return None
        cost = row.get("total_cost", {})
        amount = cost.get("amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount) or amount <= 0:
            return None
        if not cost.get("unit") or (unit is not None and unit != cost["unit"]):
            return None
        unit = cost["unit"]
        count = row.get("site_attested_independent_adopted_improvements")
        if type(count) is not int or count not in (0, 1):
            return None
        if count:
            if not row.get("improvement_id"):
                return None
            ids.add(row["improvement_id"])
        total += amount  # retries still cost money/work, duplicate gains count once
    return {"unique_site_attested_improvements": len(ids), "total_cost": total,
            "unit": unit, "improvements_per_cost": len(ids) / total,
            "global_sybil_independence_verified": False}


def archived_readback(root):
    """Read original published files; never manufacture missing observations."""
    paths = {
        "design": "cell-cross-user-milestone-20261123/e5_prospective_human_cell_design.json",
        "circuit": "cell-cross-user-circuit-20261123/PAIRED_RESULT.json",
        "controls": "cell-cross-user-circuit-20261123/CANDIDATE_CONTROLS.json",
        "readiness": "cell-experiments-v3-20261116/regression-old-A/GATE.json",
    }
    data, pins = {}, {}
    for key, path in paths.items():
        raw = (root / "qualification" / path).read_bytes()
        data[key], pins[key] = json.loads(raw), hashlib.sha256(raw).hexdigest()
    design = data["design"]
    require(design["schema"] == "hepta.e5.prospective-human-cell-design.v1", "wrong existing E5 interface")
    require(design["measurements"] == [], "new E5 measurements require explicit axis validation")
    gate = data["readiness"]["receipt"]
    require(gate["schema"] == "hepta.circuit-readiness.v3", "wrong existing readiness interface")
    result = data["circuit"]
    require(result["schema"] == "hepta.paired-cold.result.v1", "wrong retained Circuit result")
    fixed = [r for r in data["controls"] if r["fixed_graph"] == "connected" and r["panel"] == "future"]
    learned_success = result["counts"]["future"]["both"] + result["counts"]["future"]["candidate_only"]
    return {"schema": "hepta.p1.acceptance-readback.v1", "input_sha256": pins,
        "growth_curves": {curve: {"status": "UNQUALIFIED", "qualified_adoption_points": 0} for curve in CURVES},
        "curve_scope": "authorized-user/adopted-improvement curves; published synthetic worker throughput is separate, not zero",
        "existing_readiness_status": gate["status"],
        "existing_readiness_scope": gate["scope"],
        "readiness_applies_to_retained_circuit": False,
        "retained_control_observations": ["fixed_connected", "edge_deleted"],
        "retained_circuit_learned_successes": learned_success,
        "retained_fixed_connected_successes": sum(r["result"] is True for r in fixed),
        "learned_fixed_tie": learned_success == sum(r["result"] is True for r in fixed),
        "circuit": circuit_controls({}), "adopted_improvements_per_total_cost": adopted_rate([]),
        "scope": "retained engineering evidence and interface checks; no new experiment or authority"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(archived_readback(args.source_root), sort_keys=True, indent=2))
