"""R9 frozen 96-case factorial; all monitors, tensors and outcomes retained."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(key, '1')
import argparse
import hashlib
import itertools
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import torch
from scipy.stats import qmc
from core import ROOT, METHODS, fit, training_rule, rule, WidePolicy, make_problem, evaluate, SCALE
from engine import TARGET, TOLERANCE, CADENCE, CAP

torch.set_num_threads(1)
HERE = Path(__file__).resolve().parent
PROTOCOL_COMMIT = '7e233ce92a8e984aa68ff217fc8b1730aee7689b'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, obj):
    data = (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    with open(path, 'xb') as stream:
        stream.write(data)
    return digest(data)


def save(path, data):
    with open(path, 'xb') as stream:
        np.savez_compressed(stream, **data)


def sources():
    return {str(p.relative_to(ROOT)): digest(p.read_bytes())
            for d in (HERE, ROOT/'scaling', ROOT/'continuous', ROOT/'nonquadratic')
            for p in sorted(d.glob('*.py'))}


def specs():
    cases = []
    settings = list(itertools.product(METHODS, ('cc5', 'gl5'), ('full', 'lazy')))
    for j, width in enumerate((64, 256)):
        for i, seed in enumerate((11, 23, 47)):
            rotation = (5*i + 3*j) % len(settings)
            for method, train, monitor in settings[rotation:]+settings[:rotation]:
                cases.append(dict(width=width, seed=seed, method=method, train=train, monitor=monitor))
    return cases


def name_for(case):
    return f"w{case['width']}-{case['method']}-{case['train']}-{case['monitor']}-s{case['seed']}"


def panels():
    for name in ('cc5', 'gl5', 'cc9', 'gl9'):
        s, w = training_rule(name) if name in ('cc5', 'gl5') else rule(name)
        yield name, s, w, make_problem()
    for rep in range(4):
        s = (2*qmc.Sobol(4, scramble=True, seed=2026101491+rep).random_base2(10)-1)*SCALE
        yield f'qmc{rep}', s, np.full(len(s), 1/len(s)), make_problem()
    s = (2*qmc.Sobol(4, scramble=True, seed=2026101491).random_base2(7)-1)*SCALE
    for name, ss, change in (('scale', 2*s, 'base'), ('dynamics', s, 'dynamics'), ('horizon4', s, 'horizon')):
        yield name, ss, np.full(len(ss), 1/len(ss)), make_problem(change)


def trial(out, case):
    out.mkdir(parents=True, exist_ok=False)
    begin, cpu = time.perf_counter(), time.process_time()
    plan = dict(schema='hepta.ndu.allocation.r9', case=case, source=sources(), protocol=PROTOCOL_COMMIT,
                target=TARGET, tolerance=TOLERANCE, cadence=CADENCE, cap=CAP)
    ph = dump(out/'PLAN.json', plan)
    initial = WidePolicy(case['width'], case['seed']).initial
    save(out/'INITIAL.npz', dict(theta=initial))
    theta, checkpoints, info = fit(**case)
    save(out/'WEIGHTS.npz', dict(theta=theta))
    save(out/'CHECKPOINTS.npz', dict(theta=checkpoints))
    fh = dump(out/'FIT.json', info)
    dump(out/'FIT_SEAL.json', dict(fit=fh, weights=digest(theta.tobytes()),
                                 checkpoints=digest((out/'CHECKPOINTS.npz').read_bytes())))
    policy = WidePolicy(case['width'], case['seed'])
    eval_start = time.process_time()
    raw, costs = {}, {}
    for name, s, w, problem in panels():
        raw[name] = evaluate(policy, torch.tensor(theta), problem, s, chunk=256)
        if not np.isfinite(raw[name]).all():
            raise FloatingPointError(name)
        costs[name] = float(w@raw[name].mean(1))
    save(out/'PREDICTIONS.npz', raw)
    if sources() != plan['source']:
        raise ValueError('source drift')
    report = dict(case=case, plan_sha256=ph, source=plan['source'], parameters=len(theta), fit=info,
                  initial_sha256=digest(initial.tobytes()), weights_sha256=digest(theta.tobytes()),
                  predictions_sha256=digest((out/'PREDICTIONS.npz').read_bytes()), costs=costs,
                  changed=not np.array_equal(initial, theta), evaluation_cpu=time.process_time()-eval_start,
                  main_wall=time.perf_counter()-begin, main_cpu=time.process_time()-cpu,
                  process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  environment=dict(python=sys.version, torch=torch.__version__, numpy=np.__version__,
                                   platform=platform.platform(), threads=torch.get_num_threads()),
                  flops=None, energy_joules=None, production_authorized=False, project_cloud=False)
    dump(out/'REPORT.json', report)
    print(json.dumps(dict(name=name_for(case), success=info['success'], time=info['observed_wall'],
                         cost=costs['cc9'], skipped=info['counts']['skipped_fine'])), flush=True)


def sweep(out):
    out.mkdir(parents=True, exist_ok=False)
    laws = {}
    for name in ('cc5', 'gl5', 'cc9'):
        s, w = training_rule(name) if name != 'cc9' else rule(name)
        laws[name+'_states'], laws[name+'_weights'] = s, w
    save(out/'LAWS.npz', laws)
    ph = dump(out/'PLAN.json', dict(cases=specs(), source=sources(), protocol=PROTOCOL_COMMIT,
                                  target=TARGET, tolerance=TOLERANCE, cadence=CADENCE, cap=CAP,
                                  law_sha256=digest((out/'LAWS.npz').read_bytes())))
    start, census = time.perf_counter(), []
    for case in specs():
        name = name_for(case)
        now, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
        cmd = [sys.executable, str(Path(__file__).resolve()), 'trial', '--out', str(out/name)]
        for k, v in case.items():
            cmd += ['--'+k, str(v)]
        row = dict(name=name, case=case)
        with open(out/(name+'.log'), 'xb') as log:
            try:
                result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                row.update(returncode=result.returncode, status='completed' if result.returncode == 0 else 'failed')
            except (subprocess.TimeoutExpired, OSError) as exc:
                row.update(status='failed', returncode=None, error=str(exc))
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(child_wall=time.perf_counter()-now,
                   child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
        if row['status'] == 'completed':
            row['report_sha256'] = digest((out/name/'REPORT.json').read_bytes())
        census.append(row)
        dump(out/(name+'.completion.json'), row)
        print(json.dumps(row), flush=True)
    failures = sum(r['status'] != 'completed' for r in census)
    dump(out/'COMPLETE.json', dict(plan_sha256=ph, census=census, completed=len(census)-failures,
                                 failed=failures, wall=time.perf_counter()-start,
                                 child_cpu=sum(r['child_cpu'] for r in census)))
    if failures:
        raise SystemExit('execution failures retained')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['trial', 'sweep'])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--width', type=int, default=64)
    p.add_argument('--seed', type=int, default=11)
    p.add_argument('--method', choices=METHODS, default='adam')
    p.add_argument('--train', choices=['cc5', 'gl5'], default='cc5')
    p.add_argument('--monitor', choices=['full', 'lazy'], default='full')
    args = p.parse_args()
    if args.mode == 'sweep':
        sweep(args.out)
    else:
        trial(args.out, {key: getattr(args, key) for key in ('width', 'seed', 'method', 'train', 'monitor')})
