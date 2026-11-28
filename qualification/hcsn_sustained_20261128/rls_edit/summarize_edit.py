"""Compact staged effects from the frozen CREMA-D RLSEdit experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from statistics import mean

SEEDS=(137,311,557)


def read(p):return json.loads(p.read_text())


def run(root,dest):
    term=read(root/'terminal.json');seal=read(root/'development_seal.json')
    means={};clock={};bygate={};parity={}
    for arm in term['methods']:
        means[arm]={};clock[arm]={};bygate[arm]={}
        for s in range(6):
            j=str(s);rows=[];fis=[]
            for seed in SEEDS:
                key=f'{seed}/{arm}';stage=read(root/key/f'stage{s}.json');fis.append(stage)
                n=str(seal['picks'][key][j]['primary']);rows.append(term['cold_scores'][key][j]['budgets'][n]['cold'])
                if stage['batch_parity']:
                    for m in ('relative_frobenius','max_absolute'):
                        parity[m]=max(parity.get(m,0),stage['batch_parity'][m])
            means[arm][j]={group:{m:mean(r[group][m] for r in rows) for m in rows[0][group]} for group in rows[0]}
            clock[arm][j]={m:mean(f[m] for f in fis) for m in ('setup_s','stage_algebra_or_gradient_s','stage_development_s','stage_serialization_s','through_stage_s')}
            gs=term['quality_gates'][arm][j]['by_seed'];valid=[v for v in gs.values() if v['qualified']];known=[v for v in gs.values() if 'selected_budget' in v]
            bygate[arm][j]={'development_pass_seeds':len(known),'held_at_dev_selected_passing_seeds':len(valid),
                            'all_three_wall_s':mean(v['charged_qualification_upper_s'] for v in valid) if len(valid)==3 else None}
        clock[arm]['six_stage_algebra_total_s']=sum(clock[arm][str(j)]['stage_algebra_or_gradient_s'] for j in range(6))
    final={k:v['5'] for k,v in term['paired_actor_contrasts'].items()}
    summary={'terminal_sha256':hashlib.sha256((root/'terminal.json').read_bytes()).hexdigest(),'development_seal_sha256':term['seal_sha256'],
          'parents':{s:seal['parents'][str(s)]['parent'] for s in SEEDS},'through_all_stages':means,'time':clock,'quality':bygate,
          'final_actor_intervals':final,'woodbury_batch_max':parity}
    dest.write_text(json.dumps(summary,indent=1,sort_keys=True,allow_nan=False)+'\n')
    print('summary',hashlib.sha256(dest.read_bytes()).hexdigest(),'seal',term['seal_sha256'],'blocks',len(term['cold_scores']),flush=True)
    for arm in term['methods']:
        t=means[arm]['5'];print(arm,'NLL current past protected',*(round(t[k]['nll'],4) for k in ('current','past','protected')),'qualified',
            bygate[arm]['5']['held_at_dev_selected_passing_seeds'],'fit_s',round(clock[arm]['six_stage_algebra_total_s'],3),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('dest',type=Path);a=p.parse_args()
    while not (a.root/'terminal.json').is_file():time.sleep(10)
    run(a.root,a.dest)
