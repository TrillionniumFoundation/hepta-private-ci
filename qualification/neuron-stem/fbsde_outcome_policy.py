"""Same 265-parameter router, contrasting model gain and verified outcome gain.

Labels enter fit/selection only; deployment sees a paid pilot's 15 features.
Both continuations retain one total verification budget. No probability claim
is made for the gate's score and no action is returned after a CPU rejection.
"""
import math
import time
from four_gate_common import digest, require
from fbsde_depth_policy import features, make_router, scalar_score
from fbsde_planning_workspace import PlanningWorkspace
from fbsde_tracking_control import PlanningBudgetError

PRICE = .002  # Explicit utility proxy for escalation; NOT a hardware charge.
TEACHERS = ('model', 'outcome')
ARMS = ('no_checks','one_step','two_step','best_fixed','numeric_router','model_model',
        'model_outcome','outcome_model','outcome_outcome','confidence_outcome',
        'verify_all_unique','exact_reverse')


def fit(torch, rows, teacher):
    require(teacher in TEACHERS and 1 <= len(rows) <= 4096 and
            all(r['source_id'].startswith('train:') for r in rows) and
            len({r['source_id'] for r in rows}) == len(rows), 'training-only outcome router')
    require(all(type(r[teacher+'_gain']) in (float,int) and math.isfinite(r[teacher+'_gain']) and -2.04-1e-12<=r[teacher+'_gain']<=2.04+1e-12 for r in rows),'finite verified teacher gain')
    x = torch.tensor([r['features'] for r in rows])
    y = torch.tensor([float(r[teacher+'_gain'] > PRICE) for r in rows])
    require(x.shape==(len(rows),15) and torch.isfinite(x).all().item(), 'finite feature inventory')
    started = time.process_time_ns(); torch.manual_seed(982451653); model = make_router(torch)
    initial = digest({k:v.detach().tolist() for k,v in model.state_dict().items()})
    optimizer = torch.optim.AdamW(model.parameters(),lr=.01); losses = []
    for _ in range(160):
        optimizer.zero_grad(); loss = torch.nn.functional.binary_cross_entropy_with_logits(model(x),y)
        require(torch.isfinite(loss).item(), 'finite router fit')
        loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
        require(time.process_time_ns()-started <= 15_000_000_000, 'router fit CPU budget')
    model.eval().requires_grad_(False)
    state = {k:v.detach().tolist() for k,v in model.state_dict().items()}
    with torch.inference_mode(): ps=model(x).sigmoid().tolist()
    require(max(abs(p-scalar_score(state,r['features'])) for p,r in zip(ps,rows)) < 1e-6,
            'scalar/Torch parity')
    return {'teacher':teacher,'state':state,'initial_sha256':initial,'losses':losses,
            'positive_labels':int(y.sum()),'parameters':sum(v.numel() for v in model.parameters()),
            'rows_sha256':digest(rows),'cpu_ns':time.process_time_ns()-started}


def select(rows, scores, objective):
    require(objective in TEACHERS and 1 <= len(rows) <= 512 and len(rows)==len(scores)
        and all(r['source_id'].startswith('selection:') for r in rows)
        and len({r['source_id'] for r in rows})==len(rows), 'selection-only outcomes')
    require(all(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1 for p in scores), 'finite scores')
    require(all(type(r[objective+'_gain']) in (float,int) and math.isfinite(r[objective+'_gain']) and -2.04-1e-12<=r[objective+'_gain']<=2.04+1e-12 for r in rows),'finite selection gain')
    grid=[]
    for threshold in sorted(set([0.,1.01,*scores])):
        deep=[s>=threshold for s in scores]
        gain=math.fsum((r[objective+'_gain']-PRICE)*d for r,d in zip(rows,deep))/len(rows)
        grid.append({'threshold':threshold,'mean_increment':gain,'deep':sum(deep)})
    best=max(grid,key=lambda r:(r['mean_increment'],-r['deep'],-r['threshold']))
    return {'selected':best['threshold'],'grid':grid,'objective':objective,'rows_sha256':digest(rows)}


def execute(problem, arm, reveal, bundle=None, *, prepared=None, context=None):
    """Only reveal(event) may expose a true pair, and only AFTER action choice.

    Adaptive root pays a one-step pilot; deeper computation shares the same
    workspace, 20k-node allowance and 100ms process deadline including disposal.
    After one observation at most one verification remains for every strategy.
    """
    require(arm in ARMS and arm not in ('exact_reverse','best_fixed'), 'deployed planner arm')
    started=time.process_time_ns(); h=(); remaining=2; decisions=[]; checks=[]; route=None
    if prepared is not None:
        from fbsde_prepared_gate import PreparedOutcomeGate
        require(type(prepared) is PreparedOutcomeGate and bundle is None and
                arm in ('numeric_router','model_model','model_outcome','outcome_model',
                        'outcome_outcome','confidence_outcome'), 'prepared adaptive arm')
        require(prepared.kind == ('confidence' if arm=='confidence_outcome' else 'learned'),
                'prepared arm kind mismatch')
    else:
        require(context is None, 'request context requires a prepared gate')
    for turn in range(len(problem.laws)+1):
        begin=time.process_time_ns()
        with PlanningWorkspace(problem,h) as w:
            available=w.available_events(h)
            if arm=='verify_all_unique' and available:
                d=None; action=f'verify:{available[0]}'
            else:
                depth=0 if arm in ('no_checks','verify_all_unique') else min(remaining,1 if arm=='one_step' else 2)
                if turn==0 and arm not in ('no_checks','one_step','two_step','verify_all_unique'):
                    if prepared is None:
                        require(bundle is not None and bundle['binding']==problem.binding, 'bound frozen router')
                    else:
                        bundle_id=prepared.bind(problem,context)
                    one=w.solve(h,horizon=1); x=features(problem,h,one,workspace=w)
                    score=(1-x[0] if arm=='confidence_outcome' else scalar_score(bundle['state'],x)) if prepared is None else prepared.score(x)
                    threshold=bundle['threshold'] if prepared is None else prepared.threshold
                    depth=2 if score>=threshold else 1
                    d=w.solve(h,horizon=2) if depth==2 else one
                    route={'features':x,'score':score,'threshold':threshold,
                           'selected_depth':depth,'pilot_value':one['value'],
                           'bundle_sha256':digest(bundle) if prepared is None else bundle_id}
                else: d=w.solve(h,horizon=depth)
                action=d['action']
        elapsed=time.process_time_ns()-begin
        if elapsed>100_000_000:
            raise PlanningBudgetError('outcome router CPU budget exhausted',problem,w.nodes,begin)
        decisions.append({'plan':d,'action':action,'known':h,'nodes':w.nodes,'cpu_ns':elapsed})
        if not action.startswith('verify:'):
            holder=None if action=='abstain' else int(action.split(':')[1]); break
        event=int(action.split(':')[1])
        require(event in available and (arm=='verify_all_unique' or remaining>0), 'legal paid verification')
        observation=reveal(event)  # first point at which selected truth is available
        require(type(observation) is int and 0 <= observation < len(problem.pairs), 'typed source observation')
        checks.append({'event':event,'outcome':observation,'known_before':h})
        h=tuple(sorted(h+((event,observation),))); remaining-=1
    else: raise ValueError('unfinished outcome policy')
    return {'arm':arm,'holder':holder,'text':'Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder],
            'probabilities':problem.marginal(h),'checks':checks,'decisions':decisions,'route':route,
            'depth2_requested':arm=='two_step' or route is not None and route['selected_depth']==2,
            'cpu_ns':time.process_time_ns()-started,'problem_sha256':problem.identity}
