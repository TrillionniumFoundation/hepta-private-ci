"""Real reference executions and cold-byte checks; no scientific authority."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ._causal_checks import ACEValidationError, _sha
from . import flr_reference as reference
from .flr_reference import ReferenceStore, run_campaign


class FLRReferenceTests(unittest.TestCase):
    def test_multigeneration_cold_readback_and_frozen_controls(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            result = run_campaign(
                output, "a" * 40, "b" * 40, generations=2, seed=17, attempts=2
            )
            plan, records = result["plan"], result["records"]
            store = ReferenceStore(output)
            self.assertEqual(json.loads((output / "records.json").read_text()), records)
            self.assertEqual(records["seal"]["rounds_digest"], _sha(records["rounds"]))
            states = {
                arm: (plan["initial_model"], plan["initial_learner"]) for arm in "FLR"
            }
            changed_learners = []
            for row in records["rounds"]:
                self.assertEqual(
                    (row["model_before"], row["learner_before"]), states[row["arm"]]
                )
                decision = row["decision"]
                selection = store.read("selection", decision["evidence_ref"])
                use = store.read("C", row["use_ref"])
                self.assertLess(selection["sequence"], use["sequence"])
                self.assertLess(use["sequence"], records["seal"]["sequence"])
                self.assertEqual(
                    (use["model"], use["learner"]),
                    (decision["model_after"], decision["learner_after"]),
                )
                states[row["arm"]] = decision["model_after"], decision["learner_after"]
                store.cold_load(*states[row["arm"]])
                if row["arm"] == "F":
                    self.assertEqual(row["attempts"], [])
                    self.assertEqual(
                        states["F"], (plan["initial_model"], plan["initial_learner"])
                    )
                if row["arm"] == "L":
                    self.assertEqual(states["L"][1], plan["initial_learner"])
                if row["arm"] == "R":
                    self.assertEqual(
                        len(row["learner_search"]), plan["budget"]["learner_trials"]
                    )
                    for trial in row["learner_search"]:
                        self.assertEqual(trial["status"], "SUCCEEDED")
                        store.cold_load(trial["result_model"], row["learner_before"])
                    changed_learners.extend(
                        a["candidate_learner"] != row["learner_before"]
                        for a in row["attempts"]
                    )
                else:
                    self.assertEqual(row["learner_search"], [])
                for attempt in row["attempts"]:
                    evaluation = store.read("B", attempt["evaluation_ref"])
                    self.assertEqual(
                        (evaluation["model"], evaluation["learner"]),
                        (attempt["candidate_model"], attempt["candidate_learner"]),
                    )
                    self.assertLess(evaluation["sequence"], selection["sequence"])
            self.assertTrue(all(changed_learners))
            self.assertNotEqual(states["R"][1], plan["initial_learner"])
            self.assertTrue(
                any(
                    row["arm"] == "R"
                    and row["generation"] > 0
                    and row["learner_before"] != plan["initial_learner"]
                    for row in records["rounds"]
                )
            )
            for arm, reference in records["audits"].items():
                final = store.read("D", reference)
                self.assertGreater(final["sequence"], records["seal"]["sequence"])
                self.assertEqual((final["model"], final["learner"]), states[arm])
            self.assertEqual(result["execution"]["independent_real_sources"], 0)
            self.assertFalse(result["execution"]["rsi_qualified"])
            self.assertFalse(result["report"]["authority_granted"])
            with self.assertRaises(FileExistsError):
                run_campaign(output, "a" * 40, "b" * 40, generations=2)

    def test_corrupt_retained_artifacts_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            result = run_campaign(output, "a" * 40, "b" * 40, generations=2, attempts=1)
            plan, store = result["plan"], ReferenceStore(output)
            (output / "models" / f"{plan['initial_model']}.json").write_text(
                "[9,9,9,9,9,9,9,9,9]"
            )
            with self.assertRaisesRegex(ACEValidationError, "FLR_COLD_READBACK"):
                store.cold_load(plan["initial_model"], plan["initial_learner"])
            evidence = next((output / "evidence").glob("*.json"))
            record = json.loads(evidence.read_text())
            original_kind = record["kind"]
            record["sequence"] += 100
            evidence.write_text(json.dumps(record))
            with self.assertRaisesRegex(ACEValidationError, "FLR_EVIDENCE_READBACK"):
                store.read(original_kind, evidence.stem)

    def test_d_reader_requires_a_matching_search_seal(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            result = run_campaign(output, "a" * 40, "b" * 40, generations=2, attempts=1)
            records = result["records"]
            records["seal"] = None
            (output / "records.json").write_text(json.dumps(records))
            with self.assertRaisesRegex(
                ACEValidationError, "FLR_D_REQUIRES_SEARCH_SEAL"
            ):
                ReferenceStore(output).samples(result["plan"], "external-D")

    def test_failed_dispatch_is_registered_and_retained_without_a_seal(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            with patch(
                "scripts.ndu_real_runtime.flr_reference.train",
                side_effect=RuntimeError("training failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "training failed"):
                    run_campaign(output, "a" * 40, "b" * 40, generations=2, attempts=1)
            records = json.loads((output / "records.json").read_text())
            self.assertIsNone(records["seal"])
            self.assertEqual(records["audits"], {arm: None for arm in "FLR"})
            attempt = records["rounds"][-1]["attempts"][0]
            self.assertEqual(
                (attempt["status"], attempt["b_queries"], attempt["evaluation_ref"]),
                ("FAILED", 0, None),
            )
            self.assertIsNone(records["rounds"][-1]["use_ref"])

    def test_resource_limit_stops_dispatch_and_preserves_incomplete_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            with patch("scripts.ndu_real_runtime.flr_reference.train") as training:
                with self.assertRaisesRegex(
                    ACEValidationError, "FLR_REFERENCE_RESOURCE_BUDGET"
                ):
                    run_campaign(
                        output, "a" * 40, "b" * 40, generations=2, wall_budget=1e-12
                    )
                training.assert_not_called()
            records = json.loads((output / "records.json").read_text())
            self.assertIsNone(records["seal"])
            self.assertTrue(
                all(
                    row["decision"]["kind"] == "UNAVAILABLE"
                    for row in records["rounds"]
                )
            )
            self.assertTrue((output / "plan.json").exists())

    def test_first_meta_failure_has_a_registered_trial_and_settled_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            original_train = reference.train

            def fail_meta(*args, **kwargs):
                if kwargs.get("steps") == 16:
                    saved = json.loads((output / "records.json").read_text())
                    trial = saved["rounds"][-1]["learner_search"][0]
                    self.assertEqual(
                        (trial["status"], trial["result_model"], trial["utility"]),
                        ("UNKNOWN", None, None),
                    )
                    self.assertTrue(trial["operation_id"])
                    raise RuntimeError("meta training failed")
                return original_train(*args, **kwargs)

            with patch.object(reference, "train", side_effect=fail_meta):
                with self.assertRaisesRegex(RuntimeError, "meta training failed"):
                    run_campaign(output, "a" * 40, "b" * 40, generations=2, attempts=1)
            saved = json.loads((output / "records.json").read_text())
            row = saved["rounds"][-1]
            self.assertEqual(
                (row["arm"], len(row["learner_search"]), row["attempts"]), ("R", 1, [])
            )
            self.assertEqual(row["learner_search"][0]["status"], "FAILED")
            self.assertEqual(row["costs"]["search"]["status"], "measured")
            self.assertEqual(row["costs"]["controller"]["status"], "measured")
            self.assertIsNone(row["use_ref"])
            self.assertIsNone(saved["seal"])

    def test_forged_seal_cannot_open_d_without_complete_original_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            result = run_campaign(output, "a" * 40, "b" * 40, generations=2, attempts=1)
            original = result["records"]
            mutations = []
            empty = deepcopy(original)
            empty.update(rounds=[], seal={"rounds_digest": _sha([]), "sequence": 1})
            mutations.append(empty)
            wrong_plan = deepcopy(original)
            wrong_plan["plan_digest"] = "c" * 64
            mutations.append(wrong_plan)
            incomplete = deepcopy(original)
            incomplete["rounds"][-1]["use_ref"] = None
            incomplete["seal"]["rounds_digest"] = _sha(incomplete["rounds"])
            mutations.append(incomplete)
            d_reads, original_read = [], Path.read_text

            def observed_read(path, *args, **kwargs):
                if path.parent.name == "sealed-data":
                    d_reads.append(path)
                return original_read(path, *args, **kwargs)

            for mutation in mutations:
                with self.subTest(
                    mutation=mutation["plan_digest"], rows=len(mutation["rounds"])
                ):
                    (output / "records.json").write_text(json.dumps(mutation))
                    with patch.object(Path, "read_text", observed_read):
                        with self.assertRaises(ACEValidationError):
                            ReferenceStore(output).samples(result["plan"], "external-D")
            self.assertEqual(d_reads, [])


if __name__ == "__main__":
    unittest.main()
