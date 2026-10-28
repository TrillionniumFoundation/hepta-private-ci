"""Small behavior guards for the fixed pilot archive; no Torch or network."""
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

from . import ci_pilot
from .ci_runtime_tests import ResourceGuards


class PilotGuards(unittest.TestCase):
    def test_forbidden_paths(self):
        for name in ('../outside', '/absolute', 'x/../../outside', 'x//alias', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ci_pilot.relative_path(name)

    def test_archive_rejects_unregistered_member(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            member = tarfile.TarInfo('prepared/qualification/forbidden/RECEIPT.json')
            member.size = 2
            archive.addfile(member, io.BytesIO(b'{}'))
        manifest = {'seed': {'members': [], 'maximum_member_bytes': 10, 'unpacked_bytes': 0}}
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
            ci_pilot.unpack_seed(buffer.getvalue(), manifest, Path(root) / 'assets')

    def test_archive_rejects_link(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            member = tarfile.TarInfo('safe')
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/passwd'
            archive.addfile(member)
        manifest = {'seed': {'members': [{'path': 'safe', 'bytes': 0}],
                             'maximum_member_bytes': 10, 'unpacked_bytes': 0}}
        with tempfile.TemporaryDirectory() as root, self.assertRaises(ValueError):
            ci_pilot.unpack_seed(buffer.getvalue(), manifest, Path(root) / 'assets')

    def test_actual_registered_archive_and_roles(self):
        manifest = ci_pilot.read_manifest()
        payload = ci_pilot.seed_bytes(manifest)
        with tempfile.TemporaryDirectory() as root:
            registration = ci_pilot.unpack_seed(payload, manifest, Path(root) / 'assets')
            self.assertEqual(43, registration['mechanism_events'])
            self.assertEqual(8, len(registration['mechanism_source_ids']))
            self.assertEqual(0, manifest['training_updates'])
            self.assertEqual(0, manifest['holdout_sources'])
        self.assertNotIn('torch', sys.modules)

    def test_corrupted_archive_is_rejected(self):
        manifest = ci_pilot.read_manifest()
        payload = bytearray(ci_pilot.seed_bytes(manifest))
        payload[0] ^= 1
        with tempfile.TemporaryDirectory() as root, self.assertRaises((ValueError, tarfile.ReadError)):
            ci_pilot.unpack_seed(bytes(payload), manifest, Path(root) / 'assets')


if __name__ == '__main__':
    unittest.main()
