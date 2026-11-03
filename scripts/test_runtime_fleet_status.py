#!/usr/bin/env python3
"""Runs the real SQLite schema and command entrypoint; not a Rust qualification."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fleet_status", ROOT / "scripts/runtime_fleet_status.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FleetStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "supervisor.sqlite3"
        connection = sqlite3.connect(self.database)
        for name in ("durable_schema.sql", "durable_execution_schema.sql"):
            connection.executescript((ROOT / "codex-rs/hepta-fleet/src" / name).read_text())
        connection.execute("INSERT INTO fleet_schema VALUES(1, 2, ?, 1)", (MODULE.LINEAGE,))
        connection.execute("INSERT INTO fleet_clock VALUES(1, 100)")
        connection.execute("INSERT INTO fleet_hosts VALUES('host', 'rack', 1, 100, 10000, 100, 100, 0, 10, 10, 10, 'digest')")
        connection.execute("INSERT INTO fleet_resource_totals VALUES('host', 20, 20, 0, 2, 2, 2, 'digest', 100)")
        connection.commit()
        connection.close()

    def files(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file()}

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/runtime_fleet_status.py"), *args], capture_output=True, text=True)

    def test_status_does_not_change_any_source_file(self):
        before = self.files()
        result = self.run_cli("status", "--state-dir", str(self.root), "--now-ms", "200")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.files())
        value = json.loads(result.stdout)
        self.assertFalse(value["authorizes_execution"])
        self.assertIsNone(value["revocation_lag_ms"])

    def test_missing_database_is_not_created(self):
        self.database.unlink()
        self.assertEqual(self.run_cli("status", "--state-dir", str(self.root), "--now-ms", "200").returncode, 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_live_wal_is_rejected_without_changes(self):
        wal = Path(str(self.database) + "-wal")
        wal.write_bytes(b"committed-or-incomplete-wal")
        before = self.files()
        self.assertEqual(self.run_cli("status", "--database", str(self.database), "--now-ms", "200").returncode, 2)
        self.assertEqual(before, self.files())

    def test_unsupported_open_and_unknown_flags_fail(self):
        for arguments in (("open", "--allow-create"), ("status", "--state-dir", str(self.root), "--now-ms", "200", "--unknown"),
                          ("status", "--state-d", str(self.root), "--now-ms", "200")):
            with self.subTest(arguments=arguments):
                before = self.files()
                self.assertNotEqual(self.run_cli(*arguments).returncode, 0)
                self.assertEqual(before, self.files())

    def test_snapshot_dry_run_uses_all_axes(self):
        request = {"host_id": "host", "resources": dict.fromkeys(MODULE.AXES, 0)}
        request["resources"]["tool_processes"] = 9
        path = self.root / "request.json"
        path.write_text(json.dumps(request))
        before = self.files()
        result = self.run_cli("dry-run", "--state-dir", str(self.root), "--now-ms", "200", "--request", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["admissible_in_snapshot"])
        self.assertEqual(before, self.files())

    def test_missing_totals_are_not_reported_as_zero(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("DELETE FROM fleet_resource_totals")
        self.assertEqual(self.run_cli("status", "--state-dir", str(self.root), "--now-ms", "200").returncode, 2)

    def test_clock_rollback_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.status(self.database, 99)

    def test_bad_schema_rejected(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE fleet_schema SET schema_version = 99")
        with self.assertRaises(ValueError):
            MODULE.status(self.database, 200)

    def test_bool_is_not_a_counter(self):
        with self.assertRaises(ValueError):
            MODULE.nonnegative(True, "counter")

    def test_replayed_or_duplicate_boot_cannot_get_a_new_generation(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO fleet_seen_boots VALUES('host', 'boot-z', 1)")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO fleet_seen_boots VALUES('host', 'boot-z', 2)")

    def test_duplicate_json_key_is_rejected(self):
        path = self.root / "profile.json"
        path.write_text('{"host_id":"host","host_id":"other","resources":{}}')
        with self.assertRaises(ValueError):
            MODULE.read_request(path)

    def test_symlink_source_rejected(self):
        alias = self.root / "alias.sqlite3"
        alias.symlink_to(self.database)
        with self.assertRaises(ValueError):
            MODULE.snapshot(alias)


if __name__ == "__main__":
    unittest.main(verbosity=2)
