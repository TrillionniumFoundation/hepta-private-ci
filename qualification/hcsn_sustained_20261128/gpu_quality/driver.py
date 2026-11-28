"""Cold time and board energy at the first predeclared 80% development gate."""
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
REQUEST='hcsn-native-quality-energy-1140569-20261128'


def save(path,body):
    path.write_text(json.dumps(body,indent=2,allow_nan=False)+'\n')


def scientific(report,folder,output):
    import numpy as np
    import torch
    from telemetry import BoardMeter
    assert torch.cuda.is_available()
    report['torch']=str(torch.__version__)
    report['cuda_build']=torch.version.cuda
    report['gpu']=torch.cuda.get_device_name()
    report['memory_gib']=torch.cuda.get_device_properties(0).total_memory/2**30
    assert 'T4' in report['gpu']
    tensor=torch.arange(8,dtype=torch.float32,device='cuda')
    report['cuda_dot']=(tensor@tensor).item()
    assert tensor.is_cuda and report['cuda_dot']==140.
    physical=[]
    for i,k in enumerate((12,128)):
        for j,seed in enumerate((314,159)):
            modes=('dense','fft') if (i+j)%2==0 else ('fft','dense')
            for mode in modes:
                physical.append((k,seed,mode))
    report.update(arms={},pairs=[],success=False)
    env={**os.environ,'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    def call(k,seed,mode,phase):
        start=time.perf_counter()
        args=[sys.executable,str(folder/'worker.py'),'--output',str(folder),'--seed',str(seed),
              '--atoms',str(k),'--mode',mode,'--phase',phase,'--spawn',str(start)]
        process=subprocess.run(args,env=env,capture_output=True,text=True)
        if process.returncode:
            raise RuntimeError(process.stderr[-3000:])
        return time.perf_counter()-start
    with BoardMeter() as idle_meter:
        time.sleep(2.)
    report['idle_board']=idle_meter.result
    for k,seed,mode in physical:
        arm=f'{k}-{seed}-{mode}'
        with BoardMeter() as meter:
            cold_seconds=call(k,seed,mode,'train')
        fit=json.loads((folder/(arm+'.json')).read_text())
        fit.update(cold_child_seconds=cold_seconds,board_energy=meter.result)
        report['arms'][arm]=fit
        save(output,report)
    seal={'arms':{key:{'state_sha256':arm['state_sha256'],'gate':arm['first_dev_gate']}
                  for key,arm in report['arms'].items()}}
    save(folder/'seal.json',seal)
    report['seal_sha256']=hashlib.sha256((folder/'seal.json').read_bytes()).hexdigest()
    report['seal']=seal
    for k,seed,mode in physical:
        arm=f'{k}-{seed}-{mode}'
        seconds=call(k,seed,mode,'cold')
        cold=json.loads((folder/(arm+'-cold.json')).read_text())
        report['arms'][arm]['cold_review']={**cold,'cold_eval_process_s':seconds}
    for k,seed,_ in physical[::2]:
        name=f'{k}-{seed}-'
        a,b=report['arms'][name+'dense'],report['arms'][name+'fft']
        va=np.load(folder/(name+'dense-logits.npy'))
        vb=np.load(folder/(name+'fft-logits.npy'))
        assert a['schedule_sha256']==b['schedule_sha256']
        ga,gb=a['first_dev_gate'],b['first_dev_gate']
        da,db=a['checks'],b['checks']
        max_dev_ce=max(abs(x['ce']-y['ce']) for x,y in zip(da,db))
        max_logit=float(np.abs(va-vb).max())
        primary_pass=ga is not None and ga==gb and max_logit<1e-7 and max_dev_ce<1e-7
        row={'atoms':k,'seed':seed,'gate_dense':ga,'gate_fft':gb,'matched':primary_pass,
             'max_abs_cold_logit_difference':max_logit,'max_dev_ce_difference_over_common_prefix':max_dev_ce,
             'cold_accuracy_dense':a['cold_review']['heldout']['balanced_accuracy'],
             'cold_accuracy_fft':b['cold_review']['heldout']['balanced_accuracy']}
        if primary_pass:
            row.update(cold_to_gate_dense_s=da[-1]['cold_seconds'],cold_to_gate_fft_s=db[-1]['cold_seconds'],
                       dense_over_fft_cold_to_gate=da[-1]['cold_seconds']/db[-1]['cold_seconds'])
            for key in ('board_counter_joules','power_integral_joules'):
                ja,jb=a['board_energy'][key],b['board_energy'][key]
                if ja is not None and jb:
                    row[key]={'dense':ja,'fft':jb,'dense_over_fft':ja/jb}
        report['pairs'].append(row)
    report['success']=all(p['matched'] for p in report['pairs']) and len(report['pairs'])==4


if __name__=='__main__':
    output=Path.cwd()/'gpu_quality.json'
    report={'request':REQUEST,'source_inputs':{k:v['sha'] for k,v in INPUTS.items()},
            'started_unix':time.time(),'success':False}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name,item in INPUTS.items():
                raw=zlib.decompress(base64.b64decode(item['blob'],validate=True))
                assert Path(name).name==name and hashlib.sha256(raw).hexdigest()==item['sha']
                (folder/name).write_bytes(raw)
            sys.path.insert(0,str(folder))
            scientific(report,folder,output)
    except Exception:
        report['error']=traceback.format_exc()[-3200:]
    report['ended_unix']=time.time()
    save(output, report)
