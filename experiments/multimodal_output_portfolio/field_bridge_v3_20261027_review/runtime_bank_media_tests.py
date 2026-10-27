"""Synthetic complete-tree media audit and corruption/boundary contracts."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from feedback_evidence import ObserverArithmetic
from feedback_evidence_tests import SyntheticObserver
from runtime_audit_support import records
from runtime_bank_media_audit import audit_tree, open_banks, plan
from runtime_media_context import cases_for
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.feedback_bank import build_bank, batches
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.runtime_integration_tests import fixture
from experiments.multimodal_output_portfolio.v6.neural import NeuralPortfolio


class OfflineMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        torch.manual_seed(271045)
        cls.temp = tempfile.TemporaryDirectory(prefix="v3-bank-audit-synthetic-", dir="/tmp")
        cls.root = Path(cls.temp.name)
        cls.corpus, cls.protocol = fixture(1)
        cls.model = NeuralPortfolio(hidden=16).eval().requires_grad_(False)
        cls.observer = SyntheticObserver().eval().requires_grad_(False)
        cls.roles = {}
        for role in ("runtime_fit", "runtime_select"):
            directory = cls.root / role
            complete = build_bank(cls.model, cls.corpus, cls.observer, 17, "artificial", role,
                                  cls.protocol, directory, {"synthetic_only": True})
            cases, groups, panel = cases_for(cls.corpus, role, 17, cls.protocol)
            with np.load(directory / "bank.npz", allow_pickle=False) as saved:
                arrays = {name: saved[name].copy() for name in saved.files}
            rows = [row for row, _ in records(directory / "evidence.jsonl.gz")]
            cls.roles[role] = (directory, complete, cases, groups, arrays, rows, panel)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def audit(self, role="runtime_fit", rows=None, arrays=None):
        directory, _, cases, groups, original, evidence, _ = self.roles[role]
        observer = ObserverArithmetic({"reward": self.observer, "audit": self.observer})
        result = audit_tree(directory, evidence if rows is None else rows, original if arrays is None else arrays,
                            cases, groups, observer, role)
        return result, observer

    def test_all_85_nodes_actual_bytes_public_events_rewards_and_costs(self):
        for role, (_, complete, _, _, _, _, _) in self.roles.items():
            result, observer = self.audit(role)
            self.assertEqual(result["resources_reconstructed"], complete["resources"])
            self.assertEqual((result["trees"], result["terminal_rewards"], result["public_events"], result["feedback_packets"]),
                             (4, 340, 84, 80))
            self.assertEqual(result["logical_media_deliveries"], 340)
            self.assertEqual(observer.calls["audit"], 0)
            self.assertEqual(observer.logical_images, {"reward": 424, "audit": 0})

    def test_independent_batch_seed_mask_target_and_case_order(self):
        for role in self.roles:
            _, _, cases, groups, _, _, _ = self.roles[role]
            for index, (_, _, expected_cases, batch) in enumerate(batches(self.corpus, role, 17, self.protocol)):
                self.assertEqual(groups[index], list(expected_cases))
                for i, case in enumerate(expected_cases):
                    self.assertEqual(cases[case]["source_ids"], list(batch.source_ids[i]))
                    self.assertTrue(torch.equal(cases[case]["pixels"], batch.target.pixels[i]))
                    self.assertTrue(torch.equal(cases[case]["mask"], batch.observation.mask[i]))
                    self.assertTrue(torch.equal(cases[case]["labels"], batch.target.labels[i]))

    def test_stored_targets_and_events_cannot_replace_actual_media_truth(self):
        original = self.roles["runtime_fit"][4]
        for name, address in (("terminal_values", (0, 0)), ("events", (0, 0, 0))):
            arrays = {key: value.copy() for key, value in original.items()}
            arrays[name][address] += .001
            with self.assertRaisesRegex(ValueError, "Actual delivered"):
                self.audit(arrays=arrays)
        rows = copy.deepcopy(self.roles["runtime_fit"][5])
        rows[0]["reward_scores"][0]["utility"] += .1
        with self.assertRaisesRegex(ValueError, "Actual delivered reward"):
            self.audit(rows=rows)

    def test_feedback_values_side_and_chronology_are_checked(self):
        for change in (lambda packet: packet["public_feedback"].__setitem__(3, .5),
                       lambda packet: packet["public_feedback"].__setitem__(1, 0),
                       lambda packet: packet.update(after_readback_monotonic_ns=0),
                       lambda packet: packet.update(source_kind="human")):
            rows = copy.deepcopy(self.roles["runtime_fit"][5])
            change(rows[1]["feedback"][0])
            with self.assertRaisesRegex(ValueError, "feedback truth"):
                self.audit(rows=rows)

    def test_branch_source_and_delivery_scope_are_checked(self):
        changes = [lambda rows: rows[0].update(node=1),
                   lambda rows: rows[0]["source_ids"][0].reverse(),
                   lambda rows: rows[0].update(role="runtime_audit"),
                   lambda rows: rows[0]["media"][0].update(physical_record_reused=True),
                   lambda rows: rows[1]["media"][0].update(readback_monotonic_ns=rows[0]["committed_monotonic_ns"] - 1)]
        for change in changes:
            rows = copy.deepcopy(self.roles["runtime_fit"][5])
            change(rows)
            with self.assertRaises(ValueError):
                self.audit(rows=rows)

    def test_complete_grid_and_terminal_horizon_cannot_be_reduced(self):
        rows = self.roles["runtime_fit"][5]
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            self.audit(rows=rows[:-1])
        with self.assertRaisesRegex(ValueError, "Unexpected extra"):
            self.audit(rows=rows + [rows[0]])
        self.assertEqual(plan(84), [4, 4, 4])
        for invalid in (-1, 85, True):
            with self.assertRaises(ValueError):
                plan(invalid)

    def test_access_gate_precedes_frozen_inputs_and_any_raw_outcomes(self):
        source = Path(__file__).parent.parent / "field_bridge_v3_20261027"
        with self.assertRaisesRegex(ValueError, "All three completed"):
            open_banks(self.root / "never-created-run", "frozen", source, self.root / "missing-freeze.json")


if __name__ == "__main__":
    unittest.main()
