from __future__ import annotations

import importlib.util
import pathlib
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
            }
        elif kind == "backup_restore":
            assertions = {
                "restoredDigestMatches": True,
                "oldGenerationRejected": True,
            }
        else:
            raise AssertionError(kind)
        return {
            "module": "learning.artifacts",
            "kind": kind,
            "sourceSha": "a" * 40,
            "sourceTree": "b" * 40,
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

    def test_backup_restore_requires_rollback_rejection(self) -> None:
        claims = self.claims("backup_restore")
        claims["assertions"]["oldGenerationRejected"] = False
        with self.assertRaises(DRILL.ReceiptError):
            DRILL.validate_claims(claims)

    def test_canonical_digest_is_order_independent(self) -> None:
        left = {"a": 1, "b": 2}
        right = {"b": 2, "a": 1}
        self.assertEqual(DRILL.sha256(DRILL.canonical(left)), DRILL.sha256(DRILL.canonical(right)))


if __name__ == "__main__":
    unittest.main()
