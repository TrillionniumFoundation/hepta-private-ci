"""Preregister final old/new panels and ALL candidate attempts, not a selector.

The local exclusive registry prevents slot reuse within that registry. It is not
an authenticated global trial registry or an OS information-flow boundary.
Conditional bounds require independently sampled source groups and models fixed
without final-label access. Repeated rows/seeds do not increase the group count.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path

from matrix_materials import public_row, strict_json, validate_config, validate_workload
from next_round_matrix import _digest
from paired_execution import _integer, _sha, validate_contract

SCHEMA = "hepta.stem.final-panel-protocol.v1"
LABEL_SCHEMA = "hepta.stem.common-final-labels.v1"
ROLES = ("baseline", "candidate")


def freeze_protocol(plan, contract, workload, *, contrast_id, slots, panels,
                    registered_at_ns, alpha, max_old_accuracy_drop, min_new_accuracy_gain):
    validate_contract(plan, contract)
    validate_workload(workload, contract)
    _integer(registered_at_ns, "registration time", 1)
    if registered_at_ns >= contract["eval_start_ns"]:
        raise ValueError("register the final protocol before evaluation starts")
    for name, value in (("alpha", alpha), ("old drop", max_old_accuracy_drop),
                        ("new gain", min_new_accuracy_gain)):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("invalid final " + name)
    if not 0 < alpha < 1:
        raise ValueError("alpha must be strictly between zero and one")
    contrasts = {c["contrast_id"]: c for c in plan["contrasts"]}
    if contrast_id not in contrasts:
        raise ValueError("unknown final contrast")
    if not isinstance(slots, list) or not 2 <= len(slots) <= 32:
        raise ValueError("register a bounded complete attempt inventory")
    seen, counts, shared_protocol = set(), dict.fromkeys(ROLES, 0), None
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != {"attempt_id", "role", "config"}:
            raise ValueError("complete final attempt slot required")
        name, role, cfg = slot["attempt_id"], slot["role"], slot["config"]
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None or name in seen:
            raise ValueError("unique safe attempt ID required")
        if role not in ROLES:
            raise ValueError("unknown attempt role")
        profile = validate_config(plan, contract, cfg)
        if profile["arm_id"] != contrasts[contrast_id][role]:
            raise ValueError("attempt assigned to the wrong arm")
        # Same declared protocol, not equal observed work; existing audit still
        # measures the latter. This profile does not support changing backbones.
        comparable = _digest({k: v for k, v in cfg.items() if k not in ("arm_id", "config_id")})
        if shared_protocol is not None and comparable != shared_protocol:
            raise ValueError("final attempt training protocols differ")
        shared_protocol = comparable
        seen.add(name)
        counts[role] += 1
    if counts["baseline"] != counts["candidate"]:
        raise ValueError("register equal numbers of baseline/candidate attempts")
    groups = {r["source_group"] for r in workload["eval"]}
    if (not isinstance(panels, dict) or set(panels) != groups
            or any(type(v) is not str for v in panels.values()) or set(panels.values()) != {"old", "new"}):
        raise ValueError("old/new panels must cover every final source group exactly once")
    # Exact duplicate content cannot be relabeled as independent source groups.
    content_groups, tasks = {}, []
    for row in workload["eval"]:
        fingerprint = _digest({k: row[k] for k in ("state", "question", "options")})
        if fingerprint in content_groups and content_groups[fingerprint] != row["source_group"]:
            raise ValueError("duplicate final content assigned to different source groups")
        content_groups[fingerprint] = row["source_group"]
        tasks.append(dict(task_id=row["sample_id"], source_group=row["source_group"],
                          panel=panels[row["source_group"]], input_digest=_digest(public_row(row))))
    body = dict(schema=SCHEMA, plan_id=plan["plan_id"], contract_id=contract["contract_id"],
                workload_content_id=_digest(workload), contrast_id=contrast_id, slots=slots,
                panels=panels, tasks=tasks, registered_at_ns=registered_at_ns, alpha=alpha,
                max_old_accuracy_drop=max_old_accuracy_drop, min_new_accuracy_gain=min_new_accuracy_gain,
                estimand="fail_closed_attempt_averaged_source_group_accuracy_delta",
                failure_score=0, missing_attempt_score=None, final_model_selection_permitted=False)
    # Copy nested input structures so later caller mutation cannot change the plan.
    import json
    body = json.loads(json.dumps(body, allow_nan=False))
    return {**body, "protocol_id": _digest(body)}


def validate_protocol(plan, contract, workload, protocol, expected_id):
    _sha(expected_id, "externally retained final protocol ID")
    fields = ("contrast_id", "slots", "panels", "registered_at_ns", "alpha",
              "max_old_accuracy_drop", "min_new_accuracy_gain")
    if not isinstance(protocol, dict) or any(k not in protocol for k in fields):
        raise ValueError("complete final protocol required")
    expected = freeze_protocol(plan, contract, workload, **{k: protocol[k] for k in fields})
    if expected["protocol_id"] != expected_id or _digest(expected) != _digest(protocol):
        raise ValueError("final protocol differs from its retained identity")


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_registry(path, protocol):
    """Exclusive local registration; the operator must retain its ID externally."""
    from matrix_runtime import write_json_exclusive
    root = Path(path)
    root.mkdir(exist_ok=False)
    write_json_exclusive(root / "PROTOCOL.json", protocol)
    (root / "claims").mkdir()
    _sync_directory(root)
    _sync_directory(root.parent)


def claim_attempt(path, protocol, attempt_id, *, started_at_ns):
    """One-shot claim. A failed/unfinished slot cannot be reused as a retry."""
    from matrix_runtime import write_json_exclusive
    root = Path(path)
    if _digest(strict_json(root / "PROTOCOL.json")) != _digest(protocol):
        raise ValueError("registry protocol changed")
    slot = next((s for s in protocol["slots"] if s["attempt_id"] == attempt_id), None)
    if slot is None:
        raise ValueError("unregistered final attempt")
    _integer(started_at_ns, "attempt start", 1)
    if started_at_ns < protocol["registered_at_ns"]:
        raise ValueError("attempt predates its preregistration")
    record = dict(schema="hepta.stem.final-attempt.v1", protocol_id=protocol["protocol_id"],
                  attempt_id=attempt_id, config_id=slot["config"]["config_id"], started_at_ns=started_at_ns)
    write_json_exclusive(root / "claims" / (attempt_id + ".json"), record)
    _sync_directory(root / "claims")
    return record


def project_common_observer(observer, execution, expected_seal_id):
    """Project ONE shared raw label receipt; its original file digest is retained.

    This is a checked schema projection, not a fabricated independent observation.
    The outer final audit additionally validates every terminal and task panel.
    """
    expected = {"schema", "protocol_id", "contract_id", "observer_id", "created_at_ns", "terminals", "rows"}
    if not isinstance(observer, dict) or set(observer) != expected or observer["schema"] != LABEL_SCHEMA:
        raise ValueError("complete common final labels required")
    attempt = execution.get("final_attempt")
    if (not isinstance(attempt, dict) or attempt.get("protocol_id") != observer["protocol_id"]
            or not isinstance(observer["terminals"], dict)
            or observer["terminals"].get(attempt.get("attempt_id")) != {"kind": "completed", "id": expected_seal_id}):
        raise ValueError("shared labels are not bound to this registered prediction seal")
    return dict(schema="hepta.stem.independent-labels.v1", seal_id=expected_seal_id,
                contract_id=observer["contract_id"], observer_id=observer["observer_id"],
                created_at_ns=observer["created_at_ns"], rows=observer["rows"])


def panel_statistics(protocol, scores):
    """Two simultaneous, one-sided Hoeffding bounds, conditional on independence.

    Each group difference is in [-1,1]. P(mean-Emean >= e) <= exp(-G*e^2/2).
    Allocate alpha/2 to each of the two preregistered panels. Repeated attempts
    and correlated rows are averaged WITHIN each group, never counted as new G.
    No common-label access or candidate choice may be adaptive to this panel.
    """
    slots, tasks = protocol["slots"], protocol["tasks"]
    if set(scores) != {s["attempt_id"] for s in slots}:
        raise ValueError("all registered attempts, including rejections, are required")
    for vector in scores.values():
        if (not isinstance(vector, list) or len(vector) != len(tasks)
                or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in vector)):
            raise ValueError("complete bounded score vector required; unknown is not zero")
    results = {}
    for panel in ("old", "new"):
        rows = []
        for group in sorted(g for g, p in protocol["panels"].items() if p == panel):
            ids = [i for i, t in enumerate(tasks) if t["source_group"] == group]
            values = {}
            for role in ROLES:
                attempts = [s["attempt_id"] for s in slots if s["role"] == role]
                values[role] = math.fsum(scores[a][i] for a in attempts for i in ids) / (len(attempts) * len(ids))
            rows.append(dict(source_group=group, task_rows=len(ids), **values,
                             delta=values["candidate"] - values["baseline"]))
        n = len(rows)
        estimate = math.fsum(g["delta"] for g in rows) / n
        # log(2/alpha) avoids overflow at tiny positive alpha.
        radius = math.sqrt(2 * (math.log(2) - math.log(protocol["alpha"])) / n)
        lower = max(-1., estimate - radius)
        threshold = -protocol["max_old_accuracy_drop"] if panel == "old" else protocol["min_new_accuracy_gain"]
        results[panel] = dict(groups=rows, independent_group_count_assumed=n,
                              estimated_delta=estimate, conditional_lower_bound=lower,
                              worst_observed_group_delta=min(g["delta"] for g in rows),
                              radius=radius, required_delta=threshold,
                              conditional_gate_passed=lower >= threshold)
    return dict(panels=results, family_alpha=protocol["alpha"],
                conditional_gate_passed=all(r["conditional_gate_passed"] for r in results.values()),
                independence_verified=False, subgroup_uniform_retention_established=False,
                repeated_selection_across_registries_controlled=False,
                retention_established=False, statistical_superiority_established=False)
