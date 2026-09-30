from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/channel_matrix_readiness.py"
SPEC = importlib.util.spec_from_file_location("channel_matrix_readiness", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def file_row(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "gitBlob": hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def lane(name: str, tested_sha: str, tree: str, source_sha: str, base_sha: str, run: str = "41", attempt: str = "2"):
    source = {
        "schema": "hepta.channel-matrix-source-snapshot.v1",
        "lane": name,
        "sourceSha": source_sha,
        "baseSha": base_sha,
        "testedSha": tested_sha,
        "testedTree": tree,
        "files": [file_row("tracked", b"same")],
    }
    return {
        "source": source,
        "status": {"candidate": {"commit": tested_sha, "tree": tree, "lane": name}},
        "ledger": {
            "registry_sha256": "a" * 64,
            "external_gates_remaining": ["real_target"],
        },
        "manifest": {
            "runId": run,
            "runAttempt": attempt,
            "artifactSetSha256": "b" * 64,
        },
        "provenance": {
            "workflow": {"sha256": "0" * 64},
            "execution": {
                "workflowRunId": run,
                "attemptId": attempt,
                "runnerImage": "ubuntu24@20260929.1",
                "targetTriple": "x86_64-unknown-linux-gnu",
            },
        },
        "digests": {
            "candidate": "1" * 64,
            "source": "2" * 64,
            "status": "3" * 64,
            "scenarioLedger": "4" * 64,
            "manifest": "5" * 64,
            "provenanceBefore": "6" * 64,
            "provenanceAfter": "7" * 64,
        },
    }


class ReadinessTests(unittest.TestCase):
    def test_cross_attempt_evidence_is_rejected(self) -> None:
        rows = {
            "source-head": lane("source-head", "1" * 40, "2" * 40, "1" * 40, "0" * 40),
            "base-merge": lane("base-merge", "3" * 40, "4" * 40, "1" * 40, "0" * 40, attempt="3"),
        }
        with self.assertRaisesRegex(ValueError, "one workflow run and attempt"):
            MODULE.require_same_execution(rows)

    def test_hash_groups_bind_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "codex-rs/Cargo.lock": b"lock\n",
                "codex-rs/hepta-matrix-store/migrations/0001.sql": b"create table x;\n",
                "scripts/tests/test_channel_matrix_example.py": b"pass\n",
                "docs/modules/channel.matrix/QUALIFICATION_SCENARIOS.json": b"{}\n",
                "codex-rs/.config/nextest.toml": b"[profile.default]\n",
                "docs/modules/channel.matrix/PRODUCTION_QUALIFICATION_PROFILE.json": b"{}\n",
                "docs/modules/channel.matrix/IMPLEMENTATION_MAP.json": json.dumps(
                    {"observedAtHead": {"commit": "1" * 40, "tree": "2" * 40}}
                ).encode(),
                "docs/modules/channel.matrix/TECHNICAL.md": b"technical\n",
                ".github/workflows/channel-matrix-preserve-unknown.yml": b"name: exact\n",
            }
            rows = []
            for path, payload in files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                rows.append(file_row(path, payload))
            source = {"testedTree": "3" * 40, "files": rows}
            result = MODULE.derive_hashes(root, source)
            self.assertEqual(result["Cargo.lock_hash"], hashlib.sha256(files["codex-rs/Cargo.lock"]).hexdigest())
            self.assertEqual(result["frozen_source_sha"], "1" * 40)
            for key in (
                "migration_hash",
                "test_set_hash",
                "qualification_profile_hash",
                "implementation_map_hash",
                "documentation_hash",
                "workflow_sha",
            ):
                self.assertRegex(result[key], r"^[0-9a-f]{64}$")

    def test_pull_request_manifest_is_single_run_and_fail_closed_for_production(self) -> None:
        source_sha = "1" * 40
        base_sha = "2" * 40
        source_tree = "3" * 40
        merge_tree = "4" * 40
        fixtures = {
            "source-head": lane("source-head", source_sha, source_tree, source_sha, base_sha),
            "base-merge": lane("base-merge", "5" * 40, merge_tree, source_sha, base_sha),
            "github-merge": lane("github-merge", "6" * 40, merge_tree, source_sha, base_sha),
        }
        hashes = {
            "Cargo.lock_hash": "a" * 64,
            "migration_hash": "b" * 64,
            "test_set_hash": "c" * 64,
            "qualification_profile_hash": "d" * 64,
            "implementation_map_hash": "e" * 64,
            "documentation_hash": "f" * 64,
            "workflow_sha": "0" * 64,
            "source_tree_hash": source_tree,
            "frozen_source_sha": "7" * 40,
        }

        def fake_load(_path, name):
            return fixtures[name]

        with mock.patch.object(MODULE, "load_lane", side_effect=fake_load), mock.patch.object(
            MODULE, "derive_hashes", return_value=hashes.copy()
        ), mock.patch.object(MODULE, "snapshot_hashes", return_value=hashes.copy()):
            row = MODULE.readiness(
                Path.cwd(),
                Path("source"),
                Path("base"),
                Path("github"),
                "pull-request",
                source_sha,
                base_sha,
                None,
            )
        self.assertTrue(row["mergeReady"])
        self.assertFalse(row["productionQualified"])
        self.assertEqual(row["workflow_run_id"], "41")
        self.assertEqual(row["attempt_id"], "2")
        self.assertEqual(row["github_merge_sha"], "6" * 40)
        self.assertIsNone(row["final_merge_sha"])
        self.assertIn("final_merge_sha_not_yet_available", row["blockers"])
        self.assertFalse(row["claims"]["mixedEvidenceAccepted"])


if __name__ == "__main__":
    unittest.main()
