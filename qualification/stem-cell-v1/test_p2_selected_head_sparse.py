"""Actual CPU sparse-Head dispatch and Torch-free independent parity fault tests.

Fixture Stem is random and mock, never the pinned Granite97 pretrained model.
All source/output policy remains research DENY_ALL and no future-time utility.
"""
from __future__ import annotations

import copy
import inspect
import unittest
from unittest.mock import patch

import torch

import p1_real_granite_cohort as p1
import p1_real_granite_review as original_source
import p2_real_cell_split as p2
import p2_real_cell_split_review as original_math
import p2_real_cell_split_sparse_probe as sparse
import p2_real_cell_split_sparse_review as audit
from test_p1_real_granite_cohort import FakePhysicalStem, setup_fixture


class PhysicallySelectedHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel, cls.train, cls.blind, cls.owner, cls.source_sha = setup_fixture()
        torch.manual_seed(7359)
        backend = FakePhysicalStem()
        with patch.object(p1, "PANEL_SHA", cls.source_sha), \
             patch.object(original_source, "PANEL_SHA", cls.source_sha):
            cls.parent = p2.execute(cls.train, cls.blind, backend, seed=7347)
            cls.legacy_review = original_math.review(
                cls.panel, cls.train, cls.blind, cls.owner, cls.parent)
        cls.physical = sparse.run(cls.parent)
        with patch.object(p1, "PANEL_SHA", cls.source_sha), \
             patch.object(original_source, "PANEL_SHA", cls.source_sha):
            cls.independent = audit.audit(cls.parent, cls.physical, cls.legacy_review,
                                          cls.panel, cls.train, cls.blind, cls.owner)

    def review_sparse(self, physical=None, prior=None, parent=None, panel=None, owner=None):
        with patch.object(p1, "PANEL_SHA", self.source_sha), \
             patch.object(original_source, "PANEL_SHA", self.source_sha):
            return audit.audit(self.parent if parent is None else parent,
                               self.physical if physical is None else physical,
                               self.legacy_review if prior is None else prior,
                               self.panel if panel is None else panel,
                               self.train, self.blind,
                               self.owner if owner is None else owner)

    def test_actual_selected_only_forward_matches_original_trained_logits(self):
        self.assertEqual(self.independent["outcome"], "NUMERIC_SELECTED_HEAD_PARITY_ONLY")
        self.assertEqual(set(self.independent["arms"]), set(sparse.ARMS))
        for name in sparse.ARMS:
            report = self.physical["arms"][name]
            self.assertEqual(report["dense_two_head_forward_rows"], 192)
            self.assertEqual(report["sparse_selected_head_forward_rows"], 96)
            self.assertEqual(sum(report["group_selected_row_counts"]), 96)
            self.assertEqual(len(report["selected_case_head_indices"]), 96)
            self.assertLessEqual(report["max_abs_dense_and_original_logit_delta"],
                                 p2.TOLERANCE)
            self.assertFalse(self.independent["arms"][name]["actual_cpu_speedup_certified"])
            self.assertFalse(self.independent["eligible_model_selection"])

    def test_instrumented_physical_dispatch_never_executes_unselected_head(self):
        x, threshold = sparse.materialize(self.parent)
        for name in sparse.ARMS:
            arm = self.parent["compared_arms"][name]
            weights = sparse.parameters_from_exact_fp32(arm)
            chosen = sparse.selected_heads(x, arm, threshold)
            calls = []
            real = sparse.single_head

            def observed(source, tensors, head):
                calls.append((head, len(source)))
                return real(source, tensors, head)

            with self.subTest(name=name), patch.object(sparse, "single_head", side_effect=observed):
                logits, groups = sparse.sparse_selected_forward(x, chosen, weights)
                self.assertEqual(sum(n for _,n in calls), 96)
                self.assertEqual(sorted(calls), sorted((i,n) for i,n in enumerate(groups) if n))
                self.assertEqual(logits.shape, (96,2))

    def test_original_label_blinding_and_no_new_encoder_forward(self):
        self.assertFalse(self.physical["source_original_labels_seen_by_probe"])
        self.assertEqual(self.physical["pretrained_encoder_forward_calls_in_probe"], 0)
        self.assertFalse(self.physical["pretrained_encoder_loaded_in_probe"])
        self.assertFalse(self.independent["physical_cell_split_authorized"])
        self.assertFalse(self.independent["codex_effect_authorized"])
        self.assertEqual(self.independent["production_admission"], "BLOCKED")
        self.assertFalse(self.independent["source_execution_counters_independently_attested"])

    def test_sparse_timing_is_measured_but_no_speedup_is_promised(self):
        for arm in sparse.ARMS:
            data = self.physical["arms"][arm]
            self.assertEqual(len(data["real_cpu_dense_process_ns"]), sparse.REPEATS)
            self.assertEqual(len(data["real_cpu_sparse_process_ns"]), sparse.REPEATS)
            self.assertTrue(all(type(v) is int and v>0
                                for v in data["real_cpu_sparse_process_ns"]))
            self.assertFalse(self.independent["arms"][arm]["target_host_cpu_rss_energy_certified"])

    def test_forged_probe_logits_or_route_mask_refused(self):
        for edit in (
            lambda p: p["arms"]["fixed_two_cell"]["actual_sparse_logits"][0].__setitem__(0, 900.),
            lambda p: p["arms"]["adaptive_train_only"]["selected_case_head_indices"].__setitem__(0, 2),
            lambda p: p["arms"]["fixed_two_cell"]["group_selected_row_counts"].__setitem__(0, -1),
            lambda p: p["arms"]["fixed_two_cell"].__setitem__("sparse_selected_head_forward_rows",192),
            lambda p: p["arms"]["fixed_two_cell"].__setitem__("source_weights_sha256","f"*64),
            lambda p: p["arms"]["fixed_two_cell"].__setitem__("sparse_head_dispatch_groups",0),
        ):
            with self.subTest(edit=str(edit)):
                bad = copy.deepcopy(self.physical)
                edit(bad)
                with self.assertRaises((ValueError, TypeError)):
                    self.review_sparse(physical=bad)

    def test_false_grants_and_lifecycle_cost_claims_are_refused(self):
        for field,fake in (
            ("full_task_cpu_cost_matched",True),
            ("source_original_labels_seen_by_probe",True),
            ("independent_ndu_selection_authorized",True),
            ("pretrained_model_origin_independently_authenticated",True),
            ("production_admission","PROMOTED"),
            ("authority_posture","AUTHORIZED"),
            ("pretrained_encoder_forward_calls_in_probe",224),
        ):
            with self.subTest(field=field):
                bad=copy.deepcopy(self.physical)
                bad[field]=fake
                with self.assertRaises(ValueError):
                    self.review_sparse(physical=bad)

    def test_original_report_and_independent_human_review_cannot_be_replaced(self):
        bad = copy.deepcopy(self.parent)
        bad["compared_arms"]["fixed_two_cell"]["logits"][0][0] += 0.1
        bad["report_sha256"] = original_math.digest(
            {k:v for k,v in bad.items() if k!="report_sha256"})
        with self.assertRaises(ValueError):
            sparse.run(bad)
        bad = copy.deepcopy(self.legacy_review)
        bad["eligible_model_selection"] = True
        with self.assertRaises(ValueError):
            self.review_sparse(prior=bad)

    def test_original_tensor_bytes_and_hidden_extra_controls_refused(self):
        bad=copy.deepcopy(self.parent)
        hx=bad["compared_arms"]["fixed_two_cell"]["weights"]["down"]["bytes_le_hex"]
        bad["compared_arms"]["fixed_two_cell"]["weights"]["down"]["bytes_le_hex"] = ("ff" if hx[:2]!="ff" else "00")+hx[2:]
        bad["report_sha256"] = original_math.digest(
            {k:v for k,v in bad.items() if k!="report_sha256"})
        with self.assertRaises(ValueError):
            sparse.run(bad)
        bad=copy.deepcopy(self.physical)
        bad["grant"]=True
        with self.assertRaises(ValueError):
            self.review_sparse(physical=bad)

    def test_rehashed_plausible_original_human_score_cannot_stand_in_for_real_owner(self):
        prior = copy.deepcopy(self.legacy_review)
        score = prior["results"]["fixed_two_cell"]["test"]
        score["accuracy"] = 0.0 if score["accuracy"] > 0.5 else 1.0
        # Source panel and authority fields remain identical; the old
        # shallow prior-record acceptance would have admitted this.
        with self.assertRaisesRegex(ValueError, "human-label score"):
            self.review_sparse(prior=prior)

    def test_relabelled_owner_and_resealed_source_cannot_launder_human_score(self):
        owner = copy.deepcopy(self.owner)
        owner["rows"][0]["label"] = 1 - owner["rows"][0]["label"]
        # Neither an internally consistent SHA nor a post-score claim
        # permits altering the registered owner labels.
        if "seal_id" in owner:
            owner["seal_id"] = original_math.digest({k:v for k,v in owner.items()
                                                      if k != "seal_id"})
        with self.assertRaises(ValueError):
            self.review_sparse(owner=owner)

    def test_reviewer_is_independent_of_torch_and_sparse_producer(self):
        text=inspect.getsource(audit)
        self.assertNotIn("import torch",text)
        self.assertNotIn("import p2_real_cell_split_sparse_probe",text)
        self.assertNotIn("torch.",text)


if __name__ == "__main__":
    unittest.main()
