"""Original-source split anti-leakage admission controls: no neural inference."""

import copy
import unittest

from prospective_family_gate import admission

SHA = "a" * 64


def sample():
    rows = [
        dict(
            id="train",
            family="f-train",
            partition="train",
            kind="new_fact",
            source_digest="1" * 64,
            source_at="2026-10-13T01:00:00Z",
            exposed_at="2026-10-14T01:00:00Z",
        ),
        dict(
            id="select",
            family="f-select",
            partition="select",
            kind="updated_fact",
            source_digest="2" * 64,
            source_at="2026-10-13T01:00:00Z",
            exposed_at="2026-10-14T01:00:00Z",
        ),
    ]
    for i, kind in enumerate(("new_fact", "updated_fact", "composition", "program")):
        rows.append(
            dict(
                id=f"test-{i}",
                family=f"f-test-{i}",
                partition="test",
                kind=kind,
                source_digest=str(i + 3) * 64,
                source_at="2026-10-13T03:00:00Z",
                exposed_at="2026-10-15T00:00:00Z",
            )
        )
    return dict(
        schema="hepta.memory.prospective-source-cut.v1",
        contains_answers=False,
        publisher_answer_oracle=False,
        registered_at="2026-10-12T00:00:00Z",
        frozen_at="2026-10-14T00:00:00Z",
        policy_snapshot_sha256=SHA,
        knowledge_snapshot_sha256=SHA,
        sources=rows,
    )


class OriginalSourceCutTests(unittest.TestCase):
    def test_registered_not_certified(self):
        result = admission(sample())
        self.assertEqual(
            result["partition_source_counts"], {"train": 1, "select": 1, "test": 4}
        )
        self.assertFalse(result["source_lineage_independently_authenticated"])
        self.assertFalse(result["production_accepted"])

    def test_family_leak_rejected(self):
        manifest = sample()
        manifest["sources"][2]["family"] = "f-train"
        with self.assertRaisesRegex(ValueError, "family crosses"):
            admission(manifest)

    def test_byte_duplicate_cross_split_rejected(self):
        manifest = sample()
        manifest["sources"][3]["source_digest"] = "2" * 64
        with self.assertRaisesRegex(ValueError, "source bytes cross"):
            admission(manifest)

    def test_revealed_before_freeze_rejected(self):
        manifest = sample()
        manifest["sources"][2]["exposed_at"] = "2026-10-13T23:00:00Z"
        with self.assertRaisesRegex(ValueError, "chronology"):
            admission(manifest)

    def test_unregistered_preexisting_test_source_rejected(self):
        manifest = sample()
        manifest["sources"][2]["source_at"] = "2026-10-11T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "predates"):
            admission(manifest)

    def test_unregistered_stratum_rejected(self):
        manifest = sample()
        manifest["sources"][5]["kind"] = "composition"
        with self.assertRaisesRegex(ValueError, "four untouched"):
            admission(manifest)

    def test_answer_oracle_rejected(self):
        for field in ("contains_answers", "publisher_answer_oracle"):
            manifest = sample()
            manifest[field] = True
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "gold access"):
                    admission(manifest)

    def test_unknown_model_snapshot_rejected(self):
        manifest = sample()
        manifest["knowledge_snapshot_sha256"] = None
        with self.assertRaisesRegex(ValueError, "knowledge snapshot"):
            admission(manifest)

    def test_no_chronology_forgery_claim(self):
        manifest = sample()
        manifest["registered_at"] = "2026-10-14T00:00:01Z"
        with self.assertRaisesRegex(ValueError, "registration must precede"):
            admission(manifest)

    def test_duplicate_source_and_non_utc_rejected(self):
        manifest = sample()
        manifest["sources"][1]["id"] = "train"
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            admission(manifest)
        manifest = sample()
        manifest["sources"][1]["source_at"] = "2026-10-13T01:00:00+02:00"
        with self.assertRaisesRegex(ValueError, "UTC Z"):
            admission(manifest)


if __name__ == "__main__":
    unittest.main()
