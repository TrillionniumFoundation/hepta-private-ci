"""No-network negative tests for read-only exact original GitHub ZIP handoff."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import download_original_zip_v5 as dl


class OriginalDownloaderTests(unittest.TestCase):
    def setUp(self):
        self.meta = {'run_id': 100, 'artifact_id': 200, 'archive_sha256': '1'*64,
                     'json_member': 'source.json', 'json_sha256': '2'*64}

    def test_rejects_unfrozen_artifact_before_network(self):
        for field, replacement in [('artifact_id', None), ('archive_sha256', None),
                                   ('json_sha256','F'*64), ('run_id', 0)]:
            meta = dict(self.meta)
            meta[field] = replacement
            with patch.object(dl, 'get_api_json') as network:
                with tempfile.TemporaryDirectory() as path:
                    with self.assertRaises(ValueError):
                        dl.download_one('TrillionniumFoundation/hepta-private-ci', 'token', meta,
                                        Path(path) / 'blocked.zip')
                network.assert_not_called()

    def test_bad_owner_rejected_before_remote_api(self):
        with patch.object(dl, 'get_api_json') as network:
            with self.assertRaisesRegex(ValueError, 'unexpected repo owner'):
                dl.download_one('other/repo', 'token', self.meta, Path('blocked.zip'))
            network.assert_not_called()

    def test_archive_not_from_frozen_run_rejected(self):
        with patch.object(dl, 'get_api_json', return_value={
            'id': 200, 'expired': False, 'workflow_run': {'id': 101}, 'digest': 'sha256:' + '1'*64}):
            with tempfile.TemporaryDirectory() as path:
                with self.assertRaisesRegex(ValueError, 'run ownership mismatch'):
                    dl.download_one('TrillionniumFoundation/hepta-private-ci', 'token', self.meta,
                                    Path(path) / 'blocked.zip')

    def test_original_zip_metadata_digest_mismatch_rejected(self):
        with patch.object(dl, 'get_api_json', return_value={
            'id': 200, 'expired': False, 'workflow_run': {'id': 100}, 'digest': 'sha256:' + 'f'*64}):
            with tempfile.TemporaryDirectory() as path:
                with self.assertRaisesRegex(ValueError, 'metadata digest changed'):
                    dl.download_one('TrillionniumFoundation/hepta-private-ci', 'token', self.meta,
                                    Path(path) / 'blocked.zip')


if __name__ == '__main__':
    unittest.main()
