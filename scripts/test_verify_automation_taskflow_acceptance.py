import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("verify_automation_taskflow_acceptance.py")
SPEC = importlib.util.spec_from_file_location("automation_acceptance", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(shutil.which("openssl"), "openssl is required")
class AcceptanceVerifierTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        private_key = root / "private.pem"
        public_key = root / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        commit = "a" * 40
        tree = "b" * 40
        focused = {
            "schema": "hepta.automation-taskflow.command-receipt.v1",
            "commit": commit,
            "tree": tree,
            "runId": "101",
        }
        selected = {
            "schema": "hepta.automation-taskflow.selected-host-receipt.v1",
            "commit": commit,
            "tree": tree,
            "targetProfile": "selected-linux-x86_64",
            "providerIdentitySha256": "c" * 64,
            "terminalObserverIdentitySha256": "d" * 64,
            "finalUseTrustSha256": "e" * 64,
            "revocationHeadSha256": "f" * 64,
            "run": {"id": "202"},
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        }
        focused_path = root / "focused.json"
        selected_path = root / "selected.json"
        focused_path.write_text(json.dumps(focused, sort_keys=True) + "\n", encoding="utf-8")
        selected_path.write_text(json.dumps(selected, sort_keys=True) + "\n", encoding="utf-8")

        payload = {
            "schema": "hepta.automation-taskflow.independent-acceptance-payload.v1",
            "module": "automation.taskflow",
            "candidateCommit": commit,
            "candidateTree": tree,
            "focusedRunId": "101",
            "selectedHostRunId": "202",
            "targetProfile": "selected-linux-x86_64",
            "focusedReceiptSha256": MODULE.sha256_file(focused_path),
            "selectedHostReceiptSha256": MODULE.sha256_file(selected_path),
            "providerIdentitySha256": "c" * 64,
            "terminalObserverIdentitySha256": "d" * 64,
            "finalUseTrustSha256": "e" * 64,
            "revocationHeadSha256": "f" * 64,
            "implementationPrincipal": "implementation:automation-platform",
            "acceptancePrincipal": "acceptance:independent-review",
            "acceptanceKeySha256": MODULE.trusted_public_key_sha256(public_key),
            "decision": "accepted",
            "independentAcceptance": True,
            "acceptedAtUtc": "2026-09-27T00:00:00Z",
            "nonce": "acceptance-1",
        }
        payload_path = root / "payload.json"
        signature_path = root / "signature.bin"
        payload_path.write_bytes(MODULE.canonical_payload_bytes(payload))
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(private_key),
                "-rawin",
                "-in",
                str(payload_path),
                "-out",
                str(signature_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        envelope_path = root / "envelope.json"
        envelope_path.write_text(
            json.dumps(
                {
                    "schema": "hepta.automation-taskflow.independent-acceptance-envelope.v1",
                    "payload": payload,
                    "signatureHex": signature_path.read_bytes().hex(),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return temporary, envelope_path, focused_path, selected_path, public_key, commit, tree

    def verify(self, values, **overrides):
        temporary, envelope, focused, selected, public_key, commit, tree = values
        del temporary
        arguments = {
            "envelope_path": envelope,
            "focused_receipt_path": focused,
            "selected_host_receipt_path": selected,
            "public_key_pem": public_key,
            "candidate_commit": commit,
            "candidate_tree": tree,
            "focused_run_id": "101",
            "selected_host_run_id": "202",
            "expected_implementation_principal": "implementation:automation-platform",
            "expected_acceptance_principal": "acceptance:independent-review",
        }
        arguments.update(overrides)
        return MODULE.verify_acceptance(**arguments)

    def test_valid_independent_signature_binds_both_receipts(self):
        values = self.fixture()
        self.addCleanup(values[0].cleanup)
        result = self.verify(values)
        self.assertTrue(result["independentAcceptance"])
        self.assertFalse(result["release"])
        self.assertEqual(result["candidateCommit"], "a" * 40)

    def test_same_principal_is_rejected(self):
        values = self.fixture()
        self.addCleanup(values[0].cleanup)
        with self.assertRaisesRegex(MODULE.AcceptanceError, "must be distinct"):
            self.verify(
                values,
                expected_acceptance_principal="implementation:automation-platform",
            )

    def test_receipt_mutation_breaks_signed_binding(self):
        values = self.fixture()
        self.addCleanup(values[0].cleanup)
        selected = json.loads(values[3].read_text(encoding="utf-8"))
        selected["targetProfile"] = "mutated-profile"
        values[3].write_text(json.dumps(selected, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.AcceptanceError, "target profile mismatch"):
            self.verify(values)


if __name__ == "__main__":
    unittest.main()
