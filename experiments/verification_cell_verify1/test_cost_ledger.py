"""Exclusive cost accounting, missingness and declared utility boundaries."""

from dataclasses import replace
import unittest

from .cost_ledger import CostItem, CostReceipt, summarize_costs


RATES = dict(
    wall_seconds=1, process_cpu_seconds=10, energy_joules=0.1, external_charge=2
)


def item(identity="one", stage="checker", resource="worker", clock="host/boot"):
    return CostItem(identity, "attempt", stage, resource, clock)


def receipt(spec=None, start=0, end=10**9, **changes):
    args = dict(
        item=spec or item(),
        status="completed",
        started_ns=start,
        finished_ns=end,
        process_cpu_seconds=0.3,
        peak_rss_bytes=1000,
        energy_joules=2,
        external_charge=0.1,
        evidence_sha256="a" * 64,
        measurement_gaps=(),
    )
    args.update(changes)
    return CostReceipt(**args)


class CostLedgerTests(unittest.TestCase):
    def test_complete_declared_roster_keeps_failed_cancelled_unpublished_costs(self):
        first, second = item(stage="training"), item("two", "checker")
        rows = [
            receipt(first, status="failed", published=False),
            receipt(
                second,
                2 * 10**9,
                4 * 10**9,
                status="cancelled",
                process_cpu_seconds=0.4,
                energy_joules=3,
                external_charge=0.2,
            ),
        ]
        report = summarize_costs([first, second], rows, RATES)
        self.assertEqual(report["totals"]["wall_seconds"], 3)
        self.assertAlmostEqual(report["totals"]["process_cpu_seconds"], 0.7)
        self.assertAlmostEqual(report["declared_receipt_utility"], 11.1)
        self.assertEqual(report["global_elapsed_seconds"], 4)
        self.assertEqual(report["unpublished_operations"], 1)
        self.assertTrue(report["declared_roster_complete"])
        self.assertTrue(report["utility_covers_declared_roster"])
        self.assertFalse(report["full_physical_cost_complete"])
        self.assertEqual(
            report["status_counts"], dict(completed=0, failed=1, cancelled=1, not_run=0)
        )

    def test_concurrency_wall_resource_seconds_and_peak_memory_are_not_summed(self):
        first, second = item(), item("two", resource="other")
        rows = [
            receipt(first, end=2 * 10**9),
            receipt(second, end=3 * 10**9, peak_rss_bytes=2000),
        ]
        report = summarize_costs([first, second], rows)
        self.assertEqual(
            (
                report["totals"]["wall_seconds"],
                report["global_elapsed_seconds"],
                report["peak_rss_bytes"],
            ),
            (5, 3, 2000),
        )
        self.assertIsNone(report["declared_receipt_utility"])
        self.assertFalse(report["exclusive_attribution_proved"])

    def test_overlap_is_refused_but_adjacent_intervals_are_valid(self):
        first, second = item(), item("two")
        with self.assertRaises(ValueError):
            summarize_costs([first, second], [receipt(first), receipt(second)])
        report = summarize_costs(
            [first, second], [receipt(first), receipt(second, 10**9, 2 * 10**9)]
        )
        self.assertEqual(report["totals"]["wall_seconds"], 2)

    def test_missing_measurement_and_missing_operation_do_not_become_free_complete_cost(
        self,
    ):
        first, second = item(), item("two", "evaluation")
        row = receipt(
            first,
            energy_joules=None,
            peak_rss_bytes=None,
            measurement_gaps=("energy/RSS attribution unavailable",),
        )
        report = summarize_costs([first, second], [row], RATES)
        self.assertEqual(report["missing_operations"], ["two"])
        self.assertIsNone(report["totals"]["wall_seconds"])
        self.assertIsNone(report["global_elapsed_seconds"])
        self.assertEqual(report["known_partial_totals"]["wall_seconds"], 1)
        self.assertIsNone(report["totals"]["energy_joules"])
        self.assertIsNone(report["peak_rss_bytes"])
        self.assertIsNone(report["declared_receipt_utility"])
        self.assertFalse(report["utility_covers_declared_roster"])
        repriced = summarize_costs([first], [row], {**RATES, "energy_joules": 0})
        self.assertAlmostEqual(repriced["declared_receipt_utility"], 4.2)
        self.assertFalse(repriced["full_physical_cost_complete"])

    def test_frozen_bindings_duplicates_and_unpriced_metrics_refuse(self):
        first, second = item(), item("two")
        for roster, rows in (
            ([first, first], []),
            ([first], [receipt(first), receipt(first)]),
            ([first], [receipt(second)]),
            ([first], [receipt(replace(first, stage="fit"))]),
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                summarize_costs(roster, rows)
        with self.assertRaises(ValueError):
            summarize_costs([first], [receipt(first)], {"wall_seconds": 1})

    def test_numeric_validation_and_missing_reasons(self):
        for changes in (
            dict(process_cpu_seconds=True),
            dict(energy_joules=float("nan")),
            dict(external_charge=-1),
            dict(started_ns=True),
            dict(finished_ns=-1),
            dict(peak_rss_bytes=0.1),
            dict(energy_joules=None),
            dict(published=1),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                receipt(**changes)

    def test_clock_identity_controls_elapsed_and_zero_duration_not_run(self):
        first, second = item(), item("two", clock="other/boot")
        report = summarize_costs([first, second], [receipt(first), receipt(second)])
        self.assertIsNone(report["global_elapsed_seconds"])
        row = receipt(
            first,
            end=0,
            status="not_run",
            process_cpu_seconds=0,
            energy_joules=0,
            external_charge=0,
            peak_rss_bytes=0,
        )
        report = summarize_costs([first], [row], RATES)
        self.assertEqual(report["declared_receipt_utility"], 0)
        self.assertFalse(report["full_physical_cost_complete"])
        with self.assertRaises(ValueError):
            receipt(first, status="not_run")
