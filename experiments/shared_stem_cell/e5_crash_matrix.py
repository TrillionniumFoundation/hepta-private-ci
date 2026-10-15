#!/usr/bin/env python3
"""Run true SIGKILL phase matrix; verify only committed SGD checkpoints survive.

The current host process-kill experiment is NOT proof of power-cut durability,
production artifact CAS, revocation handling, or future task utility.
"""
from __future__ import annotations
import argparse,hashlib,json,os,resource,subprocess,sys,tempfile,time
from pathlib import Path
import torch
from e5_packed_momentum_replay import initialize,train,serialize,restore
from e5_crash_atomic_store import ZERO,FAILPOINTS,canonical,commit,load

SCHEMA='hepta.e5.actual-sigkill-atomic-checkpoint.v1'

def exercise(logical=64,active=8,points=FAILPOINTS):
    if logical not in (64,256,1024,4096) or type(active) is not int or not 1<=active<=logical:
        raise ValueError('unregistered cohort')
    if not points or len(points)!=len(set(points)) or any(p not in FAILPOINTS for p in points):
        raise ValueError('missing/duplicate/unknown fault stage')
    scope='shadow.scoped';gen=2;fence='a'*64;model='b'*64
    torch.set_num_threads(1)
    start=time.perf_counter_ns()
    bank,mom,selected=initialize(logical,active)
    first_loss=train(bank,mom,selected,2)
    old=serialize(bank,mom,selected,scope,gen,2)
    remaining_loss=train(bank,mom,selected,2)
    new=serialize(bank,mom,selected,scope,gen,4)
    expected_bank={k:v.detach().clone() for k,v in bank.items()}
    expected_mom={k:v.detach().clone() for k,v in mom.items()}
    stages=[]
    for point in points:
        with tempfile.TemporaryDirectory(prefix='e5-crash-store-') as d:
            directory=Path(d);root=directory/'cas';root.mkdir(mode=0o700)
            first=commit(root,old,scope,gen,fence,model,ZERO)
            filename=directory/'uncommitted-next.json';filename.write_bytes(canonical(new))
            command=[sys.executable,str(Path(__file__).with_name('e5_crash_atomic_store.py')),
                     '--store',str(root),'--snapshot',str(filename),'--scope',scope,
                     '--generation',str(gen),'--fence',fence,'--model',model,
                     '--expected',first['manifest_sha256'],'--crash',point]
            crashed=subprocess.run(command,timeout=120,capture_output=True,
                  env={**os.environ,'HEPTA_E5_CRASH_INJECTION':'research-only'})
            if crashed.returncode!=-9:
                raise RuntimeError('child did not terminate by SIGKILL at '+point)
            recovered=load(root,scope,gen,fence,model,logical)
            step=recovered['snapshot']['steps']
            if step not in (2,4):raise RuntimeError('torn or unexpected optimizer step count')
            if point not in ('head_replaced','head_dirsynced') and step!=2:
                raise RuntimeError('uncommitted snapshot became visible')
            if step==2:
                b,m,s=restore(recovered['snapshot'],scope,gen,logical)
                if train(b,m,s,2)!=remaining_loss:
                    raise RuntimeError('partial restart changed loss trajectory')
                again=serialize(b,m,s,scope,gen,4)
                commit(root,again,scope,gen,fence,model,recovered['manifest_sha256'])
            final=load(root,scope,gen,fence,model,logical)
            if final['snapshot']['steps']!=4:raise RuntimeError('recovery failed to complete SGD')
            finalbank,finalmomentum,_=restore(final['snapshot'],scope,gen,logical)
            if any(not torch.equal(finalbank[k],expected_bank[k]) or not torch.equal(finalmomentum[k],expected_mom[k]) for k in expected_bank):
                raise RuntimeError('full cell weight or momentum divergence')
            stages.append({'failpoint':point,'child_exit_signal':'SIGKILL','child_returncode':-9,
                'observed_step_after_crash':step,'final_step':4,'replay_bit_exact':True,
                'prelabel_or_production_outcome_authenticated':False,
                'stage_manifest_sha256':final['manifest_sha256']})
    return {'schema':SCHEMA,'authority':'DENY_ALL','production_promotion_permitted':False,
        'logical_cells':logical,'active_cells':active,'real_child_sigkill_count':len(points),
        'cut_points_checked':list(points),'stage_observations':stages,
        'same_seed_four_step_reference_momentum_and_weights_bit_exact':True,
        'reference_training_loss_sequence_sha256':hashlib.sha256(canonical(first_loss+remaining_loss)).hexdigest(),
        'process_wall_ms':(time.perf_counter_ns()-start)/1e6,
        'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'power_loss_durability_verified':False,'production_WAL_CAS_or_FinalUse_verified':False,
        'independent_model_origin_verified':False,'real_pretrained_encoder_forward_executed':False,
        'real_future_ndu_verified':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cells',type=int,default=64,choices=(64,256,1024,4096))
    p.add_argument('--active',type=int,default=8)
    p.add_argument('--failpoint',action='append',choices=FAILPOINTS)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('write-once physical experiment evidence')
    result=exercise(a.cells,a.active,tuple(a.failpoint) if a.failpoint else FAILPOINTS)
    with a.output.open('x',encoding='utf8') as f:
        json.dump(result,f,indent=2,sort_keys=True,allow_nan=False)
        f.write('\n')
if __name__=='__main__':main()
