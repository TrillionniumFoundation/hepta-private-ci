"""Historical Mac closure corpus and synthetic SSHSIG owner/identity regressions."""
import base64
import gzip
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

import a32_sshsig_closure as closure
from a32_sshsig_guard import digest, MANIFEST, save
import a32_sshsig_qualification as controller

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / '.github/fixtures/a32-sshsig-qualification/macos-v2-configured-labels.json'
OWNERS = ['//codex-rs/utils/path-utils:path-utils-unit-tests', '//codex-rs/state:state-unit-tests',
          '//codex-rs/hepta-memory:hepta-memory-unit-tests',
          '//codex-rs/hepta-operator-acceptance:hepta-operator-acceptance-tests']
BASE = ('\n'.join(OWNERS) + '\n').encode()
UUID = '@@rules_rs++crate+crates__uuid-1.28.0//:src/v8.rs'


class ClosureTests(unittest.TestCase):
    def test_complete_actual_mac_exec_corpus_is_not_sshsig_native_qualification(self):
        fixture = json.loads(FIXTURE.read_bytes())
        self.assertEqual(fixture['source_log_sha256'], '13e652e4d18b802b444e908b27c8a798fbc568d3edf43e276bb19db0fa23b364')
        self.assertEqual(fixture['source_log_bytes'], 4735922)
        compressed = base64.b64decode(''.join(fixture['gzip_base64_chunks']), validate=True)
        self.assertEqual(len(compressed), fixture['gzip_bytes']); self.assertEqual(digest(compressed), fixture['gzip_sha256'])
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(3905771)
            self.assertEqual(stream.read(1), b'')
        self.assertEqual(len(raw), 3905770); self.assertEqual(fixture['labels_bytes'], len(raw))
        self.assertEqual(digest(raw), '0d2e591797e982b71d6304a89c4339951a3c2f07f268a357dcd04a90280ee1f1')
        self.assertEqual(fixture['labels_sha256'], digest(raw))
        labels = closure.validate_closure(raw, fixture['mac_owners'])
        self.assertEqual(len(labels), 47631); self.assertEqual(fixture['labels_count'], len(labels))
        self.assertEqual(raw, ('\n'.join(labels) + '\n').encode()); self.assertIn(UUID, labels)
        old = re.compile(r'(^|[/@_+:~.-])(?:rusty_)?v8(?:[/_:~+.-]|$)|//codex-rs/(?:core|cli|code-mode|code_mode|v8-poc)(?:/|:)', re.I)
        self.assertEqual([label for label in labels if old.search(label)], [UUID])
        with self.assertRaisesRegex(RuntimeError, 'owner missing'):
            closure.validate_closure(raw, OWNERS)

    def test_exact_current_sshsig_owner_sets_and_every_missing_owner_rejects(self):
        manifest = json.loads((ROOT / MANIFEST).read_bytes())
        for platform in ('linux', 'windows'):
            self.assertEqual(manifest['bazel_targets'][platform], OWNERS)
            self.assertEqual(closure.validate_closure(BASE + UUID.encode(), OWNERS), sorted([*OWNERS, UUID]))
            for absent in OWNERS:
                raw = ('\n'.join(owner for owner in OWNERS if owner != absent) + '\n' + UUID).encode()
                with self.subTest(platform=platform, absent=absent), self.assertRaisesRegex(RuntimeError, 'owner missing'):
                    closure.validate_closure(raw, manifest['bazel_targets'][platform])

    def test_source_filenames_do_not_supply_repository_package_or_rule_identity(self):
        for label in (UUID, '@uuid//:v8.rs', '@uuid//:src/v8_helpers.rs', '@aes//:src/armv8.rs', '@ring//:asm/armv8.S'):
            with self.subTest(label=label):
                self.assertIn(label, closure.validate_closure(BASE + label.encode(), OWNERS))

    def test_v8_repository_and_package_identities_reject_source_target_names(self):
        repositories = ['@v8', '@@v8+', '@rusty_v8', '@rusty-v8', '@rustyv8',
                        '@@rules_rs++crate+crates__v8-0.142.0', '@@rules_rs++crate+crates__rusty_v8-150.4.0',
                        '@@rules_rs++crate+crates__rusty-v8-150.4.0', '@v8_crate_150_4_0',
                        '@rusty_v8_150_4_0_aarch64_apple_darwin_archive', '@@_main~extension~v8',
                        '@rusty_v8_libcxx', '@rusty_v8_libcxxabi', '@rusty_v8_llvm_libc']
        labels = [repo + '//:src/v8.rs' for repo in repositories]
        labels += ['//third_party/v8:binding_150_4_0.cc', '//third_party/v8/libcxx_config:__config_site',
                   '@@main//vendor/rusty-v8/src:lib.rs', '//codex-rs/v8-poc/src:lib.rs']
        for label in labels:
            with self.subTest(label=label), self.assertRaisesRegex(RuntimeError, 'stop, do not prune'):
                closure.validate_closure(BASE + label.encode(), OWNERS)

    def test_v8_rules_and_archives_reject(self):
        names = ['v8', 'rusty_v8', 'rusty-v8', 'rustyv8', 'v8_build_script', 'build_v8', 'v8-150.4.0',
                 'v8_150_4_0_aarch64_apple_darwin_bazel', 'rusty_v8_archive_for_target',
                 'librusty_v8.a', 'libv8.so', 'v8.dll', 'rusty_v8.lib', 'v8.dylib']
        for name in names:
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'unreviewed V8'):
                closure.validate_closure(BASE + ('//unrelated:dir/' + name).encode(), OWNERS)

    def test_core_cli_code_mode_and_explicit_host_packages_reject_nested_and_qualified(self):
        for repository in ('', '@@main', '@other'):
            for package in ('core', 'cli', 'code-mode', 'code_mode', 'code-mode-host', 'code_mode_host', 'v8-poc'):
                for child in ('', '/tests/common', '/tests/remote_env_windows'):
                    label = repository + '//codex-rs/' + package + child + ':source.rs'
                    with self.subTest(label=label), self.assertRaisesRegex(RuntimeError, 'unreviewed V8/full-CLI'):
                        closure.validate_closure(BASE + label.encode(), OWNERS)

    def test_malformed_configured_labels_reject(self):
        for label in ('@v8', '//:v8:extra', '@@bad/repo//:target', '//missing-target', '//:'):
            with self.subTest(label=label), self.assertRaisesRegex(RuntimeError, 'malformed'):
                closure.validate_closure(BASE + label.encode(), OWNERS)

    def test_controller_graph_calls_checked_helper_before_aquery_or_analysis(self):
        for platform in ('linux', 'win32'):
            with tempfile.TemporaryDirectory() as temporary:
                q = object.__new__(controller.Qualification)
                q.evidence = Path(temporary); q.state = {}; q.flush = Mock()
                save(q.evidence / 'source-manifest.json', {'bazel_targets': {'linux': OWNERS, 'windows': OWNERS}})
                # This is synthetic SSHSIG data, not the historical Mac closure.
                raw = BASE + UUID.encode()
                q.run = Mock(side_effect=[raw, RuntimeError('stop after admitted closure')])
                with patch.object(controller.sys, 'platform', platform), patch.object(closure, 'validate_closure', wraps=closure.validate_closure) as checked:
                    with self.assertRaisesRegex(RuntimeError, 'stop after admitted closure'):
                        q.graph()
                    checked.assert_called_once_with(raw, OWNERS)
                self.assertEqual([call.args[0] for call in q.run.call_args_list], ['configured-cquery', 'configured-aquery'])
                rejected = BASE + b'//codex-rs/code-mode-host:src/lib.rs'
                q.run = Mock(return_value=rejected)
                with patch.object(controller.sys, 'platform', platform), self.assertRaisesRegex(RuntimeError, 'unreviewed V8/full-CLI'):
                    q.graph()
                self.assertEqual([call.args[0] for call in q.run.call_args_list], ['configured-cquery'])


if __name__ == '__main__':
    unittest.main()
