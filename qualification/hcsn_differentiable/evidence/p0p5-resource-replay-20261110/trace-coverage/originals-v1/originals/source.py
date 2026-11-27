"""Read original terminal JSON traces and their epoch ledger; no model import."""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import traceback

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
AUDIT = Path('/home/qian-qi/hepta-hcsn-final-numerics-20261110-c385-v1')
OUTPUT = BASE / 'final-retained-trace-labels-v1'
PLAN_SHA = '6ae8bb984d994f0d3fa6963e37d0f4180366a3a7bafd316d887e74f2ef1c7d26'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')


def inspect(name, plan):
    receipt_path = AUDIT/name/'input-receipt.json'
    receipt = read(receipt_path)
    root = Path(receipt['root'])
    require(root == BASE/'campaign-v2'/name, 'unexpected original fit path')
    report, fit_plan = receipt['report'], receipt['fit_plan']
    original_report = root/'result.json'
    require(digest(original_report.read_bytes()) == receipt['bound_files'][str(original_report)]
            and digest((root/'plan.json').read_bytes()) == receipt['bound_files'][str(root/'plan.json')],
            'original report/plan bytes differ from terminal binding')
    require(read(original_report) == report and read(root/'plan.json') == fit_plan,
            'original report/plan differs from bound receipt')
    require(receipt['terminal_kind']=='soft_budget_censored_trained_checkpoint',
            'this inspection requires acknowledged original soft-budget terminal fit')
    source = Path(receipt['source'])
    producer_sources = {}
    for relative in ['proposals/localization-v3/train.py', 'proposals/localization-v3/hcsn_study_support.py',
                     'proposals/localization-v3/cores.py', 'qualification/hcsn_differentiable/training_domain.py']:
        path = source/relative
        expected = report['source_before'][str(path)]
        require(digest(path.read_bytes()) == expected, 'producer source changed')
        producer_sources[str(path)] = expected
    manifest_path = Path(receipt['prepared'])/'data-manifest.json'
    raw_manifest = manifest_path.read_bytes()
    require(digest(raw_manifest) == fit_plan['manifest_sha256'], 'manifest differs')
    manifest = json.loads(raw_manifest)
    episodes = {item['id']: item for item in manifest['episodes'] if item['partition']=='train'}
    require(len(episodes) == report['episodes_train'] and sum(e['events'] for e in episodes.values()) == report['train_events'],
            'training event metadata differs')
    events_path = root/'events.jsonl'
    raw_events = events_path.read_bytes()
    require(digest(raw_events) == report['events_sha256'], 'original epoch ledger differs')
    events = [json.loads(line) for line in raw_events.splitlines()]
    starts = [event for event in events if event['kind']=='epoch_started']
    effective, micro = fit_plan['batch_size'], fit_plan['micro_batch_size']
    updates_per_epoch = (len(episodes)+effective-1)//effective
    capture_plan = []
    for epoch, event in enumerate(starts, 1):
        require(event['epoch'] == epoch, 'epoch-start ledger is not contiguous')
        order = event['episode_order']
        require(len(order)==len(episodes) and set(order)==set(episodes), 'epoch order is not the training set')
        for batch_start in range(0, len(order), effective):
            whole = order[batch_start:batch_start+effective]
            padded = max(episodes[eid]['events'] for eid in whole)
            for start in range(0, len(whole), micro):
                ids = whole[start:start+micro]
                sizes = [episodes[eid]['events'] for eid in ids]
                capture_plan.append({'epoch': epoch, 'phase': 'main',
                    'update_index': (epoch-1)*updates_per_epoch+batch_start//effective,
                    'ids': ids, 'sizes': sizes, 'padded_length': padded})
    path = Path(receipt['original_training_trace'])
    expected_digest = receipt['original_training_trace_sha256']
    require(path.stat().st_size <= 67108864, 'original trace exceeds declared byte limit')
    full_hash, prefix_hash = hashlib.sha256(), hashlib.sha256()
    header = footer = None
    rows = []
    groups = defaultdict(lambda: {'record_slots': 0, 'valid_sample_position_layer_states': 0, 'captures': set(), 'layers': set(), 'model_digests': set()})
    by_capture = defaultdict(lambda: {'record_slots': 0, 'valid_sample_position_layer_states': 0})
    with path.open('rb') as stream:
        for line in stream:
            require(footer is None, 'unexpected bytes after trace footer')
            full_hash.update(line)
            item = json.loads(line)
            if item['kind']=='header':
                require(header is None and not rows, 'duplicate or misplaced header')
                header = item
            elif item['kind']=='end':
                footer = item
                require(prefix_hash.hexdigest()==item['prefix_sha256'], 'trace prefix commitment differs')
                continue
            else:
                require(header is not None and item['kind']=='visit', 'invalid trace row kind')
                require(item['index']==len(rows) and item['layer']==0, 'record slots not contiguous single-layer prefix')
                capture = capture_plan[item['capture']]
                position = item['position']
                require(item['episode_id']=='+'.join(capture['ids']) and item['update_index']==capture['update_index'],
                        'record does not match original epoch/microbatch ledger')
                indices = [i for i, size in enumerate(capture['sizes']) if position<size]
                require(bool(indices) and item['batch_indices']==indices, 'record padding/valid sample indices differ')
                count = len(indices)
                require(all(len(item[k])==count for k in ['prior','posterior','dt','expected_events']), 'sample-vector geometry differs')
                key = (item['update_index'], capture['epoch'], capture['phase'])
                group = groups[key]
                group['record_slots'] += 1
                group['valid_sample_position_layer_states'] += count
                group['captures'].add(item['capture']); group['layers'].add(item['layer'])
                group['model_digests'].add(item['model_sha256'])
                by_capture[item['capture']]['record_slots'] += 1
                by_capture[item['capture']]['valid_sample_position_layer_states'] += count
                rows.append({k: item[k] for k in ['index','capture','position','layer','update_index','batch_indices','episode_id','model_sha256']})
                rows[-1].update(derived_epoch=capture['epoch'], derived_phase=capture['phase'], valid_sample_position_layer_states=count,
                               literal_epoch_field=item.get('epoch'), literal_phase_field=item.get('phase'))
            prefix_hash.update(line)
    require(header is not None and footer is not None, 'missing trace header/footer')
    require(header['schema']=='hcsn-training-domain-v1', 'unexpected trace schema')
    require(full_hash.hexdigest()==expected_digest, 'complete original trace commitment differs')
    require(footer['retained_records']==len(rows) and footer['source_unchanged'] and header['sources']==footer['sources_after'],
            'footer/source/retained counts differ')
    require(header['data_sha256']==fit_plan['manifest_sha256'] and header['configuration_sha256']==report['plan_sha256'],
            'trace data/plan identity differs')
    captures = footer['captures']
    require(captures==report['main_micro_forward_attempts'] and captures<=len(capture_plan), 'capture count differs from main forward ledger')
    visited = capture_plan[:captures]
    seen_slots = sum(max(c['sizes']) for c in visited)
    padded = sum(len(c['sizes'])*c['padded_length']-sum(c['sizes']) for c in visited)
    seen_valid = sum(sum(c['sizes']) for c in visited)
    require(seen_slots==footer['seen_records'] and padded==footer['padded_states_excluded'], 'source/ledger reconstruction does not reproduce original footer')
    require(footer['dropped_records']==seen_slots-len(rows) and footer['truncated']==(seen_slots!=len(rows)), 'truncation counters differ')
    distribution = []
    for (update, epoch, phase), value in sorted(groups.items()):
        distribution.append({'update_index': update, 'derived_epoch': epoch, 'derived_phase': phase,
                             **{k: sorted(v) if isinstance(v,set) else v for k,v in value.items()}})
    valid_retained = sum(row['valid_sample_position_layer_states'] for row in rows)
    require(digest(path.read_bytes())==expected_digest and digest(raw_events)==digest(events_path.read_bytes()), 'original inputs changed during read')
    require(digest(manifest_path.read_bytes())==digest(raw_manifest), 'manifest changed during read')
    require(all(digest(Path(p).read_bytes())==expected for p,expected in producer_sources.items()), 'producer source changed during read')
    return {'name': name, 'passed_integrity_and_label_reconciliation': True,
            'input_receipt_sha256': digest(receipt_path.read_bytes()), 'trace_path': str(path), 'trace_bytes': path.stat().st_size,
            'trace_sha256': expected_digest, 'epoch_ledger_sha256': digest(raw_events),
            'data_manifest_sha256': digest(raw_manifest), 'producer_sources': producer_sources,
            'literal_epoch_and_phase_fields_present': any(r['literal_epoch_field'] is not None or r['literal_phase_field'] is not None for r in rows),
            'epoch_phase_scope': 'Epoch and main phase are derived from exact original epoch_started order, fixed batch/microbatch source and update_index; the raw trace does not record these fields.',
            'retained_record_slots': len(rows), 'retained_valid_sample_position_layer_states': valid_retained,
            'seen_record_slots': seen_slots, 'reconstructed_seen_valid_sample_position_layer_states': seen_valid,
            'seen_valid_scope': 'Source/epoch-ledger/manifest reconstruction, matched to observed captures, seen slots and excluded padding; not stored probability states for dropped rows.',
            'retained_sample_state_fraction_of_reconstructed_seen': valid_retained/seen_valid,
            'distribution': distribution, 'capture_distribution': dict(by_capture), 'footer': footer,
            'post_update_retained_record_slots': sum(r['update_index']>0 for r in rows),
            'post_update_retained_valid_sample_states': sum(r['valid_sample_position_layer_states'] for r in rows if r['update_index']>0),
            'record_labels': rows, 'whole_training_domain_admission': 'HOLD'}


def main():
    started = time.monotonic()
    OUTPUT.mkdir(exist_ok=False)
    source = Path(__file__).read_text() if '__file__' in globals() else sys.orig_argv[sys.orig_argv.index('-c')+1]
    (OUTPUT/'source.py').write_text(source)
    require(digest((AUDIT/'PLAN.json').read_bytes())==PLAN_SHA, 'fixed audit plan differs')
    plan = read(AUDIT/'PLAN.json')
    result = {'schema': 'terminal-original-training-trace-labels-v1', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'source_sha256': digest(source.encode()), 'plan_sha256': PLAN_SHA,
              'actual_model_or_numerical_kernel_executed': False, 'optimizer_updates_executed': 0,
              'concurrency': 'Read-only JSON scan may overlap the unique numerical audit and independent full-D quality replay.',
              'fits': [], 'scientific_admission': 'HOLD', 'whole_training_domain_admission': 'HOLD'}
    for name in plan['fit_roster']:
        try:
            item = inspect(name, plan)
            save(OUTPUT/(name+'.json'), item)
            result['fits'].append({k:v for k,v in item.items() if k not in ['record_labels','producer_sources','footer']})
        except Exception:
            result['fits'].append({'name': name, 'passed_integrity_and_label_reconciliation': False, 'error': traceback.format_exc()})
    result.update(passed=all(r['passed_integrity_and_label_reconciliation'] for r in result['fits']),
                  finished_utc=datetime.now(timezone.utc).isoformat(), wall_sample_seconds=time.monotonic()-started,
                  CPU_sample_seconds=time.process_time(), peak_RSS_sample_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  timing_scope='Sample before final serialization; tiny standalone JSON scan, separate from numerical/original training costs.', energy_joules=None)
    save(OUTPUT/'RESULT.json', result)
    print(json.dumps(result), flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
