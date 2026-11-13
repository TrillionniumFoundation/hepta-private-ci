"""Synthetic contract tests only. Never evidence of a real host benchmark."""
import base64
import hashlib
import itertools
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import hepta_physical_split_qualification as gate


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.secret = self.directory / 'secret.pem'
        self.public = self.directory / 'observer.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'Ed25519',
                        '-out', str(self.secret)], check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(self.secret), '-pubout',
                        '-out', str(self.public)], check=True, capture_output=True)
        self.manifest = {
            'schema': 'hepta.physical-split-qualification.v1',
            'dimensions': {name: ['off', 'on'] for name in ('a', 'b', 'c', 'd')},
            'frozen_workload_sha256': '1' * 64,
            'observer_id': 'independent-observer',
            'max_candidate_over_baseline': {name: 1.1 for name in gate.LOWER},
            'min_candidate_over_baseline': {name: 1.0 for name in gate.HIGHER},
            'cases': [],
        }
        for index, combination in enumerate(itertools.product(['off', 'on'], repeat=4)):
            metrics = {name: 10.0 for name in gate.METRICS}
            evidence = {
                'observer_id': 'independent-observer',
                'executor_id': 'executor',
                'evaluator_id': 'evaluator',
                'frozen_workload_sha256': '1' * 64,
                'factors': dict(zip(('a', 'b', 'c', 'd'), combination)),
                'baseline_evidence_sha256': '2' * 64,
                'candidate_evidence_sha256': format(index + 3, '064x'),
                'baseline': metrics,
                'candidate': metrics.copy(),
            }
            self.manifest['cases'].append({
                'evidence': evidence, 'signature_b64': self.sign(evidence)})
        self.pin = self.policy_pin()

    def policy_pin(self):
        return hashlib.sha256(gate.canonical(
            {key: value for key, value in self.manifest.items()
             if key != 'cases'})).hexdigest()

    def sign(self, evidence):
        data = self.directory / 'payload.json'
        signature = self.directory / 'payload.sig'
        data.write_bytes(gate.canonical(evidence))
        subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', str(self.secret),
                        '-rawin', '-in', str(data), '-out', str(signature)],
                       check=True, capture_output=True)
        return base64.b64encode(signature.read_bytes()).decode()

    def test_full_matrix_with_observer_signatures(self):
        result = gate.qualify(self.manifest, self.public, self.pin)
        self.assertTrue(result['qualified'])
        self.assertFalse(result['execution_authority'])

    def test_missing_case_fail_closed(self):
        self.manifest['cases'].pop()
        with self.assertRaisesRegex(ValueError, 'sixteen'):
            gate.qualify(self.manifest, self.public, self.pin)

    def test_unauthenticated_metrics_fail_closed(self):
        self.manifest['cases'][0]['evidence']['candidate']['p99_ms'] = 1.0
        with self.assertRaisesRegex(ValueError, 'signature'):
            gate.qualify(self.manifest, self.public, self.pin)

    def test_changed_policy_fails_external_pin(self):
        self.manifest['max_candidate_over_baseline']['p99_ms'] = 100.0
        with self.assertRaisesRegex(ValueError, 'pinned'):
            gate.qualify(self.manifest, self.public, self.pin)

    def test_role_collision_fail_closed(self):
        evidence = self.manifest['cases'][0]['evidence']
        evidence['executor_id'] = evidence['observer_id']
        self.manifest['cases'][0]['signature_b64'] = self.sign(evidence)
        with self.assertRaisesRegex(ValueError, 'collision'):
            gate.qualify(self.manifest, self.public, self.pin)


if __name__ == '__main__':
    unittest.main()
