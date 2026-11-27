"""Verify manifest bytes in Git objects, independent of ignored working files."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--manifest', action='append', required=True)
    parser.add_argument('--extra-file', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repository.resolve()

    def git(*words):
        return subprocess.check_output(['git', *words], cwd=repo, stderr=subprocess.PIPE)

    revision = git('rev-parse', '--verify', args.revision + '^{commit}').decode().strip()
    tree = git('rev-parse', revision + '^{tree}').decode().strip()
    entries = {}
    for row in git('ls-tree', '-r', '-z', revision).split(b'\0'):
        if row:
            metadata, name = row.split(b'\t', 1)
            mode, kind, oid = metadata.decode().split()
            entries[name.decode()] = (mode, kind, oid)
    cache, checked, errors, manifests = {}, {}, [], {}

    def blob(name):
        if name not in entries:
            raise ValueError('missing committed file: ' + name)
        mode, kind, oid = entries[name]
        if kind != 'blob' or mode not in ['100644', '100755']:
            raise ValueError('nonregular committed file: ' + name)
        if oid not in cache:
            cache[oid] = git('cat-file', 'blob', oid)
        return cache[oid]

    def check(name, expected):
        try:
            raw = blob(name)
            actual = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            if actual != expected:
                raise ValueError('committed bytes differ from expected identity: ' + name)
            checked[name] = {**actual, 'git_blob': entries[name][2]}
        except ValueError as error:
            errors.append({'path': name, 'error': str(error), 'expected': expected})

    for name in args.manifest:
        raw = blob(name)
        manifests[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        parent = PurePosixPath(name).parent
        for member, expected in json.loads(raw)['files'].items():
            relative = PurePosixPath(member)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('manifest escaped its directory: ' + member)
            check((parent / relative).as_posix(), expected)
    for name in args.extra_file:
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('extra file escaped the repository: ' + name)
        raw = (repo / name).read_bytes()
        check(name, {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    result = {'schema': 'hcsn-committed-evidence-byte-verification-v1',
              'revision': revision, 'tree': tree, 'manifest_identities': manifests,
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'passed': not errors, 'errors': errors, 'verified_files': checked,
              'scope': 'Read committed regular-file Git blobs and compare exact manifest identities. Extra files compare committed bytes with the explicitly checked working files. This establishes tree completeness, not scientific accuracy or CI success.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'passed': result['passed'], 'errors': len(errors),
                      'verified_files': len(checked), 'revision': revision, 'tree': tree}))
    return 0 if result['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
