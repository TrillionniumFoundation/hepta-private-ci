"""Actual optimizer/serialization and capture-boundary controls; no real labels."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from . import dual_runtime as runtime
from . import r2_action_value as av
from .test_transition_capture import SyntheticBackend
from .transition_capture import DevelopmentSource, TransitionCapture, file_identity
from .transition_capture_read import read_capture


class ActionValueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.counter = 0

    def capture(self, *, split="train", actions=("text", "draft", "stop"), error=None,
                cluster=None, color=None, controller=None, backend=None, **kwargs):
        number = self.counter
        self.counter += 1
        image = self.root / f"input-{number}.png"
        Image.new("RGB", (2, 2), color or (number + 1, 20, 30)).save(image)
        source = DevelopmentSource(split, f"source-{number}", file_identity(image)["sha256"],
                                  hashlib.sha256(b"Describe shapes.").hexdigest(), "a" * 64)
        request = runtime.Request(source.source_id, str(image), source.image_sha256, "Describe shapes.")
        directory = self.root / f"capture-{number}"
        backend = backend or SyntheticBackend(error)
        runtime.run(request, backend, controller or runtime.FixedSchedule(actions), directory,
                    recorder=TransitionCapture(source), **kwargs)
        parsed = read_capture(directory)
        entry = {"capture_id": f"capture-{number}", "directory": directory.name,
                 "summary_sha256": file_identity(directory / "transition_capture/SUMMARY.json")["sha256"],
                 "declared_source": asdict(source), "split": split,
                 "source_cluster_id": cluster or f"cluster-{number}"}
        return entry, parsed, backend

    def bundle(self, captures):
        rows = []
        for entry, parsed, _ in captures:
            for t in parsed["transitions"]:
                if t.get("choice") not in runtime.ACTIONS:
                    continue
                after = -1.0 if "failure_state" in t else 0.35
                if t.get("actual_after_state", {}).get("episode_status_so_far") == "abstained":
                    after = 0.0
                rows.append({"capture_id": entry["capture_id"], "step": t["step"],
                             "transition_sha256": av.digest(t), "utility_before": 0.0, "utility_after": after})
        manifest = {"schema": "hepta.development-action-labels.v1", "evaluator_id": "synthetic-control-only",
                    "evaluator_source_sha256": "b" * 64, "rubric_sha256": "c" * 64, "rows": rows}
        return {"schema": "hepta.r2.action-value-training.v1", "purpose": "synthetic_control",
                "config": {"seed": 17, "updates": 160, "learning_rate": 0.05, "momentum": 0.5, "l2": 0.001,
                           "maximum_cpu_seconds": 30, "maximum_wall_seconds": 60, "failure_utility": -1.0,
                           "cpu_tariff": 0.02, "wall_tariff": 0.001,
                           "service_tariffs": {action: 0.003 for action in runtime.ACTIONS}},
                "roster": deepcopy([c[0] for c in captures]), "label_manifest": manifest, "labels_sha256": av.digest(manifest)}

    def fit(self, bundle):
        output = self.root / f"fit-{self.counter}"
        self.counter += 1
        report = av.fit(bundle, output, bundle_sha256=av.digest(bundle), base_directory=self.root)
        return output, report

    def test_actual_updates_are_reproducible_and_leave_captures_unchanged(self):
        capture = self.capture()
        bundle = self.bundle([capture])
        calls = deepcopy(capture[2].calls)
        before = file_identity(self.root / capture[0]["directory"] / "transition_capture/SUMMARY.json")
        first, a = self.fit(bundle)
        second, b = self.fit(bundle)
        self.assertEqual((a["status"], b["status"]), ("completed", "completed"))
        ma, mb = (json.loads((p / "checkpoint.json").read_bytes()) for p in (first, second))
        self.assertEqual(ma, mb)
        self.assertNotEqual(ma["initial_parameter_sha256"], ma["parameter_sha256"])
        self.assertEqual(ma["optimizer"]["updates"], 160)
        self.assertTrue(np.any(np.asarray(ma["optimizer"]["velocity"])))
        self.assertLess(a["train_mse_after"], a["loss_before_updates"][0] / 100)
        self.assertEqual(calls, capture[2].calls)
        self.assertEqual(before, file_identity(self.root / capture[0]["directory"] / "transition_capture/SUMMARY.json"))
        self.assertFalse(a["custody_authenticated"])
        self.assertTrue(a["no_update"])

    def test_new_process_loading_reproduces_prediction_and_rejects_bad_pins(self):
        capture = self.capture()
        out, report = self.fit(self.bundle([capture]))
        model = av.ActionValue(out / "checkpoint.json", report["checkpoint"]["sha256"], report["fit_receipt"]["sha256"])
        view = capture[1]["transitions"][0]["before_view"]
        query = self.root / "query.json"
        query.write_bytes(av.canonical({"view": view, "action": "text"}))
        command = [sys.executable, "-m", av.__name__, "predict", "--checkpoint", str(out / "checkpoint.json"),
                   "--checkpoint-sha256", report["checkpoint"]["sha256"],
                   "--fit-sha256", report["fit_receipt"]["sha256"], "--query", str(query)]
        child = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout), {"predicted_one_step_net_gain": model.predict(view, "text"),
                                                 "independent_observation": False, "no_update": True})
        command[7] = "0" * 64
        rejected = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(rejected.returncode, 0)
        with self.assertRaisesRegex(ValueError, "No training observation"):
            model.predict(view, "refine")
        with self.assertRaisesRegex(ValueError, "Hidden or missing"):
            model.predict({**view, "reference_answer": "not allowed"}, "text")

    def test_failed_cancelled_and_timeout_actions_remain_trainable_negative_observations(self):
        captures = [self.capture(actions=("draft", "stop"), error=e) for e in
                    (ValueError("partial failure"), TimeoutError("partial timeout"), KeyboardInterrupt("cancelled"))]
        out, report = self.fit(self.bundle(captures))
        self.assertEqual(report["status"], "completed")
        self.assertEqual([x["status"] for x in report["retained_captures"]], ["failed", "timeout", "cancelled"])
        for c in captures:
            self.assertNotIn("actual_after_state", c[1]["transitions"][0])
            self.assertEqual((self.root / c[0]["directory"] / "00-draft.png").read_bytes(), b"partial synthetic output")
        self.assertTrue(all(r["original_cost"]["wall_seconds"] > 0 for r in report["retained_captures"]))
        model = av.ActionValue(out / "checkpoint.json", report["checkpoint"]["sha256"], report["fit_receipt"]["sha256"])
        self.assertLess(model.predict(captures[0][1]["transitions"][0]["before_view"], "draft"), -0.9)

    def test_missing_failure_label_and_extra_unexecuted_label_reject_whole_fit(self):
        failed = self.capture(actions=("draft", "stop"), error=ValueError("failed"))
        for extra in (False, True):
            bundle = self.bundle([failed])
            rows = bundle["label_manifest"]["rows"]
            if extra:
                rows.append({**rows[0], "step": 30})
            else:
                rows.clear()
            bundle["labels_sha256"] = av.digest(bundle["label_manifest"])
            out, report = self.fit(bundle)
            self.assertEqual(report["status"], "failed")
            self.assertFalse((out / "checkpoint.json").exists())
            self.assertGreater(report["metering"]["wall_seconds"], 0)
            self.assertEqual(report["retained_captures"][0]["status"], "failed")

    def test_unexecuted_intent_is_retained_without_fabricating_an_action_label(self):
        class BadController:
            def choose(self, view):
                raise RuntimeError("actual controller failure")
        failed = self.capture(controller=BadController())
        out, report = self.fit(self.bundle([self.capture(), failed]))
        self.assertEqual(report["status"], "completed")
        retained = report["retained_captures"][1]
        self.assertEqual(retained["status"], "failed")
        self.assertEqual(retained["unlabelled_intents"][0]["reason"], "no_observed_action_terminal")
        self.assertNotIn("choice", retained["unlabelled_intents"][0]["transition"])

    def test_test_split_real_label_claim_and_source_overlap_are_rejected(self):
        captured = self.capture(color=(8, 8, 8))
        test = self.bundle([captured])
        test["roster"][0]["split"] = "test"
        real_claim = self.bundle([captured])
        real_claim["purpose"] = "development"
        overlap = self.bundle([captured, self.capture(split="development", color=(8, 8, 8))])
        for bundle in (test, real_claim, overlap):
            _, report = self.fit(bundle)
            self.assertEqual(report["status"], "failed")

    def test_development_labels_are_not_used_for_parameter_updates(self):
        captures = [self.capture(), self.capture(split="development")]
        first = self.bundle(captures)
        second = deepcopy(first)
        for row in second["label_manifest"]["rows"]:
            if row["capture_id"] == captures[1][0]["capture_id"]:
                row["utility_after"] = -0.7
        second["labels_sha256"] = av.digest(second["label_manifest"])
        pa, a = self.fit(first)
        pb, b = self.fit(second)
        self.assertEqual((a["status"], b["status"]), ("completed", "completed"))
        self.assertEqual(json.loads((pa / "checkpoint.json").read_bytes())["parameters"],
                         json.loads((pb / "checkpoint.json").read_bytes())["parameters"])
        self.assertNotEqual(a["development_mse"], b["development_mse"])

    def test_budget_failure_preserves_cost_and_partial_state_without_overwrite(self):
        bundle = self.bundle([self.capture()])
        bundle["config"]["maximum_wall_seconds"] = 1e-12
        out, report = self.fit(bundle)
        self.assertEqual(report["status"], "timeout")
        self.assertEqual(report["updates_completed"], 0)
        self.assertTrue((out / "partial_state.json").is_file())
        self.assertFalse((out / "checkpoint.json").exists())
        self.assertGreater(report["metering"]["wall_seconds"], 0)
        with self.assertRaises(FileExistsError):
            av.fit(bundle, out, bundle_sha256=av.digest(bundle), base_directory=self.root)

    def test_checkpoint_that_finishes_after_budget_is_retained_but_refused(self):
        bundle = self.bundle([self.capture()])
        original_write, real_time, offset = av.write_new, av.time, [0.0]
        clock = SimpleNamespace(process_time=real_time.process_time,
                                perf_counter=lambda: real_time.perf_counter() + offset[0])
        def write(path, value):
            result = original_write(path, value)
            if Path(path).name == "checkpoint.json":
                offset[0] = 1000.0  # Synthetic budget fault; not a physical write-time claim.
            return result
        with patch.object(av, "write_new", write), patch.object(av, "time", clock):
            out, report = self.fit(bundle)
        self.assertEqual(report["status"], "timeout")
        self.assertTrue((out / "checkpoint.json").is_file())
        with self.assertRaisesRegex(ValueError, "Fit did not complete"):
            av.ActionValue(out / "checkpoint.json", report["checkpoint"]["sha256"], report["fit_receipt"]["sha256"])
        receipt = json.loads((out / "FIT.json").read_bytes())
        receipt["status"] = "completed"
        (out / "FIT.json").write_bytes(av.canonical(receipt))
        with self.assertRaisesRegex(ValueError, "Fit receipt bytes changed"):
            av.ActionValue(out / "checkpoint.json", report["checkpoint"]["sha256"], report["fit_receipt"]["sha256"])

    def test_untrained_development_action_is_unknown_instead_of_a_zero_prediction(self):
        bundle = self.bundle([self.capture(actions=("text", "stop")),
                              self.capture(split="development", actions=("draft", "stop"))])
        _, report = self.fit(bundle)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["development_unsupported_actions"], ["draft"])
        self.assertIsNone(report["development_mse"])

    def test_source_drift_and_changed_capture_are_not_trainable_candidates(self):
        capture = self.capture()
        bundle = self.bundle([capture])
        pins = av.source_pins()
        with patch.object(av, "source_pins", side_effect=[pins, {**pins, "dual_runtime.py": "0" * 64}]):
            out, report = self.fit(bundle)
        self.assertEqual(report["status"], "failed")
        self.assertTrue((out / "partial_state.json").is_file())
        source = self.root / capture[0]["directory"] / "report.json"
        source.write_bytes(source.read_bytes() + b" ")
        _, report = self.fit(bundle)
        self.assertEqual(report["status"], "failed")

    def test_loader_rejects_failed_fit_and_rebound_wrong_source(self):
        out, report = self.fit(self.bundle([self.capture()]))
        bad = self.root / "bad-model"
        shutil.copytree(out, bad)
        receipt = json.loads((bad / "FIT.json").read_bytes())
        receipt["status"] = "timeout"
        (bad / "FIT.json").write_bytes(av.canonical(receipt))
        with self.assertRaisesRegex(ValueError, "Fit did not complete"):
            av.ActionValue(bad / "checkpoint.json", report["checkpoint"]["sha256"], file_identity(bad / "FIT.json")["sha256"])
        model = json.loads((bad / "checkpoint.json").read_bytes())
        model["source_pins"]["dual_runtime.py"] = "0" * 64
        raw = av.canonical(model)
        pin = hashlib.sha256(raw).hexdigest()
        (bad / "checkpoint.json").write_bytes(raw)
        receipt.update(status="completed", checkpoint={"sha256": pin, "bytes": len(raw)})
        (bad / "FIT.json").write_bytes(av.canonical(receipt))
        with self.assertRaisesRegex(ValueError, "different execution source"):
            av.ActionValue(bad / "checkpoint.json", pin, file_identity(bad / "FIT.json")["sha256"])

    def test_finite_extreme_costs_produce_failed_receipt_instead_of_unserializable_infinity(self):
        bundle = self.bundle([self.capture()])
        bundle["config"]["service_tariffs"] = {action: 1e200 for action in runtime.ACTIONS}
        bundle["config"]["learning_rate"] = 1e-300
        out, report = self.fit(bundle)
        self.assertEqual(report["status"], "failed")
        self.assertIsNotNone(report["fit_receipt"])
        self.assertGreater(report["metering"]["wall_seconds"], 0)
        self.assertTrue((out / "partial_state.json").is_file())
        self.assertFalse((out / "checkpoint.json").exists())
        json.loads((out / "FIT.json").read_bytes(), parse_constant=lambda value: self.fail(value))

    def test_episode_timeout_after_successful_action_cannot_receive_a_positive_label(self):
        real_time, offset = runtime.time, [0.0]
        clock = SimpleNamespace(process_time=real_time.process_time,
                                perf_counter=lambda: real_time.perf_counter() + offset[0])
        class SlowBackend(SyntheticBackend):
            def describe(self, *args):
                result = super().describe(*args)
                offset[0] = 1000.0  # Deterministic deadline fault, not measured model latency.
                return result
        with patch.object(runtime, "time", clock):
            captured = self.capture(actions=("text", "stop"), backend=SlowBackend(), deadline_seconds=100)
        self.assertEqual(captured[1]["report"]["status"], "timeout")
        self.assertIn("actual_after_state", captured[1]["transitions"][0])
        bundle = self.bundle([captured])
        _, report = self.fit(bundle)
        self.assertEqual(report["status"], "failed")
        self.assertIn("Failure utility changed", report["error"]["message"])
        bundle["label_manifest"]["rows"][0]["utility_after"] = -1.0
        bundle["labels_sha256"] = av.digest(bundle["label_manifest"])
        out, report = self.fit(bundle)
        self.assertEqual(report["status"], "completed")
        row = json.loads((out / "TRAINING_ROWS.json").read_bytes())[0]
        self.assertEqual((row["action_status"], row["outcome_status"]), ("ok", "timeout"))
        class FinalIdentityFailure(SyntheticBackend):
            def identity(self):
                if any(call[0] == "identity" for call in self.calls):
                    raise RuntimeError("Actual final identity failure")
                return super().identity()
        # The existing reader already refuses missing inventory when a final
        # identity failure leaves generated files. Keep that refusal intact.
        with self.assertRaisesRegex(ValueError, "artifact was deleted/changed"):
            self.capture(backend=FinalIdentityFailure())
        final_failure = self.capture(actions=("stop",), backend=FinalIdentityFailure())
        self.assertEqual(final_failure[1]["report"]["status"], "failed")
        _, report = self.fit(self.bundle([final_failure]))
        self.assertEqual(report["status"], "failed")
        self.assertIn("Failure utility changed", report["error"]["message"])

    def test_finite_parameters_cannot_return_an_infinite_prediction(self):
        capture = self.capture()
        out, report = self.fit(self.bundle([capture]))
        model = json.loads((out / "checkpoint.json").read_bytes())
        view = capture[1]["transitions"][0]["before_view"]
        weights = np.asarray(model["parameters"])
        weights[runtime.ACTIONS.index("text")] = np.copysign(1e308, av.features(view))
        model.update(parameters=weights.tolist(), parameter_sha256=av.parameter_hash(weights))
        raw = av.canonical(model)
        (out / "checkpoint.json").write_bytes(raw)
        receipt = json.loads((out / "FIT.json").read_bytes())
        receipt["checkpoint"] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        (out / "FIT.json").write_bytes(av.canonical(receipt))
        predictor = av.ActionValue(out / "checkpoint.json", receipt["checkpoint"]["sha256"], file_identity(out / "FIT.json")["sha256"])
        with self.assertRaises((ValueError, FloatingPointError)):
            predictor.predict(view, "text")

    def test_failed_final_receipt_write_never_returns_a_completed_fit_identity(self):
        original = av.write_new
        for error, status in ((OSError("receipt storage unavailable"), "failed"),
                              (KeyboardInterrupt("cancelled during final receipt"), "cancelled")):
            with self.subTest(status=status):
                def write(path, value):
                    if Path(path).name == "FIT.json":
                        raise error
                    return original(path, value)
                with patch.object(av, "write_new", write):
                    out, report = self.fit(self.bundle([self.capture()]))
                self.assertEqual(report["status"], status)
                self.assertIsNone(report["fit_receipt"])
                self.assertTrue((out / "checkpoint.json").is_file())
                self.assertFalse((out / "FIT.json").exists())

    def test_partial_state_cancellation_preserves_the_original_failure_and_cost(self):
        original = av.write_new
        bundle = self.bundle([self.capture()])
        bundle["config"]["maximum_wall_seconds"] = 1e-12
        def write(path, value):
            if Path(path).name == "partial_state.json":
                raise KeyboardInterrupt("cancelled during partial save")
            return original(path, value)
        with patch.object(av, "write_new", write):
            out, report = self.fit(bundle)
        self.assertEqual((report["status"], report["error"]["type"], report["partial_state_write_error"]["type"]),
                         ("cancelled", "TimeoutError", "KeyboardInterrupt"))
        self.assertIsNotNone(report["fit_receipt"])
        self.assertGreater(report["metering"]["wall_seconds"], 0)
        self.assertEqual(json.loads((out / "FIT.json").read_bytes())["status"], "cancelled")

    def test_cli_sigterm_preserves_cancelled_fit_receipt(self):
        if sys.platform == "win32":
            self.skipTest("Windows process SIGTERM does not deliver the POSIX Python signal handler")
        bundle = self.bundle([self.capture()])
        bundle["config"]["updates"] = 10000
        path, output = self.root / "bundle.json", self.root / "signalled-fit"
        path.write_bytes(av.canonical(bundle))
        command = [sys.executable, "-m", av.__name__, "fit", "--bundle", str(path),
                   "--bundle-sha256", av.digest(bundle), "--output", str(output)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not (output / "INPUT_RECEIPT.json").exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNone(process.poll(), "Child finished before cancellation control")
            self.assertTrue((output / "INPUT_RECEIPT.json").exists())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1, stderr)
            self.assertEqual(json.loads(stdout)["status"], "cancelled")
            self.assertEqual(json.loads((output / "FIT.json").read_bytes())["status"], "cancelled")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
