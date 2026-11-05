"""Integrity rejection tests use a temporary git tree, never scientific scores."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from verify_evidence import verify


class EvidenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.package = self.repo / "qualification/memory-cell-research"
        self.package.mkdir(parents=True)
        self.source = self.package / "fixture.py"
        self.source.write_text("def fixture():\n    return 'first'\n")
        (self.package / "PROTOCOL.json").write_text('{"mechanism_fixture":true}\n')
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=MemoryCell Test",
            "-c",
            "user.email=memory-cell@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "temporary source fixture",
        )
        self.commit = self.git("rev-parse", "HEAD").strip()
        self.output = self.root / "run"
        self.output.mkdir()
        self.identity = {
            "commit": self.commit,
            "files": {
                path.relative_to(self.repo).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in self.package.iterdir()
            },
        }
        (self.output / "source_identity.json").write_text(json.dumps(self.identity))
        (self.output / "environment.json").write_text(
            json.dumps(
                {
                    "mode": "frozen_protocol_research",
                    "source_dirty": False,
                    "fixture_only": True,
                }
            )
        )
        (self.output / "execution_status.json").write_text(
            json.dumps({"execution": "completed"})
        )
        (self.output / "raw.json").write_text('{"fixture":"file integrity only"}\n')
        self.reseal()

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.repo, text=True)

    def reseal(self):
        inventory = {
            path.relative_to(self.output).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in self.output.rglob("*")
            if path.is_file()
            and path.relative_to(self.output).as_posix() != "MANIFEST.json"
        }
        (self.output / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "schema": "memory-cell-research.evidence.v1",
                    "source_commit": self.commit,
                    "files": inventory,
                    "execution_success_is_not_efficacy": True,
                }
            )
        )

    def test_accepts_exact_fixture_without_inferring_efficacy(self):
        result = verify(self.output, self.repo)
        self.assertTrue(result["verified"])
        self.assertTrue(result["scientific_efficacy_not_inferred"])
        self.assertEqual(result["commit_binding"], "exact-committed-bytes")

    def test_missing_file_is_rejected(self):
        (self.output / "raw.json").unlink()
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify(self.output, self.repo)

    def test_extra_file_is_rejected(self):
        (self.output / "undeclared.txt").write_text("not inventoried")
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify(self.output, self.repo)

    def test_nested_manifest_name_cannot_hide_an_extra_file(self):
        nested = self.output / "nested"
        nested.mkdir()
        (nested / "MANIFEST.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify(self.output, self.repo)

    def test_modified_bytes_are_rejected(self):
        (self.output / "raw.json").write_text('{"fixture":"changed data"}\n')
        with self.assertRaisesRegex(ValueError, "byte mismatch"):
            verify(self.output, self.repo)

    def test_current_source_drift_is_rejected(self):
        self.source.write_text("def fixture():\n    return 'different'\n")
        with self.assertRaisesRegex(ValueError, "source differs"):
            verify(self.output, self.repo)

    def test_omitted_source_entry_is_rejected_even_after_evidence_resealing(self):
        del self.identity["files"][self.source.relative_to(self.repo).as_posix()]
        (self.output / "source_identity.json").write_text(json.dumps(self.identity))
        self.reseal()
        with self.assertRaisesRegex(ValueError, "source inventory"):
            verify(self.output, self.repo)

    def test_removing_current_source_and_its_identity_cannot_hide_committed_source(
        self,
    ):
        del self.identity["files"][self.source.relative_to(self.repo).as_posix()]
        self.source.unlink()
        (self.output / "source_identity.json").write_text(json.dumps(self.identity))
        self.reseal()
        with self.assertRaisesRegex(ValueError, "inventory"):
            verify(self.output, self.repo)

    def test_root_manifest_symlink_is_rejected(self):
        manifest_path = self.output / "MANIFEST.json"
        outside = self.root / "external-manifest.json"
        outside.write_bytes(manifest_path.read_bytes())
        manifest_path.unlink()
        try:
            manifest_path.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symbolic links unavailable on this host: {error}")
        with self.assertRaises(ValueError):
            verify(self.output, self.repo)

    def test_claimed_commit_must_contain_the_executed_source_bytes(self):
        self.source.write_text("def fixture():\n    return 'uncommitted'\n")
        self.identity["files"][self.source.relative_to(self.repo).as_posix()] = (
            hashlib.sha256(self.source.read_bytes()).hexdigest()
        )
        (self.output / "source_identity.json").write_text(json.dumps(self.identity))
        self.reseal()
        with self.assertRaisesRegex(ValueError, "claimed commit"):
            verify(self.output, self.repo)


if __name__ == "__main__":
    unittest.main()
