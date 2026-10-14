"""Local fake-byte pinning tests; these are not actual model weights."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from prepare_gemma2_snapshot import prepare_snapshot, remote_plan
from embeddinggemma2_shadow import QualificationError, load_manifest

REVISION = 'a' * 40
VERSIONS = {'torch': '2.10.0', 'transformers': '5.19.0', 'tokenizers': '0.22.0',
            'safetensors': '0.6.0', 'sentence-transformers': '6.1.0'}


def make_api(root, extra=None):
    files = []
    for name in ('config.json', 'model.safetensors'):
        content = (root / name).read_bytes()
        files.append(SimpleNamespace(rfilename=name, size=len(content),
                     lfs={'sha256': hashlib.sha256(content).hexdigest()}))
    files.extend(extra or [])
    return SimpleNamespace(model_info=lambda **kwargs: SimpleNamespace(
        sha=REVISION, card_data={'license': 'apache-2.0'}, siblings=files))


class SnapshotPreparation(unittest.TestCase):
    def test_prepare_verified_local_inert_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config.json').write_text('{"ok":true}')
            (root / 'model.safetensors').write_bytes(b'fake weight identity fixture')
            result = prepare_snapshot(
                REVISION, root / 'prepared', api=make_api(root),
                downloader=lambda **kwargs: str(root / kwargs['filename']),
                runtime_versions=VERSIONS)
            self.assertFalse(result['actual_encoder_forward_executed'])
            self.assertEqual(result['production_promotion'], 'DENY_ALL')
            manifest, folder, _ = load_manifest(root / 'prepared' / 'manifest.json')
            self.assertEqual(len(manifest['files']), 2)
            self.assertEqual(folder, (root / 'prepared' / 'snapshot').resolve())
            self.assertFalse((root / 'prepared' / 'snapshot' / 'model.safetensors').is_symlink())

    def test_remote_revision_bad_license_and_executable_rejected(self):
        source = SimpleNamespace(sha='b' * 40, card_data={'license': 'apache-2.0'}, siblings=[])
        with self.assertRaises(QualificationError):
            remote_plan(source, REVISION)
        source = SimpleNamespace(sha=REVISION, card_data={'license': 'unknown'}, siblings=[])
        with self.assertRaises(QualificationError):
            remote_plan(source, REVISION)
        source = SimpleNamespace(sha=REVISION, card_data={'license': 'apache-2.0'},
                                 siblings=[SimpleNamespace(rfilename='model.bin', size=20, lfs=None)])
        with self.assertRaises(QualificationError):
            remote_plan(source, REVISION)

    def test_corrupt_remote_byte_digest_never_publish_partial_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config.json').write_text('{}')
            (root / 'model.safetensors').write_bytes(b'fixture')
            api = make_api(root)
            (root / 'model.safetensors').write_bytes(b'tampered')
            with self.assertRaises(QualificationError):
                prepare_snapshot(
                    REVISION, root / 'prepared', api=api,
                    downloader=lambda **kwargs: str(root / kwargs['filename']),
                    runtime_versions=VERSIONS)
            self.assertFalse((root / 'prepared').exists())


if __name__ == '__main__':
    unittest.main()
