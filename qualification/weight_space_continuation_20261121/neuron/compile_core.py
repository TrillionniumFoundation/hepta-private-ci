"""Bounded own-law policy compilation; no evaluator-law input or fitting."""
import gzip
import json
import os
from pathlib import Path
import sys
import time

BASE = Path(os.environ.get('HEPTA_WSP_INPUT_ROOT', '/workspace/scratch/4b91365ace88')).resolve()
OLD = BASE / 'neuron_margin_experiment'
FT = BASE / 'neuron_full_mlp_experiment'
CAUSAL = BASE / 'neuron_causal_rescue_20261120'
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CAUSAL / 'v2'))
import causal_core as c
from causal_core import planning, mlp, read, save, sha, canonical, identity
from artifact_io import EventChain, verify_manifest
import numpy as np

ARMS = ('C', 'D', 'T', 'K', 'J_COMPILED')
TERMINAL = (0, 4, 5)
CAPSULE_SCHEMA = 'hepta-own-law-policy-capsule-v1'


def completion_record(due, index):
    if due is None:
        if index != 0: raise ValueError('only one no-completion branch')
        return dict(kind='none', observation_tick=None, observation=None)
    if index == 0:
        return dict(kind='failure', observation_tick=due, observation=None)
    if index in (1, 2):
        return dict(kind='observation', observation_tick=due, observation=index-1)
    raise ValueError('bounded completion branch')


def completion_source(record):
    if record['kind'] == 'none':
        if record != dict(kind='none', observation_tick=None, observation=None):
            raise ValueError('ambiguous no-completion')
        return None
    if record['kind'] == 'failure':
        if record['observation'] is not None: raise ValueError('failure observation')
        return dict(failure=True, observation_tick=record['observation_tick'])
    if record['kind'] == 'observation' and record['observation'] in (0, 1):
        return dict(observation_tick=record['observation_tick'], observation=record['observation'])
    raise ValueError('unknown completion')


def compile_policy(full, public, base, source, protocol, budget):
    """No truth object can enter this interface; sources and law are immutable."""
    started, wall = time.process_time(), time.perf_counter()
    model = full.NumpyPolicy(base)
    own = full.Oracle(public, planning.OwnTableLaw(model, full), model.confusion)
    graph = c.enumerate_graph(full, public, own, protocol['state_cap'], budget)
    compute_cpu = time.process_time()-started
    actions = np.where(graph['masks'], graph['qstar'], -np.inf).argmax(1)
    edges = []
    for i, state in enumerate(graph['states']):
        row = [[] for _ in range(6)]
        for action in (1, 2, 3):
            if not graph['masks'][i, action]: continue
            due = full.due_request(public, state, action)
            source_edges = graph['edges'][i][action-1]
            if len(source_edges) != (1 if due is None else 3):
                raise ArithmeticError('unexpected completion branching')
            for j, (probability, target, fee) in enumerate(source_edges):
                completion = completion_record(due, j)
                after = full.successor(public, state, action, completion_source(completion))
                if canonical(after) != graph['keys'][target]:
                    raise ArithmeticError('full-state edge identity')
                row[action].append(dict(probability=probability, target=target,
                                        fee=fee, completion=completion))
        edges.append(row)
    reached, pending = set(), [graph['initial']]
    while pending:
        i = pending.pop()
        if i in reached: continue
        reached.add(i)
        pending.extend(edge['target'] for edge in edges[i][int(actions[i])])
    reachable = sorted(reached)
    compressed = source.read_bytes()
    decoded = gzip.decompress(compressed)
    public_key = canonical(public)
    bindings = dict(compressed_sha256=sha(compressed), decoded_sha256=sha(decoded),
        task_code_sha256=identity(OLD/'vendor/frozen_joint/joint_task.py')['sha256'],
        planning_code_sha256=identity(OLD/'vendor/planning.py')['sha256'],
        compiler_code_sha256=identity(Path(__file__))['sha256'],
        public_sha256=sha(public_key.encode()))
    capsule = dict(schema=CAPSULE_SCHEMA, bindings=bindings, public=public,
        public_key=public_key, initial=graph['initial'], states=graph['states'],
        state_keys=graph['keys'], legal_masks=graph['masks'].tolist(),
        posterior=graph['posterior'].tolist(), edges=edges,
        q_values=graph['qstar'].tolist(), actions=actions.tolist(),
        order=graph['order'], policy_reachable=reachable)
    dense_bytes = canonical(capsule).encode()
    sparse = dict(schema='hepta-policy-automaton-v1',
        capsule_sha256=sha(dense_bytes), bindings=bindings, public_key=public_key,
        initial=graph['initial'], nodes=[])
    for i in reachable:
        action = int(actions[i]); state = graph['states'][i]
        terminal_after = canonical(full.successor(public, state, action)) if action in TERMINAL else None
        sparse['nodes'].append(dict(index=i, state_key=graph['keys'][i], action=action,
            edges=edges[i][action], terminal_after_key=terminal_after))
    sparse_bytes = canonical(sparse).encode()
    load_start = time.process_time(); loaded_dense = json.loads(dense_bytes)
    dense_load = time.process_time()-load_start
    load_start = time.process_time(); loaded_sparse = json.loads(sparse_bytes)
    sparse_load = time.process_time()-load_start
    if loaded_dense != capsule or loaded_sparse != sparse:
        raise ArithmeticError('compiler serialization changed data')
    checks = verify_automaton(full, loaded_dense, loaded_sparse)
    cost = dict(own_graph_compute_CPU_seconds=compute_cpu,
        full_cold_compile_CPU_seconds=time.process_time()-started,
        full_cold_compile_wall_seconds=time.perf_counter()-wall,
        dense_load_CPU_seconds=dense_load, sparse_load_CPU_seconds=sparse_load,
        dense_canonical_bytes=len(dense_bytes), sparse_canonical_bytes=len(sparse_bytes),
        full_states=len(graph['states']), policy_states=len(reachable),
        full_edges=sum(len(e) for row in edges for e in row),
        policy_edges=sum(len(node['edges']) for node in sparse['nodes']),
        sparse_to_dense_byte_ratio=len(sparse_bytes)/len(dense_bytes),
        timing_scope='same-process measured reference costs; no future latency bound',
        upfront_cost_not_amortized=True, identical_schedule_reuse_count=0)
    return capsule, sparse, graph, cost, checks


def verify_automaton(full, capsule, sparse):
    public = capsule['public']
    nodes = {node['index']: node for node in sparse['nodes']}
    if len(nodes) != len(sparse['nodes']) or capsule['initial'] not in nodes:
        raise ValueError('missing or repeated automaton node')
    edges_checked, terminals_checked = 0, 0
    for i, node in nodes.items():
        state = json.loads(node['state_key']); action = node['action']
        if state != capsule['states'][i] or node['state_key'] != capsule['state_keys'][i]:
            raise ArithmeticError('complete state changed')
        if action != capsule['actions'][i] or not full.legal(public, state)[action]:
            raise ArithmeticError('compiled action/legality changed')
        if node['edges'] != capsule['edges'][i][action]:
            raise ArithmeticError('selected action edges changed')
        if action in TERMINAL:
            if node['edges'] or canonical(full.successor(public, state, action)) != node['terminal_after_key']:
                raise ArithmeticError('terminal transition mismatch')
            terminals_checked += 1
        else:
            if node['terminal_after_key'] is not None: raise ArithmeticError('premature terminal')
            for edge in node['edges']:
                target = edge['target']
                if target not in nodes: raise ArithmeticError('policy automaton not closed')
                after = full.successor(public, state, action, completion_source(edge['completion']))
                if canonical(after) != nodes[target]['state_key']:
                    raise ArithmeticError('observation update changed complete owner state')
                if edge['fee'] != after['charges']-state['charges']:
                    raise ArithmeticError('fee changed')
                edges_checked += 1
    return dict(all_policy_states_checked=len(nodes), all_policy_edges_checked=edges_checked,
                terminal_updates_checked=terminals_checked, closed_all_outcomes=True,
                complete_state_and_terminal_exact=True)


def evaluate_compiled(world, capsule, sparse, graph):
    if graph['keys'] != world['graph']['keys']:
        raise ArithmeticError('own/evaluator complete reachable state order differs')
    report = c.measure(world, graph['qstar'], graph['posterior'])
    sparse_actions = np.zeros(len(graph['states']), dtype=np.int64)
    for node in sparse['nodes']: sparse_actions[node['index']] = node['action']
    values = c.backward_values(world['graph']['order'], sparse_actions,
        world['graph']['terminal'], world['graph']['edges'])
    occupancy, terminal_mass = c.forward_occupancy(world['graph']['order'],
        world['graph']['initial'], sparse_actions, world['graph']['edges'])
    if float(values[graph['initial']]) != report['utility']:
        raise ArithmeticError('pruned automaton expected utility changed')
    outside = np.ones(len(sparse_actions), dtype=bool)
    outside[capsule['policy_reachable']] = False
    if np.any(occupancy[outside] != 0): raise ArithmeticError('missing reachable policy state')
    report['sparse_exact_value'] = True
    report['expected_decisions'] = float(occupancy.sum())
    report['expected_continuations'] = float(occupancy[np.isin(sparse_actions, (1,2,3))].sum())
    report['terminal_probability'] = float(terminal_mass)
    return report
