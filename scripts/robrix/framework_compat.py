"""Exact upstream web-startup compatibility; never suppress initialization errors."""
import hashlib
import subprocess
from pathlib import Path

BEFORE = {
    'platform/src/window.rs': '0dccf2ea7f449b7cb3a775b8a0236ef07eb1028c25c49e93fdcdcef221dfc039',
    'platform/src/os/web/web.rs': '8be1ad8d5b7cd0191fffdc94bad14aa7adbde7d5abf39825aaa8c4971c7318e8',
}


def apply(source):
    patch = Path(__file__).with_name('patches') / 'makepad-493d23a-web-startup.patch'
    for name, expected in BEFORE.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned framework source hash drift: ' + name)
    subprocess.run(['git', 'apply', '--check', str(patch.resolve())], cwd=source, check=True)
    subprocess.run(['git', 'apply', str(patch.resolve())], cwd=source, check=True)
    return {'revision': '493d23a7630f487d29912dd73f2cbb5b639b74ca',
            'patchSha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
            'before': BEFORE, 'after': {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in BEFORE}}


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
