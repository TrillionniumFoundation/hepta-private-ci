"""Adversarial accounting checks for VERIFY-1 descriptive measurements."""

import unittest

from experiments.verification_cell_verify1.metrics import compare_votes
from experiments.verification_cell_verify1.metrics import summarize
from experiments.verification_cell_verify1.metrics import summarize_costs


def trajectory(tid="t0", **changes):
    row = dict(
        trajectory_id=tid,
        source_group="source",
        arm="policy",
        fault="clean",
        risk=0.1,
        accepted=False,
        outcome_error=False,
        injected_step=None,
        detected_step=None,
        terminal_step=5,
        interrupted=False,
    )
    return {**row, **changes}


def vote(tid="t0", voter="a", **changes):
    row = dict(
        trajectory_id=tid,
        voter_id=voter,
        base_sha256="a" * 64,
        adapter_sha256=None,
        output_sha256="b" * 64,
        vote_error=False,
        outcome_error=False,
    )
    return {**row, **changes}


def cost(oid="op0", **changes):
    row = dict(
        operation_id=oid,
        trajectory_id="t0",
        arm="policy",
        kind="check",
        wall_ns=10,
        cpu_ns=5,
        units=1,
        energy_joules=None,
        status="succeeded",
    )
    return {**row, **changes}


class TrajectoryMetricsTests(unittest.TestCase):
    def test_unknown_labels_and_rejected_errors_remain_in_denominators(self):
        rows = [
            trajectory("t0", accepted=True, outcome_error=True, risk=0.2),
            trajectory("t1", accepted=True, outcome_error=None),
            trajectory("t2", outcome_error=True),
            trajectory("t3", accepted=True, risk=0.9),
        ]
        arm = summarize(rows, (0, 0.1, 1))["arms"]["policy"]
        self.assertEqual(
            arm["policy_accepted"],
            dict(
                selected=3,
                coverage=0.75,
                known_errors=1,
                known_labels=2,
                unknown_labels=1,
                known_label_error_rate=0.5,
                error_rate=None,
                error_rate_bounds=[1 / 3, 2 / 3],
            ),
        )
        self.assertEqual(
            arm["risk_coverage"][1],
            dict(
                threshold=0.1,
                selected=2,
                coverage=0.5,
                known_errors=1,
                known_labels=1,
                unknown_labels=1,
                known_label_error_rate=1,
                error_rate=None,
                error_rate_bounds=[0.5, 1],
            ),
        )
        self.assertEqual(arm["risk_coverage"][2]["known_errors"], 2)
        self.assertIsNone(arm["risk_coverage"][0]["error_rate"])

    def test_empty_acceptance_and_shared_sources_do_not_create_samples(self):
        rows = [trajectory("t0"), trajectory("t1")]
        arm = summarize(rows)["arms"]["policy"]
        self.assertEqual(
            (arm["source_groups"], arm["source_group_count"]), (["source"], 1)
        )
        self.assertEqual(
            (
                arm["policy_accepted"]["error_rate"],
                arm["policy_accepted"]["error_rate_bounds"],
            ),
            (None, None),
        )
        self.assertEqual(summarize([])["arms"], {})
        self.assertEqual(
            summarize(rows + [trajectory("t0", arm="other")])["total_rows"], 3
        )

    def test_undetected_faults_and_clean_interruptions_are_not_dropped(self):
        rows = [
            trajectory(
                "t0",
                fault="stale",
                outcome_error=True,
                injected_step=1,
                detected_step=3,
            ),
            trajectory("t1", fault="missing", outcome_error=True, injected_step=2),
            trajectory("t2", interrupted=True, detected_step=0),
            trajectory("t3"),
            trajectory("t4", interrupted=True, outcome_error=None),
        ]
        arm = summarize(rows)["arms"]["policy"]
        self.assertEqual(
            arm["detection"],
            dict(
                injected_trajectories=2,
                detected=1,
                undetected_trajectory_ids=["t1"],
                detected_without_injection_ids=["t2"],
                detected_observations=[
                    dict(trajectory_id="t0", delay_steps=2, terminal_lead_steps=2)
                ],
            ),
        )
        self.assertEqual(
            arm["interruptions"],
            dict(
                total=2,
                known_clean_trajectories=2,
                interrupted_known_clean=1,
                rate_among_known_clean=0.5,
                interrupted_unknown_outcome=1,
            ),
        )

    def test_invalid_trajectory_rows_are_rejected(self):
        bad = [
            dict(risk=value)
            for value in (float("nan"), float("inf"), -1, 1.1, True, "0.1")
        ]
        bad += [
            dict(terminal_step=True),
            dict(terminal_step=-1),
            dict(injected_step=6),
            dict(detected_step=6),
            dict(injected_step=2, detected_step=1),
            dict(accepted=1),
            dict(outcome_error=0),
            dict(interrupted=None),
            dict(source_group=" "),
            dict(unexpected=True),
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize([trajectory(**change)])
        with self.assertRaises(ValueError):
            summarize([trajectory(), trajectory()])
        for thresholds in ((0.2, 0.1), (0.1, 0.1), (True,), (float("nan"),)):
            with self.subTest(thresholds=thresholds), self.assertRaises(ValueError):
                summarize([], thresholds)


class VoteMetricsTests(unittest.TestCase):
    def test_identical_errors_across_different_models_remain_correlated(self):
        rows = []
        for index, wrong in enumerate((True, True, False, False)):
            for voter, base, adapter in (
                ("a", "a", None),
                ("b", "a", "c" * 64),
                ("c", "d", None),
            ):
                rows.append(
                    vote(
                        f"t{index}",
                        voter,
                        base_sha256=base * 64,
                        adapter_sha256=adapter,
                        vote_error=wrong,
                        outcome_error=wrong,
                    )
                )
        result = compare_votes(rows)
        self.assertEqual(
            [
                (p["provenance_relation"], p["error_phi"], p["both_error"])
                for p in result["pairwise"]
            ],
            [
                ("same_base_different_adapter", 1, 2),
                ("different_base", 1, 2),
                ("different_base", 1, 2),
            ],
        )
        self.assertEqual(
            result["cofailure_clusters"][0],
            dict(
                trajectory_id="t0",
                outcome_error=True,
                voter_ids=["a", "b", "c"],
                shared_wrong_outputs=[
                    dict(output_sha256="b" * 64, voter_ids=["a", "b", "c"])
                ],
            ),
        )

    def test_degenerate_correlation_and_incomplete_panels(self):
        result = compare_votes([vote(), vote(voter="b"), vote("t1")])
        self.assertEqual(
            (
                result["pairwise"][0]["paired_trajectories"],
                result["pairwise"][0]["error_phi"],
            ),
            (1, None),
        )
        self.assertEqual(result["incomplete_panel_trajectory_ids"], ["t1"])
        self.assertEqual(compare_votes([])["pairwise"], [])

    def test_duplicate_votes_and_provenance_or_truth_drift_are_rejected(self):
        for rows in (
            [vote(), vote()],
            [vote(), vote("t1", base_sha256="c" * 64)],
            [vote(), vote(voter="b", outcome_error=True)],
            [vote(adapter_sha256="")],
            [vote(vote_error=1)],
            [vote(output_sha256="g" * 64)],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                compare_votes(rows)


class CostMetricsTests(unittest.TestCase):
    def test_failed_work_and_unknown_energy_are_preserved(self):
        result = summarize_costs(
            [
                cost(status="failed", energy_joules=2.5),
                cost("retry", kind="model_tokens", units=100, wall_ns=20),
            ]
        )
        self.assertEqual(
            result["totals"],
            dict(
                operations=2,
                summed_operation_wall_ns=30,
                summed_operation_cpu_ns=10,
                units_by_kind={"check": 1, "model_tokens": 100},
                status_counts={"failed": 1, "succeeded": 1},
                energy_joules=None,
                known_energy_joules=2.5,
                energy_known_operations=1,
                energy_unknown_operations=1,
            ),
        )
        self.assertEqual(result["by_kind"]["check"]["energy_joules"], 2.5)
        self.assertIsNone(summarize_costs([])["totals"]["energy_joules"])
        missing_energy = cost()
        del missing_energy["energy_joules"]
        self.assertIsNone(
            summarize_costs([missing_energy])["totals"]["known_energy_joules"]
        )

    def test_duplicate_physical_executions_and_invalid_measurements_fail(self):
        with self.assertRaises(ValueError):
            summarize_costs([cost(), cost(arm="other")])
        for change in (
            dict(wall_ns=True),
            dict(cpu_ns=-1),
            dict(units=True),
            dict(units=-1),
            dict(energy_joules=float("inf")),
            dict(units=float("nan")),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_costs([cost(**change)])
        with self.assertRaises(ValueError):
            summarize_costs(
                [cost(energy_joules=1e308), cost("op1", energy_joules=1e308)]
            )


if __name__ == "__main__":
    unittest.main()
