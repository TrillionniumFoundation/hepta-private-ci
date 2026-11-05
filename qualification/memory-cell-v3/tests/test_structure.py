import tempfile
import unittest
from pathlib import Path

import numpy as np

from structure_study import addresses, evaluate_flow, synthetic_flows
from v3.factor_cell import FactorBank
from v3.structure import WorkLedger, fit_adaptive, fit_partition


class StructuralOwnerTests(unittest.TestCase):
    def test_initial_routes_reject_bad_shape_labels_and_excess_cells_before_fitting(
        self,
    ):
        matrix = np.arange(96, dtype=np.int32).reshape(8, 12)
        selection = np.ones(matrix.shape, dtype=bool)
        domains = np.zeros(len(matrix), dtype=np.uint8)
        invalid = (
            np.arange(8, dtype=np.uint8),
            np.zeros((8, 1), dtype=np.uint8),
            np.zeros(7, dtype=np.uint8),
            np.full(8, 7, dtype=np.uint8),
            np.full(8, -1, dtype=np.int8),
            np.zeros(8, dtype=np.float64),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for index, routes in enumerate(invalid):
                destination = Path(temporary) / str(index)
                with self.assertRaises(ValueError):
                    fit_adaptive(
                        matrix,
                        budget=4096,
                        selection=selection,
                        domains=domains,
                        directory=destination,
                        seed=8011,
                        initial_routes=routes,
                    )
                self.assertFalse(destination.exists())

    def test_real_split_survives_reload_and_consolidates_after_subspaces_converge(self):
        flows, domains = synthetic_flows(8011)
        with tempfile.TemporaryDirectory() as temporary:
            first = flows["convergent"][0]
            selection, hidden = addresses(first.shape, 98012)
            split, receipt = fit_adaptive(
                first,
                budget=4096,
                selection=selection,
                domains=domains,
                directory=Path(temporary) / "split",
                seed=8011,
            )
            self.assertGreater(len(split.blocks), 1)
            self.assertLessEqual(len(split.to_bytes()), 4096)
            self.assertTrue(
                any(
                    event.get("accepted") and event["action"] == "split"
                    for event in receipt["events"]
                )
            )
            for domain, error in receipt["selection"]["domain_mse"].items():
                self.assertLessEqual(
                    error,
                    receipt["single_selection"]["domain_mse"][domain] * 1.02 + 0.25,
                )
            loaded = FactorBank.load(
                Path(temporary) / "split" / f"{split.digest}.factor", split.digest
            )
            rows, columns = np.nonzero(hidden)
            self.assertEqual(loaded.read(rows, columns), split.read(rows, columns))
            second = flows["convergent"][1]
            selection, _ = addresses(second.shape, 98043)
            consolidated, receipt = fit_adaptive(
                second,
                budget=4096,
                selection=selection,
                domains=domains,
                directory=Path(temporary) / "consolidate",
                seed=8011,
                initial_routes=split.routes,
            )
            self.assertEqual(len(consolidated.blocks), 1)
            self.assertTrue(
                any(
                    event.get("accepted") and event["action"] == "consolidate"
                    for event in receipt["events"]
                )
            )
            self.assertNotEqual(consolidated.digest, split.digest)
            self.assertGreater(receipt["work"]["svd_calls"], 1)

    def test_stable_and_random_controls_pay_diagnostics_but_avoid_candidate_fits(self):
        flows, domains = synthetic_flows(8011)
        with tempfile.TemporaryDirectory() as temporary:
            receipts = {}
            for name in ("stable_lowrank", "random"):
                matrix = flows[name][0]
                selection, _ = addresses(matrix.shape, 98012)
                _, receipt = fit_adaptive(
                    matrix,
                    budget=4096,
                    selection=selection,
                    domains=domains,
                    directory=Path(temporary) / name,
                    seed=8011,
                )
                self.assertEqual(receipt["work"]["fit_calls"], 1)
                self.assertFalse(
                    any(event.get("accepted") for event in receipt["events"])
                )
                receipts[name] = receipt
            self.assertGreater(
                receipts["random"]["work"]["diagnostic_multiply_work_proxy"],
                receipts["stable_lowrank"]["work"]["diagnostic_multiply_work_proxy"],
            )

    def test_infeasible_retention_is_rejected_after_charging_the_actual_fit(self):
        rng = np.random.default_rng(8011)
        matrix = rng.integers(-100, 101, size=(32, 12), dtype=np.int32)
        mask = np.ones(matrix.shape, dtype=bool)
        selection, _ = addresses(matrix.shape, 8011)
        routes = np.repeat(np.arange(2, dtype=np.uint8), 16)
        with tempfile.TemporaryDirectory() as temporary:
            ledger = WorkLedger(Path(temporary))
            bank, reason = fit_partition(
                matrix,
                mask,
                routes,
                256,
                selection,
                routes,
                ledger,
                label="unfunded_retention",
                seed=8011,
                floors={"0": 0.0, "1": 0.0},
            )
            self.assertIsNone(bank)
            self.assertIn("retention", reason["reason"])
            self.assertEqual(ledger.fit_calls, 1)
            self.assertGreater(ledger.svd_work, 0)
            self.assertGreater(sum(ledger.retained.values()), 256)

    def test_fixed_structure_control_executes_equal_or_greater_work(self):
        flows, domains = synthetic_flows(8017)
        with tempfile.TemporaryDirectory() as temporary:
            result = evaluate_flow(
                "convergent",
                flows["convergent"],
                domains,
                seed=8017,
                budget=4096,
                directory=temporary,
            )
            for episode in result["episodes"]:
                target = episode["adaptive"]["work"]["total_work_proxy"]
                for k in (1, 2, 4):
                    self.assertGreaterEqual(
                        episode[f"fixed_{k}"]["work"]["total_work_proxy"], target
                    )
                    self.assertLessEqual(episode[f"fixed_{k}"]["deployed_bytes"], 4096)
            chosen = min(
                ("efficient_fixed_1", "efficient_fixed_2", "efficient_fixed_4"),
                key=lambda name: result["totals"][name]["selection_mse"],
            )
            self.assertEqual(result["best_fixed_by_whole_flow_selection"], chosen)
            for episode in result["episodes"]:
                self.assertTrue(
                    episode["adaptive"]["route_migration"][
                        "hidden_coordinate_read_parity_after_reload"
                    ]
                )
                self.assertGreater(episode["shared_state"]["charged_bytes_per_arm"], 0)
                for k in (1, 2, 4):
                    fixed = episode[f"fixed_{k}"]
                    self.assertLessEqual(
                        fixed["efficient_before_work_padding"]["work"][
                            "total_work_proxy"
                        ],
                        fixed["work"]["total_work_proxy"],
                    )


if __name__ == "__main__":
    unittest.main()
