"""Reject partial owner scope and a missing actual routing regression."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import windows_fixture_followup as subject


class QuietOwnerScopeTests(unittest.TestCase):
    def setUp(self):
        self.scope = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "fixtures/windows-appserver-quiet-scope.json"
            ).read_text()
        )

    def test_partial_or_foreign_owner_cannot_be_admitted(self):
        self.assertEqual(
            subject.select_appserver_owner_groups(self.scope, None),
            self.scope["groups"],
        )
        for identifier in ("appserver-fixtures", "appserver-status-routing", "missing"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                subject.select_appserver_owner_groups(self.scope, identifier)
        changed = copy.deepcopy(self.scope)
        changed["groups"][1]["package"] = "codex-another-owner"
        with self.assertRaises(ValueError):
            subject.select_appserver_owner_groups(changed, None)

    def test_missing_routing_regression_is_rejected_by_actual_selection(self):
        group = next(
            row
            for row in self.scope["groups"]
            if row["id"] == "appserver-status-routing"
        )
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root, target = base / "source", base / "target"
            binary = target / "dev-small/deps/example.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ receipt-check fixture, never executed")
            suite = {
                "binary-id": group["binaryId"],
                "package-name": group["package"],
                "cwd": str(root / "codex-rs" / group["crate"]),
                "binary-path": str(binary),
                "testcases": {
                    name: {"ignored": False, "filter-match": {"status": "matches"}}
                    for name in group["required"]
                },
            }
            document = {"rust-suites": {group["binaryId"]: suite}}
            self.assertEqual(
                subject.selected_cases(document, group, root, target)["selectedCount"],
                2,
            )
            del suite["testcases"][group["required"][-1]]
            with self.assertRaises(ValueError):
                subject.selected_cases(document, group, root, target)


if __name__ == "__main__":
    unittest.main()
