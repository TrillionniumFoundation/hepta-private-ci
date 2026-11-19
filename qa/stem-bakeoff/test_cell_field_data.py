"""Behavioral checks for transitive source isolation and label-file boundaries."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cell_field_data import FINAL_ROLES, ROLE_PLAN, TRAIN_ROLES, build_cohorts, prepare
from prepare_news_cohorts import publisher_is_ood


class CellFieldDataTests(unittest.TestCase):
    def setUp(self):
        self.publisher = next(f"publisher-{i}" for i in range(20) if not publisher_is_ood(f"publisher-{i}"))
        self.plan = tuple((role, month, 4) for role, month, _ in ROLE_PLAN)
        self.rows = []
        for month in ("2014-03", "2014-04", "2014-05", "2014-06"):
            for label in range(4):
                for number in range(12):
                    key = f"{month}-{label}-{number}"
                    self.rows.append(self.row(key, month, label))

    def row(self, key, month, label, *, story=None, title=None):
        timestamp = int(datetime.fromisoformat(month + "-10").replace(tzinfo=timezone.utc).timestamp() * 1000)
        return {"source_id": key, "source_group_id": story or "story-" + key,
                "text": title or "title " + key, "timestamp_ms": timestamp,
                "label": label, "publisher": self.publisher, "source_row_sha256": "0" * 64}

    def test_complete_partition_and_source_order_stable(self):
        first, _ = build_cohorts(self.rows, {}, role_plan=self.plan)
        second, _ = build_cohorts(list(reversed(self.rows)), {}, role_plan=self.plan)
        self.assertEqual(first, second)
        self.assertEqual({x["role"] for x in first}, TRAIN_ROLES | FINAL_ROLES)
        self.assertEqual(len(first), 28)
        self.assertEqual(len({x["component_id"] for x in first}), 28)

    def test_transitive_title_story_component_excluded_as_previous(self):
        extra = [self.row("link-a", "2014-03", 0, story="link-one", title="Title A"),
                 self.row("link-b", "2014-03", 0, story="link-one", title=" Shared  title "),
                 self.row("link-c", "2014-03", 0, story="link-two", title="shared TITLE")]
        selected, audit = build_cohorts(self.rows + extra, {"old": [extra[-1]]}, role_plan=self.plan)
        self.assertEqual(audit["excluded_components_by_reason"]["previous_cohort_component"], 1)
        self.assertFalse(any(set(x["members"]) & {"link-a", "link-b", "link-c"} for x in selected))
        self.assertEqual(audit["raw_components"], len(self.rows) + 1)

    def test_cross_month_and_label_conflict_not_representative_only(self):
        extra = [self.row("conflict-a", "2014-03", 0, story="conflict"),
                 self.row("conflict-b", "2014-04", 1, story="conflict")]
        selected, audit = build_cohorts(self.rows + extra, {}, role_plan=self.plan)
        self.assertEqual(audit["excluded_components_by_reason"]["cross_month"], 1)
        self.assertEqual(audit["excluded_components_by_reason"]["label_conflict"], 1)
        self.assertFalse(any("conflict-a" in x["members"] for x in selected))

    def test_unknown_previous_source_and_insufficient_support_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside this archive"):
            build_cohorts(self.rows, {"old": [self.row("unknown", "2014-03", 0)]}, role_plan=self.plan)
        with self.assertRaisesRegex(ValueError, "insufficient independent"):
            build_cohorts([r for r in self.rows if r["label"] != 3], {}, role_plan=self.plan)

    def test_written_encoder_and_training_inputs_exclude_final_labels(self):
        selected, audit = build_cohorts(self.rows, {}, role_plan=self.plan)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.zip"
            archive.write_bytes(b"test fixture")
            output = Path(directory) / "data"
            with patch("cell_field_data._read_archive", return_value=self.rows), \
                    patch("cell_field_data.select_rows", return_value={}), \
                    patch("cell_field_data.build_cohorts", return_value=(selected, audit)), \
                    patch("cell_field_data.ROLE_PLAN", self.plan):
                receipt = prepare(archive, output)
            predictors = json.loads((output / "predictors.json").read_bytes())
            training = json.loads((output / "train_labels.json").read_bytes())
            final = json.loads((output / "final_labels.json").read_bytes())
            self.assertTrue(all(set(row) == {"source_id", "source_version", "text"}
                                for row in predictors["rows"]))
            self.assertEqual(set(training["roles"]), TRAIN_ROLES)
            self.assertEqual(set(final["roles"]), FINAL_ROLES)
            training_indices = {i for role in training["roles"].values() for i in role["indices"]}
            final_indices = {i for role in final["roles"].values() for i in role["indices"]}
            self.assertFalse(training_indices & final_indices)
            self.assertEqual(training_indices | final_indices, set(range(28)))
            self.assertEqual(set(receipt["files"]),
                             {"predictors.json", "sources.json", "train_labels.json", "final_labels.json"})


if __name__ == "__main__":
    unittest.main()
