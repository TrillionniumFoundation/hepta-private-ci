"""Offline 32-family to 16-parent behavioral distillation, never weight averaging.

One fixed candidate is trained on the existing fitting folds only. Both original
retention gates and teacher-relative subgroup gates must pass. Internal selection
is not independent future evaluation. No production topology is installed.
"""
from __future__ import annotations

import contextlib
import hashlib
import math

import torch
from torch import nn

from family_routing import FamilyCellBank
from matrix_bank import CellBank, state_digest
from next_round_matrix import _digest
from retention_training import ROLES, RetentionRejected, reference_kl

POLICY_SCHEMA = "hepta.cell-consolidation-policy.v1"
OUTPUT_PROFILE = "consolidated_parent16_mlp.v1"


class ConsolidationRejected(ValueError):
    """Preserve the unsuccessful candidate's observations; no success seal."""

    def __init__(self, report):
        super().__init__(report["disposition"])
        self.report = report


def validate_policy(policy):
    fields = {"schema", "steps", "temperature", "distillation_weight",
              "max_accuracy_drop", "max_nll_increase"}
    if not isinstance(policy, dict) or set(policy) != fields or policy["schema"] != POLICY_SCHEMA:
        raise ValueError("complete versioned consolidation policy required")
    if type(policy["steps"]) is not int or not 1 <= policy["steps"] <= 512:
        raise ValueError("bounded consolidation steps required")
    limits = {"temperature": (1, 8), "distillation_weight": (0, 1),
              "max_accuracy_drop": (0, 1), "max_nll_increase": (0, 10)}
    for name, (low, high) in limits.items():
        value = policy[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("invalid consolidation coefficient: " + name)
    if policy["distillation_weight"] == 0:
        raise ValueError("this compression profile requires behavioral distillation")


def student_recipe(profile):
    """The original arm describes training history; the output is explicitly 16."""
    return {**profile, "logical_cells": 16, "initial_logical_cells": 16,
            "split": False, "ndu": False, "resident_stem_copies": 1}


def teacher_gate(groups, policy):
    """Apply every frozen teacher-relative limit; no improvement hides a loss."""
    return all((r["candidate_correct"] - r["baseline_correct"]) / r["count"] >= -policy["max_accuracy_drop"]
               and r["candidate_nll"] - r["baseline_nll"] <= policy["max_nll_increase"] for r in groups)


def consolidate(teacher, retention, config, contract, profile, growth, *, seed, meter):
    """Create and train a physically smaller successor under the same live cap.

    The caller's initial parent stays live until train_with_growth returns. Count
    it alongside teacher and student; no extra teacher parameter copy is made.
    Reference logits are a second, separately preflighted retained payload.
    """
    policy = config["consolidation_policy"]
    validate_policy(policy)
    if not isinstance(teacher, FamilyCellBank) or len(teacher.heads) != 32 or retention is None:
        raise ValueError("consolidation requires retained family specialization")
    if meter is None:
        raise ValueError("consolidation requires its live execution meter")
    scope = meter.scope
    total = sum(p.numel() for p in teacher.parameters())
    expected = 16 * (teacher.dimension + teacher.classes + 1) * config["width_units"] * (
        profile["total_head_budget_params"] // 32_000_000)
    extra_parent = growth["parent_parameters"] if growth["split_performed"] else 0
    peak = extra_parent + total + expected
    if expected * 2 != total or peak > contract["max_peak_trainable_params"]:
        raise ValueError("consolidation live-parent/teacher/student parameter cap exceeded")
    payload = len(retention.x) * teacher.classes * 4
    fit_count = sum(len(retention.ids[r]) for r in ROLES[:2])
    # Count original features, both logit references, and the reserved fitting slice.
    required = retention.x.numel() * 4 + 2 * payload + fit_count * teacher.dimension * 4
    if required > config["max_feature_bytes"]:
        raise ValueError("consolidation reference payload exceeds the bound")
    report = {"schema": "hepta.cell-consolidation.v1", "policy_id": _digest(policy),
              "output_profile": OUTPUT_PROFILE, "disposition": "candidate",
              "teacher_parameters": total, "student_parameters": expected,
              "retained_parent_parameters": extra_parent, "peak_live_trainable_params": peak,
              "teacher_parameter_sha256": state_digest(teacher),
              "teacher_reference_payload_bytes": payload, "teacher_reference_rows": len(retention.x),
              "role_examples": {r: len(retention.ids[r]) for r in ROLES},
              "internal_selection_only": True, "independent_gain_established": False,
              "production_authorized": False}
    with scope("train", "bank"):
        reference = torch.empty((len(retention.x), teacher.classes), dtype=torch.float32)
        with torch.no_grad():
            for start in range(0, len(reference), 64):
                logits = teacher(retention.x[start:start + 64])
                if not torch.isfinite(logits).all().item():
                    raise ValueError("nonfinite compression reference")
                reference[start:start + 64].copy_(logits)
        report["teacher_reference_sha256"] = hashlib.sha256(reference.numpy().tobytes()).hexdigest()
        report["teacher_inventory"] = teacher.inventory()
    with scope("migration", "bank"):
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(seed)
            student = CellBank(teacher.dimension, teacher.classes, student_recipe(profile), config["width_units"] // 2)
        with torch.no_grad():
            # Deterministic warm start from sibling zero, not averaging divergent weights.
            for index, head in enumerate(student.heads):
                head.load_state_dict(teacher.heads[index].state_dict(), strict=True)
            ids = torch.arange(16)
            student.gate.weight.copy_(teacher.gate.weight.index_select(0, ids))
            student.gate.bias.copy_(teacher.gate.bias.index_select(0, ids))
        if sum(p.numel() for p in student.parameters()) != expected:
            raise ValueError("unexpected compression geometry")
        report["initialized_student_sha256"] = state_digest(student)
    with scope("train", "bank"):
        rng = torch.Generator(device="cpu").manual_seed(seed)
        optimizer = torch.optim.AdamW(student.parameters(), lr=.001, weight_decay=.01)
        batches = {r: min(len(retention.ids[r]), config["batch_size"]) for r in ROLES[:2]}
        student.train()
        losses = []
        for _ in range(policy["steps"]):
            optimizer.zero_grad(set_to_none=True)
            loss = None
            for role in ROLES[:2]:
                pool = retention.ids[role]
                ids = pool[torch.randint(len(pool), (batches[role],), generator=rng)]
                logits = student(retention.x[ids])
                term = nn.functional.cross_entropy(logits, retention.y[ids])
                term = term + policy["distillation_weight"] * reference_kl(
                    logits, reference[ids], policy["temperature"])
                loss = term if loss is None else loss + term
            if not torch.isfinite(loss).item():
                raise ValueError("nonfinite consolidation loss")
            loss.backward()
            nn.utils.clip_grad_norm_(student.parameters(), 1.)
            optimizer.step()
            losses.append(float(loss.detach()))
        if not all(torch.isfinite(p).all().item() for p in student.parameters()):
            raise ValueError("nonfinite compressed weights")
        report["training"] = {"steps": policy["steps"], "losses": losses,
                              "examples_seen_by_role": {r: policy["steps"] * batches[r] for r in batches},
                              "optimizer_tensor_bytes": sum(v.numel() * v.element_size() for s in optimizer.state.values()
                                                            for v in s.values() if isinstance(v, torch.Tensor))}
        del optimizer
        student.eval()
        student.zero_grad(set_to_none=True)
        digest = state_digest(student)
        report["student_parameter_sha256"] = digest
        report["student_inventory"] = student.inventory()
        # Internal holdout labels are first accessed after the final update.
        groups = []
        with torch.no_grad():
            for role in ROLES[2:]:
                for group in retention.policy[role]:
                    ids = torch.tensor([i for i in retention.ids[role].tolist() if retention.groups[i] == group])
                    row = {"role": role, "source_group": group, "count": len(ids),
                           "baseline_correct": 0, "candidate_correct": 0, "baseline_nll": 0., "candidate_nll": 0.}
                    for start in range(0, len(ids), 64):
                        selected = ids[start:start + 64]
                        logits = student(retention.x[selected])
                        if not torch.isfinite(logits).all().item():
                            raise ValueError("nonfinite compressed validation")
                        for name, value in (("baseline", reference[selected]), ("candidate", logits)):
                            y = retention.y[selected]
                            row[name + "_correct"] += int((value.argmax(1) == y).sum().item())
                            row[name + "_nll"] += -value.log_softmax(1).gather(1, y[:, None]).sum().item() / len(ids)
                    groups.append(row)
        report["groups"] = groups
        report["teacher_relative_passed"] = teacher_gate(groups, policy)
        try:
            # Also recheck the ORIGINAL pre-specialization retention baseline.
            report["final_retention"] = retention.evaluate(student)
        except RetentionRejected as exc:
            report["final_retention"] = exc.report
        report["passed"] = report["teacher_relative_passed"] and report["final_retention"]["passed"]
        if (state_digest(teacher) != report["teacher_parameter_sha256"] or state_digest(student) != digest
                or hashlib.sha256(reference.numpy().tobytes()).hexdigest() != report["teacher_reference_sha256"]):
            raise ValueError("fixed teacher, reference or student changed during consolidation evaluation")
        report["disposition"] = "accepted_internal_candidate" if report["passed"] else "consolidation_validation_failed"
    if not report["passed"]:
        raise ConsolidationRejected(report)
    return student, report
