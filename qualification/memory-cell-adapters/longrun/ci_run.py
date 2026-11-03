"""Prepare and run an unchanged-protocol clean cost replication on GitHub CI.

Preparation is accounted separately from the sampled maintenance lifecycle.
Historical monotonic timestamps are never compared with this runner's clock.
The original protocol, manager, fit worker and reader are not modified.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent
REPO = HERE.parents[2]
PROTOCOL_SHA = '3f7a09a1158b3e40cd33157e0da727deda13fa6654950b01449d419c6cb9a007'
FORMAL_ARCHIVE_SHA = 'ac5a13169fcad61eda46ee4e42c67e5549c82da48a32c1121e9727baa2ee706f'
INITIAL_STUDY = Path('/workspace/scratch/76e2020e4b36/memory-adapter-formal-01')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def save(path, value):
    path.write_bytes(encoded(value)+b'\n')


def identity(path):
    hasher, size = hashlib.sha256(), 0
    with path.open('rb') as source:
        while block := source.read(65536):
            hasher.update(block)
            size += len(block)
    return {'bytes': size, 'sha256': hasher.hexdigest()}


def text_file(path):
    try:
        return Path(path).read_text()
    except OSError as error:
        return {'unavailable': type(error).__name__}


def command(argv, stem, *, timeout=1200, progress=None):
    began, before = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out, progress_offset = False, 0
    with stem.with_suffix('.stdout').open('xb') as stdout, stem.with_suffix('.stderr').open('xb') as stderr:
        with subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True) as child:
            pid = child.pid
            while True:
                try:
                    child.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    if progress is not None and progress.exists():
                        with progress.open('rb') as live:
                            live.seek(progress_offset)
                            data = live.read()
                            progress_offset += len(data)
                        if data:
                            print(data.decode(errors='replace'), end='', flush=True)
                    if time.monotonic_ns()-began > timeout*1_000_000_000:
                        timed_out = True
                        os.killpg(pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=60)
                        except subprocess.TimeoutExpired:
                            os.killpg(pid, signal.SIGKILL)
                            child.wait()
                        break
    ended, after = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {'argv': argv, 'pid': pid, 'started_monotonic_ns': began, 'exited_monotonic_ns': ended,
               'exit_code': child.returncode, 'timed_out': timed_out, 'wall_ns': ended-began,
               'completed_child_cpu_seconds': after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
               'kernel_input_blocks': after.ru_inblock-before.ru_inblock,
               'kernel_output_blocks': after.ru_oublock-before.ru_oublock,
               'stdout': identity(stem.with_suffix('.stdout')), 'stderr': identity(stem.with_suffix('.stderr'))}
    save(stem.with_suffix('.process.json'), receipt)
    if child.returncode or timed_out:
        raise RuntimeError(f'command failed: {stem.name}; exit {child.returncode}; raw output preserved')
    return receipt


def run(args):
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    phases = []
    try:
        if os.environ.get('GITHUB_ACTIONS') != 'true' or sys.version_info[:2] != (3, 12):
            raise ValueError('this entry requires GitHub Actions with the registered Python 3.12')
        request = json.loads(args.request.read_bytes())
        fields = {'schema', 'request_id', 'protocol_sha256', 'initial_archive_sha256'}
        if (set(request) != fields or request['schema'] != 'hepta.memory.adapter-longrun-request.v1'
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', request['request_id'])
                or request['protocol_sha256'] != PROTOCOL_SHA or request['initial_archive_sha256'] != FORMAL_ARCHIVE_SHA):
            raise ValueError('request differs from the fixed clean-replication contract')
        protocol_path = HERE/'LONGRUN_PROTOCOL.json'
        if identity(protocol_path)['sha256'] != PROTOCOL_SHA or (HERE/'LONGRUN_PROTOCOL.sha256').read_text().strip() != PROTOCOL_SHA:
            raise ValueError('frozen protocol changed')
        protocol = json.loads(protocol_path.read_bytes())
        if Path(protocol['initial_study']) != INITIAL_STUDY:
            raise ValueError('registered absolute initial-study path changed')
        save(output/'REQUEST.json', request)
        save(output/'PATHS.json', {'repo_root': str(REPO), 'adapter_root': str(ADAPTER), 'output_root': str(output),
                                 'run_root': str(output/'run-03-clean'), 'initial_study': str(INITIAL_STUDY),
                                 'audit_rule': 'declare exact prefix mappings after download; never rewrite raw requests or receipts'})
        marker = None
        if args.job_start_marker is not None and args.job_start_marker.exists():
            shutil.copyfile(args.job_start_marker, output/'JOB_START.json')
            marker = json.loads(args.job_start_marker.read_bytes())
        hardware = {'schema': 'hepta.memory.adapter-ci-hardware.v1', 'platform': platform.platform(),
                    'machine': platform.machine(), 'uname': list(platform.uname()), 'logical_cpus': os.cpu_count(),
                    'python': sys.version, 'executable': sys.executable,
                    'os_release': text_file('/etc/os-release'), 'cpuinfo': text_file('/proc/cpuinfo'),
                    'meminfo': text_file('/proc/meminfo'), 'cpu_max': text_file('/sys/fs/cgroup/cpu.max'),
                    'memory_max': text_file('/sys/fs/cgroup/memory.max'), 'boot_id': text_file('/proc/sys/kernel/random/boot_id'),
                    'disk_before': shutil.disk_usage(output)._asdict(),
                    'environment': {key: os.environ.get(key) for key in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion',
                                     'GITHUB_SHA', 'GITHUB_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REPOSITORY')},
                    'same_hardware_as_local_run_claimed': False}
        if marker is not None and marker.get('boot_id') == hardware['boot_id']:
            hardware['job_pre_wrapper_wall_ns'] = started-marker['monotonic_ns']
        else:
            hardware['job_pre_wrapper_wall_ns'] = None
        save(output/'HARDWARE.json', hardware)
        pip = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir']
        phases.append(command(pip+['--index-url', 'https://pypi.org/simple', 'numpy==2.3.5'], output/'install-numpy'))
        phases.append(command(pip+['--index-url', 'https://download.pytorch.org/whl/cpu', 'torch==2.8.0+cpu'], output/'install-torch'))
        phases.append(command([sys.executable, '-m', 'pip', 'freeze', '--all'], output/'pip-freeze'))
        parent = INITIAL_STUDY.parent
        if any(p.is_symlink() for p in (parent, *parent.parents)) or INITIAL_STUDY.exists():
            raise ValueError('new nonsymlink initial-study destination required')
        if parent.exists():
            if not parent.is_dir() or any(parent.iterdir()) or not os.access(parent, os.W_OK):
                raise ValueError('existing initial-study parent must be empty and writable')
        else:
            phases.append(command(['sudo', '-n', 'install', '-d', '-m', '0755', '-o', str(os.getuid()), '-g', str(os.getgid()), str(parent)],
                                  output/'create-initial-parent', timeout=60))
        archive_root = ADAPTER/'evidence'/'formal-01'
        archive = json.loads((archive_root/'ARCHIVE.json').read_bytes())
        if archive['archive']['sha256'] != FORMAL_ARCHIVE_SHA:
            raise ValueError('published initial evidence archive changed')
        phases.append(command([sys.executable, '-I', '-B', str(archive_root/'restore.py'), str(INITIAL_STUDY)], output/'restore-formal', timeout=300))
        training = json.loads((INITIAL_STUDY/'models'/'TRAINING.json').read_bytes())
        historical_process = json.loads((INITIAL_STUDY/'training.process.json').read_bytes())
        encoder = json.loads((INITIAL_STUDY/'development-encoder.json').read_bytes())
        if historical_process['exit_code'] != 0 or historical_process['pid'] != training['pid'] or historical_process['timed_out']:
            raise ValueError('historical training receipt is not a completed successful process')
        if encoder['base_encoder_sha'] != training['encoder_sha']:
            raise ValueError('initial encoder identities differ')
        for name in ('sources.json', 'canonical.npz', 'models/TRAINING.json', 'training.process.json', 'development-encoder.json'):
            if identity(INITIAL_STUDY/name) != archive['files'][name]:
                raise ValueError('restored training input identity mismatch')
        diagnostic = r'''import contextlib,io,json,pathlib,platform,sys
import numpy as np,torch
root,initial=map(pathlib.Path,sys.argv[1:])
sys.path.insert(0,str(root))
from tensor_cell import CellConfig,OutputSpec,TensorCell
if torch.__version__!='2.8.0+cpu' or np.__version__!='2.3.5' or torch.version.cuda is not None:
 raise ValueError('pinned CPU dependency contract differs')
torch.set_num_threads(1)
torch.use_deterministic_algorithms(True)
rows=[]
for seed in (731,732,733):
 manifest=json.loads((initial/'models'/f'seed-{seed}'/'semantic'/'manifest.json').read_bytes())
 c=manifest['config']
 cell=TensorCell(CellConfig('ci-clean-initialization',rank=c['rank'],input_dim=c['input_dim'],outputs=tuple(OutputSpec(**s) for s in c['outputs']),seed=seed),manifest['base_encoder_sha'])
 loaded=TensorCell.load(initial/'models'/f'seed-{seed}'/'semantic',manifest['base_encoder_sha'])
 rows.append({'seed':seed,'fresh_parameter_sha256':cell.parameter_digest(),'initial_checkpoint_sha256':loaded.parameter_digest(),'architecture':c,'base_encoder_sha':manifest['base_encoder_sha'],'parameter_counts':cell.parameter_counts()})
buf=io.StringIO()
with contextlib.redirect_stdout(buf):np.show_config()
print(json.dumps({'torch':str(torch.__version__),'numpy':np.__version__,'python':sys.version,'platform':platform.platform(),'torch_config':torch.__config__.show(),'numpy_config':buf.getvalue(),'initializations':rows,'training_executed':False,'prediction_executed':False,'encoder_executed':False,'cross_hardware_parameter_equality_is_not_a_gate':True},sort_keys=True))
'''
        phases.append(command([sys.executable, '-I', '-B', '-c', diagnostic, str(ADAPTER), str(INITIAL_STUDY)], output/'local-initializations', timeout=180))
        initialization = json.loads((output/'local-initializations.stdout').read_bytes())
        save(output/'DEPENDENCIES_AND_INITIALIZATION.json', initialization)
        preparation = {'schema': 'hepta.memory.adapter-ci-preparation.v1', 'request': request,
                       'protocol_sha256': PROTOCOL_SHA, 'initial_archive_sha256': FORMAL_ARCHIVE_SHA,
                       'completed_at_monotonic_ns': time.monotonic_ns(), 'wall_ns': time.monotonic_ns()-started,
                       'wrapper_own_cpu_ns': time.process_time_ns()-cpu, 'processes': list(phases),
                       'completed_children_cpu_seconds': sum(p['completed_child_cpu_seconds'] for p in phases),
                       'shared_encoder_reference_bytes': encoder['base_bytes'], 'encoder_sha256': encoder['base_encoder_sha'],
                       'canonical_features': identity(INITIAL_STUDY/'canonical.npz'), 'restored_evidence_bytes': archive['original_evidence_bytes'],
                       'encoder_weights_downloaded_or_reencoded': False,
                       'held_artifacts_restored_as_opaque_archive_bytes': True, 'held_json_parsed_or_supplied_to_training': False,
                       'historical_trainer_monotonic_compared_to_runner_clock': False,
                       'historical_training_gate': 'immutable verified archive and successful source process receipt restored before local launch',
                       'source_clock_domains': 'historical training receipt belongs to original host; local process ordering uses this runner only'}
        save(output/'PREPARATION.json', preparation)
        run_root = output/'run-03-clean'
        run_root.mkdir()
        monitor = REPO/'qualification'/'memory-cell-v9'/'learning'/'resource_monitor.py'
        argv = [sys.executable, '-I', '-B', str(monitor), '--root', str(run_root), '--output', str(run_root/'resource.json'),
                '--samples', str(run_root/'resource-samples.jsonl'), '--stdout', str(run_root/'driver.stdout'), '--stderr', str(run_root/'driver.stderr'),
                '--interval-ms', '200', '--timeout-seconds', '3600', '--', sys.executable, '-I', '-B', str(HERE/'manager.py'),
                '--output', str(run_root), '--python', sys.executable]
        lifecycle = command(argv, output/'lifecycle-monitor', timeout=3780, progress=run_root/'driver.stdout')
        result = json.loads((run_root/'RESULT.json').read_bytes())
        resource_receipt = json.loads((run_root/'resource.json').read_bytes())
        if (result['completed_cycles'] != 192 or result['phase_count'] != 216 or result['failures']
                or not result['all_preflight_passed'] or not result['all_readers_after_trainer_exit'] or not resource_receipt['passed']):
            raise ValueError('complete fixed-horizon replication did not satisfy its execution contract')
        phases.append(command(['git', '-C', str(REPO), 'diff', '--exit-code', '--', 'qualification/memory-cell-adapters',
                               '.github/workflows/memory-adapter-longrun.yml'], output/'source-unchanged', timeout=60))
        summary = {'schema': 'hepta.memory.adapter-ci-clean-replication.v1', 'request': request,
                   'source_commit': os.environ.get('GITHUB_SHA'), 'preparation': preparation,
                   'lifecycle_launcher': lifecycle, 'result': identity(run_root/'RESULT.json'), 'resource': identity(run_root/'resource.json'),
                   'completed_cycles': 192, 'completed_fit_phases': 216, 'fresh_reader_processes': 219,
                   'source_unchanged': True, 'wrapper_wall_ns': time.monotonic_ns()-started, 'wrapper_own_cpu_ns': time.process_time_ns()-cpu,
                   'disk_after': shutil.disk_usage(output)._asdict(), 'native_runtime_executed': False,
                   'same_hardware_as_local_run_claimed': False, 'encoder_reexecuted': False,
                   'original_interrupted_costs_replaced': False, 'research_total_must_include_both_executions_and_original_unknowns': True,
                   'full_cost_exact': False, 'resource_limit': 'sampled intervals and kernel child accounting; preserve sampling errors and endpoint gaps',
                   'job_checkout_python_setup_cpu_cost': None, 'archive_and_upload_costs': 'separate always-run workflow packaging receipt and platform logs'}
        save(output/'CI_RESULT.json', summary)
        print(json.dumps({'completed': True, 'cycles': 192, 'fit_phases': 216, 'output': str(output), 'full_cost_exact': False}), flush=True)
        return 0
    except Exception as error:
        save(output/'CI_FAILED.json', {'error': f'{type(error).__name__}: {error}', 'wall_ns': time.monotonic_ns()-started,
                                      'wrapper_own_cpu_ns': time.process_time_ns()-cpu, 'native_runtime_executed': False,
                                      'completed_preparation_processes': phases})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--request', type=Path, default=HERE/'LONGRUN_REQUEST.json')
    parser.add_argument('--job-start-marker', type=Path)
    raise SystemExit(run(parser.parse_args()))
