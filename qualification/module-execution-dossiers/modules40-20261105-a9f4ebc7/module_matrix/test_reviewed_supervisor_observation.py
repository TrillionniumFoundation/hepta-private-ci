"""Exact historical-observation review plus real-Git archival behavior."""

import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_refresh_navigation as navigation


helper = navigation.helper
maps = navigation.maps
fixtures = navigation.fixtures
ROOT = Path(__file__).resolve().parent


class ReviewedSupervisorObservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceIdentityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.normalize_maps()
        self.ledger = "qualification/module-execution-dossiers/reviewed-observation.json"

    def refresh(self, *, approve=False, apply=False):
        current = maps.current_source_base()
        return helper.refresh(
            maps,
            expected_sha=current["commit"],
            expected_tree=current["tree"],
            ledger=self.ledger,
            apply=apply,
            archive_reviewed_supervisor_observation=approve,
        )

    def prepared_supervisor_fixture(self):
        fixture = self.fixture
        row = fixture.rows.pop("alpha")
        old_path = fixture.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json"
        old_path.unlink()
        row["module"] = "runtime.supervisor"
        row["observedAtHead"] = {
            **row["sourceBase"],
            "interpretation": "Historical source observation; product execution remains unproved.",
        }
        fixture.rows["runtime.supervisor"] = row
        fixture.modules[0]["id"] = "runtime.supervisor"
        fixture.write("docs/modules/MODULES.json", {"modules": fixture.modules})
        fixture.write(
            "docs/readiness/READINESS.json",
            {"implementationLanes": [{"id": "test-lane", "modules": ["runtime.supervisor", "beta"]}]},
        )
        fixture.change_maps()
        fixture.verify()
        path = fixture.root / "docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json"
        before = path.read_bytes()
        binding = {
            "module": "runtime.supervisor",
            "mapBlob": fixture.git("rev-parse", "HEAD:docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json"),
            "mapSha256": hashlib.sha256(before).hexdigest(),
            "observationSha256": hashlib.sha256(
                json.dumps(row["observedAtHead"], ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()
            ).hexdigest(),
        }
        fixture.write("src/alpha/lib.rs", "pub fn calculate() { let _changed = 1; }\n")
        fixture.commit("change navigated source after historical observation")
        return row, before, binding

    def assert_no_write(self, before):
        self.assertEqual(before, self.fixture.map_bytes())
        self.assertFalse((self.fixture.root / self.ledger).exists())

    def test_exact_real_review_record_is_accepted_and_every_binding_is_required(self):
        path = ROOT / "source/docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json"
        before = path.read_bytes()
        row = json.loads(before)
        blob = hashlib.sha1(b"blob " + str(len(before)).encode() + b"\0" + before).hexdigest()
        record = helper.reviewed_supervisor_observation(row, before, blob)
        self.assertEqual(record["previousObservedAtHead"], row["observedAtHead"])
        self.assertFalse(record["historicalInterpretationTransferred"])
        for changed_row, changed_bytes, changed_blob in (
            ({**row, "module": "other.module"}, before, blob),
            (row, before + b"\n", blob),
            (row, before, "0" * 40),
            ({**row, "productionImplementation": True}, before, blob),
            ({**row, "observedAtHead": {**row["observedAtHead"], "interpretation": "different"}}, before, blob),
            ({**row, "observedAtHead": {**row["observedAtHead"], "extra": "not reviewed"}}, before, blob),
        ):
            with self.subTest(changed_module=changed_row["module"], changed_blob=changed_blob):
                with self.assertRaises(ValueError):
                    helper.reviewed_supervisor_observation(changed_row, changed_bytes, changed_blob)

    def test_default_refusal_and_opt_in_archival_preserve_original_semantics(self):
        row, before_bytes, binding = self.prepared_supervisor_fixture()
        before = self.fixture.map_bytes()
        with patch.object(helper, "REVIEWED_SUPERVISOR_OBSERVATION", binding):
            with self.assertRaisesRegex(ValueError, "explicit review"):
                self.refresh(apply=True)
            self.assert_no_write(before)
            preview = self.refresh(approve=True)
            self.assertEqual(preview["changedMaps"], 1)
            self.assert_no_write(before)
            current = maps.current_source_base()
            self.assertTrue(self.refresh(approve=True, apply=True)["written"])
        migrated = maps.load("docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json")
        self.assertEqual(migrated["observedAtHead"], current)
        self.assertEqual(set(migrated["observedAtHead"]), {"commit", "tree"})
        self.assertEqual(migrated["sourceBase"], row["sourceBase"])
        self.assertEqual(migrated["claimBoundary"], row["claimBoundary"])
        self.assertEqual(helper.semantic_view(migrated), helper.semantic_view(row))
        ledger = json.loads((self.fixture.root / self.ledger).read_text())
        record = next(r for r in ledger["records"] if r["module"] == "runtime.supervisor")
        self.assertEqual(record["previousObservedAtHead"], row["observedAtHead"])
        self.assertEqual(record["reviewedObservationArchival"]["previousObservedAtHead"], row["observedAtHead"])
        self.assertTrue(record["reviewedObservationArchival"]["reviewReason"])
        self.assertEqual(record["previousMap"]["sha256"], hashlib.sha256(before_bytes).hexdigest())
        self.assertEqual(self.fixture.git("cat-file", "blob", record["previousMap"]["blob"]), before_bytes.decode().strip())
        self.assertFalse(ledger["executionEvidenceTransferred"])
        self.fixture.commit("persist current navigation and full old observation archive")
        self.fixture.verify()

    def test_opt_in_does_not_allow_another_module_or_unreviewed_map(self):
        row, _, binding = self.prepared_supervisor_fixture()
        before = self.fixture.map_bytes()
        with patch.object(helper, "REVIEWED_SUPERVISOR_OBSERVATION", {**binding, "mapSha256": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "identity changed"):
                self.refresh(approve=True, apply=True)
        self.assert_no_write(before)
        other = self.fixture.rows["beta"]
        other["observedAtHead"] = {**other["sourceBase"], "interpretation": "unreviewed"}
        self.fixture.change_maps()
        self.fixture.write("src/beta/lib.rs", "pub fn calculate() { let _changed = 2; }\n")
        self.fixture.commit("drift another unreviewed source observation")
        before = self.fixture.map_bytes()
        with patch.object(helper, "REVIEWED_SUPERVISOR_OBSERVATION", binding):
            with self.assertRaisesRegex(ValueError, "not the reviewed supervisor"):
                self.refresh(approve=True, apply=True)
        self.assert_no_write(before)

    def test_opt_in_never_bypasses_stale_true_execution_pins(self):
        row, _, binding = self.prepared_supervisor_fixture()
        row["claimBoundary"]["productExecutionComplete"] = True
        self.fixture.change_maps()
        before = self.fixture.map_bytes()
        with patch.object(helper, "REVIEWED_SUPERVISOR_OBSERVATION", binding):
            with self.assertRaises(maps.SourceDrift):
                self.refresh(approve=True, apply=True)
        self.assert_no_write(before)


if __name__ == "__main__":
    unittest.main()
