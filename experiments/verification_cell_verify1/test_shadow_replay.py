"""Replay real fixture ledgers; mutate evidence without executing any model."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .model_policy import Pilot
from .model_protocol import Journal, cases, frozen_plan
from .shadow_replay import INPUTS, load, records, run, validate
from .test_model_policy import UnitOnlyScore, dependencies


class ShadowReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        cls.directory = cls.root / "original"
        plan = frozen_plan()
        plan["cases"] = {split: [c for c in cases(split) if c["source_group"].endswith("/0")]
                         for split in ("train", "calibration", "confirmation")}
        plan["planned_trajectories"] = [{"case_id": c["goal"]["task_id"], "arm": arm}
                                       for c in plan["cases"]["confirmation"]
                                       for arm in ("constant_prior", "fixed_check")]
        journal = Journal(cls.directory, plan)
        pilot = Pilot(journal, dependencies(), UnitOnlyScore(), plan)
        pilot.prior = 0.5
        for split in ("train", "calibration"):
            for case in plan["cases"][split]:
                context = {"split": split, "case_id": case["goal"]["task_id"],
                           "attempt": split + "/uninterrupted_panel"}
                database = pilot.database(case, context["attempt"])
                for tick in (1, 2, 3):
                    pilot.host("host_effect", {**context, "tick": tick}, pilot.runtime.execute_step,
                               database, case["goal"], case["fault"], tick)
                label, operation = pilot.host("independent_outcome_label", context,
                                              pilot.runtime.outcome, database, case["goal"])
                journal.append("panel_labels.jsonl", {**context, "source_group": case["source_group"],
                                                      "label": label, "label_operation_id": operation,
                                                      "all_three_effect_steps_completed": True})
        for case in plan["cases"]["confirmation"]:
            for arm in ("constant_prior", "fixed_check"):
                pilot.trajectory(case, arm)
        cls.original = load(cls.directory)

    def data(self):
        return copy.deepcopy(self.original)

    def test_early_and_post_horizon_interruptions_have_different_truth(self):
        _, groups = records(self.original)
        constant_views, constant_labels = groups["confirmation"]["constant_prior"]
        fixed_views, fixed_labels = groups["confirmation"]["fixed_check"]
        self.assertEqual({s.observed_step for s in constant_views + fixed_views}, {0, 2})
        self.assertTrue(all(s.features == () for s in constant_views if s.observed_step == 0))
        self.assertTrue(any(x.disposition == "interrupted" and x.error is None for x in constant_labels))
        self.assertTrue(any(x.disposition == "interrupted" and x.error is True for x in fixed_labels))
        self.assertTrue(all(x.error is not None for x in fixed_labels))

    def test_fault_metadata_cannot_change_features_or_labels(self):
        data = self.data()
        for cases_in_split in data["plan"]["cases"].values():
            for case in cases_in_split:
                case["fault"] = "untrusted diagnostic text"
        for row in data["rows"]:
            row["fault"] = "different diagnostic text"
        _, before = records(self.original)
        _, after = records(validate(data))
        for split in before:
            for arm in before[split]:
                self.assertEqual([(x.observed_step, x.features) for x in before[split][arm][0]],
                                 [(x.observed_step, x.features) for x in after[split][arm][0]])
                self.assertEqual([x.error for x in before[split][arm][1]], [x.error for x in after[split][arm][1]])

    def test_ledger_inventory_and_ack_tampering_rejected(self):
        for mutation in ("duplicate_operation", "missing_start", "missing_row", "invalid_ack"):
            data = self.data()
            if mutation == "duplicate_operation":
                data["operations"].append(data["operations"][0])
            elif mutation == "missing_start":
                data["attempts"].pop()
            elif mutation == "missing_row":
                data["rows"].pop()
            else:
                next(o for o in data["operations"] if o["kind"] == "host_effect")["result"]["ack"] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate(data)

    def test_terminal_label_must_follow_all_observed_effects(self):
        data = self.data()
        position = next(i for i, o in enumerate(data["operations"])
                        if o["kind"] == "independent_outcome_label" and o["context"]["split"] == "train")
        label = data["operations"].pop(position)
        target = next(i for i, o in enumerate(data["operations"])
                      if o["kind"] == "host_effect" and o["context"]["case_id"] == label["context"]["case_id"])
        data["operations"].insert(target, label)
        with self.assertRaisesRegex(ValueError, "label precedes"):
            validate(data)

    def test_acceptance_cannot_survive_missing_mandatory_check(self):
        data = self.data()
        operation = next(o for o in data["operations"] if o["kind"] == "mandatory_host_check" and o["result"]["accepted"])
        for key in ("operations", "attempts"):
            data[key] = [o for o in data[key] if o["operation_id"] != operation["operation_id"]]
        with self.assertRaises(ValueError):
            validate(data)

    def test_failed_label_collection_keeps_acceptance_and_unknown_truth(self):
        data = self.data()
        row = next(r for r in data["rows"] if r["accepted"])
        case, arm = row["case_id"], row["arm"]
        label = next(o for o in data["operations"] if o["kind"] == "independent_outcome_label"
                     and o["context"].get("case_id") == case and o["context"].get("arm") == arm)
        for key in ("operations", "attempts"):
            data[key] = [o for o in data[key] if o["operation_id"] != label["operation_id"]]
        row.update(status="failed", outcome_error=None)
        next(a for a in data["trajectory_attempts"] if a["case_id"] == case
             and a["arm"] == arm and a["status"] == "completed")["status"] = "failed"
        _, groups = records(validate(data))
        kept = next(x for x in groups["confirmation"][arm][1] if case in x.trajectory_id)
        self.assertEqual((kept.disposition, kept.error, kept.evidence_sha256, kept.missing_reason),
                         ("accept", None, None, "terminal_label_unavailable"))

    def test_cli_output_is_create_only_and_originals_unchanged(self):
        before = {name: hashlib.sha256((self.directory / name).read_bytes()).hexdigest() for name in INPUTS}
        output = self.root / "replay"
        result = run(self.directory, output)
        self.assertEqual((result["status"], result["training_trajectories"]), ("RETAINED_REPLAY_COMPLETED", 6))
        calibration = result["reports"]["calibration"]["panel"]
        policy_fields = ("acceptance_coverage", "accepted_error_missing_label_bounds",
                         "all_trajectory_false_accept_missing_label_bounds")
        self.assertEqual({field: calibration[field] for field in policy_fields},
                         {field: None for field in policy_fields})
        self.assertEqual(calibration["policy_metric_reason"], "no_policy_acceptance_decision")
        confirmation = result["reports"]["confirmation"]["fixed_check"]
        self.assertEqual(confirmation["acceptance_coverage"], 2 / 6)
        self.assertEqual(confirmation["accepted_error_missing_label_bounds"], [0.0, 0.0])
        self.assertEqual(before, {name: hashlib.sha256((self.directory / name).read_bytes()).hexdigest() for name in INPUTS})
        freeze = json.loads((output / "freeze.json").read_text())
        self.assertEqual(freeze["input_sha256"], before)
        with self.assertRaises(FileExistsError):
            run(self.directory, output)
        with self.assertRaises(ValueError):
            run(self.directory, self.directory / "forbidden-output")


if __name__ == "__main__":
    unittest.main()
