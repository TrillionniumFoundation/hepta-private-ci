"""Compile a new controller against the original, read-only 22-crate artifacts."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time


ROOT = Path('/workspace/scratch/2b3c256bef7d')
OWNER = ROOT / 'native-product-build-20261025/codex-rs/hepta-agentd/src/neuron_runtime.rs'
OWNER_SHA = '4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf'
ORIGINAL = ROOT / 'abc4-native-runs/build-001/native-head/src'
DEPS = ROOT / 'abc4-native-runs/target/release/deps'
RUSTC = ROOT / 'task-tools/rust-1.95.0/bin/rustc'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output):
    if sha(OWNER) != OWNER_SHA:
        raise ValueError('Original AgentdNeuronOwner source identity changed')
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'src'
    source.mkdir()
    for name in ('future_head.rs', 'head.rs', 'measure.rs', 'runtime_profile.rs',
                 'dynamics_profile.rs', 'stream_io.rs'):
        shutil.copyfile(ORIGINAL / name, source / name)
    shutil.copyfile(OWNER, source / 'agentd_owner.rs')
    for path in Path(__file__).parent.glob('*.rs'):
        shutil.copyfile(path, source / path.name)
    names = ('codex_hepta_neuron', 'codex_hepta_types', 'codex_hepta_infer_core',
             'codex_hepta_ndu', 'codex_native_owner_bridge', 'serde', 'serde_json')
    extern = []
    libraries = {}
    for name in names:
        paths = sorted(DEPS.glob(f'lib{name}-*.rlib'))
        if len(paths) != 1:
            raise ValueError(f'Expected one frozen dependency: {name}')
        libraries[name] = {'path': str(paths[0]), 'sha256': sha(paths[0])}
        extern += ['--extern', f'{name}={paths[0]}']
    common = [str(RUSTC), '--edition=2024', '-C', 'opt-level=2', '-C', 'debuginfo=0',
              '-L', f'dependency={DEPS}'] + extern
    owner = output / 'libhepta_online_agentd_owner.rlib'
    commands = [common + ['--crate-name', 'hepta_online_agentd_owner', '--crate-type', 'lib',
                         str(source / 'agentd_owner.rs'), '-o', str(owner)],
                common + ['--crate-name', 'hepta_native_online', '--extern',
                          f'hepta_online_agentd_owner={owner}', str(source / 'online.rs'),
                          '-C', 'strip=symbols', '-o', str(output / 'hepta-native-online')]]
    began = time.monotonic_ns()
    results = []
    for command in commands:
        process = subprocess.run(command, capture_output=True, text=True)
        results.append({'command': command, 'returncode': process.returncode,
                        'stdout': process.stdout, 'stderr': process.stderr})
        if process.returncode:
            break
    receipt = {'schema': 'hepta.closure.native-build.v1', 'commands': results,
               'wall_ns': time.monotonic_ns() - began,
               'compiler': subprocess.check_output([str(RUSTC), '--version'], text=True).strip(),
               'source_sha256': {p.name: sha(p) for p in sorted(source.glob('*.rs'))},
               'dependencies': libraries, 'original_sources_modified': False,
               'owner_source_commit': '985a52e84cdaed7c8d4c363f30bc8841c5e3730c',
               'dependency_source_commit': '9595221c21f1fe0775295a9c8756a1ba4d69ea49',
               'whole_agentd_daemon_built': False}
    binary = output / 'hepta-native-online'
    if binary.exists():
        receipt['binary_sha256'] = sha(binary)
    (output / 'build.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    if not binary.exists():
        raise RuntimeError(results[-1]['stderr'])
    print(json.dumps({'binary': str(binary), 'sha256': sha(binary)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
