#!/usr/bin/env python3
"""Exercise normal archive observation with real codec/filesystem operations.

The native SQLite checker is deliberately mocked, as in the inherited protocol
suite. These tests do not certify native owner semantics or host qualification.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import archive
import archive_observation as observation
import test_publication_observation as fixtures


class ObservationBoundaryTests(unittest.TestCase):
    setUp = fixtures.PublicationTests.setUp
    make_permit = fixtures.PublicationTests.make_permit
    sign = fixtures.PublicationTests.sign
    write_authorizations = fixtures.PublicationTests.write_authorizations
    create_archive = fixtures.PublicationTests.create_archive
    observe = fixtures.PublicationTests.observe
    snapshot = fixtures.PublicationTests.snapshot

    def restore_output(self):
        report = self.create_archive()
        restore = {**self.plan, 'action': 'restore', 'request_id': 'restore-original',
                   'input_path': self.plan['output_path'], 'output_path': str(self.root / 'restored.sqlite3'),
                   'archive_sha256': report['archive_sha256']}
        archive.restore_archive(restore, self.key, self.verifier, lambda: restore)
        self.plan = restore
        self.permit = self.make_permit(restore)

    def observe_with(self, reauthorize):
        return observation.observe_publication(self.plan, self.permit, self.key, self.verifier, reauthorize)

    def mutate_after_native(self, image, *args):
        image.write_bytes(b'X' * len(self.data))

    def test_archive_changed_bytes_after_owner_check_reject(self):
        self.create_archive()
        self.owner_check.side_effect = self.mutate_after_native
        with self.assertRaisesRegex(ValueError, 'changed after owner'):
            self.observe()

    def test_restore_changed_bytes_after_owner_check_reject(self):
        self.restore_output()
        self.owner_check.side_effect = self.mutate_after_native
        with self.assertRaisesRegex(ValueError, 'changed after owner'):
            self.observe()

    def test_same_bytes_replacement_is_not_the_created_inode(self):
        self.create_archive()
        replacements = []
        def replace(image, *args):
            replacement = image.with_name('replacement.tmp')
            replacement.write_bytes(self.data)
            replacement.chmod(0o600)
            os.replace(replacement, image)
            replacements.append(image)
        self.owner_check.side_effect = replace
        with self.assertRaisesRegex(ValueError, 'created inode'):
            self.observe()
        self.assertEqual(replacements[0].read_bytes(), self.data)

    def test_replacement_payload_is_retained_not_recursively_erased(self):
        self.create_archive()
        replacements = []
        def replace(image, *args):
            other = image.with_name('other.tmp')
            other.write_bytes(b'foreign evidence')
            other.chmod(0o600)
            os.replace(other, image)
            replacements.append(image)
        self.owner_check.side_effect = replace
        with self.assertRaises(ValueError):
            self.observe()
        self.assertEqual(replacements[0].read_bytes(), b'foreign evidence')

    def test_scratch_redirected_during_initial_authorization_rejects_before_copy(self):
        self.create_archive()
        target = self.root / 'replacement-scratch'
        target.mkdir(mode=0o700)
        old = self.root / 'original-scratch'
        def change():
            self.scratch.rename(old)
            self.scratch.symlink_to(target, target_is_directory=True)
            return copy.deepcopy(self.plan)
        self.owner_check.reset_mock()
        with self.assertRaises((ValueError, OSError)):
            self.observe_with(change)
        self.owner_check.assert_not_called()
        self.assertEqual(list(target.iterdir()), [])

    def test_canonical_scratch_replacement_during_authorization_rejects(self):
        self.create_archive()
        def change():
            self.scratch.rename(self.root / 'original-scratch')
            self.scratch.mkdir(mode=0o700)
            return copy.deepcopy(self.plan)
        self.owner_check.reset_mock()
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.observe_with(change)
        self.owner_check.assert_not_called()
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_parent_replacement_after_native_cannot_borrow_observation(self):
        self.create_archive()
        def change(image, *args):
            self.scratch.rename(self.root / 'original-scratch')
            self.scratch.mkdir(mode=0o700)
            (self.scratch / 'foreign').write_bytes(b'untouched')
        self.owner_check.side_effect = change
        with self.assertRaises((ValueError, OSError)):
            self.observe()
        self.assertEqual((self.scratch / 'foreign').read_bytes(), b'untouched')

    def test_final_authorization_cannot_change_checked_bytes(self):
        self.create_archive()
        paths = []
        self.owner_check.side_effect = lambda image, *args: paths.append(image)
        calls = 0
        def change():
            nonlocal calls
            calls += 1
            if calls == 2:
                paths[0].write_bytes(b'Z' * len(self.data))
            return copy.deepcopy(self.plan)
        with self.assertRaisesRegex(ValueError, 'changed after owner'):
            self.observe_with(change)

    def test_final_authorization_cannot_add_hardlink(self):
        self.create_archive()
        paths = []
        self.owner_check.side_effect = lambda image, *args: paths.append(image)
        calls = 0
        link = self.root / 'retained-hardlink'
        def change():
            nonlocal calls
            calls += 1
            if calls == 2:
                os.link(paths[0], link)
            return copy.deepcopy(self.plan)
        with self.assertRaisesRegex(ValueError, 'private created inode'):
            self.observe_with(change)
        self.assertEqual(link.read_bytes(), self.data)
        self.assertTrue(paths[0].exists())

    def test_final_authorization_cannot_relax_staging_permissions(self):
        self.create_archive()
        paths = []
        self.owner_check.side_effect = lambda image, *args: paths.append(image)
        calls = 0
        def change():
            nonlocal calls
            calls += 1
            if calls == 2:
                paths[0].chmod(0o644)
            return copy.deepcopy(self.plan)
        with self.assertRaisesRegex(ValueError, 'private created inode'):
            self.observe_with(change)

    def test_unknown_scratch_child_is_not_deleted(self):
        self.create_archive()
        paths = []
        def introduce(image, *args):
            marker = image.with_name('unrecognized-evidence')
            marker.write_bytes(b'preserve')
            paths.append(marker)
        self.owner_check.side_effect = introduce
        report = self.observe()
        self.assertTrue(report['artifact_verified'])
        self.assertEqual(paths[0].read_bytes(), b'preserve')

    def test_native_failure_cleans_only_own_staged_image(self):
        self.create_archive()
        self.owner_check.side_effect = ValueError('native unavailable')
        with self.assertRaisesRegex(ValueError, 'native unavailable'):
            self.observe()
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertTrue((self.root / 'archive' / 'manifest.json').exists())

    def test_final_revocation_preserves_original_output(self):
        self.create_archive()
        before = self.snapshot(self.root / 'archive')
        calls = 0
        def revoke():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('revoked')
            return copy.deepcopy(self.plan)
        with self.assertRaisesRegex(ValueError, 'revoked'):
            self.observe_with(revoke)
        self.assertEqual(before, self.snapshot(self.root / 'archive'))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_clock_regression_is_not_completion(self):
        self.create_archive()
        with patch.object(observation.time, 'time', side_effect=[self.now, self.now - 1]):
            with self.assertRaisesRegex(ValueError, 'clock regressed'):
                self.observe()

    def test_expiry_during_final_payload_read_rejects_completion(self):
        self.create_archive()
        with patch.object(observation.time, 'time', side_effect=[self.now, self.now, self.now + 1000]):
            with self.assertRaisesRegex(ValueError, 'expired or future'):
                self.observe()

    def test_missing_output_does_not_bypass_parent_identity(self):
        calls = 0
        def change():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.scratch.rename(self.root / 'old-scratch')
                self.scratch.mkdir(mode=0o700)
            return copy.deepcopy(self.plan)
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.observe_with(change)
        self.owner_check.assert_not_called()

    def test_normal_observation_never_grants_replay_or_erasure(self):
        self.create_archive()
        before = self.snapshot(self.root / 'archive')
        report = self.observe()
        self.assertTrue(report['artifact_verified'])
        for key in ('replay_authorized', 'grants_authority', 'publication_durability_proved',
                    'physical_erasure_proved', 'hot_history_pruned', 'target_host_qualified'):
            self.assertIs(report[key], False)
        self.assertEqual(before, self.snapshot(self.root / 'archive'))
        self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
