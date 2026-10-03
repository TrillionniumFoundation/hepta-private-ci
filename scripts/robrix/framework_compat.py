"""Exact upstream web-startup compatibility; never suppress initialization errors."""
import hashlib
import subprocess
from pathlib import Path

BEFORE = {
    'widgets/src/text_input.rs': 'cc8ca79929a1410b014e3dc9bc193c38884a1d500e9a46d5e2ab5d8966500b19',
    'platform/src/script/res.rs': '2ae11aa2520266f4d2a77aab93c6e90db1bf9cb4ff44a051544b39d5bb38ac8b',
    'platform/src/window.rs': '0dccf2ea7f449b7cb3a775b8a0236ef07eb1028c25c49e93fdcdcef221dfc039',
    'platform/src/os/web/web.rs': '8be1ad8d5b7cd0191fffdc94bad14aa7adbde7d5abf39825aaa8c4971c7318e8',
}


def apply(source):
    patch = Path(__file__).with_name('patches') / 'makepad-493d23a-web-startup.patch'
    added = 'widgets/src/hepta_font_tests.rs'
    if (source / added).exists():
        raise ValueError('Framework regression path already exists: ' + added)
    for name, expected in BEFORE.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned framework source hash drift: ' + name)
    subprocess.run(['git', 'apply', '--check', str(patch.resolve())], cwd=source, check=True)
    subprocess.run(['git', 'apply', str(patch.resolve())], cwd=source, check=True)
    return {'revision': '493d23a7630f487d29912dd73f2cbb5b639b74ca',
            'patchSha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
            'before': BEFORE, 'after': {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in [*BEFORE, added]}}


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
