"""Exact upstream web-startup compatibility; never suppress initialization errors."""
import hashlib
import re
import subprocess
from pathlib import Path

BEFORE = {
    'widgets/src/dock.rs': '7ac23dce77f2a7a2c4a2a083740353f07bdcf7ab98ca370e4763db2760577654',
    'widgets/src/scroll_bars.rs': '9d4c9e1ebf8bf756f33f3f29ab8965c57b48a9a404582411b87c8a4a34d32b44',
    'platform/src/draw_list.rs': '32475b53c3e38dd82b33c24f7a3e6b3c9137773493ac1a36c3668eaf4ad23c92',
    'widgets/src/nav_control.rs': '56830fb21636ebbcaeda7e3394021fda9a5342c4d3f784b869839e0cf7c7350b',
    'widgets/src/button.rs': '3e45061fb0a12036a6480306df89a4ebc918b7995e73c70041f9c485ce8ac7db',
    'widgets/src/text_input.rs': 'cc8ca79929a1410b014e3dc9bc193c38884a1d500e9a46d5e2ab5d8966500b19',
    'platform/src/script/res.rs': '2ae11aa2520266f4d2a77aab93c6e90db1bf9cb4ff44a051544b39d5bb38ac8b',
    'platform/src/window.rs': '0dccf2ea7f449b7cb3a775b8a0236ef07eb1028c25c49e93fdcdcef221dfc039',
    'platform/src/os/web/web.rs': '8be1ad8d5b7cd0191fffdc94bad14aa7adbde7d5abf39825aaa8c4971c7318e8',
    # The browser keeps its existing incremental keyboard/composition bridge.
    'platform/src/os/web/web.js': 'c9f17ebc80bb03bbc272174c91dc3f5d56ab4cc306b4fca11e2c29bb86c084f7',
}


def verify_web_input_dispatch(source):
    """These native-buffer/toolbar notifications must not reach Web's error arm.

    No payload is forwarded or reflected into the incremental JS textarea.
    All other unsupported operations must retain the original error reporting.
    Actual focus, typing and clearing are checked on the packaged WASM canvas.
    """
    start = source.index('    fn handle_platform_ops(&mut self) {')
    fallback = 'crate::error!("Not implemented on this platform: CxOsOp::{:?}", e);'
    if source.count(fallback) != 1:
        raise ValueError('Web unsupported-operation error reporting changed')
    dispatch = source[start:source.index(fallback)]
    for pattern in (r'CxOsOp::SyncImeState\s*\{\s*\.\.\s*\}',
                    r'CxOsOp::HideClipboardActions'):
        if len(re.findall(pattern + r'\s*=>\s*\{\s*\}', dispatch)) != 1:
            raise ValueError('Web input notification is not explicitly consumed: ' + pattern)


def verify_button_focus(source):
    start = source.index('Hit::FingerDown(fe) if self.enabled && fe.is_primary_hit() => {')
    end = source.index('Hit::FingerHoverIn', start)
    pointer = source[start:end]
    guarded = 'if self.grab_key_focus {\n                    cx.set_key_focus(self.draw_bg.area());\n                }'
    if pointer.count(guarded) != 1 or 'set_key_focus' in pointer.replace(guarded, ''):
        raise ValueError('Button pointer focus ignores grab_key_focus')


def apply(source):
    patch = Path(__file__).with_name('patches') / 'makepad-493d23a-web-startup.patch'
    added = 'widgets/src/hepta_font_tests.rs'
    if (source / added).exists():
        raise ValueError('Framework regression path already exists: ' + added)
    for name, expected in BEFORE.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned framework source hash drift: ' + name)
    nav_patch = patch.with_name('makepad-493d23a-nav.patch')
    nav_test = 'widgets/src/hepta_nav_tests.rs'
    scroll_test = 'widgets/src/hepta_scroll_area_tests.rs'
    key_test = 'widgets/src/hepta_button_key_tests.rs'
    dock_test = 'widgets/src/hepta_dock_retirement_tests.rs'
    if (source / dock_test).exists():
        raise ValueError('Framework regression path already exists: ' + dock_test)
    if (source / key_test).exists():
        raise ValueError('Framework regression path already exists: ' + key_test)
    if (source / scroll_test).exists():
        raise ValueError('Framework regression path already exists: ' + scroll_test)
    if (source / nav_test).exists():
        raise ValueError('Framework regression path already exists: ' + nav_test)
    subprocess.run(['git', 'apply', '--check', str(nav_patch.resolve())], cwd=source, check=True)
    subprocess.run(['git', 'apply', '--check', str(patch.resolve())], cwd=source, check=True)
    subprocess.run(['git', 'apply', str(patch.resolve())], cwd=source, check=True)
    subprocess.run(['git', 'apply', str(nav_patch.resolve())], cwd=source, check=True)
    verify_web_input_dispatch((source / 'platform/src/os/web/web.rs').read_text())
    verify_button_focus((source / 'widgets/src/button.rs').read_text())
    assert hashlib.sha256((source / 'platform/src/os/web/web.js').read_bytes()).hexdigest() == BEFORE['platform/src/os/web/web.js']
    return {'revision': '493d23a7630f487d29912dd73f2cbb5b639b74ca',
            'patchSha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
            'navPatchSha256': hashlib.sha256(nav_patch.read_bytes()).hexdigest(),
            'before': BEFORE, 'after': {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in [*BEFORE, added, nav_test, scroll_test, key_test, dock_test]}}


def local_reporter(source):
    start = "            const reportBrowserIssue = async (kind, data) => {{"
    end = "            window.makepad_report_browser_issue = reportBrowserIssue;"
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError('Pinned generated reporter shape drift')
    a, b = source.index(start), source.index(end)
    block = source[a:b]
    if block.count("await fetch('/$report_error?data='") != 1:
        raise ValueError('Pinned report transmission shape drift')
    replacement = '''            const reportBrowserIssue = async (kind, data) => {{
                console.error('Makepad browser issue', kind, JSON.stringify(data));
            }};
'''
    return source[:a] + replacement + source[b:]
