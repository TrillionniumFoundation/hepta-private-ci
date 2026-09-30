from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_evidence_v2.py"
spec = importlib.util.spec_from_file_location("channel_matrix_evidence_v2_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ExtendedEvidencePolicyTests(unittest.TestCase):
    def test_api_compile_fail_is_a_canonical_command(self) -> None:
        self.assertEqual(
            module.evidence.COMMANDS["api-compile-fail"],
            module.API_COMPILE_FAIL_COMMAND,
        )

    def test_transitive_product_and_target_inputs_are_closed(self) -> None:
        roots = set(module.evidence.SOURCE_ROOTS)
        self.assertTrue(set(module.EXTRA_SOURCE_ROOTS).issubset(roots))
        self.assertIn("codex-rs/hepta-supervisor/src/matrix.rs", roots)
        self.assertIn(
            "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh",
            roots,
        )
        self.assertIn("tests/fixtures/run-hermetic-synapse.sh", roots)


if __name__ == "__main__":
    unittest.main()
