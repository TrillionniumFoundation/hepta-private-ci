"""Read completed interface evidence and archive it; never construct or run a model."""
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from zipfile import ZipFile, ZIP_DEFLATED

os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[key] = '1'
import torch
torch.set_num_threads(1)
torch.set_num_interop_threads(1)

started = time.perf_counter()
base = Path(sys.argv[1]).resolve()
run = base / 'interface-001'
out = base / 'interface-001-audit'
out.mkdir(exist_ok=False)
sha = lambda value: hashlib.sha256(value).hexdigest()
read = lambda path: json.loads(path.read_text())

def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')

def filemap(folder):
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlink in original output: ' + str(path))
        if path.is_file():
            data = path.read_bytes()
            result[str(path.relative_to(folder))] = {'bytes': len(data), 'sha256': sha(data)}
    return result

def tensor_digest(state):
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        if not isinstance(tensor, torch.Tensor) or not bool(torch.isfinite(tensor).all()):
            raise ValueError('nonfinite or non-tensor state: ' + name)
        header = json.dumps([name, str(tensor.dtype), list(tensor.shape)], separators=(',', ':')).encode()
        digest.update(len(header).to_bytes(8, 'little'))
        digest.update(header)
        digest.update(tensor.detach().cpu().contiguous().reshape(-1).view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()

before = filemap(run)
suite = read(run / 'suite.json')
features = read(run / 'data/features.json')
data = read(run / 'data/data-manifest.json')
execution = read(base / 'interface-001-execution.json')
expected = {(arm, seed) for arm in ('gru', 'cfc', 'snn_plif', 'ssm_s4d', 'attention', 'hcsn')
            for seed in (20261108, 20261109, 20261110)}
report = {'schema': 'hcsn-localization-v2-read-only-audit-v1', 'checks': {}, 'fits': [],
          'training_or_model_forwards_in_this_audit': 0, 'original_files': before,
          'canonical_state_hash': 'sorted names, dtype, shape, CPU contiguous tensor bytes; length-prefixed JSON headers',
          'failures': [], 'scope': 'interface evidence only; no efficacy ranking or formal fit'}

def check(name, condition):
    report['checks'][name] = bool(condition)
    if not condition:
        report['failures'].append(name)

check('exact_18_arm_seed_pairs', len(suite['attempts']) == 18 and
      {(r['arm'], r['seed']) for r in suite['attempts']} == expected)
check('suite_completed_unchanged', suite['status'] == 'completed_interfaces_only' and
      suite['source_unchanged'] and suite['source_before'] == suite['source_after'])
check('no_formal_fits', suite['formal_fits_started'] == 0)
check('features_digest', sha((run / 'data/features.json').read_bytes()) == data['features_sha256'])
check('frontend_digest', sha((run / 'data/frontend.json').read_bytes()) == data['frontend_sha256'])
check('fixed_event_counts', len(features['train']['y']) == 128 and len(features['dev']['y']) == 64)
dependencies = {}
for row in suite['attempts']:
    name = f"{row['arm']}-{row['seed']}"
    folder = run / name
    actual = read(folder / 'result.json')
    check(name + ':result_matches_suite', all(row.get(k) == v for k, v in actual.items()))
    check(name + ':completed', row['status'] == 'completed_interface_only' and row['exit_code'] == 0
          and row['completed_updates_recorded'] == 4 and row['smoke_fits_started'] == 1
          and row['formal_fits_started'] == 0)
    check(name + ':sources', row['source_unchanged'] and row['source_before'] == row['source_after']
          and row['source_before'] == suite['source_before'])
    check(name + ':common_input', row['features_sha256'] == data['features_sha256']
          and row['frontend_sha256'] == data['frontend_sha256'])
    event_bytes = (folder / 'events.jsonl').read_bytes()
    events = [json.loads(line) for line in event_bytes.splitlines()]
    wanted = ['fit_started'] + [kind for _ in range(4) for kind in
              ('optimizer_step_started', 'optimizer_step_completed')] + ['finished']
    check(name + ':events', sha(event_bytes) == row['events_sha256']
          and [event['event'] for event in events] == wanted
          and [e['update'] for e in events if e['event'] == 'optimizer_step_completed'] == [1, 2, 3, 4])
    check(name + ':logits', sha((folder / 'development-logits.json').read_bytes()) == row['dev_logits_sha256'])
    check(name + ':finite_loss_gradient_receipts', len(row['loss_records']) == 4 and all(
          math.isfinite(record['loss_before_update']) and math.isfinite(record['preclip_gradient_norm'])
          and record['preclip_gradient_norm'] > 0 for record in row['loss_records']))
    initial_path = folder / 'initial.pt'
    initial = torch.load(initial_path, map_location='cpu', weights_only=True)
    check(name + ':initial_file', sha(initial_path.read_bytes()) == row['initialization_sha256'])
    fit = {'arm': row['arm'], 'seed': row['seed'], 'initial_state_sha256': tensor_digest(initial),
           'updates': [], 'trainable_parameters_reported': row['trainable_parameters']}
    frozen = {k: v for k, v in initial.items() if '.physics.' in k}
    previous = fit['initial_state_sha256']
    for index in range(1, 5):
        path = folder / f'update-{index}.pt'
        state = torch.load(path, map_location='cpu', weights_only=True)
        current = tensor_digest(state['model'])
        check(name + f':update{index}:changed', current != previous and set(state['model']) == set(initial))
        check(name + f':update{index}:rows', state['source_rows'] == features['train']['source_rows'][(index-1)*32:index*32])
        steps = [float(v['step']) for v in state['optimizer']['state'].values()]
        check(name + f':update{index}:adam', bool(steps) and all(step == index for step in steps))
        if row['arm'] == 'hcsn':
            check(name + f':update{index}:frozen_physics', bool(frozen) and all(
                  torch.equal(v, state['model'][k]) for k, v in frozen.items()))
        fit['updates'].append({'update': index, 'file_sha256': sha(path.read_bytes()),
                               'state_sha256': current, 'optimizer_parameter_states': len(steps),
                               'rng_sha256': sha(state['rng'].numpy().tobytes())})
        previous = current
    check(name + ':final_file', fit['updates'][-1]['file_sha256'] == row['checkpoint_sha256'])
    if row['arm'] == 'hcsn':
        fit['frozen_physics_state_keys'] = sorted(frozen)
        check(name + ':physics_receipt', row['frozen_parameters_unchanged'] and
              row['model']['profile_sha256'] == 'a6661067b366f386d96782687dee6ace5718ffcd8148b2def3bca286c7293600'
              and row['model']['qualification_sha256'] == '1c31a015de53ad720bfa7ac3e952fdbe494a8251161f5741c49239b247a53ddc')
    else:
        for source, expected_sha in row['model']['source_files_sha256'].items():
            observed = sha(Path(source).read_bytes())
            check(name + ':dependency:' + source, observed == expected_sha)
            dependencies[source] = observed
    if row['arm'] == 'snn_plif':
        fit['plif_diagnostics'] = [record['diagnostics'] for record in row['loss_records']]
        check(name + ':plif_diagnostics', all(0 <= d['spike_fraction'] <= 1 and
              math.isfinite(d['learned_tau']) and d['learned_tau'] > 1 for d in fit['plif_diagnostics']))
    report['fits'].append(fit)
for arm in sorted({arm for arm, _ in expected}):
    rows = [r for r in report['fits'] if r['arm'] == arm]
    check(arm + ':distinct_initial_tensor_states', len({r['initial_state_sha256'] for r in rows}) == 3)
    check(arm + ':distinct_final_tensor_states', len({r['updates'][-1]['state_sha256'] for r in rows}) == 3)
for relative, expected_sha in suite['source_before'].items():
    check('live_source:' + relative, sha((base / 'source' / relative).read_bytes()) == expected_sha)
check('source_zip', sha((base / 'source.zip').read_bytes()) == 'd5d745c839204512ca53d617a7d2dbb84dad94e0de13d382174f67bbd8e59c82')
check('original_outputs_unchanged', filemap(run) == before)
report.update(dependencies_current_sha256=dependencies, native_execution_receipt=execution,
              status='passed_interface_evidence_audit' if not report['failures'] else 'failed_evidence_audit',
              audit_wall_seconds=time.perf_counter()-started, audit_process_cpu_seconds=time.process_time(),
              audit_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
save(out / 'native-audit.json', report)
archive = out / 'interface-001-evidence.zip'
manifest = {}
with ZipFile(archive, 'x', compression=ZIP_DEFLATED, compresslevel=9) as zipped:
    selected = list(sorted(run.rglob('*'))) + [out / 'native-audit.json']
    selected += [p for p in sorted(base.iterdir()) if p.is_file() and p.suffix in ('.json', '.zip', '.py', '.txt', '.log')]
    for path in selected:
        if path.is_file() and not path.is_symlink():
            payload = path.read_bytes()
            relative = str(path.relative_to(base))
            zipped.writestr(relative, payload)
            manifest[relative] = {'bytes': len(payload), 'sha256': sha(payload)}
    zipped.writestr('EVIDENCE_MANIFEST.json', json.dumps(manifest, indent=2, sort_keys=True) + '\n')
save(out / 'archive-receipt.json', {'archive': str(archive), 'sha256': sha(archive.read_bytes()),
     'bytes': archive.stat().st_size, 'original_file_count': len(before), 'archived_files': len(manifest),
     'status': report['status'], 'failures': report['failures']})
print((out / 'archive-receipt.json').read_text())
raise SystemExit(0 if not report['failures'] else 2)
