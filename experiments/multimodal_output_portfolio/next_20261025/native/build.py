"""Compile the original owner and next value driver against restored native crates."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from .common import AREA, NATIVE, sha, write


OWNER_SHA = '4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf'


def build(output):
    original = NATIVE / 'raw_evidence/native/build-004/src'
    if sha(original / 'agentd_owner.rs') != OWNER_SHA:
        raise ValueError('Original product owner changed')
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'src'; source.mkdir()
    for name in ('future_head.rs', 'head.rs', 'measure.rs', 'runtime_profile.rs',
                 'dynamics_profile.rs', 'stream_io.rs', 'agentd_owner.rs'):
        shutil.copyfile(original / name, source / name)
    for path in AREA.glob('*.rs'):
        shutil.copyfile(path, source / path.name)
    deps = NATIVE / 'target/release/deps'
    rustc = NATIVE / 'toolchain/installed/bin/rustc'
    names = ('codex_hepta_neuron', 'codex_hepta_types', 'codex_hepta_infer_core',
             'codex_hepta_ndu', 'codex_native_owner_bridge', 'serde', 'serde_json')
    extern, libraries = [], {}
    for name in names:
        paths = sorted(deps.glob(f'lib{name}-*.rlib'))
        if len(paths) != 1:
            raise ValueError('Expected exactly one restored dependency: ' + name)
        libraries[name] = {'path': str(paths[0]), 'sha256': sha(paths[0])}
        extern += ['--extern', f'{name}={paths[0]}']
    common = [str(rustc), '--edition=2024', '-C', 'opt-level=2', '-C', 'debuginfo=0', '-L', f'dependency={deps}'] + extern
    owner = output / 'libhepta_online_agentd_owner.rlib'
    commands = [common + ['--crate-name', 'hepta_online_agentd_owner', '--crate-type', 'lib',
                         str(source / 'agentd_owner.rs'), '-o', str(owner)],
                common + ['--crate-name', 'hepta_native_ndu_online', '--extern',
                          f'hepta_online_agentd_owner={owner}', str(source / 'online.rs'),
                          '-C', 'strip=symbols', '-o', str(output / 'hepta-native-ndu-online')]]
    began = time.perf_counter_ns()
    results = []
    for command in commands:
        process = subprocess.run(command, capture_output=True, text=True)
        results.append({'command': command, 'returncode': process.returncode,
                        'stdout': process.stdout, 'stderr': process.stderr})
        if process.returncode:
            break
    binary = output / 'hepta-native-ndu-online'
    receipt = {'schema': 'hepta.next.native-build.v1', 'commands': results,
               'wall_ns': time.perf_counter_ns() - began,
               'compiler': subprocess.check_output([str(rustc), '--version'], text=True).strip(),
               'compiler_sha256': sha(rustc), 'source_sha256': {p.name: sha(p) for p in source.glob('*.rs')},
               'dependencies': libraries, 'owner_source_modified': False,
               'original_owner_source_commit': '985a52e84cdaed7c8d4c363f30bc8841c5e3730c',
               'dependency_source_commit': '9595221c21f1fe0775295a9c8756a1ba4d69ea49',
               'whole_agentd_daemon_built': False,
               'binary_sha256': sha(binary) if binary.exists() else None}
    write(output / 'build.json', receipt)
    if not binary.exists():
        raise RuntimeError(results[-1]['stderr'])
    print(json.dumps({'binary': str(binary), 'sha256': sha(binary)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
