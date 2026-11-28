"""Run, freeze, independently score and preserve one SHD accelerator panel."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO='TrillionniumFoundation/hepta-private-ci'
PREFIX='qualification/hcsn_shd_rtx4060_8559'
BRANCH='research/hcsn-shd-rtx4060-clock-8559'
RUNGS=(30,180,720,1800)

def api(path,body=None):
    cmd=['gh','api','repos/'+REPO+'/'+path]
    if body is not None:cmd.extend(['--method','POST','--input','-'])
    run=subprocess.run(cmd,input=json.dumps(body) if body is not None else None,capture_output=True,text=True,timeout=160)
    if run.returncode:raise RuntimeError(run.stderr[:650])
    return json.loads(run.stdout)

def publish(files,title,base,root):
    try:parent=api('git/ref/heads/'+BRANCH)['object']['sha']
    except RuntimeError as err:
        if '404' not in str(err):raise
        parent=api('git/refs',{'ref':'refs/heads/'+BRANCH,'sha':base})['object']['sha']
    commit=api('git/commits/'+parent)
    tree=[]
    for f in files:
        buf=f.read_bytes()
        local=hashlib.sha1(b'blob '+str(len(buf)).encode()+b'\0'+buf).hexdigest()
        cache=root/'uploaded'/local
        if not cache.exists():
            remote=api('git/blobs',dict(content=base64.b64encode(buf).decode(),encoding='base64'))
            assert remote['sha']==local
            cache.parent.mkdir(exist_ok=True);cache.touch()
        tree.append(dict(path=PREFIX+'/'+str(f.relative_to(root)),mode='100644',type='blob',sha=local))
    mapping=api('git/trees',dict(base_tree=commit['tree']['sha'],tree=tree))['sha']
    if mapping==commit['tree']['sha']:return parent
    sha=api('git/commits',dict(tree=mapping,parents=[parent],message=title))['sha']
    cmd=['gh','api','--method','PATCH','repos/'+REPO+'/git/refs/heads/'+BRANCH,'--input','-']
    subprocess.run(cmd,input=json.dumps(dict(sha=sha,force=False)),text=True,stdout=subprocess.DEVNULL,check=True)
    assert api('git/ref/heads/'+BRANCH)['object']['sha']==sha
    return sha

def retry(action,log,attempts=8):
    for i in range(attempts):
        try:return action()
        except Exception as err:
            print(log,'retry',i+1,repr(err),flush=True)
            if i+1==attempts:raise
            time.sleep(min(40,3*(i+1)))

def run(args):
    print('starting',args,flush=True)
    subprocess.run([sys.executable,*map(str,args)],check=True)
def mark(root,name,fn):
    out=root/'receipts'/(name+'.json');out.parent.mkdir(exist_ok=True)
    if out.exists():return
    value=fn()
    tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(dict(action=name,result=value,at=time.time()))+'\n')
    os.replace(tmp,out)
def joined(runs,r):
    seal=runs/f'seal-{r}.json'
    rows=json.loads(seal.read_text());assert len(rows)==21
    return [seal]+[f for p in sorted(runs.iterdir()) if p.is_dir() for f in (p/f'rung-{r}.json',p/f'selected-{r}.pt')]

def score(root,work,r,matched=0):
    runs=root/'runs';folder=root/(f'cold-{r}'+(f'-updates-{matched}' if matched else ''))
    argv=[work/'cold.py','data','runs',folder,r,'--device','cuda']
    if matched:argv+=['--matched-step',matched]
    run(argv);result=folder/'summary.json'
    run([work/'compare.py',folder,runs,r,result])
    return sorted(folder.iterdir())

def main(root,base):
    root=root.resolve();work=root/'source';runs=root/'runs'
    os.chdir(root)
    with (root/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for rung in RUNGS:
            retry(lambda:run([work/'gpu_train.py','data','runs','--rungs',rung]),'training')
            mark(root,f'sealed-{rung}',lambda:retry(lambda:publish(joined(runs,rung),f'Seal all 21 RTX4060 selections before test at rung {rung}',base,root),'preserve'))
            if rung==30:
                files=retry(lambda:score(root,work,rung),'cold')
                mark(root,'early-30',lambda:retry(lambda:publish(files,'Publish independent early RTX4060 scores and full logits',base,root),'publish early'))
        for r in RUNGS[1:]:
            files=retry(lambda:score(root,work,r),'cold')
            mark(root,f'cold-{r}',lambda:retry(lambda:publish(files,f'Publish independently reloaded RTX4060 level {r}',base,root),'preserve cold'))
        match=min(max(int(p.stem.split('-')[1]) for p in d.glob('update-*.pt')) for d in runs.iterdir() if d.is_dir())
        weights=sorted(runs.glob(f'*/update-{match}.pt'))
        assert len(weights)==21
        mark(root,'seal-matched',lambda:retry(lambda:publish(weights,f'Seal RTX4060 common {match} update panel',base,root),'seal matched'))
        scores=retry(lambda:score(root,work,1800,match),'matched')
        mark(root,'cold-matched',lambda:retry(lambda:publish(scores,f'Publish RTX4060 common {match} update verification',base,root),'publish matched'))
        print('MATRIX FINISHED',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('base');a=p.parse_args();main(a.root,a.base)
