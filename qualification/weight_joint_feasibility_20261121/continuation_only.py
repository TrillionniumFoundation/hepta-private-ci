"""Parent-authorized posthoc belief-independent necessary subset; one attempt."""
from pathlib import Path
import json
import time
import resource
import numpy as np
import verify_records as reader
import joint_solver as solver

ROOT=Path(__file__).resolve().parent


def main():
    out=ROOT/'posthoc_continuation_only';out.mkdir(exist_ok=False)
    seal=reader.read(ROOT/'CONTINUATION_ONLY_PROTOCOL.json')
    for path,pin in seal['files'].items():reader.check_file(path,pin)
    original=reader.read(ROOT/'PROTOCOL_FROZEN.json');records=[];forward_rows=0
    for fit in original['fits']:
        if time.process_time()>=4.2:break
        started=time.process_time();d=reader.load_independently(original['inputs'][str(fit)])
        H=d['H'];forward_rows+=len(H);audit=reader.read(ROOT/'attempt001'/f'fit_{fit}_SUPPORT.json')
        assert reader.digest(H.tobytes())==audit['hidden_sha256']
        t=d['target'];oc=d['normocc']>0;selected=oc&np.isin(t,[1,2,3])
        ii,jj=np.nonzero(d['masks']&selected[:,None]&np.isin(np.arange(6),[1,2,3])[None,:]&(np.arange(6)[None,:]!=t[:,None]))
        coeff=(t[ii,None]==np.arange(1,4)).astype(float)-(jj[:,None]==np.arange(1,4)).astype(float)
        A=(coeff[:,:,None]*H[ii,None,:]).reshape(len(ii),147)
        b0=d['scores'][ii,jj]-d['scores'][ii,t[ii]];margin=1e-6*(jj<t[ii]);b=b0+margin
        limit=min(.35,4.5-time.process_time())
        if limit<=.03:
            records.append(dict(fit=fit,status='UNKNOWN_TOTAL_CPU_BUDGET_AFTER_H_RECOVERY',rows=len(H)));break
        x,z,info=solver.invoke(A,b,limit)
        subset_rows=np.unique(ii);hp=out/f'fit_{fit}_CHECKED_H.npy';np.save(hp,H[subset_rows])
        ap=out/f'fit_{fit}_SOLVER.npz';np.savez(ap,delta=x,raw_dual=z,rows=ii,competitors=jj,H_row_ids=subset_rows)
        record=dict(fit=fit,rows=len(H),constraints=len(ii),occupied_continuation_target_states=int(selected.sum()),
            source_hidden_sha256=reader.digest(H.tobytes()),checked_H_path=hp.name,checked_H_sha256=reader.digest(hp.read_bytes()),
            solver_arrays_path=ap.name,solver_arrays_sha256=reader.digest(ap.read_bytes()),solver=info,radius=d['radius'],
            parameter_scope='Q147; necessary for any belief49 choice with the same fixed hidden and total196 norm budget',
            strict_tie_margin=1e-6,forward_recovery_rows=len(H),
            zero_new_Q_closed_residual=float(np.max(np.abs(b0+A@d['head'][:3].ravel()))),
            zero_new_Q_delta_norm=float(np.linalg.norm(d['head'][:3])),
            new_candidate_for_quality_evaluation=False)
        if info['status'] in ('PrimalInfeasible','AlmostPrimalInfeasible'):
            indication=solver.infeasibility_indication(A,b,z);record.update(indication)
            lam=np.maximum(z,0);lam/=lam.sum();adjoint=A.T@lam;norm=float(np.linalg.norm(adjoint))
            sep=float(b0@lam);sep_eps=float(b@lam);u=np.finfo(float).eps/2;m=len(ii);g=(2*m+4)*u/(1-(2*m+4)*u)
            absadj=np.abs(A).T@lam/(1-g);adjerr=g*absadj
            normup=(norm+float(np.linalg.norm(adjerr)))*(1+300*u/(1-300*u))
            rhserr=2*u*(np.abs(d['scores'][ii,jj])+np.abs(d['scores'][ii,t[ii]]))
            se= g*float(np.abs(b0)@lam)/(1-g)+float(rhserr@lam)/(1-g)
            exclusion=sep-se-d['radius']*normup*(1+4*u)-4*u*(abs(sep)+se+d['radius']*normup)
            record.update(closed_separation=sep,epsilon_separation=sep_eps,adjoint_L2=norm,
                radius_times_adjoint_L2=d['radius']*norm,closed_radius_exclusion_after_roundoff_sensitivity=exclusion,
                closed_exclusion_supported=bool(exclusion>1e-10),closed_radius_lower_sensitivity=max(0.,sep-se)/normup,
                interpretation='Numerical infeasibility of the declared strict-margin necessary subset. Closed-radius exclusion is a separate explicit flag; no exact certificate.')
        else:
            new=d['head'][:3]+x.reshape(3,49)
            q=np.sum(H[:,None,:]*new[None,:,:],axis=2)
            differences=q[ii,t[ii]-1]-q[ii,jj-1]
            actual=bool(np.all(np.where(jj<t[ii],differences>0.,differences>=0.)))
            facts=reader.kkt(A,b,b0,x,z,float(max(0.,np.max(b-A@x))),actual)
            record.update(facts,status='NECESSARY_SUBSET_FEASIBLE' if facts['feasible_upper'] else 'UNKNOWN_NO_CHECKED_NECESSARY_SUBSET_UPPER',
                continuation_pair_conditions_actual_F64=actual,
                interpretation='Feasibility of this necessary subset never establishes full joint196 feasibility or quality.')
        record['CPU_seconds']=time.process_time()-started
        with (out/f'fit_{fit}.json').open('x') as f:json.dump(record,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
        records.append(record)
        del d,H,A
    result=dict(schema='hepta-continuation-only-necessary-subset-posthoc-v1',
        status='COMPLETED' if len(records)==5 and all('solver' in x for x in records) else 'PARTIAL_BUDGET_UNKNOWN',
        posthoc=True,parent_authorized_H_recovery=True,original_hidden_forward_rows=forward_rows,
        optimizer_calls=sum('solver' in x for x in records),gradient_updates=0,new_CONF=0,
        cases=records,CPU_seconds=time.process_time(),peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        no_retry=True,no_global_architecture_certificate=True)
    with (out/'SUMMARY.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(json.dumps({'status':result['status'],'CPU_seconds':result['CPU_seconds'],'cases':[{'fit':x['fit'],'status':x['status']} for x in records]}))


if __name__=='__main__':main()
