"""Synthetic C2 execution-decision admission regression; does not launch training."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import c2_runner
from c2_boundary import Ineligible

class ExecutionDecisionFreezeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.contract = self.root / 'CONTRACT.json'
        self.manifest = self.root / 'PROGRAM-MANIFEST.json'
        self.path = self.root / 'EXECUTION-DECISION.json'
        self.contract.write_bytes(b'{"contract":"fixture"}')
        self.manifest.write_bytes(b'{"manifest":"fixture"}')
        self.valid = {
            'schema': 'hcsn-c2-execution-decision-v1',
            'execution_authorized': True,
            'scope': 'six-original-hcsn-c2-only',
            'confirmation_E_access': False,
            'contract_sha256': hashlib.sha256(self.contract.read_bytes()).hexdigest(),
            'program_manifest_sha256': hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
        }

    def check(self, raw):
        self.path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        return c2_runner.require_decision(self.path, digest, self.contract, self.manifest)

    def test_exact_well_formed_decision(self):
        self.assertEqual(self.check(json.dumps(self.valid).encode()), self.valid)

    def test_duplicate_authorization_key_rejected_even_if_digest_matches(self):
        raw = json.dumps(self.valid).replace('"execution_authorized": true',
             '"execution_authorized": false, "execution_authorized": true').encode()
        with self.assertRaises(Ineligible):
            self.check(raw)

    def test_unreviewed_extra_metadata_rejected(self):
        variant = dict(self.valid, unreviewed={'x': 0})
        with self.assertRaises(Ineligible):
            self.check(json.dumps(variant).encode())

    def test_nonfinite_extra_metadata_rejected(self):
        raw = json.dumps(self.valid)[:-1] + ', "cost": NaN}'
        with self.assertRaises(Ineligible):
            self.check(raw.encode())

    def test_wrong_or_missing_schema_is_rejected(self):
        for variant in (dict(self.valid, schema='legacy'),
                        {k: v for k, v in self.valid.items() if k != 'schema'}):
            with self.subTest(variant=variant.get('schema')):
                with self.assertRaises(Ineligible):
                    self.check(json.dumps(variant).encode())

    def test_matching_symlink_decision_is_rejected(self):
        real = self.root / 'real-decision.json'
        raw = json.dumps(self.valid).encode()
        real.write_bytes(raw)
        self.path.symlink_to(real)
        with self.assertRaises(Ineligible):
            c2_runner.require_decision(self.path, hashlib.sha256(raw).hexdigest(),
                self.contract, self.manifest)

    def test_oversized_decision_is_rejected(self):
        raw = json.dumps({**self.valid, 'padding': 'x' * 70000}).encode()
        with self.assertRaises(Ineligible):
            self.check(raw)

    def test_digest_or_manifest_mismatch_rejected(self):
        raw = json.dumps(self.valid).encode()
        self.path.write_bytes(raw)
        with self.assertRaises(Ineligible):
            c2_runner.require_decision(self.path, '0' * 64, self.contract, self.manifest)
        self.manifest.write_bytes(b'changed')
        with self.assertRaises(Ineligible):
            self.check(raw)

if __name__ == '__main__':
    unittest.main()
