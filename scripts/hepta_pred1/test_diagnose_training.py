"""Concrete contamination, accounting and source-interpretation regression tests."""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "diagnose_training", Path(__file__).with_name("diagnose_training.py")
)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
SOURCE = """
raise RuntimeError("The diagnostic must never execute this source")
def train_one(config, variant, seed, train, dev, out):
    model = Model(kind, INPUT_DIM, ACTION_DIM, 32, hidden, seed)
    rng = np.random.default_rng(seed + 911)
    if dev_loss < best:
        pass
def run(config, output):
    train = generate_dataset(config["train_episodes"], seed, "train", config["history_length"])
    dev = generate_dataset(config["dev_episodes"], seed, "dev", config["history_length"])
"""


class TrainingDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.campaign = self.root / "campaign"
        self.campaign.mkdir()
        self.source = self.root / "run.py"
        self.source.write_text(SOURCE)
        self.config = {
            "schema": "pred1-experiment-v1",
            "selection_seeds": [11, 22],
            "seeds": [101, 202],
            "train_episodes": 5,
            "dev_episodes": 3,
            "epochs": 3,
            "batch_size": 2,
            "checkpoint_selection": "minimum development observed-label NLL",
        }
        self.config_path = self.root / "registered_config.json"
        self.config_path.write_text(D.canonical(self.config))
        for seed in self.config["selection_seeds"] + self.config["seeds"]:
            for variant in D.VARIANTS:
                self.path(variant, seed).write_text(
                    D.canonical(self.record(variant, seed))
                )

    def path(self, variant="gru", seed=202):
        return self.campaign / f"{variant}-{seed}-training.json"

    def record(self, variant="gru", seed=202):
        dev = {
            "episodes": 3,
            "net_utility": 0.1 if variant == "gru" else 0.0,
            "inference_wall_seconds": 0.01,
            "inference_process_cpu_seconds": 0.01,
            "planning_wall_seconds": 0.001,
            "planning_process_cpu_seconds": 0.001,
        }
        return {
            "variant": variant,
            "seed": seed,
            "parameters": 42,
            "hidden_dim": 2,
            "best_epoch": 2,
            "epochs_consumed": 3,
            "optimizer_steps_consumed": 9,
            "selected_checkpoint_steps": 6,
            "training_examples_consumed": 15,
            "train_wall_seconds": 1.0,
            "train_process_cpu_seconds": 0.9,
            "checkpoint": f"{variant}-{seed}.npz",
            "checkpoint_sha256": "a" * 64,
            "curve": [
                {"epoch": 1, "train_nll": 1.0, "dev_observed_nll": 1.0},
                {"epoch": 2, "train_nll": 0.8, "dev_observed_nll": 0.7},
                {"epoch": 3, "train_nll": 0.7, "dev_observed_nll": 0.8},
            ],
            "dev": dev,
            "metering": {
                "energy_joules": None,
                "financial_cost": None,
                "physical_cost_complete": False,
            },
        }

    def audit(self):
        return D.audit(self.campaign, self.config_path, self.source)

    def test_explicit_input_allowlist_never_opens_confirmation_or_checkpoint(self):
        forbidden = [
            self.campaign / "gru-202-confirm.json",
            self.campaign / "RESULT.json",
            self.campaign / "gru-202.npz",
        ]
        for path in forbidden:
            path.write_text("poison confirmation/private bytes")
        allowed = {self.source, self.config_path} | {
            self.path(v, s) for v in D.VARIANTS for s in [11, 22, 101, 202]
        }
        original = D.os.open
        observed = []

        def monitored(path, flags, *args, **kwargs):
            self.assertIn(path, allowed)
            observed.append(path)
            return original(path, flags, *args, **kwargs)

        with mock.patch.object(D.os, "open", monitored):
            report = self.audit()
        self.assertEqual(set(observed), allowed)
        self.assertEqual(len(observed), 26)
        self.assertFalse(report["confirmation_data_read"])
        self.assertEqual(report["confirmation_samples_generated"], 0)
        self.assertEqual(report["original_qualification"], "HOLD_UNCHANGED")

    def test_actual_oversized_file_is_rejected_before_open_or_whole_file_read(self):
        oversized = self.root / "oversized.json"
        with oversized.open("wb") as stream:
            stream.seek(4 * D.MAX_INPUT_BYTES)
            stream.write(b"x")
        self.assertGreater(oversized.stat().st_size, D.MAX_INPUT_BYTES)
        manifest = []
        with (
            mock.patch.object(
                D.os, "open", side_effect=AssertionError("oversized file opened")
            ),
            mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("whole file read attempted"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "exceeds one MiB"):
                D.read_bound(oversized, manifest, "training_record")
        self.assertEqual(manifest, [])

    def test_file_growth_after_stat_still_reads_only_limit_plus_one(self):
        growing = self.root / "growing.json"
        growing.write_bytes(b"{}")
        original_fstat, original_fdopen = D.os.fstat, D.os.fdopen
        reads = []

        def grow_after_descriptor_stat(descriptor):
            initial = original_fstat(descriptor)
            with growing.open("r+b") as stream:
                stream.seek(4 * D.MAX_INPUT_BYTES)
                stream.write(b"x")
            return initial

        test = self

        class MonitoredStream:
            def __init__(self, inner):
                self.inner = inner

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.inner.close()

            def fileno(self):
                return self.inner.fileno()

            def read(self, size=-1):
                test.assertEqual(size, D.MAX_INPUT_BYTES + 1)
                data = self.inner.read(size)
                reads.append((size, len(data)))
                return data

        def monitored_fdopen(*args, **kwargs):
            return MonitoredStream(original_fdopen(*args, **kwargs))

        manifest = []
        with (
            mock.patch.object(D.os, "fstat", grow_after_descriptor_stat),
            mock.patch.object(D.os, "fdopen", monitored_fdopen),
            mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("whole file read attempted"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "exceeds one MiB"):
                D.read_bound(growing, manifest, "training_record")
        self.assertEqual(reads, [(D.MAX_INPUT_BYTES + 1, D.MAX_INPUT_BYTES + 1)])
        self.assertGreater(growing.stat().st_size, reads[0][1])
        self.assertEqual(manifest, [])

    def test_symlink_input_remains_rejected(self):
        link = self.root / "linked-training.json"
        try:
            link.symlink_to(self.path())
        except OSError:
            self.skipTest("symlink creation unavailable on this host")
        with self.assertRaisesRegex(ValueError, "ordinary non-symlink"):
            D.read_bound(link, [], "training_record")

    def test_all_arms_and_full_fit_steps_count_including_partial_batches(self):
        report = self.audit()
        totals = report["costs"]["original_fit_totals"]
        self.assertEqual(
            (
                totals["fits"],
                totals["optimizer_steps_consumed"],
                totals["selected_checkpoint_steps"],
                totals["training_examples_consumed"],
            ),
            (24, 216, 144, 360),
        )
        self.assertEqual(set(report["costs"]["per_variant"]), set(D.VARIANTS))
        self.assertEqual(totals["train_wall_seconds"], 24.0)

    def test_uses_only_family_selection_seed_dev_values_for_family_rule(self):
        for seed in self.config["seeds"]:
            record = self.record("diag_ssm", seed)
            record["dev"]["net_utility"] = 100.0
            self.path("diag_ssm", seed).write_text(D.canonical(record))
        report = self.audit()
        self.assertEqual(
            report["registered_family_rule_recomputed"]["selected_family"], "gru"
        )

    def test_full_consumption_cannot_be_replaced_by_checkpoint_steps(self):
        record = self.record()
        record["optimizer_steps_consumed"] = record["selected_checkpoint_steps"]
        self.path().write_text(D.canonical(record))
        with self.assertRaisesRegex(ValueError, "optimizer_steps_consumed"):
            self.audit()

    def test_checkpoint_tie_uses_first_strict_minimum(self):
        record = self.record()
        record["curve"][-1]["dev_observed_nll"] = 0.7
        D.validate_record(record, "gru", 202, self.config)
        record["best_epoch"] = 3
        record["selected_checkpoint_steps"] = 9
        with self.assertRaisesRegex(ValueError, "best_epoch"):
            D.validate_record(record, "gru", 202, self.config)

    def test_duplicate_json_nonfinite_and_wrong_payload_identity_rejected(self):
        inputs = [
            '{"variant":"gru","variant":"single_step"}',
            D.canonical(self.record()).replace(
                '"train_wall_seconds": 1.0', '"train_wall_seconds": NaN'
            ),
            D.canonical(self.record(seed=303)),
        ]
        for payload in inputs:
            with self.subTest(payload=payload[:70]):
                self.path().write_text(payload)
                with self.assertRaises(ValueError):
                    self.audit()

    def test_misnamed_result_and_hidden_confirmation_fields_rejected(self):
        inputs = [{"confirm": {"net_utility": 100.0}}, self.record()]
        inputs[1]["dev"]["confirmation_net_utility"] = 100.0
        for record in inputs:
            with self.subTest(record=record):
                self.path().write_text(D.canonical(record))
                with self.assertRaisesRegex(ValueError, "confirmation"):
                    self.audit()

    def test_missing_epoch_and_missing_fit_fail_closed(self):
        record = self.record()
        record["curve"].pop()
        self.path().write_text(D.canonical(record))
        with self.assertRaisesRegex(ValueError, "missing training epochs"):
            self.audit()
        self.path().unlink()
        with self.assertRaisesRegex(ValueError, "ordinary non-symlink"):
            self.audit()

    def test_source_is_never_executed_and_changed_wiring_is_not_misinterpreted(self):
        wiring = D.source_wiring(SOURCE)
        self.assertFalse(wiring["factors_independently_varied"])
        with self.assertRaisesRegex(ValueError, "unsupported source wiring"):
            D.source_wiring(SOURCE.replace("seed + 911", "seed + 912"))

    def test_seed_sets_must_be_disjoint_and_integer(self):
        config = copy.deepcopy(self.config)
        config["seeds"].append(11)
        with self.assertRaisesRegex(ValueError, "overlap"):
            D.validate_config(config)
        config = copy.deepcopy(self.config)
        config["seeds"][0] = True
        with self.assertRaisesRegex(ValueError, "integer"):
            D.validate_config(config)

    def test_misleading_epoch_or_cost_booleans_rejected(self):
        for path in (("curve", 0, "epoch"), ("train_wall_seconds",)):
            record = self.record()
            target = record
            for item in path[:-1]:
                target = target[item]
            target[path[-1]] = True
            with self.assertRaises(ValueError):
                D.validate_record(record, "gru", 202, self.config)


if __name__ == "__main__":
    unittest.main()
