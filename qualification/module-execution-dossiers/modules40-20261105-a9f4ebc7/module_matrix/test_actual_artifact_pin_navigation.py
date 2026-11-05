"""Reproduce the actual learning.artifacts legacy-pin mismatch in real Git."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

import test_refresh_navigation as navigation


ROOT = Path(__file__).resolve().parent
maps = navigation.maps
helper = navigation.helper
fixtures = navigation.fixtures
ACTUAL_PATH = "codex-rs/hepta-learning-artifacts/src/pinned.rs"
ACTUAL_BLOB = "3a097702ef7294467e2a16b5ae8624b716372c41"
OLD_OPERATION_BLOB = "3ff1450b5111706d737643351fb5692ee657726c"


class ActualArtifactPinNavigationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceIdentityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.normalize_maps()
        fixture = self.fixture
        original = json.loads(
            (ROOT / "source/docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json").read_text()
        )
        self.actual_operations = [
            copy.deepcopy(operation) for operation in original["operations"]
            if operation.get("sourcePath") == ACTUAL_PATH
        ]
        self.assertEqual(len(self.actual_operations), 2)
        self.assertTrue(all(op["sourceBlob"] == OLD_OPERATION_BLOB for op in self.actual_operations))
        raw = (ROOT / "actual-c58-pinned.rs").read_bytes()
        calculated = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        self.assertEqual(calculated, ACTUAL_BLOB)
        target = fixture.root / ACTUAL_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(raw)
        fixture.write("codex-rs/Cargo.toml", "[workspace]\n")
        fixture.write("codex-rs/Cargo.lock", "# isolated source-identity fixture\n")
        current_source = fixture.commit("actual C58 pinned source bytes")
        row = fixture.rows.pop("alpha")
        (fixture.root / "docs/modules/alpha/IMPLEMENTATION_MAP.json").unlink()
        row.update(
            module="learning.artifacts",
            sourceBase=current_source,
            declaredRoots=["codex-rs/hepta-learning-artifacts"],
            resolvedRoots=["codex-rs/hepta-learning-artifacts"],
            sourceRoot=["codex-rs/hepta-learning-artifacts"],
            operations=copy.deepcopy(self.actual_operations),
        )
        row["sourceObjects"] = maps.current_source_objects(row)
        fixture.rows["learning.artifacts"] = row
        fixture.modules[0]["id"] = "learning.artifacts"
        fixture.modules[0]["rootBindings"] = [{"path": "codex-rs/hepta-learning-artifacts"}]
        fixture.write("docs/modules/MODULES.json", {"modules": fixture.modules})
        fixture.write(
            "docs/readiness/READINESS.json",
            {"implementationLanes": [{"id": "test-lane", "modules": ["learning.artifacts", "beta"]}]},
        )
        fixture.change_maps()
        self.row = row
        self.ledger = "qualification/module-execution-dossiers/artifact-pin-rebind.json"
        self.assertNotIn("mappingSourceIdentityMode", row)
        self.assertNotIn("observedAtHead", row)
        self.assertEqual(
            next(x["object"] for x in row["sourceObjects"] if x["path"] == ACTUAL_PATH),
            ACTUAL_BLOB,
        )
        # This is the actual failure shape: sourceBase and sourceObjects are
        # current, so the original path observation succeeds; only the two old
        # explicit operation pins disagree. The history here is an isolated
        # fixture, not a re-creation or qualification of the actual C58 commit.
        maps.verify_source_identity(
            row, ["codex-rs/hepta-learning-artifacts"], maps.current_source_base(),
            check_checkout=False,
        )

    def refresh(self, verifier_helper=helper, *, apply=False):
        current = maps.current_source_base()
        return verifier_helper.refresh(
            maps, expected_sha=current["commit"], expected_tree=current["tree"],
            ledger=self.ledger, apply=apply,
        )

    def assert_no_write(self, before):
        self.assertEqual(self.fixture.map_bytes(), before)
        self.assertFalse((self.fixture.root / self.ledger).exists())

    def test_actual_old_helper_red_then_navigation_only_refresh_and_strict_green(self):
        old_path = ROOT / "refresh-navigation.pre-explicit-pin-fallback.py"
        self.assertEqual(hashlib.sha256(old_path.read_bytes()).hexdigest(),
                         "790d124c85dc299f6254fcd0427461881023bf60fcc4943713867eacd3dba438")
        spec = importlib.util.spec_from_file_location("old_pin_fallback_helper", old_path)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        before = self.fixture.map_bytes()
        with self.assertRaisesRegex(maps.SourceDrift, "source blob drift"):
            self.refresh(old, apply=True)
        self.assert_no_write(before)
        current = maps.current_source_base()
        preview = self.refresh()
        self.assertEqual(preview["changedMaps"], 1)
        self.assert_no_write(before)
        self.assertTrue(self.refresh(apply=True)["written"])
        migrated = maps.load("docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json")
        self.assertEqual(migrated["sourceBase"], self.row["sourceBase"])
        self.assertEqual(migrated["observedAtHead"], current)
        self.assertEqual(migrated["mappingSourceIdentityMode"], "exact_blob")
        self.assertTrue(all(op["sourceBlob"] == ACTUAL_BLOB for op in migrated["operations"]))
        self.assertEqual(helper.semantic_view(migrated), helper.semantic_view(self.row))
        ledger = json.loads((self.fixture.root / self.ledger).read_text())
        entry = next(r for r in ledger["records"] if r["module"] == "learning.artifacts")
        recovered = self.fixture.git("cat-file", "blob", entry["previousMap"]["blob"])
        original = json.loads(recovered)
        self.assertTrue(all(op["sourceBlob"] == OLD_OPERATION_BLOB for op in original["operations"]))
        self.assertFalse(ledger["executionEvidenceTransferred"])
        self.fixture.commit("new exact navigation; old pins retained in original map blob")
        self.fixture.verify()

    def test_true_original_and_alias_claims_still_refuse_before_rewrite(self):
        for claim in ("productExecutionProved", "productExecutionComplete"):
            with self.subTest(claim=claim):
                self.row["claimBoundary"][claim] = True
                self.fixture.change_maps()
                before = self.fixture.map_bytes()
                with self.assertRaisesRegex(maps.SourceDrift, "source blob drift"):
                    self.refresh(apply=True)
                self.assert_no_write(before)
                self.row["claimBoundary"][claim] = False
                self.fixture.change_maps()

    def test_invalid_pin_format_is_not_caught_as_source_drift(self):
        self.row["operations"][0]["sourceBlob"] = "not-a-source-object"
        self.fixture.change_maps()
        before = self.fixture.map_bytes()
        with self.assertRaisesRegex(ValueError, "invalid exact source blob") as error:
            self.refresh(apply=True)
        self.assertNotIsInstance(error.exception, maps.SourceDrift)
        self.assert_no_write(before)


if __name__ == "__main__":
    unittest.main()
