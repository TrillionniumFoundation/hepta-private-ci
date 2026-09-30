from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_focused_gate.py"
spec = importlib.util.spec_from_file_location(
    "channel_matrix_focused_gate_test", SCRIPT
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FocusedGateTests(unittest.TestCase):
    def test_commands_cover_locked_rust_and_all_matrix_repository_tests(self) -> None:
        self.assertEqual(module.RUST_COMMAND[:3], ["just", "test", "--locked"])
        self.assertEqual(
            module.REPOSITORY_COMMAND[1:],
            [
                "-m",
                "unittest",
                "discover",
                "-s",
                "../scripts/tests",
                "-p",
                "test_channel_matrix*.py",
                "-v",
            ],
        )
        self.assertEqual(
            set(module.PACKAGES),
            {
                "codex-hepta-matrix-protocol",
                "codex-hepta-matrix-store",
                "codex-hepta-matrix-sdk",
                "codex-hepta-matrixd",
            },
        )

    def test_main_executes_both_suites_and_requires_both(self) -> None:
        with mock.patch.object(module, "execute", side_effect=[7, 0]) as execute:
            self.assertEqual(module.main(), 1)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args_list[0].args[0], module.RUST_COMMAND)
        self.assertEqual(execute.call_args_list[1].args[0], module.REPOSITORY_COMMAND)

    def test_main_passes_only_when_both_suites_pass(self) -> None:
        with mock.patch.object(module, "execute", side_effect=[0, 0]):
            self.assertEqual(module.main(), 0)

    def test_launch_failure_is_a_hard_failure(self) -> None:
        with mock.patch.object(
            module.subprocess,
            "run",
            side_effect=OSError("missing"),
        ):
            self.assertEqual(module.execute(["missing-tool"]), 127)

    def test_execute_uses_canonical_codex_working_directory(self) -> None:
        result = subprocess.CompletedProcess(["tool"], 0)
        with mock.patch.object(module.subprocess, "run", return_value=result) as run:
            self.assertEqual(module.execute(["tool", "arg"]), 0)
        self.assertEqual(run.call_args.kwargs["cwd"], module.CODEX_ROOT)
        self.assertFalse(run.call_args.kwargs["check"])


if __name__ == "__main__":
    unittest.main()
