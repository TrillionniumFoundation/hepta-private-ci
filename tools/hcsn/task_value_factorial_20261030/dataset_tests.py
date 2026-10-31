"""Causality, public-state sufficiency and actual-owner collection checks."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .dataset import FEATURE_NAMES, MAX_DEADLINE, collect, decode_features, feature_vector, state_record
from .task import ACTIONS, Bellman, Owner
from .task_tests import FixtureAdapter, make_fixture


class DatasetTests(unittest.TestCase):
    def test_roundtrip_preserves_both_jobs_and_bellman_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_fixture(folder)
            owner = Owner(folder, FixtureAdapter(), [[.9, .1], [.2, .8]], 1.3, .04)
            owner.meta["reliability"][1][4] = .61
            owner.meta["price"][1][4] = .47
            owner.act("READ")
            vector = feature_vector(owner)
            self.assertEqual((len(vector), MAX_DEADLINE), (62, 10))
            self.assertEqual(len(set(FEATURE_NAMES)), 62)
            decoded = decode_features(vector)
            self.assertEqual(decoded["state"], dict(job=owner.job, tick=owner.tick,
                budget=owner.budget, posterior=owner.posterior))
            for key in ("deadline", "budget", "reliability", "price", "duration"):
                self.assertEqual(decoded["meta"][key], owner.meta[key])
            first = Bellman(owner.meta, owner.confusion, owner.multiplier, owner.latency_price)
            second = Bellman(decoded["meta"], decoded["confusion"],
                             decoded["multiplier"], decoded["latency_price"])
            state = decoded["state"]
            np.testing.assert_allclose(first.q(**state), second.q(**state), atol=1e-14)
            before = vector.copy()
            owner.meta["price"][1][4] += .01
            after = feature_vector(owner)
            changed = np.flatnonzero(before != after).tolist()
            self.assertEqual([FEATURE_NAMES[i] for i in changed], ["price_1_4"])

    def test_state_record_needs_no_unread_files_labels_or_teacher(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            meta = make_fixture(folder)
            adapter = FixtureAdapter()
            owner = Owner(folder, adapter, [[.9, .1], [.1, .9]], 1., .1)
            for names in meta["packets"]:
                for name in names:
                    (folder / name).unlink()
            (folder / "evaluator_labels.json").unlink()
            before = owner.snapshot()
            history = [dict(driver=.12, duration=.3, reset=True)]
            record = state_record(owner, history)
            self.assertEqual(owner.snapshot(), before)
            self.assertEqual(adapter.reads, [])
            self.assertNotIn("q", record)
            self.assertNotIn("q_myopic", record)
            self.assertNotIn("next_observation", record)
            self.assertAlmostEqual(record["driver"], .12)
            self.assertEqual(record["horizon"], .2)
            history[0]["driver"] = 99.
            self.assertAlmostEqual(record["history"][0]["driver"], .12)

    def test_value_columns_differ_only_by_next_job_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_fixture(folder)
            owner = Owner(folder, FixtureAdapter(), [[.9, .1], [.1, .9]], 1., .1)
            full = Bellman(owner.meta, owner.confusion, 1., .1)
            myopic = Bellman(owner.meta, owner.confusion, 1., .1, future=False)
            record = state_record(owner, [], full, myopic)
            self.assertGreater(record["q"][3], record["q_myopic"][3])
            self.assertAlmostEqual(record["q"][3]-record["q_myopic"][3],
                                   full.value(1, 2, owner.budget, .5))
            owner.act("FIRE")
            final_job = state_record(owner, [], full, myopic)
            np.testing.assert_allclose(final_job["q"], final_job["q_myopic"], atol=1e-14)

    def test_collection_keeps_causal_intervals_train_only_labels_and_real_costs(self):
        protocol = dict(data_seed_base=1730000000, deadlines=[6], read_budgets=[2],
                        packet_reliabilities=[.8], packet_prices=[.1],
                        step_durations=[.2, .5], packet_length=32,
                        behavior_action_weights=[0., 0., 1., 0.])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            adapter = FixtureAdapter()
            train = collect(folder / "train", "train", 3, 3, protocol, adapter,
                            [[.9, .1], [.1, .9]], 1., .1)
            validation = collect(folder / "validation", "validation", 3, 2, protocol,
                                 adapter, [[.9, .1], [.1, .9]], 1., .1)
            train_ids = {row["session"] for row in train["rows"]}
            self.assertTrue(train_ids.isdisjoint(row["session"] for row in validation["rows"]))
            self.assertTrue(set(train["cohort"]["payload_hashes"]).isdisjoint(
                validation["cohort"]["payload_hashes"]))
            for dataset in (train, validation):
                self.assertGreater(dataset["costs"]["generation_wall_seconds"], 0.)
                self.assertGreater(dataset["costs"]["collection_cpu_seconds"], 0.)
                for episode in dataset["episodes"]:
                    start, length = episode["first_row"], episode["row_count"]
                    rows = dataset["rows"][start:start+length]
                    history = []
                    for row, event in zip(rows, episode["events"], strict=True):
                        self.assertEqual(row["history"], history)
                        self.assertTrue(row["feasible"][ACTIONS.index(row["chosen_action"])])
                        self.assertEqual(row["chosen_action"], event["action"])
                        self.assertGreater(row["behavior_probability"], 0.)
                        for target in ("q", "q_myopic"):
                            self.assertEqual(len(row[target]), 4)
                            self.assertTrue(np.all(np.isfinite(row[target])))
                            self.assertTrue(all(q == 0 for q, legal in zip(row[target], row["feasible"]) if not legal))
                        observed = dataset["split"] == "train" and event["action"] == "READ"
                        self.assertEqual("next_observation" in row, observed)
                        if observed:
                            self.assertEqual(row["next_observation"], event["observation"])
                        history.append(dict(driver=row["driver"], duration=event["duration"],
                                            reset=event["action"] == "FIRE"))
                    # The first READ updates posterior; its elapsed interval
                    # must nevertheless use the previous, public-only drift.
                    self.assertEqual(rows[0]["chosen_action"], "READ")
                    self.assertAlmostEqual(rows[1]["history"][0]["driver"], .12)
                    self.assertNotAlmostEqual(rows[1]["driver"], .12)
                    read_events = [event for event in episode["events"] if event["action"] == "READ"]
                    self.assertEqual(episode["counts"]["content_invocations"], len(read_events))
                    self.assertEqual(episode["counts"]["payload_bytes"], sum(e["payload_bytes"] for e in read_events))
                    self.assertAlmostEqual(episode["task_elapsed"], sum(e["duration"] for e in episode["events"]))
                    self.assertAlmostEqual(episode["score"]["charged_cost"],
                        .1*len(read_events)+.1*episode["task_elapsed"])
                    self.assertTrue(Path(episode["trace"]).is_file())
                    self.assertTrue(json.loads(Path(episode["trace"]).read_text())["state"]["terminal"])
            self.assertEqual(len(adapter.reads), sum(e["counts"]["READ"] for d in (train, validation) for e in d["episodes"]))

    def test_test_collection_is_rejected_before_generating_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                collect(directory, "test", 0, 1, {}, FixtureAdapter(), [[.9, .1], [.1, .9]], 1.)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
