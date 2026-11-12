"""Pure Python driver checks. Synthetic reports are NOT native evidence.

Only local read-only git commands retrieve the reference source. No H, cargo,
rustc, nextest, sudo, test executable, or configured template runtime is launched.
The uninstantiated main is checked only for its refusal before any I/O.
"""
import ast
import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / 'root_completed_chain_native_template_v1.py'
REFERENCE_REPO = HERE.parent / 'hepta-recovered-20261112'
REFERENCE_HEAD = '27bbd027bf02e134755cadb98ccd20d320364ce0'
OUTPUT = HERE / 'validation/root-completed-chain-driver-template-v1'
CHECKS = []


def checked(name, condition):
    if not condition:
        raise AssertionError(name)
    CHECKS.append(name)


def original(path):
    return subprocess.check_output(
        ['git', 'show', REFERENCE_HEAD + ':' + path], cwd=REFERENCE_REPO
    ).decode()


source = TEMPLATE.read_text()
module = types.ModuleType('driver_template_validation_only')
module.__file__ = str(TEMPLATE)
exec(compile(source, str(TEMPLATE), 'exec'), module.__dict__)
checked('import has no run, output creation, or result initialization', module.result is None)
try:
    module.main()
except RuntimeError as error:
    checked('uninstantiated main refuses before I/O', str(error) == 'instantiate exact HEAD')
else:
    raise AssertionError('uninstantiated main did not refuse')

workflow = original('.github/workflows/hepta-daemon-learning-native.yml')
nextest_config = original('codex-rs/.config/nextest.toml')
acceptance_source = original('codex-rs/hepta-agentd/src/authority_host_publication_acceptance_tests.rs')
refusal_source = original('codex-rs/hepta-agentd/src/authority_host_publication_refusal_tests.rs')
collector_source = original('scripts/hepta_ci_junit.py')
collector = types.ModuleType('actual_collector_pure_validation_only')
exec(compile(collector_source, 'reference_hepta_ci_junit.py', 'exec'), collector.__dict__)

checked('two acceptance parents use actual nested module',
        '#[path = "authority_host_publication_acceptance_tests.rs"]\nmod acceptance;' in refusal_source)
for test_name in module.ACCEPTANCE_PARENTS:
    checked('actual acceptance function ' + test_name.rsplit('::', 1)[-1],
            'fn ' + test_name.rsplit('::', 1)[-1] + '(' in acceptance_source
            and '::refusal::tests::acceptance::' in test_name)

main = next(node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == 'main')
schedule = next(node.value for node in ast.walk(main)
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'schedule' for t in node.targets))
schedule_names = [entry.elts[0].value for entry in schedule.elts]
checked('native stage order is exact', schedule_names + ['seven-libs'] == module.NATIVE_ORDER)
calls = [node for node in ast.walk(main) if isinstance(node, ast.Call)
         and isinstance(node.func, ast.Name) and node.func.id == 'attempt'
         and node.args and isinstance(node.args[0], ast.Constant)]
tail = [(call.lineno, call.args[0].value) for call in calls
        if call.args[0].value in ('seven-libs', 'fullsource', 'fullcallers')]
checked('full QA then authoritative CLI follow seven libraries',
        [name for _, name in sorted(tail)] == ['seven-libs', 'fullsource', 'fullcallers'])

forbidden_processes = []


def forbidden(*arguments, **keywords):
    forbidden_processes.append(repr(arguments))
    raise AssertionError('external process forbidden in synthetic validation')


with tempfile.TemporaryDirectory(prefix='hepta-driver-template-python-') as raw_tmp:
    tmp = Path(raw_tmp)
    module.OUT = tmp / 'out'
    module.OUT.mkdir()
    module.REPO = tmp / 'repo'
    module.REPO.mkdir()
    module.TARGET = tmp / 'target'
    module.PUBLIC = tmp / 'public'
    module.ROOT = tmp / 'root'
    module.HEAD, module.TREE = 'f' * 40, 'e' * 40
    state = dict(head=module.HEAD, tree=module.TREE, status='', tracked_files=1,
                 tracked_sha256='0' * 64)
    module.result = dict(before=state, stages=[], checks={})
    module.snapshot = lambda: dict(state)
    module.restore_ownership = lambda: None
    module.collect = collector.collect
    (module.REPO / '.github/workflows').mkdir(parents=True)
    (module.REPO / '.github/workflows/hepta-daemon-learning-native.yml').write_text(workflow)
    (module.REPO / 'codex-rs/.config').mkdir(parents=True)
    (module.REPO / 'codex-rs/.config/nextest.toml').write_text(nextest_config)
    checked('reference workflow45 plus two exact parents equals 47', len(module.require_roster()) == 47)
    checked('reference wholecold watchdog remains 30 seconds times 16',
            (module.OUT / 'original-nextest-budgets.json').exists())
    (module.REPO / '.github/workflows/hepta-daemon-learning-native.yml').write_text(
        workflow.replace(module.WORKFLOW_PARENTS[0], 'different_parent', 1))
    try:
        module.require_roster()
    except RuntimeError as error:
        checked('equal-count but different roster is rejected', 'roster changed' in str(error))
    else:
        raise AssertionError('changed roster accepted')

    captured = io.StringIO()
    with patch.dict(os.environ, {'SOURCE_SHA': module.HEAD}, clear=False), \
            patch.object(subprocess, 'Popen', forbidden), \
            patch.object(subprocess, 'run', forbidden), \
            patch.object(subprocess, 'check_output', forbidden), \
            contextlib.redirect_stdout(captured):
        for binary in ('codex-hepta-agentd', 'hepta-authority-host', 'hepta-joint-propose'):
            for variant in (binary, binary.replace('-', '_')):
                os.environ['CARGO_BIN_EXE_' + variant] = str(module.PUBLIC / 'unprepared' / binary)
        flow = []

        def failed():
            flow.append('exception')
            raise RuntimeError('intentional pure Python failure')

        module.attempt('synthetic-false', lambda: flow.append('false') or False)
        module.attempt('synthetic-exception', failed)
        module.attempt('synthetic-after', lambda: flow.append('after') or True)
        checked('false and exception preserve subsequent stage execution',
                flow == ['false', 'exception', 'after']
                and module.result['checks']['synthetic-after']['passed'] is True)
        checked('stage exception preserves traceback',
                'intentional pure Python failure' in
                (module.OUT / 'synthetic-exception-driver-error.log').read_text())

        original_command = module.command
        with patch.object(subprocess, 'Popen', side_effect=OSError('synthetic launch error')):
            try:
                original_command('synthetic-launch-failure', ['NOT_EXECUTED'])
            except OSError:
                pass
            checked('failed process launch has a terminal record',
                    module.result['stages'][-1]['status'] == 'launch_failed'
                    and 'synthetic launch error' in module.result['stages'][-1]['error'])

        reports = [module.TARGET / 'nextest/local/junit.xml',
                   module.REPO / 'codex-rs/target/nextest/local/junit.xml']
        for report in reports:
            report.parent.mkdir(parents=True, exist_ok=True)

        def probe(label, cases=None, duplicate_report=False, command_exit=0,
                  after_changed=False, expected=None):
            expected = ['required_parent'] if expected is None else expected
            calls = []
            for report in reports:
                if report.exists():
                    report.unlink()
            reports[0].write_bytes(b'OLD EXCLUDED REPORT; NOT NATIVE')

            def simulated_command(name, argv, cwd=None):
                calls.append((name, argv))
                if cases is not None:
                    suite = ET.Element('testsuite')
                    for case_name, kind in cases:
                        case = ET.SubElement(suite, 'testcase', name=case_name)
                        if kind:
                            ET.SubElement(case, kind).text = 'synthetic driver check only'
                    data = ET.tostring(suite)
                    reports[0].write_bytes(data)
                    if duplicate_report:
                        reports[1].write_bytes(data)
                    moment = reports[0].stat().st_mtime
                    passed = sum(kind is None for _, kind in cases)
                    failures = sum(kind in ('failure', 'error') for _, kind in cases)
                    command_start = argv.index('just')
                    record = dict(schema_version=1, source_sha=module.HEAD,
                                  tested_sha=module.HEAD, lane='source-head',
                                  before=dict(commit=module.HEAD, tree=module.TREE, dirty=False),
                                  command=argv[command_start:],
                                  started_at=datetime.datetime.fromtimestamp(moment - 1, datetime.timezone.utc).isoformat(),
                                  finished_at=datetime.datetime.fromtimestamp(moment + 1, datetime.timezone.utc).isoformat(),
                                  observed_passed_tests=passed, observed_failed_tests=failures,
                                  status='passed' if command_exit == 0 else 'failed',
                                  exit_code=command_exit, command_exit_code=command_exit)
                    record['after'] = dict(record['before'])
                    module.save(module.OUT / (label + '.json'), record)
                if after_changed:
                    module.snapshot = lambda: dict(state, status=' M changed.rs\n')
                return command_exit

            module.command = simulated_command
            module.snapshot = lambda: dict(state)
            passed = module.test(label, ['--lib', '--run-ignored', 'only', '-E',
                                         'test(=required_parent)'], expected)
            module.snapshot = lambda: dict(state)
            checked(label + ': stage name is not shadowed by binary environment loop',
                    calls[0][0] == label + '-execution')
            argv = calls[0][1]
            checked(label + ': actual command shape keeps just test and no retries',
                    argv[argv.index('just'):argv.index('just') + 4] ==
                    ['just', 'test', '--locked', '--offline']
                    and argv[argv.index('--retries') + 1] == '0'
                    and argv[argv.index('--no-tests') + 1] == 'fail'
                    and argv[argv.index('--timeout-seconds') + 1] == '7200')
            checked(label + ': root command requires real sudo UID0',
                    argv[:4] == ['sudo', '-n', 'env', '-i']
                    and any('assert os.geteuid()==0' in item for item in argv))
            checked(label + ': prior JUnit is preserved but excluded',
                    (module.OUT / (label + '-prior-junit-0-excluded.xml')).read_bytes()
                    == b'OLD EXCLUDED REPORT; NOT NATIVE')
            return passed

        checked('missing fresh JUnit cannot pass', not probe('missing'))
        checked('different parent cannot pass even when collector counts pass',
                not probe('wrong-parent', [('other_parent', None)]))
        checked('duplicate parent cannot count as exact coverage',
                not probe('duplicate-parent', [('required_parent', None)] * 2))
        checked('skipped expected parent cannot pass',
                not probe('skipped-parent', [('required_parent', 'skipped')]))
        checked('failed exact parent cannot pass',
                not probe('failed-parent', [('required_parent', 'failure')], command_exit=100))
        checked('two fresh JUnit paths are ambiguous and rejected',
                not probe('two-reports', [('required_parent', None)], duplicate_report=True)
                and module.result['two-reports']['collection']['status'] == 'multiple-fresh-native-reports')
        checked('successful report cannot hide source mutation',
                not probe('source-changed', [('required_parent', None)], after_changed=True))
        checked('one exact successful synthetic parent is accepted by driver logic only',
                probe('exact-parent', [('required_parent', None)]))
        checked('raw failed report is retained verbatim',
                (module.OUT / 'failed-parent-fresh-native-observed-0.xml').read_bytes()
                == (module.OUT / 'failed-parent.xml').read_bytes())

        called = []
        module.snapshot = lambda: dict(state, status=' M source.rs\n')
        module.command = lambda *a, **k: called.append(a)
        try:
            module.source_check('changed-source-cli', ['NOT_EXECUTED'])
        except RuntimeError:
            pass
        checked('source drift cannot execute full CLI on a different source', not called)
        module.snapshot = lambda: dict(state)
        helper_root = module.PUBLIC / 'helpers'
        helper_root.mkdir(parents=True)
        (helper_root / 'compile.stderr.log').write_bytes(b'actual-format raw error sentinel\n')
        module.command = lambda *a, **k: 101
        checked('helper failure returns failure', not module.build_helpers(['NOT_EXECUTED']))
        checked('helper failure still retains inner Cargo stderr',
                (module.OUT / 'helper-build-preparation-records/compile.stderr.log').read_bytes()
                == b'actual-format raw error sentinel\n')
        checked('no external process launched during synthetic checks', forbidden_processes == [])

OUTPUT.mkdir(parents=True, exist_ok=True)
report = dict(
    kind='pure-python-driver-validation-not-native',
    result='passed', checks=len(CHECKS), checked=CHECKS,
    reference_source=REFERENCE_HEAD,
    template=dict(path=str(TEMPLATE), bytes=len(source.encode()),
                  sha256=hashlib.sha256(source.encode()).hexdigest()),
    actual_collector_sha256=hashlib.sha256(collector_source.encode()).hexdigest(),
    external_execution='Only read-only local git show. No H or Rust or template runtime.',
    native_tests_executed=0, whole_positive=0, whole_evaluated_no_update=0, whole_cold=0,
    synthetic_files='Temporary directory removed; no synthetic JUnit is delivered as evidence.'
)
(OUTPUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
