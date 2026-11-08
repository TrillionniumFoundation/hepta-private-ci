"""Actual temporary-directory scans; no training or fabricated completeness flag."""

from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import inventory as module
from .comparison import ARMS, Attempt, Design, compare
from .inventory import START_FIELDS, START_SCHEMA, TERMINAL_SCHEMA, scan_inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.design = Design("fixture", "h4-d1", (0, 1), "1"*64, "2"*64,
                             "3"*64, "4"*64, "5"*64, 10, 4, 20, 8, 4, .01)
        quality = dict(A=.1, B=.2, C=.4, D=.8)
        self.rows = [Attempt(a, s, f"{a}-{s}", self.design.identity(), str(s+5)*64,
                            "completed", 10, 4, 20, 160, 4, 100.,
                            50. if a == "D" else 100., quality[a], .01 if a == "D" else .02)
                     for a in ARMS for s in self.design.seeds]
        for row in self.rows:
            self.write(row)

    def write(self, row):
        payload = asdict(row)
        start = {"schema": START_SCHEMA, **{k: payload[k] for k in START_FIELDS}}
        raw = json.dumps(start).encode()
        (self.path / (row.attempt_id + ".start.json")).write_bytes(raw)
        terminal = {"schema": TERMINAL_SCHEMA, "start_sha256": hashlib.sha256(raw).hexdigest(),
                    "attempt": payload}
        (self.path / (row.attempt_id + ".terminal.json")).write_text(json.dumps(terminal))

    def test_closed_inventory_and_paired_gate(self):
        attempts, inventory = scan_inventory(self.path, self.design)
        self.assertEqual(attempts, tuple(self.rows))
        inventory.verify(self.design, reversed(attempts))
        evidence = inventory.as_dict()
        self.assertEqual(json.loads(json.dumps(evidence)), evidence)
        expected_hash = hashlib.sha256(json.dumps(asdict(self.rows[0]), sort_keys=True,
                                                  separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(evidence["attempts"][0]["canonical_sha256"], expected_hash)
        self.assertEqual({r["attempt_id"] for r in evidence["starts"]},
                         {r["attempt_id"] for r in evidence["terminals"]})
        self.assertEqual(len(evidence["attempts"]), 8)
        self.assertTrue(compare(self.design, attempts, inventory=inventory)["quality_latency_energy_gain"])
        self.assertFalse(compare(self.design, attempts)["quality_latency_energy_gain"])

    def test_omitted_oom_changed_cost_and_duplicate_are_rejected(self):
        failed = replace(self.rows[0], attempt_id="oom", status="oom", optimizer_updates=1,
                         submitted_examples=8, tuning_updates=0, total_wall_seconds=7.,
                         energy_joules=14., higher_is_better_quality=None, inference_p95_seconds=None)
        self.write(failed)
        attempts, inventory = scan_inventory(self.path, self.design)
        for rows in (self.rows, attempts + (attempts[0],),
                     tuple(replace(r, total_wall_seconds=1.) if r.attempt_id == "A-0" else r
                           for r in attempts)):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                compare(self.design, rows, inventory=inventory)
        report = compare(self.design, attempts, inventory=inventory)
        self.assertEqual(report["outcomes"]["oom"], 1)
        self.assertEqual(report["costs_by_identity"][0]["total_wall_seconds"], 107.)
        self.assertEqual(report["status"], "HOLD")

    def test_unpaired_starts_or_terminals_cannot_close(self):
        for suffix in ("start", "terminal"):
            with self.subTest(suffix=suffix):
                (self.path / f"A-0.{suffix}.json").unlink()
                with self.assertRaises(ValueError):
                    scan_inventory(self.path, self.design)
                self.write(self.rows[0])

    def test_unknown_outcome_and_missing_nullable_field_reject(self):
        path = self.path / "A-0.terminal.json"
        for change in ("unknown", "missing", "extra", "wrong_start_hash"):
            data = json.loads(path.read_text())
            if change == "unknown":
                data["attempt"].update(status="unknown", higher_is_better_quality=None,
                                       inference_p95_seconds=None)
            elif change == "missing":
                del data["attempt"]["higher_is_better_quality"]
            elif change == "extra":
                data["attempt"]["ignored_failure"] = True
            else:
                data["start_sha256"] = "0"*64
            path.write_text(json.dumps(data))
            with self.subTest(change=change), self.assertRaises(ValueError):
                scan_inventory(self.path, self.design)
            self.write(self.rows[0])

    def test_extra_entry_duplicate_json_and_alias_identity_reject(self):
        extra = self.path / "notes.txt"
        extra.write_text("not part of the ledger")
        with self.assertRaises(ValueError):
            scan_inventory(self.path, self.design)
        extra.unlink()
        start = self.path / "A-0.start.json"
        original = start.read_bytes()
        start.write_bytes(b'{"schema":"duplicate",' + original[1:])
        with self.assertRaises(ValueError):
            scan_inventory(self.path, self.design)
        start.write_bytes(original)
        (self.path / "alias.start.json").write_bytes(original)
        (self.path / "alias.terminal.json").write_bytes((self.path / "A-0.terminal.json").read_bytes())
        with self.assertRaises(ValueError):
            scan_inventory(self.path, self.design)

    def test_symlink_hardlink_and_nested_directory_reject(self):
        extra = self.path / "linked.start.json"
        for kind in ("symlink", "hardlink", "directory"):
            with self.subTest(kind=kind):
                try:
                    if kind == "symlink":
                        extra.symlink_to(self.path / "A-0.start.json")
                    elif kind == "hardlink":
                        os.link(self.path / "A-0.start.json", extra)
                    else:
                        extra.mkdir()
                except (OSError, NotImplementedError):
                    continue  # Platforms without link privileges still exercise directory rejection.
                with self.assertRaises(ValueError):
                    scan_inventory(self.path, self.design)
                extra.rmdir() if kind == "directory" else extra.unlink()

    def test_later_ledger_edit_or_pair_deletion_invalidates_inventory(self):
        attempts, inventory = scan_inventory(self.path, self.design)
        self.write(replace(self.rows[0], total_wall_seconds=1.))
        with self.assertRaises(ValueError):
            inventory.verify(self.design, attempts)
        self.write(self.rows[0])
        attempts, inventory = scan_inventory(self.path, self.design)
        for suffix in ("start", "terminal"):
            (self.path / f"A-0.{suffix}.json").unlink()
        with self.assertRaises(ValueError):
            inventory.verify(self.design, self.rows[1:])

    def test_change_between_full_reads_rejects_snapshot(self):
        original = module._snapshot
        calls = []
        def racing_read(path):
            result = original(path)
            calls.append(1)
            if len(calls) == 1:
                self.write(replace(self.rows[0], energy_joules=1.))
            return result
        with patch.object(module, "_snapshot", side_effect=racing_read), self.assertRaises(ValueError):
            scan_inventory(self.path, self.design)


if __name__ == "__main__":
    unittest.main()
