import copy
import unittest
from unittest.mock import patch

import torch

import test_retention_training as fixtures
from consolidation_training import (POLICY_SCHEMA, ConsolidationRejected, consolidate, teacher_gate, validate_policy)
from execution_meter import WorkLedger, BudgetStop
from family_routing import FamilyCellBank
from matrix_bank import state_digest
from matrix_materials import validate_config
from retention_training import RetentionSession, ROLES


def consolidation_policy():
    # Permissive, test-only selection thresholds; not model acceptance.
    return {"schema": POLICY_SCHEMA, "steps": 3, "temperature": 2., "distillation_weight": .5,
            "max_accuracy_drop": 1., "max_nll_increase": 10.}


def core_case():
    p, c, cfg, work = fixtures.retained_setup("shared_421m_sparse_direct32_no_ndu")
    cfg = copy.deepcopy(cfg)
    x = torch.tensor([[float(r["state"]), 1., float(r["state"])**2, -float(r["state"])] for r in work["train"]])
    y = torch.tensor([r["label"] for r in work["train"]])
    groups = [r["source_group"] for r in work["train"]]
    profile = validate_config(p, c, cfg)
    with torch.random.fork_rng():
        torch.manual_seed(12)
        teacher = FamilyCellBank(4, 2, profile, cfg["width_units"], sibling_loss_weight=.1)
    # Identical constant logits provide a real, simple initial reference; training is real.
    with torch.no_grad():
        for head in teacher.heads:
            head[-1].weight.zero_()
            head[-1].bias.copy_(torch.tensor([2., 0.]))
    teacher.eval()
    session = RetentionSession(x, y, groups, cfg["retention_policy"], cache_budget=100000)
    session.capture(teacher)
    cfg["consolidation_policy"] = consolidation_policy()
    meter = WorkLedger(cfg["measurement_policy"], c["flops_caps"])
    return teacher, session, cfg, c, profile, {"split_performed": False}, meter


def call(case, **overrides):
    teacher, session, cfg, contract, profile, growth, meter = case
    return consolidate(teacher, session, cfg, contract, profile, growth, seed=123, meter=meter, **overrides)


class ConsolidationTests(unittest.TestCase):
    def test_actual_compression_half_parameters_and_live_costs(self):
        case = core_case()
        before = state_digest(case[0])
        student, report = call(case)
        self.assertEqual((len(case[0].heads), len(student.heads)), (32, 16))
        self.assertEqual((report["teacher_parameters"], report["student_parameters"]), (896, 448))
        self.assertEqual(report["peak_live_trainable_params"], 1344)
        self.assertEqual(state_digest(case[0]), before)
        self.assertNotEqual(report["initialized_student_sha256"], report["student_parameter_sha256"])
        self.assertEqual(report["training"]["examples_seen_by_role"],
                         {"old_train_groups": 6, "new_train_groups": 6})
        self.assertGreater(case[-1].report()["phase_flops"]["train"], 0)
        self.assertGreater(case[-1].report()["phase_flops"]["migration"], 0)
        self.assertEqual(case[-1].report()["unknown_operators"], {})
        self.assertFalse(report["independent_gain_established"])
        self.assertTrue(report["final_retention"]["passed"])

    def test_student_has_no_storage_aliases_with_teacher(self):
        case = core_case(); student, report = call(case)
        teacher_storage = {p.untyped_storage().data_ptr() for p in case[0].parameters()}
        self.assertFalse(teacher_storage & {p.untyped_storage().data_ptr() for p in student.parameters()})
        self.assertEqual(report["student_inventory"]["unique_weight_bytes"], 448 * 4)

    def test_invalid_policy_never_silently_disables_checks(self):
        for key, value in (("steps", True), ("temperature", float("nan")),
                           ("distillation_weight", 0.), ("max_accuracy_drop", 1.1),
                           ("max_nll_increase", -1), ("override", True)):
            policy = consolidation_policy(); policy[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_policy(policy)

    def test_preflight_includes_caller_parent_and_refuses_before_allocation(self):
        case = list(core_case())
        case[5] = {"split_performed": True, "parent_parameters": 448}
        case[3] = {**case[3], "max_peak_trainable_params": 1791}
        with patch("consolidation_training.CellBank") as factory:
            with self.assertRaisesRegex(ValueError, "parameter cap"): call(case)
            factory.assert_not_called()
        case[3]["max_peak_trainable_params"] = 1792
        _, report = call(case)
        self.assertEqual(report["peak_live_trainable_params"], 1792)

    def test_two_reference_payloads_are_preflighted(self):
        case = list(core_case())
        case[2] = {**case[2], "max_feature_bytes": 8*4*4 + 2*8*2*4 + 4*4*4 - 1}
        with patch("consolidation_training.CellBank") as factory:
            with self.assertRaisesRegex(ValueError, "payload"): call(case)
            factory.assert_not_called()

    def test_validation_labels_do_not_change_trained_student(self):
        a, b = core_case(), core_case()
        for role in ROLES[2:]:
            b[1].y[b[1].ids[role]] = 1 - b[1].y[b[1].ids[role]]
        left, _ = call(a)
        right, _ = call(b)
        self.assertEqual(state_digest(left), state_digest(right))

    def test_real_teacher_relative_subgroup_degradation_rejects(self):
        case = core_case()
        case[2]["consolidation_policy"]["max_accuracy_drop"] = 0.
        # Clone sibling zero predicts the wrong class, while the teacher routes sibling one.
        with torch.no_grad():
            case[0].gate.bias[16:].fill_(10.)
            for head in case[0].heads[:16]:
                head[-1].bias.copy_(torch.tensor([0., 8.]))
        with self.assertRaises(ConsolidationRejected) as caught:
            call(case)
        self.assertFalse(caught.exception.report["teacher_relative_passed"])
        self.assertEqual(caught.exception.report["disposition"], "consolidation_validation_failed")

    def test_no_overall_mean_can_hide_one_subgroup(self):
        rows = [{"count": 10, "candidate_correct": 9, "baseline_correct": 10, "candidate_nll": .1, "baseline_nll": .1},
                {"count": 10, "candidate_correct": 10, "baseline_correct": 0, "candidate_nll": .1, "baseline_nll": 1.}]
        policy = consolidation_policy(); policy["max_accuracy_drop"] = 0.
        self.assertFalse(teacher_gate(rows, policy))

    def test_strict_budget_stop_does_not_change_teacher(self):
        case = list(core_case())
        case[-1] = WorkLedger(case[2]["measurement_policy"], dict.fromkeys(case[3]["flops_caps"], 1))
        before = state_digest(case[0])
        with self.assertRaises(BudgetStop): call(case)
        self.assertEqual(state_digest(case[0]), before)


if __name__ == "__main__":
    unittest.main()
