import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile
import time

ROOT = Path('/home/qq/hepta-common-20261109-e1c98-model-no-update-002')
COMMON = Path('/home/qq/hepta-cell-common-e1c98-20261109')
PLAN = COMMON / 'model-no-update-002-plan-f070.json'
os.umask(0o077)
started_ns = time.time_ns()
started_monotonic = time.monotonic()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write('\n')


assert sha(PLAN) == '429b01e4955c816ff154457e8555ee30f41b879479999df218280727930bf4c2'
plan = json.loads(PLAN.read_text())
collection = ROOT / 'collection'
collection.mkdir(mode=0o700)
materials = []
for item in plan['material_pins']:
    actual = sha(item['path'])
    materials.append({**item, 'observed_sha256': actual, 'matches': actual == item['sha256']})
save(collection / 'MATERIALS_AFTER.json', {'observed_unix_ns': time.time_ns(), 'files': materials,
                                         'all_match': all(item['matches'] for item in materials)})
native = json.loads((ROOT / 'evidence/native-result.json').read_text())
inputs = {label: json.loads((ROOT / f'evidence/{label}-input.json').read_text())
          for label in ('source-task', 'next-task')}
frozen = json.loads((ROOT / 'model/frozen.json').read_text())
evaluation = json.loads((ROOT / 'model/evaluate-result.json').read_text())
checkpoint = ROOT / 'evidence/native-completed-checkpoint.bin'
assert inputs == plan['expected_task_inputs'] == frozen['task_inputs']
assert inputs['source-task']['prompt'] != inputs['next-task']['prompt']
assert sha(checkpoint) == native['checkpoint_sha256']
assert checkpoint.read_bytes()[:8] == b'HEPLCP02'
counts = {row['role']: sum(bool(probe['correct']) for probe in row['rows'])
          for row in evaluation['evaluations']}
forward_calls = sum(probe['model_forward_calls'] for row in evaluation['evaluations'] for probe in row['rows'])
assert counts == {'parent': 3, 'candidate': 1} and forward_calls == 8
assert native['disposition'] == evaluation['disposition'] == 'NoUpdate'
assert native['selected_adapter'] == evaluation['selected_adapter'] == frozen['parent']['adapter']
assert native['selected_artifact_sha256'] == frozen['parent']['file_sha256']
assert native['source_input_sha256'] == sha(ROOT / 'evidence/source-task-input.json')
assert native['next_input_sha256'] == sha(ROOT / 'evidence/next-task-input.json')
save(collection / 'OBSERVED_BINDINGS.json', {
    'inputs_equal_predeclared_plan_and_frozen': True, 'actual_inputs': inputs,
    'prompt_content_distinct': True, 'evaluation_correct_recomputed': counts,
    'evaluation_forward_calls_recomputed': forward_calls, 'checkpoint_magic': 'HEPLCP02',
    'checkpoint_sha256': sha(checkpoint), 'selected_adapter': native['selected_adapter'],
    'selected_artifact_sha256': native['selected_artifact_sha256'],
    'ordinary_daemon_task_loop': False, 'independent_confirmation_tasks': 0,
    'prior_tasks_and_outcomes_exposed': True, 'scientific_status': 'HOLD',
})
unit = 'hepta-runtime-job-1a1c0435e71-5e21-994'
properties = ['LoadState', 'ActiveState', 'SubState', 'ControlGroup', 'TasksCurrent',
              'CPUQuotaPerSecUSec', 'MemoryMax', 'MemoryPeak', 'CPUUsageNSec']
command = ['systemctl', '--user', 'show', unit]
for name in properties:
    command.extend(['-p', name])
systemd = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
live_workers = []
markers = (b'worker.py', b'llm_inherited_runtime.py', b'readback-runner.py', b'codex_hepta_agentd')
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    try:
        if entry.stat().st_uid != os.getuid():
            continue
        raw = (entry / 'cmdline').read_bytes()
        if (str(ROOT).encode() in raw or plan['expected_task_inputs']['source-task']['request_id'].encode() in raw) and any(marker in raw for marker in markers):
            live_workers.append({'pid': int(entry.name), 'cmdline': raw.replace(b'\0', b' ').decode(errors='replace')})
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
save(collection / 'PROCESS_READBACK.json', {
    'observed_unix_ns': time.time_ns(), 'unit': unit, 'systemctl_argv': command,
    'systemctl_exit_code': systemd.returncode, 'systemctl_stdout': systemd.stdout,
    'systemctl_stderr': systemd.stderr, 'matching_live_model_workers': live_workers,
    'scan_scope': 'current UID and this operation output/request plus known model worker executable markers',
})
members = []
for directory in ('model', 'evidence'):
    members.extend((path, str(path.relative_to(ROOT))) for path in sorted((ROOT / directory).rglob('*')) if path.is_file())
for relative in ['model-config.json', 'model-environment.json', 'EXECUTION_STARTED.json',
                 'preparation/RESULT.json', 'preparation/plan.json', 'preparation/tools.json',
                 'preparation/binaries.json', 'preparation/native-prerequisites.json',
                 'preparation/materials-before.json', 'preparation/archive-command.json',
                 'preparation/list-command.json']:
    members.append((ROOT / relative, relative))
for name in ('smollm-prepare-f070-v1', 'smollm-prepare-f070-v2', 'smollm-execute-f070-v1'):
    for suffix in ('.json', '.log', '.log.gz', '.junit.xml'):
        path = COMMON / 'evidence' / (name + suffix)
        if path.exists():
            members.append((path, 'command-records/' + path.name))
for name in ('model-no-update-001-prepare_and_run-v1.py', 'model-no-update-001-plan-f070.json',
             'model-no-update-002-prepare_and_run-v2.py', 'model-no-update-002-plan-f070.json', 'run_common_native.py'):
    members.append((COMMON / name, 'execution/' + name))
members.extend((collection / name, 'collection/' + name) for name in ('MATERIALS_AFTER.json', 'OBSERVED_BINDINGS.json', 'PROCESS_READBACK.json'))
manifest = []
for path, arcname in members:
    assert not path.is_symlink(), path
    size = path.stat().st_size
    metadata = path.suffix not in ('.safetensors', '.pt', '.pkl') and size <= 512000
    manifest.append({'path': str(path), 'archive_path': arcname, 'bytes': size, 'sha256': sha(path),
                     'metadata_archive_included': metadata})
old_root = Path('/home/qq/hepta-common-20261109-e1c98-model-no-update-001')
unbundled = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
             for directory in (old_root, ROOT)
             for path in (directory / 'preparation/source.tar.gz', directory / 'preparation/native-nextest.tar.zst')]
save(collection / 'MANIFEST.json', {'files': manifest, 'total_bytes': sum(item['bytes'] for item in manifest),
                                   'source_and_nextest_archives_bound_separately': unbundled})
members.append((collection / 'MANIFEST.json', 'collection/MANIFEST.json'))
outputs = []
for name, metadata_only in [('raw-all-model.tar.gz', False), ('raw-metadata.tar.gz', True)]:
    destination = collection / name
    with destination.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as archive:
                for path, arcname in members:
                    if metadata_only and arcname != 'collection/MANIFEST.json' and not next(item['metadata_archive_included'] for item in manifest if item['archive_path'] == arcname):
                        continue
                    archive.add(path, arcname=arcname, recursive=False)
    outputs.append({'path': str(destination), 'bytes': destination.stat().st_size, 'sha256': sha(destination), 'metadata_only': metadata_only})
summary = {'schema': 'hepta.common.actual-model-collection.v1', 'files': len(manifest), 'archives': outputs,
           'all_67_material_pins_unchanged': all(item['matches'] for item in materials),
           'matching_live_model_workers': live_workers, 'model_reexecuted': False,
           'independent_confirmation_tasks': 0, 'scientific_status': 'HOLD'}
usage = resource.getrusage(resource.RUSAGE_SELF)
children = resource.getrusage(resource.RUSAGE_CHILDREN)
summary['collection_cost'] = {'started_unix_ns': started_ns, 'completed_unix_ns': time.time_ns(),
                              'wall_seconds': time.monotonic() - started_monotonic,
                              'self_cpu_seconds': usage.ru_utime + usage.ru_stime,
                              'child_cpu_seconds': children.ru_utime + children.ru_stime,
                              'self_peak_rss_kib': usage.ru_maxrss,
                              'energy_joules': None, 'provider_cost': None}
save(collection / 'RESULT.json', summary)
print(json.dumps(summary), flush=True)
assert summary['all_67_material_pins_unchanged'] and not live_workers
