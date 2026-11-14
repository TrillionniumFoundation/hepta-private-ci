"""Scoped real-library qualification of the unchanged private Bao adapter.

Excludes Agentd startup, runtime registration and its five unresolved V1 clock
callers. This is not a substitute for the pending normal Agentd crate tests.
Run only through the shared build-slot gate on the coordinated target.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/workspace/shared/operations-authbus-integration')
RUST = ROOT / 'codex-rs'
OUT = Path('/workspace/shared/authbus-native-evidence/bao-composition-harness')
OUT.mkdir(exist_ok=True)
NAMES = {'codex_hepta_authbus', 'codex_hepta_bao_adapter', 'codex_hepta_cognitive_store',
         'codex_hepta_contracts', 'codex_hepta_memory', 'codex_hepta_operations',
         'codex_hepta_paths', 'codex_hepta_types', 'ed25519_dalek', 'tokio',
         'serde_json', 'rcgen', 'rustls', 'tokio_rustls', 'tempfile'}
source_paths = [RUST / 'hepta-agentd/src' / name for name in (
    'bao_operation_target.rs', 'bao_operation_target_tests.rs',
    'bao_operation_target_cancellation_tests.rs')]
source_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
# Bind the local owner/provider implementation and migrations, not just the
# wrapper source, to the Cargo-produced libraries for this coordinated build.
implementation_paths = [RUST / 'Cargo.lock', RUST / 'Cargo.toml', RUST / 'rust-toolchain.toml']
for crate in ('hepta-authbus', 'hepta-bao-adapter', 'hepta-cognitive-store',
              'hepta-memory', 'hepta-operations', 'hepta-contracts', 'hepta-types',
              'hepta-paths', 'state'):
    implementation_paths.extend(p for p in (RUST / crate).rglob('*')
                                if p.is_file() and p.suffix in {'.rs', '.sql', '.toml'})
implementation_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(set(implementation_paths)) if p.exists()}
command = ['cargo', '+1.95.0', 'build', '--locked', '--lib',
           '-p', 'codex-hepta-cognitive-store', '-p', 'codex-hepta-bao-adapter',
           '-p', 'rcgen', '-p', 'tokio-rustls', '-p', 'tokio',
           '--features', 'tokio/process,tokio/net,tokio/macros,tokio/rt-multi-thread',
           '--message-format=json']
if '--reuse-artifacts' not in sys.argv:
    with (OUT / 'cargo-artifacts.jsonl').open('w') as output:
        subprocess.run(command, cwd=RUST, stdout=output, check=True)
    for path, expected in implementation_hashes.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise SystemExit('implementation changed during Cargo build: ' + path)
    (OUT / 'cargo-source-bindings.json').write_text(json.dumps(implementation_hashes, indent=2) + '\n')
else:
    binding_file = OUT / 'cargo-source-bindings.json'
    if not binding_file.exists() or json.loads(binding_file.read_text()) != implementation_hashes:
        raise SystemExit('cannot reuse artifacts without matching captured implementation source bindings')
candidates = {}
for line in (OUT / 'cargo-artifacts.jsonl').read_text().splitlines():
    item = json.loads(line)
    name = item.get('target', {}).get('name')
    if item.get('reason') == 'compiler-artifact' and name in NAMES:
        for filename in item['filenames']:
            if filename.endswith('.rlib'):
                candidates.setdefault(name, []).append({'path': filename,
                    'package_id': item['package_id'], 'features': item.get('features', []),
                    'cargo_profile': item.get('profile', {})})
artifacts = {}
for name, choices in candidates.items():
    # This graph emits narrower host/build-time variants as well. Only accept
    # a unique feature-superset candidate; compiler type checking must still
    # prove that its crate identity agrees with the real owner/provider libs.
    largest = [a for a in choices if all(set(a['features']) >= set(b['features']) for b in choices)]
    if len(largest) != 1:
        raise SystemExit('ambiguous Cargo artifact variants for ' + name)
    artifacts[name] = largest[0]
if artifacts.keys() != NAMES:
    raise SystemExit('missing exact Cargo libraries: ' + str(sorted(NAMES - artifacts.keys())))
for value in artifacts.values():
    value['sha256'] = hashlib.sha256(Path(value['path']).read_bytes()).hexdigest()
wrapper = OUT / 'wrapper.rs'
wrapper.write_text('#[path = "' + str(source_paths[0]) + '"]\nmod bao_operation_target;\n')
compiler = ['rustc', '+1.95.0']
version = subprocess.check_output(compiler + ['--version', '--verbose'], cwd=RUST, text=True)
compile_command = compiler + ['--edition=2024', '--test', '-C', 'debuginfo=0', '-C', 'strip=debuginfo',
                              str(wrapper), '-o', str(OUT / 'bao-composition-tests')]
for directory in sorted({str(Path(a['path']).parent) for a in artifacts.values()}):
    compile_command += ['-L', 'dependency=' + directory]
for name, value in sorted(artifacts.items()):
    compile_command += ['--extern', name + '=' + value['path']]
manifest = {'status': 'compile pending', 'scope': __doc__, 'compiler': version,
            'build_environment': {key: os.environ.get(key) for key in ('CARGO_TARGET_DIR', 'CARGO_PROFILE_DEV_DEBUG', 'CARGO_PROFILE_TEST_DEBUG', 'CARGO_INCREMENTAL', 'CARGO_BUILD_JOBS')},
            'source_hashes': source_hashes, 'implementation_source_hashes': implementation_hashes,
            'cargo_command': command,
            'artifact_selection': 'unique feature-superset Cargo unit; rustc validates cross-crate identities',
            'rustc_command': compile_command, 'artifacts': artifacts,
            'shared_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
subprocess.run(compile_command, cwd=RUST, check=True)
for artifact in artifacts.values():
    if hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit('Cargo library changed while compiling wrapper: ' + artifact['path'])
for path in source_paths:
    if hashlib.sha256(path.read_bytes()).hexdigest() != source_hashes[str(path)]:
        raise SystemExit('source changed while compiling: ' + str(path))
for path, expected in implementation_hashes.items():
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise SystemExit('implementation source changed during build: ' + path)
manifest['status'] = 'compiled; test pending'
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
result = subprocess.run([str(OUT / 'bao-composition-tests'), '--test-threads=2', '--nocapture'], cwd=RUST)
manifest['status'] = 'passed' if result.returncode == 0 else 'failed'
manifest['test_exit'] = result.returncode
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
raise SystemExit(result.returncode)
