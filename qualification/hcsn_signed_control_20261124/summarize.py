"""Read-only descriptive supplement analysis; no training/model imports."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def read(path):
    return json.loads(Path(path).read_text())


def optional(path):
    return read(path) if Path(path).exists() else {'status': 'missing', 'path': str(path)}


def formatted(value, scale=1, digits=2):
    return '—' if value is None else f'{value*scale:.{digits}f}'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def stats(values):
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'sample_std': statistics.stdev(values) if len(values)>1 else None,
            'min': min(values) if values else None, 'max': max(values) if values else None}


def write(path, value):
    with Path(path).open('x') as h:
        json.dump(value, h, indent=2, sort_keys=True, allow_nan=False)
        h.write('\n')


def summarize(root):
    training = root/'training'
    p = read(root/'PROTOCOL_SIGNED.json')
    protocol_sha = canonical(p)
    final, seal, signed = (read(training/name) for name in ('FINAL_RESULTS.json', 'SEAL.json', 'SIGNED_SEAL.json'))
    verifier = read(root/'INDEPENDENT_METRICS_VERIFICATION.json')
    if (final['protocol_sha256'] != protocol_sha or final['seal_sha256'] != sha(training/'SEAL.json')
            or seal['protocol_sha256'] != protocol_sha or signed['protocol_sha256'] != protocol_sha
            or signed['training_seal_sha256'] != sha(training/'SEAL.json')
            or verifier['final_results_sha256'] != sha(training/'FINAL_RESULTS.json')
            or p['supplement']['main_final_results_sha256'] != sha(root/'MAIN_FINAL_RESULTS.json')
            or p['supplement']['main_protocol_sha256'] != canonical(read(root/'MAIN_PROTOCOL.json'))):
        raise ValueError('protocol/seal/independent-verification provenance mismatch')
    for name, expected in p['supplement']['source_hashes'].items():
        if sha(Path(__file__).parent/name) != expected:
            raise ValueError('supplement source changed')
    for module, expected in p['source_hashes'].items():
        path = root.joinpath(*module.split('.'))
        path = path/'__init__.py' if path.is_dir() else path.with_suffix('.py')
        if sha(path) != expected:
            raise ValueError('frozen base source changed')
    expected = {f'n{n}-qvi_signed_only-s{s}': (n,s) for n in p['independent_neurons'] for s in p['seeds']}
    test = {r['attempt']:r for r in final['results']}
    if set(test) != set(expected) or len(final['results']) != len(expected) or set(seal['attempts']) != set(expected):
        raise ValueError('incomplete/duplicate supplemental roster')
    verified = {r['attempt']:r['status'] for r in verifier['rows']}
    baseline = {(r['neurons'],r['arm'],r['seed']):r for r in read(root/'MAIN_FINAL_RESULTS.json')['results'] if r['status']=='evaluated'}
    v = p['validation']
    rows = []
    for name,(n,seed) in expected.items():
        directory = training/name
        train, row = read(directory/'result.json'), test[name]
        if (sha(directory/'result.json') != seal['attempts'][name]
                or train['protocol_sha256'] != protocol_sha
                or train['arm'] != p['arms'][0] or train['neurons'] != n or train['seed'] != seed):
            raise ValueError('sealed training record mismatch')
        if train['checkpoint_sha256'] is not None and sha(directory/'checkpoint.pt') != train['checkpoint_sha256']:
            raise ValueError('checkpoint bytes changed')
        metrics, passed = {}, False
        if row['status']=='evaluated':
            if (row != read(directory/'test_result.json') or verified.get(name)!='verified'
                    or sha(directory/'test_predictions.json') != row['predictions_sha256']
                    or row['data_sha256'] != baseline[n,'qvi_flow',seed]['data_sha256']
                    or row['selected_step'] != train['selected_step'] or name not in signed['masks']):
                raise ValueError('test pair, signed mask or data identity mismatch')
            metrics = {k:row['metrics'][k] for k in ('accuracy','brier','pre_late_accuracy')}
            metrics['final_over_pre_late'] = metrics['accuracy']-metrics['pre_late_accuracy']
            metrics['learned_over_initial'] = metrics['accuracy']-row['initial_metrics']['accuracy']
            passed = (metrics['accuracy']>=v['min_final_accuracy']
                and metrics['final_over_pre_late']>=v['min_final_over_pre_late_accuracy']
                and metrics['learned_over_initial']>=v['min_learned_over_initial_accuracy'])
        receipts = {key:optional(directory/filename) for key,filename in (
            ('worker_cost','worker_cost.json'),('parent_cost','parent_cost.json'),
            ('test_worker_cost','test_worker_cost.json'),('test_parent_cost','test_parent_cost.json'))}
        evidence_verified = all(receipt.get('status')!='missing' for receipt in receipts.values())
        rows.append({'attempt':name,'neurons':n,'seed':seed,'training_status':train['status'],
            'test_status':row['status'],'updates':train['updates'],'selected_step':train['selected_step'],
            'metrics':metrics,'descriptive_learning_gate':passed and evidence_verified,
            'numeric_criteria_pass':passed,'evidence_verified':evidence_verified,
            'training_cpu_seconds':train['training_cpu_seconds'],'fit_body_cost':train['cost'],
            'test_pair_cost':row.get('cost'),**receipts})
    groups, pairs = [], []
    for n in p['independent_neurons']:
        group = [r for r in rows if r['neurons']==n]
        valid = [r for r in group if r['test_status']=='evaluated']
        passing = sum(r['descriptive_learning_gate'] for r in group)
        complete = all(r['evidence_verified'] for r in group)
        group_pass = complete and passing/len(group)>=v['min_fraction_seeds_passing_learning']
        groups.append({'neurons':n,'expected':len(group),'evaluated':len(valid),'passing_seeds':passing,
            'group_pass':group_pass,'all_evidence_verified':complete,
            'group_status':'UNVERIFIED' if not complete else 'PASS' if group_pass else 'FAIL',
            'selected_step_zero':sum(r['selected_step']==0 for r in group),
            'metrics':{k:stats([r['metrics'][k] for r in valid]) for k in
                ('accuracy','brier','pre_late_accuracy','final_over_pre_late','learned_over_initial')},
            'updates':stats([r['updates'] for r in group]),
            'training_cpu_seconds':sum(r['training_cpu_seconds'] for r in group)})
        for arm in ('qvi_flow','qvi_full'):
            pairs.append({'neurons':n,'reference':arm,'direction':'signed_only minus main reference',
                'accuracy_difference':stats([r['metrics']['accuracy']-baseline[n,arm,r['seed']]['metrics']['accuracy'] for r in valid]),
                'brier_difference':stats([r['metrics']['brier']-baseline[n,arm,r['seed']]['metrics']['brier'] for r in valid]),
                'coverage':len(valid),'inference':'descriptive after main results; no p-value or fresh-holdout claim'})
    report = {'schema':1,'experiment_id':p['experiment_id'],'protocol_sha256':protocol_sha,
        'scope':p['claim_scope'],'test_policy':p['test_policy'],'main_protocol_sha256':p['supplement']['main_protocol_sha256'],
        'analysis_source_sha256':sha(__file__),'source_hashes':p['supplement']['source_hashes'],
        'independent_verification_sha256':sha(root/'INDEPENDENT_METRICS_VERIFICATION.json'),
        'max_scalar_error':verifier['max_scalar_error'],'groups':groups,'paired_comparisons':pairs,'attempts':rows,
        'execution':{'fit':read(training/'FIT_EXECUTION.json'),'test':read(training/'TEST_EXECUTION.json'),
            'campaign':read(training/'CAMPAIGN_RECEIPT.json')},
        'cost_note':'Training intervals are included in fit-body and worker CPU; test pairs are included in test-worker CPU. Do not add nested ledgers. Energy unknown.'}
    write(root/'SUMMARY.json',report)
    lines = ['# Signed-only 补充对照','',p['claim_scope'],'',p['test_policy'],'',
        '保留全部9个预定槽位；沿用主试验80% / +10pp / +10pp、至少2/3种子的数值门槛，仅作描述。±为3个seed的样本标准差。','',
        '| N | 准确率±SD (%) | Brier | pre-late (%) | final−pre-late (pp) | final−initial (pp) | 更新数范围 | 门槛 |',
        '|---:|---:|---:|---:|---:|---:|---:|---|']
    for g in groups:
        m=g['metrics']; a=m['accuracy']
        lines.append(f"| {g['neurons']} | {formatted(a['mean'],100)} ± {formatted(a['sample_std'],100)} | {formatted(m['brier']['mean'],digits=3)} | {formatted(m['pre_late_accuracy']['mean'],100)} | {formatted(m['final_over_pre_late']['mean'],100)} | {formatted(m['learned_over_initial']['mean'],100)} | {g['updates']['min']}–{g['updates']['max']} | {g['group_status']} {g['passing_seeds']}/{g['expected']} |")
    lines += ['', '配对方向为 signed-only 减去原主试验的对应seed；使用相同数据、初始化seed和CPU预算，更新次数可能不同。','',
              '| N | 主试验对照 | Δ准确率±SD (pp) |','|---:|---|---:|']
    for row in pairs:
        a=row['accuracy_difference']
        lines.append(f"| {row['neurons']} | {row['reference']} | {formatted(a['mean'],100)} ± {formatted(a['sample_std'],100)} |")
    lines += ['',f"独立 NumPy 指标复核最大误差：{verifier['max_scalar_error']:.3g}。",'',report['cost_note'],'']
    with (root/'RESULTS_SIGNED_ONLY.md').open('x') as h:h.write('\n'.join(lines))
    print(json.dumps({'evaluated':sum(r['test_status']=='evaluated' for r in rows),'expected':len(rows),'groups':groups}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    summarize(parser.parse_args().root)
