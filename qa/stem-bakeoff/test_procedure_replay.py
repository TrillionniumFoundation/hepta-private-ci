"""Mechanism tests use tiny fixtures; only the separate real run qualifies Granite."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from cell_evolution_snapshot import WithdrawalViewV1
from cell_head_training import HeadCohortV1, HeadTrainingConfigV1, save_head_artifact, train_cell_head
from feature_bundle import FeatureIdentityV1
from procedure_replay_contracts import CONTRACTS, canonical, execute, sha
from procedure_replay_data import make_cases, validate_partitions
from procedure_replay_evaluation import evaluate_policy
from procedure_replay_learning import calibrated_probabilities, feature_baselines, pooled_bundle
from procedure_replay_observer import observe
from procedure_replay_owner import ReplayHeadOwner
from procedure_replay_probe import ReplayBM25, attempt, freeze, require_plan, write_json


class ProcedureReplayTests(unittest.TestCase):
    def test_actual_files_have_one_observed_success_and_charge_wrong_programs(self):
        cases = make_cases()
        for contract in CONTRACTS:
            case = next(case for case in cases if case.goal == contract["id"])
            rows = [attempt(case, choice) for choice in range(4)]
            self.assertEqual(sum(row["observation"]["success"] for row in rows), 1)
            self.assertEqual(sum(row["execution"]["execution_calls"] for row in rows), 4)
            self.assertTrue(all(row["observation"]["output_exists"] for row in rows))
            self.assertEqual(next(row["execution"]["contract"] for row in rows
                                  if row["observation"]["success"]), contract["id"])

    def test_observer_reopens_files_rejects_tamper_and_input_change(self):
        case = next(case for case in make_cases() if case.goal == "latest_by_id")
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "data.json", Path(directory) / "output.json"
            source.write_bytes(case.input_bytes)
            execution = execute(0, source, output)
            self.assertIsNone(execution["execution_error"])
            self.assertTrue(observe(case.goal, source, output, case.query.input_sha256)["success"])
            output.write_text("[]\n")
            self.assertFalse(observe(case.goal, source, output, case.query.input_sha256)["success"])
            output.unlink()
            execute(0, source, output)
            source.write_bytes(case.input_bytes + b" ")
            checked = observe(case.goal, source, output, case.query.input_sha256)
            self.assertFalse(checked["input_unchanged"])
            self.assertFalse(checked["success"])

    def test_real_execution_failure_is_charged_and_has_no_success_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "data.json", Path(directory) / "output.json"
            source.write_bytes(b'{"records":[],"threshold":0}\n')
            result = execute(0, source, output)
            self.assertEqual(result["execution_calls"], 1)
            self.assertIsNotNone(result["execution_error"])
            self.assertFalse(observe("latest_by_id", source, output, sha(source.read_bytes()))["success"])

    def test_templates_and_input_families_are_disjoint_and_crossed_with_all_goals(self):
        cases = make_cases()
        self.assertEqual({key: value["queries"] for key, value in validate_partitions(cases).items()},
                         {"train": 64, "calibration": 32, "development": 32, "heldout": 64})
        for family in {case.query.input_family for case in cases}:
            group = [case for case in cases if case.query.input_family == family]
            self.assertEqual({case.goal for case in group}, {contract["id"] for contract in CONTRACTS})
            self.assertEqual(len({case.input_bytes for case in group}), 1)
        train = next(case for case in cases if case.query.split == "train")
        held = next(case for case in cases if case.query.split == "heldout")
        changed = replace(held, query=replace(held.query, input_family=train.query.input_family))
        with self.assertRaises(ValueError):
            validate_partitions(tuple(changed if case == held else case for case in cases))

    def test_gold_and_output_fields_are_not_available_to_retrieval(self):
        cases = make_cases()
        train = [case for case in cases if case.query.split == "train"]
        labels = {case.query.query_id: next(row["choice"] for row in
                  [attempt(case, i) for i in range(4)] if row["observation"]["success"])
                  for case in train[:8]}
        index = ReplayBM25([case.query for case in train[:8]], labels)
        query = next(case for case in cases if case.query.split == "heldout")
        changed_gold = replace(query, goal="not-the-original-goal")
        self.assertEqual(index.scores(query.query)[0], index.scores(changed_gold.query)[0])
        self.assertNotIn("goal", asdict(query.query))
        index.db.close()
        with self.assertRaises(ValueError):
            ReplayBM25([query.query], {query.query.query_id: 0})

    def test_one_execution_per_query_and_abstention_executes_nothing(self):
        cases = tuple(next(case for case in make_cases() if case.query.split == split)
                      for split in ("development", "heldout"))
        choices = {cases[0].query.query_id: 0, cases[1].query.query_id: None}
        with patch("procedure_replay_probe.execute", wraps=execute) as observed:
            result = evaluate_policy(cases, choices, arm="unit", policy="bounded")
        self.assertEqual(observed.call_count, 1)
        self.assertEqual(result["summary"]["heldout"]["execution_calls"], 0)
        self.assertEqual(result["summary"]["development"]["execution_calls"], 1)

    def test_train_and_calibration_only_baseline_inputs(self):
        features = torch.eye(4).repeat(2, 1)
        results = feature_baselines(features, [0, 1, 2, 3], [0, 1, 2, 3])
        for scores, _ in results.values():
            probabilities, _ = calibrated_probabilities(scores, [0, 1, 2, 3], [0, 1, 2, 3])
            self.assertEqual(probabilities.argmax(dim=1).tolist(), [0, 1, 2, 3] * 2)

    def test_frozen_plan_rejects_changed_source_pin_and_input(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence"
            freeze(target)
            plan = require_plan(target)
            with self.assertRaises(ValueError):
                require_plan(target, "0" * 64)
            input_path = next((target / "inputs").iterdir())
            original = input_path.read_bytes()
            input_path.write_bytes(original + b" ")
            with self.assertRaises(ValueError):
                require_plan(target)
            input_path.write_bytes(original)
            plan["source_code_sha256"]["procedure_replay_probe.py"] = "0" * 64
            (target / "plan.json").write_bytes(canonical(plan))
            with self.assertRaises(ValueError):
                require_plan(target)

    def test_actual_artifact_reload_and_before_after_withdrawal(self):
        identity = FeatureIdentityV1("1" * 64, "2" * 40, "3" * 64, scope_id="unit-fixture")
        bundles = {role: pooled_bundle(torch.eye(4), [sha(f"{role}-{i}".encode()) for i in range(4)], identity)
                   for role in ("train", "calibration", "development")}
        cohorts = {role: HeadCohortV1(bundle, (0, 1, 2, 3), tuple(f"{role}-{i}" for i in range(4)))
                   for role, bundle in bundles.items()}
        trained = train_cell_head(cohorts["train"], cohorts["calibration"],
            {"development": cohorts["development"]}, config=HeadTrainingConfigV1(task_count=4, mode="linear", steps=2))
        source = bundles["train"].source_record_digests[0]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "head"
            saved = save_head_artifact(trained, target)
            write_json(target / "replay_owner.json", {"head_manifest_sha256": saved["manifest_sha256"],
                "feature_identity": asdict(identity), "learned_source_digests": [source],
                "authority": "DENY_ALL", "mode": "SHADOW_ONLY"})
            pin = sha((target / "replay_owner.json").read_bytes())
            view = [WithdrawalViewV1(identity.scope_id)]
            owner = ReplayHeadOwner(target, pin, identity, lambda: view[0])
            actual = owner.predict(bundles["development"])
            self.assertTrue(torch.equal(actual["task_probabilities"], trained.predict_task(bundles["development"])["task_probabilities"]))
            view[0] = WithdrawalViewV1(identity.scope_id, 1, (source,))
            with self.assertRaises(ValueError):
                owner.predict(bundles["development"])
            self.assertEqual(owner.forward_calls, 1)
            with self.assertRaises(ValueError):
                ReplayHeadOwner(target, pin, identity, lambda: view[0])
            view[0] = WithdrawalViewV1(identity.scope_id)
            with self.assertRaises(ValueError):
                owner.predict(bundles["development"])
            self.assertEqual(owner.forward_calls, 1)
            owner._handle.remove()
            # A distinct controlled host scenario tests current query-source
            # withdrawal, including a change after the real Head did work.
            owner = ReplayHeadOwner(target, pin, identity, lambda: view[0])
            query_source = bundles["development"].source_record_digests[0]
            def revoke_during_forward(module, arguments, output):
                view[0] = WithdrawalViewV1(identity.scope_id, 1, (query_source,))
            handle = owner.model._head.register_forward_hook(revoke_during_forward)
            with self.assertRaises(ValueError):
                owner.predict(bundles["development"])
            self.assertEqual(owner.forward_calls, 1)
            handle.remove()
            owner._handle.remove()
            owner = ReplayHeadOwner(target, pin, identity, lambda: view[0])
            with self.assertRaises(ValueError):
                owner.predict(bundles["development"])
            self.assertEqual(owner.forward_calls, 0)
            view[0] = WithdrawalViewV1(identity.scope_id)
            with self.assertRaises(ValueError):
                owner.predict(bundles["development"])
            self.assertEqual(owner.forward_calls, 0)
            owner._handle.remove()
            with self.assertRaises(ValueError):
                ReplayHeadOwner(target, "0" * 64, identity, lambda: view[0])


if __name__ == "__main__":
    torch.set_num_threads(2)
    unittest.main()
