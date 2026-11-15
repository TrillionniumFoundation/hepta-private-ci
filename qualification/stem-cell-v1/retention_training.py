"""Old-task replay and frozen-reference distillation inside offline growth.

The two validation folds are excluded from optimization and growth decisions.
They are INTERNAL model-selection data, not the final blind evaluator or proof
of future generalization. Replay preserves a model's behavior, including its
errors; old labels therefore remain supervised too. No parameters are merged,
installed, or compressed by this module.
"""
from __future__ import annotations

import hashlib
import math

import torch
from torch import nn

from matrix_bank import state_digest
from next_round_matrix import _digest

POLICY_SCHEMA = "hepta.cell-retention-policy.v1"
ROLES = ("old_train_groups", "new_train_groups", "old_validation_groups", "new_validation_groups")
COEFFICIENTS = {"replay_weight": (0., 1.), "distillation_weight": (0., 1.),
                "temperature": (1., 8.), "max_old_accuracy_drop": (0., 1.),
                "max_old_nll_increase": (0., 10.), "min_new_accuracy_gain": (0., 1.)}


class RetentionRejected(ValueError):
    """Internal validation failed; keep diagnostics, never a successful seal."""

    def __init__(self, report):
        super().__init__("retention_validation_failed")
        self.report = report


def validate_retention_policy(policy):
    if (not isinstance(policy, dict) or set(policy) != {"schema", *ROLES, *COEFFICIENTS}
            or policy["schema"] != POLICY_SCHEMA):
        raise ValueError("complete versioned retention policy required")
    seen = set()
    for role in ROLES:
        groups = policy[role]
        if (not isinstance(groups, list) or not 1 <= len(groups) <= 4096
                or any(not isinstance(g, str) or not g or len(g.encode()) > 256 for g in groups)
                or groups != sorted(set(groups)) or seen.intersection(groups)):
            raise ValueError("canonical, disjoint, bounded retention source groups required")
        seen.update(groups)
    if len(seen) > 4096:
        raise ValueError("retention group inventory exceeds workload limit")
    for key, (low, high) in COEFFICIENTS.items():
        v = policy[key]
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError("invalid retention coefficient: " + key)
    if policy["replay_weight"] == 0 or policy["distillation_weight"] == 0:
        raise ValueError("this profile requires supervised replay and reference distillation")


def partition_groups(source_groups, policy):
    validate_retention_policy(policy)
    if (not isinstance(source_groups, list) or not 1 <= len(source_groups) <= 4096
            or any(not isinstance(g, str) or not g for g in source_groups)):
        raise ValueError("bounded training source groups required")
    declared = set(g for role in ROLES for g in policy[role])
    if set(source_groups) != declared:
        raise ValueError("retention roles must cover exactly the supplied training groups")
    return {role: [i for i, g in enumerate(source_groups) if g in set(policy[role])] for role in ROLES}


def validate_retention_rows(rows, policy):
    """Run before any model call; group names alone do not establish disjointness."""
    roles = partition_groups([r["source_group"] for r in rows], policy)
    seen = {}
    for role, indices in roles.items():
        for i in indices:
            content = _digest({k: rows[i][k] for k in ("state", "question", "options")})
            if content in seen and seen[content] != role:
                raise ValueError("exact input shared by optimization/validation or old/new roles")
            seen[content] = role
    return roles


def reference_kl(student_logits, reference_logits, temperature):
    """T^2 KL(reference || student), class-sum then batch-mean, not element mean."""
    if (reference_logits.requires_grad or student_logits.shape != reference_logits.shape
            or student_logits.ndim != 2 or not 1 <= len(student_logits) <= 4096
            or type(temperature) not in (int, float) or not math.isfinite(temperature) or not 1 <= temperature <= 8):
        raise ValueError("shape-matched detached reference required")
    a = (reference_logits / temperature).log_softmax(1)
    b = (student_logits / temperature).log_softmax(1)
    return (a.exp() * (a - b)).sum() / len(a) * temperature * temperature


class RetentionSession:
    """Bound training partition and one frozen-logit reference; no teacher copy.

    This object retains the one existing feature tensor, not a second feature
    cache. The reference logits are separately bounded/accounted. Validation
    labels are used only after second-stage weights have been fixed.
    """

    def __init__(self, features, targets, source_groups, policy, *, cache_budget):
        roles = partition_groups(source_groups, policy)
        if (features.ndim != 2 or not 1 <= len(features) <= 4096 or features.requires_grad
                or features.dtype != torch.float32 or features.device.type != "cpu"
                or targets.shape != (len(features),) or targets.dtype != torch.long
                or targets.device.type != "cpu" or len(source_groups) != len(features)):
            raise ValueError("bounded frozen CPU feature and label geometry required")
        import copy
        self.x, self.y, self.groups, self.policy = features, targets, list(source_groups), copy.deepcopy(policy)
        self.ids = {role: torch.tensor(indices, dtype=torch.long) for role, indices in roles.items()}
        self.cache_budget = cache_budget
        self.reference = None
        self.first_digest = None

    def capture(self, bank):
        required = len(self.x) * bank.classes * 4
        if type(self.cache_budget) is not int or required > self.cache_budget or self.reference is not None:
            raise ValueError("reference cache budget exceeded or reference already fixed")
        self.first_digest = state_digest(bank)
        self.reference = torch.zeros((len(self.x), bank.classes), dtype=torch.float32)
        with torch.no_grad():
            for role in ("old_train_groups", "old_validation_groups", "new_validation_groups"):
                for start in range(0, len(self.ids[role]), 64):
                    ids = self.ids[role][start:start + 64]
                    logits = bank(self.x[ids])
                    if not torch.isfinite(logits).all().item():
                        raise ValueError("nonfinite retention reference")
                    self.reference.index_copy_(0, ids, logits)
        self.reference_sha256 = hashlib.sha256(self.reference.numpy().tobytes()).hexdigest()
        if state_digest(bank) != self.first_digest:
            raise ValueError("reference capture mutated first-stage weights")

    def train(self, bank, config, *, steps, seed):
        """Only new/train and old/replay inputs reach the optimizer or auxiliary gate."""
        if (type(steps) is not int or not 1 <= steps <= 512
                or type(config["batch_size"]) is not int or not 1 <= config["batch_size"] <= 128):
            raise ValueError("bounded retention training steps/batch required")
        if self.reference is None or self.reference.requires_grad:
            raise ValueError("frozen reference must precede specialization")
        rng = torch.Generator(device="cpu").manual_seed(seed)
        opt = torch.optim.AdamW(bank.parameters(), lr=.001, weight_decay=.01)
        bank.train()
        old, new = self.ids[ROLES[0]], self.ids[ROLES[1]]
        old_batch, new_batch = min(len(old), config["batch_size"]), min(len(new), config["batch_size"])
        losses = []
        for _ in range(steps):
            a = old[torch.randint(len(old), (old_batch,), generator=rng)]
            b = new[torch.randint(len(new), (new_batch,), generator=rng)]
            opt.zero_grad(set_to_none=True)
            loss = bank.training_loss(self.x[b], self.y[b])
            loss = loss + self.policy["replay_weight"] * bank.training_loss(self.x[a], self.y[a])
            # This is a THIRD actual bank call, deliberately not treated as free.
            loss = loss + self.policy["distillation_weight"] * reference_kl(
                bank(self.x[a]), self.reference[a], self.policy["temperature"])
            if not torch.isfinite(loss).item():
                raise ValueError("nonfinite retained-specialization objective")
            loss.backward()
            nn.utils.clip_grad_norm_(bank.parameters(), 1.)
            opt.step()
            losses.append(float(loss.detach()))
        if not all(torch.isfinite(p).all().item() for p in bank.parameters()):
            raise ValueError("nonfinite retained candidate")
        bank.eval()
        optimizer_bytes = sum(v.numel() * v.element_size() for s in opt.state.values()
                              for v in s.values() if isinstance(v, torch.Tensor))
        return {"steps": steps, "examples_seen": steps * (old_batch + new_batch), "losses": losses,
                "optimizer_tensor_bytes": optimizer_bytes, "replay_examples_seen": steps * old_batch,
                "new_examples_seen": steps * new_batch, "reference_bank_rows": steps * old_batch}

    def evaluate(self, bank):
        """Fixed internal validation, subgroup intersection; no threshold fitting/retry."""
        if self.reference is None:
            raise ValueError("missing pre-specialization reference")
        candidate_digest = state_digest(bank)
        results = []
        with torch.no_grad():
            for role in ROLES[2:]:
                for group in self.policy[role]:
                    ids = torch.tensor([i for i in self.ids[role].tolist() if self.groups[i] == group])
                    stats = {"count": len(ids), "baseline_correct": 0, "candidate_correct": 0,
                             "baseline_nll": 0., "candidate_nll": 0.}
                    for start in range(0, len(ids), 64):
                        batch = ids[start:start + 64]
                        a, b, y = self.reference[batch], bank(self.x[batch]), self.y[batch]
                        if not torch.isfinite(b).all().item():
                            raise ValueError("nonfinite internal validation prediction")
                        for name, logits in (("baseline", a), ("candidate", b)):
                            stats[name + "_correct"] += int((logits.argmax(1) == y).sum().item())
                            nll = -logits.log_softmax(1).gather(1, y[:, None]).sum().item()
                            stats[name + "_nll"] += nll / len(ids)
                    results.append({"role": role, "source_group": group, **stats})
        report = {"schema": "hepta.retention-observation.v1", "policy_id": _digest(self.policy),
                  "reference_parameter_sha256": self.first_digest, "candidate_parameter_sha256": candidate_digest,
                  "reference_logits_sha256": self.reference_sha256,
                  "reference_payload_bytes": self.reference.numel() * self.reference.element_size(),
                  "role_examples": {r: len(v) for r, v in self.ids.items()}, "groups": results,
                  "validation_role": "internal_selection_not_final_blind_evaluation",
                  "independent_future_gain_established": False, "production_authorized": False}
        report["passed"] = gate_passes(report, self.policy)
        if state_digest(bank) != candidate_digest or hashlib.sha256(self.reference.numpy().tobytes()).hexdigest() != self.reference_sha256:
            raise ValueError("validation changed fixed weights or reference")
        if not report["passed"]:
            raise RetentionRejected(report)
        return report


def gate_passes(report, policy):
    """Recompute every decision from fixed policy and observed subgroup counts."""
    passed = True
    for row in report["groups"]:
        gain = (row["candidate_correct"] - row["baseline_correct"]) / row["count"]
        if row["role"] == ROLES[2]:
            passed = passed and gain >= -policy["max_old_accuracy_drop"]
            passed = passed and row["candidate_nll"] - row["baseline_nll"] <= policy["max_old_nll_increase"]
        else:
            passed = passed and gain >= policy["min_new_accuracy_gain"]
    return bool(passed)


def validate_retention_record(report, policy, candidate_digest, classes):
    """Structural export validation; hashes and group names are not attestation."""
    from paired_execution import _integer, _sha
    validate_retention_policy(policy)
    fields = {"schema", "policy_id", "reference_parameter_sha256", "candidate_parameter_sha256",
              "reference_logits_sha256", "reference_payload_bytes", "role_examples", "groups",
              "validation_role", "independent_future_gain_established", "production_authorized", "passed"}
    if (not isinstance(report, dict) or set(report) != fields or report["schema"] != "hepta.retention-observation.v1"
            or report["policy_id"] != _digest(policy) or report["candidate_parameter_sha256"] != candidate_digest
            or report["validation_role"] != "internal_selection_not_final_blind_evaluation"
            or report["independent_future_gain_established"] is not False or report["production_authorized"] is not False
            or report["passed"] is not True or not isinstance(report["role_examples"], dict)
            or set(report["role_examples"]) != set(ROLES)):
        raise ValueError("invalid retention decision/provenance")
    for name in ("reference_parameter_sha256", "candidate_parameter_sha256", "reference_logits_sha256"):
        _sha(report[name], name)
    for n in report["role_examples"].values():
        _integer(n, "role denominator", 1)
    count = sum(report["role_examples"].values())
    if count > 4096 or type(report["reference_payload_bytes"]) is not int or report["reference_payload_bytes"] != count * classes * 4:
        raise ValueError("invalid bounded reference payload")
    expected = [(r, g) for r in ROLES[2:] for g in policy[r]]
    if not isinstance(report["groups"], list) or len(report["groups"]) != len(expected):
        raise ValueError("complete internal validation group denominator required")
    for row, (role, group) in zip(report["groups"], expected, strict=True):
        if (not isinstance(row, dict) or set(row) != {"role", "source_group", "count", "baseline_correct",
                                                    "candidate_correct", "baseline_nll", "candidate_nll"}
                or row["role"] != role or row["source_group"] != group):
            raise ValueError("invalid validation subgroup identity")
        n = _integer(row["count"], "subgroup count", 1)
        for kind in ("baseline", "candidate"):
            if _integer(row[kind + "_correct"], "correct count") > n:
                raise ValueError("correct count exceeds denominator")
            loss = row[kind + "_nll"]
            if type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0:
                raise ValueError("invalid subgroup log loss")
    for role in ROLES[2:]:
        if sum(r["count"] for r in report["groups"] if r["role"] == role) != report["role_examples"][role]:
            raise ValueError("validation denominator mismatch")
    if not gate_passes(report, policy):
        raise ValueError("retention gate violated")
