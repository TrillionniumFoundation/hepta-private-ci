"""Exhaustive small-cache and finite-trajectory rejection audit; no randomness."""
from copy import deepcopy
from fractions import Fraction as F
from itertools import product
from pathlib import Path
from types import SimpleNamespace
import argparse,hashlib,json,time
from .contract import Contract,State,key
from .exact_solver import full_dp,history_reference
from .anytime import Partial,reverse_influence,classical_occupancy,priorities,solve


def encode(x):
    if isinstance(x,F):return str(x)
    if isinstance(x,State):return key(x)
    raise TypeError(type(x).__name__)


def enumerate_policy(c,method,exact=None):
    leaves=[]
    for h,prior in enumerate(c.prior):
        initial=Partial(c) if method!='full_dp' else None
        def walk(s,view,mass,fees,elapsed,history):
            if method=='full_dp':
                work=exact['planning_units']+len(history)+1
                action=exact['actions'][s];trace=[]
            else:
                answer=solve(view,s,method)
                action=answer['action'];trace=answer['trace'];work=view.work
            if work*c.compute_time>c.compute_reserve:
                raise ArithmeticError('Planning clock exceeded declared reserve')
            step={'state':key(s),'action':action,'expansions':trace,'planning_units':work}
            if action in ('stop','follow','flip'):
                value=c.terminal_world(action,h)-fees-c.time_price*elapsed
                compute_cost=work*c.compute_price+c.time_price*work*c.compute_time
                leaves.append({'world':h,'conditional_mass':mass,'prior_mass':prior*mass,
                    'terminal_action':action,'terminal_score_after_deployment_fees':c.terminal_world(action,h),
                    'calibration_fees':fees,'calibration_time':elapsed,'labels':s.labels,
                    'planning_units':work,'planning_time':work*c.compute_time,
                    'planning_charge_including_time':compute_cost,'validation_fee':c.validation_fee,
                    'before_planning_validation_value':value,
                    'net_value':value-compute_cost-c.validation_fee,'history':history+[step]})
                if elapsed+work*c.compute_time>c.deadline+c.compute_reserve:
                    raise ArithmeticError('Hard clock violated')
                return
            for p,child in c.world_responses(s,action,h):
                walk(child,deepcopy(view) if view is not None else None,mass*p,
                     fees+c.fee(action),elapsed+c.duration(action),history+[step])
        walk(c.root,initial,F(1),F(0),0,[])
    for h in range(len(c.prior)):
        if sum((r['conditional_mass'] for r in leaves if r['world']==h),F(0))!=1:
            raise ArithmeticError('A common policy lost terminal mass')
    fields=['terminal_score_after_deployment_fees','calibration_fees','calibration_time','labels',
            'planning_units','planning_time','planning_charge_including_time','validation_fee',
            'before_planning_validation_value','net_value']
    return {'leaves':leaves,'expected':{f:sum((r['prior_mass']*r[f] for r in leaves),F(0)) for f in fields}}


def run():
    began=time.perf_counter();checks=0;cache_records=[];cases=[]
    def require(test,message):
        nonlocal checks
        checks+=1
        if not test:raise AssertionError(message)
    for deadline in range(5):
        c=Contract(deadline=deadline)
        exact=full_dp(c);independent=history_reference(c)
        require(exact['value']==independent['value'],'DP/history oracle disagreement')
        root_candidate=Partial(c);root_classic=Partial(c)
        a=solve(root_candidate,c.root,'candidate');b=solve(root_classic,c.root,'classical')
        require(a==b,'Different expansion trace or root certificate')
        require(root_candidate.work==root_classic.work,'Different declared scheduler work')
        require(exact['q'][c.root][a['action']]==exact['value'],'Invalid first-action certificate')
        actual_candidate=enumerate_policy(c,'candidate')
        actual_classic=enumerate_policy(c,'classical')
        exact_policy=enumerate_policy(c,'full_dp',exact)
        require(actual_candidate==actual_classic,'Different warm-cache trajectory, cost or stop')
        require(actual_candidate['expected']['before_planning_validation_value']==exact['value'],
                'Anytime closed-loop actions lose exact planning value')
        require(exact_policy['expected']['before_planning_validation_value']==exact['value'],
                'Exact policy trajectory check failed')
        cases.append({'deadline':deadline,'best_no_calibration':max(c.terminal(c.root).values()),
            'perfect_law_headroom':c.upper(c.root)-max(c.terminal(c.root).values()) if deadline>=2 else F(0),
            'unconstrained_perfect_law_ceiling':c.deployments*sum((w*max(F(1,2),p-c.deployment_fee,1-p-c.deployment_fee)
                for w,p in zip(c.prior,c.world_accuracy)),F(0)),
            'same_information_full_dp_value':exact['value'],'exact_states':len(exact['values']),
            'independent_history_calls':independent['history_calls'],'root_action':a['action'],
            'initial_expansion_trace':a['trace'],'initial_candidate_work':root_candidate.work,
            'initial_classical_work':root_classic.work,'candidate':actual_candidate,
            'classical':actual_classic,'full_dp':exact_policy})
    # Exhaust every ancestor-admissible subset of expandable states in the
    # maximum four-unit graph, including states a particular heuristic never visits.
    c=Contract();exact=full_dp(c)
    expandable=sorted((s for s in exact['values'] if c.information_actions(s)),
                      key=lambda s:(-s.remaining,key(s)))
    shared_frontiers=0;admissible=0
    for bits in product((False,True),repeat=len(expandable)):
        selected=[s for s,b in zip(expandable,bits) if b]
        view=Partial(c);valid=True
        for s in selected:
            if s not in view.data:valid=False;break
            view.expand(s)
        if not valid:continue
        admissible+=1
        ca,cl=deepcopy(view),deepcopy(view)
        influence=reverse_influence(ca,c.root);occupancy=classical_occupancy(cl,c.root)
        require(influence==occupancy,'Reverse influence != classical shared-DAG occupancy')
        pc=priorities(ca,c.root,'candidate');pl=priorities(cl,c.root,'classical')
        require(pc==pl,'Different cost-normalized priorities')
        require(ca.work==cl.work,'Different modeled work for equivalent O(E) rules')
        for s,bounds in view.data.items():
            require(bounds['L']<=exact['values'][s]<=bounds['U'],'Invalid partial-DAG interval')
        action=view.certificate(c.root)
        if action is not None:require(exact['q'][c.root][action]==exact['value'],'Spurious root certificate')
        # Count real shared descendants in the selected optimistic graph.
        incoming={};todo=[c.root];seen=set()
        while todo:
            s=todo.pop()
            if s in seen:continue
            seen.add(s);r=view.data[s]
            edges=r['edges'].get(view.optimistic_action(s),()) if r['expanded'] else ()
            for _,child in edges:incoming[child]=incoming.get(child,0)+1;todo.append(child)
        shared=any(n>1 for n in incoming.values());shared_frontiers+=shared
        cache_records.append({'expanded':[key(s) for s in selected],
            'frontier_influence':{key(s):w for s,w in influence.items()},
            'priorities':{key(s):v for s,v in pc.items()},'certificate':action,
            'selected_graph_has_shared_descendant':shared})
    # The economic contract's selected optimistic subgraphs did not merge in
    # this grid. Retain that fact and add a separate structural diamond fixture
    # instead of tuning economic parameters to manufacture a desired witness.
    r=State(3);left=State(2,1,0,True);right=State(2,1,1,True);leaf=State(1,2,1,True)
    graph={r:((F(2,5),left),(F(3,5),right)),left:((F(1),leaf),),right:((F(1),leaf),),leaf:()}
    diamond=SimpleNamespace(data={s:{'expanded':bool(edges),'edges':{'branch':edges},
        'L':F(1,2),'U':F(5,2)} for s,edges in graph.items()},work=0,
        optimistic_action=lambda s:'branch',c=SimpleNamespace(quote=lambda s:1))
    di,do=deepcopy(diamond),deepcopy(diamond)
    ia=reverse_influence(di,r);ob=classical_occupancy(do,r)
    require(ia==ob=={leaf:F(1)},'Shared diamond probability contributions did not combine')
    require(priorities(di,r,'candidate')==priorities(do,r,'classical')=={leaf:F(2)},
            'Shared diamond priority differs')
    require(di.work==do.work,'Shared-DAG O(E) work differs')
    c1=Contract(deadline=1)
    correct=full_dp(c1)['value']
    wrong_free_preparation_time=full_dp(c1,State(1,ready=True))['value']-c1.cost('prepare')
    require(correct==max(c1.terminal(c1.root).values()),'One-unit cold calibration should not help')
    require(wrong_free_preparation_time>correct,'Preparation-time counterexample not separated')
    c=Contract()
    weak=c.terminal(c.root)['follow'];strong=max(c.terminal(c.root).values())
    require(strong>weak,'Weak no-acquisition baseline did not inflate headroom')
    return {'schema':'ndu.root-influence-candidate.structural-rejection.v1',
        'status':'REJECTED_AS_CLASSICAL_SCHEDULER_EQUIVALENT','random_draws':0,'new_model_calls':0,
        'objective':'Expected fixed external four-task score minus all declared deployment/calibration fees, actual model-clock charge, measured-contract computation and validation charges; eta absent.',
        'deadline_cases':list(range(5)),'fixed_deployment_batch':4,'checks':checks,
        'expandable_state_count':len(expandable),'candidate_subsets_considered':2**len(expandable),
        'admissible_partial_caches':admissible,'caches_with_shared_selected_descendants':shared_frontiers,
        'separate_shared_diamond_fixture':{'incoming_probabilities':['2/5','3/5'],
            'shared_frontier_influence':F(1),'shared_frontier_priority':F(2),'same_OE_work':True},
        'cache_records':cache_records,'cases':cases,
        'counterexamples':{'free_preparation_clock':{'valid_value':correct,'invalid_free_prep_clock_value':wrong_free_preparation_time},
            'weak_baseline_headroom':{'best_no_calibration':strong,'fixed_follow_value':weak,
                'actual_perfect_law_headroom':F(4,5),'inflated_headroom_against_follow':F(6,5)}},
        'conclusion':'Positive task headroom does not create a new scheduling rule. Selected Bellman adjoints equal classical DAG occupancy; priorities, early certificates, warm starts, calibration decisions and declared costs are identical. No random or LLM confirmation is warranted for this candidate.',
        'economic_scope':'All fees and compute/time counters are declared synthetic units. Actual physical hardware/provider/engineering money is not established. No positive lifecycle or speed-superiority claim.',
        'wall_seconds_for_entire_enumeration_and_validation_before_serialization':time.perf_counter()-began,
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Refuse to overwrite evidence')
    result=run();args.output.write_text(json.dumps(result,default=encode,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':result['status'],'checks':result['checks'],
        'partial_caches':result['admissible_partial_caches'],'shared':result['caches_with_shared_selected_descendants'],
        'cases':[{'T':x['deadline'],'V':x['same_information_full_dp_value'],'action':x['root_action'],
                  'candidate_net':x['candidate']['expected']['net_value'],
                  'classical_net':x['classical']['expected']['net_value'],
                  'full_dp_net':x['full_dp']['expected']['net_value']}
                 for x in result['cases']],'counterexamples':result['counterexamples']},default=encode,indent=2))
