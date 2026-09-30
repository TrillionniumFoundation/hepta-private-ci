import subprocess
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import validate_build_contract as contract


class BuildContractTest(unittest.TestCase):
    def test_build_contract_is_closed(self):
        root = Path(__file__).resolve().parents[3]
        subprocess.run(
            [
                "python3",
                str(
                    Path(__file__).with_name(
                        "validate_build_contract.py"
                    )
                ),
            ],
            cwd=root,
            check=True,
        )

    def test_boxed_error_match_patterns_are_not_constructor_expressions(self):
        host = "OutcomePending(Box<BaoConsumptionOperationV1>)\nTerminalFailure(Box<BaoConsumptionOperationV1>)"
        for branch in ("Err(BaoProductHostError::TerminalFailure(_)) => {}",
                       "BaoProductHostError::OutcomePending(operation) => {}"):
            with patch.object(Path, "read_text", side_effect=[host, branch]):
                contract.validate_materialized_source()
        with patch.object(Path, "read_text", side_effect=[host, "Err(BaoProductHostError::TerminalFailure(operation))"]):
            with self.assertRaisesRegex(SystemExit, "unboxed"):
                contract.validate_materialized_source()

    def test_source_caller_scan_ignores_comments_strings_and_test_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fake.rs").write_text('''
            // SqliteBaoProductRuntimeV1::new(host, owner, config)
            const TEXT: &str = "SqliteBaoProductRuntimeV1::new(host, owner, config)";
            #[cfg(test)]
            fn fixture() { SqliteBaoProductRuntimeV1::new(host, owner, config); }
            ''')
            (root / "real.rs").write_text('fn constructor() { SqliteBaoProductRuntimeV1::new(host, owner, config); }')
            with patch.object(contract, "ROOT", root):
                self.assertEqual(contract.rust_product_callers(), ["real.rs"])

    def test_retired_materializer_is_optional_for_frozen_source(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(contract, "MATERIALIZER", Path(directory) / "retired.yml"):
                contract.validate_materializer_role()


if __name__ == "__main__":
    unittest.main()
