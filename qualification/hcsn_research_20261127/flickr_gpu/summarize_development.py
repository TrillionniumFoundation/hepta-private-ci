"""Compact, independently verified development receipts for one sealed GPU budget."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import statistics

ROOT=Path(__file__).resolve().parent
ARMS=('hcsn','smooth','lif','mean','dense')
SEEDS=(17011,24203,39827)


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('budget',type=int);a=p.parse_args();stage=a.budget
    dr=ROOT/'development_archive';src=dr/f'{stage:04d}'
    seal=json.loads((src/'stage_seal.json').read_text());assert seal['budget']==stage and len(seal['receipts'])==15
    records={};pooled={}
    for arm in ARMS:
        xs=[]
        for seed in SEEDS:
            k=f'{arm}-{seed}';f=src/(k+'.json')
            assert sha(f)==seal['receipts'][k]
            d=json.loads(f.read_text());j=d['fit'];v=j['checkpoints'][-1]
            assert d['arm']==arm and d['seed']==seed and v['nominal_s']==stage
            assert hashlib.sha256(json.dumps(j,sort_keys=True,allow_nan=False).encode()).hexdigest()==d['fit_sha256']
            assert sha(dr/'objects'/(d['selected_sha256']+'.pt'))==d['selected_sha256']
            row=dict(seed=seed,current_development_nll=v['nll'],best_so_far_nll=j['best_nll'],best_step=j['best_step'],
                current_steps=j['steps'],current_tokens=j['tokens'],train_seconds=j['train_s'],development_seconds=j['dev_s'],
                train_plus_development_seconds=j['exposure_s'],updates_per_train_second=j['steps']/j['train_s'],
                tokens_per_train_second=j['tokens']/j['train_s'],parameters=j['parameters'],selected_sha256=d['selected_sha256'],
                raw_fit_sha256=d['fit_sha256'],archive_receipt_sha256=seal['receipts'][k],observed_checkpoint_utc=v['at'])
            xs.append(row);records[k]=row
        pooled[arm]={v:statistics.mean(q[v] for q in xs) for v in ('current_development_nll','best_so_far_nll','current_steps','current_tokens','train_seconds','development_seconds','updates_per_train_second','tokens_per_train_second','parameters')}
    dest=src/'development.json'
    report=dict(registered_budget_seconds=stage,development_photos=128,named_seeds=SEEDS,per_arm_mean=pooled,
        all_fifteen=records,primary_test_status='This receipt reads development archives exclusively; the parent test is jointly sealed after 15 complete fits.',
        fixed_stage_seal=sha(src/'stage_seal.json'),environment=sha(ROOT/'panel_gpu/environment.json'),machine='ai395/AMD Radeon 8060S Graphics',
        source='c511a75b04eb24719f9d5e424d190b071c78f261',dataset_manifest=sha(ROOT/'data/manifest.json'),
        duration_notes='Train seconds are synchronized original training loop time. Validation time is measured and cumulatively charged to later budgets. Per-process GPU peak reported by fit.json is cumulative because the source never resets peak memory.')
    raw=json.dumps(report,sort_keys=True,indent=2,allow_nan=False)
    if dest.exists():assert dest.read_text()==raw
    else:dest.write_text(raw)
    print(stage,[(k,round(q['current_development_nll'],5),round(q['current_steps'])) for k,q in pooled.items()],flush=True)


if __name__=='__main__':main()
