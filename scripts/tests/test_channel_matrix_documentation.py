from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/modules/channel.matrix"
MIGRATIONS = ROOT / "codex-rs/hepta-matrix-store/migrations"
WORKFLOW = ROOT / ".github/workflows/channel-matrix-materialize.yml"


class ChannelMatrixDocumentationTests(unittest.TestCase):
    def read_doc(self, name: str) -> str:
        return (DOCS / name).read_text(encoding="utf-8")

    def test_migration_inventory_is_exactly_contiguous_through_13(self) -> None:
        rows = []
        for path in MIGRATIONS.glob("*.sql"):
            match = re.fullmatch(r"(\d{4})_.+\.sql", path.name)
            self.assertIsNotNone(match, path.name)
            rows.append((int(match.group(1)), path.name))
        rows.sort()
        self.assertEqual([version for version, _ in rows], list(range(1, 14)))
        inventory = self.read_doc("MIGRATIONS.md")
        for _, name in rows:
            self.assertIn(f"`{name}`", inventory)

    def test_startup_and_rollback_contracts_require_migration_13(self) -> None:
        optimization = self.read_doc("OPTIMIZATION_CONTRACT.md")
        runbook = self.read_doc("OPERATIONS_RUNBOOK.md")
        schema = self.read_doc("STORAGE_SCHEMA.md")
        recovery = self.read_doc("FAILURE_AND_RECOVERY.md")
        technical = self.read_doc("TECHNICAL.md")

        self.assertIn("Migration compatibility is **13**", optimization)
        self.assertIn("store/migrations 1-13", runbook)
        self.assertIn("compatible with migrations 1-13", runbook)
        self.assertIn("`0013_matrix_inbox_recovery.sql`", schema)
        self.assertIn("migrations 6-13", schema)
        self.assertIn("verifies migrations 1-13", recovery)
        self.assertIn("Migrations 6-13", recovery)
        self.assertIn("compatibility floor for startup/rollback is migration **13**", technical)

        stale = (
            "Migration compatibility is **12**",
            "store/migrations 1-12 and their exact schema/invariants verified",
            "compatible with migrations 1-12",
            "verifies migrations 1-12",
            "Migrations 6-12 dispatch",
            "compatibility floor for startup/rollback is migration **12**",
        )
        combined = "\n".join((optimization, runbook, schema, recovery, technical))
        for marker in stale:
            self.assertNotIn(marker, combined)

    def test_diagnostics_commands_cover_transaction_event_and_alert_exit(self) -> None:
        runbook = self.read_doc("OPERATIONS_RUNBOOK.md")
        self.assertIn("--transaction EXACT_TXN_ID", runbook)
        self.assertIn("--event EXACT_EVENT_ID", runbook)
        self.assertIn("--format prometheus --check", runbook)

    def test_historical_materializer_is_now_read_only_validation(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("GH_TOKEN", workflow)
        self.assertNotIn("git push", workflow)
        self.assertNotIn("git commit", workflow)
        self.assertIn("test_channel_matrix_documentation", workflow)

    def test_all_matrix_qualification_workflows_are_read_only(self) -> None:
        workflows = sorted((ROOT / ".github/workflows").glob("channel-matrix-*.yml"))
        self.assertTrue(workflows)
        for workflow in workflows:
            source = workflow.read_text(encoding="utf-8")
            self.assertNotIn("contents: write", source, workflow.name)
            self.assertNotIn("git push", source, workflow.name)
        self.assertFalse((ROOT / ".github/channel-matrix-repair.py").exists())
        self.assertFalse((ROOT / ".matrix-staging").exists())


if __name__ == "__main__":
    unittest.main()
