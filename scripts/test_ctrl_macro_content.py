"""CPU-only content-admission controls; fixtures are not native task evidence.

The upstream native-export admission is mocked explicitly. These tests exercise
the subsequent train-only reconstruction and create-only output boundary with
the real row serializer, bound-file reads and delivery verifier, without Torch.
"""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import ctrl_macro_content as content
from ndu_real_materials import common
from ndu_real_runtime.controllers import ControlPlan
from ndu_real_runtime.episode import EpisodeHost
from ndu_real_runtime.metacontrol_macro_contract import SEQUENCES, digest
from ndu_real_runtime.objective import utility_profile


def fixture(directory):
    root, materials, output = (directory / name for name in ("run", "data", "out"))
    for path in (root, materials, output):
        path.mkdir()
    control = ControlPlan()
    control_path = directory / "control.json"
    control_sha = content.study.write(control_path, {"control": asdict(control)})
    reference = {
        "field": "total",
        "expected_text": "10.00",
        "target_boxes": [[0, 0, 10, 10]],
    }
    content.study.write(materials / "reference.json", reference)
    content.study.write(
        materials / "packet.json", {"source_size": {"width": 100, "height": 100}}
    )
    case = {
        "id": "train-case",
        "role": "train",
        "source_id": "train-source",
        "reference": common.binding(materials / "reference.json", materials),
        "packet": common.binding(materials / "packet.json", materials),
    }
    profile = {
        "control_plan": str(control_path),
        "control_plan_sha256": control_sha,
        "model_sha256": "1" * 64,
    }
    config = {
        "material_root": str(materials),
        "evaluator_sha256": "2" * 64,
        "rubric_sha256": "3" * 64,
        "runtime_roots": [],
        "latency_weight": 0.01,
    }
    plan = {
        "config": config,
        "profile": profile,
        "source_splits": {
            "train": ["train-source"],
            "calibration": ["cal-source"],
            "future": [],
        },
        "pairs": [
            {"pair_id": "trainpair", "split": "train", "case": case},
            {
                "pair_id": "calpair",
                "split": "calibration",
                "case": {
                    "id": "unopened-cal-case",
                    "source_id": "cal-source",
                    "role": "train",
                    "reference": {"path": "must-not-open.json"},
                },
            },
        ],
    }
    original = []
    for macro, actions in SEQUENCES.items():
        branch = root / "collection" / ("trainpair-" + macro)
        branch.mkdir(parents=True)
        operation = "trainpair/" + macro
        steps = [
            {
                "action": {"action": action},
                "candidate_features": [[0.0] * 126],
                "candidate_metadata": [{"text": "10.00", "bbox": [0, 0, 10, 10]}],
                "public_metadata": [0.0] * 16,
                "observed_action_seconds": 0.01,
                "remaining_seconds": 30.0 - index,
                "legal_actions": list(dict.fromkeys([*actions, "STOP"])),
            }
            for index, action in enumerate(actions)
        ]
        content.study.write(branch / "trajectory.json", {"steps": steps})
        content.study.write(
            branch / "result.json",
            {
                "actions": actions,
                "terminal_status": "Completed",
                "original_operation_id": operation,
            },
        )
        scores = []
        for index in range(len(steps) + 1):
            delivery = branch / f"delivery-{index:02d}"
            delivery.mkdir()
            delivery_pin = content.study.write(
                delivery / "delivery.json",
                {
                    "case_id": case["id"],
                    "text": "10.00" if "WRITE_TEXT" in actions[:index] else "",
                },
            )
            score = {
                "schema": "ndu.real.independent-evaluation.v1",
                "case_id": case["id"],
                "evaluator_source_sha256": config["evaluator_sha256"],
                "rubric_sha256": config["rubric_sha256"],
                "delivery_sha256": delivery_pin,
                "reference_sha256": case["reference"]["sha256"],
                "role": "train",
                "quality": float("WRITE_TEXT" in actions[:index]),
            }
            content.study.write(delivery / "evaluation.json", score)
            scores.append(score)
        receiver = SimpleNamespace(
            steps=steps,
            operation_id=operation,
            case=case,
            reference=reference,
            source_size=(100, 100),
            control=control,
            utility_profile_sha256=digest(utility_profile(control)),
            control_profile_sha256=digest(asdict(control)),
            config=config,
            profile=profile,
            output=branch,
        )
        EpisodeHost.training_rows(receiver, scores)
        original.append((branch / "training-rows.jsonl").read_bytes())
    report = {
        "planned": [{"evidence_kind": "native_module_execution"}],
        "scope": "mocked upstream admission; manufactured CPU fixture only",
    }
    content.study.write(root / "EXPORT.json", report)
    content.study.write(root / "EXPORT_PIN.json", {"canonical_sha256": digest(report)})
    admission = SimpleNamespace(
        export=Mock(return_value=deepcopy(report)), fit_rows=Mock(return_value=[])
    )
    modules = {
        "macro_training_pairs": admission,
        "ControlPlan": ControlPlan,
        "digest": digest,
    }
    frozen = {
        "collection_plan": plan,
        "collection_plan_bytes_sha256": "4" * 64,
        "converter_sha256": "5" * 64,
    }
    return SimpleNamespace(
        root=root,
        output=output,
        materials=materials,
        frozen=frozen,
        modules=modules,
        context=object(),
        original=b"".join(original),
        admission=admission,
    )


def export(data):
    return content.export_train(
        data.root, data.frozen, data.context, data.modules, data.output
    )


class ContentAdmissionTests(unittest.TestCase):
    def test_reconstructs_original_rows_without_opening_calibration_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp))
            result = export(data)
            actual = (data.output / "records.jsonl").read_bytes()
            self.assertEqual(actual, data.original)
            self.assertEqual(
                (result["sources"], result["sha256"]),
                (["train-source"], content.study.sha(actual)),
            )
            self.assertEqual(data.admission.fit_rows.call_args.args[1], "train")
            self.assertEqual(
                {row["source_group"] for row in map(json.loads, actual.splitlines())},
                {"train-source"},
            )
            self.assertTrue(
                all(
                    Path(pin["path"]).is_file()
                    and content.study.sha(Path(pin["path"]).read_bytes())
                    == pin["sha256"]
                    for pin in result["original_pins"]
                )
            )

    def test_export_drift_incomplete_gate_and_fixture_evidence_stop_before_reference(
        self,
    ):
        for fault in ("drift", "incomplete", "fixture"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                if fault == "drift":
                    data.admission.export.return_value["scope"] = "changed"
                elif fault == "incomplete":
                    data.admission.fit_rows.side_effect = ValueError(
                        "Incomplete planned collection"
                    )
                else:
                    report = data.admission.export.return_value
                    report["planned"][0]["evidence_kind"] = "fixture"
                    (data.root / "EXPORT.json").write_text(json.dumps(report))
                with patch.object(
                    common,
                    "read_bound",
                    side_effect=AssertionError("reference was opened"),
                ):
                    with self.assertRaises(ValueError):
                        export(data)
                self.assertFalse((data.output / "records.jsonl").exists())

    def test_score_delivery_and_reference_identity_drift_are_rejected(self):
        for field in ("delivery_sha256", "reference_sha256", "role", "quality"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                path = (
                    data.root / "collection/trainpair-STOP/delivery-00/evaluation.json"
                )
                score = content.study.read(path)
                score[field] = (
                    "confirmation"
                    if field == "role"
                    else 0.5
                    if field == "quality"
                    else "0" * 64
                )
                path.write_text(json.dumps(score))
                with self.assertRaises(ValueError):
                    export(data)
                self.assertFalse((data.output / "records.jsonl").exists())

    def test_serialized_training_row_change_is_not_admitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp))
            path = data.root / "collection/trainpair-READ/training-rows.jsonl"
            rows = [json.loads(line) for line in path.read_bytes().splitlines()]
            rows[0]["expected_text"] = "FORGED"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.assertRaisesRegex(ValueError, "reconstructed"):
                export(data)
            self.assertFalse((data.output / "records.jsonl").exists())

    def test_unregistered_and_missing_train_sources_cannot_shrink_denominator(self):
        for fault in ("role", "unregistered", "missing"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                plan = data.frozen["collection_plan"]
                if fault == "role":
                    plan["pairs"][0]["case"]["role"] = "development"
                elif fault == "unregistered":
                    plan["pairs"][0]["case"]["source_id"] = "cal-source"
                else:
                    plan["source_splits"]["train"].append("missing-source")
                with self.assertRaises(ValueError):
                    export(data)
                self.assertFalse((data.output / "records.jsonl").exists())

    def test_budget_stopped_branch_cannot_supply_complete_content_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = fixture(Path(tmp))
            path = data.root / "collection/trainpair-READ/result.json"
            native = content.study.read(path)
            native.update(terminal_status="BudgetStop", actions=SEQUENCES["READ"][:-1])
            path.write_text(json.dumps(native))
            with self.assertRaisesRegex(ValueError, "completed"):
                export(data)
            self.assertFalse((data.output / "records.jsonl").exists())

    def test_adaptation_output_is_private_and_create_only_before_export(self):
        for fault in ("actor_visible", "existing"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                data = fixture(Path(tmp))
                actor = Path(tmp) / "actor"
                actor.mkdir()
                data.frozen["collection_plan"]["config"]["runtime_roots"] = [str(actor)]
                target = actor / "learned" if fault == "actor_visible" else data.output
                args = SimpleNamespace(
                    repository=tmp,
                    run_dir=str(data.root),
                    freeze_sha256="6" * 64,
                    output=str(target),
                    epochs=1,
                    learning_rate=0.0003,
                    seed=7,
                )
                with (
                    patch.object(content.study, "modules", return_value=data.modules),
                    patch.object(
                        content.study,
                        "thaw",
                        return_value=(data.root, data.frozen, data.context),
                    ),
                    patch.object(
                        content,
                        "export_train",
                        side_effect=AssertionError("export entered"),
                    ),
                ):
                    with self.assertRaises((ValueError, FileExistsError)):
                        content.adapt(args)
                self.assertFalse((target / "PLAN.json").exists())


if __name__ == "__main__":
    unittest.main()
