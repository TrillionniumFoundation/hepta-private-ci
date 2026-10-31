"""Synthetic actual-output causal traces, all stop depths and native joins."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from feedback_evidence import MediaIndex, ObserverArithmetic
from feedback_evidence_tests import SyntheticObserver
from native_session_audit import NativeReplay
from runtime_audit_support import ARMS, open_profile, records
from runtime_media_audit import expected_resources, join_native
from runtime_media_context import cases_for
from runtime_media_trace import SelectedTraceAudit
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.feedback_rollout import run_profile
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.native_stream import NativeStreamBridge
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027 import runtime_controller as production
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.runtime_integration_tests import fixture
from experiments.multimodal_output_portfolio.v6.data import SourceCorpus
from experiments.multimodal_output_portfolio.v6.neural import NeuralPortfolio


def controller(rep, actions, library_sha):
    heads = []
    for stage, action in enumerate(actions):
        coefficient = np.zeros((89, 5))
        coefficient[-1, action] = 1
        heads.append({"stage": stage, "coefficient": coefficient.tolist(), "normalizer": {
            "mean": [0.] * 88, "scale": [1.] * 88, "scope": "runtime_fit_only"}})
    fourier = production._fourier(16, 36) if rep == "current" else production._fourier(48, 20) if rep == "history" else None
    return {"schema": production.SCHEMA, "representation": rep, "feature_width": 88, "alpha": .01,
        "transform": {"name": "raw", "k": None, "normalizer": {"mean": [0.] * 16, "scale": [1.] * 16, "scope": "runtime_fit_only"}},
        "fourier": fourier, "heads": heads, "native_library_sha256": library_sha if "native" in rep else None,
        "authority": "DENY_ALL", "native_owner_integration": False}


class SelectedMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        torch.manual_seed(271046)
        cls.temp = tempfile.TemporaryDirectory(prefix="v3-selected-audit-synthetic-", dir="/tmp")
        cls.root = Path(cls.temp.name)
        source = Path(__file__).parent.parent / "field_bridge_v3_20261027"
        build = json.loads((source / "evidence" / "NATIVE_BUILD_RECEIPT.json").read_text())
        cls.library, cls.library_sha = build["binary"], build["binary_sha256"]
        original, cls.protocol = fixture(3)
        cls.corpus = SourceCorpus({"runtime_audit": original.splits["runtime_fit"]}, original.manifest)
        cls.model = NeuralPortfolio(hidden=16).eval().requires_grad_(False)
        cls.observer = SyntheticObserver().eval().requires_grad_(False)
        cls.policies = {"fixed": {"kind": "fixed", "node": 0, "actions": []},
            "current": controller("current", [1, 2, 0], cls.library_sha),
            "history": controller("history", [2, 3, 4], cls.library_sha),
            "native": controller("native", [1, 0, 0], cls.library_sha),
            "reset_native": controller("reset_native", [3, 4, 2], cls.library_sha)}
        with NativeStreamBridge(cls.library, cls.library_sha) as bridge:
            cls.complete = run_profile(cls.model, cls.corpus, {"reward": cls.observer, "audit": cls.observer},
                cls.policies, bridge, 17, "artificial", "runtime_audit", cls.protocol, cls.root / "selected", {"synthetic_only": True})
            cls.generation_ticks = bridge.tick_count
        cls.cases, cls.groups, _ = cases_for(cls.corpus, "runtime_audit", 17, cls.protocol)
        cls.events = [row for row, _ in records(cls.root / "selected" / "events.jsonl.gz")]
        cls.rows = [row for row, _ in records(cls.root / "selected" / "rows.jsonl.gz")]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def audit(self, events=None, rows=None):
        arithmetic = ObserverArithmetic({"reward": self.observer, "audit": self.observer})
        trace = SelectedTraceAudit(MediaIndex(self.root / "selected" / "media.h3m"), arithmetic, self.policies,
                                   self.cases, self.groups, 17, "artificial")
        for row in self.events if events is None else events:
            trace.process(row)
        return trace.finish(self.rows if rows is None else rows)

    def test_full_causal_actual_media_score_path_and_resource_coverage(self):
        summary = self.audit()
        self.assertEqual(expected_resources(summary), self.complete["resources"])
        self.assertEqual(summary["episodes"], 60)
        self.assertEqual(summary["logical_media_deliveries"], 168)
        self.assertEqual(summary["dual_observer_scores_rebuilt"], 120)
        self.assertEqual(summary["nonnative_head_actions_replayed"], 72)
        self.assertEqual(summary["native_tick_calls"], self.generation_ticks)
        self.assertEqual(self.generation_ticks, 120)
        for arm, depth in zip(ARMS, (0, 2, 3, 1, 3), strict=True):
            self.assertEqual(summary["per_arm"][arm][f"terminal_depth_{depth}"], 12)

    def test_mixed_stop_and_continuation_preserve_causal_active_subset(self):
        first = next(row for row in self.events if row["kind"] == "initial_delivery" and row["arm"] == "current")
        public = np.asarray(first["public_events"])
        coordinate = int(np.ptp(public, axis=0).argmax())
        self.assertGreater(np.ptp(public[:, coordinate]), 0)
        threshold = np.nextafter(public[:, coordinate].max(), -np.inf)
        policy = controller("current", [1, 0, 0], self.library_sha)
        coefficient = np.zeros((89, 5))
        coefficient[-1, 2:] = -10
        coefficient[coordinate, 0], coefficient[-1, 1] = 1., threshold
        policy["heads"][0]["coefficient"] = coefficient.tolist()
        protocol = copy.deepcopy(self.protocol)
        protocol["runtime"]["conditions"] = ["heavy_noise"]
        directory = self.root / "mixed-selected"
        complete = run_profile(self.model, self.corpus, {"reward": self.observer, "audit": self.observer},
            {"current": policy}, None, 17, "artificial", "runtime_audit", protocol, directory, {"synthetic_only": True})
        cases, groups, _ = cases_for(self.corpus, "runtime_audit", 17, protocol)
        trace = SelectedTraceAudit(MediaIndex(directory / "media.h3m"), ObserverArithmetic({"reward": self.observer, "audit": self.observer}),
                                   {"current": policy}, cases, groups, 17, "artificial")
        for row, _ in records(directory / "events.jsonl.gz"):
            trace.process(row)
        summary = trace.finish(row for row, _ in records(directory / "rows.jsonl.gz"))
        self.assertEqual(expected_resources(summary), complete["resources"])
        self.assertGreater(summary["per_arm"]["current"]["terminal_depth_0"], 0)
        self.assertGreater(summary["per_arm"]["current"]["terminal_depth_1"], 0)

    def test_media_derived_native_coverage_matches_original_kernel_replay(self):
        summary = self.audit()
        with NativeStreamBridge(self.library, self.library_sha) as bridge:
            replay = NativeReplay(bridge, self.policies, self.cases)
            for row in self.events:
                replay.process(row)
            native = replay.finish()
        self.assertEqual(summary["decision_coverage_sha256"], native["decision_coverage_sha256"])
        self.assertEqual(native["verification_native_ticks"], 120)
        inputs = {key: "a" * 64 for key in ("parent_complete_sha256", "selected_complete_sha256", "events_sha256",
                                          "readouts_sha256", "fit_complete_sha256")}
        receipt = {"passed": True, "profile": "artificial", "freeze_sha256": "f" * 64,
            "generator_forward_calls": 0, "observer_forward_calls": 0, "discrepancies": 0,
            "seeds": {"17": {**native, "inputs": inputs}}}
        joined = {**summary, "seed": 17, "inputs": {**inputs, "rows_sha256": "b" * 64, "media_sha256": "c" * 64}}
        join_native(receipt, "artificial", "f" * 64, [joined])
        receipt["seeds"]["17"]["inputs"]["events_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "coverage differs"):
            join_native(receipt, "artificial", "f" * 64, [joined])

    def test_public_history_and_native_record_cannot_add_hidden_evidence(self):
        changed = copy.deepcopy(self.events)
        row = next(r for r in changed if r["kind"] == "selected_actions_before_execution" and r["arm"] == "current")
        row["public_history"][0][0][0] += .001
        with self.assertRaisesRegex(ValueError, "history includes"):
            self.audit(events=changed)
        changed = copy.deepcopy(self.events)
        row = next(r for r in changed if r["kind"] == "selected_actions_before_execution" and r["arm"] == "native")
        row["selection"]["native_records"][0]["raw_history"][0][0] += .001
        with self.assertRaisesRegex(ValueError, "Native record differs"):
            self.audit(events=changed)

    def test_premature_feedback_and_uncommitted_revisions_rejected(self):
        for mutate in (lambda row: row["feedback"][0].update(after_readback_monotonic_ns=0),
                       lambda row: row.update(decision_sha256="0" * 64),
                       lambda row: row.update(future_or_unchosen_branches_executed=1)):
            changed = copy.deepcopy(self.events)
            row = next(r for r in changed if r["kind"] == "selected_revision_delivery" and r["depth"] == 1)
            mutate(row)
            with self.assertRaises(ValueError):
                self.audit(events=changed)

    def test_frozen_head_action_private_access_and_feature_hash_rejected(self):
        for mutate in (lambda row: row["selection"]["action_indices"].__setitem__(0, 4),
                       lambda row: row["selection"].update(feature_matrix_sha256="0" * 64),
                       lambda row: row["selection"].update(target_accesses=1)):
            changed = copy.deepcopy(self.events)
            row = next(r for r in changed if r["kind"] == "selected_actions_before_execution" and r["arm"] == "current")
            mutate(row)
            with self.assertRaises(ValueError):
                self.audit(events=changed)

    def test_final_media_decision_scores_identity_and_chronology_rejected(self):
        changes = [lambda row: row["scores"]["audit"].update(utility=.123),
                   lambda row: row["decisions"].__setitem__(0, "0" * 64),
                   lambda row: row["media"][0].update(record_sha256="0" * 64),
                   lambda row: row.update(pair_index=999), lambda row: row.update(committed_monotonic_ns=0)]
        for mutate in changes:
            rows = copy.deepcopy(self.rows)
            mutate(rows[0])
            with self.assertRaisesRegex(ValueError, "Final row differs"):
                self.audit(rows=rows)

    def test_incomplete_extra_and_wrong_source_order_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete selected episode"):
            self.audit(events=self.events[:-1])
        with self.assertRaisesRegex(ValueError, "Incomplete selected final"):
            self.audit(rows=self.rows[:-1])
        with self.assertRaisesRegex(ValueError, "omit, duplicate"):
            self.audit(rows=self.rows + [self.rows[0]])
        changed = copy.deepcopy(self.events)
        changed[0]["case_ids"].reverse()
        with self.assertRaisesRegex(ValueError, "canonical source"):
            self.audit(events=changed)

    def test_selected_outcome_access_gate_precedes_missing_freeze(self):
        source = Path(__file__).parent.parent / "field_bridge_v3_20261027"
        with self.assertRaisesRegex(ValueError, "All three successful"):
            open_profile(self.root / "never-created-run", "frozen", source, self.root / "never-created-freeze.json")


if __name__ == "__main__":
    unittest.main()
