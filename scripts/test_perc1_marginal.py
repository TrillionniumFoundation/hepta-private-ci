"""Behavioral checks for identical-prefix, final-outcome marginal replay."""

import base64
import copy
from pathlib import Path
import tempfile
import unittest

from perc1.experiment import FixtureExecutor
from perc1.fixture import smoke
from perc1.schema import Dataset, Invalid, load, sha
from perc1_marginal import compare_pair


class MarginalReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        smoke(cls.root)
        cls.frozen = load(cls.root / "manifest.json")
        cls.dataset = Dataset(load(cls.root / "dataset.json"), cls.root)
        cls.evaluator = load(cls.root / "evaluator.json")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def make_pair(self, source_index=2):
        episode = self.dataset.episodes["confirmation.missing_document"]
        left = FixtureExecutor(self.frozen, self.dataset, episode, 11, "dense_active")
        left.attempt(episode["initial_ids"][0])
        right = FixtureExecutor(self.frozen, self.dataset, episode, 11, "dense_active")
        right.attempt(episode["initial_ids"][0])
        right.attempt(episode["source_ids"][source_index])
        # The same terminal rule receives only each branch's observed raw bytes.
        for executor in (left, right):
            for step in executor.trace["steps"]:
                if step["observation"] is None:
                    continue
                raw = base64.b64decode(step["observation"]["raw_base64"]).decode()
                candidates = [
                    line[7:] for line in raw.splitlines() if line.startswith("answer:")
                ]
                if candidates:
                    executor.trace["answer"] = {
                        "text": candidates[0],
                        "fields": {"critical": candidates[0]},
                        "evidence_ids": [step["proposal"]["source_id"]],
                    }
        return {
            "schema": "perc1.marginal-pair.v1",
            "world_snapshot_sha256": sha(self.dataset.value),
            "continuation_sha256": self.frozen["controller"]["sha256"],
            "inference_seed": 19,
            "without": left.trace,
            "with": right.trace,
        }

    def test_extra_evidence_changes_final_answer_and_charges_cost(self):
        result = compare_pair(
            self.make_pair(), self.frozen, self.dataset, self.evaluator
        )
        self.assertEqual(
            (result["task_success_change"], result["critical_fidelity_change"]), (1, 1)
        )
        self.assertGreater(result["incremental_cost"], 0)
        self.assertEqual(
            (result["status"], result["scientific_qualified"], result["net_utility"]),
            ("HOLD", False, None),
        )

    def test_distractor_observation_has_no_task_gain(self):
        result = compare_pair(
            self.make_pair(source_index=1), self.frozen, self.dataset, self.evaluator
        )
        self.assertEqual(result["task_success_change"], 0)
        self.assertGreater(result["incremental_cost"], 0)

    def test_changed_prefix_and_scope_are_rejected(self):
        for field, value in [("seed", 29), ("arm", "global_active")]:
            pair = self.make_pair()
            pair["with"][field] = value
            with self.subTest(field=field), self.assertRaises(Invalid):
                compare_pair(pair, self.frozen, self.dataset, self.evaluator)
        pair = self.make_pair()
        pair["without"]["steps"][0]["proposal"]["reason"] = "different actor prefix"
        with self.assertRaises(Invalid):
            compare_pair(pair, self.frozen, self.dataset, self.evaluator)

    def test_world_and_continuation_changes_are_rejected(self):
        for key in ("world_snapshot_sha256", "continuation_sha256"):
            pair = self.make_pair()
            pair[key] = sha("different")
            with self.subTest(key=key), self.assertRaises(Invalid):
                compare_pair(pair, self.frozen, self.dataset, self.evaluator)

    def test_canary_in_final_answer_is_rejected(self):
        pair = self.make_pair()
        pair["with"]["answer"]["text"] = self.evaluator["canaries"][0]
        with self.assertRaises(Invalid):
            compare_pair(pair, self.frozen, self.dataset, self.evaluator)

    def test_multiple_extra_reads_do_not_claim_single_observation_effect(self):
        pair = self.make_pair()
        pair["without"] = copy.deepcopy(pair["with"])
        with self.assertRaises(Invalid):
            compare_pair(pair, self.frozen, self.dataset, self.evaluator)

    def test_source_alias_cannot_be_counted_as_new_information(self):
        data, frozen = copy.deepcopy(self.dataset.value), copy.deepcopy(self.frozen)
        episode = next(
            e for e in data["episodes"] if e["id"] == "confirmation.missing_document"
        )
        first = next(s for s in data["sources"] if s["id"] == episode["source_ids"][0])
        alias = next(s for s in data["sources"] if s["id"] == episode["source_ids"][1])
        alias_id = alias["id"]
        alias.update(first, id=alias_id)
        dataset = Dataset(data, self.root)
        frozen["dataset_sha256"] = sha(data)
        left = FixtureExecutor(frozen, dataset, episode, 11, "dense_active")
        left.attempt(episode["initial_ids"][0])
        right = FixtureExecutor(frozen, dataset, episode, 11, "dense_active")
        right.attempt(episode["initial_ids"][0])
        right.attempt(alias_id)
        pair = {
            "schema": "perc1.marginal-pair.v1",
            "world_snapshot_sha256": sha(data),
            "continuation_sha256": frozen["controller"]["sha256"],
            "inference_seed": 19,
            "without": left.trace,
            "with": right.trace,
        }
        with self.assertRaises(Invalid):
            compare_pair(pair, frozen, dataset, self.evaluator)


if __name__ == "__main__":
    unittest.main()
