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
from package_resources import CORE_ASSETS, package_inventory, validate_pinned_resources, verify_relative_urls, patch_packager
from stage_evidence import stage


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


class TestEvidenceUploadScope(unittest.TestCase):
    def test_compiled_tool_and_fonts_are_hashed_but_never_uploaded(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "input", root / "output"
            (source / "makepad-tool/bin").mkdir(parents=True)
            (source / "makepad-tool/bin/cargo-makepad").write_bytes(
                b"\x7fELF\0executable"
            )
            (source / "font.ttf").write_bytes(b"\0font")
            (source / "partial.log").write_text("build failed\n")
            (source / "identity.json").write_text('{"candidate":"fixture"}')
            (source / "framework.patch").write_text("diagnostic patch\n")
            Image.new("RGB", (2, 2), "white").save(source / "fixture.png")
            receipt = stage(source, target)
            self.assertEqual(
                set(receipt["excluded"]), {"makepad-tool/bin/cargo-makepad", "font.ttf"}
            )
            self.assertEqual(
                {p.name for p in target.iterdir()},
                {
                    "partial.log",
                    "identity.json",
                    "framework.patch.log",
                    "fixture.png",
                    "upload-scope.json",
                },
            )
            self.assertEqual(
                (target / "framework.patch.log").read_bytes(),
                (source / "framework.patch").read_bytes(),
            )

    def test_binary_masquerading_as_text_and_symlinks_are_rejected(self):
        for kind in ("binary", "symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "input"
                source.mkdir()
                if kind == "binary":
                    (source / "fake.log").write_bytes(b"\x7fELF\0payload")
                else:
                    (source / "fake.log").symlink_to(Path(directory) / "unread-target")
                with self.assertRaises(ValueError):
                    stage(source, Path(directory) / "output")


class TestLoginPixelGate(unittest.TestCase):
    def test_unpainted_footer_and_stale_font_centering_are_rejected(self):
        from PIL import Image, ImageDraw
        from render_checks import login_pixels

        for defect in ("none", "transparent-footer", "stale-font"):
            image = Image.new("RGB", (520, 760), (226, 226, 226))
            draw = ImageDraw.Draw(image)
            draw.rectangle(
                (0, 732, 519, 759),
                fill="white" if defect != "transparent-footer" else "black",
            )
            draw.rectangle((8, 739, 85, 748), fill=(102, 102, 102))
            for top, bottom in ((198, 230), (251, 283), (304, 324)):
                draw.rectangle((123, top, 396, bottom), fill="white")
                y = (top + bottom) // 2 - 4 + (8 if defect == "stale-font" else 0)
                draw.rectangle((135, y, 175, y + 8), fill=(187, 187, 187))
            if defect == "none":
                self.assertGreater(login_pixels(image)["footerContrast"], 4.5)
            else:
                with self.assertRaises(AssertionError):
                    login_pixels(image)


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


class TestActualPackageResources(unittest.TestCase):
    def test_unpinned_minifier_source_is_rejected(self):
        from resource_transform import minifier_source
        with self.assertRaisesRegex(ValueError, 'source hash drift'):
            minifier_source('fn minify_js(input: &str) -> String { input.into() }')

    def populate(self, root):
        for name in ['index.html', 'bindgen.js', 'robrix.wasm', *CORE_ASSETS]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')

    def test_missing_makepad_bootstrap_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.populate(root)
            (root / CORE_ASSETS[0]).unlink()
            with self.assertRaisesRegex(ValueError, 'Missing'):
                package_inventory(root)

    def test_actual_relative_resource_urls_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.populate(root)
            (root / 'index.html').write_text("import('./makepad_platform/web_gl.js');")
            (root / 'makepad_platform/web_gl.js').write_text('import { WasmWebBrowser } from "./web.js";')
            (root / 'makepad_platform/web.js').write_text('import { WasmBridge } from "../makepad_wasm_bridge/wasm_bridge.js";')
            self.assertEqual(len(verify_relative_urls(root)), 3)
            (root / 'makepad_platform/web.js').write_text('import { Missing } from "./wrong-root.js";')
            with self.assertRaisesRegex(ValueError, 'packaged URL'):
                verify_relative_urls(root)

    def test_escaping_resource_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.populate(root)
            (root / 'index.html').write_text("import('../outside.js');")
            with self.assertRaisesRegex(ValueError, 'escaping'):
                verify_relative_urls(root)

    def test_packager_source_hash_drift_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hash drift'):
            patch_packager('altered upstream source')

    def test_resource_bytes_must_match_both_pinned_and_compiled_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package, source, compiled = root / 'package', root / 'source', root / 'compiled'
            self.populate(package)
            names = ['audio_worklet.js', 'web_gl.js', 'web_worker.js', 'web.js', 'auto_reload.js', 'full_canvas.css']
            pairs = [('makepad_wasm_bridge/wasm_bridge.js', 'libs/wasm_bridge/src/wasm_bridge.js', b'')]
            pairs += [('makepad_platform/' + name, 'platform/src/os/web/' + name,
                       b"import init from '../bindgen.js';\n" if name == 'web_worker.js' else b'') for name in names]
            for destination, original, prefix in pairs:
                for base in [source, compiled]:
                    path = base / original
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'exact dependency asset')
                target = package / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(prefix + b'exact dependency asset')
            self.assertEqual(len(validate_pinned_resources(package, source, compiled)['verifiedResources']), 7)
            (compiled / 'platform/src/os/web/web_gl.js').write_bytes(b'changed compiled source')
            with self.assertRaisesRegex(ValueError, 'differs'):
                validate_pinned_resources(package, source, compiled)


class TestFrameworkCompatibility(unittest.TestCase):
    def test_changed_framework_source_cannot_be_patched(self):
        import framework_compat
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in framework_compat.BEFORE:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('changed upstream source')
            with self.assertRaisesRegex(ValueError, 'source hash drift'):
                framework_compat.apply(root)

    def test_unknown_reporter_shape_is_rejected(self):
        from framework_compat import local_reporter
        with self.assertRaisesRegex(ValueError, 'shape drift'):
            local_reporter('altered upstream reporter')


if __name__ == '__main__':
    unittest.main()
