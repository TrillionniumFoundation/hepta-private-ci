import json
import ast
import subprocess
import sys
import unittest
from pathlib import Path

from multimodal_cell_contract import (
    AUTHORITY,
    MODE,
    CellContract,
    ContractError,
    WrongModality,
    UnsupportedModality,
    build_cell_bundle,
    build_feature_cache,
    require_modality,
    run_experiment,
)


class MultimodalCellTests(unittest.TestCase):
    def test_deterministic_cache_and_cells(self):
        self.assertEqual(run_experiment(17), run_experiment(17))
        self.assertNotEqual(run_experiment(17), run_experiment(18))

    def test_equal_budget_and_lineage(self):
        result = run_experiment(17)
        self.assertTrue(result["budget"]["all_modalities_equal"])
        self.assertEqual(len(result["cells"]), 4)
        self.assertTrue(result["encoder"]["frozen"])
        self.assertTrue(result["lineage"]["candidate_predecessors_match"])
        self.assertTrue(all(cell["contract"]["parent_digest"] == result["encoder"]["parent_digest"] for cell in result["cells"]))
        self.assertEqual(
            {cell["budget_flops"] for cell in result["cells"]},
            {result["budget"]["train_flops"]},
        )

    def test_contract_and_alignment_digests_are_bounded(self):
        result = run_experiment(17)
        parent_digest = result["encoder"]["parent_digest"]
        self.assertEqual(len(parent_digest), 64)
        self.assertTrue(all(char in "0123456789abcdef" for char in parent_digest))
        self.assertGreaterEqual(result["cross_modal"]["alignment_loss"], 0.0)
        self.assertGreaterEqual(result["cross_modal"]["alignment_utility"], 0.0)
        self.assertLessEqual(result["cross_modal"]["alignment_utility"], 1.0)
        for cell in result["cells"]:
            contract = cell["contract"]
            self.assertEqual(contract["parent_digest"], parent_digest)
            self.assertEqual(len(contract["adapter_digest"]), 64)
            self.assertEqual(len(contract["contract_digest"]), 64)
            self.assertEqual(len(cell["candidate_snapshot"]["artifact_digest"]), 64)
            self.assertEqual(
                cell["candidate_snapshot"]["predecessor_digest"],
                cell["initial_snapshot"]["artifact_digest"],
            )
            self.assertGreaterEqual(cell["future_task_utility"], 0.0)
            self.assertLessEqual(cell["future_task_utility"], 1.0)

    def test_implementation_is_standard_library_only(self):
        source_path = Path(__file__).with_name("multimodal_cell_contract.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue({"torch", "tensorflow", "jax", "numpy", "pandas"}.isdisjoint(imported_roots))

    def test_unsupported_and_wrong_modality_fail_closed(self):
        with self.assertRaises(UnsupportedModality):
            require_modality("depth")
        cache = build_feature_cache(17)
        bundle = build_cell_bundle(cache, "text", budget_updates=1)
        with self.assertRaises(WrongModality):
            bundle.model.predict(cache.rows_for("image")[0])

    def test_wrong_parent_and_rollback_are_rejected(self):
        cache = build_feature_cache(17)
        bundle = build_cell_bundle(cache, "text", budget_updates=1)
        self.assertEqual(bundle.rollback(bundle.initial_snapshot.artifact_digest), bundle.initial_snapshot)
        with self.assertRaises(ContractError):
            CellContract(
                cell_id="bad",
                modality="text",
                parent_digest="0" * 64,
                adapter_digest="1" * 64,
                budget_flops=10,
                capability=("encode:text",),
            ).validate(cache.encoder_digest)

    def test_protocol_and_cli(self):
        result = run_experiment(17)
        self.assertEqual(result["protocol"]["mode"], MODE)
        self.assertEqual(result["protocol"]["authority"], AUTHORITY)
        payload = json.loads(subprocess.run([sys.executable, "multimodal_cell_contract.py", "--seed", "17"], check=True, capture_output=True, text=True).stdout)
        self.assertEqual(payload["seed"], 17)
        self.assertEqual(payload["protocol"]["mode"], "SHADOW_ONLY")


if __name__ == "__main__":
    unittest.main()
