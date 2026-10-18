"""Execute the archive profile setup without changing product build semantics."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hepta_workflow_commands", ROOT / "scripts/hepta_workflow_commands.py"
)
WORKFLOW_COMMANDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW_COMMANDS)


class ArchiveProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="archive profile ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = self.root / "github environment"
        workflow = WORKFLOW_COMMANDS.load_workflow(
            (ROOT / ".github/workflows/rust-ci-full-nextest-platform.yml").read_text()
        )
        self.script = next(
            step["run"]
            for step in workflow["jobs"]["archive"]["steps"]
            if step.get("name", "").endswith("test archive debug data")
        )

    def execute(self, operating_system, profile, *, existing="UNCHANGED=present\n"):
        self.environment.write_text(existing)
        env = {
            **os.environ,
            "RUNNER_OS": operating_system,
            "CODEX_CI_PROFILE": profile,
            "GITHUB_ENV": str(self.environment),
        }
        result = subprocess.run(
            ["bash", "-c", self.script],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.environment.read_text()

    def test_unix_archive_setup_keeps_existing_environment(self):
        for operating_system in ("Linux", "macOS"):
            with self.subTest(operating_system=operating_system):
                self.assertEqual(
                    self.execute(operating_system, "ci-test"),
                    "UNCHANGED=present\nCARGO_PROFILE_CI_TEST_DEBUG=0\n",
                )

    def test_windows_archive_keeps_its_existing_profile(self):
        existing = "CARGO_PROFILE_CI_TEST_DEBUG=2\nUNCHANGED=present\n"
        self.assertEqual(
            self.execute("Windows", "ci-test", existing=existing), existing
        )

    def test_release_and_custom_profiles_are_not_overridden(self):
        for operating_system in ("Linux", "macOS", "Windows"):
            for profile in ("release", "dev", "profiling", "custom"):
                with self.subTest(operating_system=operating_system, profile=profile):
                    self.assertEqual(
                        self.execute(operating_system, profile), "UNCHANGED=present\n"
                    )

    def test_unknown_platform_keeps_its_existing_profile(self):
        self.assertEqual(self.execute("Other", "ci-test"), "UNCHANGED=present\n")


if __name__ == "__main__":
    unittest.main()
