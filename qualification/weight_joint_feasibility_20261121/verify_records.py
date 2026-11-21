"""Independent source/forward/constraint/KKT reader. No optimizer imports."""
from pathlib import Path
import datetime
import gzip
import hashlib
import json
import resource
import sys
import time
import traceback
import numpy as np

ROOT=Path(__file__).resolve().parent


def digest(raw):return hashlib.sha256(raw).hexdigest()


def read(path):
    path=Path(path);raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def check_file(path,pin):
    raw=Path(path).read_bytes()
    assert len(raw)==pin['bytes'] and digest(raw)==pin['sha256'],str(path)
    return raw


def close(actual,expected,name):
    assert np.isfinite(actual) and np.isfinite(expected),name
    assert abs(actual-expected)<=5e-10*(1+abs(expected)),(name,actual,expected)


def forward(network,X):
    w1=np.asarray(network['w1']);b1=np.asarray(network['b1'])
    rows=np.column_stack([np.asarray(network['w2']),np.asarray(network['b2'])])
    hidden=np.empty((len(X),49));zs=np.empty((len(X),4))
    for lo in range(0,len(X),128):
        hi=min(lo+128,len(X))
        a=np.add(np.multiply(X[lo:hi,None,:],w1[None,:,:]).sum(axis=-1),b1)
        hidden[lo:hi,:48]=np.tanh(a);hidden[lo:hi,48]=1.
        zs[lo:hi]=(hidden[lo:hi,None,:]*rows[None,:,:]).sum(axis=-1)
    p=1/(1+np.exp(-np.minimum(700,np.maximum(-700,zs[:,3]))))
    score=np.column_stack([np.zeros(len(X)),zs[:,:3],1-2*p,2*p-1])
    return hidden,rows,score


def affine(H,head):
    zs=np.empty((len(H),4))
    for lo in range(0,len(H),256):
        zs[lo:lo+256]=(H[lo:lo+256,None,:]*head[None,:,:]).sum(axis=-1)
    p=1/(1+np.exp(-np.minimum(700,np.maximum(-700,zs[:,3]))))
    return np.column_stack([np.zeros(len(H)),zs[:,:3],1-2*p,2*p-1])


def blocked_fixed(scores,masks,target):
    blocked=np.zeros(len(target),bool)
    for t in (0,4,5):
        for j in (0,4,5):
            if t==j:continue
            blocked|=(target==t)&masks[:,j]&((scores[:,j]>scores[:,t])|((scores[:,j]==scores[:,t])&(j<t)))
    return blocked


def load_independently(spec):
    base=read(spec['model']);rec=read(spec['reconstruction']);fam=read(spec['family']);disc=read(spec['discovery'])
    check_file(spec['model'],fam['source_C']);check_file(spec['data'],rec['dataset']);check_file(spec['teacher'],fam['teacher'])
    assert fam['program']['own_law_labels_only']
    with np.load(spec['data'],allow_pickle=False) as z:
        X=z['X'];masks=z['legal_masks'];old_scores=z['C_scores'];mixed=z['state_weights'];uniform=z['belief_weights']
    with np.load(spec['teacher'],allow_pickle=False) as z:
        Y=z['own_optimal_targets'];p=z['own_posterior'];sample=z['sample_weights']
    with np.load(spec['discovery_arrays'],allow_pickle=False) as z:old={k:z[k] for k in z.files}
    own=np.column_stack([np.zeros(len(X)),Y[:,:3],1-2*p,2*p-1]);target=np.where(masks,own,-np.inf).argmax(1)
    H,head,scores=forward(base['network'],X)
    assert np.array_equal(scores.view(np.uint64),old_scores.view(np.uint64))
    incumbent=np.where(masks,scores,-np.inf).argmax(1)
    gap=np.maximum(0.,own[np.arange(len(X)),target]-own[np.arange(len(X)),incumbent])
    assert np.array_equal(target,old['own_actions']) and np.array_equal(gap,old['own_action_gap'])
    normocc=np.zeros(len(X));rawocc=np.zeros(len(X));offset=0
    publics=read(spec['publics'])
    assert len(publics)==len(rec['reconstructed_worlds'])==len(fam['program']['TRAIN'])==64
    for wr,tr,public in zip(rec['reconstructed_worlds'],fam['program']['TRAIN'],publics):
        n=wr['rows'];sl=slice(offset,offset+n)
        assert tr['rows']==n
        assert wr['world_id']==tr['world_id']==public['id'] and wr['state_order_sha256']==tr['state_order_sha256']
        assert digest(Y[sl].tobytes())==tr['teacher_sha256'] and digest(sample[sl].tobytes())==tr['sample_weight_sha256']
        eligible=masks[sl,1:4].any(1);e=int(eligible.sum());v=np.zeros(n)
        v[eligible]=(64*mixed[sl][eligible]-.1/e)/.9
        assert v.min()>=-1e-12 and abs(v.sum()-1)<1e-10
        normocc[sl]=np.maximum(v,0.)/64;rawocc[sl]=normocc[sl]*wr['weights']['eligible_occupancy_mass'];offset+=n
    assert offset==len(X) and len(publics)==64 and np.array_equal(normocc,old['incumbent_eligible_occupancy'])
    blocked=blocked_fixed(scores,masks,target)
    assert np.array_equal(blocked,~np.isfinite(old['fixed_Q147_lower_bound']))
    assert not np.any(target[normocc>0]==0)
    radius=.5*float(np.linalg.norm(head[:3]));assert radius==disc['radius']
    return dict(H=H,head=head,scores=scores,masks=masks,target=target,incumbent=incumbent,gap=gap,
                normocc=normocc,rawocc=rawocc,uniform=uniform,blocked=blocked,rec=rec,radius=radius)


def support(d,selection):
    result={}
    weights=[('uniform_full_support',d['uniform']),('C_eligible_normalized_occupancy',d['normocc']),
             ('C_eligible_world_average_visits',d['rawocc']),('C_normalized_occupancy_times_own_gap',d['normocc']*d['gap']),
             ('C_world_average_visits_times_own_gap',d['rawocc']*d['gap'])]
    for k,w in weights:
        total=float(w.sum());selected=float(w[selection].sum())
        result[k]=dict(total=total,selected=selected,fraction=selected/total if total else None)
    result['states']=int(selection.sum());return result


def compare_support(actual,expected):
    assert actual['states']==expected['states']
    for key in actual:
        if key=='states':continue
        for sub in actual[key]:
            if actual[key][sub] is None:assert expected[key][sub] is None
            else:close(actual[key][sub],expected[key][sub],key+'/'+sub)


def check_audit(d,audit):
    H=d['H'];occ=d['normocc']>0;b=d['blocked']
    close(d['radius'],audit['radius'],'radius');assert digest(H.tobytes())==audit['hidden_sha256']
    selections={'full':np.ones(len(H),bool),'occupied':occ,'positive_gap':occ&(d['gap']>0),
        'immutable_all':b,'immutable_occupied':b&occ,'repairable_occupied':~b&occ}
    for name,select in selections.items():compare_support(support(d,select),audit[name])
    assert len(audit['immutable_witnesses'])==int(b.sum())
    assert [w['row'] for w in audit['immutable_witnesses']]==np.flatnonzero(b).tolist()
    boundaries=np.cumsum([0]+[w['rows'] for w in d['rec']['reconstructed_worlds']])
    for w in audit['immutable_witnesses']:
        i=w['row'];t=w['target'];j=w['competitor'];world=int(np.searchsorted(boundaries,i,side='right')-1);wr=d['rec']['reconstructed_worlds'][world]
        assert t==d['target'][i] and t in (0,4,5) and j in (0,4,5) and d['masks'][i,j]
        assert w['world_id']==wr['world_id'] and w['local_row']==i-boundaries[world] and w['state_order_sha256']==wr['state_order_sha256']
        assert d['scores'][i,j]>d['scores'][i,t] or (d['scores'][i,j]==d['scores'][i,t] and j<t)
        for name,v in [('target_score',d['scores'][i,t]),('competitor_score',d['scores'][i,j]),('normalized_eligible_occupancy',d['normocc'][i]),('world_average_eligible_visit',d['rawocc'][i]),('own_action_gap',d['gap'][i])]:close(float(v),w[name],name)


def kkt(A,b,b0,x,z,violation,actual_exact):
    assert all(np.isfinite(v).all() for v in (A,b,b0,x,z))
    multipliers=np.maximum(z,0);adjoint=A.T@multipliers
    primal=.5*float(np.dot(x,x));dual=float(np.dot(b,multipliers))-.5*float(np.dot(adjoint,adjoint))
    closed=float(np.dot(b0,multipliers))-.5*float(np.dot(adjoint,adjoint))
    gap=primal-dual;stationarity=float(np.max(np.abs(x-adjoint)));negative=float(z.min(initial=0.))
    feasible=bool(violation<=1e-8 and actual_exact)
    resolved=bool(feasible and negative>=-1e-8 and stationarity<=1e-7*(1+np.linalg.norm(x)) and abs(gap)<=1e-7*(1+primal))
    return dict(norm=float(np.linalg.norm(x)),primal_objective=primal,dual_objective=dual,
        closed_dual_objective=closed,epsilon_radius_lower=float(np.sqrt(2*max(0.,dual))),closed_radius_lower=float(np.sqrt(2*max(0.,closed))),
        feasible_radius_upper=float(np.linalg.norm(x)) if feasible else None,primal_max_violation=violation,
        raw_dual_min=negative,clipped_stationarity_max_abs=stationarity,primal_dual_gap=gap,
        complementarity_max_abs=float(np.max(np.abs(multipliers*(A@x-b)),initial=0.)),
        actual_F64_target_actions_exact=bool(actual_exact),feasible_upper=feasible,minimum_resolved=resolved)


def check_numeric_report(computed,reported):
    for name,v in computed.items():
        if v is None or isinstance(v,bool):assert reported[name] is v,(name,reported.get(name),v)
        else:close(v,reported[name],name)


def check_case(out,fit,name,d):
    report=read(out/f'fit_{fit}_{name}.json')
    if 'arrays' not in report:
        assert report['status'].startswith('UNKNOWN') and not report.get('feasible_upper',False)
        return dict(case=name,status=report['status'],no_solver_vector=True)
    path=out/report['arrays']['path'];check_file(path,report['arrays'])
    with np.load(path,allow_pickle=False) as z:a={k:z[k] for k in z.files}
    H=d['H'];head=d['head'].copy();occupied=d['normocc']>0;scores=d['scores'];x=a['delta'];dual=a['raw_dual']
    if name=='belief_sign':
        selected=np.flatnonzero(occupied&np.isin(d['target'],[4,5]));assert np.array_equal(a['terminal_rows'],selected)
        signs=np.where(d['target'][selected]==5,1.,-1.)
        A=signs[:,None]*H[selected];threshold=float(2*np.arctanh(1e-4)+1e-7)
        b=threshold-signs*np.sum(H[selected]*head[3],axis=1);b0=b
        head[3]+=x;actual=affine(H,head);term=actual[selected,d['target'][selected]]
        exact=bool(np.all(term>=1e-4));violation=float(max(0.,np.max(b-A@x)))
        close(threshold,report['required_signed_logit'],'belief requirement')
        if 'actual_minimum_signed_logit' in report:
            close(float(np.min(signs*np.sum(H[selected]*head[3],axis=1))),report['actual_minimum_signed_logit'],'actual belief logit')
            close(float(term.min()),report['actual_minimum_target_terminal_score'],'actual belief terminal score')
    else:
        if name=='joint_sequential':
            dep=report['belief_dependency'];check_file(out/dep['path'],dep)
            belief_report=read(out/dep['path']);check_file(out/belief_report['arrays']['path'],belief_report['arrays'])
            with np.load(out/belief_report['arrays']['path'],allow_pickle=False) as z:bd=z['delta']
            assert np.array_equal(a['belief_delta'],bd)
            head[3]+=bd;scores=affine(H,head);assert not np.any(blocked_fixed(scores,d['masks'],d['target'])&occupied)
            selected=occupied
        elif name=='full_repairable_lex':selected=~d['blocked']
        else:selected=occupied&~d['blocked']
        mode='margin' if name=='occ_margin' else 'lex'
        ts=d['target'];editable_target=np.isin(ts,[1,2,3]);pairs=[]
        total=0;max_violation=0.
        shift=np.zeros((len(H),6))
        for j in (1,2,3):shift[:,j]=np.sum(H*x.reshape(3,49)[j-1],axis=1)
        for j in range(6):
            sel=selected&d['masks'][:,j]&(ts!=j)&(editable_target|(j in (1,2,3)))
            rows=np.flatnonzero(sel);total+=len(rows)
            margin=np.full(len(rows),1e-3) if mode=='margin' else 1e-6*(j<ts[rows])
            rhs=scores[rows,j]-scores[rows,ts[rows]]+margin
            lhs=shift[rows,ts[rows]]-shift[rows,j]
            max_violation=max(max_violation,float(np.max(rhs-lhs,initial=0.)))
            pairs.extend((rows*6+j).tolist())
        cids=a['active_cids'];assert cids.ndim==1 and np.issubdtype(cids.dtype,np.integer) and np.array_equal(cids,np.unique(cids))
        assert set(cids.tolist()).issubset(set(pairs)) and total==report['constraints'] and len(cids)==report['active_constraints']
        rows=cids//6;competitors=cids%6
        coefficients=(ts[rows,None]==np.arange(1,4)[None,:]).astype(float)-(competitors[:,None]==np.arange(1,4)[None,:]).astype(float)
        A=(coefficients[:,:,None]*H[rows,None,:]).reshape(len(rows),147)
        b0=scores[rows,competitors]-scores[rows,ts[rows]]
        b=b0+(np.full(len(rows),1e-3) if mode=='margin' else 1e-6*(competitors<ts[rows]))
        head[:3]+=x.reshape(3,49);actual=affine(H,head)
        actions=np.where(d['masks'],actual,-np.inf).argmax(1);exact=bool(np.array_equal(actions[selected],ts[selected]));violation=max_violation
        compare_support(support(d,selected),report['selected_support'])
        if 'actual_support_action_errors' in report:assert report['actual_support_action_errors']==int(np.count_nonzero(actions[selected]!=ts[selected]))
        if name=='joint_sequential' and 'combined_norm' in report:
            combined=float(np.hypot(np.linalg.norm(bd),np.linalg.norm(x)));close(combined,report['combined_norm'],'combined norm')
    assert x.shape==(A.shape[1],) and dual.shape==(len(A),)
    solver_status=report['trace'][-1]['status']
    if solver_status in ('PrimalInfeasible','AlmostPrimalInfeasible'):
        lam=np.maximum(dual,0);lam/=lam.sum();res=float(np.max(np.abs(A.T@lam)));separation=float(b@lam)
        close(res,report['stationarity_max_abs'],'Farkas residual');close(separation,report['separation'],'Farkas separation')
        indication=bool(float(dual.min(initial=0.))>=-1e-8 and res<=1e-8 and separation>1e-9)
        assert report.get('checked_numeric_indication',False)==indication
        assert report['feasible_upper'] is False
        result=dict(case=name,status=report['status'],numerical_infeasibility_indication=indication,not_exact_certificate=True)
    else:
        facts=kkt(A,b,b0,x,dual,violation,exact);check_numeric_report(facts,report)
        if name=='joint_sequential':
            assert report.get('combined_feasible_upper')==(report['combined_norm'] if facts['feasible_upper'] else None)
            label='CHECKED_SEQUENTIAL_UPPER_WITHIN_RADIUS' if facts['feasible_upper'] and report['combined_norm']<=d['radius']*(1-1e-8) else 'NO_CHECKED_JOINT_UPPER_WITHIN_RADIUS'
            assert report['joint_radius_comparison']==label
        elif name!='belief_sign':
            upper=facts['feasible_radius_upper'];lower=facts['closed_radius_lower']
            label='CHECKED_NUMERIC_UPPER_WITHIN_RADIUS' if upper is not None and upper<=d['radius']*(1-1e-8) else ('NUMERIC_CLOSED_LOWER_EXCEEDS_RADIUS' if lower>d['radius']*(1+1e-8) else 'UNDETERMINED')
            assert report['radius_comparison']==label
        if 'TRAIN_behavior' in report:
            actions=np.where(d['masks'],actual,-np.inf).argmax(1);br=report['TRAIN_behavior']
            compare_support(support(d,actions==d['target']),br['target_agreement'])
            compare_support(support(d,actions!=d['incumbent']),br['changed_from_C'])
            assert digest(actions.tobytes())==br['target_action_sha256']
        result=dict(case=name,status=report['status'],**facts)
    return result


def main():
    start=time.process_time();wall=time.perf_counter();out=ROOT/'attempt001';results=[];error=None
    try:
        p=read(ROOT/'PROTOCOL_FROZEN.json')
        for path,pin in p['files'].items():check_file(path,pin)
        study=read(out/'RESULTS.json')
        for fit in p['fits']:
            if str(fit) not in study['fits']:continue
            d=load_independently(p['inputs'][str(fit)])
            check_file(out/f'fit_{fit}_ORIGINAL.json.gz',p['files'][p['inputs'][str(fit)]['model']])
            audit=read(out/f'fit_{fit}_SUPPORT.json');check_audit(d,audit)
            checks=[check_case(out,fit,name,d) for name in ('occ_lex','occ_margin','full_repairable_lex','belief_sign','joint_sequential')]
            results.append(dict(fit=fit,rows=len(d['H']),cached_scores_bit_exact=True,source_chain_checked=True,cases=checks))
            del d
        status='PASS_ALL_DECLARED_RECORDS' if study['status']=='COMPLETED_BOUNDED_DISCOVERY' and len(results)==5 else 'PASS_AVAILABLE_RECORDS_INCOMPLETE_STUDY'
        if not results:status='INSUFFICIENT_COMPLETED_FIT_RECORDS'
    except BaseException as exc:
        status='FAIL_READER_NO_RETRY';error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
    result=dict(schema='hepta-joint-feasibility-independent-reader-v1',status=status,
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),fits=results,error=error,
        original_neural_states_recomputed=sum(v['rows'] for v in results),optimizer_calls=0,
        solver_modules_imported=False,solver_hidden_arrays_used=False,teacher_CTMC_regenerated=False,
        scope='Independent original hidden/ordered scores, source-chain and every declared full-support residual, dual, action and mass check; no new quality evaluation.',
        CPU_seconds=time.process_time(),body_CPU_seconds=time.process_time()-start,wall_seconds=time.perf_counter()-wall,
        peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    with (out/'INDEPENDENT_REVIEW.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(status,flush=True)
    return 2 if error else 0


if __name__=='__main__':sys.exit(main())
