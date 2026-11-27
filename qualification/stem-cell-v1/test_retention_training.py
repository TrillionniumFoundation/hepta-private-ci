import copy
import unittest
from unittest.mock import patch

import torch

import test_family_routing as fixtures
from growth_test_support import run_growth
from matrix_bank import state_digest
from matrix_materials import freeze_config, validate_config
from matrix_test_support import FixtureEncoder
from retention_training import (POLICY_SCHEMA, ROLES, RetentionRejected, RetentionSession,
                                gate_passes, partition_groups, reference_kl,
                                validate_retention_policy, validate_retention_record, validate_retention_rows)


def retained_setup(arm="shared_421m_sparse_split_no_ndu"):
    p, c, cfg, work = fixtures.family_setup(arm)
    for prefix, magnitude, when in (("n", 3., 6), ("v", 1.5, 8), ("w", 4., 9)):
        for side in range(2):
            row = copy.deepcopy(work["train"][side])
            row.update(sample_id=prefix + str(side), source_group=prefix + str(side),
                       state=str(magnitude * (2 * side - 1)), available_at_ns=when,
                       label_observed_at_ns=when)
            work["train"].append(row)
    policy = {"schema": POLICY_SCHEMA, "old_train_groups": ["t0", "t1"],
              "new_train_groups": ["n0", "n1"], "old_validation_groups": ["v0", "v1"],
              "new_validation_groups": ["w0", "w1"], "replay_weight": .5,
              "distillation_weight": .5, "temperature": 2., "max_old_accuracy_drop": 1.,
              "max_old_nll_increase": 10., "min_new_accuracy_gain": 0.}
    # Permissive test-only thresholds exercise plumbing, not scientific acceptance.
    values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
    return p, c, freeze_config(p, c, **values, retention_policy=policy), work


class RetentionTrainingTests(unittest.TestCase):
    def test_policy_roles_disjoint_canonical_and_bounded(self):
        policy = retained_setup()[2]["retention_policy"]
        validate_retention_policy(policy)
        for field, value in (("old_train_groups", ["t1", "t0"]), ("new_train_groups", ["t0"]),
                             ("old_validation_groups", []), ("temperature", True),
                             ("distillation_weight", 0.), ("replay_weight", float("nan")),
                             ("max_old_accuracy_drop", -1), ("override", True)):
            bad = copy.deepcopy(policy); bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_retention_policy(bad)

    def test_roles_cover_exact_training_inventory_and_reject_input_overlap(self):
        _, _, cfg, work = retained_setup(); policy = cfg["retention_policy"]
        roles = validate_retention_rows(work["train"], policy)
        self.assertEqual([len(roles[r]) for r in ROLES], [2, 2, 2, 2])
        groups = [r["source_group"] for r in work["train"]]
        with self.assertRaises(ValueError): partition_groups(groups + ["unassigned"], policy)
        work["train"][4]["state"] = work["train"][0]["state"]
        with self.assertRaises(ValueError): validate_retention_rows(work["train"], policy)

    def test_kl_orientation_and_batch_normalization_match_independent_formula(self):
        student = torch.tensor([[1., -1., .3], [.5, .2, -.9]], requires_grad=True)
        reference = torch.tensor([[2., 0., -2.], [0., 1., -1.]])
        value = reference_kl(student, reference, 2.)
        target = (reference / 2.).log_softmax(1)
        expected = torch.nn.functional.kl_div((student / 2.).log_softmax(1), target,
                                              reduction="batchmean", log_target=True) * 4
        torch.testing.assert_close(value, expected)
        torch.testing.assert_close(reference_kl(student.repeat(2, 1), reference.repeat(2, 1), 2.), value)
        value.backward(); self.assertGreater(student.grad.abs().sum().item(), 0.)
        with self.assertRaises(ValueError): reference_kl(student, reference.requires_grad_(), 2.)
        with self.assertRaises(ValueError): reference_kl(student, reference.detach(), 0.)

    def test_group_intersection_rejects_hidden_subgroup_regression(self):
        policy = retained_setup()[2]["retention_policy"]
        policy["max_old_accuracy_drop"] = .1
        report = {"groups": [dict(role=ROLES[2], count=10, baseline_correct=10, candidate_correct=8,
                                  baseline_nll=.1, candidate_nll=.2),
                              dict(role=ROLES[2], count=10, baseline_correct=0, candidate_correct=10,
                                   baseline_nll=1., candidate_nll=.1)]}
        self.assertFalse(gate_passes(report, policy))
        report["groups"][0]["candidate_correct"] = 10
        self.assertTrue(gate_passes(report, policy))

    def test_actual_retained_training_is_metered_and_sealed_diagnostics_are_bounded(self):
        parts = retained_setup(); _, _, cfg, _ = parts
        bank, m, rows = run_growth(parts)
        self.assertEqual(cfg["schema"], "hepta.stem.bound-hf-config.v5")
        r = m["retention_receipt"]
        validate_retention_record(r, cfg["retention_policy"], state_digest(bank), 2)
        self.assertEqual(r["role_examples"], dict.fromkeys(ROLES, 2))
        self.assertEqual(r["reference_payload_bytes"], 64)
        self.assertEqual(m["growth_receipt"]["probe_examples"], 4)
        self.assertEqual(m["growth_receipt"]["residual_probe_examples"], 2)
        self.assertEqual(m["training"]["retained_specialization"],
                         {"replay_examples_seen": 8, "new_examples_seen": 8, "reference_bank_rows": 8})
        self.assertEqual(m["work_observation"]["unknown_operators"], {})
        self.assertGreater(m["phase_flops"]["train"], 0)
        self.assertEqual([r["task_id"] for r in rows], parts[1]["task_ids"])
        self.assertFalse(r["independent_future_gain_established"])

    def test_no_heldout_row_reaches_gradient_or_sibling_supervision(self):
        from family_routing import FamilyCellBank
        seen = []
        original = FamilyCellBank.training_loss
        def record(bank, features, targets):
            seen.extend(features[:, 0].tolist())
            return original(bank, features, targets)
        with patch.object(FamilyCellBank, "training_loss", record): run_growth(retained_setup())
        self.assertTrue(set(seen).issubset({-1., 1., -3., 3.}))
        self.assertTrue({-1., 1.}.intersection(seen))
        self.assertTrue({-3., 3.}.intersection(seen))

    def test_validation_labels_cannot_change_trained_weights_or_growth(self):
        parts = retained_setup()
        bank, m, _ = run_growth(parts)
        changed = copy.deepcopy(parts)
        for row in changed[3]["train"]:
            if row["source_group"].startswith(("v", "w")): row["label"] = 1 - row["label"]
        try:
            bank2, m2, _ = run_growth(changed)
            observed = state_digest(bank2)
        except RetentionRejected as error:
            observed = error.report["candidate_parameter_sha256"]
        self.assertEqual(state_digest(bank), observed)

    def test_reference_payload_bound_rejects_before_encoding(self):
        parts = retained_setup(); p, c, cfg, work = parts
        values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
        values["max_feature_bytes"] = 128  # Main features alone fit, reference/subset do not.
        cfg = freeze_config(p, c, **values)
        backend = FixtureEncoder()
        with self.assertRaises(ValueError): run_growth((p, c, cfg, work), backend)
        self.assertEqual(backend.calls, 0)

    def test_direct_and_split_share_final_counts_but_differ_in_first_stage(self):
        reports = []
        for arm in ("shared_421m_sparse_direct32_no_ndu", "shared_421m_sparse_split_no_ndu"):
            _, m, _ = run_growth(retained_setup(arm)); reports.append(m)
        self.assertEqual([r["inventory"]["parameters"] for r in reports], [896, 896])
        self.assertEqual([r["peak_trainable_params"] for r in reports], [896, 1344])
        self.assertEqual(reports[0]["training"]["retained_specialization"], reports[1]["training"]["retained_specialization"])

    def test_policy_binding_and_legacy_rejection(self):
        p, c, cfg, _ = retained_setup()
        validate_config(p, c, cfg)
        mutated = copy.deepcopy(cfg); mutated["retention_policy"]["temperature"] += 1
        with self.assertRaises(ValueError): validate_config(p, c, mutated)
        values = {k: v for k, v in cfg.items() if k not in ("schema", "config_id", "contract_id")}
        values["growth_policy"] = None
        with self.assertRaises(ValueError): freeze_config(p, c, **values)
        caller = copy.deepcopy(cfg["retention_policy"])
        values["growth_policy"] = cfg["growth_policy"]; values["retention_policy"] = caller
        frozen = freeze_config(p, c, **values); caller[ROLES[0]].append("mutated")
        validate_config(p, c, frozen)

    def test_record_tampering_does_not_become_valid_by_asserting_pass(self):
        parts = retained_setup(); bank, m, _ = run_growth(parts)
        for how in ("group", "denominator", "bool", "nan", "hash", "scope", "missing"):
            record = copy.deepcopy(m["retention_receipt"])
            if how == "group": record["groups"][0]["source_group"] = "wrong"
            if how == "denominator": record["groups"][0]["count"] += 1
            if how == "bool": record["groups"][0]["candidate_correct"] = True
            if how == "nan": record["groups"][0]["candidate_nll"] = float("nan")
            if how == "hash": record["candidate_parameter_sha256"] = "a" * 64
            if how == "scope": record["independent_future_gain_established"] = True
            if how == "missing": record["groups"].pop()
            with self.subTest(how=how), self.assertRaises(ValueError):
                validate_retention_record(record, parts[2]["retention_policy"], state_digest(bank), 2)

    def test_a_real_accuracy_regression_is_rejected_not_just_reported(self):
        parts = retained_setup(); policy = parts[2]["retention_policy"]
        policy["max_old_accuracy_drop"] = 0.
        x = torch.tensor([[-1., 0.], [1., 0.]] * 4)
        y = torch.tensor([0, 1] * 4)
        groups = ["t0", "t1", "n0", "n1", "v0", "v1", "w0", "w1"]
        bank = torch.nn.Linear(2, 2); bank.classes = 2
        with torch.no_grad(): bank.weight.copy_(torch.tensor([[-1., 0.], [1., 0.]])); bank.bias.zero_()
        session = RetentionSession(x, y, groups, policy, cache_budget=64)
        session.capture(bank)
        with torch.no_grad(): bank.weight.mul_(-1)
        with self.assertRaises(RetentionRejected) as caught: session.evaluate(bank)
        self.assertFalse(caught.exception.report["passed"])
        self.assertEqual(caught.exception.report["groups"][0]["baseline_correct"], 1)
        self.assertEqual(caught.exception.report["groups"][0]["candidate_correct"], 0)


if __name__ == "__main__":
    unittest.main()
