"""Behavioral checks independent of the new learned control heads."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .task import Bellman, ContentAdapter, Owner, packet, save, score_terminal


class FixtureAdapter:
    setup = {"checkpoint_sha256": "fixture-identity"}

    def __init__(self):
        self.reads = []

    def read(self, path):
        self.reads.append(str(path))
        raw = Path(path).read_bytes()
        observation = json.loads(raw)["symbols"][0]
        return dict(observation=observation, payload_bytes=len(raw),
                    io_wall_seconds=0., feature_wall_seconds=0.,
                    content_wall_seconds=0., total_cpu_seconds=0.)


def make_fixture(folder):
    meta = dict(id="fixture", deadline=6, budget=3,
                reliability=[[.8]*6, [.8]*6], price=[[.1]*6, [.1]*6],
                duration=[.2, .5, .7, .4, .3, .6],
                packets=[[f"job{j}_tick{t}.json" for t in range(6)] for j in range(2)])
    save(folder / "public.json", meta)
    save(folder / "evaluator_labels.json", dict(labels=[1, 0]))
    for job in range(2):
        for tick in range(6):
            save(folder / meta["packets"][job][tick], packet(1-job, 9000000+job*6+tick))
    return meta


class TaskTests(unittest.TestCase):
    def test_real_inherited_decoder_is_executed(self):
        adapter = ContentAdapter()
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a.json", Path(directory) / "b.json"
            save(a, packet(0, 91827001))
            save(b, packet(1, 91827001))
            x, y = adapter.read(a), adapter.read(b)
            self.assertNotEqual(x["payload_sha256"], y["payload_sha256"])
            self.assertGreater(np.max(np.abs(np.asarray(x["logits"])-y["logits"])), 1e-6)
            self.assertEqual(adapter.setup["frozen_parameter_count"], 6217)
            self.assertGreater(x["total_cpu_seconds"], 0.)

    def test_skip_and_stop_do_not_read_packets_or_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            meta = make_fixture(folder)
            (folder / meta["packets"][0][0]).unlink()
            labels = folder / "evaluator_labels.json"
            labels.rename(folder / "hidden_labels.json")
            adapter = FixtureAdapter()
            owner = Owner(folder, adapter, [[.9, .1], [.1, .9]], 1., .1)
            owner.act("SKIP")
            owner.act("STOP")
            self.assertEqual(adapter.reads, [])
            self.assertAlmostEqual(owner.charged_cost, .02)
            with self.assertRaises(RuntimeError):
                owner.act("READ")

    def test_read_reset_refractory_and_recovery_share_one_state(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_fixture(folder)
            owner = Owner(folder, FixtureAdapter(), [[.9, .1], [.1, .9]], 1., .1)
            owner.act("READ")
            self.assertAlmostEqual(owner.posterior, .74)
            snap = copy.deepcopy(owner.snapshot())
            restored = Owner(folder, FixtureAdapter(), [[.9, .1], [.1, .9]], 1., .1)
            restored.restore(snap)
            for action in ("FIRE", "READ", "FIRE"):
                self.assertEqual(owner.act(action), restored.act(action))
            self.assertEqual(owner.snapshot(), restored.snapshot())
            self.assertEqual((owner.job, owner.tick, owner.posterior, owner.budget), (2, 6, .5, 1))
            self.assertAlmostEqual(owner.task_elapsed, 2.7)
            self.assertAlmostEqual(score_terminal(owner)["utility"], 1.53)

    def test_labels_cannot_be_scored_before_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_fixture(folder)
            owner = Owner(folder, FixtureAdapter(), [[.9, .1], [.1, .9]], 1.)
            with self.assertRaises(RuntimeError):
                score_terminal(owner)

    def test_snapshot_does_not_alias_live_mutable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_fixture(folder)
            owner = Owner(folder, FixtureAdapter(), [[.9, .1], [.1, .9]], 1.)
            snapshot = owner.snapshot()
            frozen = json.dumps(snapshot, sort_keys=True)
            owner.act("READ")
            self.assertEqual(json.dumps(snapshot, sort_keys=True), frozen)
            snapshot["state"]["counts"]["READ"] = 100
            self.assertEqual(owner.counts["READ"], 1)

    def test_failed_read_is_retained_and_charged(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            meta = make_fixture(folder)
            (folder / meta["packets"][0][0]).unlink()
            owner = Owner(folder, FixtureAdapter(), [[.9, .1], [.1, .9]], 1., .1)
            with self.assertRaises(FileNotFoundError):
                owner.act("READ")
            self.assertTrue(owner.terminal)
            self.assertEqual(owner.events[-1]["status"], "failed_read")
            self.assertEqual(owner.counts["failed_read_attempts"], 1)
            self.assertEqual(owner.counts["content_invocations"], 0)
            self.assertAlmostEqual(owner.charged_cost, .12)

    def test_one_read_bellman_matches_independent_hand_calculation(self):
        meta = dict(deadline=3, budget=1, reliability=[[.8]*3]*2,
                    price=[[.1]*3]*2, duration=[.2, .5, .7])
        oracle = Bellman(meta, [[.9, .1], [.1, .9]], 1., .1)
        # Last job: READ delivers posterior .74/.26, then FIRE. No future jobs.
        np.testing.assert_allclose(oracle.q(1, 1, 1, .5), [0., -.05, .26, -.12], atol=1e-14)

    def test_changed_recovery_identity_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_fixture(folder)
            owner = Owner(folder, FixtureAdapter(), [[.9, .1], [.1, .9]], 1.)
            state = owner.snapshot()
            state["multiplier"] = 2.
            with self.assertRaises(ValueError):
                owner.restore(state)


if __name__ == "__main__":
    unittest.main()
