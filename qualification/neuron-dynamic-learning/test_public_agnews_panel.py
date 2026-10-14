"""Synthetic fixtures are never empirical pretrained-model evidence."""
import unittest
from public_agnews_panel import PanelError, select_rows, canonical, sha


def fixture(n=160):
    train = [
        {"text": f"Public train article {i}: topic {i%2}", "label": i%2}
        for i in range(n)
    ]
    holdout = [
        {"text": f"Public holdout article {i}: topic {i%2}", "label": i%2}
        for i in range(n)
    ]
    return train, holdout


class PublicPanel(unittest.TestCase):
    def test_balanced_fixed_task_and_disjoint_sources(self):
        train, holdout = fixture()
        panel = select_rows(train, holdout)
        self.assertEqual(panel["case_count"], 224)
        self.assertTrue(panel["cross_sectional_not_future"])
        self.assertEqual(panel["production_promotion"], "DENY_ALL")
        self.assertFalse(panel["pretrained_model_execution"])
        self.assertEqual(
            {name: sum(row["split"] == name for row in panel["cases"])
             for name in ("train", "calibration", "test")},
            {"train": 128, "calibration": 32, "test": 64},
        )
        self.assertEqual(len({r["source_digest"] for r in panel["cases"]}), 224)
        self.assertTrue(all(
            sha(canonical(row["joint_input"])) == row["joint_input_digest"]
            for row in panel["cases"]
        ))
        self.assertEqual(
            canonical(panel),
            canonical(select_rows(list(reversed(train)), list(reversed(holdout)))),
        )

    def test_repeated_sources_cross_split_cannot_fill_quota(self):
        train, _ = fixture()
        with self.assertRaises(PanelError):
            select_rows(train, train)

    def test_bad_label_missing_schema_or_one_class_rejected(self):
        for kind in ("label", "schema", "only_sports"):
            train, holdout = fixture()
            if kind == "label":
                train[0]["label"] = "sports"
            elif kind == "schema":
                train[0] = {"text": "missing label"}
            else:
                train = [{"text": f"sports {i}", "label": 1} for i in range(150)]
            with self.subTest(kind=kind), self.assertRaises(PanelError):
                select_rows(train, holdout)

    def test_no_future_or_independent_outcome_claims(self):
        train, holdout = fixture()
        panel = select_rows(train, holdout)
        self.assertNotIn("future1", {row["split"] for row in panel["cases"]})
        self.assertFalse(panel["independent_outcome_observer"])
        self.assertFalse(panel["fair_cpu_model_budget_verified"])


if __name__ == "__main__":
    unittest.main()
