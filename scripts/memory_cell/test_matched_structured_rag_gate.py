"""Exact archived evidence and paired-reader forgery rejection tests."""

import copy
import os
from pathlib import Path
import tempfile
import unittest

from matched_structured_rag_gate import audit, payload


@unittest.skipUnless(
    os.environ.get("HEPTA_MATCHED_RAG_ARCHIVE"),
    "Pinned original GitHub artifact is required; dedicated same-reader CI supplies it",
)
class FrozenSameReaderGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        archive = os.environ.get("HEPTA_MATCHED_RAG_ARCHIVE")
        if archive is None:
            raise unittest.SkipTest(
                "archived-result tests require the pinned artifact in their dedicated CI job"
            )
        cls.fixture = payload(Path(archive))

    def sample(self):
        plan, report, replay, rows, raw = self.fixture
        return (
            copy.deepcopy(plan),
            copy.deepcopy(report),
            copy.deepcopy(replay),
            copy.deepcopy(rows),
            raw,
        )

    def test_observed_negative_matched_baseline(self):
        got = audit(*self.sample())
        for arm in ("organized", "entity_time"):
            self.assertEqual(got["contrasts"][arm]["net_task_success_delta"], 0)
            self.assertEqual(got["contrasts"][arm]["citation_wins"], 0)
        self.assertEqual(got["by_arm"]["hybrid"]["selected_source_ids"], 32)
        self.assertEqual(got["by_arm"]["organized"]["selected_source_ids"], 12)
        self.assertFalse(got["production_accepted"])

    def test_artifact_byte_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            forged = Path(temporary) / "tampered.zip"
            forged.write_bytes(
                Path(os.environ["HEPTA_MATCHED_RAG_ARCHIVE"]).read_bytes() + b"X"
            )
            with self.assertRaisesRegex(ValueError, "GitHub artifact SHA"):
                payload(forged)

    def test_swapped_answer_postscoring_rejected(self):
        plan, report, replay, rows, raw = self.sample()
        rows[1]["output"]["answer"] = "site_ffffffff [E1]"
        with self.assertRaisesRegex(ValueError, "postscore answer tampering"):
            audit(plan, report, replay, rows, raw)

    def test_reader_identity_replacement_rejected(self):
        plan, report, replay, rows, raw = self.sample()
        rows[1]["reader_profile"] = "another reader"
        with self.assertRaisesRegex(ValueError, "postscore answer tampering"):
            audit(plan, report, replay, rows, raw)

    def test_plan_change_rejected(self):
        plan, report, replay, rows, raw = self.sample()
        plan["reader_is_structured_program_not_llm"] = False
        with self.assertRaisesRegex(ValueError, "misrepresented original protocol"):
            audit(plan, report, replay, rows, raw)

    def test_new_source_family_fabrication_rejected(self):
        plan, report, replay, rows, raw = self.sample()
        report["effective_source_family_count"] = 2
        with self.assertRaisesRegex(ValueError, "unmeasured lifetime"):
            audit(plan, report, replay, rows, raw)

    def test_replay_digest_replacement_rejected(self):
        plan, report, replay, rows, raw = self.sample()
        replay["original_journal_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "replay missing"):
            audit(plan, report, replay, rows, raw)

    def test_no_recording_omission_allowed(self):
        plan, report, replay, rows, raw = self.sample()
        with self.assertRaisesRegex(ValueError, "raw/scored paired census"):
            audit(plan, report, replay, rows[:-1], raw)

    def test_lifecycle_unknown_not_zero(self):
        plan, report, replay, rows, raw = self.sample()
        report["total_lifecycle_cost"] = 0
        with self.assertRaisesRegex(ValueError, "unmeasured lifetime"):
            audit(plan, report, replay, rows, raw)


if __name__ == "__main__":
    unittest.main()
