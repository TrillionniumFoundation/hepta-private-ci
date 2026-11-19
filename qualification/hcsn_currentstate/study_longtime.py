"""Bounded fresh-process cost/accuracy diagnostic; the finite-state kernel is unchanged."""

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time


ROOT = Path(__file__).parents[2]
KERNEL = Path(__file__).with_name("differentiable.py")
KERNEL_SHA = "fccee9781c86af243c5f691f876d0dec34296edfedc327d6f4a100bcd2def949"
TIMES = ("1/5", "4/5", "16/5", "32/5", "64/5")
LIMITS = {"total_cpu_seconds": 120, "total_wall_seconds": 180,
          "case_wall_seconds": 45, "address_space_bytes": 4*1024**3,
          "threads": 1, "max_dimension": 256, "max_packets": 256,
          "max_exponentials": 2048}
THREADS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def save(path, report):
    temporary = path.with_suffix(".part.json")
    temporary.write_text(json.dumps(report, allow_nan=False, sort_keys=True, indent=2)+"\n")
    temporary.replace(path)


def source_hashes():
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), KERNEL)}
    if hashes[KERNEL.name] != KERNEL_SHA:
        raise ValueError("original scientific kernel identity changed")
    return hashes


def renewal_reference(target, rate, dps):
    """Integer Gamma CDFs, independent of candidate matrices and autograd."""
    import mpmath as mp
    with mp.workdps(dps):
        lam, delay = mp.mpf(rate), Fraction(1, 5)
        def count(t):
            hits, derivative = mp.mpf(0), mp.mpf(0)
            for k in range(1, int(max(t, Fraction(0))/delay)+2):
                duration = t-(k-1)*delay
                if duration <= 0:
                    continue
                u = mp.mpf(duration.numerator)/duration.denominator
                z = lam*u
                hits += mp.gammainc(k, 0, z)/mp.factorial(k-1)
                derivative += u*mp.exp(-z)*z**(k-1)/mp.factorial(k-1)
            return hits, derivative
        hits, dh = count(target)
        released, dr = count(target-delay)
        waiting, dw = hits-released, dh-dr
        values, gradients = (hits, 1-waiting, waiting), (dh, -dw, dw)
        return [[mp.nstr(weight*x, dps) for x in row]
                for row in (values, gradients) for weight in (mp.mpf(1), mp.mpf(-.3))]


def child(target, output, cpu_limit):
    # Numerical libraries are imported only after both kernel limits are set.
    resource.setrlimit(resource.RLIMIT_AS, (LIMITS['address_space_bytes'],)*2)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit+1))
    report = {"status": "started", "phase": "imports", "target": str(target),
              "source_sha256_before": source_hashes(), "limits": LIMITS,
              "rlimit_as": list(resource.getrlimit(resource.RLIMIT_AS)),
              "rlimit_cpu": list(resource.getrlimit(resource.RLIMIT_CPU)),
              "thread_environment": {k: os.environ.get(k) for k in THREADS}}
    save(output, report)
    started, cpu = time.perf_counter(), time.process_time()
    try:
        import torch
        import mpmath as mp
        from .differentiable import Physics, Work, advance, initial, refractory
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        report.update(torch=torch.__version__, mpmath=mp.__version__, python=sys.version,
                      platform=platform.platform(), torch_threads=torch.get_num_threads(),
                      torch_interop_threads=torch.get_num_interop_threads(), dtype="float64",
                      rate_fp64_hex=float(1.7).hex(), delay="1/5", initial_channels=[1., -.3],
                      discount=.15, active_reward=0., escape_reward=0., spike_reward=1.)
        reference = renewal_reference(target, 1.7, 80)
        reference50 = renewal_reference(target, 1.7, 50)
        with mp.workdps(80):
            report['reference_50_vs_80_max_absolute_error'] = str(max(
                abs(mp.mpf(a)-mp.mpf(b)) for ra, rb in zip(reference, reference50) for a,b in zip(ra, rb)))
        report['reference_80_digits'] = dict(zip(('values_probability', 'values_content',
                                                 'gradients_probability', 'gradients_content'), reference))
        report.update(phase="forward", quantity_order=['hit_count', 'active', 'refractory'])
        save(output, report)
        rate = torch.tensor(1.7, dtype=torch.float64, requires_grad=True)
        p = Physics(-rate.reshape(1,1), rate.reshape(1), rate.new_zeros(1), rate.new_ones(1),
                    rate.new_zeros(1), rate.new_zeros(()), rate.new_ones(()), rate.new_tensor(.15))
        work = Work(max_dimension=LIMITS['max_dimension'], max_packets=LIMITS['max_packets'],
                    max_exponentials=LIMITS['max_exponentials'])
        before, cp = time.perf_counter(), time.process_time()
        state = advance(initial(rate.new_tensor([[1.],[-.3]])), p, target, work)
        advance_wall, advance_cpu = time.perf_counter()-before, time.process_time()-cp
        advance_exponentials, advance_dimension = work.exponentials, work.largest_dimension
        before, cp = time.perf_counter(), time.process_time()
        waiting = refractory(state, work)
        refractory_wall, refractory_cpu = time.perf_counter()-before, time.process_time()-cp
        values = torch.stack((state.hits, state.active.sum(1)+state.upper, waiting), 1)
        report.update(phase="backward", values=values.detach().tolist(),
                      state_tensor_bytes=state.tensor_bytes(), pending_packets=len(state.pending),
                      pending_generator_orders=[list(t.generator.shape) for t in state.pending],
                      advance_forward_seconds=advance_wall, advance_forward_cpu_seconds=advance_cpu,
                      refractory_forward_seconds=refractory_wall, refractory_forward_cpu_seconds=refractory_cpu,
                      advance_explicit_exponentials=advance_exponentials,
                      refractory_explicit_exponentials=work.exponentials-advance_exponentials,
                      advance_largest_matrix=advance_dimension, all_forward_largest_matrix=work.largest_dimension,
                      maximum_signed_mass_balance_error=float((values[:,1]+values[:,2]-rate.new_tensor([1.,-.3])).abs().max()),
                      peak_rss_after_forward_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        save(output, report)
        before, cp = time.perf_counter(), time.process_time()
        scalars = values.flatten().unbind()
        gradients = [torch.autograd.grad(v, rate, retain_graph=i<len(scalars)-1)[0]
                     for i, v in enumerate(scalars)]
        backward_wall, backward_cpu = time.perf_counter()-before, time.process_time()-cp
        gradient = torch.stack(gradients).reshape(2,3)
        report.update(phase="complete", gradients=gradient.detach().tolist(),
                      backward_seconds=backward_wall, backward_cpu_seconds=backward_cpu,
                      backward_scalar_calls=len(scalars), backward_internal_exponentials="not instrumented",
                      all_values_and_gradients_finite=bool(torch.isfinite(values).all() and torch.isfinite(gradient).all()))
        expected = torch.tensor([[float(s) for s in row] for row in reference], dtype=torch.float64)
        report.update(value_absolute_errors=(values.detach()-expected[:2]).abs().tolist(),
                      gradient_absolute_errors=(gradient.detach()-expected[2:]).abs().tolist(),
                      maximum_value_absolute_error=float((values.detach()-expected[:2]).abs().max()),
                      maximum_gradient_absolute_error=float((gradient.detach()-expected[2:]).abs().max()),
                      status="completed")
    except Exception as error:
        report.update(status="failed", error=repr(error))
    finally:
        report.update(child_measured_wall_seconds=time.perf_counter()-started,
                      child_measured_cpu_seconds=time.process_time()-cpu,
                      peak_rss_native_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      source_sha256_after=source_hashes())
        save(output, report)
    print(json.dumps({k: report[k] for k in ('target','status','phase')}, sort_keys=True), flush=True)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    initial_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = {"schema": "hcsn-currentstate-longtime-cost-diagnostic-v1", "limits": LIMITS,
              "source_sha256": source_hashes(), "times": TIMES,
              "scope": "one-state finite CTMC; no continuum, training or full-network claim",
              "tensor_bytes_scope": "all State tensors including repeated references; excludes Python, allocator and autograd graph",
              "forward_scope": "advance plus refractory with gradients enabled; excludes imports, oracle, construction, output serialization",
              "backward_scope": "six scalar autograd calls, same graph, probability and signed content for three quantities",
              "rss_scope": "fresh child lifetime high-water, Linux KiB; includes imports, references, forward and backward",
              "cases": []}
    save(output/'REPORT.json', report)
    for index, target in enumerate(TIMES):
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        spent_cpu = time.process_time()-cpu+usage.ru_utime+usage.ru_stime-initial_usage.ru_utime-initial_usage.ru_stime
        # Reserve for controller/reaping and the one-second CPU hard-limit interval.
        remaining_cpu = LIMITS['total_cpu_seconds']-spent_cpu-2
        remaining_wall = LIMITS['total_wall_seconds']-(time.perf_counter()-started)-1
        cpu_limit = min(43, math.floor(remaining_cpu)-1)
        wall_limit = min(LIMITS['case_wall_seconds'], remaining_wall)
        item = {"index": index, "target": target, "cpu_soft_limit": cpu_limit,
                "full_process_wall_limit": wall_limit}
        if cpu_limit < 1 or wall_limit < 1:
            item.update(status="censored_not_started", reason="total campaign resource limit")
            report['cases'].append(item)
            continue
        path = output/f'case-{index:03d}.json'
        env = {**os.environ, **{key: '1' for key in THREADS}, "PYTHONHASHSEED": "0"}
        command = [sys.executable, '-m', 'qualification.hcsn_currentstate.study_longtime',
                   '--child', target, '--cpu-limit', str(cpu_limit), '--output', str(path)]
        child_started = time.perf_counter()
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=max(.001, wall_limit-(time.perf_counter()-child_started)))
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            item.update(status="censored_wall", reason="fresh-process wall limit")
        elapsed = time.perf_counter()-child_started
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        item.update(full_process_wall_seconds=elapsed, fresh_process_cpu_seconds=
                    after.ru_utime+after.ru_stime-usage.ru_utime-usage.ru_stime,
                    returncode=process.returncode, stdout=stdout, stderr=stderr)
        if path.exists():
            result = json.loads(path.read_text())
            item.update(child_result=path.name, child_result_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        last_observed_phase=result['phase'])
            item.setdefault('status', result['status'] if process.returncode == 0 else 'censored_process_exit')
        else:
            item.setdefault('status', 'failed_no_child_receipt')
        report['cases'].append(item)
        save(output/'REPORT.json', report)
        print(json.dumps(item, sort_keys=True), flush=True)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(wall_seconds=time.perf_counter()-started, total_cpu_seconds=time.process_time()-cpu+
                  usage.ru_utime+usage.ru_stime-initial_usage.ru_utime-initial_usage.ru_stime,
                  source_sha256_after=source_hashes())
    save(output/'REPORT.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--child', choices=TIMES)
    parser.add_argument('--cpu-limit', type=int)
    args = parser.parse_args()
    if args.child:
        child(Fraction(args.child), args.output, args.cpu_limit)
    else:
        run(args.output.resolve())
