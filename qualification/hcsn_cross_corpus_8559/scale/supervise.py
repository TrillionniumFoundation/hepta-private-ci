"""Recover a stopped matrix and finish seal, cold inference and recount in that order."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent


def busy(work):
    for p in (work/'fits').glob('*/fit.lock'):
        with p.open('a') as file:
            try:fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return True
    return False


def observed(work):
    progress={};last=(work/'data/data.json').stat().st_mtime
    for p in sorted((work/'fits').glob('*/progress.json')):
        v=json.loads(p.read_text());progress[p.parent.name]=(v['step'],v['train_cpu'],v['clock_done'])
        last=max(last,p.stat().st_mtime)
    return progress,last


def call(args,path):
    with path.open('a') as f:
        subprocess.run([sys.executable,*map(str,args)],check=True,stdout=f,stderr=subprocess.STDOUT)


def run(w,law,cpu):
    w=w.resolve();law=law.resolve();os.sched_setaffinity(0,{cpu})
    with (w/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while len(list((w/'fits').glob('*/selected.json')))!=12:
            progress,last=observed(w)
            if time.time()-last>900 and not busy(w):
                print('recovering stopped training matrix from saved states',flush=True)
                call([HERE/'matrix.py',w,law,'--cpu',cpu],w/'training.log')
            else:
                time.sleep(30)
        call([HERE/'timing.py',w],w/'supervisor.log')
        call([HERE/'confirmation.py',w,law,'--seal'],w/'confirmation.log')
        print('source-only seal ready',flush=True)
        call([HERE/'confirmation.py',w,law,'--confirm'],w/'confirmation.log')
        call([HERE/'recount.py',w],w/'confirmation.log')
        print('full registered fit and confirm complete',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('law',type=Path);p.add_argument('--cpu',type=int,default=5);args=p.parse_args();run(args.work,args.law,args.cpu)
