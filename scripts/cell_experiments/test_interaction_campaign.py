"""Orchestration tests use declared fixtures; no model is loaded or trained."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import campaign, coding_sft, data, interaction_campaign as e2
from .test_data import record


def fake_collection(rows, parent, root, out, max_steps):
    out.mkdir(parents=True)
    for arm in ("demonstration", "shadow", "controlled"):
        corpus = copy.deepcopy(rows)
        for row, original in zip(corpus, rows):
            row["interaction"] = {"parent_record_digest": data.digest(original)}
        (out / (arm + ".jsonl")).write_bytes(
            b"".join(data.canonical(row) + b"\n" for row in corpus)
        )
    result = {"status": "COMPLETE_DEVELOPMENT_COLLECTION", "unit_test_fixture": True}
    coding_sft.write_new(out / "RESULT.json", result)
    return result


def setup(root):
    rows = [record(1), record(2, "selection"), record(3, "confirmation")]
    coding_sft.write_new(
        root / "CAMPAIGN.json",
        {"dataset_digest": data.digest(rows), "source_digest": e2._sources()},
    )
    coding_sft.write_new(
        root / "parent.json",
        {"runtime": {"max_input_tokens": 512}, "unit_test_fixture": True},
    )
    return rows


class InteractionCampaignTests(unittest.TestCase):
    def test_collection_freezes_correct_mode_and_exact_corpus_for_all_three_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = setup(root)
            with (
                patch.object(campaign, "guard", return_value=rows, create=True),
                patch.object(e2.interaction, "collect", side_effect=fake_collection),
            ):
                e2.run("collect", root, "unused-fixture-path")
            for name in e2.NAMES:
                plan = e2._read(root / "plans" / (name + ".json"))
                corpus = e2._read(root / "plans" / (name + ".records.json"))
                self.assertEqual(
                    (
                        plan["training_mode"],
                        plan["training"],
                        plan["training_records_digest"],
                    ),
                    ("trajectory", e2.TRAINING, data.digest(corpus)),
                )
            frozen = e2._read(root / "E2/E2_PLAN.json")
            self.assertTrue(frozen["trajectory_repeats_correction_as_final_answer"])
            self.assertEqual(frozen["original_tasks"], 1)

    def test_selection_is_create_only_and_changed_b_bytes_block_c_before_model_calls(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = setup(root)
            with (
                patch.object(campaign, "guard", return_value=rows, create=True),
                patch.object(e2.interaction, "collect", side_effect=fake_collection),
                patch.object(
                    coding_sft,
                    "verify_model",
                    side_effect=lambda value, _: data.digest(value),
                ),
            ):
                e2.run("collect", root, "unused-fixture-path")
                plan = e2._read(root / "E2/E2_PLAN.json")
                for name in e2.NAMES:
                    train_plan = e2._read(root / "plans" / (name + ".json"))
                    model = {"name": name, "unit_test_fixture": True}
                    coding_sft.write_new(
                        root / "models" / name / "manifest.json", model
                    )
                    coding_sft.write_new(
                        root / "models" / name / "training.json",
                        {
                            "status": "COMPLETE",
                            "candidate_model_digest": data.digest(model),
                            "parent_model_digest": plan["parent_model_digest"],
                            "plan_digest": data.digest(train_plan),
                            "steps": 32,
                            "mode": "trajectory",
                            "records_digest": train_plan["training_records_digest"],
                        },
                    )
                    coding_sft.write_new(
                        root / "E2/B" / name / "RESULT.json",
                        {
                            "status": "COMPLETE_DEVELOPMENT_EVALUATION",
                            "model_digest": data.digest(model),
                            "denominator": 1,
                            "max_model_calls_per_task": 2,
                            "successes": 1,
                            "tasks": [
                                {
                                    "task_id": rows[1]["task_id"],
                                    "record_digest": data.digest(rows[1]),
                                    "success": True,
                                }
                            ],
                        },
                    )
                choice = e2.run("select", root, "unused-fixture-path")
                self.assertEqual(choice["selected_arm"], "e2_controlled")
                with self.assertRaises(FileExistsError):
                    e2.run("select", root, "unused-fixture-path")
                path = root / "E2/B/e2_shadow/RESULT.json"
                path.write_text(
                    json.dumps(e2._read(path), indent=2)
                )  # Same meaning, changed original bytes.
                with patch.object(e2.interaction, "evaluate") as evaluator:
                    with self.assertRaisesRegex(ValueError, "evidence changed"):
                        e2.run("confirm", root, "unused-fixture-path")
                    evaluator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
