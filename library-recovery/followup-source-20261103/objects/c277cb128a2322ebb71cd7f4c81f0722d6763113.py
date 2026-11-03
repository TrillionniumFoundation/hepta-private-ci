"""Fail-closed tests for bounded matched serial CPU Laya measurements."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import hepta_neuron_cpu_benchmark as bench
from hepta_neuron_model_trials import InvalidTrial


class BenchmarkTests(unittest.TestCase):
    def test_percentile_nearest_rank_and_reject_nonfinite(self):
        self.assertEqual(bench.nearest_rank([float(x) for x in range(1, 101)], 50), 50.0)
        self.assertEqual(bench.nearest_rank([float(x) for x in range(1, 101)], 95), 95.0)
        self.assertEqual(bench.nearest_rank([float(x) for x in range(1, 101)], 99), 99.0)
        for bad in ([float("nan")], [-1], [], [float("inf")]):
            with self.assertRaises(InvalidTrial):
                bench.nearest_rank(bad, 99)

    def test_device_sample_warmup_and_thread_limits_fail_closed(self):
        sha = "a" * 64
        for wrong in (
            ("laya", sha, "cuda:0", 5, 100, 2),
            ("laya", sha, "cpu", 1, 100, 2),
            ("laya", sha, "cpu", 5, 99, 2),
            ("laya", sha, "cpu", 5, 100, 0),
            ("laya", sha, "cpu", 5, True, 2),
            ("other", sha, "cpu", 5, 100, 2),
            ("laya", "unbound", "cpu", 5, 100, 2),
        ):
            with self.subTest(wrong=wrong), self.assertRaises(InvalidTrial):
                bench.validate_options(*wrong)

    def test_missing_artifact_blocks_before_any_model_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "catalog.json"
            catalog_path.write_text(json.dumps({"schema": "diagnostic"}))
            with self.assertRaises(InvalidTrial):
                bench.run_benchmark(catalog_path, "laya", Path(tmp) / "missing", "a" * 64)

    def test_measurement_receipt_is_never_authority(self):
        class Agent:
            device = "cpu"
            cfg = {"max_len": 512, "head_max_len": 192}
            model = SimpleNamespace(parameters=lambda: [SimpleNamespace(numel=lambda: 421293827)])
            def predict(self, state, questions):
                return {"answers": {"q": {"probabilities": {"billing": .8, "safety": .2}}},
                        "usage": {"input_tokens": 39}}
        class FakeTorch:
            __version__ = "fake-torch-not-production"
            threads = 0
            @classmethod
            def set_num_threads(cls, n): cls.threads = n
            @classmethod
            def get_num_threads(cls): return cls.threads
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "catalog.json"
            p.write_text("{}")
            model = root / "model"
            model.mkdir()
            (model / "model.safetensors").write_bytes(b"fake")
            sdk = root / "laya"
            sdk.mkdir()
            (sdk / "__init__.py").write_text("# fake")
            cat = {"revision": "b"*40, "variants": {"laya": {"weights_sha256": "b"*64}}}
            fake_laya = SimpleNamespace(__file__=str(sdk / "__init__.py"), load=lambda *a, **kw: Agent())
            fake_memory = {"rss_bytes": 1200, "peak_rss_bytes": 1200}
            with patch.object(bench,"verify_catalog",return_value=cat), \
                 patch.object(bench,"inspect_local",return_value={"local_weight_bytes_verified":True,
                        "artifact_tree_sha256":"c"*64}), \
                 patch.object(bench,"sha_file",return_value="b"*64), \
                 patch.object(bench,"sha_tree",side_effect=["a"*64,"c"*64]), \
                 patch.object(bench,"memory_bytes",return_value=fake_memory), \
                 patch.dict(sys.modules,{"laya": fake_laya,"torch":FakeTorch()}):
                receipt = bench.run_benchmark(p,"laya",model,"a"*64,warmup=2,samples=100)
        self.assertEqual(receipt["sample_count"],100)
        self.assertEqual(len(receipt["timing_samples_ms"]),100)
        self.assertEqual(receipt["parameters"],421293827)
        self.assertEqual(receipt["input_tokens"],39)
        self.assertGreater(receipt["p99_ms"],0)
        for name in ("actual_hepta_data_used", "independent_host_attestation",
                     "production_p99_sla_established", "future_window_effectiveness_evaluated",
                     "backend_batch_throughput_measured", "ndu_net_gain_verified",
                     "ndu_selection_authorized", "production_evidence_verified", "promotion_authorized"):
            self.assertIs(receipt[name],False,name)

    def test_runner_rejects_malformed_output_and_unphysical_model_bytes(self):
        # Explicit reject for malformed contract: do not mint observation without valid artifact.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "catalog.json"
            p.write_text("{}")
            with patch.object(bench,"verify_catalog",return_value={"variants":{"typed":{}}}), \
                 patch.object(bench,"inspect_local",return_value={"local_weight_bytes_verified":False}):
                with self.assertRaisesRegex(InvalidTrial,"not physically verified"):
                    bench.run_benchmark(p,"typed",root,"a"*64)

if __name__ == "__main__":
    unittest.main()
