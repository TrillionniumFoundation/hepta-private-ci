"""Verify seals, official row labels, paired seeds, held-out accuracy and resource claims."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import zipfile

import numpy as np


ARMS = ('hcsn_frozen', 'hcsn_bp', 'gru_frozen', 'gru_bp', 'flat')
SEEDS = (107, 211, 431)
ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def block_hashes(path):
    groups = []
    current = []
    for line in path.read_bytes().splitlines():
        if line.strip():
            current.append(line)
        elif current:
            groups.append(hashlib.sha256(b'\n'.join(current)).digest())
            current = []
    if current:
        groups.append(hashlib.sha256(b'\n'.join(current)).digest())
    return groups


def summarize(out, data):
    seal = read(out/'seal.json')
    for k, name in [('program','study.py'),('protocol','PROTOCOL.md'),('launcher','launch.py'),('source','SOURCE.json')]:
        assert sha(ROOT/name) == seal[k]
    truth = np.repeat(np.arange(10), 220)
    male = np.arange(len(truth)) % 220 < 110
    result, correct = {}, {}
    for seed in SEEDS:
        for arm in ARMS:
            key = f'{arm}-{seed}'
            item = out/key
            fit, test = read(item/'fit.json'), read(item/'test.json')
            assert seal['roster'][key] == dict(weights=sha(item/'selected.pt'), initialization=sha(item/'initial.pt'), fit=sha(item/'fit.json'))
            assert sha(item/'test.npz') == test['prediction_sha256']
            assert fit['positions']==list(range(0,6600,10))
            with np.load(item/'test.npz', allow_pickle=False) as a:
                assert np.array_equal(a['row'], np.arange(2200)) and np.array_equal(a['y'], truth)
                pred = a['pred']
                assert np.array_equal(pred.shape, truth.shape) and np.isin(pred,range(10)).all()
                score = a['scores']
                assert np.isfinite(score).all() and score.shape == (2200,10)
                assert (np.abs(score[np.arange(2200), pred]-score.max(1)) < 1e-6).all()
                hit = pred == truth
            assert hit.sum() == test['correct']
            assert abs(test['accuracy']-hit.mean()) < 1e-12
            correct[key] = hit
            times=[read(out/f'{p}-{key}-process.json') for p in ('train','test')]
            assert all(p['exit']==0 for p in times)
            result[key]=dict(accuracy=float(hit.mean()), correct=int(hit.sum()),
                             digit_accuracy=[float(hit[truth==d].mean()) for d in range(10)],
                             documented_male_accuracy=float(hit[male].mean()), documented_female_accuracy=float(hit[~male].mean()),
                             train_wall_s=times[0]['wall_seconds'], test_wall_s=times[1]['wall_seconds'],
                             full_wall_s=sum(p['wall_seconds'] for p in times), final_features=fit['dimensions'],
                             ridge_residual=fit['ridge_residual'])
    per_seed={}
    for seed in SEEDS:
        for net in ('hcsn','gru'):
            pair=[read(out/f'{net}_{kind}-{seed}'/'fit.json') for kind in ('frozen','bp')]
            assert pair[0]['initial_state']==pair[1]['initial_state']==pair[0]['final_state']
            assert pair[1]['final_state']!=pair[1]['initial_state']
        base=correct[f'hcsn_frozen-{seed}']
        bp=correct[f'hcsn_bp-{seed}']
        gap=float(base.mean()-bp.mean())
        candidates={arm:result[f'{arm}-{seed}']['accuracy'] for arm in ('flat','gru_frozen','gru_bp')}
        strongest=max(candidates,key=candidates.get)
        sg=float(base.mean()-candidates[strongest])
        per_seed[str(seed)]=dict(frozen_minus_bp=gap, strongest_conventional=strongest,
             frozen_minus_strongest=sg, quality_at_least_70=bool(base.mean()>=.7),
             within_two_points_bp=gap>=-.02-1e-12, within_two_points_strongest=sg>=-.02-1e-12,
             hcsn_pair_digit_delta=[float(base[truth==d].mean()-bp[truth==d].mean()) for d in range(10)],
             hcsn_frozen_only=int((base&~bp).sum()), hcsn_bp_only=int((bp&~base).sum()))
    medians={arm:{metric:statistics.median(result[f'{arm}-{s}'][metric] for s in SEEDS)
                  for metric in ('accuracy','train_wall_s','test_wall_s','full_wall_s')} for arm in ARMS}
    speed=medians['hcsn_frozen']['train_wall_s']<medians['hcsn_bp']['train_wall_s']
    record=dict(seal_hash=sha(out/'seal.json'), rows=result, seed_comparisons=per_seed, medians=medians,
                keep_accuracy=float(np.mean(truth==0)), uniform_chance=.1, faster=bool(speed),
                passed=bool(speed and all(r['quality_at_least_70'] and r['within_two_points_bp'] and r['within_two_points_strongest'] for r in per_seed.values())))
    if data is not None:
        src=read(ROOT/'SOURCE.json')
        files=[data/(part+'_Arabic_Digit.txt') for part in ('Train','Test')]
        assert all(sha(p)==src['data'][p.name] for p in files)
        a,b=[block_hashes(p) for p in files]
        assert (len(a),len(b))==(6600,2200)
        record['source_check']=dict(official_train=len(a),official_test=len(b),
            exact_utterance_line_payload_hash_intersection=len(set(a)&set(b)),
            fit_test_hash_intersection=len(set(a[::10])&set(b)),
            duplicates_within_train=len(a)-len(set(a)),duplicates_within_selected_fit=len(a[::10])-len(set(a[::10])),
            duplicates_within_test=len(b)-len(set(b)))
    return record


def unpack(packed, dest):
    (dest/'seal.json').write_bytes((packed/'seal.json').read_bytes())
    for seed in SEEDS:
        for arm in ARMS:
            key = f'{arm}-{seed}'
            names = {f'{key}/{part}' for part in ('fit.json','test.json','test.npz','initial.pt','selected.pt')}
            names |= {f'{phase}-{key}-process.json' for phase in ('train','test')}
            with zipfile.ZipFile(packed/(key+'.zip')) as archive:
                assert set(archive.namelist()) == names
                for name in names:
                    target = dest/name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(archive.read(name))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('evidence',type=Path)
    p.add_argument('--data',type=Path)
    p.add_argument('--save',type=Path)
    args=p.parse_args()
    if (args.evidence/'hcsn_frozen-107.zip').exists():
        with tempfile.TemporaryDirectory() as tmp:
            unpack(args.evidence,Path(tmp))
            record=summarize(Path(tmp),args.data)
    else:
        record=summarize(args.evidence,args.data)
    if args.save:
        with args.save.open('x') as f: json.dump(record,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({k:v for k,v in record.items() if k!='rows'}, indent=2))
