"""Learned one/two-step computation allocation, not a new exact or risk solver.

The router sees only public conditional beliefs and an already PAID one-step
plan. No task text, correct pairs, targets or two-step result enters inference.
Choosing one step is an approximation; training regret is not a risk certificate.
"""
import math
import time
from four_gate_common import digest, require
from fbsde_tracking_control import plan, PlanningBudgetError

PROFILE = 'learned_depth_allocation_v1'
ENGINES = ('fresh_solve_v1', 'shared_continuation_v2')
WIDTH = 15
GAIN_PRICE = .002  # Declared model-utility price, NOT measured CPU or hardware price.
THRESHOLDS = (0., .25, .5, .75, 1.01)


def features(problem, known, one, *, workspace=None):
    require(problem.actors == 3 and one['problem_sha256'] == problem.identity,
            'three-actor current-model router input')
    require(one['remaining_checks'] == 1 and tuple(one['known']) == problem.history(known),
            'router must use this history and paid one-step plan')
    conditional = workspace if workspace is not None else problem
    p = one['probabilities']; available = conditional.available_events(known)
    def entropy(q): return -math.fsum(x*math.log(x) for x in q if x > 0)/math.log(3)
    laws = [conditional.outcome_law(i, known) for i in available]
    ent = [entropy(q) for q in laws] or [0.]
    peaks = [max(q) for q in laws] or [1.]
    stop = max(0., 2*max(p)-1)
    value = sorted(p, reverse=True) + [one['value'], stop, one['value']-stop,
        entropy(p), len(available)/16, len(problem.laws)/16, max(ent),
        math.fsum(ent)/len(ent), max(peaks), min(peaks),
        len(set(problem.keys))/len(problem.keys), max(conditional.member_posterior(known))]
    require(len(value) == WIDTH and all(math.isfinite(x) for x in value), 'finite router features')
    return value


def make_router(torch):
    nn = torch.nn
    class Router(nn.Module):
        def __init__(self):
            super().__init__()
            self.value = nn.Linear(WIDTH, 8)
            self.gate = nn.Linear(WIDTH, 8)
            self.out = nn.Linear(8, 1)
        def forward(self, x):
            return self.out(self.value(x).tanh()*self.gate(x).sigmoid()).squeeze(-1)
    return Router()


def scalar_score(state, values):
    """Pure scalar inference; its parity with the trained Torch Head is tested."""
    expected = {'value.weight':(8,WIDTH),'gate.weight':(8,WIDTH),'out.weight':(1,8),
                'value.bias':(8,), 'gate.bias':(8,), 'out.bias':(1,)}
    require(type(state) is dict and set(state) == set(expected), 'complete router tensors')
    for key, dims in expected.items():
        value = state[key]
        require(type(value) is list and len(value) == dims[0], 'router tensor shape')
        if len(dims) == 2:
            require(all(type(row) is list and len(row) == dims[1] for row in value), 'router tensor shape')
            value = [x for row in value for x in row]
        require(all(type(x) in (float,int) and math.isfinite(x) for x in value), 'finite router tensor')
    require(type(values) is list and len(values) == WIDTH and all(type(x) in (float,int) and math.isfinite(x) for x in values),
            'bounded finite router vector')
    def linear(name, x):
        w, b = state[name+'.weight'], state[name+'.bias']
        require(len(w) == len(b) and all(len(r) == len(x) for r in w), 'router tensor shape')
        return [math.fsum(a*v for a,v in zip(row,x))+offset for row,offset in zip(w,b)]
    def sigmoid(x):
        require(math.isfinite(x), 'nonfinite router logit')
        return 1/(1+math.exp(-x)) if x >= 0 else math.exp(x)/(1+math.exp(x))
    v, g = linear('value',values), linear('gate',values)
    require(len(v) == len(g) == 8, 'bounded hidden width')
    out = linear('out',[math.tanh(a)*sigmoid(b) for a,b in zip(v,g)])
    require(len(out) == 1, 'one allocation probability')
    return sigmoid(out[0])


def fit_router(torch, rows):
    require(type(rows) is list and 1 <= len(rows) <= 4096, 'bounded router training rows')
    require(all(r['input']['source_id'].startswith('train:') for r in rows)
            and len({digest(r['input']) for r in rows}) == len(rows), 'training-only router sources')
    torch.manual_seed(982451653); model = make_router(torch)
    initial = {k:v.detach().tolist() for k,v in model.state_dict().items()}
    x = torch.tensor([r['features'] for r in rows]); y = torch.tensor([float(r['gain'] > GAIN_PRICE) for r in rows])
    require(torch.isfinite(x).all().item() and set(y.tolist()) == {0.,1.}, 'both teacher classes required')
    started = time.process_time_ns(); optimizer = torch.optim.AdamW(model.parameters(), lr=.01)
    losses = []
    for _ in range(160):
        optimizer.zero_grad(); loss = torch.nn.functional.binary_cross_entropy_with_logits(model(x),y)
        require(torch.isfinite(loss).item(), 'finite depth-learning loss')
        loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
        require(time.process_time_ns()-started <= 15_000_000_000, 'router training CPU budget')
    model.eval().requires_grad_(False)
    state = {k:v.detach().tolist() for k,v in model.state_dict().items()}
    with torch.inference_mode(): actual = model(x).sigmoid().tolist()
    require(max(abs(a-scalar_score(state,r['features'])) for a,r in zip(actual,rows)) < 1e-6,
            'scalar/Torch route probability differs')
    return {'state':state,'initial':initial,'losses':losses,'steps':160,
        'parameters':sum(p.numel() for p in model.parameters()),'cpu_ns':time.process_time_ns()-started,
        'training_sha256':digest(rows),'teacher_is_model_not_observed_success':True}


def select_threshold(rows, state, kind, selection_profile="registered_coarse_v1"):
    require(kind in ('learned','confidence') and rows, 'selection profile')
    require(len(rows) <= 512 and all(r['input']['source_id'].startswith('selection:') for r in rows)
            and len({digest(r['input']) for r in rows}) == len(rows), 'selection-only router sources')
    require(selection_profile in ('registered_coarse_v1','validation_breakpoints_v2'), 'threshold profile')
    thresholds = THRESHOLDS
    if selection_profile == 'validation_breakpoints_v2':
        points = [scalar_score(state,r['features']) if kind=='learned'
                  else math.nextafter(r['features'][0],math.inf) for r in rows]
        thresholds = sorted(set([0.,1.01,*points]))
    scored = []
    for threshold in thresholds:
        deep = [(scalar_score(state,r['features']) >= threshold if kind == 'learned'
                 else r['features'][0] < threshold) for r in rows]
        value = math.fsum((0. if d else r['gain'])+GAIN_PRICE*d for r,d in zip(rows,deep))/len(rows)
        scored.append({'threshold':threshold,'model_regret_plus_price':value,'deep_calls':sum(deep)})
    best = min(scored,key=lambda r:(r['model_regret_plus_price'],r['deep_calls'],r['threshold']))
    return {'selected':best['threshold'],'grid':scored,'selection_profile':selection_profile,'source_sha256':digest(rows),
            'selection_uses_external_outcomes':False}


def allocate(problem, known, remaining, mode, bundle, *, engine=ENGINES[0]):
    require(mode in ('myopic','full','learned','confidence','frozen','learned_complete','confidence_complete') and type(remaining) is int
            and 0 <= remaining <= 2, 'bounded depth mode/horizon')
    require(type(bundle['context']) is dict and set(bundle['context']) == {'source','model','calibration','scope','generation'}
            and digest(bundle['context']) == problem.binding
            and bundle['context']['model'] == bundle['model']
            and bundle['context']['calibration'] == bundle['calibration']
            and bundle['problem_binding'] == problem.binding, 'router model/calibration scope binding')
    require(engine in ENGINES, 'explicit planning engine')
    from fbsde_planning_workspace import PlanningWorkspace
    started = time.process_time_ns()
    work = PlanningWorkspace(problem, known) if engine == ENGINES[1] else None
    def solve(*, horizon, max_nodes=20000):
        # Workspace node counts are cumulative; no fresh allowance on escalation.
        return (work.solve(known, horizon=horizon) if work is not None else
                plan(problem, known, horizon=horizon, max_nodes=max_nodes))
    try:
        if remaining < 2 or mode == 'full':
            result = solve(horizon=min(remaining,1 if mode=='myopic' else 2))
            route = {'features':None,'probability':None,'selected_depth':result['remaining_checks'],
                     'planner_cpu_ns':result['cpu_ns'],'one_step_cpu_ns':0,
                     'planner_nodes':result['nodes'],'one_step_nodes':0}
        else:
            one = solve(horizon=1); values = features(problem,known,one,workspace=work)
            probability = scalar_score(bundle['initial' if mode=='frozen' else 'state'],values) if mode in ('learned','frozen','learned_complete') else None
            deep = (probability >= (bundle['complete_threshold'] if mode=='learned_complete' else bundle['threshold'] if mode=='learned' else .5) if probability is not None
                    else values[0] < (bundle['complete_confidence_threshold'] if mode=='confidence_complete' else bundle['confidence_threshold']) if mode in ('confidence','confidence_complete') else False)
            if deep and one['nodes'] >= 20000:
                raise PlanningBudgetError('combined depth-allocation node budget exhausted',problem,one['nodes'],started)
            result = solve(horizon=2,max_nodes=20000-one['nodes']) if deep else one
            route = {'features':values,'probability':probability,'selected_depth':2 if deep else 1,
                     'one_step_cpu_ns':one['cpu_ns'],'planner_cpu_ns':one['cpu_ns']+(result['cpu_ns'] if deep else 0),
                     'one_step_nodes':one['nodes'],'planner_nodes':one['nodes']+(result['nodes'] if deep else 0)}
    finally:
        if work is not None:
            work.close()
    elapsed = time.process_time_ns()-started
    if elapsed > 100_000_000:
        error = PlanningBudgetError('combined depth-allocation CPU budget exhausted',problem,result['nodes'],started)
        error.evidence.update(route=route); raise error
    return result, {**route,'cpu_ns':elapsed,'known':known,'remaining':remaining,
        'mode':mode,'problem_sha256':problem.identity,'bundle_sha256':digest(bundle),
        'returned':True,'exact_two_step_optimality_claimed':mode=='full',
        'planning_engine':engine, 'workspace':work.counters() if work is not None else None}
