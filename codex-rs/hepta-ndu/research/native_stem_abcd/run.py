"""Run one preregistered, from-scratch A/B/C/D experiment in a fresh process.

C solves reduced-space finite-law FBSDE collocation with exact shared-weight
Jacobians. It is not a general continuous-time FBSDE/PMP global-optimum claim.
"""
import os
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import argparse
import hashlib
import json
import platform
import resource
import sys
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import least_squares
import torch
from torch.func import jacfwd

from models import StateStem, TransformerStem, vector, assign, call_vector
from problem import make_world, terminals, exact_step, decimal_oracle, bernoulli_fbsde_defect

torch.set_num_threads(1)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    with open(path, 'xb') as f:
        f.write(data)
    return digest(data)


def residual(model, world, g, horizon, theta=None):
    """Uniform full law of terminal x initial-state x remaining-time collocation.

    Terminal is fixed. Both sides differentiate through previous predicted fields.
    No exact solved value or evaluation terminal enters fitting.
    """
    if not 1 <= horizon <= 16 or g.ndim != 2 or not torch.isfinite(g).all():
        raise ValueError('invalid terminal/horizon')
    v, defects = g, []
    for _ in range(horizon):
        nxt = model(v, world) if theta is None else call_vector(model, theta, v, world)
        defects.append((nxt-exact_step(v, world)).reshape(-1))
        v = nxt
    r = torch.cat(defects)
    return r / np.sqrt(r.numel())


class BudgetReached(Exception):
    pass


def fit(model, arm, world, g, horizon, seconds):
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    counts = dict(residual_evaluations=0, jacobian_evaluations=0,
                  optimizer_updates=0, model_step_calls=0, forward_ad_tangent_lanes=0)
    history, selected = [], vector(model)
    initial = digest(selected.tobytes())

    def check():
        if time.process_time()-start_cpu >= seconds:
            raise BudgetReached()

    status = 'cpu_cap'
    if arm in ('A', 'B'):
        opt = torch.optim.Adam(model.parameters(), lr=0.002 if arm == 'A' else 0.01)
        try:
            for step in range(100000):
                check()
                opt.zero_grad(set_to_none=True)
                r = residual(model, world, g, horizon)
                counts['residual_evaluations'] += 1
                counts['model_step_calls'] += horizon
                loss = torch.dot(r, r)
                if not torch.isfinite(loss):
                    raise FloatingPointError('nonfinite training loss')
                loss.backward()
                opt.step()
                with torch.no_grad():
                    for p in model.parameters():
                        p.clamp_(-12, 12)
                counts['optimizer_updates'] += 1
                if step % 25 == 0:
                    history.append([counts['optimizer_updates'], time.process_time()-start_cpu,
                                    float(loss.detach())])
        except BudgetReached:
            pass
        selected = vector(model)
    elif arm == 'B_LBFGS':
        # Same model/loss; generic quasi-Newton control, not an extra NDU mechanism.
        opt = torch.optim.LBFGS(model.parameters(), lr=1.0, max_iter=1,
                                max_eval=20, history_size=20, tolerance_grad=1e-12,
                                tolerance_change=1e-15, line_search_fn='strong_wolfe')
        def closure():
            check()
            opt.zero_grad(set_to_none=True)
            r = residual(model, world, g, horizon)
            counts['residual_evaluations'] += 1
            counts['model_step_calls'] += horizon
            loss = r.square().sum()
            if not torch.isfinite(loss):
                raise FloatingPointError('nonfinite LBFGS loss')
            loss.backward()
            return loss
        try:
            for _ in range(10000):
                check()
                loss = opt.step(closure)
                with torch.no_grad():
                    for p in model.parameters():
                        p.clamp_(-12, 12)
                selected = vector(model)
                counts['optimizer_updates'] += 1
                if counts['optimizer_updates'] % 10 == 0:
                    history.append([counts['optimizer_updates'], time.process_time()-start_cpu,
                                    float(loss.detach())])
        except BudgetReached:
            assign(model, selected)  # Do not adopt an unfinished line-search trial.
    elif arm == 'C':
        # Actual coupled residual solve; no Adam and no oracle/value-target access.
        def fun(x):
            check()
            counts['residual_evaluations'] += 1
            counts['model_step_calls'] += horizon
            with torch.no_grad():
                r = residual(model, world, g, horizon, torch.tensor(x, dtype=torch.float64))
            out = r.numpy()
            if not np.isfinite(out).all():
                raise FloatingPointError('nonfinite collocation residual')
            return out

        def jac(x):
            check()
            counts['jacobian_evaluations'] += 1
            counts['model_step_calls'] += horizon
            counts['forward_ad_tangent_lanes'] += len(x)
            t = torch.tensor(x, dtype=torch.float64)
            j = jacfwd(lambda z: residual(model, world, g, horizon, z))(t)
            return j.detach().numpy()

        def accepted(intermediate_result):
            nonlocal selected
            selected = intermediate_result.x.copy()
            counts['optimizer_updates'] += 1
            history.append([counts['optimizer_updates'], time.process_time()-start_cpu,
                            float(2*intermediate_result.cost)])

        try:
            solved = least_squares(fun, selected, jac=jac, method='trf',
                                   bounds=(-12, 12), max_nfev=10000,
                                   ftol=1e-12, xtol=1e-12, gtol=1e-12,
                                   callback=accepted)
            selected = solved.x.copy()
            status = f'scipy_status_{solved.status}'
        except BudgetReached:
            pass
        assign(model, selected)
    else:
        raise ValueError('not a fitted arm')
    return dict(status=status, initial_weights_sha256=initial,
                final_weights_sha256=digest(selected.tobytes()),
                nominal_training_cpu_cap_seconds=seconds,
                training_cpu_seconds=time.process_time()-start_cpu,
                training_wall_seconds=time.perf_counter()-start_wall,
                counts=counts, history=history,
                budget_semantics='check before evaluation; one operation may overshoot; no exact-FLOP match')


def predictions(model, arm, w, g, horizon):
    v = torch.tensor(g, dtype=torch.float64)
    values = [v]
    with torch.no_grad():
        for _ in range(horizon):
            v = exact_step(v, w) if arm == 'D' else model(v, w)
            values.append(v)
    return torch.stack(values).numpy()


def scores(pred, truth, world, probability=False):
    err = pred[1:]-truth[1:]
    defects, envelope, bounded, martingale = [], 0.0, True, 0.0
    w = world.tensor()
    for t in range(1, len(pred)):
        prev = torch.tensor(pred[t-1], dtype=torch.float64)
        step = exact_step(prev, w).numpy()
        rmax = float(np.max(np.abs(pred[t]-step)))
        defects.append(rmax)
        envelope = rmax+world.discount*envelope
        bounded &= float(np.max(np.abs(pred[t]-truth[t]))) <= envelope+2e-12
        martingale = max(martingale, float(bernoulli_fbsde_defect(prev, w).abs().max()))
    # A real initial choice among pairs of terminal contracts; evaluate against oracle costs.
    a, b = pred[-1, ::2], pred[-1, 1::2]
    aa, bb = truth[-1, ::2], truth[-1, 1::2]
    regret = np.where(a <= b, aa, bb)-np.minimum(aa, bb)
    margin = np.abs(aa-bb) > 1e-10
    result = dict(rmse=float(np.sqrt(np.mean(err**2))),
                  final_max_error=float(np.max(np.abs(err[-1]))),
                  decision_regret=float(np.mean(regret)),
                  decision_accuracy=float(np.mean(((a<=b)==(aa<=bb))[margin])) if margin.any() else None,
                  max_equation_defect=max(defects), finite_horizon_error_envelope=envelope,
                  envelope_verified=bool(bounded), martingale_defect=martingale,
                  distinct_terminal_tasks=len(pred[0]), state_count=world.size,
                  evaluated_scalar_values=int(err.size))
    # Same kernel; only the initial-state law changes. These are not extra independent tasks.
    mu = np.arange(1, world.size+1, dtype=float)**2
    mu /= mu.sum()
    result['shifted_initial_law_value_rmse'] = float(np.sqrt(np.mean((err[-1]@mu)**2)))
    if probability:
        raw, target = pred[-1], truth[-1]
        invalid = (raw < 0) | (raw > 1)
        p = np.clip(raw, 0, 1)
        result.update(probability_invalid_fraction=float(invalid.mean()),
                      raw_excess_brier=float(np.mean((raw-target)**2)),
                      clipped_excess_brier=float(np.mean((p-target)**2)),
                      clipped_brier=float(np.mean((p-target)**2+target*(1-target))))
        ece = 0.0
        for lo in np.arange(10)/10:
            mask = (p >= lo) & ((p < lo+0.1) if lo < .9 else (p <= 1))
            if mask.any():
                ece += mask.mean()*abs(float(p[mask].mean()-target[mask].mean()))
        result['expected_ece10_clipped'] = ece
    return result


def panels():
    return [
        ('training_law', 2, 'train', 3, False, False, 'same exact training population'),
        ('new_terminal', 2, 'transfer', 3, False, False, 'new terminal law; same generator'),
        ('long_horizon', 2, 'transfer', 8, False, False, 'new terminal and longer horizon; same generator'),
        ('higher_dimension', 6, 'transfer', 3, False, False, '2 to 6 binary physical coordinates; new state space'),
        ('changed_dynamics', 2, 'transfer', 3, True, False, 'different kernel supplied equally to every arm'),
        ('probability', 2, 'probability', 3, False, True, 'different utility: zero risk/unit discount; factual probability'),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=list('ABCD')+['B_LBFGS'], required=True)
    parser.add_argument('--seed', type=int, default=11)
    parser.add_argument('--cpu-seconds', type=float, default=8)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.cpu_seconds <= 0 or args.seed < 0:
        parser.error('positive budget/nonnegative seed required')
    args.out.mkdir(parents=True, exist_ok=False)
    begun = time.perf_counter(), time.process_time()
    source = {p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')}
    plan = dict(schema='hepta.native-ndu-stem-abcd.research.v1', arm=args.arm,
                seed=args.seed, cpu_seconds=args.cpu_seconds, source_sha256=source,
                train_world_bits=2, train_horizon=3, train_terminal_seed=1201,
                train_terminal_count=12, train_weight_box=[-12,12],
                objective='mean squared *full* finite-law FBSDE defect; terminal clamped',
                optimizer={'A':'Adam lr=.002', 'B':'Adam lr=.01', 'C':'TRF exact-jacfwd collocation',
                           'D':'direct monotone entropic operator', 'B_LBFGS':'LBFGS strong-Wolfe lr=1'}[args.arm],
                panels=panels(), pretrained_encoder=False, production_authorized=False)
    plan_hash = write_json(args.out/'PLAN.json', plan)
    write_json(args.out/'STARTED.json', dict(plan_sha256=plan_hash, pid=os.getpid()))
    train = make_world()
    w = train.tensor()
    g = torch.tensor(terminals(train, 'train'), dtype=torch.float64)
    prep_end = time.perf_counter(), time.process_time()
    model = None if args.arm == 'D' else (TransformerStem(args.seed) if args.arm == 'A' else StateStem(args.seed))
    parameter_count = 0 if model is None else sum(p.numel() for p in model.parameters())
    initialized = time.perf_counter(), time.process_time()
    fit_result = (dict(status='direct_constructed', nominal_training_cpu_cap_seconds=0,
                       training_cpu_seconds=0.0, training_wall_seconds=0.0, counts={})
                  if model is None else fit(model,args.arm,w,g,3,args.cpu_seconds))
    frozen = None if model is None else digest(vector(model).tobytes())
    # All inference is sealed before oracle scoring. No panel participates in selection.
    raw, metadata, prediction_start = {}, {}, time.process_time()
    for name, bits, split, horizon, changed, probability, scope in panels():
        world = make_world(bits, changed, probability)
        terminal = terminals(world, split)
        t = time.process_time()
        pred = predictions(model, args.arm, world.tensor(), terminal, horizon)
        if not np.isfinite(pred).all():
            raise FloatingPointError(f'nonfinite output in {name}')
        raw[name] = pred
        raw[name+'_terminal'] = terminal
        metadata[name] = dict(scope=scope, inference_cpu_seconds=time.process_time()-t,
                              prediction_sha256=digest(pred.tobytes()))
    with open(args.out/'PREDICTIONS.npz','xb') as f:
        np.savez_compressed(f, **raw)
    prediction_hash = digest((args.out/'PREDICTIONS.npz').read_bytes())
    write_json(args.out/'PREDICTIONS_SEAL.json', dict(sha256=prediction_hash, weights_sha256=frozen))
    inference_cpu = time.process_time()-prediction_start
    oracle_start, metrics = time.process_time(), {}
    for name, bits, split, horizon, changed, probability, scope in panels():
        world = make_world(bits, changed, probability)
        oracle = decimal_oracle(world, raw[name+'_terminal'], horizon)
        metrics[name] = scores(raw[name], oracle, world, probability)
        raw[name+'_oracle'] = oracle
    oracle_cpu = time.process_time()-oracle_start
    with open(args.out/'ORACLE.npz','xb') as f:
        np.savez_compressed(f, **{k:v for k,v in raw.items() if k.endswith('_oracle')})
    if model is not None:
        if frozen != digest(vector(model).tobytes()):
            raise AssertionError('evaluation mutated selected weights')
        with open(args.out/'WEIGHTS.npy','xb') as f:
            np.save(f, vector(model), allow_pickle=False)
    report = dict(plan_sha256=plan_hash, arm=args.arm, seed=args.seed, parameter_count=parameter_count,
                  parameter_bytes=8*parameter_count, fit=fit_result, panels=metadata, metrics=metrics,
                  prediction_sha256=prediction_hash, selected_weights_sha256=frozen,
                  forward_kernel_mass_error=float(np.max(np.abs(train.kernel().sum(1)-1))),
                  forward_law_after_3_steps=(np.ones(train.size)/train.size@np.linalg.matrix_power(train.kernel(),3)).tolist(),
                  phases_cpu_seconds=dict(preparation=prep_end[1]-begun[1],
                                          model_initialization=initialized[1]-prep_end[1],
                                          prediction_and_seal=inference_cpu,
                                          independent_oracle_and_scoring=oracle_cpu),
                  process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  total_cpu_from_main_seconds=time.process_time()-begun[1],
                  total_wall_from_main_seconds=time.perf_counter()-begun[0],
                  total_flops=None, energy_joules=None, external_project_cloud=False,
                  environment=dict(python=sys.version, torch=torch.__version__, numpy=np.__version__,
                                   scipy=scipy.__version__, platform=platform.platform(),
                                   threads=torch.get_num_threads()),
                  claims=dict(production_authorized=False, general_fbsde_stem_proved=False,
                              continuous_time_viscosity_convergence_proved=False,
                              full_distribution_training_enumerated=True,
                              same_heldout_distribution_as_train=False,
                              exact_compute_matched=False))
    write_json(args.out/'REPORT.json', report)
    print(json.dumps(dict(arm=args.arm, seed=args.seed, cpu=fit_result['training_cpu_seconds'],
                         train=metrics['training_law']['rmse'], transfer=metrics['new_terminal']['rmse'],
                         long=metrics['long_horizon']['rmse']), sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
