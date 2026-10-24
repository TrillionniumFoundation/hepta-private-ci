"""No-model checks for global exclusion closure and count-only feasibility."""

from datetime import datetime, timezone
import hashlib
import unittest

from cell_field_retention_sources import source_feasibility
from prepare_news_cohorts import normalized_title, publisher_is_ood


PUBLISHER = next(f"publisher-{i}" for i in range(100) if not publisher_is_ood(f"publisher-{i}"))
OOD = next(f"publisher-{i}" for i in range(100) if publisher_is_ood(f"publisher-{i}"))


def row(identifier, label, *, story=None, title=None, month=4, publisher=PUBLISHER):
    return {"source_id": str(identifier), "source_group_id": story or f"story-{identifier}",
            "text": title or f"source title {identifier}", "label": label, "publisher": publisher,
            "timestamp_ms": int(datetime(2014, month, 5, tzinfo=timezone.utc).timestamp() * 1000)}


class SourceClosureTests(unittest.TestCase):
    def test_global_title_story_bridge_closes_unselected_sources(self):
        rows = [row("a", 0, story="s-a", title="Shared TITLE"),
                row("b", 0, story="s-b", title=" shared  title "),
                row("c", 0, story="s-b", title="another title")]
        report = source_feasibility(rows, {"old": {"source_ids": ["a"]}},
                                    role_plan=(("future", "2014-04", 4),))
        self.assertEqual(report["raw_components"], 1)
        self.assertEqual(report["excluded_raw_source_ids"], ["a", "b", "c"])
        self.assertEqual(report["exposure_components_by_origin"], {"old": 1})
        self.assertFalse(report["source_count_feasible_under_supplied_exclusions"])

    def test_multiple_historical_manifests_have_union_not_double_counted_exclusion(self):
        rows = [row("a", 0, story="same"), row("b", 0, story="same"), row("c", 1)]
        report = source_feasibility(rows, {"first": {"source_ids": ["a"]},
                                          "second": {"story_ids": ["same"]}},
                                    role_plan=(("future", "2014-04", 4),))
        self.assertEqual(report["exposure_component_pair_overlaps"], {"first|second": 1})
        self.assertEqual(report["rejection_counts_nonexclusive"]["known_exposed_component"], 1)
        self.assertEqual(report["excluded_raw_source_ids"], ["a", "b"])

    def test_future_roles_share_month_budget_and_opaque_exposure_can_exhaust_it(self):
        rows = [row(f"{label}-{j}", label) for label in range(4) for j in range(2)]
        rows.append(row("old", 0, month=3))
        report = source_feasibility(rows, {"old": {"source_ids": ["old"]}},
                                    role_plan=(("train", "2014-04", 4), ("test", "2014-04", 4)))
        self.assertTrue(report["source_count_feasible_under_supplied_exclusions"])
        self.assertFalse(report["source_inventory_completeness_verified"])
        self.assertFalse(report["selected_new_cohort"])
        exhausted = source_feasibility(rows, {"old": {"source_ids": ["old", "2-1"]}},
                                    role_plan=(("train", "2014-04", 4), ("test", "2014-04", 4)))
        self.assertEqual(exhausted["shortages"]["2014-04/2"],
                         {"required": 2, "available": 1, "shortfall": 1})

    def test_conflict_cross_month_and_publisher_exclusions_remain_visible(self):
        rows = [row("old", 0, month=3), row("a", 0, story="conflict"),
                row("b", 1, story="conflict"), row("c", 2, story="months", month=4),
                row("d", 2, story="months", month=5), row("e", 3, publisher=OOD)]
        report = source_feasibility(rows, {"old": {"source_ids": ["old"]}},
                                    role_plan=(("future", "2014-04", 4),))
        reasons = report["rejection_counts_nonexclusive"]
        self.assertEqual(reasons["label_conflict"], 1)
        self.assertEqual(reasons["cross_month"], 1)
        self.assertEqual(reasons["no_non_ood_publisher"], 1)

    def test_absent_sources_titles_and_label_payloads_are_rejected(self):
        rows = [row("old", 0)]
        for exposure in ({"source_ids": ["absent"]}, {"story_ids": ["absent"]},
                         {"title_sha256": ["0" * 64]},
                         {"source_ids": ["old"], "labels": [0]}):
            with self.subTest(exposure=exposure), self.assertRaises(ValueError):
                source_feasibility(rows, {"old": exposure}, role_plan=(("future", "2014-04", 4),))

    def test_normalized_title_exclusion_and_raw_order_invariance(self):
        rows = [row("old", 0, title="ｓａｍｅ   TITLE"),
                row("copy", 0, title="same title"), row("fresh", 1)]
        title_sha = hashlib.sha256(normalized_title("same title").encode()).hexdigest()
        exposure = {"old": {"title_sha256": [title_sha]}}
        a = source_feasibility(rows, exposure, role_plan=(("future", "2014-04", 4),))
        b = source_feasibility(list(reversed(rows)), exposure, role_plan=(("future", "2014-04", 4),))
        self.assertEqual(a, b)
        self.assertEqual(a["excluded_raw_source_ids"], ["copy", "old"])


if __name__ == "__main__":
    unittest.main()
