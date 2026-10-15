"""Real child SIGKILL sparse-safetensors checkpoint wave-2 writer and restore."""
import argparse,json,os,resource,subprocess,sys,tempfile,time
from pathlib import Path
import torch
from e5_delta_cas import ZERO,FAILPOINTS,config,fresh,wave,commit,restore,state_hash,freeze,canonical,_manifest

def run(logical=64,active=8,points=FAILPOINTS):
    torch.set_num_threads(1)
    cfg=config(logical,active,20261014,'e5.shadow','a'*64,'b'*64)
    before=time.perf_counter_ns()
    ideal=fresh(cfg);wave(ideal,cfg,1);wave(ideal,cfg,2)
    benchmark_hash=state_hash(ideal)
    cumulative_bytes=len(freeze(ideal,cfg))
    observations=[]
    for point in points:
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'store';root.mkdir()
            old=fresh(cfg);wave(old,cfg,1)
            prev=commit(root,cfg,1,ZERO,old)
            cmd=[sys.executable,str(Path(__file__).with_name('e5_delta_cas.py')),
                 '--store',str(root),'--action','second','--cells',str(logical),
                 '--active',str(active),'--epoch','1','--crash',point,
                 '--output',str(Path(d)/'child-result.json')]
            child=subprocess.run(cmd,capture_output=True,timeout=150,
                                 env={**os.environ,'HEPTA_E5_CRASH_INJECTION':'research-only',
                                      'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            if child.returncode!=-9:raise RuntimeError(f'child {point} not SIGKILL: {child.returncode} {child.stderr[-500:]}')
            recovered,receipt=restore(root,cfg,1)
            observed=receipt['wave']
            expected=2 if point in ('head_replaced','head_dirsynced') else 1
            if observed!=expected:raise RuntimeError(f'invisible delta became selected: {point}, wave={observed}')
            if observed==1:
                wave(recovered,cfg,2)
                latest=commit(root,cfg,1,prev['manifest_sha256'],recovered)
                new_bytes=latest['snapshot_bytes']
            else:
                new_bytes=_manifest(root,receipt['manifest_sha256'])['blob_bytes']
            final,final_report=restore(root,cfg,1)
            if final_report['wave']!=2 or state_hash(final)!=benchmark_hash:
                raise RuntimeError(f'checkpoint replay differs from uninterrupted training {point}')
            observations.append({'failpoint':point,'child_sigkill_verified_by_parent':True,
                'observed_recovery_wave':observed,'final_wave':2,
                'full_bank_and_momentum_bit_exact':True,
                'observed_incremental_payload_bytes':new_bytes})
    return {'schema':'hepta.e5.delta-safetensors-process-kill.v1',
            'logical_cells':logical,'active_cells':active,'sigkill_processes':len(observations),
            'cumulative_sparse_two_wave_checkpoint_bytes':cumulative_bytes,
            'full_dense_fp32_weight_payload_bytes':logical*9744*4,
            'events':observations,'reported_process_wall_ms':(time.perf_counter_ns()-before)/1e6,
            'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'synthetic_labels_and_features':True,'native_worker_or_wal_verified':False,
            'independent_powerloss_verified':False,'independent_future_ndu_verified':False,
            'authority':'DENY_ALL','production_promotion_permitted':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cells',type=int,default=64)
    p.add_argument('--active',type=int,default=8)
    p.add_argument('--failpoint',action='append');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('write once')
    v=run(a.cells,a.active,tuple(a.failpoint) if a.failpoint else FAILPOINTS)
    a.output.write_bytes(canonical(v)+b'\n')
