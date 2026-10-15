"""Hermetic and three-external-archive checks for factual Reader comparisons."""

from copy import deepcopy
from pathlib import Path
import json
import os
import tempfile
import unittest

from system2_reader_capacity_reference import (
    ARMS,
    COHORTS,
    cohorts,
    load_baseline_archives,
)
from system2_reader_paired_capacity_audit import (
    NEW_135M_RAW_SHA,
    SCHEMA,
    STRONG_RAW_SHA,
    append_new_135m,
    open_strong,
    paired_rows,
    run,
    summarize,
)

ARCHIVES = (
    "HEPTA_STRONG_READER_ARCHIVE",
    "HEPTA_CARDINALITY_ARCHIVE",
    "HEPTA_LABEL_ARCHIVE",
    "HEPTA_NEW_135M_ARCHIVE",
)


class PairedCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(os.environ.get(name) for name in ARCHIVES):
            raise unittest.SkipTest("three externally pinned old archives not staged")
        cls.paths = [Path(os.environ[name]) for name in ARCHIVES]
        cls.files, cls.plan, cls.strong = open_strong(cls.paths[0])
        cls.original = load_baseline_archives(cls.paths[1], cls.paths[2])
        cls.original = append_new_135m(cls.paths[3], cls.original, cohorts())
        cls.groups = cohorts()
        cls.scores = json.loads(cls.files["trial/scored.json"])
        cls.scored = {(r["qid"], r["arm"]): r for r in cls.scores}

    def test_four_archives_replay_and_40_exactly_paired_subjects(self):
        with tempfile.TemporaryDirectory() as t:
            output = Path(t) / "report.json"
            r = run(*self.paths, output, source_commit="a" * 40)
            self.assertEqual(r["schema"], SCHEMA)
            self.assertEqual(r["completed_strong_attempts"], 160)
            self.assertEqual(r["paired_original_135m_conditions"], 160)
            self.assertEqual(r["paired_same_question_subjects"], 40)
            self.assertEqual(r["new_135m_raw_sha256"], NEW_135M_RAW_SHA)
            self.assertEqual(r["strong_raw_sha256"], STRONG_RAW_SHA)
            self.assertEqual(len(r["by_arm"]), 8)
            self.assertFalse(r["production_accepted"])
            self.assertEqual(json.loads(output.read_text()), r)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                run(*self.paths, output, source_commit="a" * 40)

    def test_same_question_negative_and_positive_behavior_kept_separate(self):
        rows = paired_rows(
            self.strong, self.original, self.plan, self.groups, self.scored
        )
        results = summarize(rows)
        self.assertEqual(len(results), 8)
        for cohort in COHORTS:
            for arm in ARMS:
                r = next(
                    x for x in results if x["cohort"] == cohort and x["arm"] == arm
                )
                self.assertEqual(r["planned"], 20)
                self.assertEqual(r["strong_exact"], 0)
                self.assertEqual(
                    r["strong_task_success"],
                    20 if arm in ("decoy_one", "no_evidence") else 0,
                )
        old_results = results
        self.assertEqual(sum(r["original_135m_success"] for r in old_results), 0)
        self.assertEqual(sum(r["only_strong_success"] for r in old_results), 80)
        self.assertEqual(sum(r["neither_success"] for r in old_results), 80)

    def test_new_cohort_archive_is_actual_and_all_80_positions_replayed(self):
        self.assertEqual(self.original["new_model_calls"], 80)
        self.assertEqual(self.original["new_raw_sha256"], NEW_135M_RAW_SHA)
        self.assertEqual(len(self.original["by_key"]), 220)
        full = paired_rows(
            self.strong, self.original, self.plan, self.groups, self.scored
        )
        self.assertEqual(sum("old_135m" in row for row in full), 160)

    def test_tampered_new_135m_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            fake = Path(t) / "changed.zip"
            original = self.paths[3].read_bytes()
            fake.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            baseline = load_baseline_archives(self.paths[1], self.paths[2])
            with self.assertRaisesRegex(ValueError, "archive digest mismatch"):
                append_new_135m(fake, baseline, self.groups)

    def test_modified_strong_archive_rejected_by_external_digest(self):
        with tempfile.TemporaryDirectory() as t:
            target = Path(t) / "fake.zip"
            data = self.paths[0].read_bytes()
            target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, "archive digest mismatch"):
                open_strong(target)

    def test_forged_question_or_source_cannot_be_counted(self):
        bad = dict(self.strong)
        key = next(iter(bad))
        row = deepcopy(bad[key])
        row["reader"]["bundle_digest"] = "forged"
        bad[key] = row
        with self.assertRaisesRegex(ValueError, "original prompt/excerpt"):
            paired_rows(bad, self.original, self.plan, self.groups, self.scored)
        bad = dict(self.strong)
        row = deepcopy(bad[key])
        row["reader"]["delivered_evidence"] = [{"label": "E1"}]
        bad[key] = row
        with self.assertRaisesRegex(ValueError, "original prompt/excerpt"):
            paired_rows(bad, self.original, self.plan, self.groups, self.scored)

    def test_mismatched_historical_model_or_source_is_rejected(self):
        original = deepcopy(self.original)
        key = next(iter(original["by_key"]))
        original["by_key"][key]["reader"]["reader_identity"] = "fake-model"
        with self.assertRaisesRegex(ValueError, "historical same-question"):
            paired_rows(self.strong, original, self.plan, self.groups, self.scored)
        plan = deepcopy(self.plan)
        q = next(iter(plan["source_manifest"]))
        plan["source_manifest"][q] = "00" * 32
        with self.assertRaisesRegex(ValueError, "source manifest"):
            paired_rows(self.strong, self.original, plan, self.groups, self.scored)

    def test_missing_or_extra_scored_arms_rejected(self):
        scored = dict(self.scored)
        scored.pop(next(iter(scored)))
        with self.assertRaisesRegex(ValueError, "missing/extra"):
            paired_rows(self.strong, self.original, self.plan, self.groups, scored)
        scored = dict(self.scored)
        key = next(iter(scored))
        scored[key] = deepcopy(scored[key])
        scored[key]["conditional_success"] = not scored[key]["conditional_success"]
        with self.assertRaisesRegex(ValueError, "scored record drift"):
            paired_rows(self.strong, self.original, self.plan, self.groups, scored)

    def test_invalid_auditor_source_identity_refused(self):
        with tempfile.TemporaryDirectory() as t:
            output = Path(t) / "blocked.json"
            with self.assertRaisesRegex(ValueError, "exact audited Git"):
                run(*self.paths, output, source_commit="invalid")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
