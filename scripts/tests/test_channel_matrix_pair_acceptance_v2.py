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


class ExtendedPairAcceptanceTests(unittest.TestCase):
    def source(self) -> dict:
        paths = sorted(
            module.REQUIRED_EXACT_PATHS
            | {f"{prefix}fixture" for prefix in module.REQUIRED_PREFIXES}
        )
        return {
            "testedSha": "1" * 40,
            "files": [{"path": path} for path in paths],
        }

    def write_receipt(
        self,
        directory: Path,
        source: dict,
        label: str,
        arguments: list[str],
        *,
        with_junit: bool,
    ) -> tuple[Path, Path, dict[str, dict]]:
        log = directory / f"{label}.log"
        log.write_text(f"{label} passed\n", encoding="utf-8")
        inventory: dict[str, dict] = {log.name: {}}
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
        return command_path, log, inventory

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

    def test_api_receipt_binds_command_log_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = self.source()
            (directory / "source.json").write_text(
                json.dumps(source, sort_keys=True), encoding="utf-8"
            )
            _, _, inventory = self.write_receipt(
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
            _, _, inventory = self.write_receipt(
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

    def test_focused_receipt_rejects_wrong_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = self.source()
            (directory / "source.json").write_text(
                json.dumps(source, sort_keys=True), encoding="utf-8"
            )
            _, _, inventory = self.write_receipt(
                directory,
                source,
                module.FOCUSED_LABEL,
                ["python3", "-c", "print('not the suite')"],
                with_junit=True,
            )
            with self.assertRaisesRegex(ValueError, "mismatched"):
                module._command_receipt(
                    directory,
                    source,
                    inventory,
                    module.FOCUSED_LABEL,
                    module.policy.FOCUSED_GATE_COMMAND,
                    require_junit=True,
                )


if __name__ == "__main__":
    unittest.main()
