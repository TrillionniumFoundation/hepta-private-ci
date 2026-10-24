"""Predeclared source assignment mechanics; no external corpus or model."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import unittest

from cell_field_retention_data import AMENDED_ROLES, select_amended
from prepare_news_cohorts import publisher_is_ood


class AmendedSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        publisher = next(f"p-{i}" for i in range(100) if not publisher_is_ood(f"p-{i}"))
        cls.rows = []
        for month, count in ((4, 40), (5, 24), (6, 24), (7, 32), (8, 3)):
            for label in range(4):
                for index in range(count):
                    identity = f"m{month}-c{label}-i{index}"
                    cls.rows.append({"source_id": identity, "source_group_id": identity,
                        "text": f"independent source {identity}", "publisher": publisher,
                        "label": label, "source_row_sha256": hashlib.sha256(identity.encode()).hexdigest(),
                        "timestamp_ms": int(datetime(2014, month, 5, tzinfo=timezone.utc).timestamp() * 1000)})
        cls.exclusions = ["m8-c0-i0"]

    def test_frozen_counts_balance_roles_and_deterministic_order(self):
        selected = select_amended(self.rows, self.exclusions, salt="cell-retention-v1-20261024")
        self.assertEqual(len(selected), 480)
        self.assertEqual(Counter(v["role"] for v in selected), {role: n for role, _, n in AMENDED_ROLES})
        self.assertEqual(len({v["component_id"] for v in selected}), 480)
        self.assertFalse(any(v["month"] == "2014-08" for v in selected))
        for role, _, count in AMENDED_ROLES:
            self.assertEqual(Counter(v["label"] for v in selected if v["role"] == role),
                             {label: count // 4 for label in range(4)})
        repeated = select_amended(list(reversed(self.rows)), self.exclusions,
                                  salt="cell-retention-v1-20261024")
        self.assertEqual(selected, repeated)

    def test_shortage_does_not_reduce_or_replace_frozen_future_cohort(self):
        exclusions = self.exclusions + ["m6-c2-i0"]
        with self.assertRaisesRegex(ValueError, "future_june class 2"):
            select_amended(self.rows, exclusions, salt="cell-retention-v1-20261024")

    def test_changing_salt_or_roles_requires_new_reviewed_source_code(self):
        for salt, roles in (("alternative", AMENDED_ROLES),
                            ("cell-retention-v1-20261024", AMENDED_ROLES[:-1])):
            with self.assertRaises(ValueError):
                select_amended(self.rows, self.exclusions, salt=salt, role_plan=roles)


if __name__ == "__main__":
    unittest.main()
