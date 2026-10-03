#!/usr/bin/env python3
"""Exact-source, account-free Robrix qualification. No publishing or account access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import tomllib
import time
import sys
from x11_title import read_title
from package_resources import patch_packager, compiled_resource_root, package_inventory, validate_pinned_resources

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'apps/hepta-robrix'
OUT = Path(os.environ.get('ROBRIX_EVIDENCE', ROOT / 'robrix-evidence')).resolve()
MAKEPAD = '493d23a7630f487d29912dd73f2cbb5b639b74ca'


def run(args, *, cwd=APP, log=None, env=None, timeout=None):
    if log:
        # Keep partial diagnostics when the hosted job is cancelled or times out.
        with (OUT / log).open('w') as receipt:
            process = subprocess.Popen(args, cwd=cwd, env=env, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = []
            for line in process.stdout:
                print(line, end='', flush=True)
                receipt.write(line)
                receipt.flush()
                output.append(line)
            process.stdout.close()
            status = process.wait(timeout=timeout)
        if status:
            raise subprocess.CalledProcessError(status, args)
        return ''.join(output)
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    print(result.stdout, end='', flush=True)
    result.check_returncode()
    return result.stdout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity():
    upstream = json.loads((APP / 'UPSTREAM_PROVENANCE.json').read_text())
    deps = json.loads((APP / 'HEPTA_DEPENDENCY_PROVENANCE.json').read_text())
    assert upstream['commit'] == '2e9194caddb842eb9697d6dfa774c398ddea25d0'
    assert upstream['tree'] == '7b66458e9cc161cf7a4312ec0960c6f22c62cd3f'
    assert deps['makepad']['commit'] == MAKEPAD
    assert deps['matrix_sdk']['version'] == '0.19.1'
    locked = tomllib.loads((APP / 'Cargo.lock').read_text())['package']
    assert any(p['name'] == 'matrix-sdk' and p['version'] == '0.19.1' for p in locked)
    assert all(p.get('source', '').endswith('#' + MAKEPAD) for p in locked if p['name'] in ('makepad-widgets', 'makepad-code-editor'))
    assert not (APP / '.github').exists(), 'Upstream administration automation is forbidden'
    for name, expected in upstream['files_sha256'].items():
        if name == 'LICENSE-MIT' or name.startswith('licenses/'):
            assert digest(APP / name) == expected, f'Upstream license drift: {name}'
    data = {'schema': 1, 'candidate': run(['git', 'rev-parse', 'HEAD']).strip(),
            'tree': run(['git', 'rev-parse', 'HEAD^{tree}']).strip(),
            'appTree': run(['git', 'rev-parse', 'HEAD:apps/hepta-robrix']).strip(),
            'cargoLockSha256': digest(APP / 'Cargo.lock'),
            'upstream': {k: upstream[k] for k in ('commit', 'tree', 'upstream')},
            'makepadFrameworkPatchSha256': digest(ROOT / 'scripts/robrix/patches/makepad-493d23a-web-startup.patch'),
            'makepad': MAKEPAD, 'matrixSdk': '0.19.1', 'fixture': True,
            'liveAccounts': False, 'securityQualification': False,
            'installedAcceptance': False,
            'licenseScope': 'Preserved upstream notices; not a refreshed dependency license audit',
            'preservedLicenseSha256': {name: digest(APP / name) for name in upstream['files_sha256']
                                       if name == 'LICENSE-MIT' or name.startswith('licenses/')},
            'nativeCompiler': run(['rustc', '+1.96.0', '-Vv']).strip(),
            'webCompiler': run(['rustc', '+nightly-2026-10-01', '-Vv']).strip()}
    assert not run(['git', 'status', '--porcelain', '--untracked-files=no']).strip(), 'Dirty tracked source'
    (OUT / 'source-identity.json').write_text(json.dumps(data, indent=2) + '\n')


def checked_tests(args, log, minimum):
    output = run(args, log=log)
    summaries = re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored', output)
    assert summaries, 'No executed test summary; compilation is not qualification'
    assert sum(int(row[0]) for row in summaries) >= minimum, 'Missing expected test execution'
    assert all(row[1:] == ('0', '0') for row in summaries), 'Failed or ignored tests'


def framework_compat():
    from framework_compat import apply
    metadata = json.loads(subprocess.check_output(['cargo', '+nightly-2026-10-01', 'metadata',
        '--locked', '--format-version', '1', '--filter-platform', 'wasm32-unknown-unknown',
        '--features', 'ui-fixture'], cwd=APP, text=True))
    source = compiled_resource_root(metadata, MAKEPAD)
    receipt = apply(source)
    (OUT / 'makepad-framework-compat.json').write_text(json.dumps(receipt, indent=2))
    shutil.copyfile(ROOT / 'scripts/robrix/patches/makepad-493d23a-web-startup.patch',
                    OUT / 'makepad-framework-compat.patch')
    shutil.copyfile(ROOT / 'scripts/robrix/patches/makepad-493d23a-nav.patch',
                    OUT / 'makepad-nav.patch')


def native_tests():
    checked_tests(['cargo', '+1.96.0', 'test', '--locked', '-p', 'makepad-platform', '--lib',
                   'hepta_web_startup_tests', '--', '--nocapture'], 'makepad-web-startup-tests.log', 3)
    checked_tests(['cargo', '+1.96.0', 'test', '--locked', '-p', 'makepad-widgets',
                   '--lib', 'hepta_font_tests', '--', '--nocapture'], 'makepad-font-cache-tests.log', 1)
    checked_tests(['cargo', '+1.96.0', 'test', '--locked', '-p', 'makepad-widgets',
                   '--lib', 'hepta_nav_tests', '--', '--nocapture'], 'makepad-nav-tests.log', 4)
    checked_tests(['cargo', '+1.96.0', 'test', '--locked', '-p', 'makepad-widgets',
                   '--lib', 'hepta_scroll_area_tests', '--', '--nocapture'], 'makepad-scroll-area-tests.log', 4)
    validate_native_log((OUT / 'makepad-scroll-area-tests.log').read_text())
    checked_tests(['cargo', '+1.96.0', 'test', '--locked', '-p', 'makepad-widgets',
                   '--lib', 'hepta_button_key_tests', '--', '--nocapture'], 'makepad-button-key-tests.log', 5)
    validate_native_log((OUT / 'makepad-button-key-tests.log').read_text())
    for module, minimum in [('shared::hepta_theme::tests', 6),
                            ('hepta_console::tests', 4),
                            ('home::main_desktop_ui::hepta_dock_tests', 3),
                            ('app::ui_fixture::tests', 5),
                            ('ui_dispatch::tests', 3),
                            ('timeline_channel::tests', 3)]:
        checked_tests(['cargo', '+1.96.0', 'test', '--locked', '--features', 'ui-fixture',
                       '--lib', module, '--', '--nocapture'], module.replace('::', '-') + '.log', minimum)
    checked_tests(['cargo', '+1.96.0', 'test', '--locked', '--manifest-path',
                   '../hepta-native/Cargo.toml', '--no-default-features', '--lib',
                   'console::tests', '--', '--nocapture'], 'native-console-tests.log', 5)


def web_build():
    source = Path(os.environ['MAKEPAD_SOURCE']).resolve()
    assert run(['git', 'rev-parse', 'HEAD'], cwd=source).strip() == MAKEPAD
    target = source / 'tools/cargo_makepad/src/wasm/compile.rs'
    before = target.read_text()
    # Only the build tool is patched. Application and dependency source are untouched.
    assert before.count('"nightly",') == 1
    assert before.count('"nightly".to_string(),') == 1
    after = before.replace('"nightly",', '&std::env::var("MAKEPAD_WASM_TOOLCHAIN").expect("pinned toolchain"),')
    after = after.replace('"nightly".to_string(),', 'std::env::var("MAKEPAD_WASM_TOOLCHAIN").expect("pinned toolchain"),')
    flags = 'let mut env = vec![("RUSTFLAGS", rustflags)];'
    assert after.count(flags) == 1
    after = after.replace(flags, 'let rustflags = format!(r#"{rustflags} --cfg ruma_identifiers_storage=\"Arc\""#);\n    let mut env = vec![("RUSTFLAGS", rustflags.as_str())];')
    from resource_transform import minifier_source, check_real_js, check_resource_contract
    transform_source = OUT / 'makepad-resource-transform.rs'
    transform_source.write_text(minifier_source(before))
    transform_binary = OUT / 'makepad-resource-transform'
    run(['rustc', '+1.96.0', '--edition', '2024', str(transform_source), '-o', str(transform_binary)],
        log='makepad-resource-transform-compile.log')
    (OUT / 'makepad-resource-transform-preflight.json').write_text(json.dumps(
        {'realJs': check_real_js(transform_binary, source, OUT),
         'byteContractTests': check_resource_contract(transform_binary, source)}, indent=2))
    from framework_compat import local_reporter
    after = local_reporter(after)
    target.write_text(after)
    utility = source / 'tools/cargo_makepad/src/utils.rs'
    utility_before = utility.read_text()
    utility.write_text(patch_packager(utility_before))
    from package_resources import parser_regression_source
    parser_test = OUT / 'makepad-parser-regression.rs'
    parser_test.write_text(parser_regression_source(utility.read_text(), (source / 'libs/shell/src/shell.rs').read_text()))
    parser_binary = OUT / 'makepad-parser-regression'
    run(['rustc', '+1.96.0', '--edition', '2024', '--test', str(parser_test), '-o', str(parser_binary)], log='makepad-parser-compile.log')
    run([str(parser_binary), '--nocapture'], log='makepad-parser-tests.log',
        env=dict(os.environ, MAKEPAD_WASM_TOOLCHAIN='nightly-2026-10-01'))
    parser_binary.unlink()
    run(['git', 'diff', '--', str(target), str(utility)], cwd=source, log='makepad-tool-only.patch')
    (OUT / 'makepad-tool-patch.json').write_text(json.dumps({
        'revision': MAKEPAD, 'beforeSha256': hashlib.sha256(before.encode()).hexdigest(),
        'afterSha256': digest(target), 'toolchain': 'nightly-2026-10-01',
        'dependencyResolverBeforeSha256': hashlib.sha256(utility_before.encode()).hexdigest(),
        'dependencyResolverAfterSha256': digest(utility)}, indent=2))
    run(['cargo', '+1.96.0', 'install', '--locked', '--path',
         str(source / 'tools/cargo_makepad'), '--root', str(OUT / 'makepad-tool')], log='makepad-tool-build.log')
    metadata = json.loads(subprocess.check_output(['cargo', '+nightly-2026-10-01', 'metadata',
        '--locked', '--format-version', '1', '--filter-platform', 'wasm32-unknown-unknown',
        '--features', 'ui-fixture'], cwd=APP, text=True))
    resource_root = compiled_resource_root(metadata, MAKEPAD)
    (OUT / 'makepad-resource-source.json').write_text(json.dumps({'revision': MAKEPAD,
        'compiledSource': str(resource_root), 'pinnedToolSource': str(source)}, indent=2))
    env = dict(os.environ, MAKEPAD_WASM_TOOLCHAIN='nightly-2026-10-01',
               MAKEPAD_RESOURCE_ROOT=str(resource_root))
    # Makepad owns the custom target specification, build-std, flags, JS and resources.
    # Do not replace this with cargo build --target wasm32-unknown-unknown.
    run([str(OUT / 'makepad-tool/bin/cargo-makepad'), 'wasm', '--bindgen', '--no-threads',
         'build', '-p', 'robrix', '--locked', '--features', 'ui-fixture', '--release'],
        env=env, log='makepad-wasm-package.log')
    package = APP / 'target/makepad-wasm-app/release/robrix'
    assert (package / 'index.html').is_file()
    assert (package / 'robrix.wasm').stat().st_size > 8
    assert (package / 'bindgen.js').is_file()
    (OUT / 'web-package-sha256.json').write_text(json.dumps(package_inventory(package), indent=2))
    try:
        resources = validate_pinned_resources(package, source, resource_root, transform_binary)
    finally:
        transform_binary.unlink(missing_ok=True)
    (OUT / 'web-package-resource-identity.json').write_text(json.dumps(resources, indent=2))
    (OUT / 'web-package-sha256.json').write_text(json.dumps(package_inventory(package), indent=2))


def web_tests():
    env = dict(os.environ, CARGO_TARGET_WASM32_UNKNOWN_UNKNOWN_RUNNER=f'{sys.executable} {ROOT / "scripts/robrix/browser_test_runner.py"}',
               WASM_BINDGEN_USE_BROWSER='1', CHROMEDRIVER=shutil.which('chromedriver') or 'chromedriver',
               WASM_BINDGEN_TEST_TIMEOUT='120')
    # Ordinary wasm target is intentionally for wasm-bindgen tests only, not UI packaging.
    output = run(['cargo', '+nightly-2026-10-01', 'test', '--locked', '--target',
                  'wasm32-unknown-unknown', '--features', 'ui-fixture', '--lib', '--', '--nocapture'],
                 env=env, log='browser-tests.log')
    expected = ['browser_resource_profile_clock_runs_without_std_time',
                'session_roundtrip_is_isolated_from_layout_storage_and_cleared',
                'malformed_restore_clears_metadata_without_contacting_a_server',
                'logout_removes_the_entire_session_record',
                'stale_restore_cannot_remove_newer_account_metadata',
                'request_burst_is_bounded_and_returns_rejected_payload',
                'delayed_account_setup_cannot_install_after_shutdown',
                'failed_credential_removal_retires_authority_and_cannot_complete_successfully',
                'full_and_poisoned_queue_preserve_exact_draft_until_one_retry_is_admitted',
                'poisoned_stream_blocks_requests_until_new_authority',
                'authority_transition_aborts_old_account_work',
                'old_account_cannot_mutate_after_an_await',
                'active_logout_task_survives_its_own_transition',
                'stale_registered_callback_is_cancelled_before_execution']
    for test in expected:
        assert re.search(re.escape(test) + r'\s+\.\.\.\s+ok', output), f'No executed passing test: {test}'
    assert re.search(r'test result: ok\. [1-9]\d* passed; 0 failed;', output)
    assert not re.search(r'; [1-9]\d* ignored', output)


FIXTURE_TITLE = 'Hepta · UI fixture · no live accounts'


def select_fixture_window(process, resource_name):
    """Identify Makepad's supported WM_CLASS instance, never unsupported WM_PID."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Fixture exited before a mapped window: {process.returncode}')
        result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--classname',
                                 '^' + re.escape(resource_name) + '$'], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        windows = result.stdout.split()
        if len(windows) > 1:
            raise RuntimeError('Multiple mapped windows have the unique fixture identity')
        if len(windows) == 1:
            window = windows[0]
            title = read_title(window)
            (OUT / f'native-window-{window}-title.json').write_text(json.dumps(title, indent=2) + '\n')
            if title['title'] == FIXTURE_TITLE:
                return window
        time.sleep(0.25)
    raise RuntimeError('No unique mapped window with the exact fixture title within 60 seconds')


def native_window_diagnostics(scene, process):
    for label, args in [('window-tree', ['xwininfo', '-root', '-tree']),
                        ('process', ['ps', '-p', str(process.pid), '-o', 'pid,ppid,stat,comm'])]:
        try:
            result = subprocess.run(args, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=5)
            output = result.stdout.decode('utf-8', errors='backslashreplace')  # Diagnostics only.
        except (OSError, subprocess.TimeoutExpired) as error:
            output = str(error)
        (OUT / f'native-{scene}-{label}.log').write_text(output)


def capture_short_login_scroll(window, process):
    """Exercise only scroll/focus inputs; control reachability needs pixel review."""
    from PIL import Image
    for label, commands in [
        ('wheel', [['xdotool', 'windowfocus', window],
                   ['xdotool', 'mousemove', '--window', window, '200', '450'],
                   ['xdotool', 'click', '--window', window, '--repeat', '6', '--delay', '80', '5']]),
        ('keyboard', [['xdotool', 'key', '--window', window, '--clearmodifiers', 'Page_Down'],
                      ['xdotool', 'key', '--window', window, '--clearmodifiers', 'Tab', 'Tab', 'Tab', 'Tab', 'Tab', 'Tab']]),
    ]:
        assert process.poll() is None, 'Fixture exited before scroll exercise'
        assert read_title(window)['title'] == FIXTURE_TITLE, 'Fixture title changed before input'
        for command in commands:
            run(command, cwd=ROOT, timeout=5)
        time.sleep(1)
        png = OUT / f'native-login-short-after-{label}.png'
        run(['import', '-window', window, str(png)], cwd=ROOT, timeout=10)
        with Image.open(png) as image:
            assert image.size == (800, 560)
        assert process.poll() is None, 'Fixture exited during scroll exercise'
    (OUT / 'native-login-short-input-exercise.json').write_text(json.dumps({
        'viewport': [800, 560], 'fixture': True, 'liveAccounts': False,
        'before': 'native-login-short.png',
        'after': ['native-login-short-after-wheel.png', 'native-login-short-after-keyboard.png'],
        'inputs': ['six wheel-down ticks', 'PageDown', 'six Tabs'],
        'submissionKeysSent': False, 'controlReachability': 'pending pixel review',
    }, indent=2) + '\n')


def validate_native_log(output):
    # The headless runner has no PulseAudio daemon. This one known fallback is
    # harmless; all other Makepad error diagnostics remain fatal.
    lines = [
        line
        for line in output.splitlines()
        if not (
            "pulse_audio.rs:" in line
            and "PulseAudio: pa_context_connect failed (Connection refused), using ALSA only"
            in line
        )
    ]
    errors = "\n".join(lines)
    assert not re.search(
        r'\[E\]|"level"\s*:\s*"error"|panicked at|shader.*(?:error|failed|not found)|script.*error|not found error',
        errors,
        re.I,
    ), errors

def require_no_scene_failures(failures):
    assert not failures, f'Capture qualification failed: {failures}'


def native_capture():
    from PIL import Image
    from render_checks import login_pixels
    binary = APP / 'target/debug/robrix'
    run(['cargo', '+1.96.0', 'build', '--locked', '--features', 'ui-fixture', '--bin', 'robrix'], log='native-build.log')
    scene_failures = []
    for scene in ('login', 'console', 'chat-titanium', 'chat-prism', 'chat-ceramic'):
        with (OUT / f'native-{scene}.log').open('w') as log:
            resource_name = f'hepta-fixture-{os.getpid()}-{scene}'
            process = subprocess.Popen([str(binary), '--hepta-ui-fixture', scene], cwd=APP,
                                       env=dict(os.environ, RESOURCE_NAME=resource_name),
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                window = select_fixture_window(process, resource_name)
                properties = subprocess.run(['xprop', '-id', window, 'WM_CLASS', 'WM_NAME', '_NET_WM_PID'],
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5, check=True)
                (OUT / f'native-{scene}-window-identity.log').write_text(
                    properties.stdout.decode('utf-8', errors='backslashreplace'))  # Not used for acceptance.
                for label, width, height in [('wide', 1180, 760), ('narrow', 520, 760), ('short', 800, 560)]:
                    run(['xdotool', 'windowsize', window, str(width), str(height)], cwd=ROOT)
                    time.sleep(3)
                    assert process.poll() is None, 'Native application exited before capture'
                    if scene.startswith('chat-') and label == 'narrow':
                        # Production resize opens the list; retain evidence, then
                        # select the real first room through its pointer handler.
                        run(['import', '-window', window, str(OUT / f'native-{scene}-narrow-room-list.png')], cwd=ROOT)
                        run(['xdotool', 'mousemove', '--window', window, '180', '215', 'click', '1'], cwd=ROOT)
                        time.sleep(1)
                    png = OUT / f'native-{scene}-{label}.png'
                    run(['import', '-window', window, str(png)], cwd=ROOT)
                    with Image.open(png) as image:
                        assert image.size == (width, height), image.size
                        assert len(image.convert('RGB').getcolors(width * height)) > 32, 'Blank fixture image'
                        if scene == 'login':
                            (OUT / f'native-login-{label}-pixels.json').write_text(json.dumps(login_pixels(image), indent=2))
                if scene == 'login':
                    capture_short_login_scroll(window, process)
            finally:
                native_window_diagnostics(scene, process)
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        errors = (OUT / f'native-{scene}.log').read_text()
        try:
            validate_native_log(errors)
        except AssertionError:
            scene_failures.append(scene)
    (OUT / 'native-scene-failures.json').write_text(json.dumps(scene_failures, indent=2))
    require_no_scene_failures(scene_failures)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['framework-compat', 'identity', 'native-tests', 'native-capture', 'web-build', 'web-tests'])
    mode = parser.parse_args().mode
    OUT.mkdir(parents=True, exist_ok=True)
    globals()[mode.replace('-', '_')]()
    (OUT / f'{mode}-passed.json').write_text(json.dumps({'mode': mode, 'passed': True}) + '\n')
