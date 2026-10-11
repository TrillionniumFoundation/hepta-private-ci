"""Exact row-expanding oracle for bounded source-cluster resampling."""
from collections import defaultdict
import random
import unittest

from four_gate_common import percentile
from four_gate_selective import ARMS, DETECTORS, _metrics, clustered_metrics
from test_four_gate_fixtures import plan_fixture


class ResamplingTests(unittest.TestCase):
    def test_exact_intervals_match_original_row_expanding_draws(self):
        rng = random.Random(197)
        for case in range(12):
            rows = []
            for group in range(1 + case):
                for _ in range(1 + rng.randrange(19)):
                    known = bool(rng.randrange(2))
                    rows.append((str(group), (known, known and bool(rng.randrange(2)),
                                             bool(rng.randrange(2)), known and bool(rng.randrange(2)))))
            plan = plan_fixture()
            plan["bootstrap_replicates"] = 113
            actual = clustered_metrics(rows, plan)
            clusters = defaultdict(list)
            for group, record in rows:
                clusters[group].append(record)
            ordered = [clusters[group] for group in sorted(clusters)]
            oracle_rng = random.Random(plan["seed"])
            draws = defaultdict(list)
            for _ in range(plan["bootstrap_replicates"]):
                expanded = [record for _ in ordered
                            for record in ordered[oracle_rng.randrange(len(ordered))]]
                for name, value in _metrics(expanded).items():
                    draws[name].append(value if value is not None else
                                       (0.0 if name == "answerable_coverage" else 1.0))
            alpha = plan["alpha"] / (2 * len(ARMS) * len(DETECTORS) * 4)
            for name, point in _metrics([record for _, record in rows]).items():
                with self.subTest(case=case, metric=name):
                    self.assertEqual(actual[name]["estimate"], point)
                    self.assertEqual(actual[name]["lcb"], percentile(draws[name], alpha / 2))
                    self.assertEqual(actual[name]["ucb"], percentile(draws[name], 1 - alpha / 2))

    def test_record_visits_do_not_multiply_by_bootstrap_draws(self):
        class CountedRow(tuple):
            visits = 0

            def __getitem__(self, key):
                CountedRow.visits += 1
                return super().__getitem__(key)

        rows = [(str(i % 4), CountedRow((True, True, True, False))) for i in range(80)]
        plan = plan_fixture()
        visits = []
        for repeats in (2, 300):
            plan["bootstrap_replicates"] = repeats
            CountedRow.visits = 0
            result = clustered_metrics(rows, plan)
            self.assertEqual(result["accepted_error"]["estimate"], 0)
            visits.append(CountedRow.visits)
        self.assertEqual(visits[0], visits[1])

    def test_cluster_draw_budget_still_rejects_before_sampling(self):
        plan = plan_fixture()
        plan["bootstrap_replicates"] = 20_000_001
        with self.assertRaisesRegex(ValueError, "bootstrap budget"):
            clustered_metrics([("one", (True, True, True, False))], plan)


if __name__ == "__main__":
    unittest.main()
