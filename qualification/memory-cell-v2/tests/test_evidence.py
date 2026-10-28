"""Evidence tests use a genuine git history and deliberate byte/inventory drift."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v2.evidence import (
    V1,
    V2,
    seal_run,
    source_identity,
    source_snapshot,
    verify_run,
    verify_snapshot,
    verify_sources,
    write_json,
)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / V1).mkdir(parents=True)
        (self.repo / V2 / "sources").mkdir(parents=True)
        (self.repo / V1 / "model.py").write_text("weight = 1\n")
        (self.repo / V2 / "run_study.py").write_text("pass\n")
        (self.repo / V2 / "sources" / "input.bin").write_bytes(b"fixed real source")
        write_json(
            self.repo / V2 / "PROTOCOL.json",
            {
                "seeds": [211],
                "development_seeds": [8001],
                "stages": ["routing", "real"],
            },
        )
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Evidence Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "frozen test sources",
        )
        self.identity = source_identity(self.repo)
        self.output = self.repo / V2 / "results" / "test-run"

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, stderr=subprocess.STDOUT, text=True
        )

    def prepare_run(self, execution="completed", result_seed=211, completed=None):
        self.output.mkdir(parents=True)
        write_json(self.output / "source_identity.json", self.identity)
        (self.output / "protocol.json").write_bytes(
            (self.repo / V2 / "PROTOCOL.json").read_bytes()
        )
        write_json(
            self.output / "environment.json",
            {
                "mode": "frozen_protocol_research",
                "selected_seeds": [211],
                "stage": "routing",
            },
        )
        write_json(
            self.output / "execution_status.json",
            {
                "execution": execution,
                "completed_stages": ["routing"] if completed is None else completed,
            },
        )
        write_json(
            self.output
            / ("results.json" if execution == "completed" else "partial_results.json"),
            {"routing": {"development_only": False, "runs": [{"seed": result_seed}]}},
        )
        (self.output / "weights.bin").write_bytes(b"trained parameters")
        source_snapshot(self.output / "source_snapshot.zip", self.identity, self.repo)
        seal_run(self.output, self.identity)

    def test_exact_commit_and_dependency_binding(self):
        self.prepare_run()
        result = verify_run(self.output, self.repo)
        self.assertEqual(
            {
                k: result[k]
                for k in (
                    "verified",
                    "source_files",
                    "verified_files",
                    "commit_binding",
                )
            },
            {
                "verified": True,
                "source_files": 4,
                "verified_files": 7,
                "commit_binding": "exact-committed-bytes",
            },
        )
        (self.repo / V1 / "model.py").write_text("weight = 2\n")
        with self.assertRaisesRegex(ValueError, "current source"):
            verify_run(self.output, self.repo)
        uncommitted = source_identity(self.repo)
        with self.assertRaisesRegex(ValueError, "committed bytes"):
            verify_sources(uncommitted, self.repo)

    def test_source_data_and_new_executable_are_not_omitted(self):
        (self.repo / V2 / "sources" / "input.bin").write_bytes(b"replacement source")
        with self.assertRaisesRegex(ValueError, "current source"):
            verify_sources(self.identity, self.repo)
        (self.repo / V2 / "sources" / "input.bin").write_bytes(b"fixed real source")
        (self.repo / V2 / "injected.py").write_text("pass\n")
        with self.assertRaisesRegex(
            ValueError, "inventory differs from claimed commit"
        ):
            verify_sources(source_identity(self.repo), self.repo)

    def test_missing_extra_and_changed_run_bytes_fail(self):
        self.prepare_run()
        weights = self.output / "weights.bin"
        weights.write_bytes(b"changed parameters")
        with self.assertRaisesRegex(ValueError, "byte mismatch"):
            verify_run(self.output, self.repo)
        weights.unlink()
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            verify_run(self.output, self.repo)
        weights.write_bytes(b"trained parameters")
        (self.output / "undeclared.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            verify_run(self.output, self.repo)

    def test_failed_run_sealed_but_never_reported_completed(self):
        self.prepare_run("failed")
        with self.assertRaisesRegex(ValueError, "did not complete"):
            verify_run(self.output, self.repo)
        self.assertEqual(
            verify_run(self.output, self.repo, allow_failed=True)["execution"], "failed"
        )
        with self.assertRaisesRegex(ValueError, "refuse to reseal"):
            seal_run(self.output, self.identity)

    def test_invented_completed_stage_is_rejected_even_with_valid_hashes(self):
        self.prepare_run(completed=["routing", "real"])
        with self.assertRaisesRegex(ValueError, "completed stages"):
            verify_run(self.output, self.repo)

    def test_wrong_component_seed_is_rejected_even_with_valid_hashes(self):
        self.prepare_run(result_seed=8001)
        with self.assertRaisesRegex(ValueError, "seeds/mode"):
            verify_run(self.output, self.repo)

    def test_source_snapshot_retains_bytes_and_rejects_replacement(self):
        snapshot = self.repo / "snapshot.zip"
        source_snapshot(snapshot, self.identity, self.repo)
        verify_snapshot(snapshot, self.identity)
        with zipfile.ZipFile(
            snapshot, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name in self.identity["files"]:
                raw = (self.repo / name).read_bytes()
                archive.writestr(name, b"X" * len(raw))
        with self.assertRaisesRegex(ValueError, "snapshot bytes"):
            verify_snapshot(snapshot, self.identity)

    def test_symlink_and_forged_manifest_path_fail(self):
        self.prepare_run()
        weights = self.output / "weights.bin"
        weights.unlink()
        weights.symlink_to(self.repo / V2 / "sources" / "input.bin")
        with self.assertRaisesRegex(ValueError, "symlink"):
            verify_run(self.output, self.repo)
        weights.unlink()
        weights.write_bytes(b"trained parameters")
        manifest_path = self.output / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["../escape.bin"] = manifest["files"].pop("weights.bin")
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            verify_run(self.output, self.repo)


if __name__ == "__main__":
    unittest.main()
