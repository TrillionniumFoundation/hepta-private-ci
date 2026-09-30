from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_pair_acceptance_v2.py"
spec = importlib.util.spec_from_file_location(
    "channel_matrix_pair_acceptance_v2_test", SCRIPT
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def empty_sha256() -> str:
    return hashlib.sha256(b"").hexdigest()


class ExtendedPairAcceptanceTests(unittest.TestCase):
    def source(self) -> dict:
        paths = sorted(
            module.REQUIRED_EXACT_PATHS
            | {f"{prefix}fixture" for prefix in module.REQUIRED_PREFIXES}
        )
        return {
            "testedSha": "1" * 40,
            "testedTree": "2" * 40,
            "files": [{"path": path} for path in paths],
        }

    def write_receipt(
        self,
        directory,
        source,
        label,
        arguments,
        *,
        with_junit,
    ):
        log = directory / f"{label}.log"
        log.write_text(f"{label} passed\n", encoding="utf-8")
        inventory = {log.name: {}}
        junit = None
        if with_junit:
            junit_path = directory / "focused-tests.junit.xml"
            junit_path.write_text("<testsuites/>\n", encoding="utf-8")
            inventory[junit_path.name] = {}
            junit = {
                "path": junit_path.name,
                "bytes": junit_path.stat().st_size,
                "sha256": digest(junit_path),
            }
        command = {
            "schema": "hepta.channel-matrix-command.v1",
            "label": label,
            "arguments": arguments,
            "workingDirectory": "codex-rs",
            "testedSha": source["testedSha"],
            "sourceSnapshotSha256": digest(directory / "source.json"),
            "exitCode": 0,
            "completed": True,
            "launchError": None,
            "junit": junit,
            "sourceUnchanged": True,
            "log": {
                "path": log.name,
                "bytes": log.stat().st_size,
                "sha256": digest(log),
                "withinBudget": True,
            },
        }
        command_path = directory / f"{label}.command.json"
        command_path.write_text(json.dumps(command), encoding="utf-8")
        inventory[command_path.name] = {}
        return inventory

    def write_provenance(
        self,
        directory,
        source,
        lane,
        *,
        run_id="42",
        attempt="1",
    ):
        workspace = "/tmp/channel-matrix-pair-fixture"
        files = [
            {
                "absolutePath": f"{workspace}/fixture",
                "repoRelativePath": "fixture",
                "gitBlob": "3" * 40,
                "sha256": "4" * 64,
                "bytes": 1,
                "tracked": True,
                "gitLsFilesErrorUnmatch": True,
                "trackedCheck": {
                    "command": [
                        "git",
                        "ls-files",
                        "--error-unmatch",
                        "--",
                        "fixture",
                    ],
                    "exitStatus": 0,
                    "stdoutSha256": "5" * 64,
                    "stderrSha256": "6" * 64,
                },
                "introducedAtCommit": "7" * 40,
                "firstObservedStage": lane,
                "origin": "tracked_repository_source",
                "sourceClass": "tracked_repository_source",
                "classification": {
                    "fixture": True,
                    "workflow": False,
                    "documentation": False,
                    "generated": False,
                    "cache": False,
                    "artifact": False,
                },
            }
        ]
        clean = {
            "clean": True,
            "unstaged": [],
            "staged": [],
            "untrackedClosureInputs": [],
            "ignoredClosureInputs": [],
            "workspaceStatus": {
                "command": [
                    "git",
                    "status",
                    "--porcelain=v2",
                    "-z",
                    "--untracked-files=all",
                ],
                "bytes": 0,
                "sha256": empty_sha256(),
                "empty": True,
            },
        }
        row = {
            "schema": "hepta.channel-matrix-source-provenance.v1",
            "valid": True,
            "errors": [],
            "stage": lane,
            "workspaceRoot": workspace,
            "checkoutSha": source["testedSha"],
            "checkoutTree": source["testedTree"],
            "scan": {
                "defaultCommand": ["git", "ls-files", "-z"],
                "closureFileCount": 1,
                "closurePathInventorySha256": module.source_provenance.path_inventory(
                    ["fixture"]
                ),
                "cleanBefore": clean,
                "cleanAfter": clean,
            },
            "execution": {
                "workflowRunId": run_id,
                "attemptId": attempt,
                "runnerImage": "ubuntu24:fixture",
                "targetTriple": "x86_64-unknown-linux-gnu",
            },
            "claims": {
                "trackedSourceOnly": True,
                "generatedSourceIncluded": False,
                "cacheSourceIncluded": False,
                "artifactSourceIncluded": False,
                "authorityGranted": False,
            },
            "files": files,
            "sourceInventorySha256": module.source_provenance.aggregate(files),
            "sourceContentInventorySha256": module.source_provenance.canonical_digest(
                module.source_provenance.CONTENT_INVENTORY_DOMAIN,
                module.source_provenance.content_inventory(files),
            ),
        }
        path = directory / module.PROVENANCE_FILE
        path.write_text(json.dumps(row), encoding="utf-8")
        (directory / "manifest.json").write_text(
            json.dumps({"runId": run_id, "runAttempt": attempt}),
            encoding="utf-8",
        )
        return {path.name: {}}

    def test_source_closure_accepts_all_required_owners(self) -> None:
        self.assertTrue(
            module.REQUIRED_EXACT_PATHS.issubset(module._source_paths(self.source()))
        )

    def test_source_closure_rejects_missing_target_runner(self) -> None:
        source = self.source()
        source["files"] = [
            row
            for row in source["files"]
            if row["path"]
            != "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh"
        ]
        with self.assertRaisesRegex(ValueError, "exact paths"):
            module._source_paths(source)

    def test_every_policy_command_has_an_independent_receipt_contract(self) -> None:
        self.assertEqual(
            set(module.policy.evidence.COMMANDS),
            {
                "compile",
                "focused-tests",
                "clippy",
                "format",
                "api-compile-fail",
            },
        )
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = self.source()
            (directory / "source.json").write_text(
                json.dumps(source, sort_keys=True), encoding="utf-8"
            )
            for label, arguments in module.policy.evidence.COMMANDS.items():
                with self.subTest(label=label):
                    inventory = self.write_receipt(
                        directory,
                        source,
                        label,
                        arguments,
                        with_junit=label == module.FOCUSED_LABEL,
                    )
                    self.assertEqual(
                        module._command_receipt(
                            directory,
                            source,
                            inventory,
                            label,
                            arguments,
                            require_junit=label == module.FOCUSED_LABEL,
                        )["exitCode"],
                        0,
                    )
                    for path in directory.iterdir():
                        if path.name != "source.json":
                            path.unlink()

    def test_api_receipt_binds_command_log_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = self.source()
            (directory / "source.json").write_text(
                json.dumps(source, sort_keys=True), encoding="utf-8"
            )
            inventory = self.write_receipt(
                directory,
                source,
                module.API_LABEL,
                module.policy.API_COMPILE_FAIL_COMMAND,
                with_junit=False,
            )
            self.assertEqual(
                module._command_receipt(
                    directory,
                    source,
                    inventory,
                    module.API_LABEL,
                    module.policy.API_COMPILE_FAIL_COMMAND,
                    require_junit=False,
                )["exitCode"],
                0,
            )

    def test_focused_receipt_binds_full_regression_gate_and_junit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = self.source()
            (directory / "source.json").write_text(
                json.dumps(source, sort_keys=True), encoding="utf-8"
            )
            inventory = self.write_receipt(
                directory,
                source,
                module.FOCUSED_LABEL,
                module.policy.FOCUSED_GATE_COMMAND,
                with_junit=True,
            )
            self.assertEqual(
                module._command_receipt(
                    directory,
                    source,
                    inventory,
                    module.FOCUSED_LABEL,
                    module.policy.FOCUSED_GATE_COMMAND,
                    require_junit=True,
                )["exitCode"],
                0,
            )

    def test_provenance_receipt_binds_lane_attempt_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = self.source()
            inventory = self.write_provenance(directory, source, "source-head")
            row = module._provenance_receipt(
                directory, source, inventory, "source-head"
            )
            self.assertEqual(row["execution"]["workflowRunId"], "42")
            manifest = json.loads((directory / "manifest.json").read_text())
            manifest["runAttempt"] = "2"
            (directory / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "workflow attempt"):
                module._provenance_receipt(
                    directory, source, inventory, "source-head"
                )

    def test_provenance_receipt_rejects_tampered_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = self.source()
            inventory = self.write_provenance(directory, source, "source-head")
            path = directory / module.PROVENANCE_FILE
            row = json.loads(path.read_text())
            row["files"][0]["sha256"] = "9" * 64
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "inventory digest"):
                module._provenance_receipt(
                    directory, source, inventory, "source-head"
                )


if __name__ == "__main__":
    unittest.main()
