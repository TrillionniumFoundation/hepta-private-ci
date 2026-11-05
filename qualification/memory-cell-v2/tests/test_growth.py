from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory_cells.data import make_associative
from memory_cells.encoding import FrozenEncoder
from memory_cells.lifecycle import LifecycleError, MemoryRegistry
from memory_cells.model import MemoryCell
from v2.growth import (
    DEFAULT_PROFILE,
    _identity,
    _migrate,
    _predict,
    _route,
    _train,
    partition_keys,
    restore_checkpoint,
    run_growth,
    serve,
)


class ContinualGrowthTests(unittest.TestCase):
    def test_effective_holdout_ignores_values_and_is_independent_of_route(self):
        events = make_associative(
            8001, (24, 24), domain_names=("pressure-a", "pressure-b")
        ).events
        before = partition_keys(events)
        changed = partition_keys(
            tuple(replace(e, value=(e.value + 1) % 64) for e in reversed(events))
        )

        def identities(rows):
            return {(e.domain, e.key) for e in rows}

        self.assertEqual(
            tuple(map(identities, before)), tuple(map(identities, changed))
        )
        self.assertFalse(identities(before[0]) & identities(before[1]))
        for rows in before:
            self.assertEqual({_route({"route": "hash"}, e) for e in rows}, {0, 1})

    def test_rejected_candidates_remain_charged_and_clean_restore_blocks_revocation(
        self,
    ):
        profile = {
            **DEFAULT_PROFILE,
            "snapshots": [[16, 16], [32, 16], [32, 32]],
            "steps": 2,
            "revocations": 4,
            "min_selection_gain": 1.0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            row = run_growth(
                {"growth_v2_profile": profile},
                Path(temporary),
                "0" * 40,
                [8001],
                development=True,
            )["runs"][0]
            self.assertEqual(
                [p["selection"]["policy"]["operation"] for p in row["phases"]],
                ["no_change"] * 3,
            )
            self.assertEqual(row["accepted_evolution_operations"], [])
            self.assertFalse(row["criterion_met"])
            self.assertTrue(row["maintenance_guards_passed"])
            self.assertEqual(
                row["stream_accuracy"]["policy"], row["stream_accuracy"]["fixed-single"]
            )
            policy, fixed = row["costs"]["policy"], row["costs"]["fixed-single"]
            self.assertEqual(
                (
                    len(policy["attempted_checkpoints"]),
                    len(fixed["attempted_checkpoints"]),
                ),
                (10, 4),
            )
            self.assertEqual(
                policy["deployed_parameter_bytes"], fixed["deployed_parameter_bytes"]
            )
            comparison = row["comparisons"]["fixed-single"]
            self.assertAlmostEqual(
                comparison["net_gain_per_query_at_protocol_h"],
                comparison["accuracy_gain"]
                - policy["amortized_resource_cost_per_query"]
                + fixed["amortized_resource_cost_per_query"],
            )
            self.assertTrue(all(p["effective_keys_disjoint"] for p in row["phases"]))
            self.assertTrue(any(r["distillation"] for r in policy["training_receipts"]))
            self.assertTrue(
                all(
                    m["deleted_interface_refused"] == 4
                    for m in row["maintenance"].values()
                )
            )

    def test_actual_two_cell_route_migration_and_owner_guard_precede_parameter_reads(
        self,
    ):
        profile = {**DEFAULT_PROFILE, "steps": 2}
        events = make_associative(
            8001, (16, 16), domain_names=("pressure-a", "pressure-b")
        ).events
        encoder, registry = FrozenEncoder(128, seed=0), MemoryRegistry()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            parent = _train(
                "parent",
                {"route": "single", "ranks": [16]},
                events,
                encoder,
                profile,
                path / "parent",
                "0" * 40,
                8001,
                registry,
            )
            parent, _ = _migrate(parent, None, registry, encoder, events, "policy")
            split = _train(
                "split",
                {"route": "domain", "ranks": [8, 8]},
                events,
                encoder,
                profile,
                path / "split",
                "0" * 40,
                8001,
                registry,
                parent=parent,
            )
            split, migration = _migrate(
                split, parent, registry, encoder, events, "policy"
            )
            self.assertEqual(
                (
                    migration["structure_changed"],
                    migration["restored_predictions_equal"],
                ),
                (True, True),
            )
            source = _identity(events[0])
            registry.revoke_source(source)
            stale = MemoryRegistry.load(
                path / "split" / "owner-checkpoint.json",
                current_revoked_sources=[source],
            )
            with self.assertRaises(LifecycleError):
                restore_checkpoint(path / "split" / "checkpoint.json", stale)
            with patch.object(
                MemoryCell,
                "predict",
                side_effect=AssertionError("unexpected tensor read"),
            ):
                with self.assertRaises(LifecycleError):
                    _predict(split, events, encoder, registry)
                clean = MemoryRegistry.load(
                    path / "parent" / "owner-checkpoint.json",
                    current_revoked_sources=[],
                )
                self.assertEqual(
                    serve(
                        parent,
                        events[:1],
                        encoder,
                        clean,
                        {(events[0].domain, events[0].key)},
                    ),
                    [None],
                )
            manifest = json.loads((path / "split" / "checkpoint.json").read_text())
            manifest["payload"]["spec"]["ranks"] = [4, 12]
            (path / "split" / "checkpoint.json").write_text(json.dumps(manifest))
            with self.assertRaises(LifecycleError):
                restore_checkpoint(path / "split" / "checkpoint.json", registry)


if __name__ == "__main__":
    unittest.main()
