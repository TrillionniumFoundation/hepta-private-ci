"""Read only terminal JSON metadata; never import a model or open an array."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import time


BASE = Path('/home/qian-qi/hcsn-smallnet-20261124')
EXPECTED = {
    'closure-v1': 63, 'communication-training-v1': 21,
    'dual-training-v1': 12, 'fast-training-v1': 18,
    'baselines-v1': 27, 'joint-training-v1': 9,
    'precision-training-v1': 6, 'av-closure-v4': 9,
    'boundary-center-v1': 12,
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def canonical(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def check(condition, issues, text):
    if not condition:
        issues.append(text)


def stage_cost(root, action, ids, issues):
    value, identity = read(root/(action.upper()+'_EXECUTION.json'))
    rows = next((value[key] for key in ('attempts', 'rows', 'workers')
                 if isinstance(value.get(key), list)), None)
    check(rows is not None, issues, action+' stage missing worker list')
    if rows is not None:
        observed = [r['slot']['id'] if isinstance(r['slot'], dict) else r['slot'] for r in rows]
        check(len(observed) == len(ids) and set(observed) == set(ids), issues,
              action+' stage worker roster differs')
    key = next((k for k in ('children_cpu_seconds_including_shutdown', 'children_cpu_seconds')
                if isinstance(value.get(k), (int, float))), None)
    return {'seconds': value[key] if key else None, 'field': key, 'source': identity,
            'wall_seconds': value.get('wall_seconds')}


def audit_campaign(name, count):
    root = BASE/name
    issues = []
    protocol, pfile = read(root/'PROTOCOL.json')
    digest = canonical(protocol)
    seal, sfile = read(root/'SEAL.json')
    claim, cfile = read(root/'TEST_CLAIM.json')
    terminal_name = 'CAMPAIGN_TERMINAL.json' if name == 'baselines-v1' else 'CAMPAIGN_RECEIPT.json'
    terminal, tfile = read(root/terminal_name)
    slots = protocol['slots']
    ids = [s['id'] for s in slots]
    check(len(slots) == count and len(set(ids)) == count, issues, 'declared roster count or uniqueness differs')
    check(seal['protocol_sha256'] == digest, issues, 'seal protocol identity differs')
    check(set(seal['attempts']) == set(ids), issues, 'seal slot roster differs')
    check(claim['protocol_sha256'] == digest and claim['seal_sha256'] == sfile['sha256'],
          issues, 'test claim is not bound to this complete seal')
    check(terminal['status'] in ('completed', 'completed_with_failures'), issues,
          'campaign did not reach a complete terminal roster')
    cap = protocol['training']['max_updates']
    rows = []
    baseline_cpu = 0.
    baseline_cost_sources = []
    for slot in slots:
        directory = root/slot['id']
        fit, ffile = read(directory/'result.json')
        test, xfile = read(directory/'test_result.json')
        prefix = slot['id']+': '
        check(fit['slot'] == slot and fit['protocol_sha256'] == digest and fit.get('smoke') is False,
              issues, prefix+'fit binding differs or smoke entered formal roster')
        check(test['slot'] == slot, issues, prefix+'test slot differs')
        if 'protocol_sha256' in test:
            check(test['protocol_sha256'] == digest, issues, prefix+'test protocol binding differs')
        test_claim, test_claim_file = read(directory/'TEST_WORKER_CLAIM.json')
        check(test_claim == {'slot': slot, 'protocol_sha256': digest, 'seal_sha256': sfile['sha256']},
              issues, prefix+'test worker claim binding differs')
        if 'seal_sha256' in test:
            check(test['seal_sha256'] == sfile['sha256'], issues, prefix+'test seal binding differs')
        check(seal['attempts'][slot['id']]['result.json'] == ffile['sha256'],
              issues, prefix+'sealed fit result bytes differ')
        check(fit['status'] in ('completed', 'censored_cpu', 'failed'), issues, prefix+'unknown fit terminal status')
        check(0 <= fit['updates'] <= cap, issues, prefix+'actual updates outside protocol limit')
        if fit['status'] != 'failed':
            check((fit['status'] == 'completed') == (fit['updates'] == cap),
                  issues, prefix+'completed/censored status and actual updates disagree')
        check(fit['selected_step'] <= fit['updates'], issues, prefix+'selection exceeds actual updates')
        if 'updates' in test:
            check(test['updates'] == fit['updates'], issues, prefix+'test update count differs')
        if 'training_status' in test:
            check(test['training_status'] == fit['status'], issues, prefix+'test training status differs')
        records = {}
        for action in ('fit', 'test'):
            if name == 'baselines-v1':
                worker_name, launch_name = action+'_worker_cost.json', action+'_launch_cost.json'
            else:
                worker_name = 'worker_cost.json' if action == 'fit' else 'test_worker_cost.json'
                launch_name = 'parent_cost.json' if action == 'fit' else 'test_parent_cost.json'
            worker, wfile = read(directory/worker_name)
            launch, lfile = read(directory/launch_name)
            expected_status = fit['status'] if action == 'fit' else test['status']
            check(worker['status'] == expected_status and worker.get('error') is None,
                  issues, prefix+action+' worker terminal differs')
            expected_rc = 1 if action == 'fit' and fit['status'] == 'failed' else 0
            check(launch.get('error') is None and launch['returncode'] == expected_rc,
                  issues, prefix+action+' launcher terminal differs')
            if action == 'fit':
                for filename, source in ((worker_name, wfile), (launch_name, lfile)):
                    check(seal['attempts'][slot['id']].get(filename) == source['sha256'],
                          issues, prefix+'sealed '+filename+' bytes differ')
            if name == 'baselines-v1':
                baseline_cpu += launch['child_user_cpu_seconds']+launch['child_system_cpu_seconds']
                baseline_cost_sources.append(lfile)
            records[action] = {'worker': wfile, 'launch': lfile,
                               'returncode': launch['returncode'], 'worker_status': worker['status']}
        rows.append({'slot': slot, 'fit_status': fit['status'], 'test_status': test['status'],
                     'actual_updates': fit['updates'], 'attempted_updates': fit.get('attempted_updates'),
                     'selected_step': fit['selected_step'], 'protocol_max_updates': cap,
                     'fit_error': fit.get('error'), 'fit_result': ffile, 'test_result': xfile,
                     'test_worker_claim': test_claim_file,
                     'terminal_records': records})
    if name == 'baselines-v1':
        cost = {'fit_plus_test_full_children_cpu_seconds': baseline_cpu,
                'source': 'Sum of 54 disjoint sequential fit/test launch RUSAGE_CHILDREN deltas',
                'sources': baseline_cost_sources,
                'excluded': 'Stress, program edits, readiness waits, coordinator CPU, install/preflight; no nested worker/body cost added'}
    else:
        fit_cost, test_cost = (stage_cost(root, action, ids, issues) for action in ('fit', 'test'))
        complete = None if fit_cost['seconds'] is None or test_cost['seconds'] is None else fit_cost['seconds']+test_cost['seconds']
        cost = {'fit_plus_test_full_children_cpu_seconds': complete, 'fit': fit_cost, 'test': test_cost,
                'source': 'Sum of the two disjoint fit/test stage RUSAGE_CHILDREN deltas',
                'excluded': 'Coordinator, installation/preflight, interpretation/transport; no nested worker/body/outer cost added'}
    return {'campaign': name, 'root': str(root), 'expected_slots': count, 'declared_slots': len(slots),
            'terminal_training_records': len(rows), 'terminal_test_records': len(rows),
            'fit_status_counts': dict(Counter(r['fit_status'] for r in rows)),
            'test_status_counts': dict(Counter(r['test_status'] for r in rows)),
            'actual_updates_distribution': dict(Counter(str(r['actual_updates']) for r in rows)),
            'attempted_updates_distribution': dict(Counter(str(r['attempted_updates']) for r in rows)),
            'campaign_status': terminal['status'], 'protocol_sha256': digest,
            'protocol_file': pfile, 'seal_file': sfile, 'test_claim_file': cfile,
            'campaign_terminal_file': tfile, 'cost': cost, 'slots': rows,
            'metadata_checks_passed': not issues, 'issues': issues}


def main():
    started, cpu = time.perf_counter(), time.process_time()
    output = BASE/'final-roster-metadata-v2'
    output.mkdir(exist_ok=False)
    campaigns = [audit_campaign(name, count) for name, count in EXPECTED.items()]
    rows = [r for c in campaigns for r in c['slots']]
    result = {
        'schema': 'hcsn-cross-campaign-terminal-metadata-v1',
        'scope': 'Metadata-only count of nine specified frozen campaigns; no model import, dataset generation, checkpoint tensor read, prediction-array read, training, test evaluation or reselection',
        'campaigns': campaigns, 'campaign_count': len(campaigns),
        'expected_training_slots': sum(EXPECTED.values()), 'declared_training_slots': len(rows),
        'fit_status_counts': dict(Counter(r['fit_status'] for r in rows)),
        'test_status_counts': dict(Counter(r['test_status'] for r in rows)),
        'actual_updates_distribution': dict(Counter(str(r['actual_updates']) for r in rows)),
        'all_metadata_checks_passed': all(c['metadata_checks_passed'] for c in campaigns),
        'costs_are_per_campaign_only': True,
        'capability_gate_not_inferred_from_completed_status': True,
        'new_training_or_test_executions': 0,
        'source_sha256': sha(Path(__file__).read_bytes()),
        'metadata_audit_cost': {'wall_seconds': time.perf_counter()-started,
                                'cpu_seconds': time.process_time()-cpu},
    }
    with (output/'CAMPAIGNS.json').open('x') as handle:
        json.dump(result, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({k: result[k] for k in ('campaign_count', 'declared_training_slots',
          'fit_status_counts', 'test_status_counts', 'actual_updates_distribution',
          'all_metadata_checks_passed', 'metadata_audit_cost')}), flush=True)
    for campaign in campaigns:
        print(json.dumps({'campaign': campaign['campaign'], 'fit': campaign['fit_status_counts'],
                          'test': campaign['test_status_counts'], 'updates': campaign['actual_updates_distribution'],
                          'fit_test_children_cpu': campaign['cost']['fit_plus_test_full_children_cpu_seconds'],
                          'issues': campaign['issues']}), flush=True)


if __name__ == '__main__':
    main()
