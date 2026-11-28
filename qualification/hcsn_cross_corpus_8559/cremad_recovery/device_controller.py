"""Own one repaired original CREMA-D run and use the original accelerator only when available."""
import argparse,fcntl,json,os,shutil,statistics,subprocess,sys,time
from pathlib import Path

ARMS=('literal','smooth','lif','sdpa')
SEEDS=(137,311,557)


def atomic(path,obj):
    tmp=path.with_suffix('.part');tmp.write_text(json.dumps(obj,indent=2)+'\n');os.replace(tmp,path)


def occupancy():
    cmd=['/opt/rocm/bin/amd-smi','process','--json']
    q=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
    if q.returncode:raise RuntimeError('amd-smi process failed: '+q.stderr[:250])
    devs=json.loads(q.stdout);assert len(devs)==1
    owners=[int(k['process_info']['pid']) for k in devs[0].get('process_list',[]) if isinstance(k,dict) and isinstance(k.get('process_info'),dict)]
    paths=list(Path('/sys/class/drm').glob('card[0-9]/device/gpu_busy_percent'))
    assert len(paths)==1
    busy=[]
    for _ in range(5):
        busy.append(int(paths[0].read_text()));time.sleep(.6)
    return {'compute_pids':owners,'busy_percent':busy}


def main(root,wrapper):
    root=root.resolve();state=root/'recovery-8559';state.mkdir(exist_ok=True);logs=state/'log';logs.mkdir(exist_ok=True)
    with (state/'recovery.lock').open('a') as outer:
        fcntl.flock(outer,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while not (root/'data/prepared.json').is_file():
            atomic(state/'progress.json',{'state':'awaiting_real_source_reconstruction','utc':time.time()});time.sleep(15)
        data=json.loads((root/'data/prepared.json').read_text());assert data['samples']==7442 and sum(data['splits'])==7442
        with (root/'run.lock').open('a') as original_lock:
            fcntl.flock(original_lock,fcntl.LOCK_EX)
            order=[(w,s,ARMS[(i+j)%4]) for i,s in enumerate(SEEDS) for w in (416,4096) for j in range(4)]
            first=(4096,137,'literal');order=[first]+[x for x in order if x!=first]
            def execute(label,args):
                stamp=int(time.time())
                with (logs/(label+'-'+str(stamp)+'.txt')).open('a') as f:
                    p=subprocess.run([sys.executable,'-u',*map(str,args)],cwd=root/'src',stdout=f,stderr=subprocess.STDOUT)
                with (state/'processes.jsonl').open('a') as f:f.write(json.dumps({'name':label,'start':stamp,'end':time.time(),'exit':p.returncode})+'\n')
                if p.returncode:raise RuntimeError(label+' exit '+str(p.returncode))
            for phase in ('fit','cold'):
                if phase=='cold':execute('seal',[root/'src/run.py',root,'seal'])
                for width,seed,arm in order:
                    key=f'{width}-{seed}-{arm}'
                    dest=root/('fits' if phase=='fit' else 'cold')/key
                    done=dest/('fit.json' if phase=='fit' else 'result.json')
                    if done.exists():continue
                    while True:
                        obs=occupancy();atomic(state/'progress.json',{'state':'checking_shared_accelerator','phase':phase,'cell':key,'utc':time.time(),**obs})
                        # amd-smi lists compute owners separately from runtime-only /dev/kfd opens.
                        if not obs['compute_pids'] and statistics.median(obs['busy_percent'])<=10:break
                        time.sleep(25)
                    if phase=='fit' and dest.is_dir() and list(dest.iterdir()):
                        old=state/'abandoned'/(key+'-'+str(int(time.time())));old.parent.mkdir(exist_ok=True)
                        os.rename(dest,old)
                        sensitivity=state/'dev'/key
                        if sensitivity.exists():os.rename(sensitivity,old/'development_sensitivity')
                    atomic(state/'progress.json',{'state':'executing','phase':phase,'cell':key,'utc':time.time(),'start_device':obs})
                    if phase=='fit':execute('fit-'+key,[wrapper,root,arm,width,seed])
                    else:execute('cold-'+key,[root/'src/run.py',root,'cold','--arm',arm,'--width',width,'--seed',seed])
            (state/'report').mkdir(exist_ok=True)
            execute('report',[root/'src/score.py',root,state/'report'])
            atomic(state/'progress.json',{'state':'complete','utc':time.time()})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('fit_wrapper',type=Path);a=p.parse_args();main(a.root,a.fit_wrapper.resolve())
