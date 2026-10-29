"""Small synthetic replay/rollback tests; no MNIST asset or holdout access."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import unittest

import numpy as np
import torch
from torch import nn

from experiments.multimodal_output_portfolio.v6.data import SourceCorpus, SourceSplit
from .architecture import TrainablePortfolio
from .architecture_bank import build_instance, fit_architecture, replay_registered_row
from .architecture_features import measure
from .architecture_kernel import ArchitecturePlan, Context, Work, training_batches, update
from .architecture_state import capture, checkpoint_bytes, digest, restore
from .architecture_training import optimizer_for, warmup


REFERENCE_ROOT = Path(__file__).resolve().parents[2]


class SyntheticObserver(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("centers", torch.linspace(0., 1., 10))

    def forward(self, pixels):
        return -(pixels.mean((1, 2, 3)).unsqueeze(1) - self.centers.unsqueeze(0)).square()


class MemoryStore:
    def __init__(self, work):
        self.work, self.entries, self.artifacts = work, {}, []

    def check(self):
        pass

    def bytes(self, name, payload, failure_record=False):
        if name in self.entries:
            raise AssertionError("Test evidence overwritten")
        self.entries[name] = payload
        result = {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        self.artifacts.append(result)
        return result

    def json(self, name, value, failure_record=False):
        return self.bytes(name, json.dumps(value, allow_nan=False).encode())

    def json_gzip(self, name, value, failure_record=False):
        return self.bytes(name, gzip.compress(json.dumps(value, allow_nan=False).encode(), mtime=0))

    def checkpoint(self, name, state, metadata, failure_record=False):
        return self.bytes(name, checkpoint_bytes(state, metadata))


def synthetic_corpus():
    splits = {}
    generator = torch.Generator().manual_seed(77)
    for role in ("fit_gradient", "fit_rehearsal", "fit_probe", "fit_guard"):
        pixels = torch.randint(256, (8, 1, 28, 28), generator=generator, dtype=torch.uint8)
        labels = torch.arange(8) % 10
        ids = tuple(f"synthetic:{role}:{index}" for index in range(8))
        hashes = tuple(hashlib.sha256(row.numpy().tobytes()).hexdigest() for row in pixels)
        splits[role] = SourceSplit(pixels, labels, ids, hashes)
    return SourceCorpus(splits, {"synthetic": True})


class ArchitectureKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)

    def setup_case(self, mode="ordinary"):
        plan = ArchitecturePlan.from_mapping({"hidden": 16, "warmup_steps": 5, "steps": 3,
                                             "macro_steps": 1, "batch_size": 2, "rehearsal_batch_size": 1,
                                             "panel_batch_size": 2, "development_seeds": [701],
                                             "evaluation_seeds": [801]})
        corpus, work = synthetic_corpus(), Work()
        model = TrainablePortfolio(reference_root=REFERENCE_ROOT, mode=mode, seed=701, hidden=16)
        store = MemoryStore(work)
        entry = warmup(model, corpus, plan, 701, store, {"synthetic": True}, "synthetic")
        record = torch.load(io.BytesIO(gzip.decompress(store.entries[entry["checkpoint"]["path"]])), weights_only=True)
        optimizer = optimizer_for(model, plan)
        restore(model, optimizer, record["state"])
        context = Context(model, corpus, SyntheticObserver().eval(), 701, plan, work)
        return plan, corpus, work, model, optimizer, context, record, store

    def test_complete_serialization_preserves_momentum_rng_and_next_update(self):
        plan, corpus, work, model, optimizer, context, record, store = self.setup_case()
        saved = capture(model, optimizer)
        self.assertTrue(all(value is None for value in saved["gradients"].values()))
        self.assertTrue(any("momentum_buffer" in value for value in saved["optimizer"]["state"].values()))
        packed = checkpoint_bytes(saved, {"synthetic": True})
        reread = torch.load(io.BytesIO(gzip.decompress(packed)), weights_only=True)["state"]
        torch.rand(7)
        random.random()
        np.random.random()
        restore(model, optimizer, reread)
        self.assertEqual(digest(saved), digest(capture(model, optimizer)))
        batches = training_batches(corpus, plan, 701, 7000, 0)
        update(model, optimizer, context.teacher, batches, 73, ("couple",), 1., plan, work)
        terminal = digest(capture(model, optimizer))
        restore(model, optimizer, reread)
        update(model, optimizer, context.teacher, batches, 73, ("couple",), 1., plan, work)
        self.assertEqual(terminal, digest(capture(model, optimizer)))

    def test_zero_action_and_rejected_candidate_restore_complete_state_but_charge_work(self):
        plan, corpus, work, model, optimizer, context, record, store = self.setup_case()
        work.phase = "synthetic_guard"
        before = digest(capture(model, optimizer))
        zero = context.block(model, optimizer, 0, 0, 7000)
        self.assertEqual(before, zero["candidate"])
        self.assertEqual(before, zero["after"])
        self.assertTrue(zero["accepted"])
        real_hard = context.hard

        def reject(current_model, panel, role):
            result = real_hard(current_model, panel, role)
            if role == "candidate_guard":
                result["values"] = result["values"] - 10.
                result["mean"] -= 10.
            return result

        context.hard = reject
        rejected = context.block(model, optimizer, 0, 2, 7000)
        self.assertFalse(rejected["accepted"])
        self.assertNotEqual(rejected["candidate"], before)
        self.assertEqual(rejected["after"], before)
        self.assertEqual(work.values["synthetic_guard.scheduled_gradient_microsteps"], 2)
        self.assertEqual(work.values["synthetic_guard.optimizer_steps"], 1)
        self.assertEqual(work.values["synthetic_guard.discarded_microsteps"], 1)

    def test_field_measurement_is_finite_and_restores_state_without_a_future_tail(self):
        for mode in ("ordinary", "dual"):
            with self.subTest(mode=mode):
                plan, corpus, work, model, optimizer, context, record, store = self.setup_case(mode)
                before = digest(capture(model, optimizer))
                field, current, receipt = measure(context, model, optimizer, 0, 7000)
                self.assertEqual(field.shape, (12,))
                self.assertTrue(np.isfinite(field).all())
                self.assertEqual(before, digest(capture(model, optimizer)))
                self.assertEqual(field[4], 0.)
                self.assertEqual(field[6], 0.)
                self.assertTrue(receipt["state_restored"])
                self.assertFalse(any("reference_tail" in key for key in work.values))

    def test_bank_tail_pairing_head_partitions_and_independent_reconstruction(self):
        plan, corpus, work, model, optimizer, context, record, store = self.setup_case()
        rows = build_instance(context, model, optimizer, record["state"], store, "synthetic-bank")
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(row["advantages"][2] == 0. for row in rows))
        head, metadata = fit_architecture(rows, plan, store, "synthetic-head")
        self.assertEqual((head["fit_count"], head["calibration_count"]), (18, 6))
        self.assertEqual(head["coefficients"].shape, (12, 4))
        target = next(row for row in rows if row["schedule"] == 7000
                      and row["prefix"] == "balanced" and row["decision"] == 2)
        row = json.loads(gzip.decompress(store.entries[target["artifact"]["path"]]))
        replay_model = TrainablePortfolio(reference_root=REFERENCE_ROOT, mode="ordinary", seed=701, hidden=16)
        replay_optimizer = optimizer_for(replay_model, plan)
        restore(replay_model, replay_optimizer, record["state"])
        replay_context = Context(replay_model, corpus, SyntheticObserver().eval(), 701, plan, work)
        result = replay_registered_row(replay_context, replay_model, replay_optimizer, record["state"],
                                      row, store, "synthetic-replay.json.gz")
        self.assertTrue(result["passed"])
        self.assertEqual(work.values["bank.scheduled_gradient_microsteps"], 216)
        self.assertEqual(work.values["replay_audit.scheduled_gradient_microsteps"], 3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-root", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    REFERENCE_ROOT = args.reference_root
    unittest.main(argv=[__file__, *remaining])
