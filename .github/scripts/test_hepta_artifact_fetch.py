"""Offline adversarial transport checks; no network, secrets or task claims."""
import hashlib
import io
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import hepta_artifact_fetch as af

DATA = b'original only; sha256 checked before creation'
GOOD = 'https://productionresultssa0.blob.core.windows.net/result/x.zip?sv=original&sig=signed'


class FakeResponse(io.BytesIO):
    def __init__(self, data, location):
        super().__init__(data)
        self.location = location
    def geturl(self):
        return self.location


class FakeOpener:
    def __init__(self, *, location=GOOD, blob=DATA, status=302, redirect_again=False):
        self.location, self.blob, self.status = location, blob, status
        self.redirect_again = redirect_again
        self.calls = []
    def open(self, request, timeout):
        assert timeout == 120
        self.calls.append(request)
        if len(self.calls) == 1:
            raise urllib.error.HTTPError(request.full_url, self.status, 'response',
                                         {'Location': self.location}, None)
        if self.redirect_again:
            raise urllib.error.HTTPError(request.full_url, 302, 'second redirect',
                                         {'Location': 'https://evil.example/steal?sig=x'}, None)
        return FakeResponse(self.blob, self.location)


class ArtifactTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'original.zip'

    def test_real_original_lock_is_declared(self):
        self.assertEqual(af.ARCHIVE_ID, 11870475540)
        self.assertEqual(af.REPO, 'TrillionniumFoundation/hepta-private-ci')
        self.assertEqual(len(af.EXPECTED_SHA256), 64)

    def test_no_auth_cross_host_on_success(self):
        fake = FakeOpener()
        with mock.patch.object(af, 'EXPECTED_SHA256', hashlib.sha256(DATA).hexdigest()):
            a = af.download_original('secret-token', self.output,
                                     expected_sha=hashlib.sha256(DATA).hexdigest(), opener=fake)
        self.assertEqual(a['bytes'], len(DATA))
        self.assertEqual(self.output.read_bytes(), DATA)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn('Authorization', fake.calls[0].headers)
        self.assertNotIn('Authorization', fake.calls[1].headers)
        self.assertNotIn('Accept', fake.calls[1].headers)
        self.assertEqual(fake.calls[1].full_url, GOOD)
        self.assertEqual(fake.calls[1].get_method(), 'GET')

    def test_bad_original_source_sha_refuses_before_write(self):
        fake = FakeOpener()
        with self.assertRaisesRegex(ValueError, 'original artifact bytes'):
            af.download_original('token', self.output, opener=fake)
        self.assertFalse(self.output.exists())

    def test_bad_source_lock_refuses_before_network(self):
        fake = FakeOpener()
        with self.assertRaisesRegex(ValueError, 'source lock'):
            af.download_original('token', self.output, expected_sha='1'*64, opener=fake)
        self.assertEqual(fake.calls, [])

    def test_missing_token_refuses_before_network(self):
        fake = FakeOpener()
        with self.assertRaisesRegex(ValueError, 'authentication'):
            af.download_original('', self.output, opener=fake)
        self.assertEqual(fake.calls, [])

    def test_invalid_repos_refuse(self):
        for repo in ('other/repo', af.REPO + '/other', 'http://evil.example'):
            with self.subTest(repo=repo):
                with self.assertRaises(ValueError):
                    af.download_original('token', self.output, repo=repo, opener=FakeOpener())

    def test_wrong_artifact_id_refuses(self):
        with self.assertRaises(ValueError):
            af.download_original('token', self.output, artifact_id=123, opener=FakeOpener())

    def test_untrusted_redirect_urls(self):
        values = ['http://productionresultssa0.blob.core.windows.net/a?sig=x',
                  'https://evil.blob.core.windows.net.attacker.test/a?sig=x',
                  'https://evil.example/a?sig=x',
                  'https://user:pw@productionresultssa0.blob.core.windows.net/a?sig=x',
                  'https://productionresultssa0.blob.core.windows.net:444/a?sig=x',
                  'https://productionresultssa0.blob.core.windows.net/a',
                  'https://productionresultssa0.blob.core.windows.net/a?sig=x#fragment',
                  'https://productionresultssa0.blob.core.windows.net/a?sig=x\r\nsecret',
                  'file:///tmp/secret?sig=x', '', None]
        for s in values:
            with self.subTest(s=s):
                with self.assertRaises(ValueError):
                    af.signed_blob_location(s)

    def test_blob_host_allowlist(self):
        for s in [GOOD, 'https://foo.actions.githubusercontent.com/x?sig=a']:
            self.assertEqual(af.signed_blob_location(s), s)

    def test_api_401_is_distinguished_and_fails_closed(self):
        fake = FakeOpener(status=401)
        with self.assertRaisesRegex(ValueError, 'HTTP 401'):
            af.download_original('token', self.output, opener=fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(self.output.exists())

    def test_second_redirect_fails_closed(self):
        fake = FakeOpener(redirect_again=True)
        with self.assertRaisesRegex(ValueError, 'HTTP 302'):
            af.download_original('token', self.output, opener=fake)
        self.assertFalse(self.output.exists())

    def test_blobs_over_limit_are_rejected(self):
        fake = FakeOpener(blob=b'x' * (af.MAX_BYTES+1))
        with self.assertRaises(ValueError):
            af.download_original('token', self.output, opener=fake)
        self.assertFalse(self.output.exists())

    def test_create_only_output_never_overwrites(self):
        self.output.write_bytes(b'old')
        fake = FakeOpener()
        with self.assertRaises(FileExistsError):
            af.download_original('token', self.output, opener=fake)
        self.assertEqual(self.output.read_bytes(), b'old')
        self.assertEqual(fake.calls, [])

    def test_symlink_destination_never_used(self):
        original=Path(self.directory.name)/'other'
        original.write_text('private')
        self.output.symlink_to(original)
        with self.assertRaises(FileExistsError):
            af.download_original('token', self.output, opener=FakeOpener())
        self.assertEqual(original.read_text(), 'private')

    def test_redirect_handler_disallows_transitive_redirect(self):
        hand = af._NoRedirect()
        req = urllib.request.Request('https://api.github.com/something', method='GET')
        self.assertIsNone(hand.redirect_request(req, None, 302, 'moved', {'Location': GOOD}, GOOD))

    def test_no_signed_get_on_invalid_redirect(self):
        fake = FakeOpener(location='https://evil.example/blob?sig=abc')
        with self.assertRaises(ValueError):
            af.download_original('token', self.output, opener=fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
