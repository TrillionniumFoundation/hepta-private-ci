"""Execution-policy identity, failure evidence and candidate checkpoint replay."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from .. import benchmark
from ..execution import close_energy_interval, configure_cuda, execution_policy, training_memory_peak

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


def tiny_config(**changes):
    config = json.loads((Path(__file__).parents[1]/"configs/smoke.json").read_text())
    config.update(models=["gru"], seeds=[0], train_steps=1, latency_repeats=1,
                  hidden_size=2, length=4, train_count=4, validation_count=2,
                  test_count=2, batch_size=2)
    config.update(changes)
    return config


class ExecutionEvidenceTests(unittest.TestCase):
    def test_mixed_energy_intervals_keep_cost_and_do_not_promote_legacy(self):
        from ..attempts import accounting
        attempts = [dict(result=dict(status=status, training_status=status,
                                     training_examples_seen=examples, training_tokens_seen=examples*4,
                                     energy=energy))
                    for status, examples, energy in (
                        ('completed', 4, dict(joules_by_physical_counter={'gpu': 2.0, 'package': 4.0},
                                              interval_complete=True)),
                        ('failed', 2, dict(joules_by_physical_counter={'gpu': 1.0}, interval_complete=False)),
                        ('completed', 4, dict(joules_by_physical_counter={'gpu': 3.0})),
                        ('failed', 2, dict(joules_by_physical_counter=None, interval_complete=True)))]
        before = copy.deepcopy(attempts)
        result = accounting(attempts)
        self.assertEqual(attempts, before)
        self.assertEqual((result['energy_measured_attempts'], result['energy_missing_attempts'],
                          result['energy_measured_complete_interval_attempts'],
                          result['energy_measured_incomplete_interval_attempts'],
                          result['energy_measured_unknown_interval_attempts']), (3, 1, 1, 1, 1))
        self.assertEqual(result['measured_joules_by_counter'], {'gpu': 6.0, 'package': 4.0})
        self.assertEqual(result['measured_joules_by_counter_by_interval_completion'],
                         dict(complete={'gpu': 2.0, 'package': 4.0}, incomplete={'gpu': 1.0}, unknown={'gpu': 3.0}))
        self.assertEqual((result['known_training_examples'], result['known_training_tokens']), (12, 48))

    def test_invalid_policy_rejected_and_policy_changes_cache_identity(self):
        config = tiny_config()
        for key, value in (("population_checkpoint_steps", True), ("population_checkpoint_steps", 4),
                           ("cuda_memory_fraction", float("nan")), ("cuda_memory_fraction", 0),
                           ("cuda_memory_fraction", True), ("cuda_memory_fraction", .5)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                benchmark.validate_config(dict(config, **{key: value}))
        report = dict(config=dict(config, device="cuda:0", cuda_memory_fraction=.5),
                      source_sha256="fixed source", hardware={}, software={},
                      datasets={"delayed_recall": {"split_sha256": ["train", "val", "test"]}})
        original = benchmark.receipt_key(report, "delayed_recall", "population_flux", 0)
        remat = copy.deepcopy(report)
        remat["config"]["population_checkpoint_steps"] = 1
        capped = copy.deepcopy(remat)
        capped["config"]["cuda_memory_fraction"] = .75
        hardware = copy.deepcopy(remat)
        hardware["hardware"]["cuda_execution"] = dict(uuid="GPU-1", driver_version="570.00")
        self.assertEqual(len({original, *(benchmark.receipt_key(r, "delayed_recall", "population_flux", 0)
                                         for r in (remat, capped, hardware))}), 4)

    def test_cuda_public_metadata_and_cap_are_bound_without_ordinal_guess(self):
        device = SimpleNamespace(type="cuda")
        props = SimpleNamespace(uuid="GPU-test", name="fixture", total_memory=8*2**30, major=8, minor=9)
        cuda = Mock()
        cuda.is_available.return_value = True
        cuda.get_device_properties.return_value = props
        cuda.memory.get_per_process_memory_fraction.return_value = .5
        with patch("hcsn.execution.subprocess.run", return_value=SimpleNamespace(stdout="GPU-test, 570.00\n")) as query:
            info = configure_cuda(SimpleNamespace(cuda=cuda), device, .5)
        cuda.set_per_process_memory_fraction.assert_called_once_with(.5, device)
        self.assertEqual((info["uuid"], info["driver_version"], info["compute_capability"],
                          info["allocator_limit_bytes"], info["setup_error"]),
                         ("GPU-test", "570.00", [8, 9], 4*2**30, None))
        self.assertEqual(query.call_args.args[0][1:3], ["-i", "GPU-test"])
        with patch("hcsn.execution.subprocess.run", return_value=SimpleNamespace(stdout="GPU-other, 570.00\n")):
            mismatched = configure_cuda(SimpleNamespace(cuda=cuda), device, .5)
        self.assertIsNone(mismatched["driver_version"])
        self.assertIn("requested UUID", mismatched["metadata_missing_reasons"]["driver_version"])
        props.uuid = None
        with patch("hcsn.execution.subprocess.run", side_effect=AssertionError("no ordinal fallback")):
            missing = configure_cuda(SimpleNamespace(cuda=cuda), device, .5)
        self.assertIsNone(missing["uuid"])
        self.assertIn("ordinal", missing["metadata_missing_reasons"]["driver_version"])

    def test_failed_allocator_cap_prevents_matrix_attempts_without_torch(self):
        cuda = Mock()
        cuda.is_available.return_value = True
        cuda.get_device_properties.return_value = SimpleNamespace(
            uuid="GPU-test", name="fixture", total_memory=8*2**30, major=8, minor=9)
        cuda.set_per_process_memory_fraction.side_effect = RuntimeError("injected cap rejection")
        device = SimpleNamespace(type="cuda")
        fake = SimpleNamespace(cuda=cuda, device=lambda value: device, set_num_threads=lambda value: None,
                               get_num_threads=lambda: 2, use_deterministic_algorithms=lambda *a, **kw: None,
                               __version__="fixture", version=SimpleNamespace(cuda="fixture"))
        with patch.dict("sys.modules", torch=fake), patch("hcsn.benchmark._run_one") as operation:
            report = benchmark.run(tiny_config(device="cuda:0", cuda_memory_fraction=.5, seeds=[0, 1]))
        operation.assert_not_called()
        self.assertEqual(report["accounting"], dict(requested=2, unique_records=2, completed=0, failed=0, unavailable=2))
        self.assertTrue(all("injected cap rejection" in r["reason"] for r in report["runs"]))
        self.assertEqual(report["attempt_accounting"]["known_training_examples"], 0)

    def test_failed_terminal_sync_keeps_partial_reading_and_precedes_meter_stop(self):
        events = []
        def fail_sync(device):
            events.append("synchronize")
            raise RuntimeError("injected asynchronous failure")
        def stop():
            events.append("stop")
            return dict(joules_by_physical_counter={"nvml_fixture": 3.5}, missing_reason=None)
        energy = close_energy_interval(SimpleNamespace(stop=stop),
                                       SimpleNamespace(cuda=SimpleNamespace(synchronize=fail_sync)),
                                       SimpleNamespace(type="cuda"), started=True)
        self.assertEqual(events, ["synchronize", "stop"])
        self.assertEqual(energy["joules_by_physical_counter"], {"nvml_fixture": 3.5})
        self.assertFalse(energy["interval_complete"])
        self.assertFalse(energy["terminal_cuda_synchronized"])
        self.assertIn("injected asynchronous failure", energy["terminal_cuda_sync_error"])

    def test_training_peak_requires_own_reset_and_keeps_reserved_separate(self):
        cuda = Mock()
        cuda.max_memory_allocated.return_value = 120
        cuda.max_memory_reserved.return_value = 256
        torch = SimpleNamespace(cuda=cuda)
        device = SimpleNamespace(type="cuda")
        not_reset = training_memory_peak(torch, device, reset_completed=False)
        cuda.max_memory_allocated.assert_not_called()
        self.assertIsNone(not_reset["peak_gpu_allocated_bytes"])
        measured = training_memory_peak(torch, device, reset_completed=True)
        self.assertEqual((measured["peak_gpu_allocated_bytes"], measured["peak_gpu_reserved_bytes"]), (120, 256))
        self.assertEqual(measured["peak_gpu_measurement_status"], "measured")
        calls = cuda.max_memory_allocated.call_count
        cpu = training_memory_peak(torch, SimpleNamespace(type="cpu"), reset_completed=True)
        self.assertEqual((cpu["peak_gpu_allocated_bytes"], cpu["peak_gpu_reserved_bytes"],
                          cpu["peak_gpu_measurement_status"]), (None, None, "not_applicable_cpu"))
        self.assertEqual(cuda.max_memory_allocated.call_count, calls)


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch not installed; candidate execution is not verified")
class CandidateExecutionTests(unittest.TestCase):
    def test_candidate_policy_both_variants_saved_replay_and_resume(self):
        import torch
        from .. import audit_population
        from ..baselines import make_encoder
        for name in ("population_flux", "population_flux_no_recovery"):
            torch.manual_seed(17)
            original = make_encoder(name, 2, 2)
            original_rng = torch.get_rng_state()
            torch.manual_seed(17)
            candidate = make_encoder(name, 2, 2, population_checkpoint_steps=1)
            self.assertEqual(type(candidate).__name__, "RematerializedPopulationFluxEncoder")
            self.assertEqual(type(original).__name__, "PopulationFluxEncoder")
            torch.testing.assert_close(torch.get_rng_state(), original_rng, rtol=0, atol=0)
            self.assertEqual(set(candidate.state_dict()), set(original.state_dict()))
            for key, value in original.state_dict().items():
                torch.testing.assert_close(candidate.state_dict()[key], value, rtol=0, atol=0)
        config = tiny_config(models=["population_flux", "population_flux_no_recovery"],
                             population_checkpoint_steps=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"candidate.json"
            report = benchmark.run(config, path.with_suffix(".runs"))
            self.assertEqual(report["accounting"]["completed"], 2)
            benchmark.atomic_json(path, report)
            result = audit_population.audit(path)
            self.assertEqual((result["status"], result["audited_b_runs"]), ("passed", 2))
            for row in result["records"]:
                self.assertEqual(row["implementation"]["encoder_class"], "RematerializedPopulationFluxEncoder")
                self.assertEqual(row["implementation"]["population_checkpoint_steps"], 1)
            with patch("hcsn.benchmark._run_one", side_effect=AssertionError("completed candidate reran")):
                self.assertEqual(benchmark.run(config, path.with_suffix(".runs"))["runs"], report["runs"])
            original = benchmark.run(dict(config, population_checkpoint_steps=0), path.with_suffix(".runs"))
            self.assertEqual(original["accounting"]["completed"], 2)
            self.assertTrue(set(r["best_checkpoint"] for r in original["runs"]).isdisjoint(
                r["best_checkpoint"] for r in report["runs"]))
            tampered = copy.deepcopy(report)
            tampered["runs"][0]["implementation"]["population_checkpoint_steps"] = 0
            benchmark.atomic_json(path, tampered)
            rejected = audit_population.audit(path)
            self.assertEqual(rejected["status"], "failed")
            self.assertIn("execution policy", next(r["reason"] for r in rejected["records"] if r["status"] == "failed"))

    def test_missing_gradient_is_failure_but_intentionally_frozen_parameter_is_allowed(self):
        import torch
        from ..baselines import GRUEncoder
        for trainable in (True, False):
            encoder = GRUEncoder(2, 2)
            encoder.register_parameter("unused_fixture", torch.nn.Parameter(torch.zeros(1), requires_grad=trainable))
            with self.subTest(trainable=trainable), patch("hcsn.baselines.make_encoder", return_value=encoder):
                report = benchmark.run(tiny_config())
            row = report["runs"][0]
            if trainable:
                self.assertEqual((row["status"], row["training_steps_completed"], row["training_examples_seen"]),
                                 ("failed", 0, 2))
                self.assertEqual(row["missing_trainable_gradients"], ["encoder.unused_fixture"])
                self.assertTrue(row["energy"]["interval_complete"])
            else:
                self.assertEqual(row["status"], "completed")
                self.assertIsNone(row["peak_gpu_interval_complete"])
                self.assertEqual(row["peak_gpu_measurement_status"], "not_applicable_cpu")

    def test_nonfinite_norm_and_updated_parameter_preserve_actual_update_count(self):
        import torch
        with patch.object(torch.nn.utils, "clip_grad_norm_", return_value=torch.tensor(float("inf"))):
            norm_failure = benchmark.run(tiny_config())["runs"][0]
        self.assertEqual((norm_failure["status"], norm_failure["training_steps_completed"],
                          norm_failure["training_examples_seen"]), ("failed", 0, 2))
        self.assertIn("nonfinite gradient norm", norm_failure["reason"])
        original_step = torch.optim.Adam.step
        def corrupt_after_step(optimizer, *args, **kwargs):
            outcome = original_step(optimizer, *args, **kwargs)
            with torch.no_grad():
                optimizer.param_groups[0]["params"][0].fill_(float("nan"))
            return outcome
        with patch.object(torch.optim.Adam, "step", corrupt_after_step):
            parameter_failure = benchmark.run(tiny_config())["runs"][0]
        self.assertEqual((parameter_failure["status"], parameter_failure["training_steps_completed"],
                          parameter_failure["training_examples_seen"]), ("failed", 1, 2))
        self.assertIn("nonfinite updated parameter", parameter_failure["reason"])
