"""Exact source-margin exposure replay; authored data are not model scores."""

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
        self.assertEqual(set(visits) - active, {
            item["query"]["identity"]
            for item in self.entries
            if item["query"]["identity"] not in active
        })
        self.assertTrue(all(visits[q] == 0 for q in set(visits) - active))
        self.assertEqual(
            schedule_digest, self.receipt["schedule_sha256"]
        )

    def test_tampered_hard_negative_or_subset_cannot_claim_exposure(self):
        corruptions = (
            ("binding_receipt", lambda r: r["training_pairs"][0].update(
                negative_value="forged"
            )),
            ("source_supervision", lambda r: r.append(self.entries[-1])),
            ("input_tokens", lambda r: r + 1),
            ("actual_projection_positions", lambda r: r - 1),
        )
        for field, mutate in corruptions:
            forged = deepcopy(self.receipt)
            value = forged[field]
            outcome = mutate(value)
            if outcome is not None:
                forged[field] = outcome
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.replay(forged)

    def test_unregistered_binding_objective_or_fake_cost_reject(self):
        for updates in (
            {"binding_objective": "unregistered"},
            {"loss_backend": "supervised_positions"},
            {"binding_receipt": None},
        ):
            forged = deepcopy(self.receipt)
            forged.update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.replay(forged)


if __name__ == "__main__":
    unittest.main()
