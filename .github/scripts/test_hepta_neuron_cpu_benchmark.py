"""Fail-closed offline tests for real-weight serial CPU diagnostics and replay."""

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
import hepta_neuron_cpu_benchmark_verify as replay
from hepta_neuron_model_trials import InvalidTrial, MODEL_IDS


class CpuBenchmarkTests(unittest.TestCase):
    def test_nearest_rank_and_invalid_timing_rejected(self):
        values = [float(i) for i in range(1, 101)]
        self.assertEqual(bench.nearest_rank(values, 50), 50.0)
        self.assertEqual(bench.nearest_rank(values, 95), 95.0)
        self.assertEqual(bench.nearest_rank(values, 99), 99.0)
        for sample in ([], [-1], [float("nan")], [float("inf")]):
            with self.assertRaises(InvalidTrial):
                bench.nearest_rank(sample, 99)

    def test_unpinned_model_and_bad_budgets_fail(self):
        for args in (
            ("other", "a" * 64, 5, 100, 2),
            ("laya", "invalid", 5, 100, 2),
            ("laya", "a" * 64, 1, 100, 2),
            ("laya", "a" * 64, 5, 99, 2),
            ("laya", "a" * 64, 5, 100, 0),
            ("laya", "a" * 64, 5, True, 2),
        ):
            with self.assertRaises(InvalidTrial):
                bench.validate_config(*args)

    def test_no_unverified_local_weights_load(self):
        with tempfile.TemporaryDirectory() as root:
            cat = Path(root) / "cat.json"
            cat.write_text("{}")
            with (
                patch.object(
                    bench,
                    "verify_catalog",
                    return_value={"variants": {"laya": {"weights_sha256": "b" * 64}}},
                ),
                patch.object(
                    bench,
                    "inspect_local",
                    return_value={"local_weight_bytes_verified": False},
                ),
            ):
                with self.assertRaisesRegex(InvalidTrial, "not verified"):
                    bench.benchmark(cat, "laya", Path(root), "a" * 64)

    def test_mock_only_diagnostic_never_authority(self):
        class Agent:
            device = "cpu"
            cfg = {"max_len": 512, "head_max_len": 192}
            model = SimpleNamespace(
                parameters=lambda: [SimpleNamespace(numel=lambda: 421293827)]
            )

            def predict(self, state, questions):
                return {
                    "answers": {
                        "q": {"probabilities": {"billing": 0.8, "safety": 0.2}}
                    },
                    "usage": {"input_tokens": 39},
                }

        class FakeTorch:
            __version__ = "fake-torch"
            threads = 0

            @classmethod
            def set_num_threads(cls, n):
                cls.threads = n

            @classmethod
            def get_num_threads(cls):
                return cls.threads

        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "model.safetensors").write_bytes(b"fake model")
            cat = path / "cat.json"
            cat.write_text("{}")
            fake_sdk = path / "laya"
            fake_sdk.mkdir()
            (fake_sdk / "__init__.py").write_text("fake")
            fake_laya = SimpleNamespace(
                __file__=str(fake_sdk / "__init__.py"), load=lambda *a, **kw: Agent()
            )
            mem = {"rss_bytes": 4096, "peak_rss_bytes": 4096}
            with (
                patch.object(
                    bench,
                    "verify_catalog",
                    return_value={
                        "revision": "a" * 40,
                        "variants": {"laya": {"weights_sha256": "b" * 64}},
                    },
                ),
                patch.object(
                    bench,
                    "inspect_local",
                    return_value={
                        "local_weight_bytes_verified": True,
                        "artifact_tree_sha256": "c" * 64,
                    },
                ),
                patch.object(bench, "sha_file", return_value="b" * 64),
                patch.object(bench, "sha_tree", side_effect=["d" * 64, "c" * 64]),
                patch.object(bench, "process_memory", return_value=mem),
                patch.dict(sys.modules, {"laya": fake_laya, "torch": FakeTorch()}),
            ):
                result = bench.benchmark(
                    cat, "laya", path, "d" * 64, warmup=2, samples=100
                )
        self.assertEqual(len(result["timing_samples_ms"]), 100)
        self.assertEqual(result["parameters"], 421293827)
        for field in replay.FALSE_ONLY:
            self.assertIs(result[field], False)

    def test_three_arm_replay_detects_tampering_and_missing_receipts(self):
        fake_catalog = {
            "revision": "a" * 40,
            "variants": {arm: {"weights_sha256": "c" * 64} for arm in replay.ARMS},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = root / "observations"
            files.mkdir()
            catalog_path = root / "catalog.json"
            catalog_path.write_text("{}")
            for arm in replay.ARMS:
                times = [1.0 + i / 1000 for i in range(100)]
                sample = {
                    "schema": bench.SCHEMA,
                    "arm": arm,
                    "model_id": MODEL_IDS[arm],
                    "source_revision": "a" * 40,
                    "source_catalog_sha256": "b" * 64,
                    "weights_sha256": "c" * 64,
                    "installed_sdk_python_sha256": "d" * 64,
                    "physical_artifact_tree_sha256": "e" * 64,
                    "device": "cpu",
                    "cpu_threads": 2,
                    "parameters": bench.EXPECTED_PARAMETERS[arm],
                    "effective_context": 512,
                    "effective_head_budget": 192,
                    "warmup_count": 5,
                    "sample_count": 100,
                    "input_tokens": 39,
                    "timing_samples_ms": times,
                    "mean_ms": round(sum(times) / 100, 6),
                    "p50_ms": 1.049,
                    "p95_ms": 1.094,
                    "p99_ms": 1.098,
                    "load_ms": 50.0,
                    "serial_invocations_per_second": round(
                        1000 / (sum(times) / 100), 5
                    ),
                    "rss_before_model_load": {
                        "rss_bytes": 4000,
                        "peak_rss_bytes": 4000,
                    },
                    "rss_after_model_load": {"rss_bytes": 4500, "peak_rss_bytes": 4500},
                    "rss_after_forwards": {"rss_bytes": 5000, "peak_rss_bytes": 5000},
                    "measurement_scope": "serial single CPU process, synthetic repeated identical prompt",
                }
                for field in replay.FALSE_ONLY:
                    sample[field] = False
                (files / f"{arm}-cpu-diagnostic.json").write_text(json.dumps(sample))
            with (
                patch.object(replay, "verify_catalog", return_value=fake_catalog),
                patch.object(replay, "sha_file", return_value="b" * 64),
            ):
                ok = replay.verify_bundle(files, catalog_path, "d" * 64)
                self.assertFalse(ok["promotion_authorized"])
                self.assertEqual(len(ok["arms"]), 3)
                wrong = files / "typed-cpu-diagnostic.json"
                tampered = json.loads(wrong.read_text())
                tampered["p99_ms"] = 0.001
                wrong.write_text(json.dumps(tampered))
                with self.assertRaisesRegex(InvalidTrial, "p99"):
                    replay.verify_bundle(files, catalog_path, "d" * 64)
                wrong.unlink()
                with self.assertRaisesRegex(InvalidTrial, "unexpected/aliased"):
                    replay.verify_bundle(files, catalog_path, "d" * 64)


if __name__ == "__main__":
    unittest.main()
