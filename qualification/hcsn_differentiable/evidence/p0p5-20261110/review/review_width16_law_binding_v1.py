"""Independent source/checkpoint/trace/law checks; no slow oracle rerun."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback
import torch

BASE = Path('/workspace/scratch/c385a7439f8e')
ROOT = BASE / 'numerics-width16-v6-audit-v1'
OUT = BASE / 'width16-independent-law-binding-v1.json'
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
load = lambda path: json.loads(Path(path).read_text())
started = time.perf_counter()
report = {'schema': 'hcsn-width16-independent-law-binding-v1',
          'created_utc': datetime.now(timezone.utc).isoformat(),
          'reviewer': '/root/math_contract', 'passed': False,
          'scientific_admission': 'HOLD', 'slow_oracles_recomputed': False,
          'scope': 'Source, checkpoint, actual trace and finite-law input linkage only.',
          'review_source_sha256': sha(Path(__file__)), 'checks': []}


def record(name, **fields):
    report['checks'].append({'name': name, 'passed': True, **fields})


def state_digest(state):
    h = hashlib.sha256()
    for name, value in sorted(state.items()):
        h.update((json.dumps([name, str(value.dtype), list(value.shape)],
                            sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode())
        h.update(value.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def trace(path):
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    rows = [json.loads(line) for line in lines]
    head, visits, tail = rows[0], rows[1:-1], rows[-1]
    assert tail['kind'] == 'end' and not tail['truncated'] and tail['dropped_records'] == 0
    assert hashlib.sha256(b''.join(lines[:-1])).hexdigest() == tail['prefix_sha256']
    assert tail['source_unchanged'] and head['sources'] == tail['sources_after']
    assert tail['seen_records'] == tail['retained_records'] == len(visits)
    assert [r['index'] for r in visits] == list(range(len(visits)))
    for name, digest in head['sources'].items():
        suffix = name.split('qualification/hcsn_differentiable/')[-1]
        assert sha(ROOT/'source/qualification/hcsn_differentiable'/suffix) == digest
    return head, visits, tail


try:
    plan, exported = load(ROOT/'plan.json'), load(ROOT/'export-receipt.json')
    report['plan_sha256'], report['runner_sha256'] = sha(ROOT/'plan.json'), sha(ROOT/'runner.py')
    sources = {str(p.relative_to(ROOT/'source')): sha(p) for p in (ROOT/'source').rglob('*.py')}
    assert sources == plan['source_before'] == exported['source_before'] == exported['source_after']
    assert exported['source_unchanged'] and exported['wrapper_unchanged']
    assert exported['plan_sha256'] == report['plan_sha256']
    assert exported['runner_sha256'] == report['runner_sha256']
    probe = load(ROOT/'training-probe/RESULT.json')
    assert sha(ROOT/'training-probe/RESULT.json') == plan['training_receipt_sha256']
    for name, digest in probe['artifacts'].items():
        assert sha(ROOT/'training-probe'/name) == digest
    assert sha(ROOT/'training-probe/after.pt') == plan['checkpoint_sha256']
    assert sha(ROOT/'training-probe/training-domain.jsonl') == plan['training_trace_sha256']
    initial = torch.load(ROOT/'training-probe/initial.pt', map_location='cpu', weights_only=True)
    after_object = torch.load(ROOT/'training-probe/after.pt', map_location='cpu', weights_only=True)
    after = after_object['model']
    changed = [name for name in initial if not torch.equal(initial[name], after[name])]
    assert changed and all(not name.startswith(('frontend.', 'head.')) and '.physics.' not in name for name in changed)
    assert all(float(v['step']) == 2 for v in after_object['optimizer']['state'].values())
    prefix = 'core.network.'
    network_initial = {k[len(prefix):]: v for k, v in initial.items() if k.startswith(prefix)}
    network_after = {k[len(prefix):]: v for k, v in after.items() if k.startswith(prefix)}
    initial_digest, final_digest = state_digest(network_initial), state_digest(network_after)
    assert state_digest(after) == exported['wrapper_sha256']
    record('exact_source_and_real_two_update_checkpoint', source_files=len(sources),
           changed_tensors=changed, optimizer_steps=2,
           final_network_tensor_sha256=final_digest, final_wrapper_tensor_sha256=state_digest(after),
           model_file_sha256=plan['checkpoint_sha256'], shared_and_physical_tensors_unchanged=True)

    manifest = load(ROOT/'data/data-manifest.json')
    assert sha(ROOT/'data/data-manifest.json') == plan['data_manifest_sha256'] == probe['data_manifest_sha256']
    episodes = {}
    for eid in plan['episodes']:
        path = ROOT/'data'/f'{eid}.json'
        expected = next(row['sha256'] for row in manifest['episodes'] if row['id'] == eid)
        assert sha(path) == expected
        ep = load(path)
        assert ep['partition'] == 'train' and ep['sequence'][0] == 'A'
        assert len(ep['dt']) == len(ep['x']) == len(ep['y']) == 256
        assert all(any(bool(v) for v in row[12:24]) for row in ep['x'])
        episodes[eid] = ep
    record('three_official_A_training_episodes_and_masks', episode_ids=list(episodes),
           source_manifest_sha256=plan['data_manifest_sha256'], D_or_E_episodes=False)

    head, visits, footer = trace(ROOT/'training-probe/training-domain.jsonl')
    assert head['configuration_sha256'] == probe['plan_sha256']
    assert head['data_sha256'] == plan['data_manifest_sha256']
    assert len(visits) == 512
    grouped = {}
    for update in [0, 1]:
        rows = [v for v in visits if v['update_index'] == update]
        assert len(rows) == 256 and [v['position'] for v in rows] == list(range(256))
        identities = {v['model_sha256'] for v in rows}
        assert len(identities) == 1
        grouped[update] = next(iter(identities))
        for row in rows:
            assert row['episode_id'] == 'A01-0' and row['batch_indices'] == [0]
            assert row['dt'] == [episodes['A01-0']['dt'][row['position']]]
        if update == 0:
            assert grouped[update] == initial_digest
    assert grouped[0] != grouped[1] != final_digest
    journal = [json.loads(line) for line in (ROOT/'training-probe/events.jsonl').read_text().splitlines()]
    assert [(x['kind'], x['step']) for x in journal] == [('started', 0), ('completed', 0), ('started', 1), ('completed', 1)]
    assert all(x['events'] == 256 for x in journal if x['kind'] == 'completed')
    record('512_actual_pre_update_training_visits', updates=[0, 1],
           records=512, model_identities=grouped,
           interpretation='Forward visits before optimizer updates 1 and 2; final checkpoint separately evaluated.')

    all_eval = {}
    for entry in exported['traces']:
        eid = entry['episode']
        path = ROOT/f'evaluation-{eid}.jsonl'
        assert sha(path) == entry['sha256']
        h, rows, f = trace(path)
        assert h['configuration_sha256'] == report['plan_sha256']
        assert h['data_sha256'] == sha(ROOT/'data'/f'{eid}.json')
        assert len(rows) == 256 and entry['network_model_sha256'] == final_digest
        assert [r['position'] for r in rows] == list(range(256))
        for row in rows:
            assert row['update_index'] == 2 and row['model_sha256'] == final_digest
            assert row['episode_id'] == eid and row['dt'] == [episodes[eid]['dt'][row['position']]]
        all_eval[eid] = rows
    assert set(all_eval) == set(plan['episodes'])
    record('768_supplementary_final_checkpoint_evaluation_visits', records=768,
           update_index=2, episodes=list(all_eval), training_visit_credit=False)

    path = ROOT/'final-starting-laws.pt'
    assert sha(path) == exported['laws_sha256']
    laws = torch.load(path, map_location='cpu', weights_only=True)
    selected = []
    for fixture in plan['finite_fixtures']:
        eid, pos, intervals = fixture['episode'], fixture['position'], fixture['intervals']
        key = f'{eid}:{pos}:{intervals}'
        law, row = laws[key], all_eval[eid][pos]
        assert torch.equal(law['probability'], torch.tensor(row['posterior'][0], dtype=torch.float64))
        assert law['grid'] == row['grid'] == plan['grid']
        assert law['operator'] == row['operator'] and law['parameters'] == row['parameters']
        assert law['durations'] == episodes[eid]['dt'][pos+1:pos+1+intervals]
        assert len(law['durations']) == intervals
        selected.append({**fixture, 'minimum_dt': min(law['durations']),
                         'maximum_dt': max(law['durations']), 'horizon': sum(law['durations'])})
    assert len(laws) == len(selected) == 5
    record('five_laws_exactly_equal_exported_posteriors_and_actual_future_gaps', fixtures=selected,
           oracle_future_observations=False, oracle_future_labels=False)

    stable_receipts = ['training-audit-receipt.json', 'eval-A04-3072-receipt.json',
                       'finite-1-receipt.json', 'finite-3-receipt.json', 'finite-4-receipt.json']
    completed = []
    for name in stable_receipts:
        path = ROOT/name
        if not path.exists():
            continue
        row = load(path)
        assert row['source_unchanged'] and row['source_before'] == row['source_after'] == sources
        assert row['plan_sha256'] == report['plan_sha256'] and row['runner_sha256'] == report['runner_sha256']
        completed.append({'artifact': name, 'sha256': sha(path), 'execution_status': row['status'],
                          'numerical_status': row.get('audit_status', row.get('fixture_status'))})
    report['completed_stage_observation'] = completed
    report['important_status_distinction'] = 'completed/exit0 means execution finished; use audit_status or fixture_status plus coverage/source flags for numerical admission.'
    report['source_after'] = {str(p.relative_to(ROOT/'source')): sha(p) for p in (ROOT/'source').rglob('*.py')}
    assert report['source_after'] == sources
    report['source_unchanged'] = True
    report['passed'] = True
except Exception:
    report['error'] = traceback.format_exc()
report['wall_seconds'] = time.perf_counter() - started
OUT.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'wall_seconds': report['wall_seconds'], 'error': report.get('error')}))
raise SystemExit(0 if report['passed'] else 1)
