"""Status receipts for the finite SHD and MELD experiments on this native host."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import time

BASE=Path.home()/'.local/share/hepta-research'
jobs={'original_SHD':('hcsn-shd-clock-8559',21),'three_modal_MELD':('hcsn-meld-8559',18),'wall_only_SHD':('hcsn-wall-only-shd-8559',15)}
out=BASE/'hcsn-shd-clock-8559'/'observations';out.mkdir(exist_ok=True,parents=True)
def outputs(r,n):
    res={'fit_models_per_rung':{},'frozen_rungs':{},'scored':{}}
    for rung in (30,180,720,1800):
        res['fit_models_per_rung'][rung]=len(list((r/'runs').glob(f'*/rung-{rung}.json')))
        res['frozen_rungs'][rung]=(r/'runs'/f'seal-{rung}.json').is_file()
        res['scored'][rung]=(r/f'cold-{rung}'/'complete.json').is_file()
    if r.name=='hcsn-meld-8559':
        d=r/'data';res['all_official_bytes_verified']=(d/'ACQUIRED.json').is_file()
        if not res['all_official_bytes_verified']:res['acquired_ranges']=len(list((d/'parts').glob('*.part')))
        res['complete_arrays']=(d/'arrays'/'INPUTS.json').is_file()
    if r.name=='hcsn-shd-clock-8559':
        res['raw_host_preprocessing']=[s for s in ('train','test') if (r/'data'/f'{s}-data.json').exists()]
    res['receipt_files']=[p.stem for p in sorted((r/'receipts').glob('*.json'))]
    return res
def active_processes():
    mine=os.getuid();counts={name:0 for name in jobs}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if p.stat().st_uid!=mine:continue
            cwd=os.readlink(p/'cwd');cmdline=(p/'cmdline').read_bytes().split(b'\0')
            if not any(x.endswith((b'/gpu_train.py',b'/cold.py',b'/panel.py',b'/prepare.py',b'/pack_data.py',b'/train.py',b'/supervisor.py',b'/panel_supervisor.py',b'acquire.py')) for x in cmdline):continue
            for name,(leaf,n) in jobs.items():
                if cwd==str(BASE/leaf):counts[name]+=1
        except (OSError,PermissionError):continue
    return counts
def sample():
    summaries={name:outputs(BASE/leaf,n) for name,(leaf,n) in jobs.items()}
    cli=subprocess.run(['nvidia-smi','--query-gpu=name,utilization.gpu,memory.used,power.draw','--format=csv,noheader,nounits'],
                       text=True,capture_output=True,timeout=12)
    return dict(observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),epoch=time.time(),jobs=summaries,
                active_owned_processes=active_processes(),shared_device=cli.stdout.strip())
if __name__=='__main__':
    previous=None
    while True:
        try:
            item=sample();state=json.dumps([item['jobs'],item['active_owned_processes']],sort_keys=True)
            tmp=out/'latest.tmp';tmp.write_text(json.dumps(item,indent=1)+'\n');os.replace(tmp,out/'latest.json')
            if previous!=state:
                with (out/'changes.jsonl').open('a') as f:f.write(json.dumps(item)+'\n')
                previous=state;print(item['observed_utc'],item['active_owned_processes'],flush=True)
            if all(all(row['scored'].values()) for row in item['jobs'].values()):break
        except Exception as exc:print(type(exc).__name__,str(exc)[:160],flush=True)
        time.sleep(50)
