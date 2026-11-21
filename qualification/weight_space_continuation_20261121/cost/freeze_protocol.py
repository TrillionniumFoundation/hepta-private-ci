#!/usr/bin/env python3
"""Seal a finite research queue without importing Torch or executing a model."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from importlib import metadata
import os
from pathlib import Path
import platform
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False); f.write('\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old-root', type=Path, required=True)
    ap.add_argument('--runtime', type=Path, required=True)
    a = ap.parse_args(); root = Path(__file__).resolve().parent
    old, runtime = a.old_root.resolve(), a.runtime.resolve()
    fits = [f'{arm}-s{seed}' for arm in ('flow', 'flow_fixed') for seed in (101, 211, 307)]
    cases = ['training64', 'synthetic1', 'synthetic20']
    queue = []
    for phase, blocks in [('calibration', 2), ('confirmation', 4)]:
        for block in range(blocks):
            for i, fit in enumerate(fits):
                for j, case in enumerate(cases):
                    paths = ['reference', 'specialized']
                    if (block + i + j) % 2: paths.reverse()
                    for impl in paths:
                        queue.append(dict(phase=phase, block=block, fit=fit, case=case,
                                          implementation=impl, calls=4,
                                          archive_first_call=(phase == 'calibration' and block == 0)))
    write(root/'WORKLOAD_FROZEN.json', dict(schema='hepta.finite-cost-worklist.v1',
        calls_per_implementation_confirmation=288, total_calls=864, rows=queue))
    paths = [old/'specialize.py', old/'PROTOCOL_FROZEN.json', old/'UPSTREAM_PROTOCOL.json',
             old/'RUNTIME_READBACK.json', old/'attempt001/inputs.npz',
             old/'attempt001/RESULTS.json', old/'CHILD_COST.json']
    paths += sorted((old/'upstream').rglob('*.py'))
    for fit in fits:
        paths.append(old/'originals/campaign/fits'/fit/'selected.pt')
        for case in cases:
            for kind in ('full', 'cold'):
                paths += [old/'attempt001'/fit/(case+'-'+kind+ext) for ext in ('.npz', '.json')]
    paths += [root/name for name in ('README.md', 'freeze_protocol.py', 'run_cost_study.py',
                                    'supervise.py', 'read_costs.py', 'COST_SCHEMA.json',
                                    'WORKLOAD_FROZEN.json')]
    runtime_paths = [Path(sys.executable).resolve(), runtime/'torch/version.py',
                     runtime/'torch-2.8.0+cpu.dist-info/RECORD',
                     Path(metadata.distribution('numpy')._path)/'RECORD',
                     runtime/'ncps-1.0.1.dist-info/RECORD']
    for p in runtime_paths:
        if not p.is_file(): raise ValueError('Missing pinned runtime file: '+str(p))
    old_result = json.loads((old/'attempt001/RESULTS.json').read_text())
    ref_times = [t['cpu_seconds'] for r in old_result['results'] for t in r.get('timings', [])
                 if t['path'] == 'reference']
    max_ref = max(ref_times)
    # Deliberately pessimistic pre-execution allocation, not a measured new cost.
    budget_estimate = max_ref * 432 + .045 * 864 + 10.0
    if budget_estimate > 110:
        raise ValueError('Frozen queue preflight budget exceeds 110 CPU seconds')
    protocol = dict(schema='hepta.specialization-cost-protocol.v1',
        created_utc=datetime.now(timezone.utc).isoformat(), old_root=str(old), runtime=str(runtime),
        fits=fits, cases=cases, cpu_affinity=[8], torch_threads=1, interop_threads=1,
        torch_version='2.8.0+cpu', dtype='float64', device='cpu',
        cases_contract={'training64': [10,64,2], 'synthetic1': [10,1,2], 'synthetic20': [20,8,2]},
        laws='each selected checkpoint own frozen episode() law, shared across its two layers',
        dt='1/20', initial_state='reset_probability_zero_signed_content',
        full_state_contract='hcsn-causal-network-state-v1 plus emissions, logits; pending packets, messages, written ledgers and initial totals retained',
        cold_restore='torch.save into BytesIO, weights_only torch.load and state_from_record; same process, no former autograd graph',
        continuation_input='last input multiplied by 0.25, one ordinary flow.step',
        abs_tolerance=1e-10, rel_tolerance=1e-9, require_same_argmax=True,
        no_new_quality_holdout=True, no_bitwise_equivalence_claim=True,
        hardware={'machine':platform.machine(), 'kernel':platform.release(), 'python':platform.python_version(),
            'logical_cpus':os.cpu_count(), 'available_affinity':sorted(os.sched_getaffinity(0)),
            'cpu_model':[s.split(':',1)[1].strip() for s in Path('/proc/cpuinfo').read_text().splitlines() if s.startswith('model name')][0],
            'exclusive_host':False},
        budget={'main_child_soft_cpu_seconds':114, 'main_child_hard_cpu_seconds':116,
            'all_children_cpu_seconds':120, 'main_wall_seconds':240, 'rss_cap_bytes':512*1024*1024,
            'timeout_probe_wall_seconds':0.125, 'reader_cpu_soft_seconds':2,
            'post_analysis_cpu_reserve_seconds':3.0,
            'preflight_old_max_reference_cpu_seconds':max_ref,
            'preflight_other_per_call_allocation_seconds':0.045,
            'preflight_common_allocation_seconds':10.0,
            'preflight_estimated_cpu_seconds':budget_estimate,
            'preflight_is_budget_allocation_not_future_bound':True},
        prediction={'lower_multiplier':0.5, 'upper_multiplier':2.0,
            'unit':'one fixed four-call cell block',
            'bound_kind':'predeclared_empirical_prediction_envelope',
            'statistical_coverage_claim':False, 'enforceable_future_bound':False,
            'confirmation_rule':'record every block and aggregate violation; never refit or delete zeros'},
        choice={'objective':'minimum CPU for this finite research queue subject to full-state equivalence, 512MiB RSS, study CPU/wall budgets',
            'candidate_cpu_upper':'all preconfirmation CPU including imports, prepare, both-path calibration and timeout probe + 3s post-analysis reserve + sum(2*max calibration block CPU)*4',
            'original_cpu_lower':'sum(0.5*min reference calibration block CPU)*4',
            'selection_rule':'COMPILED only if every calibration comparison and argmax passes, peak RSS below cap, and candidate CPU upper strictly less than original CPU lower; otherwise KEEP_ORIGINAL; all failure => STOP',
            'decision_before_confirmation':True, 'both_paths_confirmation_purpose':'preauthorized paired research validation'},
        general_ndu={'decision':'KEEP_ORIGINAL_AND_STOP', 'production_horizon':None,
            'owner_future_original_lower':None, 'owner_future_candidate_upper':None,
            'resource_utility_exchange_rates':None, 'production_eligible':False},
        worklist_sha256=sha(root/'WORKLOAD_FROZEN.json'),
        pins=[dict(path=str(p.resolve()), bytes=p.stat().st_size, sha256=sha(p)) for p in paths],
        runtime_pins=[dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p)) for p in runtime_paths],
        runtime_pin_limitation='interpreter, package RECORD and Torch version pinned; not a complete file-by-file dependency reauthentication')
    write(root/'PROTOCOL_FROZEN.json',protocol)
    write(root/'FREEZE_RECEIPT.json',dict(created_utc=protocol['created_utc'],
        protocol_sha256=sha(root/'PROTOCOL_FROZEN.json'), worklist_sha256=protocol['worklist_sha256'],
        model_calls_before_seal=0, pins=len(paths), preflight_estimated_cpu_seconds=budget_estimate))
    print(json.dumps({'status':'FROZEN','protocol_sha256':sha(root/'PROTOCOL_FROZEN.json'),
        'worklist_sha256':protocol['worklist_sha256'],'pins':len(paths), 'budget_estimate':budget_estimate}))


if __name__ == '__main__': main()
