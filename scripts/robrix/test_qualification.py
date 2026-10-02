"""Guard against counting compile-only, empty, skipped or failed tests as execution."""
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import qualify
from browser_test_runner import passing_summary
from x11_title import decode_title
from makepad_test_bridge import patch_test_glue, load_pinned_bridge, glue_shape


class TestExecutionGate(unittest.TestCase):
    def check(self, output, minimum=4):
        with patch.object(qualify, 'run', return_value=output):
            qualify.checked_tests(['not-executed'], 'unused', minimum)

    def test_executed_tests_pass(self):
        self.check('test result: ok. 4 passed; 0 failed; 0 ignored; 12 filtered out')

    def test_compile_only_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('Finished `test` profile. Executable app.wasm')

    def test_zero_tests_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: ok. 0 passed; 0 failed; 0 ignored; 19 filtered out')

    def test_missing_required_count_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: ok. 3 passed; 0 failed; 0 ignored')

    def test_ignored_tests_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: ok. 4 passed; 0 failed; 1 ignored')

    def test_failed_tests_rejected(self):
        with self.assertRaises(AssertionError):
            self.check('test result: FAILED. 4 passed; 1 failed; 0 ignored')

    def test_failed_process_keeps_partial_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(qualify, 'OUT', Path(directory)):
                with self.assertRaises(subprocess.CalledProcessError):
                    qualify.run([sys.executable, '-c', 'print("partial evidence"); raise SystemExit(7)'],
                                log='failure.log')
                self.assertEqual((Path(directory) / 'failure.log').read_text(), 'partial evidence\n')

    def test_nonzero_process_rejected(self):
        with patch.object(qualify, 'run', side_effect=subprocess.CalledProcessError(1, 'test')):
            with self.assertRaises(subprocess.CalledProcessError):
                qualify.checked_tests(['not-executed'], 'unused', 1)


class TestNativeWindowIdentity(unittest.TestCase):
    def test_unique_resource_instance_and_exact_title_are_required(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(qualify.subprocess, 'run', return_value=Mock(returncode=0, stdout='42\n')) as search:
            with patch.object(qualify, 'read_title', return_value={'title': qualify.FIXTURE_TITLE}):
                with patch.object(Path, 'write_text'):
                    self.assertEqual(qualify.select_fixture_window(process, 'unique-fixture'), '42')
        self.assertEqual(search.call_args.args[0], ['xdotool', 'search', '--onlyvisible',
                                                   '--classname', r'^unique\-fixture$'])

    def test_duplicate_identity_is_rejected(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(qualify.subprocess, 'run', return_value=Mock(returncode=0, stdout='42\n43\n')):
            with self.assertRaisesRegex(RuntimeError, 'Multiple'):
                qualify.select_fixture_window(process, 'fixture')

    def test_dead_process_is_rejected_before_matching_a_window(self):
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            qualify.select_fixture_window(process, 'fixture')

    def test_unrelated_title_cannot_be_accepted(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(qualify.time, 'monotonic', side_effect=[0, 1, 61]):
            with patch.object(qualify.time, 'sleep'):
                with patch.object(qualify.subprocess, 'run', return_value=Mock(returncode=0, stdout='42\n')):
                    with patch.object(qualify, 'read_title', return_value={'title': 'Unrelated app'}):
                        with patch.object(Path, 'write_text'):
                            with self.assertRaisesRegex(RuntimeError, 'exact fixture title'):
                                qualify.select_fixture_window(process, 'fixture')


class TestBrowserCompletion(unittest.TestCase):
    def test_success_requires_executed_nonignored_tests(self):
        self.assertTrue(passing_summary('test result: ok. 13 passed; 0 failed; 0 ignored;'))
        for output in ['Loading scripts...', 'test result: ok. 0 passed; 0 failed; 0 ignored;',
                       'test result: ok. 12 passed; 0 failed; 1 ignored;',
                       'test result: FAILED. 12 passed; 1 failed; 0 ignored;']:
            self.assertFalse(passing_summary(output))


class TestX11TitleEncoding(unittest.TestCase):
    def test_declared_string_and_utf8_encodings_preserve_the_exact_title(self):
        title = qualify.FIXTURE_TITLE
        self.assertEqual(decode_title('STRING', title.encode('latin-1')), title)
        self.assertEqual(decode_title('UTF8_STRING', title.encode('utf-8')), title)

    def test_invalid_utf8_is_never_replaced_for_acceptance(self):
        with self.assertRaises(UnicodeDecodeError):
            decode_title('UTF8_STRING', b'Hepta \xb7 UI fixture')

    def test_unsupported_title_encoding_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_title('COMPOUND_TEXT', b'Hepta')


class TestRealMakepadAdapter(unittest.TestCase):
    GLUE = """import * as import0 from "env";
function __wbg_get_imports() { return {
    "env": import0,
}; }
function __wbg_finalize_init(instance, module) {
    return wasm;
}
function initSync(module) {
    const imports = __wbg_get_imports();
}
async function __wbg_init(module_or_path) {
    const imports = __wbg_get_imports();
}
export { initSync, __wbg_init as default };
"""

    def test_adapter_uses_real_bridge_and_original_wasm_exports(self):
        patched = patch_test_glue(self.GLUE)
        self.assertIn('new WasmBridge(instance, {})', patched)
        self.assertIn('const set_wasm = init_env(env)', patched)
        self.assertIn('return instance.exports', patched)
        self.assertNotIn('from "env"', patched)
        self.assertEqual(patch_test_glue(self.GLUE.replace('from "env";', 'from "env"')), patched)

    def test_multiple_real_env_imports_have_a_complete_bijection(self):
        source = self.GLUE.replace('import * as import0 from "env";',
                                  'import * as import0 from "env"\nimport * as import1 from "env"')
        source = source.replace('"env": import0,', '"env": import0,\n    "env": import1,')
        source = 'import * as other from "other_module";\n' + source
        source = source.replace('"env": import0,', '"other_module": other,\n    "env": import0,')
        patched = patch_test_glue(source)
        self.assertIn('import * as other from "other_module";', patched)
        self.assertIn('"other_module": other,', patched)
        self.assertNotIn('from "env"', patched)
        self.assertEqual(glue_shape(source)['envSyntaxCount'], 4)
        with self.assertRaises(ValueError):
            patch_test_glue(source.replace('"env": import1,', '"env": wrong_alias,'))
        with self.assertRaises(ValueError):
            patch_test_glue(source.replace('import1', 'import0'))

    def test_glue_drift_fails_closed(self):
        for changed in [self.GLUE.replace('"env": import0,', ''),
                        self.GLUE.replace('__wbg_init(module_or_path)', '__wbg_init(changed)'),
                        self.GLUE.replace('return wasm;', 'return changed;'),
                        self.GLUE + 'import * as duplicate from "env";\n']:
            with self.assertRaises(ValueError):
                patch_test_glue(changed)

    def test_bridge_hash_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ['libs/wasm_bridge/src/wasm_bridge.js', 'tools/cargo_makepad/src/wasm/compile.rs']:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('untrusted drift')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_pinned_bridge(root)


if __name__ == '__main__':
    unittest.main()
