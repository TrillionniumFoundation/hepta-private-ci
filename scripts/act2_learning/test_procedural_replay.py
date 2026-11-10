"""Actual replay purpose, paired-permutation and denied-effect checks."""

import argparse
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import procedural_replay as replay


class ProceduralReplayTests(unittest.TestCase):
    archive = None

    @classmethod
    def setUpClass(cls):
        cls.records, cls.allowed, _ = replay.load_training(cls.archive)

    def test_factual_confirmation_missing_labels_and_nonfinite_records_rejected(self):
        mutations = [
            ("purpose", "factual_memory"),
            ("split", "CONFIRMATION"),
            ("task_id", "confirm/forbidden"),
            ("source_sha256", "wrong"),
            ("actions", []),
            ("actions", [None] * len(self.records[0]["actions"])),
        ]
        for key, value in mutations:
            record = {**self.records[0], key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                replay.replay_arrays([record], self.allowed, "ordered")
        record = copy.deepcopy(self.records[0])
        record["features"][0][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            replay.replay_arrays([record], self.allowed, "ordered")
        with self.assertRaisesRegex(ValueError, "repeated"):
            replay.replay_arrays(
                [self.records[0], self.records[0]], self.allowed, "ordered"
            )

    def test_valid_source_label_cannot_authorize_changed_train_content(self):
        changed_action = copy.deepcopy(self.records[0])
        changed_action["actions"][0] = (
            "stop" if changed_action["actions"][0] != "stop" else "inspect"
        )
        changed_feature = copy.deepcopy(self.records[0])
        changed_feature["features"][0][0] += 1
        for record in (changed_action, changed_feature):
            with self.assertRaisesRegex(ValueError, "pinned TRAIN content"):
                replay.fit_replay([record], self.allowed, "ordered", 700, epochs=1)

    def test_shuffle_preserves_each_observation_label_pair_and_mask(self):
        ordered = replay.replay_arrays(self.records, self.allowed, "ordered")
        shuffled = replay.replay_arrays(self.records, self.allowed, "shuffled")
        np.testing.assert_array_equal(ordered[2], shuffled[2])
        changed = 0
        for index, item in enumerate(shuffled[3]):
            permutation = item["permutation"]
            length = len(permutation)
            np.testing.assert_array_equal(
                shuffled[0][index, :length], ordered[0][index, permutation]
            )
            np.testing.assert_array_equal(
                shuffled[1][index, :length], ordered[1][index, permutation]
            )
            changed += permutation != list(range(length))
        self.assertGreater(changed, 0)

    def test_offline_fits_complete_while_all_sqlite_and_destination_effects_are_denied(
        self,
    ):
        blocked = AssertionError("offline replay tried a tool effect")
        with (
            patch("sqlite3.connect", side_effect=blocked) as sql,
            patch("sqlite_destination.Destination", side_effect=blocked) as destination,
        ):
            for order in ("ordered", "shuffled"):
                model, receipt = replay.fit_replay(
                    self.records, self.allowed, order, 700, epochs=2
                )
                self.assertEqual(2, receipt["optimizer_calls"])
                self.assertTrue(
                    all(np.isfinite(value).all() for value in model.p.values())
                )
            sql.assert_not_called()
            destination.assert_not_called()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    arguments, remaining = parser.parse_known_args()
    ProceduralReplayTests.archive = arguments.archive.resolve()
    unittest.main(argv=[__file__] + remaining)
