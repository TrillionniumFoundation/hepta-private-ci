from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


REPO = Path('/home/qian-qi/hepta-framework-owner-assembly-20261110-b68b')
OUT = Path('/home/qian-qi/hepta-framework-validation-06f3219-20261110-b68b')
BASE = 'abf75d8e2097785b2ad01897c15a7531eebe6e44'
PREVIOUS = '6c5e5fa199ef291c5dbbc0ab13fe3e565d750fec'
HEAD = '06f32191452df9f03bb5dc21ff8105db6b66d3d6'
TREE = 'd6db19d921be786713a7b1f91aa2a460b2ead8fe'
BRANCH = 'codex/framework-learning-recovery-20261110-b68b'
TARGET = Path('/data/codex-organ-hepta5ece-complete-ten-owner-source-target-20261101-02')
ENV = dict(os.environ)
ENV.update(PATH='/home/qian-qi/.cargo/bin:' + ENV.get('PATH', ''),
           RUSTUP_TOOLCHAIN='1.96.0', CARGO_HOME='/home/qian-qi/.cargo',
           CARGO_TARGET_DIR=str(TARGET), CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
           PYTHONDONTWRITEBYTECODE='1')

REQUIRED_TESTS = [
    'full_learning_actor_leaves_completion_unclaimed_then_delivers_once',
    'lost_learning_delivery_response_reconciles_without_repeating_stages',
    'completed_and_intermediate_histories_read_original_evaluation_after_work_expiry',
    'corrupted_or_replaced_evaluation_history_is_refused_before_owner_io',
    'expired_learning_readback_allows_multiple_bounded_original_owner_reads',
    'stalled_learning_readback_exhausts_its_budget_without_repeating_or_writing',
    'learning_submit_keeps_its_work_deadline_while_restoring_a_checkpoint',
]


def now():
    return datetime.now(timezone.utc).isoformat()


OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
if OUT.is_symlink():
    raise RuntimeError('refuse symlink evidence directory')
claim = os.open(OUT / 'invocation.claim', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(claim, b'framework-native-06f3219-b68b-01\n')
os.close(claim)
status = {'schema': 'hepta-framework-native-validation-v1', 'started_at': now(),
          'requested_head': HEAD, 'requested_tree': TREE, 'repo': str(REPO),
          'pid': os.getpid(), 'state': 'starting', 'phase': 'preflight', 'phases': [],
          'selected_native_tests_passed': False, 'source_preserved_during_tests': False,
          'environment': {key: ENV[key] for key in ('RUSTUP_TOOLCHAIN', 'CARGO_HOME',
              'CARGO_TARGET_DIR', 'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL',
              'PYTHONDONTWRITEBYTECODE')}}


def write_json(name, data):
    path = OUT / name
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def checkpoint():
    status['updated_at'] = now()
    write_json('status.json', status)


def phase(name, argv, cwd=REPO, required=True):
    record = {'name': name, 'argv': argv, 'cwd': str(cwd), 'started_at': now(),
              'stdout': name + '.stdout.log', 'stderr': name + '.stderr.log'}
    status['phase'] = name
    status['state'] = 'running'
    status['phases'].append(record)
    checkpoint()
    started = time.monotonic()
    with (OUT / record['stdout']).open('xb') as stdout, (OUT / record['stderr']).open('xb') as stderr:
        result = subprocess.run(argv, cwd=cwd, env=ENV, stdout=stdout, stderr=stderr)
    record.update(returncode=result.returncode, finished_at=now(),
                  elapsed_seconds=time.monotonic() - started)
    tail = ''
    for key in ('stdout', 'stderr'):
        path = OUT / record[key]
        record[key + '_bytes'] = path.stat().st_size
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            stream.seek(max(0, path.stat().st_size - 10000))
            tail += key + ':\n' + stream.read().decode('utf-8', errors='replace') + '\n'
        record[key + '_sha256'] = digest.hexdigest()
    (OUT / (name + '.tail.txt')).write_text(tail, encoding='utf-8')
    checkpoint()
    if required and result.returncode:
        raise RuntimeError(f'{name} failed with exit {result.returncode}; see original logs')
    return result.returncode


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], env=ENV).decode().strip()


def source_identity():
    changed = git('diff', '--name-only', BASE, '--').splitlines()
    index = subprocess.check_output(['git', '-C', str(REPO), 'ls-files', '-s', '-z'], env=ENV)
    hashes = {}
    for name in changed:
        path = REPO / name
        if path.is_file() and path.resolve().is_relative_to(REPO.resolve()):
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
            'status_porcelain': git('status', '--porcelain'),
            'index_sha256': hashlib.sha256(index).hexdigest(),
            'changed_source_sha256': hashes}


def qualify_native_results(source, native_phase, required_tests):
    import re
    import xml.etree.ElementTree as ET

    started_ns = int(datetime.fromisoformat(native_phase['started_at']).timestamp() * 1_000_000_000)
    finished_ns = int(datetime.fromisoformat(native_phase['finished_at']).timestamp() * 1_000_000_000)
    result = {'schema': 'hepta-native-result-gate-v1', 'source_head': source['head'],
              'source_tree': source['tree'], 'native_started_at': native_phase['started_at'],
              'native_finished_at': native_phase['finished_at'],
              'native_exit_code': native_phase['returncode'],
              'required_tests': required_tests, 'reports': [], 'passed': False,
              'native_stderr_sha256': native_phase['stderr_sha256'],
              'source_preserved_during_tests': status['source_preserved_during_tests'],
              'requested_head': HEAD, 'requested_tree': TREE}
    stderr = (OUT / native_phase['stderr']).read_text(encoding='utf-8')
    plain = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', stderr)
    summaries = re.findall(r'^\s*Summary\s+\[[^\]]+\]\s+(\d+)\s+tests?\s+run:\s*([^\r\n]+)', plain, re.MULTILINE)
    result['stderr_summaries'] = [{'executed': int(count), 'text': detail} for count, detail in summaries]
    pass_lines = re.findall(r'^\s*PASS\s+\[[^\]]+\]\s+(\S+)\s+(\S+)\s*$', plain, re.MULTILINE)
    pass_matches = {name: [{'binary': binary, 'name': full_name} for binary, full_name in pass_lines
                          if full_name.rsplit('::', 1)[-1] == name] for name in required_tests}
    result['required_stderr_pass_records'] = pass_matches
    qualified_report = None
    for candidate in [TARGET / 'nextest/local/junit.xml', REPO / 'codex-rs/target/nextest/local/junit.xml']:
        if not candidate.is_file():
            continue
        report = {'original_path': str(candidate), 'freshness_qualified': False}
        result['reports'].append(report)
        try:
            stat_before = candidate.stat()
            data = candidate.read_bytes()
            stat_after = candidate.stat()
            report.update(mtime_ns=stat_after.st_mtime_ns, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            stable = (stat_before.st_ino, stat_before.st_size, stat_before.st_mtime_ns) == (stat_after.st_ino, stat_after.st_size, stat_after.st_mtime_ns)
            report['stable_during_read'] = stable
            report['freshness_qualified'] = stable and started_ns <= stat_after.st_mtime_ns <= finished_ns
            name = 'observed-junit-' + hashlib.sha256(str(candidate).encode()).hexdigest()[:8] + '.xml'
            report['retained_path'] = name
            (OUT / name).write_bytes(data)
            root = ET.fromstring(data)
            cases = []
            for case in root.iter():
                if case.tag.rsplit('}', 1)[-1] != 'testcase':
                    continue
                children = {child.tag.rsplit('}', 1)[-1] for child in case}
                outcome = 'failed' if children.intersection({'failure', 'error'}) else 'skipped' if 'skipped' in children else 'passed'
                cases.append({'name': case.attrib.get('name', ''), 'classname': case.attrib.get('classname', ''),
                              'seconds': case.attrib.get('time'), 'outcome': outcome})
            counts = {outcome: sum(case['outcome'] == outcome for case in cases) for outcome in ('passed', 'failed', 'skipped')}
            counts['executed'] = counts['passed'] + counts['failed']
            matches = {required: [case for case in cases if case['name'].rsplit('::', 1)[-1] == required]
                       for required in required_tests}
            report.update(counts=counts, required_cases=matches)
            report['case_set_qualified'] = counts['executed'] > 0 and counts['failed'] == 0 and all(
                len(matches[required]) == 1 and matches[required][0]['outcome'] == 'passed' for required in required_tests)
            if report['freshness_qualified'] and report['case_set_qualified']:
                qualified_report = report
            write_json(name + '.metadata.json', report)
        except Exception as error:
            report['read_or_parse_error'] = str(error)
    source_bound = source['head'] == HEAD and source['tree'] == TREE and not source['status_porcelain'] and status['source_preserved_during_tests']
    if native_phase['returncode'] == 0 and source_bound and len(required_tests) == 7 and len(set(required_tests)) == 7:
        if qualified_report is not None:
            result.update(passed=True, result_source='fresh-junit', counts=qualified_report['counts'],
                          required_cases=qualified_report['required_cases'], junit_sha256=qualified_report['sha256'])
        elif len(summaries) == 1 and all(len(matches) == 1 for matches in pass_matches.values()):
            count, detail = summaries[0]
            counts = {label: int(value) for value, label in re.findall(r'(\d+)\s+(passed|failed|skipped)', detail)}
            if int(count) > 0 and counts.get('passed') == int(count) and counts.get('failed', 0) == 0:
                counts['executed'] = int(count)
                result.update(passed=True, result_source='original-stderr-summary-and-pass-lines', counts=counts,
                              required_cases=pass_matches)
    write_json('native-result-gate.json', result)
    return result


exit_code = 1
checkpoint()
try:
    if len(REQUIRED_TESTS) != 7 or len(set(REQUIRED_TESTS)) != 7:
        raise RuntimeError('final seven-case regression set is not bound; no native tests launched')
    if git('rev-parse', 'HEAD') not in (PREVIOUS, HEAD) or git('status', '--porcelain'):
        raise RuntimeError('worktree is dirty or has an unexpected head; no checkout performed')
    if not TARGET.is_dir():
        raise RuntimeError('previously observed target directory is unavailable')
    write_json('cache-metadata.json', {'target': str(TARGET), 'target_children': sorted(p.name for p in TARGET.iterdir()),
        'cargo_home': ENV['CARGO_HOME'], 'registry_present': Path(ENV['CARGO_HOME'], 'registry').is_dir(),
        'git_cache_present': Path(ENV['CARGO_HOME'], 'git').is_dir()})
    phase('fetch', ['git', '-c', 'credential.helper=!gh auth git-credential', 'fetch', '--no-tags',
          'https://github.com/TrillionniumFoundation/hepta-private-ci.git', BRANCH])
    if git('status', '--porcelain') or git('rev-parse', HEAD + '^{tree}') != TREE:
        raise RuntimeError('source changed during fetch or fetched candidate has unexpected tree')
    phase('checkout', ['git', 'checkout', '--detach', HEAD])
    before = source_identity()
    write_json('source_before.json', before)
    if before['head'] != HEAD or before['tree'] != TREE or before['status_porcelain']:
        raise RuntimeError('frozen source identity mismatch')
    phase('just-version', ['just', '--version'])
    phase('rustc-version', ['rustc', '--version', '--verbose'], cwd=REPO / 'codex-rs')
    phase('rustfmt-version', ['rustfmt', '--version'], cwd=REPO / 'codex-rs')
    phase('nextest-version', ['cargo', 'nextest', '--version'], cwd=REPO / 'codex-rs')
    phase('fmt-check', ['just', 'fmt', '--check', '--base', BASE], cwd=REPO / 'codex-rs')
    if source_identity() != before:
        raise RuntimeError('source changed during preflight or formatting check')
    test_argv = ['just', 'test', '--locked', '--offline', '--cargo-profile', 'dev-small',
                 '-p', 'codex-hepta-agentd', '--lib', '-E',
                 'test(learning_iteration) | test(circuit_learning_delivery) | test(root_production_learning_inputs)',
                 '--test-threads', '2', '--retries', '0']
    test_code = phase('native-tests', test_argv, cwd=REPO / 'codex-rs', required=False)
    after_tests = source_identity()
    write_json('source_after_tests.json', after_tests)
    status['source_preserved_during_tests'] = before == after_tests
    status['native_command_succeeded'] = test_code == 0 and before == after_tests
    checkpoint()
    native_phase = next(record for record in status['phases'] if record['name'] == 'native-tests')
    result_gate = qualify_native_results(before, native_phase, REQUIRED_TESTS)
    status['native_result_gate_passed'] = result_gate['passed']
    status['selected_native_tests_passed'] = result_gate['passed']
    status['native_result_source'] = result_gate.get('result_source')
    checkpoint()
    if test_code or before != after_tests or not result_gate['passed']:
        raise RuntimeError(f"native tests exit {test_code}; source_preserved={before == after_tests}; result_gate={result_gate['passed']}")
    phase('fix', ['just', 'fix', '-p', 'codex-hepta-agentd', '--locked', '--offline', '--profile', 'dev-small'],
          cwd=REPO / 'codex-rs')
    write_json('source_after_fix.json', source_identity())
    phase('fmt-maintenance', ['just', 'fmt'], cwd=REPO / 'codex-rs')
    after_maintenance = source_identity()
    write_json('source_after_maintenance.json', after_maintenance)
    status['maintenance_changed_source'] = before != after_maintenance
    phase('maintenance-diff', ['git', 'diff', '--binary'], required=True)
    phase('diff-check', ['git', 'diff', '--check'], required=True)
    status['state'] = 'completed'
    status['phase'] = 'complete'
    status['tests_after_maintenance'] = False
    exit_code = 0
except Exception as error:
    status['state'] = 'failed'
    status['error'] = str(error)
    (OUT / 'driver-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
finally:
    try:
        write_json('source_final.json', source_identity())
    except Exception as error:
        status['source_final_error'] = str(error)
    status['finished_at'] = now()
    status['driver_exit_code'] = exit_code
    checkpoint()
sys.exit(exit_code)
