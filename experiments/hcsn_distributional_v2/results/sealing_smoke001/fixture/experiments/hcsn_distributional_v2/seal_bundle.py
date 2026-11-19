"""Stream a new evidence bundle in isolation and publish its manifest last.

Each invocation owns one bundle. Complete archive-child CPU and wrapper self
CPU are disjoint; the inner archive clocks are nested in the child receipt.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback


PACKAGE = Path(__file__).resolve().parent


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def write(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def run(name, includes):
    if sys.flags.optimize:
        raise RuntimeError('Evidence sealing requires Python without -O/PYTHONOPTIMIZE')
    if not re.fullmatch(r'[a-zA-Z0-9_]+', name):
        raise ValueError('Use a simple unique bundle name')
    artifacts = PACKAGE/'artifacts'
    if any(artifacts.glob(name+'.*')) or (artifacts/(name+'_EXECUTION.json')).exists():
        raise FileExistsError('Bundle names are immutable')
    state = PACKAGE/'results/evidence_sealing'/name
    state.mkdir(parents=True, exist_ok=False)
    work = state/'work'
    package = work/'experiments/hcsn_distributional_v2'
    child_cpu, child_exit, completed, error = 0.0, None, False, None
    wall = time.monotonic()
    try:
        sources = {}
        for relative in includes:
            lexical = PACKAGE/relative
            target = lexical.resolve()
            if lexical.is_symlink() or not target.is_relative_to(PACKAGE) or not target.exists():
                raise ValueError('Expected an existing local non-symlink package member')
            if target.is_relative_to(artifacts) or target.is_relative_to(state):
                raise ValueError('Do not recursively bundle archives or this staging tree')
            paths = [target] if target.is_file() else target.rglob('*')
            for path in paths:
                if path.is_symlink():
                    raise ValueError('Symlinks are forbidden')
                if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                    relative = path.relative_to(PACKAGE)
                    if path.is_relative_to(artifacts) or 'work' in relative.parts:
                        raise ValueError('An include contains archives or an internal staging work tree')
                    sources[str(relative)] = path
        if not sources:
            raise ValueError('No files selected')
        members = {name: {'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)}
                   for name, path in sorted(sources.items())}
        source_identity = {name: sha(PACKAGE/name) for name in ('evidence_bundle.py', 'seal_bundle.py')}
        source_identity['v1/archive.py'] = sha(PACKAGE.parent/'hcsn_free_boundary_v1/archive.py')
        selection = state/'SELECTION.json'
        write(selection, {'schema': 'hcsn-v2-staged-bundle-selection.v1', 'bundle_name': name,
                          'members': list(members.values()), 'source_sha256': source_identity,
                          'selection_rule': 'Explicit complete evidence paths; no score filtering'})
        relative = str(selection.relative_to(PACKAGE))
        sources[relative] = selection
        members[relative] = {'path': relative, 'bytes': selection.stat().st_size, 'sha256': sha(selection)}
        for relative, source in sources.items():
            destination = package/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, destination)
        if 'evidence_bundle.py' not in sources:
            os.link(PACKAGE/'evidence_bundle.py', package/'evidence_bundle.py')
        old_archive = work/'experiments/hcsn_free_boundary_v1/archive.py'
        old_archive.parent.mkdir(parents=True, exist_ok=True)
        os.link(PACKAGE.parent/'hcsn_free_boundary_v1/archive.py', old_archive)
        # Pass the enumerated files, so a later directory entry cannot silently
        # enter the archive. Re-enumeration below also rejects directory changes.
        command = [sys.executable, '-m', 'experiments.hcsn_distributional_v2.evidence_bundle', '--name', name]
        for relative in sources:
            command.extend(['--include', relative])
        environment = dict(os.environ, PYTHONPATH=str(work), PYTHONDONTWRITEBYTECODE='1')
        with (state/'worker.log').open('x') as log:
            process = subprocess.Popen(command, cwd=work, env=environment, stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        child_cpu = usage.ru_utime+usage.ru_stime
        child_exit = process.returncode
        write(state/'WORKER_EXECUTION.json', {'command': command, 'returncode': child_exit,
            'complete_archive_child_cpu_seconds': child_cpu, 'peak_rss_kib_linux': usage.ru_maxrss,
            'log_sha256': sha(state/'worker.log'), 'measurement': 'Complete Linux wait4 child including imports, packing, restore verification and exit'})
        if child_exit:
            raise RuntimeError('Archive child failed; staging and receipt retained')
        manifest_path = package/'artifacts'/(name+'.json')
        manifest = json.loads(manifest_path.read_bytes())
        actual = {row['path']: row for row in manifest['members']}
        assert len(actual)==len(manifest['members']) and actual==members
        assert manifest['schema']=='hcsn-evidence-bundle.v1' and manifest['name']==name
        seal_path = manifest_path.with_name(name+'_EXECUTION.json')
        seal = json.loads(seal_path.read_bytes())
        assert seal['source_sha256']==source_identity['evidence_bundle.py']
        assert seal['pack_restore_source_sha256']==source_identity['v1/archive.py']
        assert seal['verified_restore']=={'archive_sha256': manifest['archive_sha256'],
                                         'restored_or_already_identical': len(members)}
        whole = hashlib.sha256()
        for part in manifest['parts']:
            path = manifest_path.parent/part['path']
            assert path.parent==manifest_path.parent and not path.is_symlink()
            assert path.stat().st_size==part['bytes'] and sha(path)==part['sha256']
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1048576), b''):
                    whole.update(block)
        assert whole.hexdigest()==manifest['archive_sha256']
        for relative, row in members.items():
            assert (PACKAGE/relative).stat().st_size==row['bytes'] and sha(PACKAGE/relative)==row['sha256']
        current_names = set()
        for relative in includes:
            target = (PACKAGE/relative).resolve()
            for path in ([target] if target.is_file() else target.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Selected tree acquired a symlink during sealing')
                if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                    current_names.add(str(path.relative_to(PACKAGE)))
        assert current_names == set(members)-{str(selection.relative_to(PACKAGE))}
        assert sha(__file__)==source_identity['seal_bundle.py']
        assert sha(PACKAGE/'evidence_bundle.py')==source_identity['evidence_bundle.py']
        assert sha(PACKAGE.parent/'hcsn_free_boundary_v1/archive.py')==source_identity['v1/archive.py']
        for filename in [row['path'] for row in manifest['parts']]+[name+'_EXECUTION.json']:
            os.link(manifest_path.parent/filename, artifacts/filename)
        os.link(manifest_path, artifacts/manifest_path.name)
        completed = True
        print(json.dumps({'status': 'completed', 'bundle_name': name,
            'manifest_sha256': sha(artifacts/manifest_path.name), 'archive_sha256': manifest['archive_sha256'],
            'members': len(members), 'parts': len(manifest['parts'])}), flush=True)
    except BaseException:
        error = traceback.format_exc()
        raise
    finally:
        write(state/'EXECUTION.json', {'schema': 'hcsn-v2-staged-bundle-execution.v1',
            'status': 'completed' if completed else 'failed', 'bundle_name': name,
            'manifest_path': 'artifacts/'+name+'.json', 'archive_child_exit_code': child_exit,
            'complete_archive_child_cpu_seconds': child_cpu,
            'coordinator_whole_self_cpu_seconds_through_cutoff': time.process_time(),
            'wall_seconds': time.monotonic()-wall, 'error': error, 'source_sha256': sha(__file__),
            'scope': 'One bundle per interpreter. Add complete child and whole wrapper self CPU once; inner seal/body/pack/restore clocks are nested. Final receipt serialization/exit is outside cutoff.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--include', action='append', default=[])
    parser.add_argument('--include-file', type=Path, help='JSON list of explicit package-relative paths')
    args = parser.parse_args()
    includes = args.include + (json.loads(args.include_file.read_bytes()) if args.include_file else [])
    os.nice(5)
    run(args.name, includes)
