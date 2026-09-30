from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hepta_learning_artifacts_drill",
    ROOT / "scripts" / "hepta-learning-artifacts-drill.py",
)
assert SPEC is not None and SPEC.loader is not None
DRILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRILL)


class DrillReceiptTests(unittest.TestCase):
    def claims(self, kind: str) -> dict[str, object]:
        assertions: dict[str, object]
        if kind == "target_filesystem":
            assertions = {
                "faultsPassed": sorted(DRILL.REQUIRED_TARGET_FAULTS),
                "unknownNeverBecameNotStarted": True,
                "fileSyncVerified": True,
                "directorySyncVerified": True,
                "atomicReplaceVerified": True,
                "encryptedAtRest": True,
                "singleHostWriter": True,
                "filesystemType": "fixturefs",
                "mountOptionsHash": "d" * 64,
                "keySource": "fixture-kms",
                "keyIdentifier": "fixture-key",
                "keyRotationEpoch": 7,
                "capabilityAttestation": "e" * 64,
            }
        elif kind == "product_execution":
            assertions = {
                "lifecycleStepsPassed": sorted(DRILL.REQUIRED_PRODUCT_STEPS),
                "productionComposition": True,
                "fixtureFallbackAbsent": True,
                "syntheticCredentialAbsent": True,
                "testBypassAbsent": True,
                "coldStartFromIndependentAnchor": True,
            }
        elif kind == "backup_restore":
            assertions = {
                "restoredDigestMatches": True,
                "oldGenerationRejected": True,
                "independentAnchorMatched": True,
            }
        elif kind == "release":
            assertions = {
                "readinessManifestVerified": True,
                "exactHeadQualified": True,
                "syntheticMergeQualified": True,
                "targetFilesystemQualified": True,
                "productExecutionVerified": True,
                "operatorAcceptanceVerified": True,
                "promotionReceiptVerified": True,
            }
        else:
            raise AssertionError(kind)
        return {
            "module": "learning.artifacts",
            "kind": kind,
            "sourceSha": "a" * 40,
            "sourceTree": "b" * 40,
            "readinessManifestSha256": "f" * 64,
            "qualificationRunId": "12345",
            "qualificationRunAttempt": 1,
            "targetFingerprint": "fixture-host",
            "startedAt": 10,
            "completedAt": 20,
            "outcome": "pass",
            "assertions": assertions,
            "evidence": [
                {
                    "name": "log",
                    "sha256": "c" * 64,
                    "mediaType": "text/plain",
                    "locator": "artifact://fixture/log",
                }
            ],
        }

    def test_target_filesystem_requires_every_physical_fault(self) -> None:
        claims = self.claims("target_filesystem")
        DRILL.validate_claims(claims)
        claims["assertions"]["faultsPassed"].remove("physical_power_loss")
        with self.assertRaises(DRILL.ReceiptError):
            DRILL.validate_claims(claims)

    def test_target_filesystem_requires_machine_storage_capability(self) -> None:
        for field, value in (
            ("encryptedAtRest", False),
            ("directorySyncVerified", False),
            ("mountOptionsHash", "not-a-digest"),
            ("keyRotationEpoch", 0),
        ):
            with self.subTest(field=field):
                claims = self.claims("target_filesystem")
                claims["assertions"][field] = value
                with self.assertRaises(DRILL.ReceiptError):
                    DRILL.validate_claims(claims)

    def test_product_execution_requires_full_real_lifecycle(self) -> None:
        claims = self.claims("product_execution")
        DRILL.validate_claims(claims)
        claims["assertions"]["lifecycleStepsPassed"].remove("cold_start_restore")
        with self.assertRaises(DRILL.ReceiptError):
            DRILL.validate_claims(claims)
        claims = self.claims("product_execution")
        claims["assertions"]["fixtureFallbackAbsent"] = False
        with self.assertRaises(DRILL.ReceiptError):
            DRILL.validate_claims(claims)

    def test_release_requires_readiness_and_product_execution(self) -> None:
        claims = self.claims("release")
        DRILL.validate_claims(claims)
        for field in ("readinessManifestVerified", "productExecutionVerified"):
            with self.subTest(field=field):
                changed = self.claims("release")
                changed["assertions"][field] = False
                with self.assertRaises(DRILL.ReceiptError):
                    DRILL.validate_claims(changed)

    def test_backup_restore_requires_independent_anchor(self) -> None:
        claims = self.claims("backup_restore")
        claims["assertions"]["independentAnchorMatched"] = False
        with self.assertRaises(DRILL.ReceiptError):
            DRILL.validate_claims(claims)

    def test_candidate_must_bind_readiness_run(self) -> None:
        for field, value in (
            ("readinessManifestSha256", "bad"),
            ("qualificationRunId", ""),
            ("qualificationRunAttempt", 0),
        ):
            with self.subTest(field=field):
                claims = self.claims("product_execution")
                claims[field] = value
                with self.assertRaises(DRILL.ReceiptError):
                    DRILL.validate_claims(claims)

    def test_duplicate_json_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "claims.json"
            path.write_text('{"kind":"release","kind":"target_filesystem"}')
            with self.assertRaises(DRILL.ReceiptError):
                DRILL.load_json(path)

    def test_unknown_fields_are_rejected(self) -> None:
        claims = self.claims("product_execution")
        claims["unbound"] = True
        with self.assertRaises(DRILL.ReceiptError):
            DRILL.validate_claims(claims)

    def test_canonical_digest_is_order_independent(self) -> None:
        left = {"a": 1, "b": 2}
        right = {"b": 2, "a": 1}
        self.assertEqual(DRILL.sha256(DRILL.canonical(left)), DRILL.sha256(DRILL.canonical(right)))


if __name__ == "__main__":
    unittest.main()
