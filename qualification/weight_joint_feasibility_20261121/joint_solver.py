"""Bounded fixed-hidden convex programs. No optimizer or forward on import."""
import time
import numpy as np
import scipy.sparse as sparse
import clarabel


def strict_hidden_and_scores(base, X):
    n={k:np.asarray(v,dtype=np.float64) for k,v in base['network'].items()}
    hidden=[];scores=[];logits=[]
    head=np.c_[n['w2'],n['b2']]
    for start in range(0,len(X),128):
        x=X[start:start+128]
        h=np.tanh(np.sum(n['w1'][None,:,:]*x[:,None,:],axis=2)+n['b1'])
        H=np.c_[h,np.ones(len(h))]
        z=np.sum(head[None,:,:]*H[:,None,:],axis=2)
        p=1/(1+np.exp(-np.clip(z[:,3],-700,700)))
        hidden.append(H);logits.append(z)
        scores.append(np.c_[np.zeros(len(h)),z[:,:3],1-2*p,2*p-1])
    return np.concatenate(hidden),np.concatenate(logits),np.concatenate(scores)


def scores_from_rows(H, head):
    rows=[]
    for start in range(0,len(H),256):
        z=np.sum(head[None,:,:]*H[start:start+256,None,:],axis=2)
        p=1/(1+np.exp(-np.clip(z[:,3],-700,700)))
        rows.append(np.c_[np.zeros(len(z)),z[:,:3],1-2*p,2*p-1])
    return np.concatenate(rows)


def immutable_obstructions(scores,masks,target):
    blocked=np.zeros(len(target),bool);witness=np.full(len(target),-1,np.int64)
    fixed=(target==0)|(target==4)|(target==5)
    own=scores[np.arange(len(target)),target]
    for j in (0,4,5):
        bad=fixed & masks[:,j] & (target!=j) & ((scores[:,j]>own)|((scores[:,j]==own)&(j<target)))
        witness[bad & ~blocked]=j;blocked|=bad
    return blocked,witness


def constraint_metadata(scores,masks,target,selected,mode):
    teditable=(target>=1)&(target<=3)
    js=np.arange(6)[None,:]
    variable=teditable[:,None]|((js>=1)&(js<=3))
    use=masks & variable & (js!=target[:,None]) & selected[:,None]
    rows,competitors=np.nonzero(use)
    b0=scores[rows,competitors]-scores[rows,target[rows]]
    margin=(1e-6*(competitors<target[rows]) if mode=='lex' else np.full(len(rows),1e-3))
    return dict(rows=rows,competitors=competitors,cids=rows*6+competitors,
                b0=b0,b=b0+margin,margin=margin)


def materialize(H,target,meta,positions):
    rows=meta['rows'][positions];js=meta['competitors'][positions];ts=target[rows]
    A=np.zeros((len(rows),147),dtype=np.float64)
    for k in (1,2,3):
        at=np.flatnonzero(ts==k);A[at,(k-1)*49:k*49]+=H[rows[at]]
        at=np.flatnonzero(js==k);A[at,(k-1)*49:k*49]-=H[rows[at]]
    return A


def full_lhs(H,target,meta,delta):
    change=np.c_[np.zeros(len(H)),H@delta.reshape(3,49).T,np.zeros((len(H),2))]
    r=meta['rows'];return change[r,target[r]]-change[r,meta['competitors']]


def select_worst(meta,target,deficit,used=None,only_violated=False):
    chosen=[]
    for t in range(6):
        for j in range(6):
            mask=(target[meta['rows']]==t)&(meta['competitors']==j)
            if only_violated:mask &= deficit>1e-8
            ix=np.flatnonzero(mask)
            if used is not None:ix=ix[~used[ix]]
            if len(ix):
                ix=ix[np.lexsort((meta['cids'][ix],-deficit[ix]))[:8]]
                chosen.extend(ix.tolist())
    return np.asarray(sorted(chosen),dtype=np.int64)


def invoke(A,b,time_limit):
    settings=clarabel.DefaultSettings()
    settings.verbose=False;settings.max_threads=1
    settings.max_iter=100;settings.time_limit=float(time_limit)
    settings.direct_solve_method='qdldl'
    settings.tol_gap_abs=1e-9;settings.tol_gap_rel=1e-9;settings.tol_feas=1e-9
    settings.tol_infeas_abs=1e-9;settings.tol_infeas_rel=1e-9
    started=time.process_time();wall=time.perf_counter()
    solver=clarabel.DefaultSolver(sparse.eye(A.shape[1],format='csc'),
        np.zeros(A.shape[1]),sparse.csc_matrix(-A),-b,
        [clarabel.NonnegativeConeT(len(b))],settings)
    solution=solver.solve()
    return (np.asarray(solution.x),np.asarray(solution.z),
        dict(status=str(solution.status),iterations=int(solution.iterations),
             CPU_seconds=time.process_time()-started,wall_seconds=time.perf_counter()-wall,
             requested_wall_seconds=float(time_limit)))


def diagnostics(A,b,b0,x,z,all_violation,actual_actions_exact):
    if not all(np.isfinite(v).all() for v in (A,b,b0,x,z)):
        return dict(status='UNKNOWN_NONFINITE',feasible_upper=False,minimum_resolved=False)
    dual=np.maximum(z,0.);at=A.T@dual
    objective=.5*float(x@x);dual_value=float(b@dual)-.5*float(at@at)
    closed_dual=float(b0@dual)-.5*float(at@at)
    slack=A@x-b
    primal=float(max(0.,all_violation))
    stationarity=float(np.max(np.abs(x-at)))
    gap=objective-dual_value
    finite_feasible=bool(primal<=1e-8 and actual_actions_exact)
    residuals=bool(primal<=1e-8 and float(z.min(initial=0.))>=-1e-8 and
        stationarity<=1e-7*(1+np.linalg.norm(x)) and abs(gap)<=1e-7*(1+objective))
    return dict(status='FEASIBLE_NUMERIC_UPPER_BOUND' if finite_feasible else 'UNKNOWN_NO_CHECKED_UPPER',
        feasible_upper=finite_feasible,minimum_resolved=bool(finite_feasible and residuals),
        norm=float(np.linalg.norm(x)),primal_objective=objective,dual_objective=dual_value,
        closed_dual_objective=closed_dual,epsilon_radius_lower=float(np.sqrt(2*max(0.,dual_value))),
        closed_radius_lower=float(np.sqrt(2*max(0.,closed_dual))),
        feasible_radius_upper=float(np.linalg.norm(x)) if finite_feasible else None,
        primal_max_violation=primal,raw_dual_min=float(z.min(initial=0.)),
        clipped_stationarity_max_abs=stationarity,primal_dual_gap=gap,
        complementarity_max_abs=float(np.max(np.abs(dual*slack),initial=0.)),
        actual_F64_target_actions_exact=bool(actual_actions_exact),
        floating_point_numeric_not_exact_certificate=True)


def infeasibility_indication(A,b,z):
    if not np.isfinite(z).all():return dict(status='UNKNOWN_NONFINITE_DUAL')
    rawmin=float(z.min(initial=0.));l=np.maximum(z,0.);total=float(l.sum())
    if total<=0:return dict(status='UNKNOWN_EMPTY_INFEASIBILITY_VECTOR')
    l/=total;res=float(np.max(np.abs(A.T@l)));sep=float(b@l)
    checked=rawmin>=-1e-8 and res<=1e-8 and sep>1e-9
    return dict(status='NUMERICAL_FARKAS_INDICATION' if checked else 'UNKNOWN_UNCHECKED_INFEASIBILITY',
        raw_dual_min=rawmin,normalized_L1=1.,stationarity_max_abs=res,
        separation=sep,checked_numeric_indication=bool(checked),not_an_exact_certificate=True)


def solve_q(H,head,scores,masks,target,selected,mode,remaining,cap,cutting=False):
    start=time.process_time();wall=time.perf_counter()
    meta=constraint_metadata(scores,masks,target,selected,mode)
    if not len(meta['rows']):
        raise ValueError('empty declared joint Q problem')
    active=select_worst(meta,target,meta['b']) if cutting else np.arange(len(meta['b']))
    traces=[];last=None
    for iteration in range(8 if cutting else 1):
        limit=min(remaining(),cap-(time.perf_counter()-wall),1. if cutting else cap)
        if limit<.03:break
        A=materialize(H,target,meta,active)
        x,z,info=invoke(A,meta['b'][active],limit)
        info['active_constraints']=len(active);info['iteration']=iteration
        traces.append(info);last=(A,x,z,active.copy())
        if info['status'] in ('PrimalInfeasible','AlmostPrimalInfeasible'):
            break
        if not np.isfinite(x).all():break
        deficit=meta['b']-full_lhs(H,target,meta,x)
        info['complete_max_violation']=float(max(0.,deficit.max(initial=0.)))
        if not cutting or deficit.max(initial=0.)<=1e-8:break
        if info['status'] not in ('Solved','AlmostSolved'):break
        used=np.zeros(len(meta['b']),bool);used[active]=True
        extra=select_worst(meta,target,deficit,used,True)
        if not len(extra) or len(active)+len(extra)>2048:break
        active=np.unique(np.r_[active,extra])
    if last is None:
        return dict(status='UNKNOWN_BUDGET_BEFORE_SOLVE',CPU_seconds=time.process_time()-start,
                    constraints=len(meta['b']),trace=traces),dict(),None
    A,x,z,active=last
    arrays=dict(delta=x,raw_dual=z,active_cids=meta['cids'][active])
    status=traces[-1]['status']
    if status in ('PrimalInfeasible','AlmostPrimalInfeasible'):
        result=infeasibility_indication(A,meta['b'][active],z);new_scores=None
        result.update(feasible_upper=False,minimum_resolved=False)
    elif np.isfinite(x).all():
        changed=head.copy();changed[:3]+=x.reshape(3,49)
        new_scores=scores_from_rows(H,changed)
        action=np.where(masks,new_scores,-np.inf).argmax(1)
        violation=float(max(0.,np.max(meta['b']-full_lhs(H,target,meta,x))))
        exact=bool(np.array_equal(action[selected],target[selected]))
        result=diagnostics(A,meta['b'][active],meta['b0'][active],x,z,violation,exact)
        result['actual_support_action_errors']=int(np.count_nonzero(action[selected]!=target[selected]))
    else:
        result=dict(status='UNKNOWN_NONFINITE_ITERATE',feasible_upper=False,minimum_resolved=False);new_scores=None
    result.update(constraints=len(meta['b']),active_constraints=len(active),
        CPU_seconds=time.process_time()-start,wall_seconds=time.perf_counter()-wall,
        trace=traces,margin_mode=mode,cutting_plane=cutting,
        support_states=int(np.count_nonzero(selected)),epsilon_optimum_not_exact_strict_minimum=True)
    return result,arrays,new_scores


def solve_belief(H,head,target,occupied,remaining,cap=2.):
    rows=np.flatnonzero(occupied & ((target==4)|(target==5)))
    signs=np.where(target[rows]==5,1.,-1.)
    A=H[rows]*signs[:,None]
    original_logit=np.sum(H[rows]*head[3],axis=1)
    margin=float(2*np.arctanh(1e-4)+1e-7);b=margin-signs*original_logit
    limit=min(remaining(),cap)
    if limit<.03:return dict(status='UNKNOWN_BUDGET_BEFORE_SOLVE',feasible_upper=False),dict(),None
    x,z,info=invoke(A,b,limit)
    arrays=dict(delta=x,raw_dual=z,terminal_rows=rows)
    if info['status'] in ('PrimalInfeasible','AlmostPrimalInfeasible'):
        report=infeasibility_indication(A,b,z);report.update(feasible_upper=False,minimum_resolved=False);changed=None
    elif np.isfinite(x).all():
        changed=head.copy();changed[3]+=x
        actual=np.sum(H[rows]*changed[3],axis=1)*signs
        actual_scores=scores_from_rows(H,changed)
        terminal_scores=actual_scores[rows,target[rows]]
        report=diagnostics(A,b,b,x,z,float(max(0.,np.max(b-A@x))),bool(np.all(terminal_scores>=1e-4)))
        report['actual_minimum_signed_logit']=float(actual.min())
        report['actual_minimum_target_terminal_score']=float(terminal_scores.min())
    else:report=dict(status='UNKNOWN_NONFINITE_ITERATE',feasible_upper=False);changed=None
    report.update(trace=[info],terminal_states=len(rows),required_signed_logit=margin,
                  norm_scope='49 belief coordinates; not a global joint196 minimum')
    return report,arrays,changed
