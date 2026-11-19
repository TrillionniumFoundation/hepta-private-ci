#!/usr/bin/env python3
"""Single-owner, fail-closed full-budget desktop CUDA campaign.

This controller installs nothing, changes no runner configuration, and never
retries a training attempt automatically. All research children are sequential.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import itertools
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback

from contracts import (BASE_MAP, CANDIDATE_MAP, CANDIDATE_TEST_COUNT, GPU_UUID, MAMBA_MANIFEST,
                       REMAT_CONFIG, TORCH_MANIFEST, canonical_sha, execution_config,
                       read_json, require, sha, summarize_matrix, validate_checks,
                       validate_parity, validate_probe, validate_source)


def now():
    return datetime.now(timezone.utc).isoformat()


def publish(path, value, *, replace=False):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        if replace:
            os.replace(temp, path)
        else:
            os.link(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Campaign:
    def __init__(self, args):
        self.args = args
        self.root, self.bundle = args.task_root.resolve(), Path(__file__).resolve().parent
        self.candidate = self.bundle/'candidate'
        self.output = args.output_dir.resolve()
        self.python = self.root/'.venv/bin/python'
        self.setup = self.root/'envsetup'
        self.child = None
        self.report = dict(schema='hcsn-gated-cuda-campaign-v2', status='initializing',
                           started_utc=now(), pid=os.getpid(), stages=[],
                           completed_cuda_runs=0, requested_cuda_runs=170,
                           global_qualification='open', source_branch_ci_not_claimed=True,
                           no_automatic_training_retries=True,
                           budget_change_permitted=False,
                           physical_energy_missing_is_not_zero=True)
        require(self.root.is_dir() and self.root != self.output, 'invalid task root/output')
        require(self.output.is_relative_to(self.root/'campaigns'), 'campaign output outside isolated task')
        require(sha(self.bundle/'MANIFEST.json') == args.manifest_sha256, 'campaign manifest mismatch')
        self.manifest = read_json(self.bundle/'MANIFEST.json')
        self.verify_sources()
        self.campaign_lock = (self.setup/'campaign.lock').open('a+b')
        fcntl.flock(self.campaign_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.install_lock = None
        self.output.parent.mkdir(exist_ok=True)
        self.output.mkdir()  # Atomic one-owner claim; never reuse an existing campaign directory.
        publish(self.output/'claim.json', dict(pid=os.getpid(), started_utc=now(),
                manifest_sha256=args.manifest_sha256,
                campaign_sha256=sha(__file__), task_root=str(self.root)))
        self.environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0',
            PYTHONNOUSERSITE='1',
            CUBLAS_WORKSPACE_CONFIG=':4096:8', CUDA_VISIBLE_DEVICES=GPU_UUID,
            OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
            TRITON_CACHE_DIR=str(self.root/'runtime-cache/triton'),
            CUDA_CACHE_PATH=str(self.root/'runtime-cache/cuda'),
            TORCHINDUCTOR_CACHE_DIR=str(self.root/'runtime-cache/inductor'),
            TORCH_EXTENSIONS_DIR=str(self.root/'runtime-cache/extensions'),
            XDG_CACHE_HOME=str(self.root/'runtime-cache/xdg'),
            TMPDIR=str(self.root/'runtime-cache/tmp'))
        self.environment.pop('PYTHONPATH', None)
        for key in ('TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TORCHINDUCTOR_CACHE_DIR',
                    'TORCH_EXTENSIONS_DIR', 'XDG_CACHE_HOME', 'TMPDIR'):
            Path(self.environment[key]).mkdir(parents=True, exist_ok=True)
        self.base_config = read_json(self.root/'qualification/hcsn/configs/full.json')
        publish(self.output/'predeclared-plan.json', dict(
            original_config=self.base_config,
            matrix=list(itertools.product(self.base_config['tasks'], self.base_config['models'], self.base_config['seeds'])),
            b_policy='0 if original full-shape B succeeds; 1 only after original graph OOM and fixed CPU/CUDA parity',
            policy_applies_uniformly_to_all_20_b_identities=True,
            predeclared_execution_config_sha256={
                '0': '124969205d3e1c69c8707f20415c887447d0fe2e19975df698d790a0c6a58016',
                '1': REMAT_CONFIG},
            cuda_allocator_fraction=0.5, minimum_free_disk_bytes=5*1024**3,
            minimum_control_filesystem_free_bytes=1024**3,
            selection_uses_task_quality=False, physical_gpu_energy_required_for_energy_claim=True,
            optional_legacy_diagnostic_does_not_select_models=True,
            runtime_environment={k:self.environment[k] for k in ('PYTHONHASHSEED', 'CUBLAS_WORKSPACE_CONFIG',
                 'CUDA_VISIBLE_DEVICES', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'TRITON_CACHE_DIR',
                 'CUDA_CACHE_PATH', 'TORCHINDUCTOR_CACHE_DIR', 'TORCH_EXTENSIONS_DIR', 'XDG_CACHE_HOME', 'TMPDIR')},
            precision='FP32 tensors; PyTorch highest matmul precision and TF32 disabled; custom Triton behavior recorded separately',
            runtime_wait_seconds=args.runtime_wait_seconds))
        self.progress()

    def verify_sources(self):
        for relative, expected in self.manifest['bundle_files_sha256'].items():
            path = self.bundle/relative
            require(path.resolve().is_relative_to(self.bundle) and sha(path) == expected,
                    f'bundle changed: {relative}')
        for relative, expected in self.manifest['task_files_sha256'].items():
            path = self.root/relative
            require(path.resolve().is_relative_to(self.root) and sha(path) == expected,
                    f'staged original tool changed: {relative}')
        validate_source(self.root, BASE_MAP)
        validate_source(self.candidate, CANDIDATE_MAP)

    def progress(self):
        self.report.update(updated_utc=now(), disk_free_bytes=shutil.disk_usage(self.root).free,
                           control_filesystem_free_bytes=shutil.disk_usage(Path.home()).free)
        run_dir = self.output/'full.runs'
        if run_dir.exists():
            counts = dict(completed=0, failed=0, unavailable=0)
            for p in run_dir.glob('*.json'):
                try:
                    state = read_json(p).get('result', {}).get('status')
                    if state in counts:
                        counts[state] += 1
                except (ValueError, OSError):
                    continue
            self.report['registered_run_indexes_observed'] = counts
            self.report['completed_cuda_runs'] = counts['completed']
        publish(self.output/'progress.json', self.report, replace=True)

    def disk_gate(self):
        free = shutil.disk_usage(self.root).free
        require(free >= 5*1024**3, f'isolated volume below 5 GiB reserve: {free} bytes free')
        control_free = shutil.disk_usage(Path.home()).free
        require(control_free >= 1024**3,
                f'runtime control filesystem below 1 GiB reserve: {control_free} bytes free')

    def runtime_ready(self):
        torch_path, mamba_path = self.setup/'TORCH_READY.json', self.setup/'MAMBA_READY.json'
        if not (torch_path.is_file() and mamba_path.is_file()):
            return False
        require(sha(self.setup/'torch-wheel-manifest.json') == TORCH_MANIFEST
                and sha(self.setup/'mamba-wheel-manifest.json') == MAMBA_MANIFEST,
                'official wheel manifests changed')
        t, m = read_json(torch_path), read_json(mamba_path)
        require(t.get('state') == 'ready' and t.get('manifest_sha256') == TORCH_MANIFEST
                and m.get('state') == 'imports_ready' and m.get('manifest_sha256') == MAMBA_MANIFEST
                and m.get('torch_manifest_sha256') == TORCH_MANIFEST, 'runtime READY identity mismatch')
        require(t.get('python') == str(self.python) and m.get('python') == str(self.python),
                'READY refers to another interpreter')
        require(t.get('availability_sha256') == sha(self.setup/'torch-availability.json')
                and m.get('availability_sha256') == sha(self.setup/'mamba-import-availability.json'),
                'runtime availability receipts do not match READY')
        return True

    def wait_for_runtime(self):
        self.report['status'] = 'waiting_for_pinned_runtime'
        began = time.monotonic()
        while not self.runtime_ready():
            require(time.monotonic()-began < self.args.runtime_wait_seconds,
                    'runtime deadline elapsed; CUDA training was not started')
            self.disk_gate()
            self.progress()
            time.sleep(30)
        self.report['runtime_ready_receipts'] = {p.name: sha(p) for p in
            (self.setup/'TORCH_READY.json', self.setup/'MAMBA_READY.json')}
        self.progress()

    def stop_owned_child(self):
        if self.child is None or self.child.poll() is not None:
            return
        os.killpg(self.child.pid, signal.SIGTERM)
        try:
            self.child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(self.child.pid, signal.SIGKILL)
            self.child.wait(timeout=10)

    def stage(self, name, root, device, arguments, *, module=None, script=None, allowed_codes=(0,)):
        self.verify_sources()
        self.disk_gate()
        require(module is not None or script is not None, 'stage has no target')
        result_path = self.output/(name+'.json')
        profile = self.output/(name+'.runtime.json')
        require(not result_path.exists(), 'stage receipt already exists')
        cmd = [str(self.python), '-B', str(self.bundle/'runtime_entry.py'), '--repo-root', str(root),
               '--device', device, '--profile', str(profile)]
        cmd += ['--module', module] if module else ['--script', str(script)]
        cmd += ['--', *map(str, arguments), '--output', str(result_path)]
        record = dict(name=name, started_utc=now(), command=cmd, status='running')
        self.report.update(status='running', active_stage=name)
        self.report['stages'].append(record)
        self.progress()
        publish(self.output/(name+'.started.json'), record)
        with (self.output/(name+'.stdout.log')).open('xb') as stdout, \
                (self.output/(name+'.stderr.log')).open('xb') as stderr:
            self.child = subprocess.Popen(cmd, cwd=root, env=self.environment,
                                          stdout=stdout, stderr=stderr, start_new_session=True,
                                          pass_fds=(self.campaign_lock.fileno(), self.install_lock.fileno()))
            record.update(child_pid=self.child.pid, child_process_group=self.child.pid)
            publish(self.output/(name+'.launched.json'), record)
            try:
                while self.child.poll() is None:
                    self.disk_gate()
                    self.progress()
                    time.sleep(15)
                code = self.child.returncode
            finally:
                self.stop_owned_child()
                self.child = None
        record.update(exit_code=code, finished_utc=now(), status='returned',
                      result_sha256=sha(result_path) if result_path.is_file() else None)
        terminal = read_json(profile.with_suffix('.terminal.json'))
        require(terminal.get('runtime_unchanged') is True
                and terminal.get('runtime_profile_sha256') == sha(profile), 'runtime integrity failed')
        self.verify_sources()
        publish(self.output/(name+'.finished.json'), record)
        self.progress()
        require(code in allowed_codes, f'{name} returned {code}; inspect immutable receipt/logs')
        return read_json(result_path), profile, code

    def execute(self):
        self.wait_for_runtime()
        # Installers use LOCK_EX on this same file. Hold shared ownership through all experiments.
        with (self.setup/'install.lock').open('a+b') as install_lock:
            self.install_lock = install_lock
            lock_wait = time.monotonic()
            while True:
                try:
                    fcntl.flock(install_lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic()-lock_wait < 300, 'installer retained environment lock after READY')
                    self.report['status'] = 'waiting_for_installer_lock_release'
                    self.progress()
                    time.sleep(5)
            require(self.runtime_ready(), 'runtime changed while acquiring environment lock')
            self.verify_sources()
            for name, root, count in (('baseline-strict-tests', self.root, 95),
                                      ('candidate-strict-tests', self.candidate, CANDIDATE_TEST_COUNT)):
                result, _, _ = self.stage(name, root, 'cpu', ['--require-torch'], module='qualification.hcsn.checks')
                validate_checks(result, count, root)
            preflight = self.root/'experiments/cuda_probe_v2.py'
            common = ['--repo-root', self.root, '--device', 'cuda:0', '--max-memory-fraction', '0.5',
                      '--task', 'delayed_recall', '--seed', '0']
            a, _, _ = self.stage('original-a-fullshape', self.root, 'cuda:0',
                                  common+['--model', 'hx_dual'], script=preflight)
            validate_probe(a, 'hx_dual')
            b, _, _ = self.stage('original-b-fullshape', self.root, 'cuda:0',
                                  common+['--model', 'population_flux'], script=preflight, allowed_codes=(0, 1))
            b_outcome = validate_probe(b, 'population_flux', permit_oom=True)
            policy = 1 if b_outcome == 'original_b_oom' else 0
            if policy == 1:
                remat_root = self.root/'experiments/remat_candidate'
                for device, name in (('cpu', 'parity-cpu'), ('cuda:0', 'parity-cuda')):
                    parity, _, _ = self.stage(name, self.root, device,
                         ['--repo-root', self.root, '--device', device], script=remat_root/'check_rematerialization.py')
                    validate_parity(parity, device)
                for model in ('population_flux', 'population_flux_no_recovery'):
                    result, _, _ = self.stage('candidate-fullshape-'+model, self.root, 'cuda:0',
                         common+['--model', model, '--remat-root', remat_root],
                         script=self.root/'experiments/cuda_probe_rematerialized_v1.py')
                    validate_probe(result, model, rematerialized=True)
            mamba, _, _ = self.stage('original-mamba2-fullshape', self.root, 'cuda:0',
                                    common+['--model', 'mamba2'], script=preflight)
            validate_probe(mamba, 'mamba2')
            selected = dict(self.base_config, population_checkpoint_steps=policy, cuda_memory_fraction=0.5)
            execution_config(self.base_config, selected, policy)
            config_path = self.output/'execution-config.json'
            publish(config_path, selected)
            if policy == 1:
                require(sha(config_path) == REMAT_CONFIG, 'policy 1 serialization differs from frozen config')
            publish(self.output/'admission.json', dict(status='admitted', selected_policy=policy,
                config_sha256=sha(config_path), admitted_utc=now(), selection_uses_heldout=False,
                original_b_outcome=b_outcome, applies_to_all_b_runs=20,
                gate_receipts={s['name']:sha(self.output/(s['name']+'.json')) for s in self.report['stages']}))
            # Preserve cross-platform legacy replay as a separate diagnostic; it cannot select a policy.
            smoke = self.root/'experiments/b_smoke_separable_v1/numeric-audit'
            legacy, _, _ = self.stage('legacy-smoke-separable', self.root, 'cpu',
                ['--repo-root', self.root, '--benchmark', smoke/'smoke-replay/smoke.json'],
                script=smoke/'audit_population_separable.py', allowed_codes=(0, 1, 2))
            self.report['legacy_smoke_diagnostic_status'] = legacy.get('status')
            matrix, profile, _ = self.stage('full', self.candidate, 'cuda:0',
                ['--config', config_path], module='qualification.hcsn.benchmark', allowed_codes=(0, 1, 2))
            counts = summarize_matrix(matrix, selected, self.candidate, self.output/'full.runs')
            self.report.update(matrix_accounting=counts, completed_cuda_runs=counts['completed'])
            sidecar = self.output/'full.runtime-manifest.json'
            publish(sidecar, dict(schema='hcsn-benchmark-runtime-link-v1', benchmark_sha256=sha(self.output/'full.json'),
                runtime_profile_sha256=sha(profile), execution_config_sha256=sha(config_path),
                runtime_terminal_sha256=sha(profile.with_suffix('.terminal.json')),
                admission_sha256=sha(self.output/'admission.json'), campaign_manifest_sha256=self.args.manifest_sha256))
            audit, _, _ = self.stage('full-b-audit', self.candidate, 'cuda:0',
                ['--repo-root', self.candidate, '--benchmark', self.output/'full.json',
                 '--execution-config', config_path, '--runtime-profile', profile,
                 '--benchmark-runtime-manifest', sidecar,
                 '--launch-runtime-profile', self.output/'full-b-audit.runtime.json',
                 '--launch-runtime-entry', self.bundle/'runtime_entry.py'], script=self.bundle/'audit_full_population.py',
                allowed_codes=(0, 1, 2))
            self.report.update(status='executed', full_b_audit_status=audit.get('status'),
                               finished_utc=now(), global_qualification='open',
                               resolution_independence_established=False,
                               ci_pass_established_by_this_job=False)
            self.verify_sources()
            self.progress()
            publish(self.output/'terminal.json', self.report)
            return 0 if counts['completed'] == 170 and audit.get('status') == 'completed' else 2


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task-root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--runtime-wait-seconds', type=int, default=86400)
    args = p.parse_args()
    require(0 < args.runtime_wait_seconds <= 86400, 'runtime deadline out of bounds')
    campaign = Campaign(args)
    def stop(signum, frame):
        raise InterruptedError(f'campaign received signal {signum}')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        return campaign.execute()
    except BaseException as exc:
        campaign.stop_owned_child()
        campaign.report.update(status='interrupted' if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 'blocked',
                               reason=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc(),
                               finished_utc=now(), global_qualification='open')
        campaign.progress()
        publish(campaign.output/'terminal.json', campaign.report)
        print(json.dumps(dict(status=campaign.report['status'], reason=campaign.report['reason'])), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
