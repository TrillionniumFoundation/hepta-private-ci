"""Time each method as a separate one-thread process, and retain errors and exit times."""
import argparse
import datetime
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
HERE=Path(__file__).resolve().parent
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--phase',choices=['construct','bp','edit'],required=True)
    args=ap.parse_args();root=args.root
    if args.phase=='construct':
        roster=[(arm,s) for arm in ('ridge','physical','smooth','random','shuffled') for s in ((137,251,389) if arm in ('random','shuffled') else (137,))]
    elif args.phase=='bp':
        roster=[(arm,s) for arm in ('physical','conv','english') for s in (137,251,389)]
    else:
        roster=[(arm,s) for s in (137,251,389) for arm in ('keep','direct','shuffle','adam','lora')]
    for arm,seed in roster:
        out=root/'fits'/args.phase/f'{arm}-{seed}';out.mkdir(parents=True,exist_ok=True)
        if (out/'supervised.json').exists() and json.loads((out/'supervised.json').read_text())['exit_code']==0:continue
        command=[sys.executable,str(HERE/(args.phase+'.py')),'--data',str(root/'data'),'--out',str(out),'--arm',arm,'--seed',str(seed)]
        if args.phase=='edit':command.extend(['--parents',str(root/'fits'/'bp')])
        for attempt in range(3):
            t=time.perf_counter();r0=resource.getrusage(resource.RUSAGE_CHILDREN)
            with (out/'stdout.log').open('a') as log:
                process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=os.environ)
            rr=resource.getrusage(resource.RUSAGE_CHILDREN)
            receipt=dict(wall_s=time.perf_counter()-t,cpu_s=rr.ru_utime+rr.ru_stime-r0.ru_utime-r0.ru_stime,
                         exit_code=process.returncode,command=[Path(command[0]).name,Path(command[1]).name]+command[2:],
                         completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            (out/'supervised.json').write_text(json.dumps(receipt,indent=2)+'\n')
            print(args.phase,arm,seed,round(receipt['wall_s'],3),process.returncode,flush=True)
            if process.returncode == 0: break
            failed=out/f'failed-attempt-{len(list(out.glob("failed-attempt-*.json")))+1:03d}.json'
            failed.write_text(json.dumps(receipt,indent=2)+'\n')
            if process.returncode!=-9 or attempt>=2:raise SystemExit(process.returncode)
            time.sleep(2.0)
if __name__=='__main__':main()
