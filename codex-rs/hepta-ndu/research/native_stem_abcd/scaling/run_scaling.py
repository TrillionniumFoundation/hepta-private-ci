"""R8 complete scaling census; stopping monitors are separate from sealed evaluation."""
import os
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ.setdefault(key, '1')
import argparse
import hashlib
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
from engine import fit, TARGET, TOLERANCE, CADENCE, CAP
from wide import WidePolicy, make_problem, rule, evaluate, SCALE, ROOT

torch.set_num_threads(1)
HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, data):
    b = (json.dumps(data, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    with open(path, 'xb') as f:
        f.write(b)
    return digest(b)


def save(path, arrays):
    with open(path, 'xb') as f:
        np.savez_compressed(f, **arrays)


def sources():
    return {str(p.relative_to(ROOT)):digest(p.read_bytes())
            for d in (HERE, ROOT/'continuous', ROOT/'nonquadratic') for p in sorted(d.glob('*.py'))}


def specs():
    rows = []
    methods = ['adam', 'lbfgs', 'adjoint_ncg', 'ad_ncg']
    for j, width in enumerate((4, 16, 64, 256)):
        for i, seed in enumerate((11, 23, 47)):
            k = (i+j) % 4
            for method in methods[k:]+methods[:k]:
                rows.append(dict(width=width, seed=seed, method=method))
    return rows


def name_for(s):
    return f"w{s['width']}-{s['method']}-s{s['seed']}"


def panels():
    for name in ('cc17', 'gl9'):
        s, w = rule(name)
        yield name, s, w, make_problem()
    for rep in range(4):
        s = (2*qmc.Sobol(4, scramble=True, seed=2026101481+rep).random_base2(10)-1)*SCALE
        yield f'qmc{rep}', s, np.full(len(s), 1/len(s)), make_problem()
    s = (2*qmc.Sobol(4, scramble=True, seed=2026101481).random_base2(7)-1)*SCALE
    for name, ss, change in [('scale', 2*s, 'base'), ('dynamics', s, 'dynamics'), ('horizon4', s, 'horizon')]:
        yield name, ss, np.full(len(ss), 1/len(ss)), make_problem(change)


def trial(out, spec):
    out.mkdir(parents=True, exist_ok=False)
    started = time.process_time(), time.perf_counter()
    plan = dict(schema='hepta.ndu.scaling.r8', spec=spec, source=sources(), wall_cap=CAP,
                target=TARGET, integration_tolerance=TOLERANCE, cadence=CADENCE,
                parent='fd83665f764ea654f260090712d8bec370ec123a',
                protocol_commit='c8180293adfb6d552e2df40668a8a8883968d785')
    ph = dump(out/'PLAN.json', plan)
    policy = WidePolicy(spec['width'], spec['seed'])
    save(out/'INITIAL.npz', dict(theta=policy.initial))
    dump(out/'STARTED.json', dict(plan_sha256=ph))
    theta, checkpoints, info = fit(**spec)
    save(out/'WEIGHTS.npz', dict(theta=theta))
    save(out/'CHECKPOINTS.npz', dict(theta=checkpoints))
    ih, wh = digest(policy.initial.tobytes()), digest(theta.tobytes())
    dump(out/'FIT_SEAL.json', dict(weights=wh, checkpoints=digest((out/'CHECKPOINTS.npz').read_bytes()),
                                  fit_sha256=dump(out/'FIT.json', info)))
    now = time.process_time(); raw, metrics = {}, {}
    for name, s, w, problem in panels():
        raw[name] = evaluate(policy, torch.tensor(theta), problem, s, chunk=256)
        if not np.isfinite(raw[name]).all():
            raise FloatingPointError(name)
        metrics[name] = float(w@raw[name].mean(1))
    save(out/'PREDICTIONS.npz', raw)
    report = dict(plan_sha256=ph, spec=spec, initial_sha256=ih, weights_sha256=wh,
                  prediction_sha256=digest((out/'PREDICTIONS.npz').read_bytes()),
                  parameters=len(theta), changed=not np.array_equal(theta, policy.initial),
                  fit=info, metrics=metrics, evaluation_cpu=time.process_time()-now,
                  total_main_cpu=time.process_time()-started[0], total_main_wall=time.perf_counter()-started[1],
                  process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  source=plan['source'], environment=dict(python=sys.version, torch=torch.__version__,
                  numpy=np.__version__, platform=platform.platform(), threads=torch.get_num_threads()),
                  full_flops=None, energy_joules=None, production_authorized=False, project_cloud=False)
    if sources() != plan['source']:
        raise ValueError('source drift')
    dump(out/'REPORT.json', report)
    print(json.dumps(dict(name=name_for(spec), success=info['success'], observed=info['observed_wall'],
                         final=metrics['cc17'], fit_wall=info['wall'])), flush=True)


def sweep(out):
    out.mkdir(parents=True, exist_ok=False)
    laws = {}
    for n in ('cc5', 'cc9'):
        s, w = rule(n); laws[n+'_states'] = s; laws[n+'_weights'] = w
    save(out/'TRAIN_LAWS.npz', laws)
    ph = dump(out/'PLAN.json', dict(specs=specs(), source=sources(), target=TARGET,
        tolerance=TOLERANCE, cadence=CADENCE, cap=CAP, law_hash=digest((out/'TRAIN_LAWS.npz').read_bytes()),
        protocol_commit='c8180293adfb6d552e2df40668a8a8883968d785',
        primary='first observed qualifying time and success counts by width, C versus Adam; all controls retained'))
    start = time.perf_counter(); rows = []
    for spec in specs():
        name = name_for(spec); before = resource.getrusage(resource.RUSAGE_CHILDREN); now = time.perf_counter()
        command = [sys.executable, str(Path(__file__).resolve()), 'trial', '--out', str(out/name)]
        for k, v in spec.items():
            command += ['--'+k, str(v)]
        entry = dict(spec=spec, name=name)
        with open(out/(name+'.log'), 'xb') as log:
            try:
                r = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                entry.update(returncode=r.returncode, status='completed' if r.returncode==0 else 'failed')
            except subprocess.TimeoutExpired:
                entry.update(status='timeout', returncode=None)
            except OSError as exc:
                entry.update(status='launch_failed', returncode=None, error=str(exc))
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        entry.update(child_wall=time.perf_counter()-now,
                     child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
        if entry['status']=='completed':
            entry['report_sha256'] = digest((out/name/'REPORT.json').read_bytes())
        rows.append(entry); dump(out/(name+'.completion.json'), entry)
        print(json.dumps(entry), flush=True)
    failed = sum(r['status']!='completed' for r in rows)
    dump(out/'COMPLETE.json', dict(plan_sha256=ph, census=rows, completed=len(rows)-failed,
        failed=failed, wall=time.perf_counter()-start, child_cpu=sum(r['child_cpu'] for r in rows)))
    if failed:
        raise SystemExit('execution failures retained')


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('mode', choices=['trial', 'sweep'])
    p.add_argument('--out', type=Path, required=True); p.add_argument('--width', type=int, default=4)
    p.add_argument('--seed', type=int, default=11); p.add_argument('--method', default='adam')
    a = p.parse_args()
    if a.mode=='sweep':
        sweep(a.out)
    else:
        trial(a.out, dict(width=a.width, seed=a.seed, method=a.method))
