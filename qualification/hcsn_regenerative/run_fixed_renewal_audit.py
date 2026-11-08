"""Reproduce the bounded FP64 release/zero-refractory construction checks."""

import argparse
import datetime
import hashlib
import io
import json
from pathlib import Path
import platform
import time
import unittest

import numpy as np
import scipy

from .fixed_renewal import FixedDiffusion, instant_reset_transition
from .tests.test_fixed_renewal import FixedRenewalTests, conservative_reset_pde


def source_map():
    directory = Path(__file__).parent
    return {str(p.relative_to(directory.parent.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [directory/'fixed_renewal.py', directory/'run_fixed_renewal_audit.py',
                      directory/'FIXED_RENEWAL.md', directory/'tests/test_fixed_renewal.py']}


def audit():
    start, cpu = time.monotonic(), time.process_time()
    sources = source_map()
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FixedRenewalTests))
    process = FixedDiffusion(-.1,.3)
    refinement = []
    for spacing in [.1,.05,.025]:
        centers,mass,count = conservative_reset_pde(spacing)
        exact = instant_reset_transition(process,.25,.35,1.4,np.arange(len(centers)+1)*spacing)
        refinement.append(dict(spacing=spacing,
                               max_cdf_error=float(np.abs(np.cumsum(mass)-np.cumsum(exact.active_bins)).max()),
                               hit_count_error=abs(count-exact.expected_hits_partial),
                               pde_hit_count=count, renewal_count_partial=exact.expected_hits_partial,
                               count_tail_bound=exact.omitted_hit_count_bound, terms=exact.terms))
    cases = []
    for x,horizon in [(1e-5,1e-6),(0.,1e-6),(.35,1.4),(4.,.5)]:
        state = instant_reset_transition(process,.25,x,horizon,[0.,.1,.25,.5,1.,2.,4.])
        cases.append(dict(x=x,horizon=horizon,mass_residual=state.mass_residual_against_truncated_law,
                          terms=state.terms,omitted_active_mass=state.omitted_active_mass,
                          log_omitted_active_mass=state.log_omitted_active_mass,
                          state_tail_exponential_underflow=state.omitted_active_mass==0 and horizon>0,
                          omitted_count_bound=state.omitted_hit_count_bound,
                          diagnostics=state.construction_diagnostics.__dict__))
    unchanged = sources == source_map()
    passed = result.wasSuccessful() and unchanged
    return dict(schema='hcsn-fixed-renewal-construction-v2',
                status='BOUNDED_FP64_CONSTRUCTION_CHECKS_PASS' if passed else 'FAIL',
                finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                source_files_sha256=sources,source_unchanged=unchanged,
                construction_dtype='float64',python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
                unit_methods_run=result.testsRun,unit_failures=len(result.failures),unit_errors=len(result.errors),
                unit_log=log.getvalue(),independent_time_convolution_cases=36,
                independent_pde_refinement=refinement,boundary_short_tail_cases=cases,
                wall_seconds=time.monotonic()-start,process_cpu_seconds=time.process_time()-cpu,
                physical_energy_joules=None,physical_energy_reason='No bound whole-machine physical meter',
                parameter_autodiff_qualified=False,tensor_execution_qualified=False,
                global_parameter_box_certified=False,task_training_runs=0,
                external_task_gain_established=False,original_campaign_completion_credit=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=audit()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():
        raise FileExistsError('Use a new immutable audit receipt path')
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('status','unit_methods_run','unit_failures','unit_errors','wall_seconds')}))
    return 0 if result['status']=='BOUNDED_FP64_CONSTRUCTION_CHECKS_PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
