"""Exact full/sparse source-margin exposure; fixtures are not model scores."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch

from experience_memory import source_examples
from source_probe_exposure import verified_visits
from test_source_composition_curriculum import event
from test_source_write_training import reader


class SourceExposureReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = (
            event("location", "service", "location", "site_a", scope="s"),
            event("version", "service", "version", "site_b", scope="s"),
            event("other", "archive", "document", "unpaired_value", scope="s"),
        )
        cls.entries, _ = source_examples(
            cls.documents,
            revision=2,
            allowed_roots={d.root for d in cls.documents},
            revoked=set(),
        )
        cls.writer = reader()
        with redirect_stdout(io.StringIO()), patch("experience_memory.STEPS", 4):
            cls.receipt = cls.writer.fit_sources(
                cls.documents,
                revision=2,
                allowed_roots={d.root for d in cls.documents},
                revoked=set(),
                binding_objective="source_margin",
                loss_backend="full",
            )

    def replay(self, report):
        with patch("experience_memory.STEPS", 4):
            return verified_visits(self.documents, self.writer.tokenizer, report)

    def test_actual_subset_keeps_all_original_questions_and_zero_visits(self):
        visits, schedule_digest = self.replay(self.receipt)
        active = {
            item["query"]["identity"] for item in self.receipt["source_supervision"]
        }
        original = {item["query"]["identity"] for item in self.entries}
        self.assertEqual(set(visits), original)
        self.assertEqual(sum(visits.values()), self.receipt["steps"])
        unseen = set(visits) - active
        self.assertEqual(
            unseen,
            {
                item["query"]["identity"]
                for item in self.entries
                if item["query"]["identity"] not in active
            },
        )
        self.assertEqual(len(unseen), 1)
        self.assertTrue(all(visits[q] == 0 for q in set(visits) - active))
        self.assertEqual(schedule_digest, self.receipt["schedule_sha256"])

    def test_tampered_hard_negative_or_subset_cannot_claim_exposure(self):
        for field in (
            "binding_receipt",
            "source_supervision",
            "input_tokens",
            "actual_projection_positions",
        ):
            forged = deepcopy(self.receipt)
            if field == "binding_receipt":
                forged[field]["training_pairs"][0]["negative_value"] = "forged"
            elif field == "source_supervision":
                # The persisted training cohort is an immutable tuple. Forge
                # an extra source-derived question without mutating it.
                # The production verifier, not fixture setup, must reject it.
                forged[field] = tuple(forged[field]) + (deepcopy(self.entries[-1]),)
            elif field == "input_tokens":
                forged[field] += 1
            else:
                forged[field] -= 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.replay(forged)

    def test_sparse_writer_exposure_matches_full_schedule_without_fake_tokens(self):
        sparse = deepcopy(self.receipt)
        sparse["loss_backend"] = "supervised_positions"
        sparse["actual_projection_positions"] = sparse["supervised_tokens"]
        sparse_visits, sparse_schedule = self.replay(sparse)
        full_visits, full_schedule = self.replay(self.receipt)
        self.assertEqual(sparse_visits, full_visits)
        self.assertEqual(sparse_schedule, full_schedule)
        self.assertEqual(sparse["input_tokens"], self.receipt["input_tokens"])
        self.assertEqual(sparse["supervised_tokens"], self.receipt["supervised_tokens"])
        self.assertLess(
            sparse["actual_projection_positions"], sparse["input_tokens"]
        )

    def test_sparse_margin_rejects_wrong_projection_or_input_exposure(self):
        sparse = deepcopy(self.receipt)
        sparse["loss_backend"] = "supervised_positions"
        sparse["actual_projection_positions"] = sparse["supervised_tokens"]
        for edits in (
            {"actual_projection_positions": sparse["input_tokens"]},
            {"actual_projection_positions": sparse["supervised_tokens"] + 1},
            {"input_tokens": sparse["input_tokens"] - 1},
            {"supervised_tokens": sparse["supervised_tokens"] - 1},
            {"loss_backend": "unknown"},
        ):
            corrupted = deepcopy(sparse)
            corrupted.update(edits)
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                self.replay(corrupted)

    def test_unregistered_binding_objective_or_fake_cost_reject(self):
        for updates in (
            {"binding_objective": "unregistered"},
            {"loss_backend": "unregistered"},
            {"binding_receipt": None},
        ):
            forged = deepcopy(self.receipt)
            forged.update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.replay(forged)


if __name__ == "__main__":
    unittest.main()
