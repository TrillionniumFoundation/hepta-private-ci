"""Scoped CLI verification retains source provenance and checkout safety."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import test_hepta_implementation_maps as fixtures


class ScopedVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceIdentityTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.subject = fixtures.maps

    def cli(self, *args):
        output = io.StringIO()
        with (
            patch("sys.argv", ["hepta-implementation-maps.py", "verify", *args]),
            contextlib.redirect_stdout(output),
        ):
            self.subject.main()
        return json.loads(output.getvalue())

    def test_selected_inventory_does_not_claim_unrelated_map_health(self):
        other = self.fixture.git(
            "commit-tree", self.fixture.anchor["tree"], "-m", "unrelated provenance"
        )
        self.fixture.rows["beta"]["sourceBase"]["commit"] = other
        self.fixture.change_maps()

        result = self.cli("--module", "alpha", "--module", "alpha")
        self.assertEqual(
            (result["modules"], result["maps"], result["registeredModules"], result["selectedModules"]),
            (1, 1, 2, ["alpha"]),
        )
        with self.assertRaisesRegex(SystemExit, "beta"):
            self.cli()
        with self.assertRaisesRegex(SystemExit, "beta"):
            self.cli("--module", "beta")

    def test_unknown_and_empty_cli_selection_fail(self):
        for selected in ("unknown", "", " "):
            with self.subTest(selected=selected), self.assertRaisesRegex(
                SystemExit, "unknown modules|empty or invalid module selection"
            ):
                self.cli("--module", selected)
        with self.assertRaisesRegex(SystemExit, "empty or invalid module selection"):
            self.subject.verify(selected_modules=[])

    def test_selected_evidence_drift_fails_even_when_committed(self):
        self.fixture.write("src/alpha/lib.rs", "pub fn changed_source() {}\n")
        self.fixture.commit("source drift")
        with self.assertRaisesRegex(SystemExit, "mapped source/evidence changed"):
            self.cli("--module", "alpha")

    def test_selected_untracked_evidence_and_global_dirty_source_fail(self):
        self.fixture.write("src/alpha/untracked.rs", "// uncommitted evidence\n")
        with self.assertRaisesRegex(SystemExit, "uncommitted evidence"):
            self.cli("--module", "alpha")
        (self.fixture.root / "src/alpha/untracked.rs").unlink()

        self.fixture.write("src/beta/lib.rs", "// unrelated dirty source\n")
        with self.assertRaisesRegex(SystemExit, "candidate checkout changed or is dirty"):
            self.cli("--module", "alpha")

    def test_global_hidden_index_scan_survives_selection(self):
        self.fixture.git("update-index", "--assume-unchanged", "src/beta/lib.rs")
        with self.assertRaisesRegex(SystemExit, "candidate index hides tracked paths"):
            self.cli("--module", "alpha")


if __name__ == "__main__":
    unittest.main()
