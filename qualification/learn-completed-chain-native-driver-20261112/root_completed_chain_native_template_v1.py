"""Run actual source-bound native processes; never infer qualification from compilation."""
import ast
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import tomllib
import traceback
import xml.etree.ElementTree as ET

BASE = Path('/home/qq/hepta-learn-ff41-tools')
REPO = Path('__FROZEN_REPO_ABSOLUTE__')
TARGET = Path('/home/qq/hepta-learn-ff41-target-f73704ac-v1')
RUN_ID = '__NEW_UNIQUE_RUN_ID__'
OUT = BASE / 'validation' / RUN_ID
FIX_RECORD = Path('__MATCHING_SCOPED_FIX_RESULT_JSON__')
HEAD = '__SOURCE_HEAD_40_HEX__'
TREE = '__SOURCE_TREE_40_HEX__'
PUBLIC = Path('/tmp') / ('hepta-native-' + RUN_ID)
ROOT = Path('/run') / ('hepta-daemon-learning-' + RUN_ID)
A_PARENT = ('neuron_generation_current::initial_root_tests::ordinary::'
            'ordinary_main_a_records_independent_outcome_and_retires_original_processes')

POST_A = 'neuron_generation_current::initial_root_tests::ordinary::post_a_process::'
ADOPT_PARENT = POST_A + 'ordinary_main_adopts_after_independent_b_and_executes_original_c'
NO_UPDATE_PARENT = POST_A + 'ordinary_main_retains_after_completed_independent_b_and_executes_original_c'
COLD_PARENT = ('neuron_generation_current::initial_root_tests::ordinary::cold_process::'
               'ordinary_main_cold_recovers_completed_c_after_actual_daemon_and_root_retirement')
PACKAGES = ['codex-hepta-agentd', 'codex-hepta-agent-protocol', 'codex-hepta-learning-ledger',
            'codex-hepta-contracts', 'codex-hepta-neuron', 'codex-hepta-intelligence-eval',
            'codex-hepta-learning-artifacts']
# Exact original workflow roster reviewed at 27bbd027. A frozen-source roster
# change needs an explicit template review; a count alone is not sufficient.
WORKFLOW_PARENTS = [
    "authority_host_service::writer::learning_registration::tests::root_learning_registration_reopens_without_replacing_original_history",
    "authority_host_service::writer::learning_registration::tests::root_learning_sealed_pin_and_dedicated_uds_recover_original_checkpoint",
    "authority_host_service::writer::learning_registration::tests::root_scoped_learning_reopens_exact_scope_and_refuses_legacy_client",
    "authority_host_service::writer::learning_registration::tests::root_learning_scoped_sealed_pin_preserves_scope_on_cold_reopen",
    "root_production_handoff::learning::tests::root_learning_handoff_reaches_dedicated_uid_with_original_root_pin",
    "authority_host_learning_service_root_tests::root_learning_public_registration_serves_retained_writer_and_recovers_history",
    "authority_host_service::q24_model::registration::tests::root_factory_record_reopens_bound_without_replacing_original_files",
    "authority_host_service::q24_model::registration::tests::root_factory_file_pins_reject_alias_replacement_wrong_access_and_missing_witness",
    "root_production_handoff::q24_model::tests::root_model_handoff_preserves_four_original_rights_and_cloexec",
    "root_production_handoff::q24_model::tests::root_model_handoff_rejects_learning_purpose_and_reordered_rights",
    "authority_host_q24_model_service_root_tests::root_q24_factory_registers_transfers_binds_and_recovers_original_custody",
    "learning_iteration_evidence_client::tests::root::original_external_uid_returns_a_verified_receipt_through_held_pidfd",
    "root_production_handoff::generation_publication::tests::root_publication_handoff_reaches_dedicated_uid_and_refuses_confused_rights",
    "final_use::store::root_observer::tests::root_observer_reads_live_original_and_rejects_revocation_without_claiming",
    "final_use::store::root_observer::tests::root_observer_fences_partial_rollback_schema_and_replaced_original_files",
    "neuron_generation_current::publication_root_tests::root_broker_late_enrolls_publishes_and_recovers_original_current",
    "neuron_generation_current::initial_root_tests::root_initial_publication_uses_original_consumer_and_readonly_recovery",
    "neuron_generation_current::initial_root_tests::root_initial_peer_ready_registers_fixed_inputs_without_trigger_file",
    "authority_host_service::generation_initial::historical_source_pin::tests::root_source_pin_preserves_exact_registration_and_never_initializes_recovery",
    "authority_host_runtime::session::generation_initial::source_capture::tests::root_source_capture_capability_rejects_replaced_lifetime_and_late_ack",
    "authority_host_runtime::session::generation_initial::source_capture::tests::root_source_capture_ack_is_data_and_keeps_the_one_shot_consumed",
    "authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_recovery_never_promotes_missing_pending_or_fenced",
    "authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_observed_conflict_stays_refused_after_restored_bytes",
    "authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_recovery_rejects_peer_ack_without_context_finalization",
    "authority_host_service::generation_initial::data_refusal::tests::root_data_refusal_sequences_block_stale_cross_handle_completion",
    "authority_host_service::generation_initial::data_refusal::tests::root_data_refusal_does_not_retrofit_old_primary_or_split_one_scope",
    "authority_host_service::generation_initial::data_refusal::tests::root_data_refusal_crash_during_failed_primary_read_remains_armed_after_restore",
    "authority_host_service::generation_initial::historical_source_pin::tests::cold::root_source_pin_physical_corruption_then_restore_stays_refused_across_processes",
    "authority_host_service::generation_initial::historical_source_pin::tests::cold::root_source_pin_unfinished_capture_cannot_initialize_after_restart",
    "authority_host_service::generation_initial::historical_source_handoff::tests::cold::root_source_handoff_physical_corruption_then_restore_stays_refused_across_processes",
    "authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_finalized_primary_before_failed_postcheck_is_not_recoverable",
    "authority_host_service::generation_initial::run_start_retention::tests::root_run_start_data_never_promotes_pending_or_missing_refusal",
    "authority_host_service::generation_initial::run_start_retention::tests::root_run_start_finalized_primary_before_failed_postcheck_cannot_recover",
    "authority_host_service::generation_initial::run_start_retention::tests::root_run_start_corruption_then_restore_stays_refused_across_processes",
    "authority_host_service::generation_initial::run_start_retention::tests::root_run_start_historical_join_cannot_skip_or_swallow_physical_read",
    "authority_host_runtime::session::q24_model::cold_root_tests::root_q24_factory_v2_cold_reopens_original_files_with_new_root_and_writer",
    "authority_host_runtime::session::q24_model::cold_root_tests::root_q24_factory_v2_cold_missing_witness_never_reinitializes",
    "authority_host_service::generation_publication::refusal::tests::root_publication_refusal_cold_restore_rejects_after_observed_primary_corruption",
    "authority_host_service::generation_publication::refusal::tests::root_publication_refusal_cross_handle_attempts_and_missing_marker_fail_closed",
    "authority_host_service::generation_publication::grant_store::tests::root_publication_grant_attempt_survives_process_exit_without_new_nonce",
    "authority_host_service::generation_publication::grant_store::tests::root_publication_grant_retains_actual_signature_and_reopen_never_issues",
    "authority_host_service::generation_publication::grant_store::tests::root_publication_grant_recovery_refuses_missing_and_substituted_profile",
    "root_production_handoff::independent_b_source::fresh_rights_tests::original_b_source_fresh_handoff_requires_six_exact_original_rights",
    "root_independent_b_notice::terminal_tests::original_b_source_terminal_notice_allows_exit_after_real_frame_postcheck",
    "root_independent_b_notice::terminal_tests::original_b_source_terminal_missing_notice_never_completes"
]
ACCEPTANCE_PARENTS = [
    "authority_host_service::generation_publication::refusal::tests::acceptance::root_completed_publication_missing_acceptance_cannot_be_backfilled",
    "authority_host_service::generation_publication::refusal::tests::acceptance::root_completed_publication_missing_lock_is_not_repaired"
]
NATIVE_ORDER = ['ordinary-a', 'ordinary-post-a-adopt', 'ordinary-post-a-no-update',
                'ordinary-whole-cold', 'root47', 'seven-libs']


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


def snapshot():
    digest = hashlib.sha256()
    count = 0
    for entry in git('ls-files', '-s', '-z').split(b'\0'):
        if not entry:
            continue
        meta, name = entry.split(b'\t', 1)
        path = REPO / os.fsdecode(name)
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        digest.update(meta.split()[0] + b'\0' + name + b'\0' + hashlib.sha256(data).digest())
        count += 1
    return dict(head=git('rev-parse', 'HEAD').decode().strip(),
                tree=git('rev-parse', 'HEAD^{tree}').decode().strip(),
                status=git('status', '--porcelain', '--untracked-files=all').decode(),
                tracked_files=count, tracked_sha256=digest.hexdigest())


result = None
collect = None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def attempt(name, action):
    """A failed stage is retained and never suppresses subsequent stages."""
    item = dict(started=utc(), status='running')
    result['checks'][name] = item
    persist()
    started = time.monotonic()
    try:
        passed = action()
        item.update(status='passed' if passed else 'failed', passed=bool(passed))
    except Exception as error:
        item.update(status='failed', passed=False, error=repr(error))
        (OUT / (name + '-driver-error.log')).write_text(traceback.format_exc())
    finally:
        item.update(finished=utc(), elapsed_seconds=time.monotonic() - started)
        persist()
    return item.get('passed', False)


def save(path, value):
    pending = path.with_suffix(path.suffix + '.tmp')
    pending.write_text(json.dumps(value, indent=2) + '\n')
    pending.replace(path)


def persist():
    save(OUT / 'result.json', result)


def command(name, argv, cwd=None):
    cwd = REPO if cwd is None else cwd
    item = dict(name=name, command=argv, cwd=str(cwd), started=utc(), status='running', launcher_uid=os.getuid())
    started = time.monotonic()
    result['stages'].append(item)
    persist()
    try:
        with (OUT / (name + '.stdout.log')).open('xb') as stdout, (OUT / (name + '.stderr.log')).open('xb') as stderr:
            child = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr)
            item['pid'] = child.pid
            persist()
            code = child.wait()
    except Exception as error:
        item.update(status='launch_failed', error=repr(error), finished=utc(),
                    elapsed_seconds=time.monotonic() - started)
        persist()
        raise
    item.update(status='completed', exit_code=code, finished=utc(), elapsed_seconds=time.monotonic() - started)
    persist()
    return code


def restore_ownership():
    paths = [str(p) for p in [TARGET, OUT, REPO / 'codex-rs/target/nextest'] if p.exists()]
    subprocess.run(['sudo', '-n', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', *paths], check=True)


def test(name, arguments, expected=None):
    source_before = snapshot()
    save(OUT / (name + '-source-before.json'), source_before)
    require(source_before == result['before'], 'source changed before this exact test stage')
    restore_ownership()
    reports = [TARGET / 'nextest/local/junit.xml', REPO / 'codex-rs/target/nextest/local/junit.xml']
    for index, report in enumerate(reports):
        if report.exists():
            report.rename(OUT / f'{name}-prior-junit-{index}-excluded.xml')
    argv = ['python3', 'scripts/hepta_ci_exec.py', '--timeout-seconds', '7200',
            '--minimum-tests', '1', '--output', str(OUT / (name + '.json')), '--',
            'just', 'test', '--locked', '--offline', *arguments, '--retries', '0',
            '--success-output', 'final', '--failure-output', 'final', '--no-tests', 'fail']
    root = expected is not None
    if root:
        keys = ['PATH', 'SOURCE_SHA', 'TESTED_SHA', 'HEPTA_CI_LANE', 'PYTHONDONTWRITEBYTECODE',
                'CARGO_INCREMENTAL', 'CARGO_BUILD_JOBS', 'CARGO_TARGET_DIR', 'CARGO_NET_OFFLINE',
                'RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH', 'LIBCLANG_PATH',
                'RUSTUP_TOOLCHAIN', 'BINDGEN_EXTRA_CLANG_ARGS', 'RUSTFLAGS', 'LD_LIBRARY_PATH']
        environment = {key: os.environ[key] for key in keys if key in os.environ}
        environment.update(CARGO_HOME=os.environ.get('CARGO_HOME', '/home/qq/.cargo'),
                           RUSTUP_HOME=os.environ.get('RUSTUP_HOME', '/home/qq/.rustup'),
                           GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='safe.directory',
                           GIT_CONFIG_VALUE_0=str(REPO),
                           HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=str(ROOT / 'bind'),
                           HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE=str(ROOT / 'source'),
                           HEPTA_Q24_FACTORY_WITNESS_BIND=str(ROOT / 'witness-bind'),
                           HEPTA_Q24_FACTORY_WITNESS_SOURCE=str(ROOT / 'witness-source'),
                           HEPTA_CHECKPOINT_TEST_ROOT=str(ROOT / 'checkpoints'),
                           HEPTA_ORDINARY_SOURCE_COMMIT=HEAD, HEPTA_ORDINARY_SOURCE_TREE=TREE)
        # Only this attempt's verified helper/pinned product environment is
        # exported. Failed preparation leaves explicit unavailable paths.
        for binary_name in ('codex-hepta-agentd', 'hepta-authority-host', 'hepta-joint-propose'):
            for variant in (binary_name, binary_name.replace('-', '_')):
                key = 'CARGO_BIN_EXE_' + variant
                environment[key] = os.environ[key]
        wrapper = "import os,runpy,sys; assert os.geteuid()==0; print('Root test uid=0',flush=True); runpy.run_path(sys.argv.pop(1),run_name='__main__')"
        argv = ['sudo', '-n', 'env', '-i', *(k + '=' + v for k, v in sorted(environment.items())),
                'python3', '-c', wrapper, *argv[1:]]
    save(OUT / (name + '-launch.json'), dict(command=argv, required_euid=0 if root else 1000))
    try:
        code = command(name + '-execution', argv)
    finally:
        if root:
            restore_ownership()
    observed = [p for p in reports if p.exists()]
    collection = dict(status='multiple-fresh-native-reports' if len(observed) > 1
                      else 'missing-fresh-native-report', paths=[str(p) for p in observed])
    for index, report in enumerate(observed):
        shutil.copyfile(report, OUT / f'{name}-fresh-native-observed-{index}.xml')
    if len(observed) == 1:
        collected = collect(OUT / (name + '.json'), observed[0], OUT / (name + '.xml'))
        collection = json.loads((OUT / (name + '.summary.json')).read_text())
        collection['collector_exit_code'] = collected
        if expected is not None and (OUT / (name + '.xml')).exists():
            cases = list(ET.parse(OUT / (name + '.xml')).iter('testcase'))
            actual = [c.attrib['name'] for c in cases if c.find('skipped') is None]
            coverage = dict(expected=expected, observed=actual, skipped=sum(c.find('skipped') is not None for c in cases), exact=len(cases) == len(expected) and sorted(actual) == sorted(expected))
            save(OUT / (name + '-parent-coverage.json'), coverage)
            collection['exact_parent_coverage'] = coverage['exact']
    save(OUT / (name + '-collection.json'), collection)
    result[name] = dict(command_exit_code=code, collection=collection)
    persist()
    after = snapshot()
    result[name]['source_after'] = after
    result[name]['source_unchanged'] = after == result['before']
    persist()
    return (code == 0 and collection.get('collector_exit_code') == 0
            and collection.get('status') == 'passed'
            and (expected is None or collection.get('exact_parent_coverage') is True)
            and after == result['before'])


def retain_helper_records(stage):
    source = PUBLIC / 'helpers'
    destination = OUT / (stage + '-preparation-records')
    destination.mkdir()
    if source.is_dir():
        for path in sorted(source.iterdir()):
            if path.is_file():
                shutil.copyfile(path, destination / path.name)


def build_helpers(helper):
    try:
        return command('helper-build', helper) == 0
    finally:
        # The helper keeps Cargo stderr in its own directory even on failure.
        # Preserve those raw records, not just the outer process error message.
        retain_helper_records('helper-build')


def verify_and_load_helpers(helper):
    for path in (PUBLIC / 'helpers', PUBLIC / 'helpers/bin'):
        if path.exists():
            path.chmod(0o755)
    try:
        code = command('helper-verify', [*helper, '--verify-only'])
    finally:
        retain_helper_records('helper-verify')
    if code != 0:
        return False
    environment = json.loads((PUBLIC / 'helpers/env.json').read_text())
    os.environ.update(environment)
    for key, value in environment.items():
        os.environ[key.replace('-', '_')] = value
    for filename in ('env.json', 'manifest.json'):
        shutil.copyfile(PUBLIC / 'helpers' / filename, OUT / ('helper-' + filename))
    return snapshot() == result['before']


def prepare_products():
    binaries = {'codex-hepta-agentd', 'hepta-authority-host'}
    argv = ['cargo', 'build', '--locked', '--offline', '-p', 'codex-hepta-agentd',
            '--bin', 'codex-hepta-agentd', '--bin', 'hepta-authority-host',
            '--message-format=json-render-diagnostics']
    assert command('product-build', argv, REPO / 'codex-rs') == 0, 'actual product build failed'
    artifacts, finished = {}, None
    (PUBLIC / 'bin').mkdir(mode=0o755)
    for line in (OUT / 'product-build.stdout.log').read_text().splitlines():
        record = json.loads(line)
        if record.get('reason') == 'build-finished':
            finished = record.get('success')
        target = record.get('target', {})
        name = target.get('name')
        if record.get('reason') != 'compiler-artifact' or name not in binaries or not record.get('executable'):
            continue
        assert 'bin' in target['kind'] and not record['profile']['test']
        source = Path(record['executable'])
        assert source.is_absolute() and source.is_file()
        pinned = PUBLIC / 'bin' / name
        digest = hashlib.sha256()
        with source.open('rb') as stream, pinned.open('xb') as output:
            before = os.fstat(stream.fileno())
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        assert all(getattr(before, k) == getattr(after, k) for k in fields)
        pinned.chmod(0o555)
        with pinned.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest.hexdigest()
        assert pinned.stat().st_size == before.st_size and stat.S_ISREG(before.st_mode)
        artifacts[name] = dict(package_id=record['package_id'], profile=record['profile'],
                               compiler_executable=str(source), pinned=str(pinned),
                               bytes=before.st_size, sha256=digest.hexdigest())
    assert finished is True and set(artifacts) == binaries
    save(PUBLIC / 'product-manifest.json', dict(head=HEAD, tree=TREE, artifacts=artifacts))
    environment = {f'CARGO_BIN_EXE_{variant}': a['pinned'] for name, a in artifacts.items()
                   for variant in {name, name.replace('-', '_')}}
    save(PUBLIC / 'product-env.json', environment)
    save(OUT / 'product-manifest.json', dict(head=HEAD, tree=TREE, artifacts=artifacts))
    save(OUT / 'product-env.json', environment)
    os.environ.update(environment)
    return snapshot() == result['before']



def require_roster():
    workflow = (REPO / '.github/workflows/hepta-daemon-learning-native.yml').read_text()
    match = re.search(r'          parents = (\[.*?\n          \])', workflow, re.S)
    require(match is not None, 'actual workflow parent roster missing')
    parents = ast.literal_eval(match[1])
    require(parents == WORKFLOW_PARENTS, 'actual workflow roster changed; review exact names')
    parents = parents + ACCEPTANCE_PARENTS
    require(len(parents) == len(set(parents)) == 47, 'exact 45 plus two acceptance parents required')
    config = tomllib.loads((REPO / 'codex-rs/.config/nextest.toml').read_text())
    cold = [row for row in config['profile']['default']['overrides']
            if row.get('filter') == 'package(codex-hepta-agentd) & test(=' + COLD_PARENT + ')']
    require(len(cold) == 1 and cold[0]['slow-timeout'] == {'period': '30s', 'terminate-after': 16}
            and cold[0].get('retries') == 0, 'original eight-minute cold harness differs')
    save(OUT / 'root47-parent-roster.json', parents)
    save(OUT / 'ordinary-parent-roster.json', [A_PARENT, ADOPT_PARENT, NO_UPDATE_PARENT, COLD_PARENT])
    save(OUT / 'original-nextest-budgets.json', config)
    return parents


def prepare_library_binaries():
    # UID1000 compilation/listing only, no test execution and no PASS inferred.
    # The later test commands remain actual repository just test invocations.
    argv = ['cargo', 'nextest', 'list', '--locked', '--offline',
            *(item for p in PACKAGES for item in ['-p', p]), '--lib',
            '--list-type', 'binaries-only', '--message-format', 'json']
    code = command('library-binaries-build-uid1000', argv, REPO / 'codex-rs')
    return code == 0 and snapshot() == result['before']


def setup_mounts():
    setup = """import os,pathlib,subprocess,json
assert os.geteuid()==0
root=pathlib.Path(%r);root.mkdir(mode=0o700)
for name in ['source','bind','witness-source','witness-bind','checkpoints']:(root/name).mkdir(mode=0o700)
for source,target in [('source','bind'),('witness-source','witness-bind')]:
 subprocess.run(['mount','--bind',str(root/source),str(root/target)],check=True)
 assert (root/source).stat().st_dev==(root/target).stat().st_dev
 assert (root/source).stat().st_ino==(root/target).stat().st_ino
rows=[line for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines() if str(root) in line]
assert len(rows)==2
print(json.dumps({'uid':os.geteuid(),'root':str(root),'actual_mountinfo':rows}))
""" % str(ROOT)
    return command('root-mount-setup', ['sudo', '-n', 'python3', '-c', setup]) == 0


def source_check(name, argv):
    before = snapshot()
    save(OUT / (name + '-source-before.json'), before)
    require(before == result['before'], 'source changed before this exact source-check stage')
    code = command(name, argv)
    observed = snapshot()
    result[name] = dict(exit_code=code, source_after=observed,
                        source_unchanged=observed == result['before'])
    persist()
    return code == 0 and observed == result['before']


def main():
    global result, collect
    require(re.fullmatch(r'[0-9a-f]{40}', HEAD) is not None, 'instantiate exact HEAD')
    require(re.fullmatch(r'[0-9a-f]{40}', TREE) is not None, 'instantiate exact tree')
    require(REPO.is_absolute() and FIX_RECORD.is_absolute(), 'instantiate absolute source and prior fix record')
    require(re.fullmatch(r'[a-z0-9][a-z0-9-]{3,70}', RUN_ID) is not None, 'instantiate a new unique run ID')
    require(not any(tag in RUN_ID for tag in ('448f9bd3', 'f07963e4', '4851ff07', '1d6e4d5c')),
            'do not reuse a prior diagnostic run namespace')
    OUT.mkdir(parents=True, exist_ok=False)
    result = dict(status='preflight', started=utc(), head=HEAD, tree=TREE, uid=os.getuid(),
                  target=str(TARGET), stages=[], checks={}, native_order=NATIVE_ORDER,
                  scope='Actual ordinary A, Adopt, completed independent-B NoUpdate, whole daemon+Root cold, exact Root47, seven library packages, all source QA and authoritative complete caller CLI. No native or whole result is inferred from build/listing or template validation.')
    persist()
    started = time.monotonic()
    owner = None
    mounts_attempted = False
    try:
        require(os.getuid() == os.geteuid() == 1000, 'build and driver require actual UID1000')
        require(TARGET.is_dir(), 'original exclusive target missing')
        owner = (TARGET / '.hepta-root-native-owner.lock').open('a+b')
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (TARGET / 'debug/.cargo-lock').open('rb') as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe, fcntl.LOCK_UN)
        result['before'] = snapshot()
        require(result['before']['head'] == HEAD and result['before']['tree'] == TREE
                and not result['before']['status'], 'source must equal clean frozen HEAD/tree')
        fix = json.loads(FIX_RECORD.read_text())
        require(fix['status'] == 'completed' and fix['exit_code'] == 0 and fix['source_unchanged'],
                'matching exact-source scoped fix is not complete and successful')
        require(all(value == fix['before'][key] for key, value in result['before'].items()),
                'matching fix/source snapshot differs')
        result['prior_fix_record'] = dict(path=str(FIX_RECORD), sha256=hashlib.sha256(FIX_RECORD.read_bytes()).hexdigest())
        original = json.loads((BASE / 'env.json').read_text())
        os.environ.update({key: value for key, value in original.items() if isinstance(value, str)})
        for key in list(os.environ):
            if key.startswith('CARGO_PROFILE_') or key.startswith('CARGO_BIN_EXE_'):
                del os.environ[key]
        os.environ.update(RUSTUP_TOOLCHAIN='1.96.0', CARGO_BUILD_JOBS='1', CARGO_INCREMENTAL='0',
                          CARGO_TARGET_DIR=str(TARGET), CARGO_NET_OFFLINE='true',
                          SOURCE_SHA=HEAD, TESTED_SHA=HEAD, HEPTA_CI_LANE='source-head',
                          PYTHONDONTWRITEBYTECODE='1', GIT_TERMINAL_PROMPT='0')
        os.environ['PATH'] = str(BASE / 'bin') + ':/home/qq/.cargo/bin:' + os.environ['PATH']
        recorded_environment = ['PATH', 'RUSTUP_TOOLCHAIN', 'CARGO_HOME', 'RUSTUP_HOME',
            'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL', 'CARGO_TARGET_DIR', 'CARGO_NET_OFFLINE',
            'RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH', 'LIBCLANG_PATH',
            'BINDGEN_EXTRA_CLANG_ARGS', 'RUSTFLAGS', 'LD_LIBRARY_PATH']
        result['environment'] = {key: os.environ[key] for key in recorded_environment if key in os.environ}
        result['environment_file_sha256'] = hashlib.sha256((BASE / 'env.json').read_bytes()).hexdigest()
        result['cargo_profile_overrides'] = {key: value for key, value in os.environ.items()
                                             if key.startswith('CARGO_PROFILE_')}
        for name in ('codex-hepta-agentd', 'hepta-authority-host', 'hepta-joint-propose'):
            for variant in (name, name.replace('-', '_')):
                os.environ['CARGO_BIN_EXE_' + variant] = str(PUBLIC / 'unprepared' / name)
        os.chdir(REPO)
        sys.path.insert(0, str(REPO / 'scripts'))
        from hepta_ci_junit import collect as native_collect
        collect = native_collect
        parents = require_roster()
        PUBLIC.mkdir(mode=0o755)
        result.update(status='preparing', driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        persist()
        helper = ['python3', 'scripts/hepta_cell_test_helpers.py', '--package',
                  'codex-hepta-infer-worker-host', '--output-dir', str(PUBLIC / 'helpers')]
        attempt('helper-build', lambda: build_helpers(helper))
        attempt('helper-verify-and-load', lambda: verify_and_load_helpers(helper))
        attempt('product-build-and-pin', prepare_products)
        attempt('library-binaries-build-uid1000', prepare_library_binaries)
        mounts_attempted = True
        attempt('root-mount-setup', setup_mounts)
        result['status'] = 'testing'
        persist()
        root_args = ['-p', 'codex-hepta-agentd', '-p', 'codex-hepta-contracts', '--lib',
                     '--run-ignored', 'only', '--test-threads', '1', '-E']
        schedule = [('ordinary-a', [A_PARENT]), ('ordinary-post-a-adopt', [ADOPT_PARENT]),
                    ('ordinary-post-a-no-update', [NO_UPDATE_PARENT]),
                    ('ordinary-whole-cold', [COLD_PARENT]), ('root47', parents)]
        for name, expected in schedule:
            attempt(name, lambda name=name, expected=expected: test(
                name, [*root_args, ' | '.join(f'test(={p})' for p in expected)], expected))
        attempt('seven-libs', lambda: test('seven-libs',
            [*(item for p in PACKAGES for item in ['-p', p]), '--lib', '--test-threads', '2']))
        attempt('fullsource', lambda: source_check('fullsource', ['python3', '-m', 'unittest',
            'discover', '-s', 'qa/b4-no-bypass', '-p', 'test_*.py', '-v']))
        attempt('fullcallers', lambda: source_check('fullcallers', ['python3',
            'scripts/verify_hepta_callers.py', 'verify', '--root', str(REPO)]))
        result['status'] = 'completed'
    except BaseException as error:
        result.update(status='driver_failed', error=repr(error))
        (OUT / 'driver-error.log').write_text(traceback.format_exc())
    finally:
        if mounts_attempted:
            try:
                cleanup = []
                for name in ('witness-bind', 'bind'):
                    active = [line.split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()]
                    if str(ROOT / name) not in active:
                        continue
                    p = subprocess.run(['sudo', '-n', 'umount', str(ROOT / name)], capture_output=True, text=True)
                    cleanup.append(dict(path=str(ROOT / name), code=p.returncode, stdout=p.stdout, stderr=p.stderr))
                save(OUT / 'mount-cleanup.json', cleanup)
                if any(item['code'] for item in cleanup):
                    result['cleanup_error'] = 'original task mount cleanup failed; raw statuses retained'
            except BaseException as error:
                result['cleanup_error'] = repr(error)
        try:
            result['after'] = snapshot()
            result['source_unchanged'] = result.get('before') == result['after']
        except BaseException as error:
            result['snapshot_error'] = repr(error)
        result.update(finished=utc(), elapsed=time.monotonic() - started)
        result['all_stages_passed'] = (result['status'] == 'completed' and result.get('source_unchanged') is True
            and not result.get('cleanup_error') and all(v.get('passed') is True for v in result['checks'].values()))
        result['logs'] = {}
        for path in sorted(OUT.rglob('*')):
            if path.is_file() and path.name not in ('result.json', 'result.json.tmp'):
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                result['logs'][str(path.relative_to(OUT))] = dict(bytes=path.stat().st_size, sha256=digest)
        persist()
        if owner is not None:
            owner.close()
        print('ROOT_COMPLETED_CHAIN_NATIVE_TERMINAL ' + json.dumps(result), flush=True)
    return 0 if result['all_stages_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
