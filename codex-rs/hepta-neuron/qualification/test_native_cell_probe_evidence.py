"""Exercise probe orchestration with explicit fake model/native ports, not efficacy."""
import hashlib
import importlib.util
import json
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
        panel.repository_source = lambda: dict(SOURCE)
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
                self._process = SimpleNamespace(poll=lambda: 0)
            def __enter__(self):
                return self
            def __exit__(self, *_a):
                return False
            def exchange(self, request, *_a, **_kw):
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

        def native(command, _out, _index):
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
            return code, False

        with tempfile.TemporaryDirectory() as directory, patch.object(module, "run_native", native):
            output = Path(directory) / "result"
            result = module.probe(Path("unused"), Path("unused"), output, 1)
            self.assertEqual(json.loads((output / "report.json").read_text()), result)
        return result

    def test_existing_probe_consumes_validated_positive_and_negative_results(self):
        result = self.run_probe("correct")
        self.assertEqual(result["schema"], "hepta.model-native-execution-probe.v2")
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


if __name__ == "__main__":
    unittest.main()
