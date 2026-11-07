"""Keep the ordinary Agentd entry bound to the migrated runtime profile guard."""

import importlib.util
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "codex-rs/hepta-agentd/src/runtime.rs"
SPEC = importlib.util.spec_from_file_location(
    "verify_hepta_callers_runtime_migration", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AgentdRuntimeCallerMigrationTests(unittest.TestCase):
    def setUp(self):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        self.guards = {
            "protected_file": [
                row for row in manifest["protected_file"] if row["path"] == RUNTIME
            ]
        }
        self.assertTrue(self.guards["protected_file"])
        self.source = (ROOT / RUNTIME).read_text()

    def check(self, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / RUNTIME
            path.parent.mkdir(parents=True)
            path.write_text(source)
            return MODULE._verify_protected_files(root, self.guards)

    def test_actual_wrapper_and_migrated_profile_body_pass_original_checker(self):
        self.assertEqual(
            self.check(self.source),
            [RUNTIME] * len(self.guards["protected_file"]),
        )

    def test_wrapper_cannot_omit_hide_or_substitute_the_guarded_runtime(self):
        self.check(self.source)
        call = "run_with_shutdown(config, arg0_paths, shutdown_signal()).await"
        self.assertEqual(self.source.count(call), 1)
        for replacement in (
            "Ok(())",
            f"/* {call} */ Ok(())",
            f'let unused = "{call}"; Ok(())',
            f"async fn unused() {{ {call} }} Ok(())",
            f"if false {{ {call} }} else {{ Ok(()) }}",
            "run_with_shutdown(other_config, arg0_paths, shutdown_signal()).await",
        ):
            with self.subTest(replacement=replacement):
                with self.assertRaises(MODULE.VerificationFailure):
                    self.check(self.source.replace(call, replacement, 1))

    def test_original_profile_selection_and_server_argument_remain_mandatory(self):
        self.check(self.source)
        for old, replacement in (
            (
                "crate::app_runtime::AppServerModelToolProfile::OriginalNotes",
                "crate::app_runtime::AppServerModelToolProfile::Standard",
            ),
            ("} else if notes_thread_tools.is_some()", "} else if false"),
            ("run_app_server(", "unreviewed_server("),
            (
                "                app_server_model_tools,",
                "                crate::app_runtime::AppServerModelToolProfile::Standard,",
            ),
        ):
            self.assertIn(old, self.source)
            with self.subTest(marker=old):
                with self.assertRaises(MODULE.VerificationFailure):
                    self.check(self.source.replace(old, replacement, 1))


if __name__ == "__main__":
    unittest.main()
