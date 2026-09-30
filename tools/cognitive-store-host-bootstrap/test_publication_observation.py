#!/usr/bin/env python3
"""Real crypto/filesystem regressions; the native owner is mocked explicitly.

Native SQLite semantics remain covered by cognitive_archive_owner in the Rust
qualification plan. A mock is never reported as target-host or native evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import archive
import archive_observation as observation
import lifecycle


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.fleet = self.root / 'fleet'
        self.fleet.mkdir(mode=0o700)
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir(mode=0o700)
        self.source = self.root / 'source.sqlite3'
        self.data = b'fixture cold-image codec payload\0' * 40000
        self.source.write_bytes(self.data)
        self.key = b'k' * 32
        self.now = int(time.time())
        self.plan = {
            'schema': archive.PLAN_SCHEMA, 'request_id': 'archive-original', 'action': 'archive',
            'owner_agent_id': '00000000-0000-4000-8000-000000000058', 'writer_generation': 3,
            'anchor': {'profile': 'hepta:cognitive:exact-current-cut:v1',
                       'owner_agent_id': '00000000-0000-4000-8000-000000000058',
                       'schema_digest': 'a' * 64, 'state_digest': 'b' * 64},
            'image_sha256': hashlib.sha256(self.data).hexdigest(), 'image_bytes': len(self.data),
            'key_id': 'test-key', 'key_sha256': hashlib.sha256(self.key).hexdigest(),
            'policy_sha256': 'c' * 64, 'created_at': self.now - 100, 'expires_at': self.now + 1000,
            'input_path': str(self.source), 'output_path': str(self.root / 'archive'),
            'live_fleet_root': str(self.fleet), 'verifier_sha256': 'd' * 64, 'archive_sha256': None,
        }
        self.permit = self.make_permit(self.plan)
        self.native = patch.object(archive, 'native_check')
        self.owner_check = self.native.start()
        self.addCleanup(self.native.stop)
        self.verifier = self.root / 'not-a-real-native-verifier'
        self.authorized = lambda: copy.deepcopy(self.plan)
        self.signing_key = Ed25519PrivateKey.generate()
        owner_key = Ed25519PrivateKey.generate()
        def trust_key(name, key):
            return {'signer_id': name, 'key_epoch': 1, 'revoked': False,
                    'public_key_hex': key.public_key().public_bytes_raw().hex()}
        self.trust = {'schema': 'hepta.cognitive.lifecycle-trust.v1', 'revision': 1,
                      'valid_until': self.now + 2000, 'coordinator': trust_key('coordinator', self.signing_key),
                      'owners': [trust_key('storage-owner', owner_key)]}
        self.trust_path = self.root / 'trust.json'
        self.plan_path = self.root / 'plan.json'
        self.permit_path = self.root / 'permit.json'
        self.write_authorizations()

    def make_permit(self, plan):
        return {'schema': observation.SCHEMA, 'request_id': 'observe-response-loss',
                'operation_plan_sha256': lifecycle.sha256(plan), 'purpose': 'reconcile_publication',
                'created_at': self.now - 10, 'expires_at': self.now + 500, 'scratch_parent': str(self.scratch)}

    def sign(self, payload):
        envelope = {'payload': payload, 'signer_id': 'coordinator', 'key_epoch': 1}
        envelope['signature_hex'] = self.signing_key.sign(lifecycle.signing_bytes(envelope)).hex()
        return envelope

    def write_authorizations(self):
        self.trust_path.write_bytes(lifecycle.canonical(self.trust))
        self.plan_path.write_bytes(lifecycle.canonical(self.sign(self.plan)))
        self.permit_path.write_bytes(lifecycle.canonical(self.sign(self.permit)))

    def authorize(self, *, observe=True):
        extra = {'observation_path': self.permit_path,
                 'expected_observation': lifecycle.sha256(self.permit)} if observe else {}
        return archive.authorize(self.plan_path, self.trust_path, lifecycle.sha256(self.plan),
                                 lifecycle.sha256(self.trust), **extra)

    def create_archive(self):
        return archive.make_archive(self.plan, self.key, self.verifier, self.authorized)

    def observe(self):
        return observation.observe_publication(self.plan, self.permit, self.key, self.verifier, self.authorized)

    def snapshot(self, path):
        return {str(item.relative_to(path)): (item.stat().st_ino, item.read_bytes())
                for item in path.rglob('*') if item.is_file()}

    def test_lost_archive_response_observes_same_artifact_without_publication(self):
        written = self.create_archive()
        before = self.snapshot(self.root / 'archive')
        with patch.object(archive, 'make_archive', side_effect=AssertionError('must not replay')), \
             patch.object(archive, 'write_new', side_effect=AssertionError('must not publish')):
            report = self.observe()
        self.assertEqual(report['artifact_sha256'], written['archive_sha256'])
        self.assertEqual(report['result'], 'valid_archive_observed')
        self.assertEqual(before, self.snapshot(self.root / 'archive'))
        self.assertEqual([], list(self.scratch.iterdir()))
        self.assertEqual(self.source.read_bytes(), self.data)
        for flag in ('replay_authorized', 'publication_durability_proved', 'production_activated',
                     'physical_erasure_proved', 'hot_history_pruned', 'target_host_qualified'):
            self.assertIs(report[flag], False)
        self.assertEqual(self.owner_check.call_count, 2)

    def test_repeated_observation_does_not_replay(self):
        self.create_archive()
        first, second = self.observe(), self.observe()
        self.assertEqual(first['artifact_sha256'], second['artifact_sha256'])
        self.assertEqual(first['operation_plan_sha256'], second['operation_plan_sha256'])

    def test_missing_destination_never_means_not_applied(self):
        report = self.observe()
        self.assertFalse(report['artifact_verified'])
        self.assertEqual(report['result'], 'missing_or_incomplete')
        self.assertFalse(report['replay_authorized'])
        self.assertFalse((self.root / 'archive').exists())
        self.owner_check.assert_not_called()

    def test_incomplete_archive_is_preserved(self):
        target = self.root / 'archive'
        target.mkdir(mode=0o700)
        marker = target / ('0' * 64)
        marker.write_bytes(b'partial ciphertext')
        before = self.snapshot(target)
        report = self.observe()
        self.assertFalse(report['artifact_verified'])
        self.assertEqual(before, self.snapshot(target))

    def test_truncated_segment_is_not_completed(self):
        self.create_archive()
        target = self.root / 'archive'
        segment = next(item for item in target.iterdir() if item.name != 'manifest.json')
        segment.write_bytes(segment.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            self.observe()

    def test_unknown_archive_file_rejected(self):
        self.create_archive()
        (self.root / 'archive' / 'unexpected').write_bytes(b'x')
        with self.assertRaises(ValueError):
            self.observe()

    def test_different_original_request_cannot_claim_same_archive(self):
        self.create_archive()
        self.plan['request_id'] = 'different-original'
        self.permit = self.make_permit(self.plan)
        with self.assertRaisesRegex(ValueError, 'another original operation'):
            self.observe()

    def test_owner_cut_denial_is_not_success(self):
        self.create_archive()
        self.owner_check.side_effect = archive.OwnerCutRejected('fixture explicit denial')
        with self.assertRaises(archive.OwnerCutRejected):
            self.observe()

    def test_owner_infrastructure_failure_is_not_cut_denial(self):
        self.create_archive()
        self.owner_check.side_effect = RuntimeError('fixture native dependency unavailable')
        with self.assertRaises(RuntimeError):
            self.observe()

    def test_missing_native_verifier_is_not_an_absent_publication(self):
        self.create_archive()
        self.owner_check.side_effect = FileNotFoundError('fixture missing owner binary')
        with self.assertRaises(FileNotFoundError):
            self.observe()

    def test_live_reauthorization_failure_during_observation(self):
        self.create_archive()
        with self.assertRaisesRegex(ValueError, 'revoked'):
            observation.observe_publication(self.plan, self.permit, self.key, self.verifier,
                                           unittest.mock.Mock(side_effect=[self.plan, ValueError('revoked')]))

    def test_reauthorization_cannot_substitute_operation(self):
        self.create_archive()
        other = {**self.plan, 'writer_generation': 99}
        with self.assertRaisesRegex(ValueError, 'changed'):
            observation.observe_publication(self.plan, self.permit, self.key, self.verifier, lambda: other)

    def test_fresh_observation_can_authenticate_expired_original_but_cannot_reexecute(self):
        self.plan['expires_at'] = self.now - 1
        self.permit = self.make_permit(self.plan)
        self.write_authorizations()
        self.assertEqual(self.authorize(), self.plan)
        with self.assertRaises(ValueError):
            self.authorize(observe=False)

    def test_expired_observation_rejected_even_with_valid_signature(self):
        self.permit['expires_at'] = self.now - 1
        self.write_authorizations()
        with self.assertRaises(ValueError):
            self.authorize()

    def test_revoked_current_trust_rejects_historical_observation(self):
        self.trust['coordinator']['revoked'] = True
        self.write_authorizations()
        with self.assertRaisesRegex(ValueError, 'revoked'):
            self.authorize()

    def test_expired_trust_rejected(self):
        self.trust['valid_until'] = self.now - 1
        self.write_authorizations()
        with self.assertRaises(ValueError):
            self.authorize()

    def test_forged_observation_signature_rejected(self):
        envelope = self.sign(self.permit)
        envelope['signature_hex'] = '0' * 128
        self.permit_path.write_bytes(lifecycle.canonical(envelope))
        with self.assertRaises(ValueError):
            self.authorize()

    def test_forged_original_signature_rejected(self):
        envelope = self.sign(self.plan)
        envelope['signature_hex'] = '0' * 128
        self.plan_path.write_bytes(lifecycle.canonical(envelope))
        with self.assertRaises(ValueError):
            self.authorize()

    def test_observation_digest_is_independently_pinned(self):
        with self.assertRaises(ValueError):
            archive.authorize(self.plan_path, self.trust_path, lifecycle.sha256(self.plan),
                              lifecycle.sha256(self.trust), observation_path=self.permit_path,
                              expected_observation='e' * 64)

    def test_observation_path_and_digest_required_together(self):
        for kwargs in ({'observation_path': self.permit_path}, {'expected_observation': 'f' * 64}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                archive.authorize(self.plan_path, self.trust_path, lifecycle.sha256(self.plan),
                                  lifecycle.sha256(self.trust), **kwargs)

    def test_future_original_never_authenticated_by_observation(self):
        self.plan['created_at'] = self.now + 1
        self.permit = self.make_permit(self.plan)
        self.write_authorizations()
        with self.assertRaises(ValueError):
            self.authorize()

    def test_wrong_or_extra_observation_fields_rejected(self):
        for altered in ({**self.permit, 'purpose': 'erase'}, {**self.permit, 'extra': True},
                        {**self.permit, 'operation_plan_sha256': 'e' * 64},
                        {**self.permit, 'created_at': True}):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                observation.validate_observation(altered, self.plan, self.now)

    def test_scratch_must_not_overlap_fleet_or_output(self):
        self.create_archive()
        for target in (self.root, self.fleet, self.root / 'archive'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                observation.validate_observation({**self.permit, 'scratch_parent': str(target)}, self.plan, self.now)

    def test_scratch_must_be_private(self):
        self.scratch.chmod(0o755)
        with self.assertRaises(ValueError):
            self.observe()

    def test_lost_restore_response_uses_same_owner_oracle(self):
        archive_report = self.create_archive()
        restore = {**self.plan, 'action': 'restore', 'request_id': 'restore-original',
                   'input_path': self.plan['output_path'], 'output_path': str(self.root / 'restored.sqlite3'),
                   'archive_sha256': archive_report['archive_sha256']}
        archive.restore_archive(restore, self.key, self.verifier, lambda: restore)
        target = Path(restore['output_path'])
        before = (target.stat().st_ino, target.read_bytes())
        report = observation.observe_publication(restore, self.make_permit(restore), self.key, self.verifier, lambda: restore)
        self.assertEqual(report['result'], 'valid_restore_observed')
        self.assertEqual(report['artifact_sha256'], self.plan['image_sha256'])
        self.assertEqual(before, (target.stat().st_ino, target.read_bytes()))

    def test_restore_sidecar_prevents_completion(self):
        restore = {**self.plan, 'action': 'restore', 'archive_sha256': 'e' * 64,
                   'output_path': str(self.root / 'restored.sqlite3')}
        Path(restore['output_path']).write_bytes(self.data)
        Path(restore['output_path'] + '-wal').write_bytes(b'')
        with self.assertRaises(ValueError):
            observation.observe_publication(restore, self.make_permit(restore), self.key, self.verifier, lambda: restore)

    def test_cli_missing_artifact_returns_incomplete_not_success(self):
        key_path = self.root / 'key'
        key_path.write_bytes(self.key)
        key_path.chmod(0o600)
        command = [sys.executable, str(Path(archive.__file__)), '--plan', str(self.plan_path),
                   '--trusted-owners', str(self.trust_path), '--expected-plan-sha256', lifecycle.sha256(self.plan),
                   '--expected-trust-sha256', lifecycle.sha256(self.trust), '--key-file', str(key_path),
                   '--owner-verifier', str(self.verifier), '--reconcile-plan', str(self.permit_path),
                   '--expected-reconcile-plan-sha256', lifecycle.sha256(self.permit)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 3, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['artifact_verified'])
        self.assertFalse(report['replay_authorized'])


class SignedFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / 'signed.json'
        self.path.write_text('{"revision":1}')

    def test_normal_file(self):
        self.assertEqual(lifecycle.load_bounded(self.path), {'revision': 1})

    @unittest.skipUnless(os.name == 'posix', 'FIFO regression requires POSIX')
    def test_fifo_is_rejected_without_open_blocking(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo, mode=0o600)
        code = ('from pathlib import Path; import lifecycle; '
                f'lifecycle.load_bounded(Path({str(fifo)!r}))')
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(lifecycle.__file__).parent,
                                capture_output=True, text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('single-link regular file', result.stderr)

    def test_replaced_path_rejected_even_if_open_descriptor_unchanged(self):
        original = os.fstat
        count = 0
        def replaced(fd):
            nonlocal count
            value = original(fd)
            count += 1
            if count == 2:
                replacement = self.root / 'new.json'
                replacement.write_text('{"revision":2}')
                replacement.replace(self.path)
            return value
        with patch.object(lifecycle.os, 'fstat', side_effect=replaced), self.assertRaises(ValueError):
            lifecycle.load_bounded(self.path)

    def test_symlink_rejected(self):
        linked = self.root / 'link'
        linked.symlink_to(self.path)
        with self.assertRaises(ValueError):
            lifecycle.load_bounded(linked)

    def test_hardlink_rejected(self):
        os.link(self.path, self.root / 'hardlink')
        with self.assertRaises(ValueError):
            lifecycle.load_bounded(self.path)

    def test_writable_file_rejected(self):
        self.path.chmod(0o666)
        with self.assertRaises(ValueError):
            lifecycle.load_bounded(self.path)

    def test_oversized_input_rejected(self):
        self.path.write_bytes(b' ' * (lifecycle.MAX_INPUT_BYTES + 1))
        with self.assertRaises(ValueError):
            lifecycle.load_bounded(self.path)

    def test_duplicate_and_float_rejected(self):
        for content in ('{"revision":1,"revision":2}', '{"revision":1.0}', '{"revision":NaN}'):
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                lifecycle.load_bounded(self.path)


if __name__ == '__main__':
    unittest.main()
