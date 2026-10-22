"""Runner execution with real tiny Heads and zero features; no semantic evidence."""

from contextlib import ExitStack, redirect_stdout
import copy
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

from cell_head_training import load_head_artifact
from feature_bundle import FeatureIdentityV1
import multimodal_cohorts as data
import multimodal_features as bank
import multimodal_research as research
from prediction_ledger import (LedgerIdentityV1, canonical, load_prediction_ledger, sha)


def execution_fixture(root):
    """Retain the real 64-block test shape without images or a model download."""
    counts = {"train": 4, "dev": 4, "calibration": 4, "test": 128}
    sources = [{"image_id": i, "caption_id": 1000 + i, "file_name": f"{i}.jpg",
                "image_sha256": sha(f"image-{i}".encode()), "text": f"fixture caption {i}",
                "text_sha256": sha(f"fixture caption {i}".encode())}
               for i in range(sum(counts.values()))]
    with patch.object(data, "SPLIT_IMAGES", counts):
        rows = data.build_rows({"images": sources})
    cohort_path, bank_path = root / "cohorts", root / "bank"
    cohort_path.mkdir()
    bank_path.mkdir()
    dataset = {"schema": "execution-fixture-only", "semantic_quality_evidence": False}
    raw = canonical(dataset) + b"\n"
    (cohort_path / "manifest.json").write_bytes(raw)
    data_hash = sha(raw)
    features = {key: torch.zeros((len(sources), 2)) for key in ("text", "image")}
    stream = io.BytesIO()
    np.savez(stream, **{key: value.numpy() for key, value in features.items()})
    payload = stream.getvalue()
    (bank_path / "features.npz").write_bytes(payload)
    receipts = {}
    for channel in features:
        name = channel + "-receipts.json"
        raw_receipt = canonical({"execution_fixture": True, "model_calls": 0})
        (bank_path / name).write_bytes(raw_receipt)
        receipts[channel] = {"file": name, "sha256": sha(raw_receipt)}
    plan = {"dataset_manifest_sha256": data_hash, "code_file_sha256": bank.bank_code_identity()}
    manifest = {"schema": "hepta.multimodal-feature-bank.v1", "plan": plan,
        "plan_sha256": sha(canonical(plan)), "shape": [len(sources), 2],
        "image_ids": [item["image_id"] for item in sources],
        "base_identity": asdict(FeatureIdentityV1("a" * 64, "b" * 40, "c" * 64)),
        "provenance": {channel: [sha(f"{channel}:{i}".encode()) for i in range(len(sources))]
                       for channel in features},
        "features_file": "features.npz", "features_sha256": sha(payload),
        "feature_tensor_sha256": bank.bank_tensor_digest(features), "receipts": receipts,
        "encoder": {"execution_fixture": True}, "runtime": {"execution_fixture": True},
        "authority": "DENY_ALL", "production_activation_allowed": False}
    raw_manifest = canonical(manifest) + b"\n"
    (bank_path / "manifest.json").write_bytes(raw_manifest)
    return {"root": root, "cohorts": cohort_path, "bank": bank_path,
            "rows": rows, "dataset": dataset, "manifest": manifest, "features": features,
            "data_sha256": data_hash, "bank_sha256": sha(raw_manifest)}


def run_fixture(fixture, name, *, screen_override=None):
    target, events = fixture["root"] / name, []
    real_make_plan = research.make_plan
    real_select = research.select_head
    real_pair = research.pair_features
    real_train = research.train_cell_head

    def fixture_cohorts(directory, *, expected_manifest_sha256):
        if (Path(directory) != fixture["cohorts"]
                or expected_manifest_sha256 != fixture["data_sha256"]
                or sha((Path(directory) / "manifest.json").read_bytes()) != expected_manifest_sha256):
            raise AssertionError("fixture data identity changed")
        events.append(("load_cohorts",))
        return copy.deepcopy(fixture["dataset"]), copy.deepcopy(fixture["rows"])

    def small_plan(**kwargs):
        plan = real_make_plan(**kwargs)
        plan["head_latency"] = {"warmup_calls": 1, "measured_calls": 2, "batch_size": 1}
        plan["test_fixture"] = "execution-only zero features, never semantic quality evidence"
        return plan

    def guarded_training(*args, **kwargs):
        if not (target / "plan.json").is_file() or any(event[0] == "test_view" for event in events):
            raise AssertionError("training crossed preregistration/test boundary")
        if set(args[2]) != {"development"}:
            raise AssertionError("training received a test holdout")
        events.append(("train", kwargs["config"].mode, kwargs["config"].steps))
        return real_train(*args, **kwargs)

    def guarded_select(*args, **kwargs):
        value = real_select(*args, **kwargs)
        events.append(("selected", kwargs["mode"]))
        return value

    def guarded_pair(rows, *args, **kwargs):
        if rows[0]["split"] == "test":
            if sum(event[0] == "selected" for event in events) != 6:
                raise AssertionError("test features accessed before all model selection completed")
            events.append(("test_view", kwargs["arm"]))
        return real_pair(rows, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(research, "STEPS", (1, 2)))
        stack.enter_context(patch.object(research, "make_plan", side_effect=small_plan))
        stack.enter_context(patch.object(research, "load_cohorts", side_effect=fixture_cohorts))
        stack.enter_context(patch.object(research, "train_cell_head", side_effect=guarded_training))
        stack.enter_context(patch.object(research, "select_head", side_effect=guarded_select))
        stack.enter_context(patch.object(research, "pair_features", side_effect=guarded_pair))
        encoder = stack.enter_context(patch.object(bank, "FrozenRealEncoder",
            side_effect=AssertionError("Head runner instantiated an Encoder")))
        if screen_override is not None:
            stack.enter_context(patch.object(research, "assess_multimodal_research",
                                            side_effect=screen_override))
        stack.enter_context(redirect_stdout(io.StringIO()))
        report = research.run_research(cohorts=fixture["cohorts"], bank=fixture["bank"],
            expected_bank_sha256=fixture["bank_sha256"], output=target, threads=1)
        encoder.assert_not_called()
    return report, target, events


class MultimodalResearchSelectionTests(unittest.TestCase):
    def test_selection_uses_only_development_raw_nll_then_fewer_steps(self):
        plan = research.make_plan(data_sha256="a" * 64, bank_sha256="b" * 64, threads=1)
        plan["step_candidates"] = [9, 3, 1]
        train, calibration, development = object(), object(), object()
        results, calls = {}, []
        for steps, raw, train_nll, calibrated in ((9, .8, .01, .001),
                                                (3, .2, .02, .002), (1, .2, 10, 20)):
            results[steps] = SimpleNamespace(report={
                "splits": {"development": {"metrics": {"trained": {"nll": raw},
                    "calibrated": {"nll": calibrated}}},
                    "train": {"metrics": {"trained": {"nll": train_nll}}},
                    "calibration": {"metrics": {"calibrated": {"nll": calibrated}}}},
                "trained_tensor_sha256": sha(str(steps).encode())})

        def fit(got_train, got_calibration, holdouts, *, config):
            self.assertIs(got_train, train)
            self.assertIs(got_calibration, calibration)
            self.assertEqual(holdouts, {"development": development})
            self.assertEqual(config.mode, "gated")
            calls.append(config.steps)
            return results[config.steps]

        with patch.object(research, "train_cell_head", side_effect=fit), redirect_stdout(io.StringIO()):
            selected, record = research.select_head(train, calibration, development,
                                                    mode="gated", plan=plan)
        self.assertIs(selected, results[1])
        self.assertEqual(calls, [9, 3, 1])
        self.assertEqual(record["selected_steps"], 1)
        self.assertEqual(record["total_optimizer_steps_including_selection"], 13)
        self.assertFalse(record["selection_used_test"])
        self.assertFalse(record["selection_used_calibration_metrics"])

    def test_minority_selection_is_repeatable_order_independent_and_exact(self):
        rows = [{"row_id": f"row-{i}", "label": i % 2} for i in range(256)]
        plan = research.make_plan(data_sha256="a" * 64, bank_sha256="b" * 64, threads=1)
        indices = research.minority_indices(rows, plan)
        self.assertEqual(indices, research.minority_indices(rows, plan))
        chosen = [rows[i] for i in indices]
        self.assertEqual((sum(r["label"] for r in chosen), len(chosen)), (32, 160))
        self.assertEqual({r["row_id"] for r in chosen if not r["label"]},
                         {r["row_id"] for r in rows if not r["label"]})
        expected_positive = sorted((r for r in rows if r["label"]),
            key=lambda row: sha(f'20261022:{row["row_id"]}'.encode()))[:32]
        self.assertEqual({r["row_id"] for r in chosen if r["label"]},
                         {r["row_id"] for r in expected_positive})
        reversed_rows = list(reversed(rows))
        self.assertEqual({r["row_id"] for r in chosen},
            {reversed_rows[i]["row_id"] for i in research.minority_indices(reversed_rows, plan)})
        for bad in (rows[1:], [r for r in rows if not r["label"] or r["row_id"] == "row-1"]):
            with self.assertRaisesRegex(ValueError, "counts"):
                research.minority_indices(bad, plan)


class MultimodalResearchExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.fixture = execution_fixture(Path(cls.temporary.name))
        cls.report, cls.output, cls.events = run_fixture(cls.fixture, "complete")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()
        torch.set_num_threads(cls.previous_threads)

    def test_complete_execution_is_distinct_from_failed_quality_screen(self):
        report = self.report
        self.assertEqual(report["engineering_status"], "COMPLETE")
        self.assertFalse(report["quality_qualified"])
        self.assertFalse(report["production_activation_allowed"])
        self.assertEqual(report["authority"], "DENY_ALL")
        self.assertEqual(report["encoder_calls_during_head_training"], 0)
        self.assertEqual(report["encoder_calls_during_head_serving"], 0)
        self.assertEqual(sum(event[0] == "train" for event in self.events), 12)
        self.assertEqual(sum(event[0] == "selected" for event in self.events), 6)
        self.assertEqual(sum(event[0] == "load_cohorts" for event in self.events), 2)
        for key in (f"{arm}-{mode}" for arm in research.ARMS for mode in research.MODES):
            self.assertEqual(report["ledgers"][key]["metrics"]["balanced_accuracy"], .5)
            self.assertFalse(report["arm_screens"][key]["checks"]["balanced_accuracy"])
        # A perfectly repeatable pipeline on uninformative fixtures is not a
        # semantic result, even when one class has 100% recall.
        self.assertTrue(report["minority_primary_recall_check"])
        self.assertEqual(report["multimodal_screens"]["gated"]["status"], "FAIL_RESEARCH_SCREEN")

    def test_all_twenty_ledgers_reload_with_exact_plan_data_and_head_bindings(self):
        expected = {f"{arm}-{mode}{suffix}" for arm in research.ARMS for mode in research.MODES
                    for suffix in ("", "-minority")}
        expected.update(f"text_image-{mode}-{intervention}" for mode in research.MODES
                        for intervention in (*research.INTERVENTIONS, "shuffled_relabelled"))
        self.assertEqual(set(self.report["ledgers"]), expected)
        plan = json.loads((self.output / "plan.json").read_bytes())
        plan_hash = sha(canonical(plan))
        self.assertEqual(plan_hash, self.report["plan_sha256"])
        for name, record in self.report["ledgers"].items():
            directory = self.output / record["directory"]
            manifest = json.loads((directory / "manifest.json").read_bytes())
            identity = LedgerIdentityV1(**manifest["metadata"]["identity"])
            ledger = load_prediction_ledger(directory, expected_manifest_sha256=record["manifest_sha256"],
                                             expected_identity=identity)
            human_rows = json.loads((directory / "rows.json").read_bytes())
            self.assertEqual(human_rows, ledger.rows())
            self.assertEqual(ledger.metrics(), record["metrics"])
            self.assertEqual(identity.plan_sha256, plan_hash)
            self.assertEqual(identity.data_sha256, self.fixture["data_sha256"])
            artifact = self.report["head_artifacts"][human_rows[0]["arm"]]
            head_manifest = json.loads((self.output / artifact["directory"] / "manifest.json").read_bytes())
            self.assertEqual(identity.head_sha256, head_manifest["report"]["trained_tensor_sha256"])
            self.assertEqual(len(human_rows), 160 if name.endswith("-minority") else 256)
            self.assertTrue(record["round_trip_verified"])
        actual_files = {str(path.relative_to(self.output)) for path in self.output.rglob("*")
                        if path.is_file() and path.name != "report.json"}
        self.assertEqual(set(self.report["artifact_sha256"]), actual_files)
        for name, digest in self.report["artifact_sha256"].items():
            self.assertEqual(sha((self.output / name).read_bytes()), digest)

    def test_saved_real_heads_are_frozen_and_reproduce_paired_raw_logits(self):
        for key, artifact in self.report["head_artifacts"].items():
            arm = key.rsplit("-", 1)[0]
            bundle = bank.pair_features(self.fixture["rows"]["test"], self.fixture["manifest"],
                                        self.fixture["features"], arm=arm)
            loaded = load_head_artifact(self.output / artifact["directory"],
                expected_manifest_sha256=artifact["manifest_sha256"], expected_identity=bundle.identity)
            self.assertTrue(all(not p.requires_grad and p.grad is None for p in loaded._head.parameters()))
            self.assertNotEqual(loaded.report["initial_tensor_sha256"], loaded.report["trained_tensor_sha256"])
            rows = json.loads((self.output / self.report["ledgers"][key]["directory"] / "rows.json").read_bytes())
            prediction = loaded.predict_task(bundle)
            self.assertEqual(prediction["task_logits"].tolist(), [row["logits"] for row in rows])
            self.assertEqual({row["temperature"] for row in rows}, {prediction["temperature"]})

    def test_primary_gated_is_fixed_even_if_linear_test_screen_passes(self):
        def contradictory_screens(joint, **_kwargs):
            passed = joint.rows()[0]["arm"] == "text_image-linear"
            return {"status": "PASS_RESEARCH_SCREEN" if passed else "FAIL_RESEARCH_SCREEN",
                    "multimodal_gain_research_screen_passed": passed}

        # Override only screen outputs to test the reporting branch; these
        # forced values are not a model-quality experiment or retained evidence.
        report, _, _ = run_fixture(self.fixture, "fixed-primary", screen_override=contradictory_screens)
        self.assertTrue(report["multimodal_screens"]["linear"]["multimodal_gain_research_screen_passed"])
        self.assertFalse(report["multimodal_screens"]["gated"]["multimodal_gain_research_screen_passed"])
        self.assertTrue(report["minority_primary_recall_check"])
        self.assertFalse(report["quality_qualified"])


if __name__ == "__main__":
    unittest.main()
