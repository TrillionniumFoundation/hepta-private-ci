"""Finite-support necessary edit radii; exposed TRAIN data only, no solver."""
import time
import numpy as np
from compile_core import OLD, FT, CAUSAL, c, mlp, read, identity


def weighted_report(values, weights, radius):
    weights = np.maximum(0., weights)
    total = float(weights.sum())
    if total == 0: return dict(total_weight=0., quantiles=None)
    positive = weights > 0
    values, weights = values[positive], weights[positive]
    finite = np.isfinite(values)
    order = np.argsort(values, kind='stable')
    cum = np.cumsum(weights[order])/total
    quantiles = {}
    for q in (0., .1, .25, .5, .75, .9, .99, 1.):
        ix = min(int(np.searchsorted(cum, q, side='left')), len(order)-1)
        val = float(values[order[ix]])
        quantiles[str(q)] = val if np.isfinite(val) else 'infinite_fixed_terminal_obstruction'
    return dict(total_weight=total, quantiles=quantiles,
        mass_necessary_radius_above_budget=float(weights[values > radius].sum()/total),
        mass_fixed_terminal_obstruction=float(weights[~finite].sum()/total),
        mass_bound_within_budget=float(weights[values <= radius].sum()/total),
        finite_weighted_mean=float(np.sum(values[finite]*weights[finite])/weights[finite].sum())
            if weights[finite].sum() else None)


def fit_audit(fit, base, budget):
    started = time.process_time()
    path = FT/'attempt001'/f'fit_{fit}_CANDIDATE.json.gz'
    record = read(path)
    data_path = FT/'attempt001'/record['dataset']['path']
    if identity(data_path) != {k:record['dataset'][k] for k in ('bytes','sha256')}:
        raise ValueError('cached exposed TRAIN identity changed')
    data = np.load(data_path)
    teacher_path = CAUSAL/'attempt001/TRAIN'/f'fit_{fit}_teacher.npz'
    teacher = np.load(teacher_path)
    X = data['X']; masks=data['legal_masks']; old_scores=data['C_scores']
    hidden, _logits, _p, scores = mlp.strict_chunks(mlp.pack(base), X)
    if not np.array_equal(scores, old_scores):
        raise ArithmeticError('cached original forward changed')
    Hnorm = np.sqrt(np.sum(hidden*hidden, axis=1)+1.)
    Xnorm = np.sqrt(np.sum(X*X, axis=1)+1.)
    p = teacher['own_posterior']; ownQ = np.c_[np.zeros(len(X)),
        teacher['own_optimal_targets'][:,:3], 1-2*p, 2*p-1]
    actions = np.where(masks,scores,-np.inf).argmax(1)
    desired = np.where(masks,ownQ,-np.inf).argmax(1)
    gap = ownQ[np.arange(len(X)),desired]-ownQ[np.arange(len(X)),actions]
    if np.any(gap < -1e-14): raise ArithmeticError('negative optimum regret')
    gap = np.maximum(0., gap)
    Qhead=np.c_[base['network']['w2'],base['network']['b2']][:3]
    radius=.5*float(np.linalg.norm(Qhead))
    w=np.asarray(base['network']['w2']); wnorm=np.linalg.norm(w,axis=1)
    fixed_lb=np.zeros(len(X)); whole_lb=np.zeros(len(X))
    obstruction=np.zeros(len(X),bool)
    # Each target must beat every legal competitor. Max of single-constraint
    # radius infima is necessary for their intersection, not sufficient; strict
    # tie-priority constraints need not attain the infimum.
    for target in range(6):
        indices=np.flatnonzero(desired==target)
        for competitor in range(6):
            if competitor == target: continue
            ix=indices[masks[indices,competitor]]
            if not len(ix): continue
            budget()
            margin=np.maximum(0.,scores[ix,competitor]-scores[ix,target])
            tc=target in (1,2,3); cc=competitor in (1,2,3)
            tb=target in (4,5); cb=competitor in (4,5)
            if tc or cc:
                coefficient=np.sqrt(2.) if tc and cc else 1.
                local=margin/(coefficient*Hnorm[ix])
                fixed_lb[ix]=np.maximum(fixed_lb[ix],local)
            else:
                impossible=(scores[ix,competitor]>scores[ix,target]) | (
                    (scores[ix,competitor]==scores[ix,target]) & (competitor<target))
                obstruction[ix[impossible]]=True
            if tc and cc:
                M=float(np.linalg.norm(w[target-1]-w[competitor-1])); B=np.sqrt(2.)
            elif tc or cc:
                j=(target if tc else competitor)-1
                M=wnorm[j]+(.5*wnorm[3] if tb or cb else 0.)
                B=np.sqrt(1.25) if tb or cb else 1.
            elif tb and cb:
                M=wnorm[3]; B=1.
            else:
                M=.5*wnorm[3]; B=.5
            L=np.sqrt((M*Xnorm[ix])**2+(B*Hnorm[ix])**2)
            # |Delta gap| <= L*r + (B*||[x,1]||/2)*r^2.
            root=2*margin/(L+np.sqrt(L*L+2*B*Xnorm[ix]*margin))
            whole_lb[ix]=np.maximum(whole_lb[ix],root)
    fixed_lb[obstruction]=np.inf
    # Recover original eligible C occupancy from the sealed .9/.1 mixture.
    occupancy=np.zeros(len(X)); offset=0
    for world in record['reconstructed_worlds']:
        n=world['rows']; ix=slice(offset,offset+n)
        eligible=masks[ix,1:4].any(1); E=int(eligible.sum())
        mixed=data['state_weights'][ix]*64
        recovered=np.zeros(n)
        recovered[eligible]=(mixed[eligible]-.1/E)/.9
        if np.min(recovered)<-1e-12 or abs(recovered.sum()-1)>1e-10:
            raise ArithmeticError('exposed occupancy mixture inversion')
        occupancy[ix]=np.maximum(0.,recovered)/64
        offset+=n
    if offset!=len(X): raise ArithmeticError('TRAIN block order changed')
    difference=actions!=desired
    weights=dict(uniform_full_support=data['belief_weights'],
        incumbent_eligible_occupancy=occupancy,
        incumbent_occupancy_times_own_action_gap=occupancy*gap,
        disagreement_occupancy=occupancy*difference)
    output=dict(fit=fit, scope='DISCOVERY on previously exposed original TRAIN; no held-out claim',
        rows=len(X), worlds=64, radius=radius,
        changed_optimal_actions=int(difference.sum()),
        fixed_terminal_obstruction_states=int(obstruction.sum()),
        own_action_gap_weighted=float(np.sum(occupancy*gap)),
        original_forward_cache_byte_exact=True,
        fixed_Q147_lower_bound={key:weighted_report(fixed_lb,val,radius) for key,val in weights.items()},
        whole_MLP4324_lower_bound={key:weighted_report(whole_lb,val,radius) for key,val in weights.items()},
        finite_Q147_max_bound=float(np.max(fixed_lb[np.isfinite(fixed_lb)])),
        whole_MLP_max_bound=float(whole_lb.max()),
        neither_bound_within_radius_establishes_feasibility=True,
        full_network_global_impossibility_claim=False,
        inputs=dict(dataset=dict(path=str(data_path),**identity(data_path)),
                    teacher=dict(path=str(teacher_path),**identity(teacher_path))),
        CPU_seconds=time.process_time()-started)
    arrays=dict(fixed_Q147_lower_bound=fixed_lb,whole_MLP4324_lower_bound=whole_lb,
        own_actions=desired,C_actions=actions,own_action_gap=gap,
        incumbent_eligible_occupancy=occupancy,full_uniform_weights=data['belief_weights'])
    return output,arrays
