"""Synthetic release/rc tests only: no downloads, native programs, or real home writes."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.request

import a32_sshsig_bazel as bazel
from a32_sshsig_guard import digest


class FixedBazelTests(unittest.TestCase):
    def asset(self, platform):
        raw = (b'\x7fELF' if platform == 'linux' else b'MZ') + b'synthetic, not executable'
        return raw, {'name': bazel.ASSETS[platform]['name'], 'bytes': len(raw), 'sha256': digest(raw)}

    def test_bounded_exact_release_size_digest_and_host_formats(self):
        for platform in ('linux', 'win32'):
            raw, asset = self.asset(platform)
            with patch.dict(bazel.ASSETS, {platform: asset}):
                opener = Mock(return_value=io.BytesIO(raw))
                data, receipt = bazel.payload(platform, opener)
                self.assertEqual(data, raw); self.assertEqual(receipt['sha256'], digest(raw))
                self.assertEqual(opener.call_args.kwargs, {'timeout': 120})
                for bad in (raw[:-1], raw + b'x', b'!' + raw[1:]):
                    with self.assertRaisesRegex(RuntimeError, 'size/hash'):
                        bazel.payload(platform, lambda *args, **kwargs: io.BytesIO(bad))
        with self.assertRaisesRegex(RuntimeError, 'unsupported'):
            bazel.payload('darwin', Mock())

    def test_redirects_are_only_https_official_release_hosts(self):
        handler = bazel.ReleaseRedirects(); request = urllib.request.Request('https://github.com/start')
        for url in ('http://github.com/a', 'https://evil.example/a', 'https://user@github.com/a', 'https://github.com:444/a'):
            with self.assertRaisesRegex(RuntimeError, 'release redirect'):
                handler.redirect_request(request, None, 302, 'redirect', {}, url)
        result = handler.redirect_request(request, None, 302, 'redirect', {}, 'https://release-assets.githubusercontent.com/file')
        self.assertEqual(result.full_url, 'https://release-assets.githubusercontent.com/file')

    def test_rc_preserves_linux_and_windows_exact_old_action_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); home = root / 'home'; other = root / 'HOME'; home.mkdir(); other.mkdir()
            (home / '.bazelrc').write_bytes(b'old config, not retained in plaintext')
            for platform, env, count in (('linux', {'HOME': str(other)}, 1), ('win32', {'HOME': str(other)}, 2),
                                         ('win32', {'HOME': str(home)}, 1)):
                rows = bazel.configure(root / 'a32-b/o', platform, env, home)
                self.assertEqual(len(rows), count)
                expected = ('startup --output_base=' + str(root / 'a32-b/o') + '\n').encode()
                for row in rows:
                    self.assertEqual(Path(row['path']).read_bytes(), expected)
                    self.assertEqual(row['sha256'], digest(expected))
                    self.assertNotIn('contents', row)

    def test_rc_rejects_linked_objects_and_unsupported_whitespace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); target = root / '.bazelrc'; original = root / 'other'; original.write_bytes(b'preserve')
            os.link(original, target)
            with self.assertRaisesRegex(RuntimeError, 'shared'):
                bazel.configure(root / 'o', 'linux', {}, root)
            self.assertEqual(original.read_bytes(), b'preserve'); target.unlink()
            with self.assertRaisesRegex(RuntimeError, 'whitespace'):
                bazel.configure(root / 'spaces not supported', 'linux', {}, root)
            self.assertFalse(target.exists())

    def test_installer_uses_owned_runner_outside_source_and_evidence_then_binds_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source'; evidence = root / 'evidence'; home = root / 'home'
            source.mkdir(); evidence.mkdir(); home.mkdir(); (root / 'a32-b/o').mkdir(parents=True)
            raw, asset = self.asset('linux')
            q = Mock(root=source, evidence=evidence, state={'runner_arch': 'X64'})
            q.run.return_value = b'bazel 9.3.0\n'
            env = {'RUNNER_TEMP': str(root), 'BAZEL_OUTPUT_BASE': str(root / 'a32-b/o'), 'GITHUB_PATH': str(root / 'path')}
            with patch.dict(os.environ, env), patch.object(bazel.sys, 'platform', 'linux'), patch.object(bazel.Path, 'home', return_value=home), patch.dict(bazel.ASSETS, {'linux': asset}), patch.object(bazel, 'payload', return_value=(raw, {'url': 'synthetic', **asset})):
                bazel.install(q)
                binary = root / 'a32-b/bazel-bin/bazel'
                q.run.assert_called_once_with('install-bazel-version', [str(binary), '--version'])
                self.assertEqual(binary.read_bytes(), raw)
                self.assertFalse(any(path.name == 'bazel' for path in evidence.rglob('*')))
                with patch.object(bazel.shutil, 'which', return_value=str(binary)):
                    bazel.verify_installation(q)
                    binary.write_bytes(raw + b'changed')
                    with self.assertRaisesRegex(RuntimeError, 'payload changed'):
                        bazel.verify_installation(q)
                with patch.object(bazel.shutil, 'which', return_value=str(root / 'other-bazel')):
                    with self.assertRaisesRegex(RuntimeError, 'PATH'):
                        bazel.verify_installation(q)
                with self.assertRaises(FileExistsError):
                    bazel.install(q)
                q.run.assert_called_once()
                record = json.loads((evidence / 'bazel-installation.json').read_bytes())
                self.assertTrue(record['binary_rechecked_after_version']); self.assertFalse(record['bazelisk_used'])


if __name__ == '__main__':
    unittest.main()
