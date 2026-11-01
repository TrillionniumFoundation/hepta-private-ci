"""CPU wall/process cost of complete financial values and dense Jacobians.

All three modes receive identical already-quantized FP32 inputs. The original
FP64 formulas are constructed directly so FP32 endpoint encodings just outside
the decimal FP64 box are not rejected by the unrelated wrapper's range check.
The original FullHX boundary admissibility check is always retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
from threadpoolctl import threadpool_limits

import compensated_kernel as compensated
import frozen_kernel as original

ROOT = Path(__file__).resolve().parent
MODES = ('original_float64', 'original_single_float32', 'compensated_two_word_float32')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(theta, mode):
    if mode == MODES[2]:
        return compensated.build(theta)
    dtype = np.float64 if mode == MODES[0] else np.float32
    basis = np.eye(10, dtype=dtype)
    return original.FullHX([original.Dual(dtype(v), basis[i]) for i,v in enumerate(theta)])


def state(model, value, coordinate, mode):
    if mode == MODES[2]:
        return model.state(value, coordinate)
    dtype = np.float64 if mode == MODES[0] else np.float32
    argument = original.Dual(dtype(value), np.eye(10, dtype=dtype)[-1])
    x = original.log(argument / model.b) if coordinate == 'asset' else argument
    if coordinate == 'asset' and x.v <= 0:
        e, f, g = x.coerce(0.), x.coerce(1.), x.coerce(1.)
        debt = model.alpha*model.b/model.m
    else:
        e = model.equity(x)
        f, g = model.first_hit(x, model.m)
        debt = model.c/model.R + model.discount*model.q*(1-f)
        debt += (model.alpha*model.b/model.m-model.c/model.R)*g
    fields = [model.b,e,f,g,debt]
    return (np.asarray([v.v for v in fields], dtype=dtype),
            np.asarray([v.g for v in fields], dtype=dtype))


def batch(cases, mode, reuse):
    output = []
    for case in cases:
        try:
            model = build(case['theta'], mode) if reuse else None
            build_error = None
        except Exception as error:
            model, build_error = None, repr(error)
        for coordinate, value in case['states']:
            try:
                if build_error is not None:
                    raise ArithmeticError(build_error)
                current = model if reuse else build(case['theta'], mode)
                result = state(current, value, coordinate, mode)
                output.append((case['case'], coordinate, value, result, None))
            except Exception as error:
                output.append((case['case'], coordinate, value, None, repr(error)))
    return output


def run(output):
    if output.exists():
        raise ValueError('Evidence is create-only')
    protocol = json.loads((ROOT/'R16_VALIDATION_PROTOCOL_V1.json').read_text())
    expected = protocol['candidate_source_sha256']
    seal = {name: digest(ROOT/name) for name in expected}
    if seal != expected:
        raise ValueError('Candidate changed since independent validation protocol')
    source = json.loads((ROOT/'FROZEN_REFERENCE.json').read_text())
    seen, cases = set(), []
    for row in source['rows']:
        if row['case'] in seen:
            continue
        seen.add(row['case'])
        cases.append({'case': row['case'], 'theta': row['quantized_theta'],
                      'states': [('log_distance',float(np.float32(.001))),
                                 ('log_distance',float(np.float32(.1))), ('asset',100.)]})
    if len(cases) != 18:
        raise ValueError('Expected original eighteen parameter cases')
    records = []
    for reuse in (False, True):
        for mode in MODES:
            batch(cases, mode, reuse)  # One complete warmup, excluded from cost.
            wall, cpu = time.perf_counter(), time.process_time()
            result = batch(cases, mode, reuse)
            cpu, wall = time.process_time()-cpu, time.perf_counter()-wall
            failures, checksum = [], 0.
            for case, coordinate, value, answer, error in result:
                if error is not None:
                    failures.append({'case':case, 'coordinate':coordinate, 'state':value, 'error':error})
                elif not all(np.all(np.isfinite(v)) for v in answer):
                    failures.append({'case':case, 'coordinate':coordinate, 'state':value, 'error':'nonfinite result'})
                else:
                    checksum += sum(float(np.sum(v.astype(np.float64))) for v in answer)
            record = {'mode':mode, 'boundary_reuse':reuse, 'boundary_evaluations':18 if reuse else 54,
                      'requested_output_jacobian_evaluations':54, 'finite_completed_evaluations':54-len(failures),
                      'complete_batch_comparable':not failures, 'wall_seconds':wall, 'cpu_seconds':cpu,
                      'wall_seconds_per_complete_state':wall/54 if not failures else None,
                      'cpu_seconds_per_complete_state':cpu/54 if not failures else None,
                      'failed_evaluations':failures, 'diagnostic_output_checksum':checksum}
            records.append(record)
            print(json.dumps(record), flush=True)
    after = {name:digest(ROOT/name) for name in expected}
    if after != seal:
        raise ValueError('Sources changed during cost measurement')
    result = {'schema':'hcsn.r16.financial-operator-cpu-cost.v1',
              'precision_contract':'Original FP64; original ordinary one-word FP32 (numerically unqualified); explicit two-word compensated FP32 (extended significand).',
              'timing_scope':'CPU Python implementation; imports/constant preparation excluded, one complete warmup and one measured batch per mode and reuse condition; process CPU and wall time. No GPU, energy, throughput-distribution or production-speed claim.',
              'evaluation_scope':'Complete differentiated boundary plus all five financial outputs and all ten Jacobian columns. Separate reuse condition includes one boundary per parameter case amortized across three states.',
              'represented_inputs':'Identical quantized FP32 parameter/state words converted exactly to FP64 for original Float64 formulas. Original FullHX formulas and boundary checks unchanged; wrapper decimal-box check replaced by fixed registered FP32 input manifest.',
              'script_sha256':digest(Path(__file__)), 'source_sha256_before':seal, 'source_sha256_after':after,
              'development_reference_sha256':digest(ROOT/'FROZEN_REFERENCE.json'),
              'protocol_sha256':digest(ROOT/'R16_VALIDATION_PROTOCOL_V1.json'),
              'environment':{'python':platform.python_version(), 'numpy':np.__version__,
                             'system':platform.platform(), 'threadpool_limit':1},
              'inputs':cases, 'records':records,
              'correctness_scope':'Timing does not admit the original single-FP32 mode or replace numerical evidence.'}
    with output.open('x') as handle:
        json.dump(result,handle,indent=2,allow_nan=False)
        handle.write('\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with threadpool_limits(limits=1):
        run(args.output.resolve())
