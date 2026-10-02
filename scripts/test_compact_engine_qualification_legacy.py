from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("compact_engine_qualification.py")
SPEC = importlib.util.spec_from_file_location("compact_engine_qualification", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
QUALIFICATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = QUALIFICATION
SPEC.loader.exec_module(QUALIFICATION)


def write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class CompactEngineMapVerificationTests(unittest.TestCase):
    def test_unreachable_rust_test_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write(
                root / "codex-rs/hepta-compact-engine/src/lib.rs",
                "pub fn owner_entrypoint() {}\n",
            )
            test_path = "codex-rs/hepta-compact-engine/src/orphan_tests.rs"
            write(root / test_path, "#[test]\nfn owner_contract() {}\n")
            write(
                root / "docs/modules/compact.engine/IMPLEMENTATION_MAP.json",
                json.dumps(
                    {
                        "schema": "hepta.module-implementation-map.v3",
                        "module": "compact.engine",
                        "operations": [
                            {
                                "operation": "owner",
                                "nativeSymbol": "owner_entrypoint",
                                "sourcePath": "codex-rs/hepta-compact-engine/src/lib.rs",
                                "sourcePathExists": True,
                                "tests": [test_path],
                                "delegatedCallees": [],
                            }
                        ],
                    }
                ),
            )

            with self.assertRaisesRegex(
                QUALIFICATION.QualificationError,
                "not reachable from the crate test graph",
            ):
                QUALIFICATION.verify_implementation_map(root)

            write(
                root / "codex-rs/hepta-compact-engine/src/lib.rs",
                "pub fn owner_entrypoint() {}\n#[cfg(test)]\nmod orphan_tests;\n",
            )
            report = QUALIFICATION.verify_implementation_map(root)
            self.assertTrue(report["verified"])
            self.assertEqual(report["mapped_test_sources"], [test_path])


class CompactEngineReadinessManifestTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()

    def create_repository(self, root: Path) -> str:
        paths = set(QUALIFICATION.MIGRATION_INPUTS)
        paths.add(QUALIFICATION.MAP_PATH)
        paths.update(QUALIFICATION.DOCUMENTATION_INPUTS)
        paths.update(QUALIFICATION.QUALIFICATION_PROFILE_INPUTS)
        paths.update(
            {
                Path("codex-rs/Cargo.lock"),
                QUALIFICATION.AGENTD_HOST,
                Path("codex-rs/hepta-compact-engine/src/lib_tests.rs"),
            }
        )
        for path in paths:
            content = "{}\n" if path.suffix == ".json" else f"fixture {path.as_posix()}\n"
            write(root / path, content)
        self.git(root, "init", "-q")
        self.git(root, "config", "user.name", "compact.engine test")
        self.git(root, "config", "user.email", "compact-engine-test@example.invalid")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "fixture")
        return self.git(root, "rev-parse", "HEAD")

    def create_artifacts(
        self,
        root: Path,
        *,
        source_sha: str,
        workflow_sha: str,
        base_sha: str,
        deterministic_merge_sha: str,
    ) -> Path:
        artifacts = root / "artifacts"
        identities = {
            "compact-engine-source-fixture-7": {
                "lane": "source_snapshot",
                "checked_sha": source_sha,
            },
            "compact-engine-exact-head-fixture-7": {
                "lane": "exact_head",
                "checked_sha": source_sha,
                "target_triple": "x86_64-unknown-linux-gnu",
            },
            "compact-engine-synthetic-merge-fixture-7": {
                "lane": "synthetic_merge",
                "checked_sha": deterministic_merge_sha,
                "target_triple": "x86_64-unknown-linux-gnu",
            },
            "compact-engine-capacity-required-fixture-7": {
                "lane": "capacity",
                "checked_sha": source_sha,
                "target_triple": "x86_64-unknown-linux-gnu",
            },
        }
        for name, lane_fields in identities.items():
            directory = artifacts / name
            identity = {
                "source_head_sha": source_sha,
                "frozen_source_sha": source_sha,
                "base_sha": base_sha,
                "github_merge_sha": workflow_sha,
                "workflow_sha": workflow_sha,
                "workflow_run_id": "42",
                "attempt_id": "7",
                "event_name": "pull_request",
                "runner_image": "ubuntu24/20260930.1",
                **lane_fields,
            }
            write(directory / "identity.json", json.dumps(identity))
            write(directory / "success.json", '{"success":true}\n')
        return artifacts

    def test_manifest_requires_one_successful_attempt_for_every_lane(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_sha = self.create_repository(root)
            workflow_sha = "c" * 40
            base_sha = "b" * 40
            deterministic_merge_sha = "d" * 40
            artifacts = self.create_artifacts(
                root,
                source_sha=source_sha,
                workflow_sha=workflow_sha,
                base_sha=base_sha,
                deterministic_merge_sha=deterministic_merge_sha,
            )
            output = root / "readiness.json"
            manifest = QUALIFICATION.build_readiness_manifest(
                root,
                artifacts,
                output,
                source_head_sha=source_sha,
                frozen_source_sha=source_sha,
                workflow_sha=workflow_sha,
                github_merge_sha=workflow_sha,
                final_merge_sha="",
                workflow_run_id="42",
                attempt_id="7",
                event_name="pull_request",
                source_result="success",
                qualify_result="success",
                capacity_result="success",
                postmerge_result="not-run",
            )
            self.assertTrue(manifest["requiredLanesPassed"])
            self.assertTrue(manifest["mergeReady"])
            self.assertFalse(manifest["productionQualified"])
            self.assertEqual(manifest["source_head_sha"], source_sha)
            self.assertEqual(manifest["deterministic_merge_sha"], deterministic_merge_sha)
            self.assertEqual(set(manifest["artifact_hashes"]), {
                "compact-engine-source-fixture-7",
                "compact-engine-exact-head-fixture-7",
                "compact-engine-synthetic-merge-fixture-7",
                "compact-engine-capacity-required-fixture-7",
            })

            (artifacts / "compact-engine-synthetic-merge-fixture-7/success.json").unlink()
            manifest = QUALIFICATION.build_readiness_manifest(
                root,
                artifacts,
                output,
                source_head_sha=source_sha,
                frozen_source_sha=source_sha,
                workflow_sha=workflow_sha,
                github_merge_sha=workflow_sha,
                final_merge_sha="",
                workflow_run_id="42",
                attempt_id="7",
                event_name="pull_request",
                source_result="success",
                qualify_result="success",
                capacity_result="success",
                postmerge_result="not-run",
            )
            self.assertFalse(manifest["requiredLanesPassed"])
            self.assertFalse(manifest["mergeReady"])
            self.assertFalse(manifest["productionQualified"])
            self.assertIn(
                "synthetic_merge artifact has no success marker",
                manifest["generation_errors"],
            )

    def test_final_main_sha_requires_same_run_postmerge_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_sha = self.create_repository(root)
            base_sha = "b" * 40
            deterministic_merge_sha = "d" * 40
            artifacts = self.create_artifacts(
                root,
                source_sha=source_sha,
                workflow_sha=source_sha,
                base_sha=base_sha,
                deterministic_merge_sha=deterministic_merge_sha,
            )
            for identity_path in artifacts.glob("*/identity.json"):
                identity = json.loads(identity_path.read_text(encoding="utf-8"))
                identity["event_name"] = "push"
                identity["github_merge_sha"] = ""
                identity_path.write_text(json.dumps(identity), encoding="utf-8")

            output = root / "readiness.json"
            manifest = QUALIFICATION.build_readiness_manifest(
                root,
                artifacts,
                output,
                source_head_sha=source_sha,
                frozen_source_sha=source_sha,
                workflow_sha=source_sha,
                github_merge_sha="",
                final_merge_sha=source_sha,
                workflow_run_id="42",
                attempt_id="7",
                event_name="push",
                source_result="success",
                qualify_result="success",
                capacity_result="success",
                postmerge_result="success",
            )
            self.assertTrue(manifest["requiredLanesPassed"])
            self.assertFalse(manifest["mergeReady"])
            self.assertTrue(manifest["productionQualified"])

            manifest = QUALIFICATION.build_readiness_manifest(
                root,
                artifacts,
                output,
                source_head_sha=source_sha,
                frozen_source_sha=source_sha,
                workflow_sha=source_sha,
                github_merge_sha="",
                final_merge_sha=source_sha,
                workflow_run_id="42",
                attempt_id="7",
                event_name="push",
                source_result="success",
                qualify_result="success",
                capacity_result="success",
                postmerge_result="not-run",
            )
            self.assertFalse(manifest["productionQualified"])


if __name__ == "__main__":
    unittest.main()
