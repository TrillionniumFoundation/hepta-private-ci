"""No-skip integration using ORIGINAL pinned #1494 modules and ephemeral test keys.

Invoked separately because the isolated owner checkout is a required dependency.
These generated signatures are fixtures, never production receipts or authority.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from baseline_bridge_fixtures import fixture, write_cell
from four_gate_baseline import OWNER_BLOBS, review_production_baseline
from four_gate_common import canonical, digest
from four_gate_review import BASELINE_BUNDLE, review_all

OWNER_ROOT = Path(os.environ['HEPTA_BASELINE_OWNER_ROOT'])
# Import only test constants/helpers from the separately frozen source checkout.
sys.path.insert(0, str(OWNER_ROOT / 'scripts'))
import hepta_neuron_real_cohort_preflight as owner
import hepta_neuron_production_baseline_compare as baseline
from hepta_neuron_model_trials import blind_rows, canonical_jsonl


class OwnerBridgeChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan, self.cell, self.cohort, self.sealed, self.packet, self.verified = fixture()
        self.keys = {role: Ed25519PrivateKey.generate() for role in owner.ROLES}
        self.trust = {'schema': owner.TRUST_SCHEMA, 'roles': {role: {
            'key_id': 'key-' + role, 'controller_id': 'controller-' + role,
            'principal_id': 'principal-' + role,
            'ed25519_public_key_hex': self.keys[role].public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()}
            for role in owner.ROLES}}
        self.trust_path = self.root / 'operator-trust.json'
        self.trust_path.write_bytes(canonical(self.trust))
        self.trust_sha = hashlib.sha256(self.trust_path.read_bytes()).hexdigest()
        self.build()

    def save(self, name, raw):
        (self.root / name).write_bytes(raw)
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def build(self):
        self.refs = write_cell(self.root, self.cell)
        raw = b''.join(canonical(row) + b'\n' for row in self.sealed)
        self.refs['sealed'] = self.save('sealed', raw)
        payload = self.cohort['payload']
        payload['sealed_dataset_sha256'] = hashlib.sha256(raw).hexdigest()
        by_id = {r['id']: r for r in self.sealed}
        for source in payload['rows']:
            source['observation_sha256'] = owner.observation_digest(by_id[source['id']], payload['family'])
        self.manifest = {'family': payload['family'], 'dataset_sha256': payload['sealed_dataset_sha256'],
            'blind_dataset_sha256': hashlib.sha256(canonical_jsonl(blind_rows(self.sealed, payload['family']))).hexdigest()}
        self.refs['manifest'] = self.save('manifest', canonical(self.manifest))
        revalidated = payload['source_current_revalidated_at_unix_micros']
        attestations = {}
        for role in owner.ROLES:
            record = {'schema': owner.ATTEST_SCHEMA, 'role': role, 'key_id': 'key-' + role,
                      'body_sha256': digest(payload), 'signed_at_unix_micros': revalidated + 100}
            record['signature_ed25519_hex'] = self.keys[role].sign(owner.DOMAIN + canonical(record)).hex()
            attestations[role] = record
        self.cohort['attestations'] = attestations
        self.refs['cohort'] = self.save('cohort', canonical(self.cohort))
        observations = []
        for source in payload['rows']:
            if source['split'] == 'train':
                continue
            row = deepcopy(self.verified['observations'][source['id']])
            row['observation_sha256'] = source['observation_sha256']
            observations.append(row)
        body = {'cohort_sha256': self.refs['cohort']['sha256'],
            'trial_manifest_sha256': self.refs['manifest']['sha256'],
            'dataset_sha256': self.manifest['dataset_sha256'],
            'blind_dataset_sha256': self.manifest['blind_dataset_sha256'],
            'source_dataset_digest': payload['dataset']['dataset_digest'],
            'frozen_plan_digest': payload['frozen_plan_digest'], 'no_change': payload['no_change'],
            'revalidated_at_unix_micros': revalidated, 'observations': observations}
        signature = {'role': 'baseline_owner', 'key_id': 'key-baseline_owner',
                     'signed_at_unix_micros': revalidated + 200}
        message = baseline.SIGNATURE_DOMAIN + canonical({'schema': baseline.SCHEMA, 'body': body, **signature})
        signature['signature_ed25519_hex'] = self.keys['baseline_owner'].sign(message).hex()
        self.packet = {'schema': baseline.SCHEMA, 'body': body, 'owner_signature': signature}
        self.refs['baseline'] = self.save('baseline', canonical(self.packet))

    def run_review(self, **kwargs):
        return review_production_baseline(self.plan, self.refs, self.root,
            owner_root=kwargs.get('owner_root', OWNER_ROOT), trust_path=self.trust_path,
            trust_sha256=kwargs.get('trust_sha', self.trust_sha))

    def test_original_owner_verifier_pairs_all_three_typed_arms(self):
        report = self.run_review()
        self.assertEqual(report['status'], 'diagnostic_complete')
        self.assertEqual(report['owner_verification']['verified_role_signature_count'], 5)
        self.assertEqual(report['windows']['future_1']['rows'], 32)
        self.assertIsNone(report['windows']['future_1']['no_change']['brier'])
        self.assertFalse(report['scientific_superiority_established'])
        self.assertFalse(report['native_owner_currently_queried'])
        self.assertFalse(report['candidate_trace_signature_verified'])
        self.assertFalse(report['candidate_input_delivery_authenticated'])

    def test_frozen_learned_baseline_descriptor_also_supported(self):
        d = self.cohort['payload']['no_change']
        d.update(kind='deployed_learned', model_manifest_digest=digest('model'),
                 weights_digest=digest('real-format-test-weights'), code_digest=None)
        self.plan['production_baseline']['expected_descriptor_sha256'] = digest(d)
        self.build()
        self.assertEqual(self.run_review()['status'], 'diagnostic_complete')

    def test_changed_signed_bytes_rejected_even_after_outer_rehash(self):
        self.packet['body']['observations'][-1]['selected_option'] = 'yes'
        self.refs['baseline'] = self.save('baseline', canonical(self.packet))
        with self.assertRaisesRegex(ValueError, 'verification rejected'):
            self.run_review()

    def test_wrong_independent_trust_pin_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SHA mismatch'):
            self.run_review(trust_sha=digest('other-trust'))

    def test_missing_one_role_signature_rejected(self):
        self.cohort['attestations'].pop('observer')
        self.refs['cohort'] = self.save('cohort', canonical(self.cohort))
        with self.assertRaisesRegex(ValueError, 'verification rejected'):
            self.run_review()

    def test_resigned_wrong_input_cannot_pair_with_old_cell_trace(self):
        self.sealed[-1]['question'] = 'different observed question'
        self.build()
        with self.assertRaisesRegex(ValueError, 'identical input'):
            self.run_review()

    def test_resigned_generation_change_rejected(self):
        self.verified['observations'][self.sealed[-1]['id']]['generation'] += 1
        self.build()
        with self.assertRaisesRegex(ValueError, 'verification rejected'):
            self.run_review()

    def test_resigned_partial_inventory_rejected(self):
        self.packet['body']['observations'].pop()
        # Correctly sign the changed packet: coverage must fail independently.
        sig = {k: v for k, v in self.packet['owner_signature'].items() if k != 'signature_ed25519_hex'}
        msg = baseline.SIGNATURE_DOMAIN + canonical({'schema': baseline.SCHEMA, 'body': self.packet['body'], **sig})
        self.packet['owner_signature']['signature_ed25519_hex'] = self.keys['baseline_owner'].sign(msg).hex()
        self.refs['baseline'] = self.save('baseline', canonical(self.packet))
        with self.assertRaisesRegex(ValueError, 'verification rejected'):
            self.run_review()

    def test_verifier_source_tampering_rejected_before_import(self):
        target = self.root / 'changed-source' / 'scripts'
        target.mkdir(parents=True)
        for name in OWNER_BLOBS:
            shutil.copyfile(OWNER_ROOT / 'scripts' / name, target / name)
        with (target / next(iter(OWNER_BLOBS))).open('a') as stream:
            stream.write('\nraise RuntimeError("UNTRUSTED SOURCE EXECUTED")\n')
        with self.assertRaisesRegex(ValueError, 'source drift'):
            self.run_review(owner_root=target.parent)

    def test_symlink_evidence_ref_rejected(self):
        original = self.root / 'baseline'
        original.rename(self.root / 'underlying')
        original.symlink_to('underlying')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_review()

    def test_same_entrypoint_keeps_scientific_gates_closed(self):
        bundle = {'schema': BASELINE_BUNDLE, 'plan_sha256': digest(self.plan),
                  'evidence': {k: None for k in ('compute','learning','reasoning','ndu')},
                  'production_baseline': self.refs}
        report = review_all(self.plan, bundle, self.root, baseline_owner_root=OWNER_ROOT,
                           baseline_trust_path=self.trust_path, baseline_trust_sha256=self.trust_sha)
        self.assertEqual(report['typed_production_baseline']['status'], 'diagnostic_complete')
        self.assertFalse(report['current_acceptance_profile_passed'])
        self.assertFalse(report['all_offline_diagnostics_passed'])
        self.assertFalse(report['independent_signatures_verified'])

    def test_resigned_blind_manifest_hash_cannot_replace_actual_inputs(self):
        self.manifest['blind_dataset_sha256'] = digest('different-blinded-inputs')
        self.refs['manifest'] = self.save('manifest', canonical(self.manifest))
        body = self.packet['body']
        body['trial_manifest_sha256'] = self.refs['manifest']['sha256']
        body['blind_dataset_sha256'] = self.manifest['blind_dataset_sha256']
        sig = {k: v for k, v in self.packet['owner_signature'].items() if k != 'signature_ed25519_hex'}
        message = baseline.SIGNATURE_DOMAIN + canonical({'schema': baseline.SCHEMA, 'body': body, **sig})
        self.packet['owner_signature']['signature_ed25519_hex'] = self.keys['baseline_owner'].sign(message).hex()
        self.refs['baseline'] = self.save('baseline', canonical(self.packet))
        with self.assertRaisesRegex(ValueError, 'verification rejected'):
            self.run_review()

    def test_resigned_manifest_dataset_hash_cannot_replace_original_bytes(self):
        self.manifest['dataset_sha256'] = digest('different-sealed-bytes')
        self.refs['manifest'] = self.save('manifest', canonical(self.manifest))
        body = self.packet['body']
        body['trial_manifest_sha256'] = self.refs['manifest']['sha256']
        body['dataset_sha256'] = self.manifest['dataset_sha256']
        sig = {k: v for k, v in self.packet['owner_signature'].items() if k != 'signature_ed25519_hex'}
        message = baseline.SIGNATURE_DOMAIN + canonical({'schema': baseline.SCHEMA, 'body': body, **sig})
        self.packet['owner_signature']['signature_ed25519_hex'] = self.keys['baseline_owner'].sign(message).hex()
        self.refs['baseline'] = self.save('baseline', canonical(self.packet))
        with self.assertRaisesRegex(ValueError, 'verification rejected'):
            self.run_review()

    def test_abstention_signature_keeps_risk_undefined(self):
        for row in self.verified['observations'].values():
            row.update(disposition='abstained', selected_option=None)
        self.build()
        result = self.run_review()['windows']['future_1']
        self.assertIsNone(result['no_change']['selective_accuracy'])
        self.assertEqual(result['trained']['baseline_selected_pairs'], 0)


if __name__ == '__main__':
    unittest.main()
