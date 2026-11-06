"""Bounded local controls; no actual credentials, network, source repo or ref writes."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transport = load('run_archive_transport')
bridge = load('credential_get_only')


class TransportControls(unittest.TestCase):
    def test_origin_scope_rejects_embedded_credentials_and_different_destinations(self):
        for value in ('https://github.com/TrillionniumFoundation/hepta-private-ci.git',
                      'https://github.com:443/TrillionniumFoundation/hepta-private-ci'):
            self.assertTrue(transport.origin_matches(value))
        for value in ('https://fixture-user:fixture-secret@github.com/TrillionniumFoundation/hepta-private-ci.git',
                      'https://github.com/TrillionniumFoundation/other.git',
                      'https://other.example/TrillionniumFoundation/hepta-private-ci.git',
                      'https://github.com:9443/TrillionniumFoundation/hepta-private-ci.git',
                      'ssh://git@github.com/TrillionniumFoundation/hepta-private-ci.git',
                      'git@github.com:TrillionniumFoundation/hepta-private-ci.git',
                      'ssh://other@github.com/TrillionniumFoundation/hepta-private-ci.git',
                      'https://github.com/TrillionniumFoundation/hepta-private-ci.git?redirect=x'):
            self.assertFalse(transport.origin_matches(value))

    def test_get_only_bridge_never_approves_or_erases_and_preserves_scope(self):
        fixture = b'username=fixture-user\npassword=fixture-secret\n\n'
        environ = {'HEPTA_TRANSPORT_ORIGIN': 'https://github.com/TrillionniumFoundation/hepta-private-ci.git',
                   'HEPTA_TRANSPORT_ORIGINAL_GIT_CONFIG_ENV': '{}'}
        request = b'protocol=https\nhost=github.com\npath=TrillionniumFoundation/hepta-private-ci.git\n\n'
        for action in ('store', 'erase', 'get'):
            output = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
            with mock.patch.object(sys, 'argv', ['bridge', action]), \
                    mock.patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(request), encoding='utf-8')), \
                    mock.patch.object(sys, 'stdout', output), \
                    mock.patch.dict(os.environ, environ, clear=True), \
                    mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, fixture, b'')) as call:
                self.assertEqual(bridge.main(), 0)
                if action == 'get':
                    self.assertEqual(call.call_args.args[0], ['git', '-C', bridge.SOURCE, 'credential', 'fill'])
                    self.assertEqual(output.buffer.getvalue(), fixture)
                    self.assertEqual(call.call_args.kwargs['timeout'], 15)
                else:
                    call.assert_not_called()
                    self.assertEqual(output.buffer.getvalue(), b'')
        with mock.patch.object(sys, 'argv', ['bridge', 'get']), \
                mock.patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(request.replace(b'github.com', b'other.example')), encoding='utf-8')), \
                mock.patch.object(subprocess, 'run') as call:
            self.assertEqual(bridge.main(), 1)
            call.assert_not_called()

    def test_expected_hash_and_unapproved_plan_reject_before_transport_constructor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            script_sha = hashlib.sha256((HERE / 'run_archive_transport.py').read_bytes()).hexdigest()
            path.write_text(json.dumps({'frozen': False, 'publication_authorized': False, 'script_sha256': script_sha}))
            plan_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            for supplied_sha in ('0' * 64, plan_sha):
                with mock.patch.object(sys, 'argv', ['runner', '--plan', str(path), '--expected-plan-sha256', supplied_sha,
                                                     '--expected-script-sha256', script_sha]), \
                        mock.patch.object(transport, 'Transport') as constructor:
                    with self.assertRaises(AssertionError):
                        transport.main()
                    constructor.assert_not_called()

    def test_inherited_hooks_require_review_without_override(self):
        item = transport.Transport({})
        with tempfile.TemporaryDirectory() as directory:
            item.repo = Path(directory)
            for configured in (b'/fixture/mandatory-hooks\n', b' \n', b'\n'):
                with mock.patch.object(item, 'command', return_value=configured) as command:
                    with self.assertRaises(AssertionError):
                        item.require_no_unreviewed_hooks()
                    self.assertNotIn('/dev/null', str(command.call_args))
            with mock.patch.object(item, 'command', return_value=b''):
                (item.repo / 'hooks').mkdir()
                (item.repo / 'hooks' / 'pre-push').write_text('fixture hook must not execute')
                with self.assertRaises(AssertionError):
                    item.require_no_unreviewed_hooks()

    def test_real_git_urlmatch_format_and_fixed_original_part_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / 'fixture-config'
            config.write_text('[http "https://github.com/"]\n\textraHeader = Authorization: fixture-placeholder\n')
            result = subprocess.run(['git', 'config', '--file', str(config), '--null', '--get-urlmatch', 'http',
                                     'https://github.com/TrillionniumFoundation/hepta-private-ci.git'],
                                    env=dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null'),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=True)
            self.assertEqual(result.stdout, b'http.extraheader\nAuthorization: fixture-placeholder\0')
            part = root / 'actual.part-0000'
            part.write_bytes(bytes(range(256)))
            raw, observed = transport.read_source(part, expected_bytes=256,
                expected_sha=hashlib.sha256(part.read_bytes()).hexdigest(), limit=4194304)
            self.assertEqual(raw, bytes(range(256)))
            self.assertEqual(observed['bytes'], 256)
            with self.assertRaises(AssertionError):
                transport.read_source(part, expected_sha='0' * 64)
            link = root / 'alias'
            link.symlink_to(part)
            with self.assertRaises(OSError):
                transport.read_source(link)


if __name__ == '__main__':
    unittest.main(verbosity=2)
