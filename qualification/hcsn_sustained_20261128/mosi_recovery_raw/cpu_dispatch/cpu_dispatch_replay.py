"""Test numerical sensitivity to a controlled CPU-dispatch change without opening MOSI cold scores."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from supplemental_recovery import ROOT,SOURCE,read,write,sha,source_report,cold_selected,materialize

OUT=ROOT/'cpu_dispatch'
SOURCE_SHA='4eb6bfbe5ef009d314f09bedcba3688224eb48beb128b2da68e1bc3e398e8bea'
ENV={'ATEN_CPU_CAPABILITY':'default','MKL_CBWR':'COMPATIBLE','ONEDNN_MAX_CPU_ISA':'SSE41',
     'MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}


def cell(key):
    import torch
    w,arm,seed=key.split('-')
    hist=source_report()
    base=ROOT/'candidate_replay/fits';receipt=read(base/(key+'.json'))
    pick=receipt['selected']['15'];name=pick['file'];target=hist['weights'][name]
    past=torch.load(base/name,weights_only=True,map_location='cpu')
    assert sha(base/name)==pick['sha256'] and sha(SOURCE/'train.py')==SOURCE_SHA
    src=(SOURCE/'train.py').read_text()
    marker='        cand=(mae,mse)'
    assert src.count(marker)==1
    src=src.replace(marker,'        capture(network,detail,mae,mse)\n'+marker)
    sys.path.insert(0,str(SOURCE))
    rows=[]
    def capture(net,detail,mae,mse):
        state={k:v.detach().clone() for k,v in net.state_dict().items()}
        path=temp/name;torch.save(state,path);code=sha(path)
        row={'penalty':detail['penalty'],'dev_video_mae':mae,'dev_mse':mse,'candidate_sha256':code,
             'historical_sha256':target,'exact_historical':code==target}
        if code==target:
            p=OUT/'authenticated'/name;p.parent.mkdir(exist_ok=True)
            if not p.exists():shutil.copyfile(path,p)
            assert sha(p)==target
        if detail['penalty']==pick['penalty']:
            stats={}
            for k,t in state.items():
                b=past[k]
                assert b.shape==t.shape and b.dtype==t.dtype
                delta=t.double()-b.double()
                stats[k]={'count':t.numel(),'nonidentical':int((t!=b).sum()),'max_abs':float(delta.abs().max()),
                          'rmse':float(delta.square().mean().sqrt()),'baseline_rms':float(b.double().square().mean().sqrt())}
            row['same_penalty_numeric_comparison_to_default_dispatch']=stats
        rows.append(row)
    with tempfile.TemporaryDirectory(dir=OUT) as td:
        temp=Path(td)
        sys.argv=['train.py',str(ROOT/'reconstructed'),str(SOURCE/'law.npz'),str(temp/'trained'),w,arm,seed]
        ns={'__name__':'__main__','__file__':str(SOURCE/'train.py'),'capture':capture}
        exec(compile(src,str(SOURCE/'train.py'),'exec'),ns)
    assert [v['penalty'] for v in rows]==[.001,.03,.3]
    write(OUT/'cells'/(key+'.json'),{'group':key,'weight_filename':name,'default_candidate_sha256':sha(base/name),
          'selected_baseline_penalty':pick['penalty'],'torch':str(torch.__version__),'aten_reported':torch.backends.cpu.get_cpu_capability(),
          'requested_dispatch':ENV,'records':rows})


def run():
    root=ROOT/'publication';kind='mosi_recovery_raw/cpu_dispatch';dest=root/kind
    dest.mkdir(parents=True,exist_ok=True);OUT.mkdir(exist_ok=True);(OUT/'cells').mkdir(exist_ok=True)
    receipt=root/'cpu_dispatch-receipt.json'
    if receipt.exists():print(receipt.read_text());return
    keys=[f'64-{a}-{s}' for a in ('fp_h','fp_h_shuffle','fp_h_text','fp_r','random_h') for s in (413,677,941)]
    keys += [f'0-{a}-413' for a in ('raw_all','raw_text','raw_av')]
    matches={};groups={};hist=source_report()
    for key in keys:
        p=OUT/'cells'/(key+'.json')
        if not p.is_file():subprocess.run([sys.executable,__file__,'--cell',key],env={**os.environ,**ENV},check=True)
        data=read(p);name=data['weight_filename']
        assert len(data['records'])==3;materialize(p,dest/'cells'/p.name)
        for row in data['records']:
            if row['exact_historical']:
                assert row['candidate_sha256']==hist['weights'][name]
                matches[name]=OUT/'authenticated'/name
            if 'same_penalty_numeric_comparison_to_default_dispatch' in row:
                t=row['same_penalty_numeric_comparison_to_default_dispatch'].values()
                groups[key]={'same_default_serialize':row['candidate_sha256']==data['default_candidate_sha256'],
                             'elements':sum(x['count'] for x in t),'changed':sum(x['nonidentical'] for x in t),
                             'max_abs':max(x['max_abs'] for x in t)}
        print('dispatch',key,groups[key],flush=True)
    # Exclude the nine original raw checkpoints already scored by the first authenticated experiment.
    first=read(ROOT/'candidate_replay/reconstruction_result.json')['authenticated_cold_results']
    additional={k:p for k,p in matches.items() if k not in first}
    coverage={'groups':len(keys),'candidate_operations':3*len(keys),'historical_matches':sorted(matches),
              'new_historical_matches':sorted(additional),'same_penalty':groups,
              'source_sha256':sha(Path(__file__)),'requested_dispatch':ENV,
              'scope':'Only this controlled dispatch change on one machine is observed; missing original tensors cannot be inferred from archive SHA.'}
    write(dest/'comparison_seal.json',coverage)
    final={'matched_additional':len(additional),'comparison_seal_sha256':sha(dest/'comparison_seal.json'),
           'authenticated_cold':cold_selected(dest,additional)}
    write(dest/'terminal.json',final);materialize(Path(__file__),dest/'cpu_dispatch_replay.py')
    files=sorted(p for p in dest.rglob('*') if p.is_file() and p != dest/'verified_objects.json')
    idx=dest/'verified_objects.json';write(idx,{str(p.relative_to(dest)):{'sha256':sha(p),'size':p.stat().st_size} for p in files});files.append(idx)
    from publish_mosi import native,git,PREFIX,BRANCH
    import hashlib
    while True:
        try:
            commit=native(root,kind,files);b=idx.read_bytes()
            oid=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
            assert git(root/(kind+'.git'),['rev-parse',commit+':'+PREFIX+kind+'/verified_objects.json'])==oid
            write(receipt,{'branch':BRANCH,'commit':commit,'prefix':PREFIX+kind+'/','file_count':len(files),
                           'manifest_sha256':sha(idx),'manifest_blob':oid,'terminal_sha256':sha(dest/'terminal.json'),
                           'exact_additional_matches':len(additional)})
            print(receipt.read_text(),flush=True);return
        except (RuntimeError,subprocess.TimeoutExpired) as exc:
            print('retrying',str(exc)[-200:],flush=True);time.sleep(50)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cell');arg=p.parse_args()
    if arg.cell:cell(arg.cell)
    else:run()
