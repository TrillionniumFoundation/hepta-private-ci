"""Numerical/behavioral fixtures only; none are evidence of real users or teachers."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cell_experiments import composition as c


BINDING = c.digest({"encoder": "authored two-dimensional unit-test features"})


def observations():
    """Fixed authored inputs with an explicit test-only sign classification task."""
    result = []
    for split, base in (("A", 10), ("B", 100), ("C", 200)):
        for i, value in enumerate((-2.0, -1.0, 1.0, 2.0)):
            identity = f"fixture-{split}-{i}"
            result.append(
                dict(
                    record_id=identity,
                    task_id=identity,
                    lineage_id=identity,
                    source_id=f"{split}-source-{i % 2}",
                    project_id="test-project",
                    family_id=f"{split}-sign",
                    split=split,
                    observed_at=base + i,
                    available_at=base + i + 0.25,
                    origin_kind="curated_development",
                    exposure="development",
                    teacher_id=None,
                    authorization={
                        "training_allowed": True,
                        "rights_basis": "authored test",
                    },
                    features={
                        "values": [value, 1.0],
                        "binding": BINDING,
                        "available_at": base + i - 1,
                        "preaction_at": base + i - 0.5,
                    },
                    target=int(value > 0),
                    target_name="test_positive_sign",
                    n_classes=2,
                    task={"input": {"fixture_id": identity, "value": value}},
                    verified_outcome={
                        "success": True,
                        "receipt_sha256": c.digest(identity),
                    },
                )
            )
    return result


def plan(seeds=(3,)):
    return dict(
        schema="hepta.composition-plan.v1",
        evidence_scope="engineering",
        max_train_mac=512,
        max_examples=32,
        passes=12,
        learning_rate=0.2,
        cells=3,
        active=2,
        classes=2,
        seeds=list(seeds),
        target_name="test_positive_sign",
    )


def teachers(directory, same_model=False):
    """Mock producer receipts bind literal test outputs; origin is not authenticated."""
    rows, evidence = observations(), {}
    training = [r for r in rows if r["split"] == "A"]
    rows = [r for r in rows if r["split"] != "A"]
    for i, teacher in enumerate(("fixture-teacher-one", "fixture-teacher-two")):
        model_digest = c.digest({"mock_model": 0 if same_model else i})
        outputs = {}
        for row in training:
            row = copy.deepcopy(row)
            label = row["target"] if i == 0 else 1 - row["target"]
            row.update(
                teacher_id=teacher,
                model_digest=model_digest,
                teacher_target=label,
                actual_output=str(label),
            )
            rows.append(row)
            outputs[row["task_id"]] = {"output": str(label), "teacher_target": label}
        receipt = {
            "teacher_id": teacher,
            "model_digest": model_digest,
            "kind": "external_model",
            "outputs": outputs,
            "test_fixture": True,
        }
        raw = c.canonical(receipt)
        path = Path(directory) / (teacher + ".json")
        path.write_bytes(raw)
        evidence[teacher] = {
            "receipt_path": str(path),
            "model_digest": model_digest,
            "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        }
    return rows, evidence


class IntegrityTests(unittest.TestCase):
    def test_evaluation_failure_keeps_actual_completed_training_cost(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                c, "evaluate", side_effect=ValueError("nonfinite evaluation logits")
            ),
        ):
            result = c.run(observations(), plan(), Path(directory) / "failed", BINDING)
            self.assertEqual(result["status"], "BLOCKED_NO_EVALUATED_CANDIDATE")
            self.assertEqual(result["selections"], [])
            self.assertTrue(result["attempts"])
            for attempt in result["attempts"]:
                self.assertEqual(attempt["status"], "FAILED")
                self.assertGreater(attempt["training"]["updates"], 0)
                self.assertGreater(attempt["training"]["linear_mac"], 0)

    def test_duplicate_content_and_cross_split_groups_are_rejected(self):
        for field in ("task_id", "lineage_id", "source_id", "family_id"):
            rows = observations()
            rows[4][field] = rows[0][field]
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "crosses split"),
            ):
                c.normalize(rows, BINDING, 2)
        rows = observations()
        rows[1]["task"]["input"] = copy.deepcopy(rows[0]["task"]["input"])
        with self.assertRaisesRegex(ValueError, "relabeled"):
            c.normalize(rows, BINDING, 2)
        rows = observations()
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            c.normalize(rows, BINDING, 2)

    def test_postaction_features_and_nonchronological_panels_are_rejected(self):
        rows = observations()
        rows[0]["features"]["available_at"] = rows[0]["features"]["preaction_at"] + 1
        with self.assertRaisesRegex(ValueError, "post-action"):
            c.normalize(rows, BINDING, 2)
        rows = observations()
        rows[0]["available_at"] = 1000
        with self.assertRaisesRegex(ValueError, "nonchronological"):
            c.normalize(rows, BINDING, 2)

    def test_default_independent_gate_blocks_and_engineering_records_gaps(self):
        rows, options = observations(), plan()
        del options["evidence_scope"]
        with tempfile.TemporaryDirectory() as directory:
            strict = c.run(rows, options, Path(directory) / "strict", BINDING)
            self.assertEqual(strict["status"], "BLOCKED")
            self.assertEqual(strict["attempts"], [])
            self.assertTrue(strict["evidence_gaps"])
            rows[0]["available_at"] = 1000
            engineering = c.run(rows, plan(), Path(directory) / "engineering", BINDING)
            self.assertEqual(engineering["status"], "completed_research_only")
            self.assertFalse(engineering["time_ordered"])
            self.assertEqual(engineering["independent_experiment_status"], "BLOCKED")
            self.assertFalse(engineering["production_eligible"])
            self.assertTrue(
                any("times overlap" in gap for gap in engineering["evidence_gaps"])
            )
            rows[4]["family_id"] = rows[0]["family_id"]
            leaking = c.run(rows, plan(), Path(directory) / "leaking", BINDING)
            self.assertEqual(leaking["status"], "BLOCKED")
            self.assertEqual(leaking["attempts"], [])

    def test_teacher_receipt_pin_and_distinct_model_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            rows, registry = teachers(directory, same_model=True)
            with self.assertRaisesRegex(ValueError, "two distinct"):
                c.teacher_registry(c.normalize(rows, BINDING, 2), registry, 2)
            rows, registry = teachers(directory)
            first = next(iter(registry.values()))
            Path(first["receipt_path"]).write_bytes(b"{}")
            with self.assertRaisesRegex(ValueError, "receipt bytes"):
                c.teacher_registry(c.normalize(rows, BINDING, 2), registry, 2)

    def test_empty_teacher_output_is_bound_invalid_class_not_gold_or_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            rows, registry = teachers(directory)
            for row in rows:
                row.update(n_classes=3, target_name="required_result_value_domain")
                if row.get("teacher_id"):
                    row.update(actual_output="", teacher_target=2)
            for entry in registry.values():
                path = Path(entry["receipt_path"])
                receipt = json.loads(path.read_bytes())
                for output in receipt["outputs"].values():
                    output.update(output="", teacher_target=2)
                path.write_bytes(c.canonical(receipt))
                entry["receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            options = plan()
            options.update(classes=3, target_name="required_result_value_domain")
            result = c.run(rows, options, Path(directory) / "empty", BINDING, registry)
            self.assertEqual(result["E3"]["status"], "executed_hard_label_imitation")
            saved = json.loads((Path(directory) / "empty" / "INPUTS.json").read_bytes())
            self.assertEqual(saved, rows)
            teacher_rows = [r for r in saved if r.get("teacher_id")]
            self.assertTrue(
                all(
                    r["actual_output"] == ""
                    and r["teacher_target"] == 2
                    and r["target"] in (0, 1)
                    for r in teacher_rows
                )
            )
            imitators = [
                a
                for a in result["attempts"]
                if a["experiment"] == "E3" and a["label"] != "student_specialists"
            ]
            self.assertTrue(all(a["B"]["accuracy"] == 0 for a in imitators))

    def test_c_labels_cannot_change_b_selection_and_missing_evidence_stays_blocked(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            rows = observations()
            first_dir, second_dir = (
                Path(directory) / "first",
                Path(directory) / "second",
            )
            first = c.run(rows, plan((3, 7)), first_dir, BINDING)
            altered = copy.deepcopy(rows)
            for row in altered:
                if row["split"] == "C":
                    row["target"] = 1 - row["target"]
            second = c.run(altered, plan((3, 7)), second_dir, BINDING)
            self.assertEqual(first["status"], "completed_research_only")
            self.assertEqual(second["status"], "completed_research_only")
            self.assertEqual(first["selections"], second["selections"])
            self.assertEqual(
                (first_dir / "FROZEN_SELECTIONS.json").read_bytes(),
                (second_dir / "FROZEN_SELECTIONS.json").read_bytes(),
            )
            self.assertEqual(first["E3"]["status"], "BLOCKED")
            self.assertEqual(sum(g["status"] == "BLOCKED" for g in first["E5"]), 6)
            self.assertEqual(first["C_ablation_evaluations"], 27)
            self.assertEqual(first["C_total_evaluations"], first["C_evaluations"] + 27)
            self.assertFalse(first["graph_necessity_qualified"])
            self.assertFalse(first["independent_confirmation_qualified"])
            self.assertEqual(first["real_users_verified"], 0)
            self.assertTrue(
                all(a["training"]["updates"] > 0 for a in first["attempts"])
            )
            choice = first["selections"][0]["chosen_attempt_id"]
            before = json.loads(
                (first_dir / choice / "C_EVALUATION.json").read_bytes()
            )["C"]["rows"]
            after = json.loads(
                (second_dir / choice / "C_EVALUATION.json").read_bytes()
            )["C"]["rows"]
            self.assertEqual(
                [r["prediction"] for r in before], [r["prediction"] for r in after]
            )
            self.assertNotEqual(
                [r["target"] for r in before], [r["target"] for r in after]
            )

    def test_multi_teacher_training_uses_both_cost_stages_and_preserves_raw_outputs(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            rows, registry = teachers(directory)
            result = c.run(rows, plan(), Path(directory) / "run", BINDING, registry)
            self.assertEqual(result["E3"]["status"], "executed_hard_label_imitation")
            attempts = [a for a in result["attempts"] if a["experiment"] == "E3"]
            self.assertEqual(len(attempts), 5)
            self.assertTrue(
                all(a["status"] == "completed_candidate_only" for a in attempts)
            )
            composed = next(a for a in attempts if a["label"] == "student_specialists")
            self.assertEqual(len(composed["preparation"]), 2)
            self.assertEqual(
                composed["total_training"]["linear_mac"],
                composed["training"]["linear_mac"]
                + sum(p["linear_mac"] for p in composed["preparation"]),
            )
            self.assertLessEqual(
                composed["total_training"]["linear_mac"], plan()["max_train_mac"]
            )
            self.assertLessEqual(
                composed["total_training"]["updates"], plan()["max_examples"]
            )
            self.assertNotEqual(
                composed["training"]["parent_digest"],
                composed["training"]["candidate_digest"],
            )
            self.assertEqual(
                json.loads((Path(directory) / "run" / "INPUTS.json").read_bytes()), rows
            )
            self.assertFalse(result["E3"]["on_policy_distillation"])


if __name__ == "__main__":
    unittest.main()
