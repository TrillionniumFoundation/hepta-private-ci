#!/usr/bin/env python3
"""Lexical policy regressions; strings are not executable Rust calls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("policy", Path(__file__).with_name("hepta-ndu-source-policy.py"))
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class SourcePolicyTests(unittest.TestCase):
    def test_comments_raw_strings_characters_and_lifetimes(self):
        text = '''// evaluate_candidates();
/* outer /* evaluate_candidates() */ nested */
const NOTE: &str = r###"evaluate_candidates()"###;
const BYTE: &[u8] = br##"evaluate_candidates()"##;
const C: char = '\'';
fn borrowed<'a>(s: &'a str) { evaluate_candidates /* comment */ (s); }
'''
        masked = policy.code_only(text)
        matches = list(policy.LEGACY_CALL.finditer(masked))
        self.assertEqual(len(matches), 1)
        self.assertEqual(masked.count("\n"), text.count("\n"))
        self.assertEqual(len(masked), len(text))

    def test_scanner_rejects_real_caller_but_not_its_own_assertion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "codex-rs/client/src/lib.rs"
            source.parent.mkdir(parents=True)
            source.write_text('assert!(!source.contains("evaluate_candidates("));\n')
            with patch.object(policy, "ROOT", root):
                policy.main()
                source.write_text("fn run() { evaluate_candidates(set); }\n")
                with self.assertRaisesRegex(SystemExit, "FAIL_NDU_LEGACY_CALLER_POLICY"):
                    policy.main()

    def test_unterminated_literals_do_not_bypass_the_policy(self):
        for value in ('r###"never closed', '"unterminated', '/* open'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.code_only(value)


if __name__ == "__main__":
    unittest.main()
