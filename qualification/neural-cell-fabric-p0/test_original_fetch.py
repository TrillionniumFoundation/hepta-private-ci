"""No network; strict hosted artifact downloader threat/custody surface."""
from __future__ import annotations
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from original_fetch import ArtifactDenied, NoRedirect, safe_blob_url, download_original


class FetchGuards(unittest.TestCase):
    def test_approved_blob_hostname_only(self):
        self.assertEqual(safe_blob_url('https://example.blob.core.windows.net/archive?sig=opaque'),
                         'https://example.blob.core.windows.net/archive?sig=opaque')
        self.assertEqual(safe_blob_url('https://actions.githubusercontent.com/archive?sig=x'),
                         'https://actions.githubusercontent.com/archive?sig=x')
        for url in ('http://example.blob.core.windows.net/file',
                    'https://api.github.com/anything',
                    'https://evil.blob.core.windows.net.evil.com/zip',
                    'https://user:pass@example.blob.core.windows.net/file',
                    'https://example.blob.core.windows.net:8080/zip',
                    'file:///etc/passwd', ''):
            with self.subTest(url=url):
                with self.assertRaises(ArtifactDenied):
                    safe_blob_url(url)

    def test_download_disallows_missing_credentials_and_unknown_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ArtifactDenied):
                download_original('unregistered', Path(root)/'x', 'token')
            with self.assertRaises(ArtifactDenied):
                download_original('features', Path(root)/'x', '')

    def test_no_auto_redirect_with_bearer_headers(self):
        import urllib.request
        from email.message import Message
        req = urllib.request.Request('https://api.github.com/', headers={'Authorization':'Bearer SECRET'})
        self.assertIsNone(NoRedirect().redirect_request(req, None, 302, 'Found', Message(),
                                                    'https://example.blob.core.windows.net/zip'))


if __name__ == '__main__':
    unittest.main()
