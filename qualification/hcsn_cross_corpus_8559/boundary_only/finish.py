"""Continue incomplete research work from real checkpoints, then seal and score the new galleries."""
import argparse,fcntl,os
from pathlib import Path
import subprocess,sys,time

HERE=Path(__file__).resolve().parent


def main(w,out,law):
    with (out/'completion.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while len(list((out/'fits').glob('*/selected.json')))!=18:
            latest=max((p.stat().st_mtime for p in (out/'fits').glob('*/*')),default=time.time())
            busy=False
            if time.time()-latest>1800:
                for p in (out/'fits').glob('*/fit.lock'):
                    with p.open('a') as f:
                        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        except BlockingIOError:busy=True;break
                if not busy:
                    with (out/'training.log').open('a') as log:
                        subprocess.run([sys.executable,'-u',str(HERE/'train_port.py'),str(w),str(out),str(law)],check=True,stdout=log,stderr=subprocess.STDOUT)
            time.sleep(30)
        while not (out/'NOCAPS_ROSTER.json').exists() or not (out/'RSITMD_ROSTER.json').exists():time.sleep(20)
        subprocess.run([sys.executable,'-u',str(HERE/'confirm_port.py'),str(w),str(out),str(law),'finish'],check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('work',type=Path);p.add_argument('law',type=Path);a=p.parse_args();main(a.source,a.work,a.law)
