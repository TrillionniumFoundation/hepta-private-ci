"""Test source-defined early BP candidates against every one of the 55 frozen BP object IDs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from supplemental_recovery import ROOT, SOURCE, read, write, sha, source_report, materialize, cold_selected

OUT = ROOT / 'early_bp'
FROZEN_TRAIN = '4eb6bfbe5ef009d314f09bedcba3688224eb48beb128b2da68e1bc3e398e8bea'


def cell(key):
    import torch
    width, arm, seed = key.split('-')
    assert arm in ('bp_h', 'transformer', 'transformer_text')
    expected = {n:h for n,h in source_report()['weights'].items() if n.startswith(key + '-r')}
    assert expected and sha(SOURCE / 'train.py') == FROZEN_TRAIN
    train = (SOURCE / 'train.py').read_text()
    changes = [
        ('        cand=(mae,mse)', '        capture(network,detail,mae,mse)\n        cand=(mae,mse)'),
        ('        while elapsed()<max(RUNGS):', '        while step<12:'),
        ('            for lr,md,opt in learn:\n                if elapsed()>=max(RUNGS):break',
         '            for lr,md,opt in learn:')]
    for old,new in changes:
        assert train.count(old) == 1
        train = train.replace(old,new)
    sys.path.insert(0, str(SOURCE))
    rows = []
    begin = time.monotonic()
    with tempfile.TemporaryDirectory(dir=OUT) as td:
        temp = Path(td)
        def capture(net, info, mae, mse):
            state = {k:v.detach().clone() for k,v in net.state_dict().items()}
            tests={}
            for name, target in expected.items():
                path=temp/name;torch.save(state,path);actual=sha(path)
                tests[name]={'computed':actual,'frozen':target,'exact':actual==target}
                if actual==target:
                    a=OUT/'authenticated'/name;a.parent.mkdir(exist_ok=True)
                    if not a.is_file():shutil.copyfile(path,a)
                    assert sha(a)==target
            rows.append({'step':info['steps'],'lr':info['lr'],'dev_video_mae':mae,'dev_mse':mse,'objects':tests})
        ns={'__file__':str(SOURCE/'train.py'),'__name__':'__main__','capture':capture}
        sys.argv=['train.py',str(ROOT/'reconstructed'),str(SOURCE/'law.npz'),str(temp/'derived_endpoints'),width,arm,seed]
        exec(compile(train,str(SOURCE/'train.py'),'exec'),ns)
    assert {(r['step'],r['lr']) for r in rows}=={(i,v) for i in (0,1,4,12) for v in (.0005,.003)}
    assert rows[0]['objects']==rows[1]['objects']
    write(OUT/'cells'/(key+'.json'), {'group':key,'torch':str(torch.__version__),'records':rows,'seconds':time.monotonic()-begin})


def run():
    import fcntl
    # Reuse the same low-priority single-CPU capacity as the finite solver.
    while not (ROOT/'finite_replay/terminal.json').is_file():time.sleep(15)
    OUT.mkdir(exist_ok=True);(OUT/'cells').mkdir(exist_ok=True)
    lock=(OUT/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    original=source_report()
    keys=sorted({k.rsplit('-r',1)[0] for k in original['weights'] if k.split('-')[1] in ('bp_h','transformer','transformer_text')},
                key=lambda k:(int(k.split('-')[0]),k.split('-')[1:]))
    assert len(keys)==21
    matched={};objects=set();checks=0
    for key in keys:
        p=OUT/'cells'/(key+'.json')
        if not p.exists():subprocess.run([sys.executable,__file__,'--cell',key],check=True)
        doc=read(p)
        for row in doc['records']:
            for name, rec in row['objects'].items():
                assert rec['frozen']==original['weights'][name] and rec['exact']==(rec['computed']==rec['frozen'])
                objects.add(name);checks+=1
                if rec['exact']:matched[name]=OUT/'authenticated'/name
        print('early',key,'seconds',round(doc['seconds'],1),flush=True)
    assert len(objects)==55 and checks==440
    root=ROOT/'publication';kind='mosi_recovery_raw/early_bp';dest=root/kind;dest.mkdir(exist_ok=True,parents=True)
    receipt=root/'early_bp-receipt.json'
    if receipt.exists():print(receipt.read_text(),flush=True);return
    for key in keys: materialize(OUT/'cells'/(key+'.json'),dest/'cells'/(key+'.json'))
    enumeration={'historical_sha256':sha(SOURCE/'SEAL.json'),'source_sha256':sha(Path(__file__)),'groups':len(keys),
                 'historical_objects':len(objects),'candidate_serializations':checks,'unique_step_zero_per_group':1,
                 'updates':[0,1,4,12],'lrs':[.0005,.003],'exact_historical_matches':{n:sha(p) for n,p in matched.items()},
                 'scope':'The first four validation closures only; later 24-step multiples were possible in the historical run.'}
    write(dest/'supplemental_hash_seal.json',enumeration)
    final={'matched':len(matched),'hash_seal_sha256':sha(dest/'supplemental_hash_seal.json'),'authenticated_cold':cold_selected(dest,matched)}
    write(dest/'terminal.json',final)
    materialize(Path(__file__),dest/'gradient_prefix_recovery.py')
    files=sorted(p for p in dest.rglob('*') if p.is_file() and p!=dest/'verified_objects.json')
    idx=dest/'verified_objects.json';write(idx,{str(p.relative_to(dest)):{'sha256':sha(p),'size':p.stat().st_size} for p in files});files.append(idx)
    from publish_mosi import native,git,PREFIX,BRANCH
    while True:
        try:
            commit=native(root,kind,files);b=idx.read_bytes()
            oid=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
            assert git(root/(kind+'.git'),['rev-parse',commit+':'+PREFIX+kind+'/verified_objects.json'])==oid
            write(receipt,{'branch':BRANCH,'commit':commit,'prefix':PREFIX+kind+'/','file_count':len(files),
                           'manifest_sha256':sha(idx),'manifest_blob':oid,'terminal_sha256':sha(dest/'terminal.json'),
                           'exact_additional_matches':len(matched)})
            print(receipt.read_text(),flush=True);return
        except (RuntimeError,subprocess.TimeoutExpired) as exc:
            print('retrying verified outputs',str(exc)[-250:],flush=True);time.sleep(50)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cell');a=p.parse_args()
    if a.cell:cell(a.cell)
    else:run()
