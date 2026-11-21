"""Post-result, parent-requested diagnostic of existing duals; no optimization."""
from pathlib import Path
import json
import time
import resource
import numpy as np
import verify_records as reader

ROOT=Path(__file__).resolve().parent


def gamma(n):
    u=np.finfo(np.float64).eps/2
    return n*u/(1-n*u)


def main():
    start=time.process_time();out=ROOT/'posthoc_closed_dual';out.mkdir(exist_ok=False)
    protocol=reader.read(ROOT/'POSTHOC_AUDIT_PROTOCOL.json')
    for path,pin in protocol['files'].items():reader.check_file(path,pin)
    frozen=reader.read(ROOT/'PROTOCOL_FROZEN.json');records=[]
    for fit in frozen['fits']:
        d=reader.load_independently(frozen['inputs'][str(fit)])
        for name in ('occ_lex','occ_margin','full_repairable_lex','joint_sequential'):
            old=reader.read(ROOT/'attempt001'/f'fit_{fit}_{name}.json')
            if old['trace'][-1]['status'] not in ('PrimalInfeasible','AlmostPrimalInfeasible'):
                records.append(dict(fit=fit,case=name,status='NOT_AN_INFEASIBILITY_VECTOR'));continue
            path=ROOT/'attempt001'/old['arrays']['path'];reader.check_file(path,old['arrays'])
            with np.load(path,allow_pickle=False) as z:cid=z['active_cids'];raw=z['raw_dual'];belief=z['belief_delta'] if 'belief_delta' in z else None
            chosen=np.maximum(raw,0.);chosen/=chosen.sum()
            H=d['H'];target=d['target'];rows=cid//6;comp=cid%6;scores=d['scores']
            if belief is not None:
                head=d['head'].copy();head[3]+=belief;scores=reader.affine(H,head)
            coeff=(target[rows,None]==np.arange(1,4)[None,:]).astype(float)-(comp[:,None]==np.arange(1,4)[None,:]).astype(float)
            A=(coeff[:,:,None]*H[rows,None,:]).reshape(len(rows),147)
            b0=scores[rows,comp]-scores[rows,target[rows]]
            margin=np.full(len(rows),1e-3) if name=='occ_margin' else 1e-6*(comp<target[rows])
            adjoint=A.T@chosen;norm=float(np.linalg.norm(adjoint));sep=float(b0@chosen);eps_sep=float((b0+margin)@chosen)
            reader.close(eps_sep,old['separation'],'existing normalized separation')
            reader.close(float(np.max(np.abs(adjoint))),old['stationarity_max_abs'],'existing adjoint residual')
            # Standard dot-product rounding sensitivity, treating stored H and
            # this stored nonnegative dual as fixed real coefficients. This is
            # not a machine-checked interval bound or a CTMC/hidden-error bound.
            g=gamma(2*len(rows)+4);u=np.finfo(np.float64).eps/2
            abs_adjoint=(np.abs(A).T@chosen)/(1-g)
            adjoint_error=g*abs_adjoint
            norm_error=float(np.linalg.norm(adjoint_error))*(1+gamma(300))
            norm_upper=(norm+norm_error)*(1+gamma(300))
            rhs_rounding=2*u*(np.abs(scores[rows,comp])+np.abs(scores[rows,target[rows]]))
            sep_error=g*float(np.abs(b0)@chosen)/(1-g)+float(rhs_rounding@chosen)/(1-g)
            radius=d['radius'];allowance=radius*norm;allowance_upper=radius*norm_upper*(1+4*u)
            raw_exclusion=sep-allowance
            sensitivity_exclusion=sep-sep_error-allowance_upper-4*u*(abs(sep)+sep_error+allowance_upper)
            necessary_radius=max(0.,sep-sep_error)/norm_upper if norm_upper>0 else None
            top=np.lexsort((cid,-chosen))[:12]
            details=[];bounds=np.cumsum([0]+[w['rows'] for w in d['rec']['reconstructed_worlds']])
            for k in top:
                row=int(rows[k]);wi=int(np.searchsorted(bounds,row,side='right')-1);wr=d['rec']['reconstructed_worlds'][wi]
                details.append(dict(cid=int(cid[k]),row=row,target=int(target[row]),competitor=int(comp[k]),
                    normalized_dual=float(chosen[k]),closed_rhs=float(b0[k]),world_id=wr['world_id'],
                    local_row=int(row-bounds[wi]),state_order_sha256=wr['state_order_sha256'],
                    normalized_C_eligible_occupancy=float(d['normocc'][row]),own_action_gap=float(d['gap'][row])))
            record=dict(fit=fit,case=name,status='NUMERIC_CLOSED_RADIUS_EXCLUSION_SUPPORTED' if sensitivity_exclusion>1e-10 else 'EPSILON_ONLY_OR_UNRESOLVED',
                radius=radius,constraints=len(rows),raw_dual_min=float(raw.min(initial=0.)),
                normalized_dual_sha256=reader.digest(chosen.tobytes()),closed_separation=sep,
                epsilon_separation=eps_sep,epsilon_contribution=float(margin@chosen),
                adjoint_L2=norm,adjoint_Linf=float(np.max(np.abs(adjoint))),radius_times_adjoint_L2=allowance,
                raw_closed_radius_exclusion_margin=raw_exclusion,
                dot_roundoff_gamma=g,closed_separation_roundoff_allowance=sep_error,
                adjoint_L2_roundoff_allowance=norm_error,adjoint_L2_upper_sensitivity=norm_upper,
                closed_radius_exclusion_after_roundoff_sensitivity=sensitivity_exclusion,
                joint_necessary_radius_lower_sensitivity=necessary_radius,
                adjoint_vector=adjoint.tolist(),top_dual_rows=details,
                source_arrays=old['arrays'],global_infeasibility_or_exact_certificate_claimed=False,
                coefficient_scope='stored F64 H, original scores and chosen nonnegative dual; ordinary IEEE dot-product error model, no interval verification',
                policy_scope='Q147 with fixed original belief' if belief is None else 'Q147 conditional on the one previously fixed belief solution; not all joint196 choices')
            records.append(record)
            with (out/f'fit_{fit}_{name}.json').open('x') as f:json.dump(record,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    result=dict(schema='hepta-existing-dual-closed-radius-posthoc-v1',status='COMPLETED',posthoc=True,
        motivation='Root requested separating epsilon infeasibility from closed constraints and checking within-radius separation using the same saved dual.',
        no_solver_calls=True,optimizer_calls=0,original_hidden_states_recomputed=144397,
        records=records,CPU_seconds=time.process_time(),body_CPU_seconds=time.process_time()-start,
        peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        errors_not_included=['original hidden computation error relative to another execution model','own-law teacher correctness beyond existing source chain','conditioning of alternative joint belief/representation choices'],
        no_global_architecture_impossibility_claim=True)
    with (out/'SUMMARY.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(json.dumps({'status':result['status'],'CPU_seconds':result['CPU_seconds'],'cases':len(records),'supported':sum(x['status']=='NUMERIC_CLOSED_RADIUS_EXCLUSION_SUPPORTED' for x in records)}))


if __name__=='__main__':main()
