"""Signed-gain weighting for the SAME small computation gate, not a risk claim.

For D=verified(deep)-verified(shallow)-price, weighted binary log loss uses
w=abs(D), y=1[D>0]. Its unrestricted population minimizer is
E[D_+|x]/E[abs(D)|x]; threshold 1/2 has the sign of E[D|x].
This conditional-risk identity is NOT a finite-trained-network guarantee.
"""
from fractions import Fraction as F
import math
import time
from four_gate_common import digest, require
from fbsde_depth_policy import make_router, scalar_score
from fbsde_outcome_policy import PRICE

OBJECTIVES = ('frequency_v1', 'signed_gain_v2')


def targets(rows, objective):
    require(objective in OBJECTIVES and type(rows) is list and 1 <= len(rows) <= 4096,
            'bounded gain fit inventory')
    require(all(type(r.get('source_id')) is str and r['source_id'].startswith('train:') for r in rows)
            and len({r['source_id'] for r in rows}) == len(rows), 'training-only gain sources')
    require(all(type(r.get('outcome_gain')) in (int,float) and math.isfinite(r['outcome_gain'])
                and abs(r['outcome_gain']) <= 2.04+1e-12 for r in rows), 'finite verified gains')
    net = [r['outcome_gain']-PRICE for r in rows]
    return [float(d>0) for d in net], [1. if objective==OBJECTIVES[0] else abs(d) for d in net]


def fit(torch, rows, objective):
    """Identical initialization, architecture, optimizer and steps for both losses."""
    started=time.process_time_ns(); y, weights=targets(rows,objective)
    x=torch.tensor([r['features'] for r in rows])
    require(x.shape==(len(rows),15) and torch.isfinite(x).all().item(), 'finite current features')
    y=torch.tensor(y); weights=torch.tensor(weights)
    require(float(weights.sum())>0, 'zero effective gain weight')
    torch.manual_seed(982451653); model=make_router(torch)
    initial=digest({k:v.detach().tolist() for k,v in model.state_dict().items()})
    optimizer=torch.optim.AdamW(model.parameters(),lr=.01); losses=[]
    for _ in range(160):
        optimizer.zero_grad()
        raw=torch.nn.functional.binary_cross_entropy_with_logits(model(x),y,reduction='none')
        loss=(raw*weights).sum()/weights.sum()
        require(torch.isfinite(loss).item(), 'finite signed-gain loss')
        loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
        require(time.process_time_ns()-started<=15_000_000_000, 'gain fit CPU budget')
    model.eval().requires_grad_(False)
    state={k:v.detach().tolist() for k,v in model.state_dict().items()}
    with torch.inference_mode(): ps=model(x).sigmoid().tolist()
    require(max(abs(p-scalar_score(state,r['features'])) for p,r in zip(ps,rows))<1e-6,
            'gain scalar/Torch parity')
    return {'objective':objective,'state':state,'initial_sha256':initial,'losses':losses,
        'steps':160,'parameters':sum(p.numel() for p in model.parameters()),'rows_sha256':digest(rows),
        'weight_sum':float(weights.sum()),'positive_labels':int(y.sum()),
        'cpu_ns':time.process_time_ns()-started,'score_is_success_probability':False}


def counterexample():
    """Exact two-context witness: frequency cannot order gains of different sizes."""
    contexts=[[(F(9,10),F(1,100)),(F(1,10),F(-99,100))],
              [(F(1,10),F(99,100)),(F(9,10),F(-1,100))]]
    result=[]
    for law in contexts:
        positive=sum(p*d for p,d in law if d>0); negative=sum(-p*d for p,d in law if d<0)
        result.append({'positive_frequency':str(sum(p for p,d in law if d>0)),
            'weighted_score':str(positive/(positive+negative)),
            'expected_net_gain':str(positive-negative)})
    return {'contexts':result,'optimal_deep':[False,True],
        'best_frequency_threshold_mean_gain':'0','weighted_half_mean_gain':'9/200',
        'synthetic_population_identity_not_semantic_evidence':True}
