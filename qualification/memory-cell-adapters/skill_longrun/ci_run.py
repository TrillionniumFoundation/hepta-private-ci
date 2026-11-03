"""Run a separately frozen skill-maintenance experiment on a fresh CI runner."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent
REPO = HERE.parents[2]
INITIAL = Path('/workspace/scratch/76e2020e4b36/memory-adapter-formal-01')
ARCHIVE_SHA = 'ac5a13169fcad61eda46ee4e42c67e5549c82da48a32c1121e9727baa2ee706f'

# Reuse only the unchanged generic process/accounting functions. Importing this
# module does not execute its semantic experiment or read its held results.
spec = importlib.util.spec_from_file_location('skill_ci_process_support', ADAPTER/'longrun'/'ci_run.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
command, identity, save, text_file = support.command, support.identity, support.save, support.text_file


def run(args):
    started, own_cpu = time.monotonic_ns(), time.process_time_ns()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    phases = []
    try:
        if os.environ.get('GITHUB_ACTIONS') != 'true' or sys.version_info[:2] != (3, 12):
            raise ValueError('registered GitHub Actions Python 3.12 required')
        request = json.loads(args.request.read_bytes())
        protocol_sha = identity(HERE/'LONGRUN_PROTOCOL.json')['sha256']
        if (set(request) != {'schema', 'request_id', 'protocol_sha256', 'initial_archive_sha256'}
                or request['schema'] != 'hepta.memory.skill-longrun-request.v1'
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', request['request_id'])
                or request['protocol_sha256'] != protocol_sha
                or request['initial_archive_sha256'] != ARCHIVE_SHA
                or (HERE/'LONGRUN_PROTOCOL.sha256').read_text().strip() != protocol_sha):
            raise ValueError('skill request differs from the committed protocol or initial archive')
        protocol = json.loads((HERE/'LONGRUN_PROTOCOL.json').read_bytes())
        if Path(protocol['initial_study']) != INITIAL:
            raise ValueError('initial-study namespace differs from the frozen protocol')
        run_root = output/'run-01-skill'
        save(output/'REQUEST.json', request)
        save(output/'PATHS.json', {'repo_root': str(REPO), 'adapter_root': str(ADAPTER),
             'output_root': str(output), 'run_root': str(run_root), 'initial_study': str(INITIAL),
             'audit_rule': 'explicit prefix mappings after download; original requests and receipts are immutable'})
        marker = None
        if args.job_start_marker is not None and args.job_start_marker.exists():
            shutil.copyfile(args.job_start_marker, output/'JOB_START.json')
            marker = json.loads(args.job_start_marker.read_bytes())
        hardware = {'schema': 'hepta.memory.adapter-skill-ci-hardware.v1', 'scope': 'skill',
                    'platform': platform.platform(), 'machine': platform.machine(),
                    'uname': list(platform.uname()), 'logical_cpus': os.cpu_count(),
                    'python': sys.version, 'executable': sys.executable,
                    'os_release': text_file('/etc/os-release'), 'cpuinfo': text_file('/proc/cpuinfo'),
                    'meminfo': text_file('/proc/meminfo'), 'cpu_max': text_file('/sys/fs/cgroup/cpu.max'),
                    'memory_max': text_file('/sys/fs/cgroup/memory.max'),
                    'boot_id': text_file('/proc/sys/kernel/random/boot_id'),
                    'disk_before': shutil.disk_usage(output)._asdict(),
                    'environment': {k: os.environ.get(k) for k in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS',
                        'ImageVersion', 'GITHUB_SHA', 'GITHUB_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REPOSITORY')},
                    'same_hardware_as_semantic_run_claimed': False}
        hardware['job_pre_wrapper_wall_ns'] = (started-marker['monotonic_ns']
            if marker is not None and marker.get('boot_id') == hardware['boot_id'] else None)
        save(output/'HARDWARE.json', hardware)
        phases.append(command(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], output/'source-commit', timeout=60))
        phases.append(command(['git', '-C', str(REPO), 'rev-parse', 'HEAD^{tree}'], output/'source-tree', timeout=60))
        commit = (output/'source-commit.stdout').read_text().strip()
        tree = (output/'source-tree.stdout').read_text().strip()
        if commit != os.environ.get('GITHUB_SHA'):
            raise ValueError('runner checkout differs from GitHub source identity')
        save(output/'CI_SOURCE.json', {'commit': commit, 'tree': tree,
             'workflow': {'path': '.github/workflows/memory-adapter-skill-longrun.yml',
                          **identity(REPO/'.github/workflows/memory-adapter-skill-longrun.yml')},
             'request': identity(args.request), 'protocol': identity(HERE/'LONGRUN_PROTOCOL.json')})
        pip = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir']
        phases.append(command(pip+['--index-url', 'https://pypi.org/simple', 'numpy==2.3.5'], output/'install-numpy'))
        phases.append(command(pip+['--index-url', 'https://download.pytorch.org/whl/cpu', 'torch==2.8.0+cpu'], output/'install-torch'))
        phases.append(command([sys.executable, '-m', 'pip', 'freeze', '--all'], output/'pip-freeze'))
        parent = INITIAL.parent
        if any(p.is_symlink() for p in (parent, *parent.parents)) or INITIAL.exists():
            raise ValueError('new nonsymlink initial-study destination required')
        if parent.exists():
            if not parent.is_dir() or any(parent.iterdir()) or not os.access(parent, os.W_OK):
                raise ValueError('existing initial-study parent must be empty and writable')
        else:
            phases.append(command(['sudo', '-n', 'install', '-d', '-m', '0755', '-o', str(os.getuid()),
                                   '-g', str(os.getgid()), str(parent)], output/'create-initial-parent', timeout=60))
        archive_root = ADAPTER/'evidence'/'formal-01'
        archive = json.loads((archive_root/'ARCHIVE.json').read_bytes())
        if archive['archive']['sha256'] != ARCHIVE_SHA:
            raise ValueError('published initial archive differs')
        phases.append(command([sys.executable, '-I', '-B', str(archive_root/'restore.py'), str(INITIAL)],
                              output/'restore-formal', timeout=300))
        training = json.loads((INITIAL/'models'/'TRAINING.json').read_bytes())
        historical = json.loads((INITIAL/'training.process.json').read_bytes())
        encoder = json.loads((INITIAL/'development-encoder.json').read_bytes())
        if (historical['exit_code'] != 0 or historical['pid'] != training['pid'] or historical['timed_out']
                or encoder['base_encoder_sha'] != training['encoder_sha']):
            raise ValueError('historical training identity is not a completed successful source process')
        for name in ('sources.json', 'canonical.npz', 'models/TRAINING.json', 'training.process.json',
                     'development-encoder.json', *[f'read-seed-{seed}-event-0.sqlite' for seed in (731, 732, 733)]):
            if identity(INITIAL/name) != archive['files'][name]:
                raise ValueError('restored input identity mismatch: '+name)
        diagnostic = r'''import contextlib,io,json,pathlib,platform,sys
import numpy as np,torch
root,initial=map(pathlib.Path,sys.argv[1:])
sys.path.insert(0,str(root))
from tensor_cell import TensorCell
if str(torch.__version__)!='2.8.0+cpu' or np.__version__!='2.3.5' or torch.version.cuda is not None:
 raise ValueError('pinned CPU dependency contract differs')
torch.set_num_threads(1)
torch.use_deterministic_algorithms(True)
rows=[]
for seed in (731,732,733):
 folder=initial/'models'/f'seed-{seed}'/'skill'
 manifest=json.loads((folder/'manifest.json').read_bytes())
 cell=TensorCell.load(folder,manifest['base_encoder_sha'])
 rows.append({'seed':seed,'initial_checkpoint_sha256':cell.parameter_digest(),'architecture':manifest['config'],
  'base_encoder_sha':manifest['base_encoder_sha'],'parameter_counts':cell.parameter_counts(),
  'new_untrained_initialization':'retained separately by the manager on this runner'})
buf=io.StringIO()
with contextlib.redirect_stdout(buf):np.show_config()
print(json.dumps({'torch':str(torch.__version__),'numpy':np.__version__,'python':sys.version,'platform':platform.platform(),
 'torch_config':torch.__config__.show(),'numpy_config':buf.getvalue(),'initializations':rows,
 'training_executed':False,'prediction_executed':False,'encoder_executed':False},sort_keys=True))
'''
        phases.append(command([sys.executable, '-I', '-B', '-c', diagnostic, str(ADAPTER), str(INITIAL)],
                              output/'initial-checkpoint-identities', timeout=180))
        save(output/'DEPENDENCIES_AND_INITIALIZATION.json',
             json.loads((output/'initial-checkpoint-identities.stdout').read_bytes()))
        preparation = {'schema': 'hepta.memory.adapter-skill-ci-preparation.v1', 'scope': 'skill', 'request': request,
            'protocol_sha256': protocol_sha, 'initial_archive_sha256': ARCHIVE_SHA,
            'completed_at_monotonic_ns': time.monotonic_ns(), 'wall_ns': time.monotonic_ns()-started,
            'wrapper_own_cpu_ns': time.process_time_ns()-own_cpu, 'processes': list(phases),
            'completed_children_cpu_seconds': sum(p['completed_child_cpu_seconds'] for p in phases),
            'shared_encoder_reference_bytes': encoder['base_bytes'], 'encoder_sha256': encoder['base_encoder_sha'],
            'canonical_features': identity(INITIAL/'canonical.npz'), 'restored_evidence_bytes': archive['original_evidence_bytes'],
            'encoder_weights_downloaded_or_reencoded': False, 'held_artifacts_restored_as_opaque_archive_bytes': True,
            'held_json_parsed_or_supplied_to_training': False, 'historical_trainer_monotonic_compared_to_runner_clock': False,
            'historical_training_gate': 'verified original archive and successful historical process, restored before local launch',
            'source_clock_domains': 'historical source host separate; all new ordering uses this runner'}
        save(output/'PREPARATION.json', preparation)
        run_root.mkdir()
        monitor = REPO/'qualification'/'memory-cell-v9'/'learning'/'resource_monitor.py'
        argv = [sys.executable, '-I', '-B', str(monitor), '--root', str(run_root),
                '--output', str(run_root/'resource.json'), '--samples', str(run_root/'resource-samples.jsonl'),
                '--stdout', str(run_root/'driver.stdout'), '--stderr', str(run_root/'driver.stderr'),
                '--interval-ms', '200', '--timeout-seconds', '3600', '--', sys.executable, '-I', '-B',
                str(HERE/'manager.py'), '--output', str(run_root), '--python', sys.executable, '--initial-study', str(INITIAL)]
        lifecycle = command(argv, output/'lifecycle-monitor', timeout=3780, progress=run_root/'driver.stdout')
        result = json.loads((run_root/'RESULT.json').read_bytes())
        measured = json.loads((run_root/'resource.json').read_bytes())
        if (result['completed_cycles'] != 192 or result['phase_count'] != 216 or result['failures']
                or not result['all_preflight_passed'] or not result['all_readers_after_trainer_exit'] or not measured['passed']):
            raise ValueError('complete skill maintenance did not satisfy the frozen execution contract')
        phases.append(command(['git', '-C', str(REPO), 'diff', '--exit-code', '--',
            'qualification/memory-cell-adapters', '.github/workflows/memory-adapter-skill-longrun.yml'],
            output/'source-unchanged', timeout=60))
        save(output/'CI_RESULT.json', {'schema': 'hepta.memory.adapter-skill-ci-result.v1', 'scope': 'skill',
            'request': request, 'source_commit': commit, 'source_tree': tree, 'preparation': preparation,
            'lifecycle_launcher': lifecycle, 'result': identity(run_root/'RESULT.json'), 'resource': identity(run_root/'resource.json'),
            'completed_cycles': 192, 'completed_fit_phases': 216, 'fresh_reader_processes': 219,
            'source_unchanged': True, 'wrapper_wall_ns': time.monotonic_ns()-started,
            'wrapper_own_cpu_ns': time.process_time_ns()-own_cpu, 'disk_after': shutil.disk_usage(output)._asdict(),
            'native_runtime_executed': False, 'encoder_reexecuted': False,
            'same_hardware_as_semantic_run_claimed': False, 'full_cost_exact': False,
            'resource_limit': 'sampled intervals and kernel child accounting; preserve errors and endpoint gaps',
            'job_checkout_python_setup_cpu_cost': None, 'archive_and_upload_costs': 'separate packaging receipt and platform logs',
            'semantic_run_costs_replaced': False, 'scientific_superiority_claimed': False})
        print(json.dumps({'completed': True, 'scope': 'skill', 'cycles': 192, 'fit_phases': 216,
                          'output': str(output), 'full_cost_exact': False}), flush=True)
        return 0
    except Exception as error:
        save(output/'CI_FAILED.json', {'error': f'{type(error).__name__}: {error}',
            'wall_ns': time.monotonic_ns()-started, 'wrapper_own_cpu_ns': time.process_time_ns()-own_cpu,
            'native_runtime_executed': False, 'completed_preparation_processes': phases})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--request', type=Path, default=HERE/'RUN_REQUEST.json')
    parser.add_argument('--job-start-marker', type=Path)
    raise SystemExit(run(parser.parse_args()))
