"""The sole bounded main study. Never mutates source checkpoints."""
import datetime
import gc
import os
from pathlib import Path
import resource
import sys
import time
import traceback
import numpy as np
from common import ROOT,FITS,read,save,identity,sha,verify_pin_map,load_fit
import joint_solver as solver


def weighted_support(data,mask):
    result={}
    for name,w in [('uniform_full_support',data['uniform']),
                   ('C_eligible_normalized_occupancy',data['normocc']),
                   ('C_eligible_world_average_visits',data['rawocc']),
                   ('C_normalized_occupancy_times_own_gap',data['normocc']*data['gap']),
                   ('C_world_average_visits_times_own_gap',data['rawocc']*data['gap'])]:
        total=float(w.sum());part=float(w[mask].sum())
        result[name]=dict(total=total,selected=part,fraction=part/total if total>0 else None)
    result['states']=int(np.count_nonzero(mask))
    return result


def behavior(data,scores):
    actions=np.where(data['masks'],scores,-np.inf).argmax(1)
    exact=actions==data['target']
    return dict(target_agreement=weighted_support(data,exact),
        changed_from_C=weighted_support(data,actions!=data['incumbent']),
        target_action_sha256=sha(actions.tobytes()),
        no_new_policy_occupancy_or_end_to_end_value_evaluated=True)


def relation(report,radius):
    lower=report.get('closed_radius_lower')
    upper=report.get('feasible_radius_upper')
    if upper is not None and upper<=radius*(1-1e-8):return 'CHECKED_NUMERIC_UPPER_WITHIN_RADIUS'
    if lower is not None and lower>radius*(1+1e-8):return 'NUMERIC_CLOSED_LOWER_EXCEEDS_RADIUS'
    return 'UNDETERMINED'


def main():
    protocol=read(ROOT/'PROTOCOL_FROZEN.json');out=ROOT/'attempt001'
    if not out.is_dir() or any(out.iterdir()):raise ValueError('single supervisor-created empty attempt required')
    start=time.process_time();wall=time.perf_counter();stage='source_verification'
    save(out/'STARTED.json',dict(protocol_sha256=identity(ROOT/'PROTOCOL_FROZEN.json')['sha256'],
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        affinity=sorted(os.sched_getaffinity(0)),threads={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
        resource_limits={str(k):list(resource.getrlimit(k)) for k in (resource.RLIMIT_CPU,resource.RLIMIT_AS)}))
    results={};status='IN_PROGRESS';failure=None
    try:
        verify_pin_map(protocol['files'])
        for fit in FITS:
            if time.process_time()>=105:break
            fitstart=time.process_time();stage=f'fit_{fit}_source_load'
            data=load_fit(protocol['inputs'][str(fit)]);base=data['base'];original=Path(protocol['inputs'][str(fit)]['model']).read_bytes()
            with (out/f'fit_{fit}_ORIGINAL.json.gz').open('xb') as f:f.write(original)
            def remaining():
                return max(0.,min(105-time.process_time(),18-(time.process_time()-fitstart),175-(time.perf_counter()-wall)))
            stage=f'fit_{fit}_strict_hidden_forward'
            H,logits,scores=solver.strict_hidden_and_scores(base,data['X'])
            if not np.array_equal(scores.view(np.uint64),data['scores'].view(np.uint64)):
                raise ArithmeticError('original cached scores differ bitwise')
            head=np.c_[np.asarray(base['network']['w2']),np.asarray(base['network']['b2'])]
            radius=.5*float(np.linalg.norm(head[:3]))
            if radius!=data['discovery']['radius']:raise ArithmeticError('old radius differs')
            blocked,witness=solver.immutable_obstructions(scores,data['masks'],data['target'])
            if not np.array_equal(blocked,~np.isfinite(data['previous']['fixed_Q147_lower_bound'])):
                raise ArithmeticError('fixed terminal obstructions differ')
            occupied=data['normocc']>0;repairable=~blocked
            witnesses=[]
            for row in np.flatnonzero(blocked):
                world=int(data['worldindex'][row]);j=int(witness[row]);t=int(data['target'][row])
                witnesses.append(dict(row=int(row),world_id=data['rec']['reconstructed_worlds'][world]['world_id'],
                    local_row=int(data['localindex'][row]),state_order_sha256=data['rec']['reconstructed_worlds'][world]['state_order_sha256'],
                    target=t,competitor=j,target_score=float(scores[row,t]),competitor_score=float(scores[row,j]),
                    normalized_eligible_occupancy=float(data['normocc'][row]),world_average_eligible_visit=float(data['rawocc'][row]),
                    own_action_gap=float(data['gap'][row]),strict_lower_index=bool(j<t)))
            audit=dict(fit=fit,rows=len(H),worlds=64,radius=radius,
                hidden_sha256=sha(H.tobytes()),cached_scores_bit_exact=True,
                label_source='sealed checkpoint own-law optimal Bellman teacher, not older own_Q/incumbent teacher',
                full=weighted_support(data,np.ones(len(H),bool)),occupied=weighted_support(data,occupied),
                positive_gap=weighted_support(data,occupied&(data['gap']>0)),
                immutable_all=weighted_support(data,blocked),immutable_occupied=weighted_support(data,blocked&occupied),
                repairable_occupied=weighted_support(data,repairable&occupied),
                all_strict_target_matching='FIXED_TERMINAL_ORDER_OBSTRUCTION' if blocked.any() else 'NO_FIXED_OBSTRUCTION',
                occupied_strict_target_matching='FIXED_TERMINAL_ORDER_OBSTRUCTION' if (blocked&occupied).any() else 'NO_FIXED_OBSTRUCTION',
                immutable_witnesses=witnesses,scope='exposed TRAIN finite support only')
            save(out/f'fit_{fit}_SUPPORT.json',audit)
            cases={}
            for name,selected,mode,cap,cutting in [
                ('occ_lex',occupied&repairable,'lex',3.,False),
                ('occ_margin',occupied&repairable,'margin',2.,False),
                ('full_repairable_lex',repairable,'lex',6.,True)]:
                stage=f'fit_{fit}_{name}'
                report,arrays,new_scores=solver.solve_q(H,head,scores,data['masks'],data['target'],selected,mode,remaining,cap,cutting)
                report.update(fit=fit,case=name,radius=radius,radius_comparison=relation(report,radius),
                    selected_support=weighted_support(data,selected),parameter_coordinates=147,
                    fixed_terminal_states_removed=int(np.count_nonzero(blocked & (occupied if name.startswith('occ') else True))))
                if new_scores is not None:report['TRAIN_behavior']=behavior(data,new_scores)
                if arrays:
                    ap=out/f'fit_{fit}_{name}.npz';np.savez_compressed(ap,**arrays)
                    report['arrays']=dict(path=ap.name,**identity(ap))
                save(out/f'fit_{fit}_{name}.json',report);cases[name]=report
            stage=f'fit_{fit}_belief_sign'
            br,ba,bhead=solver.solve_belief(H,head,data['target'],occupied,remaining)
            br.update(fit=fit,case='belief_sign',radius=radius,parameter_coordinates=49)
            if ba:
                ap=out/f'fit_{fit}_belief_sign.npz';np.savez_compressed(ap,**ba);br['arrays']=dict(path=ap.name,**identity(ap))
            save(out/f'fit_{fit}_belief_sign.json',br);cases['belief_sign']=br
            if br.get('feasible_upper') and bhead is not None:
                stage=f'fit_{fit}_joint_sequential'
                bscores=solver.scores_from_rows(H,bhead)
                bblocked,_=solver.immutable_obstructions(bscores,data['masks'],data['target'])
                if np.any(bblocked&occupied):raise ArithmeticError('belief feasible claim leaves occupied terminal obstruction')
                qr,qa,qscores=solver.solve_q(H,bhead,bscores,data['masks'],data['target'],occupied,'lex',remaining,2.,False)
                qr.update(fit=fit,case='joint_sequential',radius=radius,parameter_coordinates=196,
                    belief_dependency=dict(path=f'fit_{fit}_belief_sign.json',**identity(out/f'fit_{fit}_belief_sign.json')),
                    selected_support=weighted_support(data,occupied),globally_minimum_joint_radius_claimed=False)
                if qa:
                    qa['belief_delta']=ba['delta']
                    ap=out/f'fit_{fit}_joint_sequential.npz';np.savez_compressed(ap,**qa);qr['arrays']=dict(path=ap.name,**identity(ap))
                    combined=float(np.hypot(np.linalg.norm(ba['delta']),np.linalg.norm(qa['delta'])))
                    qr['combined_norm']=combined
                    qr['combined_feasible_upper']=combined if qr.get('feasible_upper') else None
                    qr['joint_radius_comparison']='CHECKED_SEQUENTIAL_UPPER_WITHIN_RADIUS' if qr.get('feasible_upper') and combined<=radius*(1-1e-8) else 'NO_CHECKED_JOINT_UPPER_WITHIN_RADIUS'
                if qscores is not None:qr['TRAIN_behavior']=behavior(data,qscores)
            else:
                qr=dict(fit=fit,case='joint_sequential',status='UNKNOWN_BELIEF_PREREQUISITE_UNRESOLVED',feasible_upper=False)
            save(out/f'fit_{fit}_joint_sequential.json',qr);cases['joint_sequential']=qr
            original_path=Path(protocol['inputs'][str(fit)]['model'])
            if original_path.read_bytes()!=original or (out/f'fit_{fit}_ORIGINAL.json.gz').read_bytes()!=original:
                raise ValueError('original checkpoint byte identity changed')
            results[str(fit)]=dict(support_path=f'fit_{fit}_SUPPORT.json',cases={k:dict(path=f'fit_{fit}_{k}.json',status=v['status'],feasible_upper=v.get('feasible_upper',False),minimum_resolved=v.get('minimum_resolved',False)) for k,v in cases.items()},
                CPU_seconds=time.process_time()-fitstart,original_gzip_unchanged=True)
            save(out/f'fit_{fit}_DONE.json',results[str(fit)])
            print(f'FIT {fit} complete CPU={time.process_time()-fitstart:.6f}',flush=True)
            del data,H,logits,scores,head,blocked,witness,base,cases
            gc.collect()
        stage='final_source_verification';verify_pin_map(protocol['files'])
        status='COMPLETED_BOUNDED_DISCOVERY' if len(results)==5 else 'STOPPED_AT_FROZEN_GLOBAL_BUDGET'
    except BaseException as error:
        status='FAILED_NO_RETRY';failure=dict(stage=stage,type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
        save(out/'FAILURE.json',failure)
    report=dict(status=status,scope='TRAIN joint feasibility only; no generalization/financial quality claim',
        fits=results,completed_fits=len(results),failure=failure,CPU_seconds=time.process_time(),
        measured_body_CPU_seconds=time.process_time()-start,wall_seconds=time.perf_counter()-wall,
        peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        gradient_updates=0,production_weight_writes=0,production_deployment=False,
        solver_attempts='one study attempt, fixed cases/cutting-plane inner algorithm; no retry or fallback',
        new_DEV_worlds=0,new_CONF_worlds=0,automatic_retry=False,NDU_default='KEEP_ORIGINAL_AND_STOP',
        protocol_sha256=identity(ROOT/'PROTOCOL_FROZEN.json')['sha256'])
    save(out/'RESULTS.json',report)
    print(status,flush=True)
    return 0 if status!='FAILED_NO_RETRY' else 2


if __name__=='__main__':sys.exit(main())
