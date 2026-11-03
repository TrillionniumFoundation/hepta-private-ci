#!/usr/bin/env python3
"""Bound resource-control tests to exact source, library and output bytes."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument('--out', type=Path, required=True)
ap.add_argument('--library', type=Path, required=True)
ap.add_argument('--dependencies', type=Path, required=True)
ap.add_argument('--rustc', type=Path, required=True)
a = ap.parse_args()
root = Path(__file__).resolve().parent
a.out.mkdir(exist_ok=False)
shutil.copy2(root / 'probe/full_profile_budgets.rs', a.out / 'main.rs')
shutil.copy2(root / 'probe/compatible_value.rs', a.out / 'safe_yaml.rs')
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
inputs = {str(p): sha(p) for p in [a.out / 'main.rs', a.out / 'safe_yaml.rs', a.library]}
argv = [str(a.rustc), '--edition=2024', '--test', '-C', 'debuginfo=0', '-C', 'opt-level=0', '-L', 'dependency=' + str(a.dependencies), '--extern', 'serde_saphyr=' + str(a.library)]
for name in ['serde', 'ryu', 'indexmap']:
    paths = list(a.dependencies.glob('lib' + name + '-*.rlib'))
    assert len(paths) == 1
    inputs[str(paths[0])] = sha(paths[0])
    argv += ['--extern', name + '=' + str(paths[0])]
argv += [str(a.out / 'main.rs'), '-o', str(a.out / 'probe')]
records = []
for name, command in [('compile', argv), ('run', [str(a.out / 'probe'), '--nocapture'])]:
    start = time.monotonic()
    p = subprocess.run(command, capture_output=True, timeout=60)
    (a.out / (name + '.stdout')).write_bytes(p.stdout)
    (a.out / (name + '.stderr')).write_bytes(p.stderr)
    records.append({'name': name, 'argv': command, 'exit_code': p.returncode, 'seconds': time.monotonic() - start, 'stdout_sha256': hashlib.sha256(p.stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(p.stderr).hexdigest()})
    print(json.dumps(records[-1]), flush=True)
    print(p.stdout.decode(), p.stderr.decode())
    if name == 'compile' and p.returncode:
        break
(a.out / 'RECEIPT.json').write_text(json.dumps({'schema': 'full-profile-resource-probe-v1', 'orchestrator_sha256': sha(__file__), 'orchestrator_argv': sys.argv, 'inputs_sha256': inputs, 'records': records, 'inputs_unchanged': all(sha(p) == h for p, h in inputs.items()), 'compiler': subprocess.check_output([str(a.rustc), '--version'], text=True).strip(), 'compiler_sha256': sha(a.rustc), 'production_accepted': False}, indent=2) + '\n')
