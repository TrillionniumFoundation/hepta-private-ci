"""Prospective driver regressions; manufactured inputs are never efficacy data."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import ctrl_macro_study as study
from ndu_real_runtime import macro_training_pairs
from ndu_real_runtime.test_macro_training_fixtures import collection, read, save


def prepared_fixture(root):
    retained, _ = collection(root)
    plan = read(retained / "PLAN.json")
    repository = str(Path(__file__).resolve().parents[1])
    plan["config"]["runtime_roots"] = [repository]
    case = plan["pairs"][0]["case"]
    case["source_sha256"] = study.sha((root / "materials/source.bin").read_bytes())
    evaluation = deepcopy(case)
    evaluation.update(
        id="development-case",
        source_id="development-source",
        role="development",
        source_sha256="a" * 64,
    )
    prepared = {
        "schema": "ctrl.fresh-experiment-input.v1",
        "collection_plan": plan,
        "evaluation_cases": [
            {
                "source_id": evaluation["source_id"],
                "case_id": evaluation["id"],
                "seed": 7,
                "read_condition": "original",
                "case": evaluation,
            }
        ],
        "read_seconds_bound": 4.0,
        "finalizer_seconds_reserve": 2.0,
    }
    path = root / "prepared.json"
    save(path, prepared)
    args = SimpleNamespace(
        repository=repository,
        prepared_plan=str(path),
        expected_input_sha256=study.sha(path.read_bytes()),
        run_dir=str(root / "study"),
    )
    return args, study.modules(repository)


class ProspectiveStudyTests(unittest.TestCase):
    def test_freeze_retains_raw_input_and_collector_bytes_without_actor(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, modules = prepared_fixture(Path(temporary))
            study.freeze(args, modules)
            root = Path(args.run_dir)
            args.freeze_sha256 = study.sha((root / "FROZEN.json").read_bytes())
            _, frozen, _ = study.thaw(args, modules)
            self.assertEqual(
                (root / "PREPARED_INPUT.json").read_bytes(),
                Path(args.prepared_plan).read_bytes(),
            )
            self.assertEqual(
                frozen["collection_plan_bytes_sha256"],
                study.sha((root / "COLLECTION_PLAN.json").read_bytes()),
            )
            self.assertEqual(
                frozen["methods"],
                [
                    "STOP",
                    "light",
                    "tuned-fixed",
                    "point",
                    "unconditional",
                    "conditional",
                ],
            )
            self.assertFalse((root / "collection").exists())
            self.assertFalse((root / "CHECKPOINT.json").exists())

    def test_external_pin_and_create_only_output_refuse_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, modules = prepared_fixture(Path(temporary))
            original = args.expected_input_sha256
            args.expected_input_sha256 = "0" * 64
            with self.assertRaisesRegex(ValueError, "external raw-byte pin"):
                study.freeze(args, modules)
            self.assertFalse(Path(args.run_dir).exists())
            args.expected_input_sha256 = original
            study.freeze(args, modules)
            frozen = (Path(args.run_dir) / "FROZEN.json").read_bytes()
            with self.assertRaises(FileExistsError):
                study.freeze(args, modules)
            self.assertEqual((Path(args.run_dir) / "FROZEN.json").read_bytes(), frozen)

    def test_thaw_refuses_retained_collection_plan_or_frozen_identity_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, modules = prepared_fixture(Path(temporary))
            study.freeze(args, modules)
            root = Path(args.run_dir)
            args.freeze_sha256 = study.sha((root / "FROZEN.json").read_bytes())
            plan = root / "COLLECTION_PLAN.json"
            plan.write_bytes(plan.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "collection plan changed"):
                study.thaw(args, modules)
            args.freeze_sha256 = "0" * 64
            with self.assertRaisesRegex(ValueError, "external raw-byte pin"):
                study.thaw(args, modules)

    def test_overlapping_or_aliased_evaluation_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, modules = prepared_fixture(Path(temporary))
            original = read(Path(args.prepared_plan))
            for kind in ("source_overlap", "physical_alias"):
                prepared = deepcopy(original)
                evaluation = prepared["evaluation_cases"][0]
                train = prepared["collection_plan"]["pairs"][0]["case"]
                if kind == "source_overlap":
                    evaluation["source_id"] = train["source_id"]
                    evaluation["case"]["source_id"] = train["source_id"]
                    evaluation["case"]["source_sha256"] = train["source_sha256"]
                else:
                    evaluation["case"]["source_sha256"] = train["source_sha256"]
                save(Path(args.prepared_plan), prepared)
                args.expected_input_sha256 = study.sha(
                    Path(args.prepared_plan).read_bytes()
                )
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    study.freeze(args, modules)
                self.assertFalse(Path(args.run_dir).exists())

    def test_one_unknown_pair_blocks_fit_without_creating_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, modules = prepared_fixture(Path(temporary))
            study.freeze(args, modules)
            root = Path(args.run_dir)
            args.freeze_sha256 = study.sha((root / "FROZEN.json").read_bytes())
            _, _, context = study.thaw(args, modules)
            report = {
                "schema": "ndu.real.macro-training-export.v1",
                "context": context.to_wire(),
                "converter_source_sha256": macro_training_pairs.source_sha256(),
                "planned": [{"pair_id": "p1", "split": "train", "status": "UNKNOWN"}],
                "rows": [],
                "planned_pairs": 1,
                "exported_pairs": 0,
                "unknown_pairs": 1,
            }
            study.write(root / "EXPORT.json", report)
            study.write(
                root / "EXPORT_PIN.json",
                {"canonical_sha256": modules["digest"](report)},
            )
            args.stage = "fit"
            with self.assertRaisesRegex(ValueError, "Incomplete planned collection"):
                study.run_stage(args, modules)
            self.assertFalse((root / "CHECKPOINT.json").exists())
            self.assertFalse((root / "FIT_STAGE.json").exists())

    def test_invalid_evaluation_registration_fails_before_any_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, modules = prepared_fixture(Path(temporary))
            original = read(Path(args.prepared_plan))
            for kind in (
                "source_identity",
                "case_identity",
                "duplicate",
                "boolean_seed",
                "negative_seed",
                "intervention",
                "excluded",
                "source_bytes",
            ):
                prepared = deepcopy(original)
                registered = prepared["evaluation_cases"][0]
                if kind == "source_identity":
                    registered["source_id"] = "unrelated-source"
                elif kind == "case_identity":
                    registered["case_id"] = "unrelated-case"
                elif kind == "duplicate":
                    prepared["evaluation_cases"].append(deepcopy(registered))
                elif kind in ("boolean_seed", "negative_seed"):
                    registered["seed"] = True if kind == "boolean_seed" else -1
                elif kind == "intervention":
                    registered["read_condition"] = "repeat"
                elif kind == "excluded":
                    prepared["collection_plan"]["excluded_sources"].append(
                        registered["source_id"]
                    )
                else:
                    registered["case"]["source_sha256"] = "unbound-image"
                save(Path(args.prepared_plan), prepared)
                args.expected_input_sha256 = study.sha(
                    Path(args.prepared_plan).read_bytes()
                )
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    study.freeze(args, modules)
                self.assertFalse(Path(args.run_dir).exists())


if __name__ == "__main__":
    unittest.main()
