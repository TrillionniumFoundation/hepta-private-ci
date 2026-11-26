import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.runtime_codex_receipt import canonical_bytes, verify_receipt


class RuntimeCodexReceiptTests(unittest.TestCase):
    def fixture(self) -> dict:
        return {
            "schema": "hepta.runtime-codex-qualification.v1",
            "schemaVersion": 1,
            "module": "runtime.codex",
            "candidate": {
                "commit": "a" * 40,
                "tree": "b" * 40,
                "parents": [],
                "clean": True,
            },
            "observedPassedTests": 8,
            "observedFailedTests": 0,
            "minimumTotalTests": 8,
            "claimBoundary": {
                "repositoryControlledSourceQualification": True,
                "exactCandidateExecution": True,
                "targetHostIdentityQualified": False,
                "realProviderQualified": False,
                "independentAcceptance": False,
                "activation": False,
                "promotion": False,
                "release": False,
            },
        }

    def write(self, directory: Path, value: dict) -> Path:
        path = directory / "receipt.json"
        raw = canonical_bytes(value)
        path.write_bytes(raw)
        path.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(raw).hexdigest()}  receipt.json\n", encoding="utf-8"
        )
        return path

    def test_canonical_repository_receipt_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            verify_receipt(self.write(Path(directory), self.fixture()))

    def test_repository_receipt_cannot_self_grant_release(self):
        with tempfile.TemporaryDirectory() as directory:
            value = self.fixture()
            value["claimBoundary"]["release"] = True
            with self.assertRaisesRegex(ValueError, "illegally claims release"):
                verify_receipt(self.write(Path(directory), value))

    def test_noncanonical_and_digest_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write(root, self.fixture())
            value = json.loads(path.read_text())
            path.write_text(json.dumps(value, indent=2) + "\n")
            with self.assertRaisesRegex(ValueError, "not canonical"):
                verify_receipt(path)
            path = self.write(root, self.fixture())
            path.with_suffix(".json.sha256").write_text("0" * 64 + "  receipt.json\n")
            with self.assertRaisesRegex(ValueError, "sidecar mismatch"):
                verify_receipt(path)

    def test_failed_or_underfloor_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = self.fixture()
            failed["observedFailedTests"] = 1
            with self.assertRaisesRegex(ValueError, "failed tests"):
                verify_receipt(self.write(root, failed))
            under = self.fixture()
            under["observedPassedTests"] = 7
            with self.assertRaisesRegex(ValueError, "test floor"):
                verify_receipt(self.write(root, under))


if __name__ == "__main__":
    unittest.main()
