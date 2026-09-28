#!/usr/bin/env python3
"""One-shot transport of the existing audited patch. Not qualification."""
import base64
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib
import zipfile

BASE = '8657079da6377f4012d73b18d194f75bd3a115f5'
ROOT = Path('qualification/kernel-evidence/transport-20260928')
EXPECTED = '8cba18c5a451924a48e3108e5b934d6f890cb45a080718976dfee12026c26c99'
LOCK = Path('codex-rs/Cargo.lock')

def git(*args, check=True):
    return subprocess.run(['git', *args], check=check, capture_output=True)

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def allowed(path):
    p = PurePosixPath(path)
    return (not p.is_absolute() and '..' not in p.parts and str(p) == path
            and (path.startswith(('codex-rs/hepta-agent-protocol/',
                                  'codex-rs/hepta-agentd/', 'codex-rs/hepta-evidence/'))
                 or path == 'qualification/kernel-evidence/FOLLOWUP_BOUNDARIES_20260928.md'))

def safe_path(value):
    if not allowed(value):
        raise ValueError('out-of-scope source path: ' + value)
    p = Path(value)
    if any(x.is_symlink() for x in (p, *p.parents)):
        raise ValueError('symlink rejected: ' + value)
    return p

def stage_sources(archive, base=BASE):
    if hashlib.sha256(archive).hexdigest() != '963f5f42ff4f703d6dde5212a6205126ff3b7cfebf6f1f0627ffe5e6f417c9fc':
        raise ValueError('formatting artifact digest mismatch')
    encoded = (ROOT/'part1.b64').read_text().strip() + (ROOT/'part2.b64').read_text().strip()
    delta = lzma.decompress(base64.b64decode(encoded, validate=True), memlimit=134217728)
    if hashlib.sha256(delta).hexdigest() != 'a399b86dc2b651cc97f36c8e4a70c043a35938e67de9a17ea23411f63c67c7d9':
        raise ValueError('semantic patch digest mismatch')
    for line in delta.decode().splitlines():
        if line.startswith('+++ b/') or line.startswith('--- a/'):
            safe_path(line[6:])
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        names = [n for n in z.namelist() if n.startswith('files/')]
        if len(names) != 57 or len(set(names)) != 57:
            raise ValueError('unexpected artifact source inventory')
        for name in names:
            p = safe_path(name[6:])
            if not p.is_file():
                raise ValueError('format source missing from fixed base: ' + str(p))
            p.write_bytes(z.read(name))
    subprocess.run(['git', 'apply', '--check', '-'], input=delta, check=True)
    subprocess.run(['git', 'apply', '-'], input=delta, check=True)
    git('add', '--', 'codex-rs/hepta-agent-protocol', 'codex-rs/hepta-agentd',
        'codex-rs/hepta-evidence', 'qualification/kernel-evidence/FOLLOWUP_BOUNDARIES_20260928.md')
    paths = git('diff', '--cached', '--name-only', '-z').stdout.decode().strip('\0').split('\0')
    if len(paths) != 61 or not all(allowed(p) for p in paths):
        raise ValueError('unexpected staged source inventory')
    rows = []
    for path in sorted(paths):
        old = git('show', base + ':' + path, check=False)
        before = blob(old.stdout) if old.returncode == 0 else '-'
        after = blob(safe_path(path).read_bytes())
        rows.append(path + '\0' + before + '\0' + after)
    actual = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    if actual != EXPECTED:
        raise ValueError('before/after source commitment mismatch: ' + actual)
    git('diff', '--cached', '--check')
    return paths

def repair_lock(data):
    text = data.decode()
    before = tomllib.loads(text)
    if len([p for p in before['package'] if p['name'] == 'libc']) != 1:
        raise ValueError('ambiguous resolved libc')
    expected = json.loads(json.dumps(before))
    for name in ('codex-hepta-agentd', 'codex-hepta-evidence'):
        packages = [p for p in expected['package'] if p['name'] == name]
        if len(packages) != 1 or 'libc' in packages[0]['dependencies']:
            raise ValueError('lock stanza drift')
        packages[0]['dependencies'].append('libc')
        packages[0]['dependencies'].sort()
        pattern = re.compile(r'(\[\[package\]\]\nname = "' + re.escape(name)
            + r'"\n(?:(?!\[\[package\]\]).)*?dependencies = \[\n)(.*?)(\n\])', re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError('ambiguous package block')
        match = matches[0]
        lines = match.group(2).splitlines()
        if not all(re.fullmatch(r' "([^"\n]+)",', line) for line in lines):
            raise ValueError('unexpected dependency syntax')
        lines.append(' "libc",')
        text = text[:match.start(2)] + '\n'.join(sorted(lines)) + text[match.end(2):]
    if tomllib.loads(text) != expected:
        raise ValueError('lock repair exceeded two dependency edges')
    return text.encode()

def main():
    git('merge-base', '--is-ancestor', BASE, 'HEAD')
    bootstrap = set(git('diff', '--name-only', BASE, 'HEAD').stdout.decode().splitlines())
    expected_bootstrap = {str(ROOT/n) for n in ('part1.b64', 'part2.b64', 'apply.py')}
    expected_bootstrap.add('.github/workflows/kernel-evidence-followup-delivery.yml')
    if bootstrap != expected_bootstrap or git('status', '--porcelain').stdout:
        raise ValueError('bootstrap drift or dirty checkout')
    paths = stage_sources(Path(sys.argv[1]).read_bytes())
    data = LOCK.read_bytes()
    if blob(data) != 'cd6650b68a815d69038166b7de50c2857f358641' or LOCK.is_symlink():
        raise ValueError('Cargo.lock baseline mismatch')
    LOCK.write_bytes(repair_lock(data))
    git('add', '--', str(LOCK))
    git('diff', '--cached', '--check')
    print(json.dumps({'sourceFileCount': len(paths), 'lockEdgesAdded': 2,
        'sourceCommitment': EXPECTED, 'nativeTestsExecuted': False,
        'qualificationGranted': False, 'activation': False, 'release': False}, indent=2))

if __name__ == '__main__':
    main()
