"""Independent saved-output reconstruction for the four additive work lanes.

This does not import their campaign, model, scoring, or reporting functions.
It verifies evidence integrity and arithmetic, never scientific acceptance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_addressed_flow_20261101 import data
from experiments.hcsn_four_stage_flow_20261031.extended_eval import stress_data

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(actual, expected):
    if actual is None or expected is None:
        assert actual is expected
    else:
        assert np.allclose(actual, expected, rtol=1e-10, atol=1e-12), (actual, expected)


def source_check(mapping):
    for path, expected in mapping.items():
        assert sha(ROOT / path) == expected, path


def missing():
    folder = ROOT / 'experiments/hcsn_missing_answers_20261101/results/run001'
    if not (folder / 'confirmation/SUMMARY.json').exists():
        return dict(status='pending')
    p, c, s = [load(folder / q) for q in ('PROTOCOL.json', 'ALL_CHECKPOINTS.json', 'confirmation/SUMMARY.json')]
    split_evaluation = (folder / 'ALL_CALIBRATIONS.json').exists()
    calibrated = load(folder / 'ALL_CALIBRATIONS.json') if split_evaluation else None
    f = calibrated['identity'] if split_evaluation else load(folder / 'EVALUATION_FREEZE.json')
    assert f['candidate_sha256'] == sha(folder / 'ALL_CHECKPOINTS.json')
    assert f['protocol_sha256'] == sha(folder / 'PROTOCOL.json') == c['protocol_sha256']
    if split_evaluation:
        assert f['evaluation_source_sha256'] == sha(ROOT / 'experiments/hcsn_missing_answers_20261101/evaluation.py')
        assert s['identity'] == f
        assert s['calibration_sha256'] == sha(folder / 'ALL_CALIBRATIONS.json')
        assert len(calibrated['records']) == 36
        calibration_map = {(r['task'],r['core'],r['seed'],r['version']):r['calibration'] for r in calibrated['records']}
    assert len(c['fits']) == 18 and c['failures'] == 0 and c['source_unchanged'] and s['source_unchanged']
    source_check(p['source_hashes'])
    for fit in c['fits']:
        assert sha(folder / fit['checkpoint']) == fit['checkpoint_sha256']
    for task in p['tasks']:
        for seed in p['fit_seeds']:
            assert len({r['input_stream_sha256'] for r in c['fits'] if r['task']==task and r['seed']==seed}) == 1
    rows = s['records'] if split_evaluation else s['rows']
    assert len(rows) == 144
    array_cache = {}
    for r in rows:
        path = folder / 'confirmation' / r['raw_file']
        assert sha(path) == r['raw_sha256']
        conf = p['confirmation']
        cache_key = (r['task'],r['condition'])
        if cache_key in array_cache:
            arrays = array_cache[cache_key]
        elif r['condition'] == 'missing_tokens_128':
            base = data.batch(r['task'], conf['episodes'], conf['seed'], conf['split'], 'missing')
            arrays = stress_data(r['task'], base, 'long_tokens_128')
            available = np.zeros_like(arrays['y'], bool)
            available[:, -4:] = base['target_available'][:, -4:]
            arrays['target_available'] = available
        else:
            arrays = data.batch(r['task'], conf['episodes'], conf['seed'], conf['split'], r['condition'])
        array_cache[cache_key] = arrays
        mask = arrays['y'] >= 0
        for key, value in arrays.items():
            assert hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest() == r['data_sha256'][key]
        with np.load(path, allow_pickle=False) as z:
            raw = {k: z[k] for k in z.files}
        assert np.array_equal(raw['labels'], arrays['y'][mask])
        assert np.array_equal(raw['available'], arrays.get('target_available', mask)[mask])
        cal = calibration_map[(r['task'],r['core'],r['seed'],r['version'])] if split_evaluation else load(folder / 'confirmation' / f"CAL_{r['task']}_{r['core']}_{r['seed']}_{r['version']}.json")
        logits = raw['logits'].astype(np.float64) / cal['temperature']
        e = np.exp(logits-logits.max(-1, keepdims=True)); prob = e/e.sum(-1, keepdims=True)
        assert np.array_equal(prob, raw['probabilities'])
        accepted = prob.max(-1) >= cal['threshold']
        assert np.array_equal(accepted, raw['accepted'])
        labels, available = raw['labels'], raw['available']
        correct = prob.argmax(-1) == labels
        losses = -np.log(prob[np.arange(len(labels)), labels].clip(1e-15))
        brier = ((prob-np.eye(8)[labels])**2).sum(-1)
        expected = dict(accuracy=correct.mean(), all4=correct.reshape(-1,4).all(-1).mean(),
                        nll=losses.mean(), brier=brier.mean(), coverage=accepted.mean(),
                        accepted_correctness=correct[accepted].mean() if accepted.any() else None,
                        accepted_known_coverage=accepted[available].mean() if available.any() else None,
                        accepted_unavailable_rate=accepted[~available].mean() if (~available).any() else None)
        for key, value in expected.items():
            close(r['metrics'][key], value)
        for name, subset in [('known',available),('unavailable',~available)]:
            if not subset.any():
                assert r['metrics'][name] is None
            else:
                v = r['metrics'][name]
                assert v['count'] == subset.sum()
                for key, value in dict(accuracy=correct[subset].mean(), nll=losses[subset].mean(),
                                       brier=brier[subset].mean(), mean_confidence=prob[subset].max(-1).mean()).items():
                    close(v[key], value)
    candidate_rows=[r for r in rows if r['version']=='missing_trained']
    gates=p['gates']
    known=[r['metrics']['known']['accuracy']>=gates['known_accuracy_min'] for r in candidate_rows]
    reliable=[r['metrics']['accepted_correctness'] is not None and r['metrics']['accepted_correctness']>=gates['accepted_correctness_min'] for r in candidate_rows]
    covered=[r['metrics']['accepted_known_coverage'] is not None and r['metrics']['accepted_known_coverage']>=gates['accepted_known_coverage_min'] for r in candidate_rows]
    strict_gate_summary=dict(candidate_condition_records=len(candidate_rows),
                             known_accuracy_passes=sum(known),accepted_correctness_passes=sum(reliable),
                             accepted_known_coverage_passes=sum(covered),
                             complete_declared_gate=False,
                             reason='At least one required selective-correctness or known-coverage condition fails; unavailable-answer accuracy is not a recovery success criterion')
    assert not (all(reliable) and all(covered)), 'Reassess overall gate if required selective gates pass'
    return dict(status='verified', record_checks=len(rows), fits=len(c['fits']), summary_sha256=sha(folder/'confirmation/SUMMARY.json'),
                strict_gate_summary=strict_gate_summary,
                limits=['No model reexecution', 'Dev Wilson statistic is a threshold-selection heuristic; four within-episode queries and threshold scanning preclude a population reliability certificate',
                        'Historical comparison changes missing-data supervision while preserving equal updates, not equal CPU',
                        'Explicit typed prior and finite generator remain'])


def dynamics():
    lane = ROOT / 'experiments/hcsn_joint_dynamics_20261101'
    paths = sorted(lane.glob('results/run*/SUMMARY.json'))
    if not paths:
        return dict(status='pending')
    folder = paths[-1].parent
    p,c,s = [load(folder/q) for q in ('PROTOCOL.json','ALL_CHECKPOINTS.json','SUMMARY.json')]
    f = load(folder / 'confirmation/FREEZE.json')
    source_check(p['source_hashes'])
    assert f['checkpoint_manifest_sha256'] == sha(folder/'ALL_CHECKPOINTS.json')
    assert c['protocol_sha256'] == sha(folder/'PROTOCOL.json')
    primary = {}
    for fit in c['fits']:
        assert sha(folder/fit['checkpoint']) == fit['sha256']
        for condition in p['conditions']:
            expected = data.batch('dynamics',p['episodes'],p['confirmation_seed'],'confirm',condition)
            path = folder/'confirmation'/f"{fit['arm']}_{fit['seed']}_{condition}.npz"
            with np.load(path,allow_pickle=False) as z:
                logits = z['logits']
                assert str(z['x_sha256']) == hashlib.sha256(expected['x'].tobytes()).hexdigest()
                for key in ('y','dt','observed'):
                    assert np.array_equal(z[key],expected[key])
            mask = expected['y']>=0
            correct = (logits.argmax(-1)==expected['y'])[mask].reshape(p['episodes'],-1)
            row = next(r for r in s['rows'] if (r['arm'],r['seed'],r['condition'])==(fit['arm'],fit['seed'],condition))
            close(row['accuracy'],correct.mean()); close(row['first_post_jump_accuracy'],correct[:,4].mean())
            assert np.flatnonzero(mask[0])[4] == (19 if condition=='resample' else 9)
            if condition=='missing': primary[fit['arm'],fit['seed']] = correct[:,4].astype(float)
    for contrast, other in zip(s['primary_contrasts'],['factorized_flow','transformer'],strict=True):
        differences = np.stack([primary['full_flow',seed]-primary[other,seed] for seed in p['seeds']])
        mean_by_episode = differences.mean(0)
        rng=np.random.default_rng(p['bootstrap']['seed'])
        boot=[mean_by_episode[rng.integers(len(mean_by_episode),size=len(mean_by_episode))].mean() for _ in range(p['bootstrap']['draws'])]
        interval=np.quantile(boot,[.025,.975])
        close(contrast['mean'],mean_by_episode.mean()); close(contrast['seed_differences'],differences.mean(1))
        close(contrast['conditional_episode_interval'],interval)
        assert contrast['pass_gate'] == bool((differences.mean(1)>0).all() and interval[0]>0)
    assert s['mechanism_gate'] == all(r['pass_gate'] for r in s['primary_contrasts'])
    secondary = dict(status='pending')
    if (folder/'secondary_factorial/SUMMARY.json').exists():
        secondary_protocol = load(lane/'SECONDARY_PROTOCOL.json')
        ss=load(folder/'secondary_factorial/SUMMARY.json')
        sf=load(folder/'secondary_factorial/FREEZE.json')
        assert secondary_protocol['primary_protocol_sha256']==sha(folder/'PROTOCOL.json')
        assert sf['secondary_protocol_sha256']==sha(lane/'SECONDARY_PROTOCOL.json')
        assert sf['candidate_manifest_sha256']==sha(folder/'ALL_CHECKPOINTS.json')
        for path,digest in secondary_protocol['source_hashes'].items(): assert sha(lane/path)==digest
        cells={}
        for row in ss['rows']:
            cell,seed,condition=(row[k] for k in ('cell','seed','condition'))
            if cell in ('A','D'):
                model='full_flow' if cell=='A' else 'factorized_flow'
                raw_path=folder/'confirmation'/f'{model}_{seed}_{condition}.npz'
            else:
                raw_path=folder/'secondary_factorial'/f'{cell}_{seed}_{condition}.npz'
            expected=data.batch('dynamics',p['episodes'],p['confirmation_seed'],'confirm',condition)
            with np.load(raw_path,allow_pickle=False) as z:
                assert np.array_equal(z['y'],expected['y'])
                correct=(z['logits'].argmax(-1)==z['y'])[z['y']>=0].reshape(p['episodes'],-1)
            close(row['all_query_accuracy'],correct.mean()); close(row['first_post_jump_accuracy'],correct[:,4].mean())
            if condition=='missing': cells[cell,seed]=correct[:,4].astype(float)
        weights=[[1,-1,0,0],[0,0,1,-1],[1,0,-1,0],[0,1,0,-1],[1,-1,-1,1]]
        for row,coefficient in zip(ss['contrasts'],weights,strict=True):
            differences=np.stack([sum(w*cells[cell,seed] for w,cell in zip(coefficient,'ABCD',strict=True)) for seed in p['seeds']])
            paired=differences.mean(0); rng=np.random.default_rng(p['bootstrap']['seed'])
            draws=[paired[rng.integers(len(paired),size=len(paired))].mean() for _ in range(p['bootstrap']['draws'])]
            close(row['mean'],paired.mean());close(row['seed_differences'],differences.mean(1));close(row['conditional_episode_interval'],np.quantile(draws,[.025,.975]))
        assert ss['primary_gate_unchanged']
        secondary=dict(status='verified',record_checks=len(ss['rows']),contrasts=len(ss['contrasts']),summary_sha256=sha(folder/'secondary_factorial/SUMMARY.json'))
    return dict(status='verified',fits=len(c['fits']),record_checks=len(s['rows']),summary_sha256=sha(folder/'SUMMARY.json'),secondary_factorial=secondary,
                declared_mechanism_gate=s['mechanism_gate'],
                limits=['No model reexecution', 'Intervals conditional on these three checkpoints and this generator',
                        'Factorization removes association at observed boundaries and retains p(state)',
                        'Two unadjusted contrast intervals do not form a simultaneous 95 percent family'])


def propagation():
    folder=ROOT/'experiments/hcsn_propagation_perf_20261101'
    candidates=list(folder.rglob('SUMMARY.json'))
    candidates=[p for p in candidates if '/confirmation' in str(p)]
    if not candidates: return dict(status='pending')
    path=sorted(candidates)[-1]; s=load(path)
    f=load(folder/'SOURCE_FREEZE.json'); source_check(f['source'])
    for task,digest in f['checkpoints'].items(): assert sha(folder/'checkpoints'/f'{task}_flow.pt')==digest
    assert s['numerical_pass'] == all(r['passed'] for r in s['checks'])
    for row in s['results']:
        med={name:float(np.median(values)) for name,values in row['raw_seconds'].items()}
        close(row['median_seconds']['dense'],med['dense']); close(row['median_seconds']['fused'],med['fused'])
        close(row['dense_over_fused'],med['dense']/med['fused'])
    assert s['stable_complete_model_speed_gate'] == all(r['dense_over_fused']>=1.05 for r in s['results'])
    supplements={}
    for filename,key in [('CONTRACT_CHECKS.json','checks'),('INDEPENDENT_GRADIENTS.json','rows')]:
        if (folder/filename).exists():
            report=load(folder/filename);source_check(report['source_sha256'])
            assert report['passed'] == all(r['passed'] for r in report[key])
            supplements[filename]=dict(passed=report['passed'],record_checks=len(report[key]),sha256=sha(folder/filename))
    return dict(status='verified',record_checks=len(s['results']),summary_sha256=sha(path),supplementary_checks=supplements,
                declared_stable_speed_gate=s['stable_complete_model_speed_gate'],
                limits=['Same-weight equivalence and timing only; no retraining', 'Restricted to AddressedModel consumed outputs; cannot replace full ContentModel preparation',
                        'Local complete-model median timing gate, not production tails or an ordinary-model speed advantage'])


def video():
    folder=ROOT/'experiments/hcsn_video_followup_20261101'
    result_paths=[p for p in folder.rglob('RESULT.json') if '/inputs/' not in str(p)]
    if not result_paths: return dict(status='pending')
    path=sorted(result_paths)[-1]; out=path.parent; s=load(path)
    identity=load(folder/'INPUT_IDENTITY.json')
    for row in identity['files']:
        assert sha(folder/row['path']) == row['sha256']
    f=load(out/'CANDIDATE_FREEZE.json'); t=load(out/'TRAINING.json')
    assert f['source_sha256']==sha(folder/'study.py') and f['protocol_sha256']==sha(folder/'PROTOCOL.json')
    for name,digest in f['checkpoints'].items(): assert sha(out/name)==digest
    assert not t['validation_loaded'] and not f['validation_loaded']
    for mod,row in t['selected'].items():
        held=[]
        for outer in row['outer']:
            assert not set(outer['held_actors']) & set(outer['fit_actors'])
            held.extend(outer['held_actors'])
        assert len(held)==len(set(held))==24
    with np.load(out/'VALIDATION_OUTPUTS.npz',allow_pickle=False) as z:
        a={k:z[k] for k in z.files}
    actors=np.unique(a['actor']); differences=[]
    for name in ['AT','AVT']:
        close(s['relation'][name]['accuracy'],np.average((a[name]>=.5)==a['y'],weights=a['sample_weight']))
        close(s['relation'][name]['brier'],np.average((a[name]-a['y'])**2,weights=a['sample_weight']))
    for actor in actors:
        ix=a['actor']==actor; w=a['sample_weight'][ix]; y=a['y'][ix]
        differences.append([np.average(((a['AVT'][ix]>=.5)==y).astype(float)-((a['AT'][ix]>=.5)==y),weights=w),
                            np.average((a['AVT'][ix]-y)**2-(a['AT'][ix]-y)**2,weights=w)])
    differences=np.asarray(differences); close(s['actor_differences'],differences)
    rng=np.random.default_rng(20261101)
    boot=differences[rng.integers(len(actors),size=(10000,len(actors)))].mean(1)
    intervals=np.quantile(boot,[.025,.975],axis=0).T
    close(s['AVT_minus_AT']['accuracy_actor_bootstrap_95'],intervals[0]); close(s['AVT_minus_AT']['brier_actor_bootstrap_95'],intervals[1])
    assert not s['genuinely_external_confirmation'] and not s['analytic_core_contribution']
    return dict(status='verified',restored_input_files=len(identity['files']),record_checks=len(actors),actors=len(actors),result_sha256=sha(path),
                declared_video_gate=s['video_gate'],
                optimizer_failed_fits=sum(not r['success'] for r in t['fits']),
                limits=['Six historically exposed validation actors; development only', 'No new raw-video acquisition or independent frontend qualification',
                        'Encoder folds are nested by actor; relation heads train on nested out-of-fold train probabilities',
                        'Bootstrap over six development actors is descriptive, not independent population confirmation'])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,default=HERE/'INDEPENDENT_REVIEW.json'); args=parser.parse_args()
    result=dict(schema='hcsn.addressed-continuation.independent-review.v1',reviewer='independent_agent',
                created_utc=datetime.now(timezone.utc).isoformat(),review_source_sha256=sha(__file__),
                scope='Independent source reading and saved-output reconstruction; not an independent model implementation or rerun',
                findings=[dict(id='CAL-01',severity='reporting_limit',status='communicated_to_owner',
                               detail='Threshold-selected dev Wilson bound pools four dependent queries per episode; it is not a coverage-adjusted population reliability certificate.'),
                          dict(id='DYN-01',severity='reporting_limit',status='source_explicit',
                               detail='Dynamics bootstrap is conditional on fixed checkpoints; no population-of-seeds inference or simultaneous two-contrast coverage.'),
                          dict(id='PERF-01',severity='scope_limit',status='source_explicit',
                               detail='Fused adapter omits J/G/b consumed by ContentModel but unused by AddressedModel; context is restricted to addressed calls.'),
                          dict(id='VIDEO-01',severity='scope_limit',status='source_explicit',
                               detail='Nested encoder train folds improve fitting discipline; six previously exposed validation actors remain development evidence.')],
                lanes={},scientific_advantage_established=False,all_blockers_closed=False,production_activation=False)
    for name,fn in [('missing_answers',missing),('joint_dynamics',dynamics),('propagation',propagation),('video',video)]:
        try: result['lanes'][name]=fn()
        except Exception as exc: result['lanes'][name]=dict(status='failed_review',error=f'{type(exc).__name__}: {exc}')
    result['all_available_evidence_checks_passed']=all(r['status']=='verified' for r in result['lanes'].values())
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({k:v['status'] for k,v in result['lanes'].items()},sort_keys=True))


if __name__=='__main__': main()
