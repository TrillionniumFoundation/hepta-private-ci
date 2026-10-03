"""Execute diagnostic shell snippets: retaining a log must not mask failure.

The fake Python/Cargo commands test exit propagation and stream separation only;
these tests do not claim native compilation or workspace qualification.
"""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from hepta_workflow_commands import load_workflow, workflow_run, workflow_step_by_id


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/hepta-integration-diagnostics.yml"
)


def command_for(step_id: str) -> str:
    workflow = load_workflow(WORKFLOW.read_text(encoding="utf-8"))
    step = workflow_step_by_id(workflow, "source-preflight", step_id)
    if step.get("shell") != "bash":
        raise AssertionError(f"shell semantics must be explicit: {step_id}")
    return workflow_run(step)


class PreflightLoggingTests(unittest.TestCase):
    def run_command(self, step: str, executable: str, status: int):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        bindir = root / "bin"
        bindir.mkdir()
        logs = root / "hepta-source-preflight"
        logs.mkdir()
        tool = bindir / executable
        tool.write_text(
            "#!/bin/sh\nprintf '%s\\n' 'fixture-stdout'\n"
            "printf '%s\\n' 'fixture-stderr' >&2\n"
            f"exit {status}\n",
            encoding="utf-8",
        )
        tool.chmod(0o700)
        result = subprocess.run(
            ["bash", "-c", command_for(step)],
            cwd=root,
            env={
                **os.environ,
                "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                "RUNNER_TEMP": str(root),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, logs

    def test_manifest_failure_retains_both_streams_and_exit_code(self):
        result, logs = self.run_command("manifest", "python3", 7)
        self.assertEqual(result.returncode, 7)
        log = (logs / "workspace-preflight.log").read_text()
        self.assertIn("fixture-stdout", log)
        self.assertIn("fixture-stderr", log)

    def test_manifest_success_is_preserved(self):
        result, logs = self.run_command("manifest", "python3", 0)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((logs / "workspace-preflight.log").is_file())

    def test_metadata_failure_retains_stderr_without_corrupting_stdout(self):
        result, logs = self.run_command("metadata", "cargo", 9)
        self.assertEqual(result.returncode, 9)
        self.assertEqual((logs / "cargo-metadata.json").read_text(), "fixture-stdout\n")
        self.assertEqual(
            (logs / "cargo-metadata.stderr.log").read_text(), "fixture-stderr\n"
        )

    def test_metadata_success_preserves_separate_outputs(self):
        result, logs = self.run_command("metadata", "cargo", 0)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("fixture-stderr", (logs / "cargo-metadata.json").read_text())


if __name__ == "__main__":
    unittest.main()
