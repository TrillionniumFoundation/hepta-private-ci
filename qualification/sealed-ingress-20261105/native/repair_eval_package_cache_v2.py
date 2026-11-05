#!/usr/bin/env python3
"""Archive the obsolete task eval unit, then invalidate this package's task cache."""
import fcntl
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import time

TASK = pathlib.Path('/home/qq/work/hepta-convergence-20261105-0c901b')
SOURCE = TASK / 'source-next'
TARGET = TASK / 'target'
BUNDLE = TASK / 'native-sealed-gate-v2'
HEAD = 'eed6541df0add428add8e2d9ab2cbd54a961abeb'
TREE = 'b8ce8b96a759f522cb7db60027d4844f1b3ad974'
RUNNER_SHA = '46552f047784d07b825cec59e0358cfbb02a010f448b7538bb0fadc15ea2f7df'
ORIGINALS = {
    'native-eval-cache-repair-v1/receipt.json': 'a82a65e07f6007cacaafe4d9673df766be65d85f43f34ed933a4c1008d95fc2e',
    'native-q3-cache-diagnostic-v1.json': '843939f2a6ae4e35f8a330cd58d1e24fa2d0634532686952422344e407ceb93d',
    'native-sealed-red-q-plasticity-v1/receipt.json': 'b98653f5a06015cb71042b642ed1df3efb08e0384c9cc350294f7e86dfd70a49',
    'native-sealed-remaining-pipeline-v1/receipt.json': 'ea4e3ea5a557c3b8951a11263f03e5e25061deb2159be025ae105ed75e0ea68c',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def inspect_target_users(target):
    """Expose only selected target options; never print complete argv/environment."""
    active = []

    def option_values(argv, option):
        values = []
        for index, value in enumerate(argv):
            if value == option:
                values.append(argv[index + 1] if index + 1 < len(argv) else None)
            elif value.startswith(option + '='):
                values.append(value[len(option) + 1:])
        return values

    def resolve(cwd, value):
        if value is None or not value:
            return None
        return (pathlib.Path(cwd) / value).resolve()

    def overlaps(path):
        return path == target or target in path.parents or path in target.parents

    for proc in pathlib.Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        name = None
        try:
            name = (proc / 'comm').read_text().strip()
            if name not in {'cargo', 'cargo-nextest', 'rustc', 'clippy-driver'}:
                continue
            cwd = str((proc / 'cwd').resolve(strict=True))
            env_values = [x.split(b'=', 1)[1].decode() for x in (proc / 'environ').read_bytes().split(b'\0')
                          if x.startswith(b'CARGO_TARGET_DIR=')]
            argv = [x.decode() for x in (proc / 'cmdline').read_bytes().split(b'\0') if x]
            selected_option = '--target-dir' if name in {'cargo', 'cargo-nextest'} else '--out-dir'
            arg_values = option_values(argv, selected_option)
            row = {'pid': int(proc.name), 'comm': name, 'cwd': cwd,
                   'CARGO_TARGET_DIR': env_values[0] if len(env_values) == 1 else None,
                   'selected_option': selected_option, 'selected_values': arg_values,
                   'classification': 'unknown-target'}
            if len(env_values) > 1 or len(arg_values) > 1:
                active.append(row)
                continue
            env_target = resolve(cwd, env_values[0]) if env_values else None
            arg_target = resolve(cwd, arg_values[0]) if arg_values else None
            if name in {'cargo', 'cargo-nextest'}:
                effective = arg_target if arg_values else env_target
                row['resolved_effective_target'] = str(effective) if effective else None
                if effective is not None:
                    row['classification'] = 'task-target-overlap' if overlaps(effective) else 'explicitly-different-target'
            else:
                row['resolved_environment_target'] = str(env_target) if env_target else None
                row['resolved_output_directory'] = str(arg_target) if arg_target else None
                known = [x for x in [env_target, arg_target] if x is not None]
                if any(overlaps(x) for x in known):
                    row['classification'] = 'task-target-overlap'
                elif arg_target is not None:
                    row['classification'] = 'explicitly-different-target'
            active.append(row)
        except FileNotFoundError:
            continue
        except (OSError, RuntimeError, UnicodeError) as error:
            active.append({'pid': int(proc.name), 'comm': name, 'classification': 'unknown-target',
                           'read_error_type': type(error).__name__})
    return active


def main():
    evidence = TASK / 'evidence/native-eval-cache-repair-v2'
    evidence.mkdir(exist_ok=False)
    receipt = {'schema': 'hepta.task-eval-cache-repair.v1', 'state': 'preflight', 'source': str(SOURCE),
               'head': HEAD, 'tree': TREE, 'target': str(TARGET), 'steps': [], 'backup': [],
               'script_sha256': sha(pathlib.Path(__file__).read_bytes()), 'original_evidence': ORIGINALS,
               'source_features_profiles_budgets_changed': False, 'tests_executed_by_repair': False}
    lock = None
    env = None

    def save():
        tmp = evidence / 'receipt.json.tmp'
        tmp.write_text(json.dumps(receipt, indent=2) + '\n')
        tmp.replace(evidence / 'receipt.json')

    def run(name, argv):
        started = time.time()
        result = subprocess.run(argv, cwd=SOURCE / 'codex-rs', env=env, capture_output=True)
        for kind, data in [('stdout', result.stdout), ('stderr', result.stderr)]:
            (evidence / (name + '.' + kind)).write_bytes(data)
        receipt['steps'].append({'name': name, 'argv': argv, 'exit_code': result.returncode,
                                 'elapsed_seconds': time.time() - started,
                                 'stdout_sha256': sha(result.stdout), 'stderr_sha256': sha(result.stderr)})
        save()
        need(result.returncode == 0, name + ' failed')
        return result.stdout

    def source_check(suffix):
        identity = run('source-identity-' + suffix, ['git', 'rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines()
        need(identity == [HEAD, TREE], 'Source identity differs')
        status = run('source-clean-' + suffix, ['git', 'status', '--porcelain=v1', '--untracked-files=all'])
        need(status == b'', 'Source is not clean')
        return sha((SOURCE / 'codex-rs/Cargo.lock').read_bytes())

    try:
        save()
        runner = BUNDLE / 'run_native_round2.py'
        need(sha(runner.read_bytes()) == RUNNER_SHA, 'Frozen runner differs')
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('frozen_native_environment', runner)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env, receipt['verified_environment'] = module.native_environment()
        need(pathlib.Path(env['CARGO_TARGET_DIR']).resolve() == TARGET.resolve() == TARGET,
             'CARGO_TARGET_DIR must resolve to the exact task-owned target')
        lock = (TASK / 'evidence/native-sealed-validation.lock').open('a+b')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = inspect_target_users(TARGET)
        receipt['process_guard_scope'] = 'exact-task-target'
        receipt['active_cargo_or_compiler_processes'] = active
        conflicts = [x for x in active if x['classification'] != 'explicitly-different-target']
        receipt['target_conflicting_or_unknown_processes'] = conflicts
        save()
        need(not conflicts, 'A Cargo/compiler process may use this task target; cleanup refused')
        versions = run('rustc-version', ['rustc', '-Vv']).decode()
        need(versions.startswith('rustc 1.96.0 '), 'Pinned toolchain differs')
        receipt['rustc_version'] = versions
        before_lock = source_check('before')
        receipt['cargo_lock_sha256'] = before_lock
        for rel, expected in ORIGINALS.items():
            need(sha((TASK / 'evidence' / rel).read_bytes()) == expected, 'Original evidence differs: ' + rel)
        diagnostic = json.loads((TASK / 'evidence/native-q3-cache-diagnostic-v1.json').read_text())
        old = next(x for x in diagnostic['fingerprints'] if x['path'].endswith('/codex-hepta-intelligence-eval-fcbed105465cd5d7'))
        items = old['files'] + [x for x in diagnostic['depinfo'] + diagnostic['artifacts']
                                if 'fcbed105465cd5d7' in x['path']]
        for item in items:
            original = pathlib.Path(item['path'])
            relative = original.relative_to(TARGET)
            need(original.resolve() == TARGET / relative and not original.is_symlink(), 'Unexpected cache path')
            need(sha(original.read_bytes()) == item['sha256'], 'Old cache differs before archive')
            backup = evidence / 'obsolete-unit' / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, backup)
            need(sha(backup.read_bytes()) == item['sha256'], 'Archive copy differs')
            receipt['backup'].append({'original': str(original), 'backup': str(backup),
                                      'size': original.stat().st_size, 'sha256': item['sha256']})
        receipt['state'] = 'obsolete-unit-archived'
        save()
        run('clean-eval-package', ['cargo', 'clean', '-p', 'codex-hepta-intelligence-eval'])
        receipt['clean_finished_unix_ns'] = time.time_ns()
        receipt['old_unit_paths_absent'] = all(not pathlib.Path(x['original']).exists() for x in receipt['backup'])
        need(receipt['old_unit_paths_absent'], 'Obsolete unit remains after package cleanup')
        need(source_check('after') == before_lock, 'Cargo.lock changed during cache cleanup')
        for rel, expected in ORIGINALS.items():
            need(sha((TASK / 'evidence' / rel).read_bytes()) == expected, 'Original evidence was changed')
        receipt.update(state='cache-repair-complete', exit_code=0, source_clean=True,
                       original_evidence_preserved=True, exact_task_target=True)
    except Exception as error:
        receipt.update(state='cache-repair-blocked', exit_code=1, error=str(error))
    finally:
        if lock is not None:
            lock.close()
        save()
    print(json.dumps({'state': receipt['state'], 'exit_code': receipt['exit_code'],
                      'receipt': str(evidence / 'receipt.json'), 'sha256': sha((evidence / 'receipt.json').read_bytes())}), flush=True)
    return receipt['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
