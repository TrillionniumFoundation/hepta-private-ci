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
spec = importlib.util.spec_from_file_location("channel_matrix_pair_acceptance_v2_test", SCRIPT)
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

    def test_source_closure_accepts_all_required_owners(self) -> None:
        self.assertTrue(module.REQUIRED_EXACT_PATHS.issubset(module._source_paths(self.source())))

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
            log = directory / "api-compile-fail.log"
            log.write_text("compile-fail passed\n", encoding="utf-8")
            command = {
                "schema": "hepta.channel-matrix-command.v1",
                "label": module.API_LABEL,
                "arguments": module.policy.API_COMPILE_FAIL_COMMAND,
                "workingDirectory": "codex-rs",
                "testedSha": source["testedSha"],
                "sourceSnapshotSha256": digest(directory / "source.json"),
                "exitCode": 0,
                "completed": True,
                "launchError": None,
                "sourceUnchanged": True,
                "log": {
                    "path": log.name,
                    "bytes": log.stat().st_size,
                    "sha256": digest(log),
                    "withinBudget": True,
                },
            }
            command_path = directory / "api-compile-fail.command.json"
            command_path.write_text(json.dumps(command), encoding="utf-8")
            inventory = {
                command_path.name: {},
                log.name: {},
            }
            self.assertEqual(
                module._api_receipt(directory, source, inventory)["exitCode"], 0
            )


if __name__ == "__main__":
    unittest.main()
