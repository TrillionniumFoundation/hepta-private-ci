import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import quality_checks as quality


class LosslessOracleTests(unittest.TestCase):
    def envelope(self):
        return {"contract": "ModalitySpanRefV1", "schema": "hepta.hnmf.modality-span-ref.v1", "schemaVersion": 1,
                "payload": {"assetSha256": "a" * 64, "featureBlobSha256": None, "modality": "text",
                            "preprocessorManifestSha256": "b" * 64, "privacyClass": "agent_private",
                            "range": {"kind": "byte_range", "start": 0, "end": 4},
                            "redactionMaskSha256": None, "spanId": "span:1", "symbolicProjectionSha256": None,
                            "uncertaintyPpm": 10000}}

    def oracle(self, wire, expected=None):
        return quality.invoke(["node", str(Path(__file__).with_name("verify_lossless_wire.mjs"))], wire, expected)

    def test_node_matches_python_frozen_known_golden(self):
        envelope = self.envelope()
        expected = quality.digests(envelope)
        self.assertEqual(expected["frozen_sha256"], "1e1c8f2232a1f6ddfea98400f3c2ae9d29ecd39ae2a2ff0e0bac70f91f0ad273")
        self.assertEqual(expected["bound_sha256"], "3b26fc9684c21992c2a1740a1b2521b9297579f48a9c9cc2d4d9ee574afcfcb3")
        self.assertTrue(self.oracle(quality.canonical(envelope), expected)["passed"])

    def test_full_width_integers_remain_exact(self):
        for integer in [2**53 - 1, 2**53, 2**53 + 1, 2**63, 2**64 - 1]:
            with self.subTest(integer=integer):
                envelope = self.envelope()
                envelope["payload"]["range"].update(start=integer - 1, end=integer)
                self.assertTrue(self.oracle(quality.canonical(envelope), quality.digests(envelope))["passed"])

    def test_unicode_profiles_preserve_codepoints(self):
        hashes = []
        for pointer in ["/é", "/e\u0301", "/😀", "/𐀀", "/~0/~1", ""]:
            envelope = self.envelope()
            envelope["payload"]["modality"] = "structured_data"
            envelope["payload"]["range"] = {"kind": "json_pointer", "pointer": pointer}
            expected = quality.digests(envelope)
            hashes.append(expected["bound_sha256"])
            self.assertTrue(self.oracle(quality.canonical(envelope), expected)["passed"])
        self.assertEqual(len(hashes), len(set(hashes)))

    def test_noncanonical_inputs_are_rejected_not_rounded(self):
        wire = quality.canonical(self.envelope())
        for mutant in [b" " + wire, wire + b"\n", b'{"contract":"wrong",' + wire[1:],
                       wire.replace(b'"end":4', b'"end":4.0'),
                       wire.replace(b'"start":0', b'"start":-0'),
                       wire.replace(b'"end":4', b'"end":18446744073709551616')]:
            with self.subTest(mutant=mutant):
                self.assertTrue(self.oracle(mutant)["passed"])

    def test_process_crash_cannot_count_as_semantic_rejection(self):
        result = quality.invoke([sys.executable, "-c", "raise SystemExit(101)"], b"invalid")
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "infrastructure_invalid")


if __name__ == "__main__":
    unittest.main()
