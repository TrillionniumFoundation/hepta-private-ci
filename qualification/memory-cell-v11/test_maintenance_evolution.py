"""Executable lifecycle tests; toy-fit outcomes are not research advantage claims."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from evolution import Action, Budget, Evaluation, EvolutionExecutor, Expert, Network, Prices
from maintenance import ReplayBackpressure, SQLiteReplayStore, StaleTraining


def record(key, version=1, target=1, source=None):
    return dict(key=key, type="semantic", version=version, query=f"read {key}",
                target_text=str(target), target=target, source_ids=[source or f"source:{key}:{version}"])


class PersistentReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def artifact(self, name, batch):
        path = self.root / f"{name}.json"
        path.write_text(json.dumps([r["target_text"] for r in batch.records]))
        return path

    def test_revocation_survives_restart_and_invalidates_checkpoint_descendants(self):
        path = self.root / "memory.sqlite"
        store = SQLiteReplayStore(path, replay_capacity=4, pending_capacity=8, max_batch_size=8)
        first = store.append(record("parent"))
        store.append(record("derived"), parent_ids=[first])
        batch = store.claim_batch(new_count=2, replay_count=0)
        store.commit_training(batch, "first", self.artifact("first", batch))
        store.append(record("independent"))
        batch = store.claim_batch(new_count=1, replay_count=2)
        store.commit_training(batch, "second", self.artifact("second", batch), parent_checkpoint="first")
        self.assertTrue(store.checkpoint_is_valid("second"))
        store.close()
        store = SQLiteReplayStore(path, replay_capacity=4, pending_capacity=8, max_batch_size=8)
        self.assertEqual(store.revoke_source("source:parent:1"), 2)
        self.assertEqual([store.current(k, "semantic") for k in ("parent", "derived")], [None, None])
        self.assertFalse(store.checkpoint_is_valid("first"))
        self.assertFalse(store.checkpoint_is_valid("second"))
        store.close()
        store = SQLiteReplayStore(path, replay_capacity=4, pending_capacity=8, max_batch_size=8)
        with self.assertRaises(ValueError):
            store.append(record("new-name", source="source:parent:1"))
        with self.assertRaises(ValueError):
            store.append(record("new-derived"), parent_ids=[first])
        store.delete_key("independent", "semantic")
        with self.assertRaises(ValueError):
            store.append(record("independent", version=2))
        self.assertEqual(store.stats()["replay_count"], 0)
        store.close()

    def test_backpressure_rollback_crash_lease_and_stale_fit(self):
        path = self.root / "memory.sqlite"
        store = SQLiteReplayStore(path, replay_capacity=2, pending_capacity=2, max_batch_size=4)
        store.append(record("a"))
        store.append(record("b"))
        with self.assertRaises(ReplayBackpressure):
            store.append(record("c"))
        self.assertEqual(store.stats()["records_count"], 2)
        with patch("maintenance.time.time", return_value=100):
            crashed = store.claim_batch(new_count=2, replay_count=0, lease_seconds=10)
        store.close()
        store = SQLiteReplayStore(path, replay_capacity=2, pending_capacity=2, max_batch_size=4)
        with patch("maintenance.time.time", return_value=111):
            resumed = store.claim_batch(new_count=2, replay_count=0)
            self.assertEqual(crashed.pending_ids, resumed.pending_ids)
            with self.assertRaises(StaleTraining):
                store.commit_training(crashed, "crashed", self.artifact("crashed", crashed))
            store.append(record("a", version=2, target=7))
            with self.assertRaises(StaleTraining):
                store.commit_training(resumed, "stale", self.artifact("stale", resumed))
        self.assertEqual(store.current("a", "semantic")["target"], 7)
        self.assertEqual([(r["key"], r["version"]) for r in store.active_page(limit=4)], [("b", 1), ("a", 2)])
        store.close()

    def test_bounded_hot_sampling_and_artifact_identity(self):
        store = SQLiteReplayStore(self.root / "memory.sqlite", replay_capacity=7,
                                  pending_capacity=512, max_batch_size=16)
        for index in range(300):
            store.append(record(f"k{index}"))
        plan = store.db.execute("""EXPLAIN QUERY PLAN SELECT id FROM records INDEXED BY active_priority
            WHERE status='active' ORDER BY priority,id LIMIT 7""").fetchall()
        self.assertTrue(any("active_priority" in row[3] for row in plan))
        batch = store.claim_batch(new_count=5, replay_count=7)
        self.assertLessEqual(len(batch.records), 12)
        self.assertEqual(len({r["record_id"] for r in batch.records}), len(batch.records))
        path = self.artifact("bounded", batch)
        store.commit_training(batch, "bounded", path)
        self.assertTrue(store.checkpoint_is_valid("bounded"))
        path.write_text("tampered checkpoint")
        self.assertFalse(store.checkpoint_is_valid("bounded"))
        stats = store.stats()
        self.assertEqual((stats["records_count"], stats["replay_count"], stats["pending_count"]), (300, 7, 295))
        self.assertGreater(stats["archive_payload_bytes"], stats["replay_payload_bytes"])
        store.close()


class MeanModel:
    def __init__(self, value):
        self.weights = np.asarray([value], dtype=np.float64)


class ExecutedEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fits = []

    def tearDown(self):
        self.temp.cleanup()

    def train(self, model, records, *, deadline, options):
        if time.perf_counter() >= deadline:
            raise TimeoutError("training deadline")
        model.weights[:] = np.mean([r["target"] for r in records])
        self.fits.append(tuple(r["key"] for r in records))
        return dict(records=len(records), mean=float(model.weights[0]))

    def save(self, model, path):
        path = Path(path)
        path.mkdir()
        (path / "weights.json").write_text(json.dumps(model.weights.tolist()))

    def load(self, path):
        return MeanModel(json.loads((Path(path) / "weights.json").read_text())[0])

    def evaluate(self, network, rows):
        rewards = []
        for row in rows:
            expert = network.experts.get(network.routes.get(row["key"]))
            prediction = int(round(float(expert.model.weights[0]))) if expert and expert.awake else row["target"]
            rewards.append(float(prediction == row["target"]))
        return Evaluation(tuple(range(len(rows))), tuple(rewards))

    def executor(self, name, **kwargs):
        return EvolutionExecutor(self.root / name, train_model=self.train, evaluate_network=self.evaluate,
                                 save_model=self.save, load_model=self.load, model_bytes=lambda m: m.weights.nbytes, **kwargs)

    def test_real_split_and_merge_fit_do_not_outrank_equal_fixed_experts(self):
        rows = [record("a", target=0), record("b", target=1)]
        validation = rows * 20
        original = Network({"one": Expert("one", MeanModel(0.5))}, {"a": "one", "b": "one"})
        fixed = Network({"fa": Expert("fa", MeanModel(0)), "fb": Expert("fb", MeanModel(1))}, {"a": "fa", "b": "fb"})
        executor = self.executor("structures")
        selected, split = executor.execute(Action("split", ("one",), ("left", "right"), {"a": "left", "b": "right"}),
                                           original, rows, validation=validation, controls={"fixed_experts": fixed, "capacity": original})
        self.assertIs(selected, original)
        self.assertFalse(split.report["admitted"])
        self.assertIn("no_measured_net_gain_over_fixed_experts", split.report["rejection_reasons"])
        self.assertEqual(self.fits, [("a",), ("b",)])
        self.assertEqual(float(original.experts["one"].model.weights[0]), 0.5)
        self.assertTrue(all(e.checkpoint for e in split.network.experts.values()))
        _, merged = executor.execute(Action("merge", ("left", "right"), ("merged",)), split.network, rows, validation=validation)
        self.assertEqual(self.fits[-1], ("a", "b"))
        self.assertFalse(merged.report["admitted"])
        costs = executor.exploration_resources()
        self.assertEqual((costs["attempted_actions"], costs["rejected_actions"]), (2, 2))
        self.assertGreater(costs["training_seconds"], 0)
        self.assertGreater(costs["retained_shadow_artifact_bytes"], 0)
        self.assertEqual(costs["total_retained_directory_bytes"],
                         sum(p.stat().st_size for p in executor.output.rglob("*") if p.is_file()))
        executor.close()

    def test_capacity_sleep_wake_and_local_migration_are_executed(self):
        rows = [record("a", target=1)]
        original = Network({"one": Expert("one", MeanModel(0))}, {"a": "one"})
        executor = self.executor("lifecycle", prices=Prices(active_memory_per_byte=0.001))
        grown, result = executor.execute(Action("capacity", ("one",), ("large",)), original, rows, validation=rows * 10)
        self.assertTrue(result.report["admitted"])
        sleeping, asleep = executor.execute(Action("sleep", ("large",)), grown, [], validation=rows * 10)
        self.assertTrue(asleep.report["admitted"])
        self.assertFalse(sleeping.experts["large"].awake)
        _, awake = executor.execute(Action("wake", ("large",)), sleeping, [], validation=rows * 10)
        self.assertEqual(float(awake.network.experts["large"].model.weights[0]), 1)
        self.assertFalse(awake.report["admitted"])
        _, moved = executor.execute(Action("migrate", ("large",), target_host="local-second-slot"), grown, [], validation=rows * 10)
        self.assertGreater(moved.report["resources"]["transfer_bytes"], 0)
        self.assertEqual(moved.network.experts["large"].host, "local-second-slot")
        self.assertIn("no cross-host", moved.report["migration_scope"])
        self.assertEqual(executor.ledger.execute("SELECT count(*) FROM decisions").fetchone()[0], 4)
        executor.close()

    def test_over_budget_candidate_is_persisted_and_never_promoted(self):
        original = Network({"one": Expert("one", MeanModel(0))}, {"a": "one"})
        executor = self.executor("budget", budget=Budget(max_active_bytes=1))
        selected, result = executor.execute(Action("capacity", ("one",), ("large",)), original,
                                            [record("a")], validation=[record("a")] * 2)
        self.assertIs(selected, original)
        self.assertFalse(result.report["admitted"])
        self.assertEqual(self.fits, [])
        self.assertEqual(executor.ledger.execute("SELECT admitted FROM decisions").fetchone()[0], 0)
        executor.close()

    def test_storage_cost_uses_actual_checkpoint_bytes_and_missing_controls_reject(self):
        model = MeanModel(1)
        checkpoint = self.root / "real-checkpoint"
        self.save(model, checkpoint)
        (checkpoint / "metadata.json").write_text(json.dumps({"provenance": "x" * 1000}))
        network = Network({"one": Expert("one", model, checkpoint=str(checkpoint), artifact_bytes=1)}, {"a": "one"})
        executor = self.executor("cost", prices=Prices(storage_per_byte=0.01, active_memory_per_byte=0.02))
        resources = executor.resources(network)
        disk_bytes = sum(p.stat().st_size for p in checkpoint.iterdir())
        self.assertEqual(resources["checkpoint_disk_bytes"], disk_bytes)
        self.assertGreater(disk_bytes, resources["active_bytes"])
        self.assertAlmostEqual(executor._cost(resources, Evaluation((1, 2), (1., 1.))), disk_bytes * 0.01 + 8 * 0.02)
        unsaved = Network({"one": Expert("one", MeanModel(0))}, {"a": "one"})
        _, result = executor.execute(Action("capacity", ("one",), ("new",)), unsaved,
                                     [record("a")], validation=[record("a")] * 2)
        self.assertIn("incumbent_storage_accounting_incomplete", result.report["rejection_reasons"])
        self.assertFalse(result.report["admitted"])
        executor.close()


if __name__ == "__main__":
    unittest.main()
