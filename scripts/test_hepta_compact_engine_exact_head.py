import importlib.util
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-compact-engine-exact-head.py"


def load_module():
    spec = importlib.util.spec_from_file_location("compact_exact_head", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exact-head generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CompactEngineExactHeadTests(unittest.TestCase):
    def test_exact_head_map_binds_current_checkout_tests_and_product_caller(self):
        module = load_module()
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        value = module.build_exact_head_map("passed", head)
        self.assertEqual(value["sourceBase"]["commit"], head)
        self.assertEqual(value["exactHeadEvidence"]["sourceSha"], head)
        self.assertEqual(value["exactHeadEvidence"]["focusedTestStatus"], "passed")
        by_symbol = {item["nativeSymbol"]: item for item in value["operations"]}
        self.assertIn("build_qualified_candidate", by_symbol)
        self.assertIn("prove_compaction", by_symbol)
        self.assertTrue(by_symbol["build_qualified_candidate"]["tests"])
        self.assertTrue(by_symbol["prove_compaction"]["tests"])
        caller = value["productionCaller"]
        self.assertIsNotNone(caller)
        self.assertTrue(caller["sourcePathExists"])
        self.assertEqual(caller["symbol"], "compact_and_publish_authorized")
        self.assertTrue(value["productionImplementation"])
        self.assertEqual(value["productCallerState"], "composed_owner_store")
        self.assertEqual(value["productionWriterState"], "established_owner_store")

    def test_expected_sha_mismatch_fails_closed(self):
        module = load_module()
        with self.assertRaises(SystemExit):
            module.build_exact_head_map("not_run", "0" * 40)


if __name__ == "__main__":
    unittest.main()
