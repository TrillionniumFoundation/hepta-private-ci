"""Keep original executable pins bound across real-Git navigation migrations."""

import copy
import unittest

import test_hepta_implementation_maps as fixtures


maps = fixtures.maps


class ExecutionClaimPinTests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.SourceIdentityTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.normalize_maps()
        return fixture

    def changed_pin(self, kind, claim):
        fixture = self.fixture()
        row = fixture.rows["beta"]
        row["claimBoundary"][claim] = True
        source = row["operations"][0]["sourcePath"]
        witness = "host/caller.rs"
        witness_blob = fixture.git("rev-parse", f"HEAD:{witness}")
        if kind == "source_objects":
            row["sourceObjects"] = [{"path": witness, "object": witness_blob}]
            row["sourceObjects"] = maps.current_source_objects(row)
        elif kind == "exact_manifest":
            row["exactSourceEvidence"] = {
                "kind": "path_blob_manifest_v1",
                "entries": [
                    {
                        "path": source,
                        "blobSha": fixture.git("rev-parse", f"HEAD:{source}"),
                    },
                    {"path": witness, "blobSha": witness_blob},
                ],
            }
        else:
            row["mappingSourceIdentityMode"] = "exact_blob"
            row["observedAtHead"] = maps.current_source_base()
            row["observedSourcePaths"] = ["src/beta"]
            row["operations"][0]["sourceBlob"] = fixture.git(
                "rev-parse", f"HEAD:{source}"
            )
            if kind == "caller":
                row["productCallers"] = [
                    {
                        "sourcePath": witness,
                        "nativeSymbol": "caller",
                        "blobSha": witness_blob,
                    }
                ]
                row["sourceObjects"] = maps.current_source_objects(row)
        fixture.change_maps()
        fixture.verify()
        changed = source if kind == "operation" else witness
        code = (
            "pub fn calculate() { let _x = 9; }\n"
            if kind == "operation"
            else "fn caller() { let _x = 9; }\n"
        )
        fixture.write(changed, code)
        current = fixture.commit("change one original execution pin")
        if kind in {"operation", "caller"}:
            # A fresh observation cannot launder an explicitly old executed blob.
            row["observedAtHead"] = current
            if kind == "caller":
                row["sourceObjects"] = maps.current_source_objects(row)
            fixture.change_maps()
        return fixture

    def test_old_execution_pins_reject_before_any_rewrite(self):
        for kind in ("source_objects", "exact_manifest", "operation", "caller"):
            for claim in ("productExecutionProved", "productExecutionComplete"):
                with self.subTest(kind=kind, claim=claim):
                    fixture = self.changed_pin(kind, claim)
                    before = fixture.map_bytes()
                    fixture.reject()
                    with self.assertRaises(ValueError):
                        fixture.migrate()
                    self.assertEqual(before, fixture.map_bytes())
                    original = copy.deepcopy(fixture.rows["beta"])
                    supplied = copy.deepcopy(original)
                    with self.assertRaises(ValueError):
                        maps.migrate_map(
                            supplied,
                            fixture.modules[1],
                            {"beta": "test-lane"},
                            supplied["sourceBase"],
                        )
                    self.assertEqual(original, supplied)
                    fixture.doCleanups()

    def test_unchanged_true_claim_with_all_explicit_pins_is_preserved(self):
        fixture = self.fixture()
        row = fixture.rows["beta"]
        row["claimBoundary"]["productExecutionComplete"] = True
        row["mappingSourceIdentityMode"] = "exact_blob"
        row["observedAtHead"] = maps.current_source_base()
        row["observedSourcePaths"] = ["src/beta"]
        source = row["operations"][0]["sourcePath"]
        source_blob = fixture.git("rev-parse", f"HEAD:{source}")
        witness_blob = fixture.git("rev-parse", "HEAD:host/caller.rs")
        row["operations"][0]["sourceBlob"] = source_blob
        row["productCallers"] = [
            {
                "sourcePath": "host/caller.rs",
                "nativeSymbol": "caller",
                "blobSha": witness_blob,
            }
        ]
        row["exactSourceEvidence"] = {
            "kind": "path_blob_manifest_v1",
            "entries": [
                {"path": source, "blobSha": source_blob},
                {"path": "host/caller.rs", "blobSha": witness_blob},
            ],
        }
        # The complete object manifest includes a source-root tree and file blobs.
        row["sourceObjects"] = maps.current_source_objects(row)
        fixture.change_maps()
        fixture.verify()
        before = fixture.map_bytes()
        self.assertEqual(fixture.migrate()["migrated"], 0)
        self.assertEqual(before, fixture.map_bytes())

    def test_unqualified_navigation_can_refresh_without_removing_witnesses(self):
        for kind in ("source_objects", "exact_manifest", "operation", "caller"):
            with self.subTest(kind=kind):
                fixture = self.changed_pin(kind, "productExecutionComplete")
                row = fixture.rows["beta"]
                row["claimBoundary"]["productExecutionComplete"] = False
                fixture.change_maps()
                original_paths = set(maps.evidence_paths(row, ["src/beta"]))
                fixture.migrate()
                fixture.commit("new navigation only; no execution claimed")
                migrated = maps.load("docs/modules/beta/IMPLEMENTATION_MAP.json")
                self.assertEqual(
                    set(maps.evidence_paths(migrated, ["src/beta"])), original_paths
                )
                self.assertFalse(migrated["claimBoundary"]["productExecutionComplete"])
                fixture.verify()
                fixture.doCleanups()

    def test_manifest_only_refresh_preserves_original_record_and_writes_result(self):
        fixture = self.changed_pin("exact_manifest", "productExecutionComplete")
        row = fixture.rows["beta"]
        row["claimBoundary"]["productExecutionComplete"] = False
        row["sourceBase"] = maps.current_source_base()
        fixture.change_maps()
        original = copy.deepcopy(row)
        migrated = maps.migrate_map(
            row, fixture.modules[1], {"beta": "test-lane"}, row["sourceBase"]
        )
        self.assertEqual(original, row)
        self.assertNotEqual(migrated["exactSourceEvidence"], row["exactSourceEvidence"])
        self.assertEqual(fixture.migrate(["beta"])["migrated"], 1)
        fixture.commit("persist changed navigation manifest without changing claims")
        self.assertEqual(
            maps.load("docs/modules/beta/IMPLEMENTATION_MAP.json"), migrated
        )
        fixture.verify()


if __name__ == "__main__":
    unittest.main()
