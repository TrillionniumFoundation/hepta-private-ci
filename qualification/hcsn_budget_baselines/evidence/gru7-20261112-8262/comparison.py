"""Compare retained pilot bytes only; no training or model forward pass."""

import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np
import torch

HCSN = Path('/dev/shm/hepta-hcsn-full-002')
GRU = Path('/dev/shm/hepta-hcsn-gru-001')
REPOSITORY = Path('/workspace/scratch/8262eeaa059c/hcsn-boundary-work')
OUT = Path(__file__).parent
STARTED = time.perf_counter()
INPUTS, FAILURES = {}, []


def read(path):
    raw = path.read_bytes()
    INPUTS[str(path)] = hashlib.sha256(raw).hexdigest()
    return raw


def json_read(path):
    return json.loads(read(path))


def check(condition, message):
    if not condition:
        FAILURES.append(message)


def metrics(logits, labels):
    x = np.asarray(logits, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    x = x - x.max(axis=1, keepdims=True)
    ce = np.mean(np.log(np.exp(x).sum(axis=1)) - x[np.arange(len(y)), y])
    return dict(cross_entropy=float(ce), accuracy=float(np.mean(x.argmax(axis=1) == y)))


def interfaces(state, prefix):
    return {key[len(prefix):]: value for key, value in state.items() if key.startswith(prefix)}


def equal_tensors(left, right):
    return set(left) == set(right) and all(torch.equal(left[key], right[key]) for key in left)


h = json_read(HCSN / 'SUMMARY.json')
g = json_read(GRU / 'SUMMARY.json')
review = json_read(Path('/dev/shm/hepta-hcsn-gru-review-001/RESULT.json'))
check(review['passed'], 'independent baseline saved-byte review passed')
check(h['status'] == g['status'] == 'completed_pilot', 'both complete producer denominators')
seeds = [11, 23, 37]
check(sorted((r['seed'], r['arm']) for r in h['runs']) ==
      sorted((seed, arm) for seed in seeds for arm in ('c0_b0', 'c0_b1', 'c1_b0', 'c1_b1')),
      'exact factorial seed/arm roster')
check(sorted(r['seed'] for r in g['runs']) == seeds, 'exact GRU seed roster')
check(sorted(r['seed'] for r in review['rows']) == seeds, 'exact independent review roster')
for name, summary in [('HCSN', h), ('GRU', g)]:
    check(summary['source_before'] == summary['source_after'], name + ' source immutable producer check')
    for path, digest in summary['source_after'].items():
        check(hashlib.sha256(read(REPOSITORY / path)).hexdigest() == digest,
              name + ' current retained source ' + path)
for name in ('DATA.json', 'PLAN.json'):
    raw = read(HCSN / name)
    digest = hashlib.sha256(raw).hexdigest()
    check(digest == g['inputs'][name]['sha256'], 'identical original input ' + name)
    check(read(Path(g['inputs'][name]['path'])) == raw, 'original and new HCSN input bytes ' + name)
data = json.loads((HCSN / 'DATA.json').read_bytes())
check(h['data_sha256'] == g['inputs']['DATA.json']['sha256'], 'both producer DATA bindings')
check(h['configuration'] == json.loads((HCSN / 'PLAN.json').read_bytes()), 'HCSN plan binding')
check(h['host'] == g['host'], 'same recorded host')
check(h['python'] == g['python'] and h['torch'] == g['torch'], 'same recorded runtime')
check(h['device'] == g['device'] == 'cpu' and h['dtype'] == g['dtype'] == 'float64', 'same CPU FP64')
check(HCSN.stat().st_dev == GRU.stat().st_dev, 'same observed output filesystem device')
check(g['co_tenant'] == str(HCSN), 'recorded concurrent HCSN study')
rows = []
task_labels = np.asarray([episode['task'] for episode in data['development']
                          for label in episode['y'] if label >= 0])
expected_labels = [label for episode in data['development'] for label in episode['y'] if label >= 0]
for seed in seeds:
    hr = next(r for r in h['runs'] if r['seed'] == seed and r['arm'] == 'c1_b1')
    gr = next(r for r in g['runs'] if r['seed'] == seed)
    rr = next(r for r in review['rows'] if r['seed'] == seed)
    hp, gp = HCSN / f'seed{seed}-c1_b1', GRU / f'seed{seed}'
    check(hr['status'] == gr['status'] == 'completed', f'{seed}: both models completed')
    check(hr['actual_optimizer_updates'] == gr['actual_optimizer_updates'] == 32, f'{seed}: equal actual update opportunities')
    check(hr['training_schedule'] == gr['schedule'], f'{seed}: equal episode order')
    check(hr['training_event_positions'] == rr['traced_events'], f'{seed}: equal training event counts')
    check(hr['training_scored_positions'] == rr['training_queries'] == 256, f'{seed}: equal training query counts')
    retained = []
    for label, base, row in [('HCSN', hp, hr), ('GRU', gp, gr)]:
        raw = read(base / 'checkpoint.pt')
        check(hashlib.sha256(raw).hexdigest() == row['checkpoint_sha256'], f'{seed}: {label} checkpoint digest')
        checkpoint = torch.load(io.BytesIO(raw), map_location='cpu', weights_only=True)
        check(checkpoint['configuration']['seed'] == seed, f'{seed}: {label} checkpoint seed')
        check(checkpoint['completed_optimizer_updates'] == 32, f'{seed}: {label} checkpoint updates')
        retained.append(checkpoint['model'])
    common = dict(frontend=equal_tensors(interfaces(retained[0], 'frontend.'),
                                       interfaces(retained[1], 'frontend.')),
                  readout=equal_tensors(interfaces(retained[0], 'network.readout.'),
                                      interfaces(retained[1], 'readout.')))
    check(all(common.values()), f'{seed}: common retained frontend/readout exact tensors')
    hd, gd = json_read(hp / 'development.json'), json_read(gp / 'development.json')
    check(hd['episode_ids'] == gd['episode_ids'] == [e['id'] for e in data['development']], f'{seed}: same D episode order')
    check(hd['labels'] == gd['labels'] == expected_labels and len(expected_labels) == 192, f'{seed}: same 192 D queries')
    hm, gm = metrics(hd['logits'], hd['labels']), metrics(gd['logits'], gd['labels'])
    for label, measured, row in [('HCSN', hm, hr), ('GRU', gm, gr)]:
        check(max(abs(measured[key] - row['development'][key]) for key in measured) < 2e-14,
              f'{seed}: {label} independent logits CE/accuracy')
    tasks = {}
    for task in sorted(set(task_labels)):
        mask = task_labels == task
        hm_task = metrics(np.asarray(hd['logits'])[mask], np.asarray(hd['labels'])[mask])
        gm_task = metrics(np.asarray(gd['logits'])[mask], np.asarray(gd['labels'])[mask])
        tasks[task] = dict(hcsn=hm_task, gru=gm_task,
                           hcsn_minus_gru={key: hm_task[key] - gm_task[key] for key in hm_task})
    rows.append(dict(seed=seed, scored_positions=192, common_interface_tensors_equal=common,
                     hcsn_c1_b1=hm, gru=gm,
                     hcsn_minus_gru={key: hm[key] - gm[key] for key in hm}, per_task=tasks,
                     costs=dict(hcsn_fit_wall=hr['wall_seconds'], hcsn_fit_cpu=hr['cpu_seconds'],
                                gru_fit_wall=gr['wall_seconds'], gru_fit_cpu=gr['cpu_seconds'],
                                gru_components=gr['component_seconds'], hcsn_components=None,
                                hcsn_component_reason='Frozen producer did not record separate compute/retention timers'),
                     capacity=dict(hcsn_joint=dict(trainable_parameters=hr['trainable_parameters'],
                                                  total_parameters=hr['total_parameters'],
                                                  recurrent_payload_bytes=hr['state_payload_bytes']),
                                   gru=gr['capacity'])))
means = {name: {key: float(np.mean([row[name][key] for row in rows])) for key in ('cross_entropy', 'accuracy')}
         for name in ('hcsn_c1_b1', 'gru', 'hcsn_minus_gru')}
for path, digest in INPUTS.items():
    check(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, 'retained input unchanged ' + path)
report = dict(schema='hcsn-gru-common-ceiling-comparison-v1', passed=not FAILURES, failures=FAILURES,
              input_files_sha256=INPUTS, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              seeds=seeds, rows=rows, descriptive_seed_means=means,
              delta_direction='HCSN c1_b1 minus GRU; positive CE is worse; positive accuracy is better',
              shared_development_queries=192, independent_test_sources=0,
              inference_scope='Three initializations on one fixed synthetic D set; no inferential significance claim',
              host=h['host'], output_device=HCSN.stat().st_dev, co_tenancy=True,
              measured_cost_scope='Each fit includes model construction, full trace retention, training, D evaluation, checkpoint and new-model D replay; final result write excluded',
              cost_limitations='Different trace payloads, cold initialization and co-tenancy; no isolated kernel throughput, deployment latency, energy or equal-quality comparison',
              all_factorial_process_wall=h['process_wall_seconds'], all_gru_process_wall=g['process_wall_seconds'],
              process_scope='12-arm factorial and 3-seed GRU process totals are different workloads; do not ratio them as model costs',
              actual_equal_occupancy=False, tuned_strong_baseline=False, adequate_training_established=False,
              readout_caveat='Frozen head tensor equality is verified; the GRU learned 7-to-9 projection changes effective readout flexibility',
              confirmation=False, adoption=False, wall_seconds=time.perf_counter() - STARTED)
with (OUT / 'RESULT.json').open('x') as stream:
    json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write('\n')
print(json.dumps(dict(passed=report['passed'], failures=FAILURES, means=means)))
raise SystemExit(0 if report['passed'] else 1)
