"""One authorized scheduling-only optimization; no model/budget/source change.

Run seed503 on CPU7 while the existing --all process trains307/401 on CPU6.
If needed, pause the original process before it can reach503, then resume after
the independent worker has exited. This keeps every trajectory intact and
prevents simultaneous writes to the same seed directory.
"""
from __future__ import annotations
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def now():return datetime.now(timezone.utc).isoformat()


def memory():
    root=Path('/sys/fs/cgroup')
    stat={k:int(v) for k,v in (line.split() for line in (root/'memory.stat').read_text().splitlines())}
    events={k:int(v) for k,v in (line.split() for line in (root/'memory.events').read_text().splitlines())}
    return {'current':int((root/'memory.current').read_text()),'limit':int((root/'memory.max').read_text()),
        'anon':stat['anon'],'file_cache':stat['file'],'inactive_file':stat['inactive_file'],'events':events}


def process_identity(pid):
    root=Path('/proc')/str(pid)
    return {'args':(root/'cmdline').read_bytes().split(b'\0'),
            'start_ticks':(root/'stat').read_text().split()[21]}


def main():
    found=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:identity=process_identity(int(path.name))
        except (OSError,IndexError):continue
        if b'rrsnn_v2.coupled.train' in identity['args'] and b'--all' in identity['args']:
            found.append((int(path.name),identity['start_ticks']))
    if len(found)!=1:raise RuntimeError(f'Need exactly one existing --all process, found{len(found)}')
    main_pid,start_ticks=found[0]
    # This capability check is essential: some executors expose host /proc
    # while each command runs in a separate PID namespace. Such environments
    # cannot use this OS-signal coordinator; refuse BEFORE launching a worker.
    try:os.kill(main_pid,0)
    except OSError as error:
        raise RuntimeError('Existing trainer is outside this signal namespace; keep sequential scheduling or use an authorized tool-session coordinator') from error
    target=ROOT/'results/equal_cpu/seed_503/training.json'
    if target.exists():raise RuntimeError('Seed503 already completed; no scheduling change needed')
    fixed=ROOT/'results/fixed_updates/seed_503/training.json'
    if fixed.exists():raise RuntimeError('Seed503 has already started; refuse duplicate trajectory')
    receipt={'schema':'rrsnn.coupled-scheduling.v1','started_at_utc':now(),
        'authorization':'Parent requested CPU7 parallel seed503 while CPU6 --all remains on307/401, with a hard same-directory concurrency guard.',
        'main_pid':main_pid,'main_cpu':6,'parallel_seed':503,'parallel_cpu':7,
        'model_or_budget_changes':False,'same_seed_initialization_permutation_and_path_rng_rules':True,
        'guard':'Pause CPU6 --all with SIGSTOP once401 is within60 process-CPU seconds of its budget if503 is still running; resume after503 exits.',
        'memory_before':memory(),'events':[],'main_was_paused':False}
    path=ROOT/'scheduling_seed503.json'
    def save():
        temporary=path.with_suffix('.json.tmp');temporary.write_text(json.dumps(receipt,indent=2)+'\n');temporary.replace(path)
    def is_same_main():
        try:
            identity=process_identity(main_pid)
            return identity['start_ticks']==start_ticks and b'--all' in identity['args']
        except (OSError,IndexError):return False
    def event(kind,**details):
        row={'time_utc':now(),'event':kind,**details};receipt['events'].append(row);save();print(json.dumps(row),flush=True)
    save();paused=False
    log=(ROOT/'training_seed503_execution.log').open('w')
    env=os.environ.copy();env.update(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    worker=subprocess.Popen(['taskset','-c','7',sys.executable,'-m','rrsnn_v2.coupled.train','--seed','503'],
        cwd=str(ROOT.parent.parent),env=env,stdout=log,stderr=subprocess.STDOUT)
    receipt['parallel_worker_pid']=worker.pid;event('parallel_worker_started',pid=worker.pid)
    try:
        while worker.poll() is None:
            progress=ROOT/'results/trajectory_seed_401/progress.json'
            if progress.exists() and not paused:
                try:status=json.loads(progress.read_text())
                except (OSError,json.JSONDecodeError):status=None
                if status and status['cpu_seconds']>=status['target_cpu_seconds']-60:
                    if not is_same_main():raise RuntimeError('Original training process disappeared or changed identity')
                    os.kill(main_pid,signal.SIGSTOP);paused=True;receipt['main_was_paused']=True
                    event('main_paused_before_seed503',seed401_cpu_seconds=status['cpu_seconds'])
            time.sleep(1.)
        receipt['parallel_returncode']=worker.returncode
        if worker.returncode!=0:raise RuntimeError('Parallel seed503 worker failed; inspect its execution log')
        result=json.loads(target.read_text())
        if result['seed']!=503 or result['milestone']!='equal_cpu' or result['train_cpu_seconds']<result['equal_cpu_target_seconds']:
            raise RuntimeError('Parallel worker did not complete the declared seed503 budget')
        event('parallel_worker_completed',cpu_seconds=result['train_cpu_seconds'],
              wall_seconds=result['train_seconds'],checkpoint_sha256=result['checkpoint_sha256'])
        receipt['completed_successfully']=True
    except Exception as error:
        receipt['completed_successfully']=False;receipt['error']=repr(error)
        raise
    finally:
        if paused and is_same_main():
            os.kill(main_pid,signal.SIGCONT);event('main_resumed')
        log.close();receipt['memory_after']=memory()
        receipt['new_oom_events']=receipt['memory_after']['events']['oom']-receipt['memory_before']['events']['oom']
        receipt['new_oom_kills']=receipt['memory_after']['events']['oom_kill']-receipt['memory_before']['events']['oom_kill']
        receipt['finished_at_utc']=now();save()
    print(json.dumps({'scheduling_completed':True,'main_was_paused':receipt['main_was_paused'],
                      'new_oom_events':receipt['new_oom_events']}),flush=True)


if __name__=='__main__':main()
