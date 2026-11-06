"""Read-only numerical observations over exact #4835 diagnostic code.

The neural computation and six requested cases remain the original implementation.
This separate wrapper materializes each tensor observed by diagnostics._tensor.
Every extra run and observation cost is retained; it confers no semantic acceptance.
"""
from pathlib import Path
import gc
import hashlib
import json
import os
import platform
import resource
import sys
import time

ROOT = Path('/home/qq/work/hepta-r1-4835-20261105-w0-r1')
SOURCE = ROOT / 'source'
OUTPUT = ROOT / 'evidence' / 'raw-capture'
OUTPUT.mkdir(exist_ok=False)
TENSORS = OUTPUT / 'tensors'
TENSORS.mkdir()
sys.path.insert(0, str(SOURCE))
SOURCE_SHA = '975e1a264c14ed3da02dcee23a64327825387e42'
manifest = json.loads((ROOT / 'SOURCE_SUBSET.json').read_text())
for row in manifest['files']:
    assert hashlib.sha256((SOURCE / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
start = time.process_time(), time.perf_counter()
record = {
    'schema': 'hepta.r1-raw-tensor-observer.v1',
    'source_sha': SOURCE_SHA,
    'source_tree': manifest['tree'],
    'observer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'host': 'ai395',
    'python': sys.version,
    'platform': platform.platform(),
    'status': 'started',
    'purpose': 'Supplement exact-source run with complete values of all observed actual input tensors and vision encoder outputs.',
    'semantics_modified': False,
    'production_qualified': False,
    'training_performed': False,
    'energy_joules': None,
    'energy_unavailable_reason': 'No whole-process energy meter configured for this run.',
}
record_path = OUTPUT / 'EXECUTION.json'
def save_record():
    record_path.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
save_record()
try:
    import torch
    from safetensors.torch import save_file
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit import diagnostics
    original_tensor = diagnostics._tensor
    def capture_tensor(value):
        observed = original_tensor(value)
        snapshot = value.detach().cpu().contiguous()
        file = TENSORS / (observed['sha256'] + '.safetensors')
        if not file.exists():
            save_file({'observed': snapshot}, str(file), metadata={
                'raw_tensor_sha256': observed['sha256'],
                'source_sha': SOURCE_SHA,
                'capture': 'read-only diagnostics._tensor observer',
            })
        return {**observed,
                'artifact_relative_path': str(file.relative_to(OUTPUT)),
                'artifact_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                'artifact_bytes': file.stat().st_size}
    diagnostics._tensor = capture_tensor
    summary = diagnostics.execute(
        ROOT / 'models', SOURCE / 'inputs/input.png', SOURCE / 'inputs/direct.png',
        OUTPUT / 'diagnostics', SOURCE_SHA, threads=2, max_tokens=80)
    record['summary'] = summary
    if summary['completed_cases'] != 6 or summary['actual_generate_calls'] != 6:
        raise RuntimeError('raw capture six-case completion failed')
    for row in manifest['files']:
        assert hashlib.sha256((SOURCE / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
    record['status'] = 'completed'
except BaseException as error:
    record['status'] = 'failed'
    record['error'] = {'type': type(error).__name__, 'message': str(error)}
    raise
finally:
    gc.collect()
    record['cpu_seconds'] = time.process_time() - start[0]
    record['wall_seconds'] = time.perf_counter() - start[1]
    record['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    record['cost_scope'] = 'Inclusive imports, six fresh VLM loads, exact diagnostics, numerical observation, serialization and cleanup before final write. Acquisition/setup shared with first run; see parent EXECUTION.json; do not double charge. Agent orchestration/transport is separately unmetered.'
    files = []
    for file in sorted(TENSORS.glob('*.safetensors')):
        files.append({'path': str(file.relative_to(OUTPUT)), 'size': file.stat().st_size,
                      'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    record['tensor_files'] = files
    record['retained_tensor_bytes'] = sum(f['size'] for f in files)
    save_record()
    print(json.dumps(record, indent=2, allow_nan=False), flush=True)
