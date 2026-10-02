#!/usr/bin/env python3
"""Exercise CI component setup without installing or downloading a toolchain."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cognitive_read_evidence import qualification_env


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/setup-cognitive-read-toolchain.sh"


class CognitiveReadToolchainSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.log = self.directory / "rustup.jsonl"
        rustup = self.directory / "rustup"
        rustup.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['SETUP_TEST_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "sys.exit(int(os.environ.get('SETUP_TEST_EXIT', '0')))\n"
        )
        rustup.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{self.directory}{os.pathsep}{os.environ['PATH']}",
            SETUP_TEST_LOG=str(self.log),
            RUSTUP_TOOLCHAIN="9.99.9",
        )

    def run_setup(self):
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_installs_and_verifies_components_on_candidate_pin(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        pin = qualification_env(ROOT)["RUSTUP_TOOLCHAIN"]
        self.assertEqual(
            [json.loads(line) for line in self.log.read_text().splitlines()],
            [
                [
                    "toolchain",
                    "install",
                    pin,
                    "--profile",
                    "minimal",
                    "--component",
                    "clippy",
                    "--component",
                    "rustfmt",
                    "--component",
                    "rust-src",
                ],
                ["run", pin, "rustfmt", "--version"],
                ["run", pin, "clippy-driver", "--version"],
            ],
        )

    def test_failed_install_stops_before_component_checks(self):
        self.env["SETUP_TEST_EXIT"] = "17"
        result = self.run_setup()
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
