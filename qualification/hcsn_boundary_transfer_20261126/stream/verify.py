"""Validate all persisted receipts, weights and raw predictions using only the standard library."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import subprocess
import sys
import tempfile
import zipfile

from summarize import ARMS,SEEDS,check_metrics


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_bundle(folder,output):
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        checkpoint_archives = {
            'equal_updates_selected_weights.zip': 'selected.pt',
            'equal_updates_wall20_weights.zip': 'wall20.pt',
        }
        for name in ['equal_updates_records.zip', *checkpoint_archives, 'equal_wall_records.zip',
                     'equal_wall_weights.zip', 'wallplus_bundle.zip']:
            with zipfile.ZipFile(folder/name) as archive:
                assert archive.testzip() is None
                if name in checkpoint_archives:
                    expected = {f'campaign/{arm}-{seed}/{checkpoint_archives[name]}'
                                for arm in ARMS for seed in SEEDS}
                    members = archive.namelist()
                    assert len(members) == len(expected) and set(members) == expected
                for member in archive.namelist():
                    p=Path(member)
                    assert not p.is_absolute() and '..' not in p.parts
                archive.extractall(root)
        old=root/'campaign'; wall=root/'wall'; fresh=root/'wallplus'
        subprocess.run([sys.executable,str(folder/'summarize.py'),'--campaign',str(old),'--wall',str(wall),'--output',str(root/'summary')],check=True)
        for f in ['summary.json','slots.csv']:
            assert (root/'summary'/f).read_bytes()==(folder/f).read_bytes()
        previous=read(old/'predictions.json')['qvi_centered-601/fixed_updates']
        assert (old/'sender_intervention.json').read_bytes()==(folder/'sender_intervention.json').read_bytes()
        interventions=read(old/'sender_intervention.json')
        assert interventions['test_ids']==previous['id']
        for case in interventions['rows'].values():
            check_metrics(dict(y=previous['y'],p=case['p']),case['score'])
        result={}; common=None; slots=[]; counts={'fits':0,'weight_files':0}; old_ids=set(previous['id'])
        for campaign in (old,wall,fresh):
            reg=read(campaign/'registration.json'); source=reg.get('source_sha256',reg.get('sources'))
            for filename,expected in source.items():
                assert digest(folder/filename)==expected
            seal=read(campaign/'seal.json')
            pred=read(campaign/'predictions.json') if campaign==fresh else None
            scores=read(campaign/'test.json') if campaign==fresh else None
            for arm in ARMS:
                for seed in SEEDS:
                    key=f'{arm}-{seed}'; slot=campaign/key
                    meta=read(slot/'fit.json'); receipt=read(campaign/(key+'.receipt.json')); assert receipt['exit']==0
                    fit_hash=digest(slot/'fit.json'); ckpt=digest(slot/'selected.pt'); counts['weight_files']+=1;counts['fits']+=1
                    assert meta['checkpoint_sha256']==ckpt
                    if campaign==old:
                        prefix=digest(slot/'wall20.pt'); counts['weight_files']+=1
                        assert meta['wall20_checkpoint_sha256']==prefix and [fit_hash,ckpt,prefix]==seal['roster'][key]
                    else:
                        assert dict(fit=fit_hash,model=ckpt)==seal[key]
                    if campaign!=fresh:
                        continue
                    case=pred[key]; score=check_metrics(case,scores[key]); assert len(set(case['id']))==len(case['id'])
                    identity=(case['id'],case['date'],case['y']); assert common is None or common==identity; common=identity
                    assert not old_ids.intersection(case['id'])
                    eligible=[v for v in meta['validation'] if v['eligible']]; assert eligible
                    assert all(v['seconds']<=20 for v in eligible)
                    assert min(eligible,key=lambda v:v['brier'])['step']==meta['selected_step']
                    slots.append(dict(arm=arm,seed=seed,**score,quality_gate=score['brier']<=.10 and score['balanced_accuracy']>=.90,updates=meta['attempted_updates'],selected_step=meta['selected_step'],cold_wall_s=receipt['launch_to_exit_s']))
        for arm in ARMS:
            rows=[r for r in slots if r['arm']==arm]
            result[arm]={k:mean(r[k] for r in rows) for k in ('accuracy','brier','balanced_accuracy','updates','selected_step')}
            result[arm].update(passing=sum(r['quality_gate'] for r in rows),median_cold_wall_s=median(r['cold_wall_s'] for r in rows))
        deltas={s:next(r['brier'] for r in slots if r['arm']=='qvi_centered' and r['seed']==s)-next(r['brier'] for r in slots if r['arm']=='qvi_raw' and r['seed']==s) for s in SEEDS}
        report=dict(verified_artifacts=counts,fresh_test_n=len(common[0]),fresh_test_positives=sum(common[2]),fresh_test_days=sorted(set(common[1])),overlap_with_older_224=len(old_ids.intersection(common[0])),arms=result,slots=slots,paired_centered_minus_raw_brier=deltas)
        encoded=json.dumps(report,allow_nan=False,sort_keys=True,indent=2)+'\n'
        if output:
            output.write_text(encoded)
        else:
            assert (folder/'wallplus_summary.json').read_text()==encoded
        print('Verified',counts, 'new windows, positives',len(common[0]),sum(common[2]))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);args=p.parse_args()
    verify_bundle(Path(__file__).resolve().parent,args.output)
