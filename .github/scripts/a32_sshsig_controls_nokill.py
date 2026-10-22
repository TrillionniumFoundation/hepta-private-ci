"""Diagnostic-only adapter: preserve frozen control/oracle bytes; remove exact Rust deadlines."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

SPECS = {
    'acquisition': ('.github/scripts/check_windows_private_state_acquisition.py', 600,
                    'codex-utils-path', 'test(private_state_windows::directory::tests::)'),
    'recovery': ('codex-rs/state/tests/windows-recovery-controls/run.py', 1200,
                 'codex-state', 'test(sqlite_recovery::windows_tests::retained_sources_deny_same_size_write_and_byte_identical_replacement) | test(sqlite_recovery::windows_tests::attributes_are_part_of_the_complete_retained_identity)'),
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def command_for(spec):
    return ['just', 'test', '--locked', '-p', spec[2], '--lib', '-E', spec[3],
            '--test-threads', '1', '--no-tests', 'fail', '--retries', '0', '--success-output',
            'immediate', '--failure-output', 'immediate', '--status-level', 'all', '--final-status-level', 'all']


def terminal_owned(operation, process, observe):
    """Wait naturally. No pending exception may run an oracle finally before child terminal."""
    pending = None
    deferred = 0
    while True:
        try:
            result = operation()
            break  # Successful wait/communicate is the terminal observation; poll uncertainty is not.
        except BaseException as error:
            pending = pending or error
            deferred += 1
            try:
                observe({'event': 'interrupted-child', 'pid': process.pid,
                         'outcome': 'pending-until-terminal', 'exception_type': type(error).__name__,
                         'exception_deferred_until_child_terminal': True})
            except BaseException as observer_error:
                pending = pending or observer_error
                deferred += 1
            try:
                time.sleep(0.05)  # Avoid a busy loop if the OS query itself temporarily fails.
            except BaseException as sleep_error:
                pending = pending or sleep_error
                deferred += 1
    if pending is not None:
        pending.add_note(f'{deferred} exception observations deferred; child terminal; no successful outcome reported')
        raise pending
    return result


def wait_owned(process, observe):
    return terminal_owned(process.wait, process, observe)


class ExactCommandProxy:
    def __init__(self, delegate, command, deadline, observe):
        self.delegate, self.command, self.deadline, self.observe = delegate, tuple(command), deadline, observe

    def run(self, command, *args, **kwargs):
        if tuple(command) != self.command:
            require('timeout' not in kwargs, 'unknown timeout-bearing command rejected, not suppressed')
            return self.delegate.run(command, *args, **kwargs)
        require(not args and kwargs.get('timeout') == self.deadline and kwargs.get('check') is False,
                'exact frozen Rust command has changed timeout/call contract')
        require(set(kwargs) in ({'cwd', 'stdout', 'stderr', 'timeout', 'check'},
                                {'cwd', 'stdout', 'stderr', 'timeout', 'check', 'text'}),
                'unexpected native call arguments')
        self.observe({'event': 'native-admitted', 'argv': list(command),
                      'removed_timeout_seconds': self.deadline, 'cwd': str(kwargs.get('cwd')),
                      'started_unix': time.time(), 'signals_sent': False,
                      'transformed_execution': 'owned-Popen-wait; same argv/cwd/stdio/check/result'})
        options = dict(kwargs)
        del options['timeout']
        del options['check']
        process = self.delegate.Popen(command, **options)
        code = wait_owned(process, self.observe)
        self.observe({'event': 'native-finished', 'pid': process.pid, 'exit_code': code})
        return self.delegate.CompletedProcess(command, code, None, None)

    def check_output(self, command, *args, **kwargs):
        if list(command) != ['rustc', '--version', '--verbose']:
            return self.delegate.check_output(command, *args, **kwargs)
        require(not args and set(kwargs) == {'cwd', 'text'} and kwargs['text'] is True,
                'unexpected frozen rustc version-query contract')
        self.observe({'event': 'version-query-admitted', 'argv': list(command), 'timeout_changed': False,
                      'cwd': str(kwargs['cwd']), 'started_unix': time.time(), 'signals_sent': False})
        process = self.delegate.Popen(command, stdout=self.delegate.PIPE, **kwargs)
        output, _ = terminal_owned(process.communicate, process, self.observe)
        self.observe({'event': 'version-query-finished', 'pid': process.pid, 'exit_code': process.returncode})
        if process.returncode:
            raise self.delegate.CalledProcessError(process.returncode, command, output)
        return output

    def __getattr__(self, name):
        return getattr(self.delegate, name)


def execute_frozen(path, evidence, expected_sha256, spec):
    require(hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256,
            'control source must match exact reviewed product manifest')
    require(not evidence.exists(), 'control evidence must be fresh')
    journal = evidence.with_name(evidence.name + '.no-kill.jsonl')
    identity = {'event': 'adapter-identity', 'control_path': str(path),
                'control_sha256': expected_sha256,
                'adapter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'argv': [str(path), str(evidence)], 'script_import_directory': str(path.parent),
                'known_timeout_removed': spec[1], 'version_query_timeout_changed': False,
                'oracle_source_mutated': False, 'explicit_main_after_module_import': True}
    with journal.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(identity, sort_keys=True) + '\n')
    calls = []
    def observe(record):
        calls.append(record)
        with journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
            stream.flush()
    argv, search_path = sys.argv, sys.path[:]
    module = None; original = None
    try:
        sys.argv = [str(path), str(evidence)]
        sys.path[0:1] = [str(path.parent)]
        module_spec = importlib.util.spec_from_file_location('frozen_control', path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        command = command_for(spec)
        require(module.COMMAND == command, 'frozen command differs from explicit adapter contract')
        original = module.subprocess
        module.subprocess = ExactCommandProxy(original, command, spec[1], observe)
        module.main()  # Exact frozen oracle and restoration, never a copied/replaced check_result.
        require(sum(x['event'] == 'native-admitted' for x in calls) == 3,
                'expected positive and two mutant native commands')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256, 'frozen control source changed')
    finally:
        sys.argv = argv
        sys.path[:] = search_path
        if module is not None and original is not None:
            module.subprocess = original


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('family', choices=SPECS)
    parser.add_argument('evidence')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    spec = SPECS[args.family]
    path = root / spec[0]
    manifest = json.loads((root / '.github/fixtures/a32-sshsig-qualification/source-manifest.json').read_bytes())
    expected = [x for x in manifest['files'] if x['path'] == spec[0]]
    require(len(expected) == 1, 'exact control identity missing')
    evidence = Path(args.evidence).resolve()
    require(not evidence.is_relative_to(root), 'control evidence must be outside checkout')
    execute_frozen(path, evidence, expected[0]['candidate_sha256'], spec)


if __name__ == '__main__':
    main()
