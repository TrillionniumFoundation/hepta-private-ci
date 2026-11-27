"""Rotate eight arms across seeds, preserve all completed cells, then lock and cold-score."""
import os,subprocess,sys,time,json
from pathlib import Path
from model import ARMS
r=Path(os.environ['FULLSTACK_DATA']);src=Path(__file__).resolve().parent
for i,seed in enumerate((109,271,463)):
    for arm in ARMS[i:]+ARMS[:i]:
        p=r/'runs'/f'{arm}-{seed}'
        if not (p/'done.json').is_file():
            tick=time.time();job=subprocess.run([sys.executable,str(src/'study.py'),'fit',arm,str(seed)])
            with (r/'processes.jsonl').open('a') as f:f.write(json.dumps(dict(arm=arm,seed=seed,exit=job.returncode,wall_s=time.time()-tick))+'\n')
            job.check_returncode()
for action in ('seal','confirm'):subprocess.run([sys.executable,str(src/'study.py'),action],check=True)
