"""Real import-closure check in the registered empty cwd; no model/data access."""
import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery04 import cwd_runner


def main():
    wall, cpu = time.monotonic(), time.process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--expected-policy-sha256', required=True)
    parser.add_argument('--freeze', required=True)
    parser.add_argument('--expected-freeze-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    require = cwd_runner.require
    policy = cwd_runner.validate_policy(args.policy, args.expected_policy_sha256)
    require(Path.cwd().resolve() == cwd_runner.empty_directory(policy), 'Probe cwd differs')
    require(cwd_runner.digest(args.freeze) == args.expected_freeze_sha256, 'Probe freeze differs')
    frozen = json.loads(Path(args.freeze).read_bytes())
    require(frozen['source_files'] == policy['source_files'], 'Probe and policy source closure differ')
    prefix = 'experiments.parameter_field_fullstudy_20261029.'
    resources = importlib.import_module(prefix + 'resource_v2')
    admission = resources.memory_admission()
    require(admission['allowed'], 'Original 768 MiB plus 1 GiB margin not available for import probe')
    runner = importlib.import_module(prefix + 'run_v2')
    runner.verify_files(frozen, SOURCE)
    modules = ('run', 'architecture_run', 'endpoint_v2', 'endpoints', 'architecture_endpoints',
               'replay_terminals', 'witness', 'analysis_launch_v2', 'report_results')
    for name in modules:
        importlib.import_module(prefix + name)
    # This loads exactly the pinned HCSN class modules, without constructing a
    # model or opening a checkpoint. It exercises their dynamic import paths.
    architecture = importlib.import_module(prefix + 'architecture')
    architecture.reference_modules(SOURCE)
    runner.ensure_loaded_closure(frozen)
    import numpy as np
    import torch
    import PIL
    require(platform.python_version() == '3.12.14' and str(torch.__version__) == '2.8.0+cpu'
            and np.__version__ == '2.3.5' and PIL.__version__ == '12.3.0', 'Exact restored runtime differs')
    after = resources.memory_profile()
    require(after['oom'] == admission['oom'] and after['oom_kill'] == admission['oom_kill'],
            'An OOM counter changed during the import probe')
    output = Path(args.output).absolute()
    require(output.is_relative_to(Path(policy['ops_root']))
            and not output.is_relative_to(Path(policy['raw_root']))
            and not output.is_relative_to(SOURCE), 'Probe receipt must be an external OPS artifact')
    receipt = {'schema': 'hepta.fullstudy.import-closure-probe.4', 'complete': True,
        'execution_episode': policy['execution_episode'], 'at_utc': datetime.now(timezone.utc).isoformat(),
        'policy': cwd_runner.descriptor(args.policy), 'freeze': cwd_runner.descriptor(args.freeze),
        'cwd': str(Path.cwd()), 'python_executable': os.path.abspath(sys.executable),
        'runtime': {'python': platform.python_version(), 'torch': str(torch.__version__),
                    'numpy': np.__version__, 'pillow': PIL.__version__},
        'modules_imported': list(modules), 'original_loaded_closure_check_passed': True,
        'pinned_hcsn_modules_imported_without_instantiation': True,
        'model_instances_created': 0, 'checkpoints_decoded': 0, 'dataset_values_read': 0,
        'scheduled_gradient_microsteps': 0, 'workers_started': 0,
        'admission': admission, 'resources_after': after,
        'wall_seconds': time.monotonic() - wall, 'own_cpu_seconds': time.process_time() - cpu,
        'process_cpu_seconds_total': time.process_time(),
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'not_a_successful_scientific_resource_qualification': True}
    cwd_runner.write_new(output, receipt)
    print(json.dumps({'status': 'REAL_IMPORT_CLOSURE_VERIFIED_ONLY', 'receipt': cwd_runner.descriptor(output),
                      'workers_started': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
