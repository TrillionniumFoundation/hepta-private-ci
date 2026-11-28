"""Measure CPU Inductor against eager on the two fixed MOSI architectures with real sealed weights."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import time

ENTRY=time.perf_counter()
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'compile_inference'
SEAL='fc024bfe4a11bcf1f95390efe0a32d2200cb532f11aa7c7c57fa15c601194858'
SEEDS=(413,677,941);ARMS=('fp_h','transformer')


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,d):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,indent=1,sort_keys=True,allow_nan=False)+'\n');tmp.replace(p)


def child(arm,mode):
    import numpy as np
    import torch
    sys.path.insert(0,str(ROOT/'source'))
    from models import model,modalities,predict
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    seal=read(ROOT/'fresh/FRESH_SEAL.json');assert sha(ROOT/'fresh/FRESH_SEAL.json')==SEAL
    assert sha(ROOT/'source/law.npz')==seal['law_sha256'] and sha(ROOT/'source/models.py')==seal['code']['models.py']
    source=ROOT/'reconstructed/test.npz';assert sha(source)==seal['test_input_sha256']
    with np.load(source) as z: x=torch.from_numpy(z['x']);y=z['y'];ids=z['clip'];video=z['video']
    x=modalities(x,arm);ts=time.perf_counter()
    net=model(64,arm,ROOT/'source/law.npz');net.eval()
    def install(s):
        fp=ROOT/f'fresh/models/64-{arm}-{s}.json'
        assert sha(fp)==seal['fits'][fp.name]
        name=read(fp)['selected']['180']['file'];p=fp.parent/name;assert sha(p)==seal['weights'][name]
        net.load_state_dict(torch.load(p,weights_only=True,map_location='cpu'));return sha(p)
    first=install(SEEDS[0]);ready=time.perf_counter();observed=net
    wrapper=time.perf_counter()
    if mode=='inductor':
        import torch._inductor.config as cfg
        cfg.compile_threads=1
        observed=torch.compile(net,backend='inductor',fullgraph=True,dynamic=False)
    wrapper_s=time.perf_counter()-wrapper
    begin=time.perf_counter();p0=predict(observed,x);first_s=time.perf_counter()-begin
    first_clock=time.perf_counter()-ENTRY
    ids_all={};timings={};pred={'clip':ids,'video':video,'y':y}
    for s in SEEDS:
        key=str(s);ids_all[key]=install(s)
        reference=ROOT/f'fresh/cold/64-{arm}-{s}.npz'
        t=read(reference.with_suffix('.json'));assert sha(reference)==t['pred_sha256']
        with np.load(reference) as z: truth=z['r180']
        recorded=[]
        for i in range(9):
            bt=time.perf_counter();z=predict(observed,x);recorded.append(time.perf_counter()-bt)
            if i==0: first_output=z.copy()
            else: assert np.array_equal(z,first_output)
        if s==SEEDS[0]:assert np.array_equal(first_output,p0)
        if mode=='eager':assert np.array_equal(first_output,truth)
        delta=np.abs(first_output.astype(float)-truth)
        gm=lambda q:np.mean([np.abs(q[video==v]-y[video==v]).mean() for v in np.unique(video)])
        timings[key]={'wall_runs':recorded,'wall_median':statistics.median(recorded),'exact_to_original':bool(np.array_equal(first_output,truth)),
                      'max_abs_score_delta':float(delta.max()),'mean_abs_score_delta':float(delta.mean()),
                      'maximum_score_jitter_across_nine_repeats':0.,'sign_flips':int(np.sum((first_output>0)!=(truth>0))),
                      'video_MAE_delta':float(gm(first_output)-gm(truth))}
        pred[key]=first_output
    f=OUT/f'{arm}-{mode}.npz';np.savez_compressed(f,**pred)
    write(f.with_suffix('.json'),{'arm':arm,'mode':mode,'torch':str(torch.__version__),'cpu':torch.backends.cpu.get_cpu_capability(),
          'seeds':SEEDS,'weights':ids_all,'cold_input_sha256':seal['test_input_sha256'],'fresh_seal_sha256':SEAL,'source_sha256':sha(Path(__file__)),
          'process_to_torch_and_checked_inputs_s':ts-ENTRY,'model_and_selected_weights_s':ready-ts,'initial_wrapper_s':wrapper_s,
          'first_full_686_predict_s':first_s,'process_to_first_full_output_s':first_clock,'warm_by_seed':timings,
          'score_file_sha256':sha(f),'num_threads':torch.get_num_threads(),'fullgraph':mode=='inductor',
          'batch_shapes':[64,46],'compile_threads':1,'mean_abs_gate':1.e-4,'max_abs_gate':1.e-3})
    print('complete',arm,mode,first_clock,flush=True)


def run():
    import numpy as np
    OUT.mkdir(exist_ok=True)
    roster=[('fp_h','eager'),('transformer','eager'),('transformer','inductor'),('fp_h','inductor')]
    from subprocess import Popen
    for arm,mode in roster:
        key=f'{arm}-{mode}'
        if (OUT/(key+'.json')).exists() or (OUT/(key+'.failed.json')).exists():continue
        env={**os.environ,'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','TORCHINDUCTOR_COMPILE_THREADS':'1',
             'TORCHINDUCTOR_CACHE_DIR':str(OUT/('cache-'+arm)),'MAX_JOBS':'1','CUDA_VISIBLE_DEVICES':''}
        log=OUT/(key+'.log');start=time.perf_counter()
        with log.open('wb') as stream:
            job=Popen([sys.executable,'-u',__file__,'--child',arm,mode],env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            try:status=job.wait(timeout=600)
            except subprocess.TimeoutExpired:
                os.killpg(job.pid,signal.SIGTERM);time.sleep(1)
                if job.poll() is None:os.killpg(job.pid,signal.SIGKILL)
                job.wait();status='600-second-bound'
        if status!=0:
            write(OUT/(key+'.failed.json'),{'arm':arm,'mode':mode,'exit':status,'wall':time.perf_counter()-start,
                  'log_sha256':sha(log),'last':log.read_text(errors='replace')[-1500:]})
        print(key,status,round(time.perf_counter()-start,3),flush=True)
    aggregate={}
    for arm in ARMS:
        a,b=(OUT/f'{arm}-{m}.json' for m in ('eager','inductor'))
        if not a.is_file() or not b.is_file():
            aggregate[arm]={'inductor_result':'unavailable','eager_available':a.is_file()};continue
        x,z=read(a),read(b)
        ex=np.mean([v['wall_median'] for v in x['warm_by_seed'].values()]);co=np.mean([v['wall_median'] for v in z['warm_by_seed'].values()])
        add=z['process_to_first_full_output_s']-x['process_to_first_full_output_s']
        fits=all(v['mean_abs_score_delta']<=1.e-4 and v['max_abs_score_delta']<=1.e-3 and v['sign_flips']==0 for v in z['warm_by_seed'].values())
        aggregate[arm]={'source_sha':SEAL,'strict_score_tolerance_and_sign_gate':fits,'mean_seed_eager_warm_median_s':float(ex),
            'mean_seed_compiled_warm_median_s':float(co),'warm_speed_ratio':float(ex/co),
            'fresh_process_to_first_result_eager_s':x['process_to_first_full_output_s'],
            'empty_cache_process_to_first_result_compiled_s':z['process_to_first_full_output_s'],
            'estimated_complete_686_sweeps_to_amortize':None if ex<=co else int(1+np.ceil(max(add,0)/(ex-co))),
            'sign_changes_total':sum(r['sign_flips'] for r in z['warm_by_seed'].values()),
            'maximum_absolute_difference':max(r['max_abs_score_delta'] for r in z['warm_by_seed'].values())}
    out=OUT/'terminal.json';write(out,{'scope':'Post-hoc inference performance on two sealed width-64 methods; 686 pre-extracted samples, three seeds, single CPU thread; no training.',
              'first_timing':'Independent fresh process per method/backend; compiler-specific caches start empty by architecture. Subsequent seed weights reuse the graph. Operating-system page caches were not cleared.',
              'timing_runs_per_seed':9,'summary':aggregate,'source_sha256':sha(Path(__file__))})
    print('terminal',sha(out),aggregate,flush=True)
    while not (ROOT/'publication/mosi_fresh_raw-receipt.json').exists():time.sleep(16)
    from publish_mosi import native,git,PREFIX,BRANCH
    root=ROOT/'publication';kind='mosi_fresh_raw/compiled_inference';dest=root/kind;dest.mkdir(exist_ok=True,parents=True)
    fs=[p for p in OUT.iterdir() if p.is_file()]+[Path(__file__),ROOT/'COMPILE_INFERENCE.md']
    paths=[]
    for p in fs:
        q=dest/p.name
        if not q.exists():os.link(p,q)
        assert sha(p)==sha(q);paths.append(q)
    idx=dest/'verified_objects.json';write(idx,{p.name:{'sha256':sha(p),'size':p.stat().st_size} for p in paths});paths.append(idx)
    while True:
        try:
            commit=native(root,kind,paths);b=idx.read_bytes();oid=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
            assert git(root/(kind+'.git'),['rev-parse',commit+':'+PREFIX+kind+'/verified_objects.json'])==oid
            write(root/'compile_inference-receipt.json',{'branch':BRANCH,'commit':commit,'prefix':PREFIX+kind+'/',
                  'manifest_sha256':sha(idx),'manifest_blob':oid,'files':len(paths),'terminal_sha256':sha(out)})
            print('published',commit,flush=True);return
        except (RuntimeError,subprocess.TimeoutExpired) as e:print('retrying',str(e)[-160:],flush=True);time.sleep(50)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--child',nargs=2);a=p.parse_args()
    if a.child:child(*a.child)
    else:run()
