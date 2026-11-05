"""Exercise the integration helper with the original real-Git test fixture."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "refresh_review/scripts"))
import test_hepta_implementation_maps as fixtures

maps = fixtures.maps

SPEC = importlib.util.spec_from_file_location("refresh_navigation", ROOT / "refresh-navigation.py")
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class NavigationRefreshTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceIdentityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.normalize_maps()
        self.ledger = "qualification/module-execution-dossiers/navigation-rebind.json"

    def refresh(self, *, apply=False, ledger=None, sha=None, tree=None):
        current = maps.current_source_base()
        return helper.refresh(
            maps,
            expected_sha=sha or current["commit"],
            expected_tree=tree or current["tree"],
            ledger=ledger or self.ledger,
            apply=apply,
        )

    def test_preserves_historical_provenance_and_is_noop_after_qualification(self):
        fixture = self.fixture
        row = fixture.rows["alpha"]
        row["sourceBaseSemantics"] = "historical_provenance_only"
        row["exactSourceCandidate"] = {**row["sourceBase"], "role": "module_source_identity"}
        row["productCompositionSourceCandidate"] = {
            **row["sourceBase"], "role": "product_composition_source_identity"
        }
        historical = copy.deepcopy(row)
        fixture.change_maps()
        fixture.write("src/alpha/lib.rs", "pub fn calculate() { let _x = 7; }\n")
        current = fixture.commit("change owner source after historical candidate")
        before = fixture.map_bytes()
        preview = self.refresh()
        self.assertEqual(preview["changedMaps"], 1)
        self.assertFalse(preview["written"])
        self.assertEqual(before, fixture.map_bytes())
        result = self.refresh(apply=True)
        self.assertTrue(result["written"])
        updated = maps.load("docs/modules/alpha/IMPLEMENTATION_MAP.json")
        self.assertEqual(updated["sourceBase"], historical["sourceBase"])
        self.assertEqual(updated["exactSourceCandidate"], historical["exactSourceCandidate"])
        self.assertEqual(updated["productCompositionSourceCandidate"],
                         historical["productCompositionSourceCandidate"])
        self.assertEqual(updated["claimBoundary"], historical["claimBoundary"])
        self.assertEqual(updated["observedAtHead"], current)
        self.assertEqual(updated["mappingSourceIdentityMode"], "exact_blob")
        self.assertEqual(before["beta"], fixture.map_bytes()["beta"])
        ledger = json.loads((fixture.root / self.ledger).read_text())
        self.assertFalse(ledger["executionEvidenceTransferred"])
        previous = ledger["records"][0]["previousMap"]
        recovered = subprocess.run(
            ["git", "cat-file", "blob", previous["blob"]], cwd=fixture.root,
            check=True, capture_output=True
        ).stdout
        self.assertEqual(recovered, before["alpha"])
        self.assertEqual(hashlib.sha256(recovered).hexdigest(), previous["sha256"])
        self.assertEqual(len(recovered), previous["bytes"])
        fixture.commit("record navigation without renewing execution evidence")
        self.assertEqual(fixture.verify()["provenanceAnchoredExactBlobMaps"], 1)
        next_ledger = "qualification/module-execution-dossiers/noop.json"
        self.assertEqual(self.refresh(apply=True, ledger=next_ledger)["changedMaps"], 0)
        self.assertFalse((fixture.root / next_ledger).exists())

    def test_stale_execution_claim_refuses_before_any_map_or_ledger_write(self):
        fixture = self.fixture
        fixture.rows["beta"]["claimBoundary"]["productExecutionComplete"] = True
        fixture.change_maps()
        fixture.write("src/alpha/lib.rs", "pub fn calculate() { let _x = 4; }\n")
        fixture.write("src/beta/lib.rs", "pub fn calculate() { let _x = 5; }\n")
        fixture.commit("both sources changed after executable claim")
        before = fixture.map_bytes()
        with self.assertRaises(maps.SourceDrift):
            self.refresh(apply=True)
        self.assertEqual(before, fixture.map_bytes())
        self.assertFalse((fixture.root / self.ledger).exists())

    def test_wrong_identity_and_dirty_checkout_refuse_without_writes(self):
        fixture = self.fixture
        before = fixture.map_bytes()
        with self.assertRaisesRegex(ValueError, "candidate identity mismatch"):
            self.refresh(apply=True, tree="f" * 40)
        fixture.write("src/alpha/lib.rs", "pub fn uncommitted() {}\n")
        with self.assertRaises(ValueError):
            self.refresh(apply=True)
        self.assertEqual(before, fixture.map_bytes())
        self.assertFalse((fixture.root / self.ledger).exists())

    def test_alias_only_verifier_is_refused_before_any_write(self):
        old_spec = importlib.util.spec_from_file_location(
            "old_alias_only_verifier",
            ROOT / "alias-patch-check/scripts/hepta-implementation-maps.py",
        )
        old = importlib.util.module_from_spec(old_spec)
        old_spec.loader.exec_module(old)
        old.ROOT = self.fixture.root
        current = old.current_source_base()
        before = self.fixture.map_bytes()
        with self.assertRaisesRegex(ValueError, "original source pin protection"):
            helper.refresh(
                old,
                expected_sha=current["commit"],
                expected_tree=current["tree"],
                ledger=self.ledger,
                apply=True,
            )
        self.assertEqual(before, self.fixture.map_bytes())
        self.assertFalse((self.fixture.root / self.ledger).exists())


if __name__ == "__main__":
    unittest.main()
