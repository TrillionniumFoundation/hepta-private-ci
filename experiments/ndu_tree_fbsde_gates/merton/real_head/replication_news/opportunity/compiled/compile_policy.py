"""Immutable, scope-bound compilation of an existing finite research controller.

Compilation is exact policy reuse, not learned distillation or general FBSDE.
Byte admission is not independent authentication or a proof of model validity.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from types import MappingProxyType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
from belief import BATCHES, MODES, STEPS, Planner, check_history
from material_news import encode, loads, sha, write
from study import PROTOCOL_SHA as PARENT_PROTOCOL, config as parent_config, source_hashes as parent_hashes

SCHEMA = 'hepta.merton.compiled-policy.v1'
FILES = ('compile_policy.py', 'benchmark.py', 'audit_compiled.py', 'test_compiled.py', 'README.md', 'protocol.json')
RECORD_KEYS = {'action', 'selected_steps', 'stop_value', 'continue_value', 'value', 'to_step',
               'alpha', 'posterior', 'reason', 'pruned', 'continue_value_upper_bound'}
MODES = tuple(MODES)


def sources():
    return {name: sha((HERE/name).read_bytes()) for name in FILES} | {
        '../'+name: value for name, value in parent_hashes().items()}


def key(history):
    check_history(tuple(history))
    return ','.join(str(k) for k in history)


def binding(worker_sha, prior_sha):
    for value in (worker_sha, prior_sha):
        if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('exact lowercase SHA256 binding required')
    return {'worker_sha256': worker_sha, 'prior_sha256': prior_sha,
            'parent_protocol_sha256': PARENT_PROTOCOL, 'head_shape': [385, 4],
            'transfer_scope': 'same_frozen_research_packet_only',
            'production_authority': False}


def compact(decision):
    return {k: decision[k] for k in RECORD_KEYS}


def compile_one(curves, scenario, mode):
    planner = Planner(curves, scenario, mode)
    rows = {}
    pending = [()]
    while pending:
        history = pending.pop()
        d = compact(planner.decision(history))
        rows[key(history)] = d
        if d['action'] == 'continue':
            pending.extend(history+(k,) for k in reversed(range(BATCHES[len(history)]+1)))
    return rows, planner.solve.cache_info().currsize


def build(prior_path, worker_sha, output):
    c, w = time.process_time_ns(), time.perf_counter_ns()
    prior_raw = prior_path.read_bytes()
    prior = loads(prior_raw)
    if (prior['source_sha256'] != parent_hashes() or prior['protocol_sha256'] != PARENT_PROTOCOL
            or prior['posture'] != 'RESEARCH_ONLY_DENY_ALL' or prior['calibration_or_holdout_used'] is not False
            or prior['actual_updates'] != 512 or prior['validation_calls'] != 16
            or prior['curves'] != [r['counts'] for r in prior['rows']]):
        raise ValueError('prior source, accounting or curve mismatch')
    tables, work = {}, {}
    for scenario in parent_config()['scenarios']:
        for mode in MODES:
            name = scenario['name']+'/'+mode
            tables[name], work[name] = compile_one(prior['curves'], scenario, mode)
    payload = {'schema': SCHEMA, 'posture': 'RESEARCH_ONLY_DENY_ALL',
               'binding': binding(worker_sha, sha(prior_raw)), 'source_sha256': sources(),
               'curves': prior['curves'], 'scenarios': parent_config()['scenarios'], 'modes': list(MODES),
               'tables': tables, 'compiler_evaluated_nodes': work}
    write(output, payload)
    raw = output.read_bytes()
    return {'asset_sha256': sha(raw), 'serialized_bytes': len(raw),
            'policy_tables': len(tables), 'stored_decisions': sum(map(len, tables.values())),
            'compiler_evaluated_nodes': sum(work.values()), 'cpu_ns': time.process_time_ns()-c,
            'wall_ns': time.perf_counter_ns()-w}


def validate_graph(rows, budget):
    """Structural validation only; the separate reviewer verifies the mathematics."""
    if type(rows) is not dict or not 1 <= len(rows) <= 1468:
        raise ValueError('invalid policy graph size')
    expected, pending = set(), [()]
    while pending:
        h = pending.pop(); k = key(h); expected.add(k)
        d = rows.get(k)
        if type(d) is not dict or set(d) != RECORD_KEYS:
            raise ValueError('incomplete node or unknown fields')
        j = len(h)
        if type(d['selected_steps']) is not int or d['selected_steps'] not in STEPS[:j+1]:
            raise ValueError('unexecuted checkpoint selection')
        if type(d['pruned']) is not bool or d['action'] not in ('stop', 'continue'):
            raise ValueError('invalid action')
        for field in ('stop_value', 'value', 'continue_value', 'continue_value_upper_bound'):
            v = d[field]
            if v is None and field in ('continue_value', 'continue_value_upper_bound'):
                continue
            if type(v) not in (float, int) or not math.isfinite(v):
                raise ValueError('invalid utility')
        p = d['posterior']
        if type(p) is not list or not 1 <= len(p) <= 8 or any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in p):
            raise ValueError('invalid posterior')
        if abs(math.fsum(p)-1) > 1e-10:
            raise ValueError('unnormalized posterior')
        if d['action'] == 'continue':
            if j == 3 or type(d['to_step']) is not int or d['to_step'] != STEPS[j+1] or d['to_step'] > budget:
                raise ValueError('invalid or unaffordable transition')
            if d['pruned'] or d['continue_value'] is None:
                raise ValueError('pruned branch cannot execute')
            pending.extend(h+(v,) for v in range(BATCHES[j]+1))
        elif d['to_step'] is not None:
            raise ValueError('stop cannot train')
    if expected != set(rows):
        raise ValueError('missing reachable node or surplus unreachable node')


class SharedPolicy:
    """Single immutable asset; every bound reader references the SAME table bytes.

    No Planner construction, posterior update or tree solve occurs after loading.
    Requests outside the frozen binding are rejected, never silently repriced.
    """
    def __init__(self, path, expected_sha, worker_sha, prior_sha):
        if path.stat().st_size > 8_000_000:
            raise ValueError('oversized compiled asset')
        raw = path.read_bytes()
        if sha(raw) != expected_sha:
            raise ValueError('compiled asset digest mismatch')
        data = loads(raw)
        required = {'schema', 'posture', 'binding', 'source_sha256', 'curves', 'scenarios', 'modes', 'tables', 'compiler_evaluated_nodes'}
        if set(data) != required or data['schema'] != SCHEMA or data['posture'] != 'RESEARCH_ONLY_DENY_ALL':
            raise ValueError('unsupported schema or authority')
        if data['binding'] != binding(worker_sha, prior_sha) or data['source_sha256'] != sources():
            raise ValueError('source or request binding drift')
        if data['scenarios'] != parent_config()['scenarios'] or data['modes'] != list(MODES):
            raise ValueError('tariff, budget, mode or horizon drift')
        scenarios = {s['name']: s for s in data['scenarios']}
        if set(data['tables']) != {s+'/'+m for s in scenarios for m in MODES}:
            raise ValueError('missing or unknown policy table')
        tables = {}
        for name, rows in data['tables'].items():
            validate_graph(rows, scenarios[name.split('/')[0]]['budget'])
            tables[name] = MappingProxyType({k: MappingProxyType({f: tuple(v) if f == 'posterior' else v
                                       for f, v in d.items()}) for k, d in rows.items()})
        self.tables = MappingProxyType(tables)
        self.scenarios = MappingProxyType({k: MappingProxyType(s) for k, s in scenarios.items()})
        self.scope_digest = sha(encode(data['binding']))
        self.asset_sha256 = expected_sha
        self.serialized_bytes = len(raw)

    def bind(self, scope_digest, scenario, mode):
        if scope_digest != self.scope_digest or mode not in MODES:
            raise ValueError('stale scope or unknown mode')
        name = scenario['name']+'/'+mode
        if dict(self.scenarios.get(scenario['name'], {})) != scenario or name not in self.tables:
            raise ValueError('unregistered scenario')
        return BoundPolicy(self, name)


class BoundPolicy:
    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    def decision(self, history, actual_updates):
        h = tuple(history); check_history(h)
        if type(actual_updates) is not int or actual_updates != STEPS[len(h)]:
            raise ValueError('state/optimizer checkpoint mismatch')
        try:
            record = self.owner.tables[self.name][key(h)]
        except KeyError as e:
            raise ValueError('history is outside admitted policy graph') from e
        return {k: list(v) if k == 'posterior' else v for k, v in record.items()}


def incremental_break_even(setup_cost, baseline_per_use, shared_per_use):
    """Descriptive extrapolation of measured rates, NOT an observed future count."""
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (setup_cost, baseline_per_use, shared_per_use)):
        raise ValueError('nonnegative finite costs required')
    saving = baseline_per_use-shared_per_use
    return None if saving <= 0 else math.floor(setup_cost/saving)+1


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prior', type=Path, required=True); p.add_argument('--worker-sha', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); print(encode(build(a.prior, a.worker_sha, a.output)).decode())
