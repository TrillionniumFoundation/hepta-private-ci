"""Finite checkpoint-own-law decomposition on frozen new public distributions.

This is a new exploratory study. It does not reopen the digital-feedback gates,
train any weights, use evaluator truth in policy inputs, or deploy a model.
"""
import argparse
import copy
import datetime
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import signal
import sys
import time

import numpy as np
from scipy.stats import t as student_t
import planning as p

ARMS = ('C', 'P', 'Q', 'J', 'M')


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False)


def save(path, x):
    b = (json.dumps(x, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if path.suffix == '.gz':
        b = gzip.compress(b, mtime=0)
    with path.open('xb') as f:
        f.write(b)
        f.flush()
        os.fsync(f.fileno())
    return hashlib.sha256(b).hexdigest()


def read(path):
    b = path.read_bytes()
    return json.loads(gzip.decompress(b) if path.suffix == '.gz' else b)


class Scores:
    def __init__(self, ctx, public, model, arm, table):
        self.ctx, self.public, self.model, self.arm = ctx, public, model, arm
        self.head = ctx.head(model.artifact)
        self.world = p.WorldPolicy(ctx, public, model, table if arm in ('Q', 'J') else None)
        self.table = table
        self.own = ctx.Oracle(public, p.OwnTableLaw(model, ctx), model.confusion) if arm == 'M' else None

    def __call__(self, state):
        if self.arm == 'J':
            return self.world.scores(state, self.head, 'J')
        if self.arm == 'M':
            belief = self.own.posterior(state)
            q = np.array([0., 0., 0., 0., 1 - 2 * belief, 2 * belief - 1])
            mask = self.ctx.legal(self.public, state)
            for action in (1, 2, 3):
                if mask[action]:
                    v = 0.
                    for probability, completion in self.ctx.outcomes(self.public, state, action, self.own):
                        after = self.ctx.successor(self.public, state, action, completion)
                        probability_after = self.own.posterior(after)
                        v += probability * (abs(2 * probability_after - 1) - after['charges'] + state['charges'])
                    q[action] = v
            return q, belief
        q, belief = self.world.scores(state, self.head, 'P' if self.arm == 'P' else 'head')
        if self.arm == 'Q':
            q = q.copy()
            q[1:4] = self.table['rows'][p.markov_key(state)]['q'][1:4]
        return q, belief


def exact_expected(ctx, public, model, arm, table, truth):
    """Truth is evaluator-only. Policy is given the checkpoint and public history."""
    scores = Scores(ctx, public, model, arm, table)
    visits, trace = 0, hashlib.sha256()
    def value(state, reach):
        nonlocal visits
        q, belief = scores(state)
        action = int(np.where(ctx.legal(public, state), q, -np.inf).argmax())
        visits += 1
        trace.update(canonical([state, action, float(belief), q.tolist(), reach]).encode())
        if action in (0, 4, 5):
            target = truth.posterior(state)
            return 0. if action == 0 else (1 - 2 * target if action == 4 else 2 * target - 1)
        total = 0.
        for probability, completion in ctx.outcomes(public, state, action, truth):
            if probability > 0:
                after = ctx.successor(public, state, action, completion)
                total += probability * (value(after, reach * probability) - after['charges'] + state['charges'])
        return total
    return dict(utility=float(value(ctx.initial(public), 1.)), nodes=visits, trace_sha256=trace.hexdigest())


def episode_cost(ctx, public_bytes, model_bytes, arm, table_bytes, uniform, truth):
    """One simulated trajectory; policy+JSON/transition timers exclude truth lookup.

    Cold table compilation is charged separately. This is a resident-interpreter
    benchmark of finite synthetic execution, not Owner/media/physical I/O.
    """
    start, wall = time.process_time(), time.perf_counter()
    public = json.loads(public_bytes)
    model = ctx.NumpyPolicy(json.loads(model_bytes))
    table = json.loads(table_bytes) if arm in ('Q', 'J') else None
    scores = Scores(ctx, public, model, arm, table)
    state = ctx.initial(public)
    cpu, elapsed = time.process_time() - start, time.perf_counter() - wall
    decisions = []
    for index in range(7):
        start, wall = time.process_time(), time.perf_counter()
        q, belief = scores(state)
        action = int(np.where(ctx.legal(public, state), q, -np.inf).argmax())
        # Include bounded JSON request/decision serialization in the policy cost.
        payload = canonical(dict(state=state, action=action, belief=float(belief)))
        json.loads(payload)
        cpu += time.process_time() - start
        elapsed += time.perf_counter() - wall
        decisions.append(action)
        if action in (0, 4, 5):
            start, wall = time.process_time(), time.perf_counter()
            state = ctx.successor(public, state, action)
            cpu += time.process_time() - start
            elapsed += time.perf_counter() - wall
            break
        # Environmental outcome computation deliberately outside policy timers.
        options = ctx.outcomes(public, state, action, truth)
        at = min(int(np.searchsorted(np.cumsum([x[0] for x in options]), uniform[index], side='right')), len(options) - 1)
        completion = options[at][1]
        start, wall = time.process_time(), time.perf_counter()
        state = ctx.successor(public, state, action, completion)
        cpu += time.process_time() - start
        elapsed += time.perf_counter() - wall
    if not state['terminal']:
        raise AssertionError('six-tick episode failed to terminate')
    return dict(policy_cpu_seconds=cpu, policy_wall_seconds=elapsed, actions=decisions,
                state_sha256=p.sha(canonical(state).encode()))


def main(args):
    started, wall = time.process_time(), time.perf_counter()
    args.output.mkdir(exist_ok=False)
    protocol = read(args.protocol)
    protocol_sha = p.sha(args.protocol.read_bytes())
    source_hashes = {x.name: p.sha(x.read_bytes()) for x in Path(__file__).parent.glob('*.py')}
    def timeout(*unused):
        raise TimeoutError('registered whole-run CPU or wall budget reached')
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(protocol['resource_caps']['wall_seconds'])
    cap = protocol['resource_caps']['cpu_seconds']
    resource.setrlimit(resource.RLIMIT_CPU, (cap, cap + 5))
    save(args.output / 'STARTED.json', dict(protocol_sha256=protocol_sha, source_hashes=source_hashes,
         utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), python=sys.version,
         numpy=np.__version__, platform=platform.platform()))
    try:
        ctx = p.load_context(args.inputs / 'frozen_joint')
        for name, expected in protocol['input_files'].items():
            if p.sha((args.inputs / name).read_bytes()) != expected:
                raise ValueError('input changed: ' + name)
        models = {}
        old = {x['fit']: x for x in read(args.inputs / 'history/OLD_CONTINUATION_HEADS.json.gz')['fits']}
        for fit in protocol['fits']:
            artifact = read(args.inputs / f'inputs/fit_{fit}/model_renewal/model.json')
            artifact['network']['w2'] = old[fit]['network_w2']
            artifact['network']['b2'] = old[fit]['network_b2']
            models[fit] = artifact
        fields = read(args.inputs / 'history/HISTORY_REGISTRY.json.gz')['canonical_schedule_fields']
        def schedule_sha(public):
            return p.sha(canonical({k: public[k] for k in fields}).encode())
        known = set(x['schedule_sha256'] for x in read(args.inputs / 'history/HISTORY_REGISTRY.json.gz')['entries'])
        for path in (args.inputs / 'history').glob('fit_*_*_WORLDS.json.gz'):
            known.update(schedule_sha(x) for x in read(path))
        for path in (args.inputs / 'exposed_followup_worlds').glob('*.json.gz'):
            known.update(schedule_sha(x) for x in read(path)['worlds'])
        worlds = {}
        for fit in protocol['fits']:
            for domain, domain_law in protocol['domains'].items():
                seed = int(p.sha(canonical([protocol_sha, fit, domain]).encode()), 16)
                rng = np.random.Generator(np.random.PCG64(seed))
                group = []
                for i in range(protocol['worlds_per_fit_domain']):
                    public = dict(schema=ctx.ns['SCHEMA'], id=f'shift_ablation_{fit}_{domain}_{i}', deadline=6,
                         initial_budget=3, target_tick=6, prior_distance=float(rng.choice(ctx.protocol['prior_distances'])),
                         duration=rng.choice(domain_law['durations'], 6).tolist(), drive=rng.choice((-1, 0, 1), 6).tolist(),
                         reliability=rng.choice(domain_law['reliabilities'], 6).tolist(), read_price=rng.choice(domain_law['prices'], 6).tolist(),
                         read_delay=rng.choice(domain_law['delays'], 6).tolist(), latency_price=domain_law['latency_price'],
                         repair_price=domain_law['repair_price'], failure_probability=domain_law['failure_probability'],
                         packets=[f'not_read_{j}.json' for j in range(6)], packet_sha256=['0' * 64] * 6)
                    ctx.ns['validate_public'](public)
                    key = schedule_sha(public)
                    if key in known:
                        raise ValueError('duplicate world: do not resample')
                    known.add(key)
                    group.append(dict(public=public, schedule_sha256=key,
                                      uniforms=rng.random((protocol['episodes_per_world'], 7)).tolist(),
                                      order=[ARMS[int(x)] for x in rng.permutation(len(ARMS))]))
                worlds[f'{fit}_{domain}'] = group
        save(args.output / 'WORLDS_BEFORE_SCORING.json.gz', worlds)
        save(args.output / 'MODELS_BEFORE_SCORING.json', {str(k): p.sha(canonical(v).encode()) for k, v in models.items()})
        results = []
        for fit in protocol['fits']:
            for domain in protocol['domains']:
                rows = []
                for spec in worlds[f'{fit}_{domain}']:
                    public = spec['public']
                    model = ctx.NumpyPolicy(models[fit])
                    table, compile_record, _ = p.compile_own(ctx, model, public, 3000)
                    serialize_start, serialize_wall = time.process_time(), time.perf_counter()
                    table_bytes = canonical(table)
                    table_serialization = dict(cpu_seconds=time.process_time() - serialize_start,
                                               wall_seconds=time.perf_counter() - serialize_wall, bytes=len(table_bytes.encode()))
                    truth = ctx.Oracle(public, ctx.law, model.confusion)
                    row = dict(fit=fit, domain=domain, world_id=public['id'], schedule_sha256=spec['schedule_sha256'],
                               cold_compile=compile_record, table_serialization=table_serialization, arms={})
                    public_bytes, model_bytes = canonical(public), canonical(models[fit])
                    for arm in spec['order']:
                        result = exact_expected(ctx, public, model, arm, table if arm in ('Q', 'J') else None, truth)
                        result['episodes'] = [episode_cost(ctx, public_bytes, model_bytes, arm, table_bytes, u, truth) for u in spec['uniforms']]
                        result['mean_resident_execution_cpu_seconds'] = float(np.mean([x['policy_cpu_seconds'] for x in result['episodes']]))
                        result['mean_resident_execution_wall_seconds'] = float(np.mean([x['policy_wall_seconds'] for x in result['episodes']]))
                        compile_cpu = compile_record['full_cold_preparation_cpu_seconds'] + table_serialization['cpu_seconds'] if arm in ('Q', 'J') else 0.
                        result['cold_total_cpu_seconds'] = compile_cpu + result['mean_resident_execution_cpu_seconds']
                        result['amortized_total_cpu_seconds'] = {str(n): compile_cpu / n + result['mean_resident_execution_cpu_seconds'] for n in protocol['reuse_counts']}
                        row['arms'][arm] = result
                    rows.append(row)
                save(args.output / f'fit_{fit}_{domain}.json.gz', rows)
                results.extend(rows)
                print(canonical(dict(fit=fit, domain=domain, worlds=len(rows), cpu_seconds=time.process_time() - started)), flush=True)
        summary = summarize(results, protocol)
        summary.update(protocol_sha256=protocol_sha, source_hashes=source_hashes,
             cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
             peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
             full_economic_value_qualified=False, production_qualified=False, pure_weight_edit_gain_qualified=False,
             scientific_scope='five reused fits; finite synthetic new schedules; new distribution definitions frozen without validation; no new fits, raw media or physical packets',
             digital_feedback_original_gates_unchanged=True)
        if source_hashes != {x.name: p.sha(x.read_bytes()) for x in Path(__file__).parent.glob('*.py')}:
            raise AssertionError('source changed during run')
        save(args.output / 'RESULTS.json', summary)
        print(canonical(summary), flush=True)
    except BaseException as e:
        import traceback
        save(args.output / 'FAILED.json', dict(type=type(e).__name__, error=str(e), traceback=traceback.format_exc(),
             cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall))
        raise


def summarize(rows, protocol):
    out = {}
    # Three registered contrasts over three new domains form one nine-test family.
    critical = float(student_t.ppf(1 - .05 / (2 * 9), 4))
    for domain in protocol['domains']:
        group = [x for x in rows if x['domain'] == domain]
        by_fit = {f: {a: float(np.mean([x['arms'][a]['utility'] for x in group if x['fit'] == f])) for a in ARMS} for f in protocol['fits']}
        summary = dict(per_fit=by_fit, mean_utility={a: float(np.mean([x['arms'][a]['utility'] for x in group])) for a in ARMS}, contrasts={})
        for baseline in ('C', 'P', 'Q'):
            delta = np.array([by_fit[f]['J'] - by_fit[f][baseline] for f in protocol['fits']])
            half = critical * delta.std(ddof=1) / math.sqrt(5)
            summary['contrasts']['J_minus_' + baseline] = dict(mean=float(delta.mean()), per_fit=delta.tolist(),
                familywise_95_interval=[float(delta.mean() - half), float(delta.mean() + half)],
                lower_exceeds_original_point005=bool(delta.mean() - half > .005))
        summary['interaction_per_fit'] = {f: by_fit[f]['J'] - by_fit[f]['P'] - by_fit[f]['Q'] + by_fit[f]['C'] for f in protocol['fits']}
        summary['mean_costs'] = {a: {k: float(np.mean([x['arms'][a][k] for x in group])) for k in ('cold_total_cpu_seconds', 'mean_resident_execution_cpu_seconds')} for a in ARMS}
        # Prices are declared sensitivity scenarios in task-utility / CPU second.
        summary['cpu_price_sensitivity'] = {}
        for reuse in protocol['reuse_counts']:
            price_rows = []
            for price in protocol['utility_per_cpu_second']:
                v = {a: float(np.mean([x['arms'][a]['utility'] - price * x['arms'][a]['amortized_total_cpu_seconds'][str(reuse)] for x in group])) for a in ARMS}
                price_rows.append(dict(price=price, means=v, J_minus_C=v['J'] - v['C']))
            summary['cpu_price_sensitivity'][str(reuse)] = price_rows
        out[domain] = summary
    return dict(domains=out, nine_contrasts_familywise_alpha=.05,
                timing_scope='model/public/table JSON parse, own policy setup, policy scoring, bounded wire serialization, successor; truth lookup excluded; cold exhaustive compile and table serialization charged once per declared reuse count',
                missing_economic_components=['prior training amortization', 'energy', 'external I/O', 'production service overhead', 'currency valuation'],
                no_adaptive_selection=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for n in ('inputs', 'protocol', 'output'):
        parser.add_argument('--' + n, type=Path, required=True)
    args = parser.parse_args()
    with np.errstate(over='raise', invalid='raise', divide='raise'):
        main(args)
