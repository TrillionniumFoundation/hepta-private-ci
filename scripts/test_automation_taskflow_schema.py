from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "automation_schema_check", ROOT / "scripts/check_automation_taskflow_schema.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AutomationSchemaDriftTests(unittest.TestCase):
    def test_repository_is_schema_v19_consistent(self) -> None:
        receipt = MODULE.verify(ROOT)
        self.assertEqual(receipt["version"], 19)
        self.assertFalse(receipt["release"])

    def test_map_version_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            selected = [
                "codex-rs/hepta-automation/src/lib.rs",
                "codex-rs/hepta-automation/migrations",
                "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json",
                "docs/modules/automation.taskflow/TECHNICAL.md",
                "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
                "qualification/module-execution-dossiers/detail/automation.taskflow.md",
                "docs/readiness/LANE_B_NATIVE_HOST.md",
                "CALLERS.toml",
            ]
            for relative in selected:
                source = ROOT / relative
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)
            path = target / "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["storeSchemaVersion"] = 18
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.SchemaDrift, "schema drift"):
                MODULE.verify(target)


if __name__ == "__main__":
    unittest.main()
