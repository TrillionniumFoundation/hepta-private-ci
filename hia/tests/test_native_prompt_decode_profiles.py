#!/usr/bin/env python3
"""Check explicit profile routing without replacing the real native admission."""
import argparse
import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_native_prompt_decode_caller as caller


class ReachedCompiler(Exception):
    pass


class PromptProfileAdmission(unittest.TestCase):
    def verify_profile(self, profile, flags):
        selected = []
        report = {"native_build": dict(flags), "inputs": {}, "commands": []}
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(rustc="rustc", library_dir=Path(directory),
                                   build_profile=profile)
            def admit(library, source, requested, actual_report):
                selected.append(requested)
                self.assertIs(actual_report, report)
            with patch.object(caller.shutil, "which", return_value="/compiler-not-invoked"), \
                    patch.object(caller, "native_inputs", side_effect=admit), \
                    patch.object(caller, "run", side_effect=ReachedCompiler):
                try:
                    caller.verify(args, report)
                finally:
                    self.assertEqual(selected, [profile])

    def test_each_complete_profile_uses_its_own_strict_receipt_flag(self):
        for profile, key in (("full-native37", "full37_manifest_verified"),
                             ("full-native38", "full38_manifest_verified")):
            with self.subTest(profile=profile), self.assertRaises(ReachedCompiler):
                self.verify_profile(profile, {key: True})

    def test_other_profile_success_cannot_admit_current_profile(self):
        for profile, key in (("full-native37", "full38_manifest_verified"),
                             ("full-native38", "full37_manifest_verified")):
            with self.subTest(profile=profile), self.assertRaises(RuntimeError):
                self.verify_profile(profile, {key: True})

    def test_missing_false_integer_float_and_text_flags_are_rejected(self):
        for value in (False, 1, 1.0, "true", None):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.verify_profile("full-native38", {"full38_manifest_verified": value})
        with self.assertRaises(RuntimeError):
            self.verify_profile("full-native38", {})

    def test_cli_keeps_legacy_default_and_admits_only_named_profiles(self):
        # Read the production parser declaration itself; all other arguments stay
        # in the real caller. This control does not claim native execution.
        tree = ast.parse(Path(caller.__file__).read_bytes())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        declaration = next(n for n in main.body if isinstance(n, ast.Expr)
                           and isinstance(n.value, ast.Call)
                           and n.value.args and isinstance(n.value.args[0], ast.Constant)
                           and n.value.args[0].value == "--build-profile")
        parser = argparse.ArgumentParser()
        exec(compile(ast.Module(body=[declaration], type_ignores=[]),
                     str(caller.__file__), "exec"), {"parser": parser})
        self.assertEqual(parser.parse_args([]).build_profile, "full-native37")
        self.assertEqual(parser.parse_args(["--build-profile", "full-native38"]).build_profile,
                         "full-native38")
        with self.assertRaises(SystemExit):
            parser.parse_args(["--build-profile", "full-native39"])


if __name__ == "__main__":
    unittest.main()
