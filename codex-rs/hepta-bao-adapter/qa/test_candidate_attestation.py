"""Control-flow tests only; synthetic receipts are not native execution evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "bao_attest", Path(__file__).with_name("attest_candidate.py")
)
attest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(attest)


class CandidateAttestationTests(unittest.TestCase):
    def receipt(self, root: Path, name: str, role: str, head: str, tree: str, passed=True) -> Path:
        path = root / name
        path.write_text(json.dumps({
            "schema": "hepta.secrets-native-feedback.v1",
            "head": head,
            "tree": tree,
            "expectedSha": head,
            "candidateRole": role,
            "identityClean": True,
            "checks": [],
            "passed": passed,
            "providerDynamicE2E": False,
            "productionExecutionProved": False,
            "independentAcceptance": False,
            "releaseAuthority": False,
        }) + "\n")
        return path

    def execute(self, *, merge_passed=True, dynamic=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.receipt(root, "source.json", "source-head", "a" * 40, "b" * 40)
            merge = self.receipt(
                root, "merge.json", "synthetic-merge", "c" * 40, "d" * 40, merge_passed
            )
            provider = root / "provider.json"
            provider.write_text(json.dumps({
                "serverSha256": "e" * 64,
                "dynamicLeaseExecutionProved": dynamic,
            }) + "\n")
            output = root / "attestation.json"
            argv = [
                "attest_candidate.py",
                "--source-receipt", str(source),
                "--merge-receipt", str(merge),
                "--source-lock-sha256", "1" * 64,
                "--source-manifest-sha256", "2" * 64,
                "--merge-lock-sha256", "3" * 64,
                "--merge-manifest-sha256", "4" * 64,
                "--provider-evidence", str(provider),
                "--output", str(output),
            ]
            with patch("sys.argv", argv), patch.object(
                attest, "tool", side_effect=["rustc synthetic", "cargo synthetic"]
            ):
                code = attest.main()
            return code, json.loads(output.read_text())

    def test_binds_both_candidates_and_all_required_environment_fields(self):
        code, receipt = self.execute()
        self.assertEqual(code, 0)
        self.assertEqual(receipt["sourceCommitSha"], "a" * 40)
        self.assertEqual(receipt["syntheticMergeSha"], "c" * 40)
        self.assertEqual(receipt["dependencyLockSha256"]["source"], "1" * 64)
        self.assertEqual(receipt["providerBinarySha256"], "e" * 64)
        self.assertFalse(receipt["releaseAuthority"])

    def test_failed_native_receipt_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "did not pass"):
            self.execute(merge_passed=False)

    def test_dynamic_provider_claim_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "read-only blocker"):
            self.execute(dynamic=True)


if __name__ == "__main__":
    unittest.main()
