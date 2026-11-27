"""Run one cell at a time, seal all weights, then launch cold score processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from panel import ARMS, SEEDS, LEVELS, digest, write


def summarize(out):
    import numpy as np
    results = {}
    per_row = {}
    for arm in ARMS:
        all_scores = []
        entries = []
        for seed in SEEDS:
            sub=out/f'{arm}-{seed}'
            fit = json.loads((sub/'fit.json').read_text())
            test = json.loads((sub/'test.json').read_text())
            assert digest(sub/'ranks.npz')==test['ranks_sha256']
            with np.load(sub/'ranks.npz') as z:
                ir, tr, owners = z['image'], z['caption'], z['owner']
                per_image_hits = np.bincount(owners,weights=tr==1,minlength=len(ir))
                captions = np.bincount(owners,minlength=len(ir))
                all_scores.append((ir==1,per_image_hits,captions))
            times={}
            for level in LEVELS:
                times[level]=next((h['complete_s'] for h in fit['history'] if h['within_budget'] and h['value']>=level),None)
            entries.append(dict(seed=seed,dev_r1=fit['best_dev'],test_r1=test['test']['bidir_r1'],
                  selected_step=fit['selected_step'],updates=fit['steps'],parameters=fit['params'],same_threshold_seconds=times))
        image = np.mean([a for a,b,c in all_scores],axis=0)
        caphits = np.mean([b for a,b,c in all_scores],axis=0)
        capn = all_scores[0][2]
        per_row[arm]=(image,caphits,capn)
        results[arm]=dict(seeds=entries,mean_best_development=np.mean([z['dev_r1'] for z in entries]),
             mean_test=np.mean([z['test_r1'] for z in entries]))
    conventional = max((r for r in ARMS if r!='physical'), key=lambda r:results[r]['mean_best_development'])
    draws = np.random.default_rng(271101).integers(0,len(image),size=(4000,len(image)))
    for name in ARMS:
        a,b,c=per_row['physical']; aa,bb,cc=per_row[name]; assert np.array_equal(c,cc)
        diff=.5*((a-aa)[draws].mean(axis=1)+(b-bb)[draws].sum(axis=1)/c[draws].sum(axis=1))
        results[name]['physical_minus_candidate_cluster_paired95']=np.quantile(diff,[.025,.975]).tolist()
    write(out/'summary.json',dict(development_selected_conventional=conventional,
          results=results,gallery_images=len(image),gallery_captions=int(capn.sum()),same_gallery_previously_observed=True))


def main():
    parser=argparse.ArgumentParser()
    for key in ("upstream","repo","out","inputs"):
        parser.add_argument("--"+key,required=True,type=lambda p:Path(p).resolve())
    a=parser.parse_args()
    a.out.mkdir(exist_ok=True,parents=True)
    root=Path(__file__).resolve().parent
    source={f.name:digest(f) for f in [root/'panel.py',root/'controls.py',root/'PROTOCOL.md',root/'run.py']}
    if (a.out/'experiment.json').exists(): assert json.loads((a.out/'experiment.json').read_text())['source']==source
    else: write(a.out/'experiment.json',dict(source=source,created_epoch=time.time(),upstream_head='cf5aa0c954e92fbecd3a53494ccefaa37a2bb7d0'))
    options=[j for name in ("upstream","repo","out","inputs") for j in ("--"+name,str(getattr(a,name)))]
    for phase in ('fit','test'):
        if phase=='test':
            states={f'{arm}-{seed}':digest(a.out/f'{arm}-{seed}'/'selected.pt') for arm in ARMS for seed in SEEDS}
            if (a.out/'seal.json').exists():assert states==json.loads((a.out/'seal.json').read_text())
            else:write(a.out/'seal.json',states)
            for seed in SEEDS:
                common=[json.loads((a.out/f'{arm}-{seed}'/'fit.json').read_text())['common_initial'] for arm in ARMS]
                assert all(values==common[0] for values in common)
        for i,seed in enumerate(SEEDS):
            for arm in ARMS[i:]+ARMS[:i]:
                cmd=[sys.executable,str(root/'panel.py'),phase,arm,str(seed),*options]
                start=time.monotonic()
                p=subprocess.run(cmd,check=False)
                with (a.out/'costs.jsonl').open('a') as f:
                    f.write(json.dumps(dict(phase=phase,arm=arm,seed=seed,exit=p.returncode,
                        whole_process_seconds=time.monotonic()-start,ended_epoch=time.time()))+'\n')
                if p.returncode:raise SystemExit(f'cell {phase}/{arm}/{seed} exit {p.returncode}')
    summarize(a.out)


if __name__=='__main__':
    main()
