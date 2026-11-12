"""Keep exact function-order guards narrow and unique for simple Rust generics."""

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "generic_function_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class ExactGenericFunctionOrderTests(unittest.TestCase):
    def verify(self, source, marker):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        PROOF._verify_function_order(
            {"required_function_order": [{
                "function": marker, "sequence": ["before();", "after();"]
            }]}, code, "original.rs", source
        )

    def test_existing_and_actual_generic_markers_remain_exact(self):
        for marker in ("fn run(", "fn run<W>(", "fn run<W: AnchorWitnessStore>(",
                       "fn run<Old, New>(", "fn run<Old: Store, New: Store>("):
            with self.subTest(marker=marker):
                self.verify(marker + ") { before(); after(); }", marker)

    def test_missing_and_duplicate_definitions_are_refused(self):
        marker = "fn run<Old, New>("
        one = marker + ") { before(); after(); }"
        for source in ("fn other() { before(); after(); }", one + "\n" + one):
            with self.subTest(source=source):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verify(source, marker)

    def test_comment_literal_and_test_only_functions_cannot_supply_definition(self):
        marker = "fn run<W>("
        definition = marker + ") { before(); after(); }"
        for source in ("// " + definition, 'const S: &str = "' + definition + '";',
                       "#[cfg(test)]\n" + definition):
            with self.subTest(source=source):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verify(source, marker)

    def test_reordered_and_nested_calls_cannot_supply_original_body(self):
        marker = "fn run<W>("
        for body in ("after(); before();",
                     "fn nested() { before(); after(); }",
                     "/* before(); */ after();",
                     'let text = "before();"; after();'):
            with self.subTest(body=body):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verify(marker + ") {" + body + "}", marker)

    def test_unimplemented_generic_grammar_is_rejected_without_fuzzy_matching(self):
        for marker in ("fn run<>(", "fn run<Old,>(", "fn run<T: A + B>(",
                       "fn run<'a>(", "fn run<const N: usize>(", "fn run <T>("):
            with self.subTest(marker=marker):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verify(marker + ") { before(); after(); }", marker)


if __name__ == "__main__":
    unittest.main()
