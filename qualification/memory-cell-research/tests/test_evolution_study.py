from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from memory_cells.composition_study import run_composition
from memory_cells.data import dataset_from_events, make_associative
from memory_cells.evolution_study import disjoint_readouts, run_evolution
from memory_cells.lifecycle import MemoryRegistry


class EvolutionStudyTests(unittest.TestCase):
    def test_selection_uses_different_effective_keys_and_ignores_values(self):
        data = make_associative(9001, (8, 8), domain_names=("left", "right"))
        selection, hidden, partition = disjoint_readouts(data)
        selection_keys = {(q.domain, q.key) for q in selection}
        hidden_keys = {(q.domain, q.key) for q in hidden}
        written_keys = {(event.domain, event.key) for event in data.events}
        self.assertEqual(
            (len(selection_keys), len(hidden_keys), selection_keys & hidden_keys),
            (8, 8, set()),
        )
        self.assertEqual(selection_keys | hidden_keys, written_keys)
        changed = dataset_from_events(
            [
                replace(event, value=(event.value + 3) % 64)
                for event in reversed(data.events)
            ]
        )
        self.assertEqual(disjoint_readouts(changed)[2], partition)

    def test_small_run_executes_models_and_revocation_restore(self):
        protocol = json.loads(
            (Path(__file__).resolve().parents[1] / "PROTOCOL.json").read_text()
        )
        protocol["optimizer_steps"] = 10
        protocol["execution_label"] = (
            "unit integration smoke, not formal efficacy evidence"
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            composition = run_composition(protocol, directory, "0" * 40, [9001])[
                "runs"
            ][0]
            evolution = run_evolution(protocol, directory, "0" * 40, [9001])
            maintenance = evolution["maintenance"]["runs"][0]
            growth = evolution["growth"]["runs"][0]
            self.assertEqual(
                (composition["calls"]["typed"], composition["calls"]["no_edges"]),
                (144, 48),
            )
            self.assertEqual(
                (
                    composition["changed_shuffled_edges"],
                    composition["metrics"]["exact_chained"]["accuracy"],
                ),
                (4, 1.0),
            )
            self.assertEqual(
                (
                    maintenance["revoked_lineage_blocked"],
                    maintenance["stale_restore_blocked"],
                ),
                (True, True),
            )
            self.assertEqual(
                (
                    maintenance["deletion_interface"]["refused"],
                    maintenance["deletion_interface"]["model_calls"],
                ),
                (4, 32),
            )
            path = directory / "evolution" / "maintenance-9001"
            frontier = json.loads((path / "tombstones.json").read_text())[
                "revoked_source_revisions"
            ]
            registry = MemoryRegistry.load(
                path / "registry-after-retrain.json", current_revoked_sources=frontier
            )
            clean = registry.resolve("current", scope="research")
            self.assertEqual(set(clean.sources) & set(frontier), set())
            self.assertEqual(
                (
                    growth["same_tensor_budget"],
                    growth["effective_selection_test_inputs_disjoint"],
                ),
                (True, True),
            )
            policy_cost, fixed_cost = (
                growth["policy_cost"],
                growth["fixed_comparator_cost"],
            )
            self.assertEqual(
                policy_cost["trained_artifact_ids"],
                ["parent", "split-0", "split-1", "merge"],
            )
            self.assertEqual(fixed_cost["trained_artifact_ids"], ["fixed-0", "fixed-1"])
            self.assertEqual(
                policy_cost["selection_evaluated_candidates"],
                ["parent", "split", "merge"],
            )
            self.assertAlmostEqual(
                policy_cost["total_write_seconds"] + fixed_cost["total_write_seconds"],
                growth["total_candidate_search_write_seconds"],
            )
            self.assertAlmostEqual(
                policy_cost["selection_read_seconds"],
                sum(
                    growth["costs"][key]["selection_read_seconds"]
                    for key in ("parent", "split", "merge")
                ),
            )
            self.assertEqual(
                policy_cost["selected_hidden_read_seconds"],
                growth["costs"][growth["selection_decision"]["selected_id"]][
                    "hidden_read_seconds"
                ],
            )
            self.assertGreater(
                policy_cost["retained_model_artifact_bytes"],
                policy_cost["selected_deployment_bytes"],
            )
            if not growth["policy_priced_resource_cost_no_greater_than_fixed"]:
                self.assertFalse(growth["criterion_met"])
            artifacts = list(directory.rglob("tensors.npz"))
            self.assertEqual(len(artifacts), 16)


if __name__ == "__main__":
    unittest.main()
