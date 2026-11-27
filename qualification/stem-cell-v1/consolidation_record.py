"""Validate compression provenance separately from its original 32-Cell trajectory.

Only a checked teacher-stage projection is passed to the unchanged growth checks.
The final inventory and predictions remain those of the 16-Cell student. Digests
link records; they do not authenticate an observer or prove future task quality.
"""
import math

from consolidation_training import OUTPUT_PROFILE, teacher_gate, validate_policy
from next_round_matrix import _digest
from paired_execution import _integer, _sha
from retention_training import ROLES, validate_retention_record


def precursor_projection(execution, config, contract):
    policy = config["consolidation_policy"]
    validate_policy(policy)
    report = execution.get("consolidation_receipt")
    fields = {"schema", "policy_id", "output_profile", "disposition", "teacher_parameters",
              "student_parameters", "retained_parent_parameters", "peak_live_trainable_params",
              "teacher_parameter_sha256", "teacher_reference_payload_bytes", "teacher_reference_rows",
              "role_examples", "internal_selection_only", "independent_gain_established",
              "production_authorized", "teacher_reference_sha256", "teacher_inventory",
              "initialized_student_sha256", "training", "student_parameter_sha256",
              "student_inventory", "groups", "teacher_relative_passed", "final_retention", "passed"}
    if (execution.get("schema") != "hepta.stem.bound-execution.v3"
            or execution.get("output_profile") != OUTPUT_PROFILE
            or not isinstance(report, dict) or set(report) != fields
            or report["schema"] != "hepta.cell-consolidation.v1"
            or execution["training"].get("consolidation") != report
            or report["policy_id"] != _digest(policy) or report["output_profile"] != OUTPUT_PROFILE
            or report["disposition"] != "accepted_internal_candidate"
            or report["internal_selection_only"] is not True
            or report["passed"] is not True or report["teacher_relative_passed"] is not True
            or report["independent_gain_established"] is not False or report["production_authorized"] is not False):
        raise ValueError("invalid consolidation decision or stage identity")
    teacher, student, actual = report["teacher_inventory"], report["student_inventory"], execution["inventory"]
    for name in ("teacher_parameter_sha256", "teacher_reference_sha256",
                 "initialized_student_sha256", "student_parameter_sha256"):
        _sha(report[name], name)
    for inv, cells in ((teacher, 32), (student, 16), (actual, 16)):
        if not isinstance(inv, dict) or inv.get("cells") != cells or inv.get("active_cells_cap") != 2:
            raise ValueError("wrong teacher/student geometry")
        for name in ("parameters", "trainable_parameters", "head_params", "gate_params", "unique_weight_bytes"):
            _integer(inv.get(name), name, 1)
        if (inv["head_params"] + inv["gate_params"] != inv["parameters"]
                or inv["parameters"] != inv["trainable_parameters"]
                or inv["unique_weight_bytes"] != inv["parameters"] * 4):
            raise ValueError("inconsistent actual compressed storage")
    for name in ("parameters", "trainable_parameters", "head_params", "gate_params", "unique_weight_bytes"):
        if student[name] != actual[name]:
            raise ValueError("final bank differs from compressed successor")
    if "routing_profile" in student or "routing_profile" in actual:
        raise ValueError("16-Cell output cannot claim 32-Cell family routing")
    dimension = teacher["gate_params"] // 32 - 1
    classes = execution["classification_classes"]
    capacity = 2 if "_64m_" in config["arm_id"] else 1
    expected = 32 * (dimension + classes + 1) * config["width_units"] * capacity
    if (not 1 <= dimension <= 8192 or teacher["gate_params"] != 32 * (dimension + 1)
            or student["gate_params"] != 16 * (dimension + 1)
            or teacher["parameters"] != expected or student["parameters"] * 2 != expected
            or report["teacher_parameters"] != expected or report["student_parameters"] * 2 != expected
            or report["student_parameter_sha256"] != execution["trained_bank_sha256"]):
        raise ValueError("compression is not the bound half-parameter transformation")
    growth = execution["growth_receipt"]
    extra = growth["parent_parameters"] if growth["split_performed"] else 0
    peak = extra + expected + expected // 2
    if (report["retained_parent_parameters"] != extra or report["peak_live_trainable_params"] != peak
            or execution["peak_trainable_params"] != peak or peak > contract["max_peak_trainable_params"]):
        raise ValueError("compression omits live parent/teacher/student peak")
    retained = config["retention_policy"]
    before, final = execution["training"]["retention"], report["final_retention"]
    validate_retention_record(before, retained, report["teacher_parameter_sha256"], classes)
    validate_retention_record(final, retained, report["student_parameter_sha256"], classes)
    if execution.get("retention_receipt") != final:
        raise ValueError("final retention receipt is not the student")
    for name in ("reference_parameter_sha256", "reference_logits_sha256", "role_examples"):
        if before[name] != final[name]:
            raise ValueError("compression reset the original retention baseline")
    counts = before["role_examples"]
    if (report["role_examples"] != counts or report["teacher_reference_rows"] != sum(counts.values())
            or report["teacher_reference_payload_bytes"] != sum(counts.values()) * classes * 4):
        raise ValueError("reference work/payload denominator mismatch")
    training = report["training"]
    wanted = {r: policy["steps"] * min(counts[r], config["batch_size"]) for r in ROLES[:2]}
    if (not isinstance(training, dict) or set(training) != {"steps", "losses", "examples_seen_by_role", "optimizer_tensor_bytes"}
            or training["steps"] != policy["steps"] or training["examples_seen_by_role"] != wanted
            or not isinstance(training["losses"], list) or len(training["losses"]) != policy["steps"]
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in training["losses"])):
        raise ValueError("consolidation training schedule/denominators changed")
    _integer(training["optimizer_tensor_bytes"], "optimizer storage", 1)
    expected_groups = [(r, g) for r in ROLES[2:] for g in retained[r]]
    if not isinstance(report["groups"], list) or len(report["groups"]) != len(expected_groups):
        raise ValueError("complete consolidation validation denominator required")
    for row, (role, group) in zip(report["groups"], expected_groups, strict=True):
        if (not isinstance(row, dict) or set(row) != {"role", "source_group", "count", "baseline_correct",
                                                    "candidate_correct", "baseline_nll", "candidate_nll"}
                or (row["role"], row["source_group"]) != (role, group)):
            raise ValueError("wrong consolidation subgroup")
        count = _integer(row["count"], "validation group count", 1)
        for kind in ("baseline", "candidate"):
            if _integer(row[kind + "_correct"], "correct count") > count:
                raise ValueError("invalid consolidation correct count")
            nll = row[kind + "_nll"]
            if type(nll) not in (int, float) or not math.isfinite(nll) or nll < 0:
                raise ValueError("invalid consolidation group loss")
    for role in ROLES[2:]:
        if sum(r["count"] for r in report["groups"] if r["role"] == role) != counts[role]:
            raise ValueError("validation subgroup denominator mismatch")
    if not teacher_gate(report["groups"], policy):
        raise ValueError("consolidation teacher-relative gate violated")
    # The original checks still validate all original lineage and fitting counts.
    # Only the explicit precursor view has 32 Cells; exported inventory stays 16.
    return {**execution, "schema": "hepta.stem.bound-execution.v2",
            "inventory": teacher, "trained_bank_sha256": report["teacher_parameter_sha256"],
            "retention_receipt": before, "peak_trainable_params": growth["peak_live_trainable_params"]}
