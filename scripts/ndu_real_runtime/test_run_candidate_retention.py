"""Runner contract fixtures, not trained-model efficacy or isolation evidence."""

from concurrent.futures import Future
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from ndu_real_materials.common import binding, json_bytes, strict_json, write_json
from .actor import parameter_sha
from .controllers import ControlPlan
from .neural import ReceiptPortfolioModel
from . import run_candidate_retention as runner


def row(source, role, family, episode=None):
    episode = episode or source + "-episode"
    return {
        "id": episode + "-" + family,
        "source_id": source,
        "role": role,
        "task_family": family,
        "episode_group": episode,
        "packet": {},
        "reference": {},
    }


def request_fixture(root):
    """Use a random untrained checkpoint and synthetic metadata only."""
    materials = root / "materials"
    materials.mkdir()
    cases = [
        row("training", "train", "text_sufficient"),
        row("tuning", "train", "text_sufficient"),
    ]
    cases += [row("development", "development", family) for family in runner.FAMILIES]
    cases += [row("retention", "retention_validation", "text_image_complementary")]
    for case in cases:
        name = case["id"]
        write_json(
            materials / (name + "-packet.json"),
            {"case_id": name, "source_size": {"width": 20, "height": 20}},
        )
        write_json(
            materials / (name + "-reference.json"),
            {
                "case_id": name,
                "role": case["role"],
                "source_group": case["source_id"],
                "episode_group": case["episode_group"],
                "source_image": {"sha256": "a" * 64},
            },
        )
        case["packet"] = binding(materials / (name + "-packet.json"), materials)
        case["reference"] = binding(materials / (name + "-reference.json"), materials)
    write_json(materials / "catalog.json", {"cases": cases})
    write_json(materials / "rubric.json", {"version": 1})
    write_json(
        materials / "private/reference-index.v2.json",
        {
            "schema": "ndu.real.reference-index.v2",
            "cases": {c["id"]: c["reference"] for c in cases},
            "case_roles": {c["id"]: c["role"] for c in cases},
            "rubric": binding(materials / "rubric.json", materials),
        },
    )
    write_json(
        materials / "selection.json",
        {
            "schema": "ndu.real.selected-sources.v1",
            "groups": {"training": ["training"], "tuning": ["tuning"]},
            "cases": {"training": [cases[0]], "tuning": [cases[1]]},
        },
    )
    write_json(
        materials / "exposure.json",
        {
            "schema": "ndu.real.researcher-exposure.v1",
            "registry_sha256": "b" * 64,
            "quarantined_source_groups": [],
        },
    )
    (materials / "records.jsonl").write_text(
        json.dumps(
            {
                "source_group": "training",
                "split": "train",
                "record_id": "r",
                "episode_id": "training-episode",
            }
        )
        + "\n"
    )
    model_dir = root / "model"
    model_dir.mkdir()
    model = ReceiptPortfolioModel("hepta")
    torch.save(model.state_dict(), model_dir / "weights.pt")
    weights = {
        **binding(model_dir / "weights.pt", root),
        "path": str(model_dir / "weights.pt"),
    }
    control = ControlPlan(max_forecasts=128, max_sequences=84, particles=2)
    control_sha = runner.canonical_sha(asdict(control))
    write_json(
        model_dir / "deployment-profile.json",
        {
            "weights_sha256": weights["sha256"],
            "core": "hepta",
            "control_profile_sha256": control_sha,
        },
    )
    deployment = {
        **binding(model_dir / "deployment-profile.json", root),
        "path": str(model_dir / "deployment-profile.json"),
    }
    records = binding(materials / "records.jsonl", materials)
    write_json(
        model_dir / "receipt.json",
        {
            "status": "CONTENT_PRETRAINED",
            "core": "hepta",
            "control": asdict(control),
            "weights_sha256": weights["sha256"],
            "final_parameter_sha256": parameter_sha(model),
            "deployment_profile_sha256": deployment["sha256"],
            "control_profile_sha256": control_sha,
            "records": {
                "sha256": records["sha256"],
                "bytes": records["bytes"],
                "source_groups": 1,
                "episodes": 1,
            },
        },
    )
    ocr = root / "ocr"
    (ocr / "libraries").mkdir(parents=True)
    (ocr / "tesseract").write_bytes(b"fixture executable, never invoked")
    (ocr / "tesseract").chmod(0o700)
    (ocr / "eng.traineddata").write_bytes(b"fixture language bytes")
    (ocr / "libraries/libocr.so").write_bytes(b"fixture library bytes")
    config = {
        "repository_root": str(runner.REPOSITORY),
        "scripts_root": str(runner.REPOSITORY / "scripts"),
        "material_root": str(materials),
        "episode_wall_seconds": 60,
        "latency_weight": 0.01,
        "evaluator_sha256": runner.file_sha(
            runner.REPOSITORY / "scripts/ndu_real_materials/evaluator.py"
        ),
        "reference_index_sha256": runner.file_sha(
            materials / "private/reference-index.v2.json"
        ),
        "rubric_sha256": runner.file_sha(materials / "rubric.json"),
        "tesseract": str(ocr / "tesseract"),
        "tessdata_dir": str(ocr),
        "ocr_library_dir": str(ocr / "libraries"),
    }
    return {
        "schema": runner.SCHEMA,
        "experiment_id": "fixture",
        "source_commit": "c" * 40,
        "source_pins": [
            binding(runner.REPOSITORY / name, runner.REPOSITORY)
            for name in sorted(runner.required_source_paths())
        ],
        "config": config,
        "model": {
            "core": "hepta",
            "weights": weights,
            "receipt": {
                **binding(model_dir / "receipt.json", root),
                "path": str(model_dir / "receipt.json"),
            },
            "deployment_profile": deployment,
            "parameters_sha256": parameter_sha(model),
            "control_profile_sha256": control_sha,
        },
        "catalog": binding(materials / "catalog.json", materials),
        "training_records": records,
        "exclusion_manifest": binding(materials / "selection.json", materials),
        "exposure_ledgers": [binding(materials / "exposure.json", materials)],
        "excluded_source_groups": ["training", "tuning"],
        "registry_sha256": "b" * 64,
        "selection_salt": "fixed-fixture-salt",
        "groups_per_role": {"development": 1, "retention_validation": 1},
        "max_workers": 2,
    }


class InlinePool:
    """Only task orchestration is synchronous; no actor results are simulated."""

    exited = False
    after_pair = None

    def __init__(self, **kwargs):
        type(self).exited = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        type(self).exited = True

    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as error:
            future.set_exception(error)
        if type(self).after_pair is not None:
            type(self).after_pair()
        return future


class CandidateRetentionRunnerTests(unittest.TestCase):
    def test_selection_is_stable_complete_and_source_excluded(self):
        cases = [
            row(source, "development", family, episode)
            for source in ("a", "b", "c")
            for episode in (source + "1", source + "2")
            for family in runner.FAMILIES
        ]
        cases += [row("r", "retention_validation", "text_image_complementary")]
        counts = {"development": 2, "retention_validation": 1}
        selected = runner.select_cases({"cases": cases}, {"a"}, counts, "salt")
        self.assertEqual(
            selected,
            runner.select_cases(
                {"cases": list(reversed(cases))}, {"a"}, counts, "salt"
            ),
        )
        self.assertEqual({c["source_id"] for c in selected}, {"b", "c", "r"})
        self.assertEqual(len(selected), 11)
        for source in ("b", "c"):
            self.assertEqual(
                len({c["episode_group"] for c in selected if c["source_id"] == source}),
                1,
            )
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            runner.select_cases({"cases": cases}, {"a", "b"}, counts, "salt")
        cases.append(row("b", "retention_validation", "text_sufficient", "cross-role"))
        with self.assertRaisesRegex(ValueError, "crosses roles"):
            runner.select_cases({"cases": cases}, set(), counts, "salt")

    def test_model_load_and_training_roster_bind_actual_tensor_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            request = request_fixture(Path(directory))
            _, receipt = runner.load_model(request, {"training"})
            self.assertEqual(
                [
                    receipt[k]
                    for k in (
                        "actual_weights_sha256",
                        "actual_parameters_sha256",
                        "independent_training_repeats",
                        "frozen_checkpoint_count",
                    )
                ],
                [
                    request["model"]["weights"]["sha256"],
                    request["model"]["parameters_sha256"],
                    0,
                    1,
                ],
            )
            with self.assertRaisesRegex(ValueError, "source roster"):
                runner.load_model(request, {"other-training"})
            request["model"]["weights"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "registered bytes"):
                runner.load_model(request, {"training"})

    def test_exclusion_manifest_and_exposure_registry_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            request = request_fixture(Path(directory))
            materials = Path(request["config"]["material_root"])
            catalog = strict_json(runner.read_pin(request["catalog"], materials))
            self.assertEqual(
                runner.exclusions(request, catalog, materials),
                ({"training", "tuning"}, {"training"}),
            )
            bad = copy.deepcopy(request)
            bad["excluded_source_groups"] = ["training"]
            with self.assertRaisesRegex(ValueError, "complete frozen"):
                runner.exclusions(bad, catalog, materials)
            bad = copy.deepcopy(request)
            bad["registry_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "different registry"):
                runner.exclusions(bad, catalog, materials)
            ledger = strict_json((materials / "exposure.json").read_bytes())
            ledger["quarantined_source_groups"] = ["unknown-source"]
            write_json(materials / "wrong-exposure.json", ledger)
            bad = copy.deepcopy(request)
            bad["exposure_ledgers"] = [
                binding(materials / "wrong-exposure.json", materials)
            ]
            with self.assertRaisesRegex(ValueError, "unknown source"):
                runner.exclusions(bad, catalog, materials)

    def test_freeze_pins_both_arms_before_any_actor_and_source_mutation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = request_fixture(root)
            with patch.object(runner, "EpisodeHost") as host:
                plan, jobs = runner.freeze(request, root / "frozen")
                host.assert_not_called()
            self.assertEqual(
                (len(plan["episodes"]), len(jobs), len(plan["paired_run_order"])),
                (12, 6, 6),
            )
            for pair in jobs:
                self.assertEqual(
                    {j["expected"]["candidate_memory_profile"]["mode"] for j in pair},
                    {"current_only", "bounded"},
                )
                self.assertEqual(
                    {j["expected"]["control_plan_sha256"] for j in pair},
                    {plan["control_plan"]["sha256"]},
                )
            request["source_pins"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "registered bytes"):
                runner.verify_sources(request)

    def test_isolation_refusal_keeps_all_planned_failures_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = request_fixture(root)
            write_json(root / "request.json", request)
            generate = runner.generate

            def after_workers(*args):
                self.assertTrue(InlinePool.exited)
                return generate(*args)

            with (
                patch.object(runner, "ProcessPoolExecutor", InlinePool),
                patch.object(runner, "EpisodeHost") as host,
                patch.object(runner, "generate", side_effect=after_workers),
            ):
                host.return_value.run.side_effect = RuntimeError(
                    "Injected isolation refusal; no actor launched"
                )
                receipt = runner.run(root / "request.json", root / "run")
            self.assertEqual(
                (receipt["status"], receipt["terminal_status_counts"], host.call_count),
                ("Completed", {"Failed": 12}, 12),
            )
            report = strict_json((root / "run/REPORT.json").read_bytes())
            manifest = strict_json((root / "run/EVIDENCE.json").read_bytes())
            self.assertEqual(
                (report["planned_episodes"], len(manifest["episodes"])), (12, 12)
            )
            self.assertTrue(all(r["retry_of"] is None for r in receipt["attempts"]))
            self.assertTrue(
                all(
                    e["result"] is None and e["attempt"] is not None
                    for e in manifest["episodes"]
                )
            )
            self.assertTrue(
                all(e["unconditional_success"] is None for e in report["episodes"])
            )
            self.assertEqual(
                len((root / "run/runner.jsonl").read_text().splitlines()), 24
            )

    def test_post_episode_ocr_drift_with_later_restore_blocks_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = request_fixture(root)
            write_json(root / "request.json", request)
            language = Path(request["config"]["tessdata_dir"]) / "eng.traineddata"
            original = language.read_bytes()

            class DriftHost:
                def __init__(self, config, case, profile, output):
                    self.output = output
                    self.assert_plan = output.parents[1] / "PLAN.json"

                def run(self):
                    if not self.assert_plan.is_file():
                        raise AssertionError("Actor started before PLAN")
                    write_json(
                        self.output / "result.json", {"terminal_status": "Completed"}
                    )
                    language.write_bytes(b"changed after host completion")
                    return {"terminal_status": "Completed"}

            InlinePool.after_pair = lambda: language.write_bytes(original)
            try:
                with (
                    patch.object(runner, "ProcessPoolExecutor", InlinePool),
                    patch.object(runner, "EpisodeHost", DriftHost),
                    patch.object(runner, "generate") as score,
                ):
                    receipt = runner.run(root / "request.json", root / "run")
                    score.assert_not_called()
            finally:
                InlinePool.after_pair = None
            self.assertEqual(
                (receipt["status"], language.read_bytes()), ("Failed", original)
            )
            self.assertIn("comparison invariant failed", receipt["error"]["message"])
            self.assertTrue(
                any(
                    r.get("comparison_invariant_failure") == "after_episode"
                    for r in receipt["attempts"]
                )
            )
            manifest = strict_json((root / "run/EVIDENCE.json").read_bytes())
            self.assertEqual(len(manifest["episodes"]), 12)
            self.assertFalse((root / "run/REPORT.json").exists())
            self.assertTrue(any(e["result"] is not None for e in manifest["episodes"]))

    def test_evidence_preserves_actor_digest_and_malformed_trajectory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trajectory = root / "episodes/op/trajectory.json"
            original = {
                "path": "candidate-audit-00.json",
                "sha256": "f" * 64,
                "bytes": 100,
            }
            write_json(
                trajectory, {"steps": [{"step": 0, "candidate_audit": original}]}
            )
            item = runner.evidence(root, {"original_operation_id": "op"})
            self.assertEqual(
                item["audits"],
                [
                    {
                        **original,
                        "path": "episodes/op/actor-output/candidate-audit-00.json",
                    }
                ],
            )
            trajectory.write_bytes(
                json_bytes(
                    {
                        "steps": [
                            {
                                "step": 0,
                                "candidate_audit": {**original, "path": "../wrong"},
                            }
                        ]
                    }
                )
            )
            item = runner.evidence(root, {"original_operation_id": "op"})
            self.assertIn("collection_error", item)
            self.assertIsNotNone(item["trajectory"])


if __name__ == "__main__":
    unittest.main()
