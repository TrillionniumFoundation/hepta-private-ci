import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/context-compiler-qualification.yml"


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux workflow shell fixture")
class ContextArtifactManifestTests(unittest.TestCase):
    def manifest_command(self):
        workflow = WORKFLOW.read_text()
        block = workflow.split(
            "- name: Bind artifact attestation to immutable execution", 1
        )[1]
        block = block.split(
            "- name: Retain candidate, partial failures and command receipts", 1
        )[0]
        return textwrap.dedent(block.split("run: |", 1)[1])

    def test_manifest_contains_every_nonself_file_and_verifies_on_repeat(self):
        command = self.manifest_command()
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "context-evidence"
            (evidence / "logs").mkdir(parents=True)
            (evidence / "nested").mkdir()
            files = {
                "candidate.json": b'{"candidate": "exact"}\n',
                "receipt.json": b'{"execution": false}\n',
                "logs/a log.txt": b"failed command retained\n",
                "empty": b"",
                "nested/artifact-files.sha256": b"ordinary nested payload\n",
            }
            for name, content in files.items():
                (evidence / name).write_bytes(content)
            manifest = evidence / "artifact-files.sha256"
            env = dict(os.environ, RUNNER_TEMP=directory)
            previous = None
            for _ in range(2):
                subprocess.run(["bash", "-c", command], env=env, check=True)
                actual = {}
                for line in manifest.read_text().splitlines():
                    digest, separator, path = line.partition("  ")
                    self.assertEqual(separator, "  ")
                    relative = Path(path).relative_to(evidence).as_posix()
                    self.assertNotIn(relative, actual)
                    actual[relative] = digest
                expected = {
                    name: hashlib.sha256(content).hexdigest()
                    for name, content in files.items()
                }
                self.assertEqual(actual, expected)
                subprocess.run(
                    ["sha256sum", "--check", str(manifest)],
                    check=True,
                    capture_output=True,
                )
                if previous is not None:
                    self.assertEqual(manifest.read_bytes(), previous)
                previous = manifest.read_bytes()

    def test_empty_evidence_has_no_phantom_stdin_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "context-evidence"
            evidence.mkdir()
            subprocess.run(
                ["bash", "-c", self.manifest_command()],
                env=dict(os.environ, RUNNER_TEMP=directory),
                check=True,
            )
            self.assertEqual((evidence / "artifact-files.sha256").read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
