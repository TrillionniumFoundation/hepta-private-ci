"""Exercise probe orchestration with explicit fake model/native ports, not efficacy."""
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from test_native_probe_evidence import SOURCE, packet_fixture, receipt_fixture


class NativeProbeIntegrationTests(unittest.TestCase):
    def run_probe(self, mode):
        panel = ModuleType("decision_cell_bakeoff")
        source_reads = 0
        def source_observation():
            nonlocal source_reads
            source_reads += 1
            if (mode == "source_drift_before_native" and source_reads >= 3 or
                    mode == "source_drift_after_copy" and source_reads >= 4):
                return {**SOURCE, "commit": "f" * 40}
            if mode == "final_source_error" and source_reads == 8:
                raise OSError("source observation unavailable")
            return dict(SOURCE)
        panel.repository_source = source_observation
        panel.verified_receipt = lambda _p: ({"model_name": "mdeberta-v3-base",
            "base_model": {"snapshot_digest": "d" * 64},
            "head_artifact": {"manifest_path": "unused", "manifest_sha256": "c" * 64,
                "weights_path": "unused", "weights_sha256": "e" * 64}}, "a" * 64)
        panel._tensor_module = SimpleNamespace(checked_bytes=lambda *_a: b'{}',
            strict_json=lambda _a: {"runtime_profile": {}})
        examples = [SimpleNamespace(example_id=name, text=name, split=split, action=2,
            target=3 if not ood else -1, ood=ood, candidates=("a", "b", "c", "d"))
            for name, split, ood in [("positive", "test", 0), ("negative1", "ood_test", 1), ("negative2", "ood_test", 1)]]
        panel.build_dataset = lambda: examples
        transport = ModuleType("decision_cell_process")
        transport.canonical = lambda v: (json.dumps(v, sort_keys=True) + "\n").encode()
        transport.build_request = lambda rid, text, targets, **_kw: {"request_id": rid, "text": text, "targets": targets}

        class FakeChild:
            def __init__(self, *_a, **_kw):
                if mode == "model_start_error":
                    raise RuntimeError("do not retain this raw detail")
                self._process = SimpleNamespace(poll=lambda: 0)
            def __enter__(self):
                return self
            def __exit__(self, *_a):
                if mode == "cleanup_error":
                    raise OSError("cleanup unconfirmed")
                return False
            def exchange(self, request, *_a, **_kw):
                if mode == "model_timeout" or (mode == "second_model_error" and request["text"] == "negative1"):
                    raise TimeoutError("do not retain this raw detail")
                probabilities = packet_fixture()["probabilities"]
                if request["text"].startswith("negative"):
                    probabilities["ood"] = [0, 1]
                return {"status": "observed", "projection_sha256": "b" * 64,
                    "observation": {"head_manifest_sha256": "c" * 64, "base_snapshot_digest": "d" * 64,
                        "base_forward_passes": 1, "latency_ns": 1,
                        "probabilities": {k: [v] for k, v in probabilities.items()}}}

        transport.FrozenEncoderProcess = FakeChild
        module_path = Path(__file__).with_name("native_cell_probe.py")
        spec = importlib.util.spec_from_file_location("probe_under_test", module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, decision_cell_bakeoff=panel, decision_cell_process=transport), patch.object(sys, "path", list(sys.path)):
            spec.loader.exec_module(module)
        self.probe_module = module

        def native(command, _out, _index):
            if mode == "native_launch_error":
                raise OSError("do not retain this raw detail")
            receipt_path, packet_path = map(Path, command[2:4])
            packet = json.loads(packet_path.read_text())
            self.assertEqual(hashlib.sha256(packet_path.read_bytes()).hexdigest(), command[4])
            receipt = receipt_fixture(packet)
            code = 0
            if packet["probabilities"]["ood"][1] == 1:
                code = 3
                receipt = {"schema": "hepta.native-model-abstention.v1", "source": receipt["source"],
                    "productionActivation": False, "externalEffect": False,
                    "modelChoice": {"status": "abstained", "requestId": packet["requestId"],
                        "replySha256": packet["replySha256"], "authorityGranted": False,
                        "predicted": {"action": 2, "target": 3, "disposition": 0, "postcondition": 2, "ood": 1},
                        "confidence": 1, "ood": 1}}
            if mode == "wrong_source":
                receipt["source"]["commit"] = "f" * 40
            elif mode == "fake_abstention" and code == 3:
                receipt = {}
            elif mode == "after_effect_error" and code == 0:
                code = 1
            receipt_path.write_text("{" if mode == "malformed" else json.dumps(receipt))
            if mode == "interrupt_after_effect" and code == 0:
                raise KeyboardInterrupt()
            return code, False

        with tempfile.TemporaryDirectory() as directory, patch.object(module, "run_native", native):
            output = Path(directory) / "result"
            result = module.probe(Path("unused"), Path("unused"), output, 1)
            self.assertEqual(json.loads((output / "report.json").read_text()), result)
            self.assertEqual(hashlib.sha256((output / "plan.json").read_bytes()).hexdigest(), result["plan_sha256"])
            self.assertEqual(hashlib.sha256((output / "progress.jsonl").read_bytes()).hexdigest(), result["progress_sha256"])
            self.assertEqual(len(json.loads((output / "plan.json").read_text())["cases"]), 3)
            self.assertNotIn("do not retain this raw detail", json.dumps(result))
        return result

    def test_existing_probe_consumes_validated_positive_and_negative_results(self):
        result = self.run_probe("correct")
        self.assertEqual(result["schema"], "hepta.model-native-execution-probe.v3")
        self.assertTrue(result["passed"]); self.assertEqual(result["actual_native_effects"], 1)
        self.assertFalse(result["production_activation"]); self.assertFalse(result["runtime_selection_eligible"])

    def test_forged_exit_three_cannot_pass_actual_probe(self):
        result = self.run_probe("fake_abstention")
        self.assertFalse(result["passed"]); self.assertEqual(result["indeterminate_native_effects"], 2)

    def test_wrong_source_cannot_pass_actual_probe(self):
        result = self.run_probe("wrong_source")
        self.assertFalse(result["passed"]); self.assertEqual(result["indeterminate_native_effects"], 3)

    def test_malformed_child_output_retains_all_selected_cases(self):
        result = self.run_probe("malformed")
        self.assertFalse(result["passed"]); self.assertEqual(len(result["records"]), 3)
        self.assertEqual(result["indeterminate_native_effects"], 3)

    def test_observed_copy_is_not_erased_when_child_later_exits_nonzero(self):
        result = self.run_probe("after_effect_error")
        self.assertFalse(result["passed"]); self.assertEqual(result["actual_native_effects"], 1)
        self.assertIs(result["records"][0]["external_effect"], True)
        self.assertFalse(result["records"][0]["task_passed"])


    def test_start_failure_retains_the_unstarted_plan(self):
        result = self.run_probe("model_start_error")
        self.assertFalse(result["passed"])
        self.assertIsNone(result["model_process_reaped"])
        self.assertEqual(result["execution_failure"]["phase"], "model_start")
        self.assertEqual([row["status"] for row in result["records"]], ["not_started"] * 3)

    def test_model_timeout_stops_without_native_effect_or_retry(self):
        result = self.run_probe("model_timeout")
        self.assertFalse(result["passed"])
        self.assertEqual(result["execution_failure"]["phase"], "model_dispatch")
        self.assertEqual([row["status"] for row in result["records"]], ["execution_failed", "not_started", "not_started"])
        self.assertEqual(result["actual_native_effects"], 0)
        self.assertEqual(result["indeterminate_native_effects"], 0)

    def test_later_model_failure_does_not_erase_observed_copy(self):
        result = self.run_probe("second_model_error")
        self.assertFalse(result["passed"])
        self.assertEqual(result["actual_native_effects"], 1)
        self.assertTrue(result["records"][0]["task_passed"])
        self.assertEqual(result["records"][2]["status"], "not_started")

    def test_native_launch_failure_is_not_claimed_not_applied(self):
        result = self.run_probe("native_launch_error")
        self.assertFalse(result["passed"])
        self.assertEqual(result["execution_failure"]["phase"], "native_dispatch")
        self.assertEqual(result["indeterminate_native_effects"], 1)
        self.assertEqual([row["status"] for row in result["records"]][1:], ["not_started"] * 2)

    def test_interrupt_preserves_retained_copy_and_stops_the_panel(self):
        result = self.run_probe("interrupt_after_effect")
        self.assertFalse(result["passed"])
        self.assertTrue(result["execution_failure"]["interrupted"])
        self.assertEqual(result["actual_native_effects"], 1)
        self.assertIsNone(result["records"][0]["native_exit"])
        self.assertFalse(result["records"][0]["task_passed"])
        self.assertEqual(result["records"][1]["status"], "not_started")

    def test_cleanup_error_prevents_a_pass_without_erasing_results(self):
        result = self.run_probe("cleanup_error")
        self.assertFalse(result["passed"])
        self.assertEqual(result["execution_failure"]["phase"], "model_cleanup")
        self.assertEqual(result["actual_native_effects"], 1)
        self.assertTrue(all(row["task_passed"] for row in result["records"]))

    def test_source_drift_before_native_prevents_actuator_dispatch(self):
        result = self.run_probe("source_drift_before_native")
        self.assertFalse(result["passed"])
        self.assertFalse(result["source_unchanged"])
        self.assertEqual(result["execution_failure"]["phase"], "source_check")
        self.assertEqual(result["actual_native_effects"], 0)
        self.assertEqual(result["indeterminate_native_effects"], 0)

    def test_source_drift_after_copy_keeps_effect_but_stops_new_work(self):
        result = self.run_probe("source_drift_after_copy")
        self.assertFalse(result["passed"])
        self.assertFalse(result["source_unchanged"])
        self.assertEqual(result["actual_native_effects"], 1)
        self.assertEqual(result["records"][2]["status"], "not_started")

    def test_final_source_observation_error_retains_observed_results(self):
        result = self.run_probe("final_source_error")
        self.assertFalse(result["passed"])
        self.assertFalse(result["source_unchanged"])
        self.assertEqual(result["execution_failure"]["phase"], "final_source_check")
        self.assertEqual(result["actual_native_effects"], 1)

    @unittest.skipUnless(os.name == "posix", "native probe uses POSIX process groups")
    def test_interruption_reaps_a_real_private_child(self):
        self.run_probe("correct")
        module = self.probe_module
        real_popen = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            wait = child.wait
            first = True
            def interrupt_once(*args, **kwargs):
                nonlocal first
                if first:
                    first = False
                    raise KeyboardInterrupt()
                return wait(*args, **kwargs)
            child.wait = interrupt_once
            return child
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(module.subprocess, "Popen", spawn):
                with self.assertRaises(KeyboardInterrupt):
                    module.run_native([sys.executable, "-c", "import time; time.sleep(60)"], Path(directory), 0)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())
        finally:
            for child in children:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()

if __name__ == "__main__":
    unittest.main()
