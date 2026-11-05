"""All-state parity and cold cost of sufficient-state planning; synthetic fixtures."""
import ast
import copy
import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import resource
import time
import numpy as np
from compact_belief import CompactBeliefPlanner

ROOT = Path(__file__).parent

def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')

def load_reference():
    source = (ROOT / 'reference_task.py').read_bytes()
    tree = ast.parse(source)
    names = {'validate_public', 'initial', 'legal', 'due_request', 'successor', 'posterior', 'Oracle'}
    selected = [x for x in tree.body if getattr(x, 'name', None) in names]
    ns = dict(np=np, Path=Path, copy=copy, lru_cache=lru_cache)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / 'reference_task.py'), 'exec'), ns)
    return ns


def enumerate_states(ctx, public):
    todo, states = [ctx['initial'](public)], {}
    while todo:
        state = todo.pop()
        # Complete full state retains the costs of the actual route.
        identity = json.dumps(state, sort_keys=True)
        if identity in states:
            continue
        states[identity] = state
        if len(states) > 10000:
            raise OverflowError('full-state cap exceeded')
        for action in (1, 2, 3):
            if not ctx['legal'](public, state)[action]:
                continue
            due = ctx['due_request'](public, state, action)
            completions = [None] if due is None else [dict(failure=True), dict(observation=0), dict(observation=1)]
            todo.extend(ctx['successor'](public, state, action, c) for c in completions)
    return list(states.values())


def main():
    started, wall = time.process_time(), time.perf_counter()
    ctx = load_reference()
    rng = np.random.default_rng(202611050061)
    worlds = []
    for index in range(12):
        repeated = index < 6
        worlds.append(dict(schema='digital-read-before-public-v1', id=f'compact_prototype_{index}', deadline=6, initial_budget=3,
            duration=rng.choice([.25,.5,.75,1.5],6).tolist(), reliability=([.85]*6 if repeated else rng.choice([.55,.65,.85,.95],6).tolist()),
            read_price=rng.choice([.01,.03,.12,.18],6).tolist(), read_delay=rng.choice([1,2],6).tolist(),
            latency_price=.025 if repeated else .04, repair_price=.03 if repeated else .05, failure_probability=.08 if repeated else .16,
            packets=[f'unopened_{j}.json' for j in range(6)], packet_sha256=['0'*64]*6))
    matrices = [[[.9,.1],[.1,.9]], [[.8,.2],[.2,.8]], [[.91,.09],[.22,.78]]]
    frozen = dict(schema='digital-compact-belief-prototype-v1', utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  source_commit='77b24407b9898aa44769502fbb22c24fb7193a58',
                  sources={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in ROOT.glob('*.py')},
                  worlds=worlds, matrices=matrices, tolerance=1e-10, timing_repeats=3,
                  scope='12 synthetic public worlds times three declared decoder matrices; no fitted checkpoints, no retraining, no original efficacy closure')
    save(ROOT / 'PROTOCOL_FROZEN.json', frozen)
    results=[]
    for wi, public in enumerate(worlds):
        states=enumerate_states(ctx, public)
        for mi, confusion in enumerate(matrices):
            oracle=ctx['Oracle'](public,confusion); compact=CompactBeliefPlanner(public,confusion)
            errors=[]; regrets=[]; raw_action_differences=0
            oldkeys=set(); newkeys=set()
            for state in states:
                oldkeys.add(oracle.key(state)); key=compact.key(state);newkeys.add(key)
                q1=oracle.q(state);q2=compact.q(key);mask=np.asarray(ctx['legal'](public,state))
                if not np.array_equal(mask,np.asarray(compact.legal(key))):
                    raise AssertionError('legal support mismatch')
                errors.append(float(np.max(np.abs(q1[mask]-q2[mask]))))
                a1,a2=int(q1.argmax()),int(q2.argmax());raw_action_differences+=int(a1!=a2)
                regrets.append(float(q1[a1]-q1[a2]))
            timing=[]
            for rep in range(3):
                for name in (('reference','compact') if rep%2==0 else ('compact','reference')):
                    begin,w=time.process_time(),time.perf_counter()
                    if name=='reference':
                        run=ctx['Oracle'](public,confusion);q0=run.q(ctx['initial'](public));cache=run._value.cache_info().currsize
                    else:
                        run=CompactBeliefPlanner(public,confusion);q0=run.q(run.key(ctx['initial'](public)));cache=run.value.cache_info().currsize
                    timing.append(dict(arm=name,repetition=rep,cpu_seconds=time.process_time()-begin,wall_seconds=time.perf_counter()-w,
                                       cache_entries=cache,q_initial=q0.tolist()))
            results.append(dict(world_index=wi,matrix_index=mi,full_states=len(states),history_keys=len(oldkeys),sufficient_keys=len(newkeys),
                max_q_error=max(errors),max_reference_regret_of_compact_choice=max(regrets),raw_action_differences=raw_action_differences,
                q_pass=max(errors)<=1e-10,choice_value_pass=max(regrets)<=1e-10,timing=timing))
    outcome=dict(schema='digital-compact-belief-prototype-result-v1',records=results,
        total_full_state_checks=sum(x['full_states'] for x in results),all_q_pass=all(x['q_pass'] for x in results),
        all_choice_value_pass=all(x['choice_value_pass'] for x in results),max_q_error=max(x['max_q_error'] for x in results),
        raw_action_differences=sum(x['raw_action_differences'] for x in results),
        history_key_total=sum(x['history_keys'] for x in results),sufficient_key_total=sum(x['sufficient_keys'] for x in results),
        cold_cpu_sum={a:sum(t['cpu_seconds'] for x in results for t in x['timing'] if t['arm']==a) for a in ('reference','compact')},
        cpu_seconds=time.process_time()-started,wall_seconds=time.perf_counter()-wall,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        original_digital_feedback_acceptance=False,semantic_efficacy_qualified=False,production_qualified=False,
        scope='finite sufficient-state prototype and all-state reference parity only; cache compression is not utility gain and fewer states do not imply lower CPU')
    save(ROOT / 'RESULTS.json',outcome)
    print(json.dumps({k:v for k,v in outcome.items() if k!='records'},indent=2))
    if not outcome['all_q_pass'] or not outcome['all_choice_value_pass']:
        raise SystemExit(1)

if __name__=='__main__':main()
