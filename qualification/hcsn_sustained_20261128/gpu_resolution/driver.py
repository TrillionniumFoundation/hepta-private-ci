"""A sealed Colab T4 operator scaling study with independent raw array outputs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import zlib

INPUTS = {}
REQUEST='hcsn-native-hires-transport-1140569-20261128'


def save(dest,obj):
    dest.write_text(json.dumps(obj,allow_nan=False,separators=(',',':'))+'\n')


def run(folder,output,raw_output,report):
    import numpy as np
    import torch
    assert torch.cuda.is_available()
    report['device']=torch.cuda.get_device_name()
    assert 'T4' in report['device']
    report['torch']=str(torch.__version__)
    report['cuda_runtime']=torch.version.cuda
    report['total_board_bytes']=torch.cuda.get_device_properties(0).total_memory
    probe=torch.arange(8,device='cuda',dtype=torch.float32)
    report['dot']=float(probe@probe)
    assert report['dot']==140.
    cfg=[('operator',dtype,k) for dtype in ('float64','float32') for k in (256,512,1024,2048)]
    cfg +=[('network','float64',k) for k in (256,1024)]
    report['arms']={};report['pairs']=[];raw={}
    env={**os.environ,'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    for i,(kind,dtype,k) in enumerate(cfg):
        order=('dense','fft') if i%2==0 else ('fft','dense')
        modes={}
        for mode in order:
            tag=f'{kind}_{dtype}_{k}_{mode}'
            sub=subprocess.run([sys.executable,str(folder/'worker.py'),'--folder',str(folder),'--dtype',dtype,
                  '--atoms',str(k),'--mode',mode,'--kind',kind],env=env,capture_output=True,text=True)
            src=folder/(tag+'.json')
            if sub.returncode or not src.exists():
                modes[mode]={'status':'error','error':sub.stderr[-1200:],'returncode':sub.returncode}
            else:
                modes[mode]=json.loads(src.read_text())
            report['arms'][tag]=modes[mode]
            if modes[mode]['status']=='ok':
                with np.load(folder/(tag+'.npz'),allow_pickle=False) as f:
                    for field in f.files:raw[tag+'__'+field]=f[field].copy()
            save(output,report)
        a,b=modes['dense'],modes['fft']
        pair={'kind':kind,'dtype':dtype,'k':k,'status_dense':a['status'],'status_fft':b['status']}
        if a['status']=='ok' and b['status']=='ok':
            comparison={}
            prefix=f'{kind}_{dtype}_{k}_'
            for fn in [x.split('__',1)[1] for x in raw if x.startswith(prefix+'dense__')]:
                aa,bb=raw[prefix+'dense__'+fn],raw[prefix+'fft__'+fn]
                absolute=float(np.max(np.abs(aa.astype('float64')-bb.astype('float64'))))
                comparison[fn]={'max_abs':absolute,'scaled_max_abs':absolute/(1.+float(np.max(np.abs(aa))))}
            tolerance=2e-9 if dtype=='float64' else 3e-4
            if kind=='operator':
                for mode in ('dense','fft'):
                    comparison['conservation_'+mode]={'max_abs':float(np.abs(raw[prefix+mode+'__balance']-1.).max()),
                                                       'scaled_max_abs':float(np.abs(raw[prefix+mode+'__balance']-1.).max())}
            passed=all(m['scaled_max_abs']<=tolerance for m in comparison.values())
            pair.update(numeric_pass=passed,acceptance_bound=tolerance,comparison=comparison)
            if passed:
                pair.update(dense_over_fft_wall=a['wall_median_s']/b['wall_median_s'],
                            dense_over_fft_cuda_event=a['cuda_event_median_s']/b['cuda_event_median_s'],
                            dense_over_fft_peak=a['incremental_peak_bytes']/b['incremental_peak_bytes'])
                if a['joules_per_call'] is not None and b['joules_per_call']:
                    pair['dense_over_fft_board_energy_per_call']=a['joules_per_call']/b['joules_per_call']
        report['pairs'].append(pair)
        save(output,report)
    np.savez_compressed(raw_output,**raw)
    report['raw_npz_sha256']=hashlib.sha256(raw_output.read_bytes()).hexdigest()
    report['raw_npz_bytes']=raw_output.stat().st_size
    report['terminal']=True
    report['all_numeric_pass']=all(x.get('numeric_pass',False) for x in report['pairs'])


if __name__=='__main__':
    result=Path.cwd()/'scaling.json'
    raw=Path.cwd()/'checks.npz'
    report={'request_id':REQUEST,'terminal':False,'started_unix':time.time(),
            'inputs':{k:v['sha'] for k,v in INPUTS.items()}}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name,item in INPUTS.items():
                content=zlib.decompress(base64.b64decode(item['blob'],validate=True))
                assert Path(name).name==name and hashlib.sha256(content).hexdigest()==item['sha']
                (folder/name).write_bytes(content)
            run(folder,result,raw,report)
    except Exception:
        report['error']=traceback.format_exc()[-2400:]
    report['ended_unix']=time.time()
    save(result,report)
