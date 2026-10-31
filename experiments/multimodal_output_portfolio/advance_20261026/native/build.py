"""Compile the new typed adapter against exact original owner/runtime objects."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from .common import AREA, NATIVE, OWNER_SHA, sha, write


def build(output):
    original = NATIVE / 'raw_evidence/native/build-004/src'
    if sha(original / 'agentd_owner.rs') != OWNER_SHA:
        raise ValueError('The original product owner identity changed')
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'src'
    source.mkdir()
    for name in ('head.rs', 'measure.rs', 'runtime_profile.rs', 'dynamics_profile.rs',
                 'stream_io.rs', 'agentd_owner.rs'):
        shutil.copyfile(original / name, source / name)
    for path in AREA.glob('*.rs'):
        shutil.copyfile(path, source / path.name)
    deps = NATIVE / 'target/release/deps'
    rustc = NATIVE / 'toolchain/installed/bin/rustc'
    extern, libraries = [], {}
    for name in ('codex_hepta_neuron', 'codex_hepta_types', 'codex_hepta_infer_core',
                 'codex_hepta_ndu', 'codex_native_owner_bridge', 'serde', 'serde_json'):
        found = sorted(deps.glob(f'lib{name}-*.rlib'))
        if len(found) != 1:
            raise ValueError('One exact restored dependency is required: ' + name)
        libraries[name] = {'path': str(found[0]), 'sha256': sha(found[0])}
        extern += ['--extern', f'{name}={found[0]}']
    flags = [str(rustc), '--edition=2024', '-C', 'opt-level=2', '-C', 'debuginfo=0',
             '-L', f'dependency={deps}', *extern]
    owner = output / 'libhepta_online_agentd_owner.rlib'
    binary = output / 'hepta-native-semantic-online'
    commands = [flags + ['--crate-name', 'hepta_online_agentd_owner', '--crate-type',
                         'lib', str(source / 'agentd_owner.rs'), '-o', str(owner)],
                flags + ['--crate-name', 'hepta_native_semantic_online', '--extern',
                         f'hepta_online_agentd_owner={owner}', str(source / 'online.rs'),
                         '-C', 'strip=symbols', '-o', str(binary)]]
    began, results = time.perf_counter_ns(), []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        results.append({'command': command, 'returncode': result.returncode,
                        'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            break
    write(output / 'build.json', {'schema': 'hepta.advance.native-build.v1',
          'wall_ns': time.perf_counter_ns() - began, 'commands': results,
          'compiler': subprocess.check_output([str(rustc), '--version'], text=True).strip(),
          'compiler_sha256': sha(rustc), 'dependencies': libraries,
          'source_sha256': {p.name: sha(p) for p in source.glob('*.rs')},
          'binary_sha256': sha(binary) if binary.exists() else None,
          'original_owner_source_commit': '985a52e84cdaed7c8d4c363f30bc8841c5e3730c',
          'dependency_source_commit': '9595221c21f1fe0775295a9c8756a1ba4d69ea49',
          'owner_source_modified': False, 'production_authority': False})
    if not binary.exists():
        raise RuntimeError(results[-1]['stderr'])
    print(json.dumps({'binary': str(binary), 'sha256': sha(binary)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    build(p.parse_args().output)
