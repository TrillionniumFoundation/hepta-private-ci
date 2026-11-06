"""Hash retained R1 files and verify every saved numerical tensor on its owner host."""
from pathlib import Path
import hashlib
import json
import os
import resource
import subprocess
import sys
import time

ROOT = Path('/home/qq/work/hepta-r1-4835-20261105-w0-r1')
TARGET = ROOT / 'RETAINED_FILE_MANIFEST.json'
assert not TARGET.exists(), 'Refuse to replace a retained inventory.'
start = time.process_time(), time.perf_counter()
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
rows = []
for folder in ('evidence', 'source', 'models'):
    for path in sorted((ROOT / folder).rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Unexpected symlink in evidence tree: ' + str(path))
        if path.is_file():
            rows.append({'path': str(path.relative_to(ROOT)), 'size': path.stat().st_size,
                         'sha256': digest(path), 'category': folder})
for name in ('SOURCE_SUBSET.json', 'LEGACY_PROBE_PLAN.json', 'capture_actual_tensors.py', 'replay_historical_prompts.py'):
    path = ROOT / name
    rows.append({'path': name, 'size': path.stat().st_size, 'sha256': digest(path), 'category': 'source_receipt'})
import torch
from safetensors import safe_open
observations = []
for row in rows:
    if row['path'].startswith('evidence/') and row['path'].endswith('.safetensors'):
        path = ROOT / row['path']
        with safe_open(path, framework='pt', device='cpu') as handle:
            assert handle.keys() == ['observed'], str(path)
            tensor = handle.get_tensor('observed').detach().cpu().contiguous()
            raw_sha = hashlib.sha256(tensor.view(torch.uint8).numpy().tobytes()).hexdigest()
            assert raw_sha == path.stem == handle.metadata()['raw_tensor_sha256'], str(path)
            finite = bool(torch.isfinite(tensor).all()) if tensor.is_floating_point() else None
            assert finite is not False, str(path)
            observations.append({'path': row['path'], 'raw_tensor_sha256': raw_sha,
                                 'shape': list(tensor.shape), 'dtype': str(tensor.dtype), 'finite': finite})
receipt = {'schema': 'hepta.r1-retained-files.v1', 'host': 'ai395', 'root': str(ROOT),
           'source_sha': '975e1a264c14ed3da02dcee23a64327825387e42',
           'generator_sha256': sys.argv[1], 'status': 'completed', 'created_unix': time.time(),
           'scope': 'Every regular file under evidence/, source/, models/, plus the four listed source receipts. No tensor body is omitted from this inventory.',
           'excluded': {'venv': 'Installed package versions are captured exactly in evidence/freeze.log; this inventory does not hash each dependency file.',
                        'self': 'The manifest cannot contain its own digest; retrieval receipt records its SHA256.'},
           'files': rows, 'file_count': len(rows), 'retained_bytes': sum(x['size'] for x in rows),
           'tensor_verification': observations, 'tensor_files': len(observations),
           'tensor_bytes': sum(x['size'] for x in rows if x['path'].startswith('evidence/') and x['path'].endswith('.safetensors')),
           'cpu_seconds': time.process_time()-start[0], 'wall_seconds': time.perf_counter()-start[1],
           'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
           'energy_joules': None, 'training_performed': False, 'production_qualified': False,
           'cost_scope': 'Hashing all declared retained source, model and evidence files, reading actual tensor values and constructing manifest before its final write.'}
TARGET.write_text(json.dumps(receipt, indent=2, allow_nan=False)+'\n')
print(json.dumps({'manifest': str(TARGET), 'sha256': digest(TARGET), 'file_count': receipt['file_count'],
                  'tensor_files': receipt['tensor_files'], 'tensor_bytes': receipt['tensor_bytes'],
                  'cpu_seconds': receipt['cpu_seconds'], 'wall_seconds': receipt['wall_seconds']}), flush=True)
probe_start = time.process_time(), time.perf_counter()
probe = {'schema': 'hepta.r1-git-readiness-probe.v1', 'host': 'ai395', 'commands': []}
for args in (['git', '--version'], ['git', 'ls-remote', '--exit-code', 'https://github.com/TrillionniumFoundation/hepta-private-ci.git', 'refs/heads/research/ndu-input-diagnostics-20261105']):
    try:
        done = subprocess.run(args, text=True, capture_output=True, timeout=40,
                              env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
        probe['commands'].append({'argv': args, 'exit_code': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr})
    except Exception as error:
        probe['commands'].append({'argv': args, 'error': {'type': type(error).__name__, 'message': str(error)}})
probe['cpu_seconds'] = time.process_time()-probe_start[0]
probe['wall_seconds'] = time.perf_counter()-probe_start[1]
probe['cost_scope'] = 'Read-only Git readiness checks; subprocess CPU is not included in parent process_time.'
(ROOT / 'GIT_READINESS.json').write_text(json.dumps(probe, indent=2)+'\n')
print(json.dumps(probe), flush=True)
