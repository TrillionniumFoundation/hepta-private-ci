from __future__ import annotations
import ast
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import time

input_bytes = sys.stdin.buffer.read()
data = json.loads(input_bytes)
started_ns = time.monotonic_ns()
deadline = time.monotonic() + 1800
repository = 'TrillionniumFoundation/hepta-private-ci'
base = 'c809b4cec93bd7daa64c2bfe0a2d7af5c886f2b9'
source_sha = 'a568e32ddc9dac056ea4e01befea4ae3fbfc941b'
source_tree = '7bc2260ffabc88a3a7db0046cb5c8734257247fd'
source_parent = 'dde6cc8247727eb30102f097bd9a798f607bbc38'
journal_evidence = 'cdc7eaa3ef7f6457270be06bbce5203d196205fb'
test_name = 'provider_receipt_tests::taskflow_step_reconcile_waits_for_writer_without_blocking_reads'
selector = 'test(=' + test_name + ')'
sourceprep = pathlib.Path('/data/root-provider-context-20261112-df05-v10-sourceprep')
seed = sourceprep / 'host'
prior_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v12-evidence')
prior_diagnostic = pathlib.Path('/data/root-provider-context-20261112-df05-concurrency-v1')
control = pathlib.Path('/data/root-provider-context-20261112-df05-step-control-v1')
evidence = control / 'private'
source = control / 'source'
prior_target = pathlib.Path('/data/root-provider-context-20261112-df05-v10-target')
target = prior_target
target_policy = None
expected_target_identity = None
if 'NEXTEST_RETRIES' in os.environ:
    raise RuntimeError('unreviewed NEXTEST_RETRIES override prevents the fixed attempt bound')
env = {
    **{k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
    'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0', 'GH_HOST': 'github.com',
    'PATH': '/home/qian-qi/.cargo/bin:' + os.environ.get('PATH', ''),
    'RUSTUP_TOOLCHAIN': '1.96.0', 'CARGO_BUILD_JOBS': '2',
    'CARGO_PROFILE_DEV_DEBUG': '0', 'CARGO_PROFILE_TEST_DEBUG': '0',
    'CARGO_INCREMENTAL': '0', 'NEXTEST_TEST_THREADS': '2', 'CARGO_TERM_COLOR': 'never',
    'CARGO_TARGET_DIR': str(target),
}
ROOT = seed
Path = pathlib.Path
CURRENT_SOURCE_ROOT = seed
SOURCE_OBSERVATIONS = []

helper_bytes = (prior_evidence / 'reviewed-helper-program.txt').read_bytes()
helper_sha = 'c65534e21bdd9b00fcb3985a90d0d33cb0fc226e969626726cb83e984c18e61b'
if hashlib.sha256(helper_bytes).hexdigest() != helper_sha:
    raise RuntimeError('reviewed helper input changed')
helper_names = {
    'emit', 'gitcmd', 'git', 'plain_git_bytes', 'plain_git', 'write', 'actor',
    'origin', 'tree_map', 'sized_tree_map', 'tree_digest', 'oid_bytes',
    'no_hold', 'repository_guard', 'flags_clear', 'ancestor_guard',
    '_fingerprint', '_tracked_blob', 'physical', 'verify_source', 'clean',
    '_source_error', '_wait_without_reaping', '_darwin_only_exited_leader',
    'owned_run', 'materialize', 'remote_ref',
}
tree = ast.parse(helper_bytes.decode('utf-8'))
definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in helper_names]
if {n.name for n in definitions} != helper_names or len(definitions) != len(helper_names):
    raise RuntimeError('reviewed helper selection changed')
exec(compile(ast.Module(body=definitions, type_ignores=[]), '<exact-reviewed-helpers>', 'exec'))

def no_hold():
    if os.path.lexists(sourceprep / 'PREPARATION_HOLD'):
        raise RuntimeError('explicit preparation HOLD exists')
    source_roots = [seed, sourceprep / 'journal', source,
                    pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v3'),
                    pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v6'),
                    pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v6-journal'), prior_diagnostic / 'source']
    for root in source_roots:
        if os.path.lexists(root / 'ROOT_PROVIDER_CONTEXT_VALIDATION_HOLD'):
            raise RuntimeError('explicit source HOLD exists')
    outputs = [control, evidence, prior_diagnostic, prior_diagnostic / 'private']
    outputs += [pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v' + str(i) + '-evidence') for i in (4, 5, 6, 7)]
    outputs += [pathlib.Path('/data/root-provider-context-20261112-df05-v' + str(i) + '-evidence') for i in range(7, 13)]
    for output in outputs:
        if os.path.lexists(output / 'PUBLICATION_HOLD'):
            raise RuntimeError('explicit observation HOLD exists')

def read_stable(path, expected=None):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise RuntimeError('evidence is not a single regular file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        with os.fdopen(os.dup(fd), 'rb') as stream:
            payload = stream.read()
        if _fingerprint(before) != _fingerprint(opened) or _fingerprint(opened) != _fingerprint(os.fstat(fd)) or _fingerprint(opened) != _fingerprint(path.lstat()):
            raise RuntimeError('evidence changed during read')
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if expected is not None and (len(payload) != expected['bytes'] or hashlib.sha256(payload).hexdigest() != expected['sha256']):
        raise RuntimeError('evidence byte identity changed')
    return payload

def select_target():
    global target, target_policy, expected_target_identity
    try:
        info = prior_target.lstat()
    except FileNotFoundError:
        target = control / 'target'
        if os.path.lexists(target):
            raise RuntimeError('fresh diagnostic target already exists')
        target_policy = 'fresh_after_prior_actual_target_was_observed_absent'
        expected_target_identity = None
        admission = {'path': str(target), 'lexists': False, 'prior_path': str(prior_target), 'prior_path_observed_absent': True,
                     'policy': target_policy, 'cache_reuse_claimed': False, 'created_by_preflight': False}
    else:
        identity = (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode))
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid() or identity != (2067, 47972373, 0o700):
            raise RuntimeError('existing prior target changed identity or type; no fallback overwrite')
        target = prior_target
        target_policy = 'reuse_observed_prior_actual_target_after_closed_owner'
        expected_target_identity = identity
        admission = {'path': str(target), 'lexists': True, 'device': info.st_dev, 'inode': info.st_ino,
                     'mode': oct(stat.S_IMODE(info.st_mode)), 'policy': target_policy, 'cache_reuse_claimed': True}
    env['CARGO_TARGET_DIR'] = str(target)
    return admission

def target_snapshot(allow_missing=False, allow_first_creation=False):
    global expected_target_identity
    try:
        info = target.lstat()
    except FileNotFoundError:
        if allow_missing and expected_target_identity is None and target_policy == 'fresh_after_prior_actual_target_was_observed_absent':
            return {'path': str(target), 'policy': target_policy, 'lexists': False, 'is_directory': False,
                    'created_by_preflight': False, 'scope': 'planned fresh directory; no Cargo creation observed yet'}
        raise RuntimeError('required actual diagnostic target is absent')
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError('diagnostic target is not an owned regular directory')
    identity = (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode))
    first = expected_target_identity is None
    if first:
        if not allow_first_creation or target_policy != 'fresh_after_prior_actual_target_was_observed_absent':
            raise RuntimeError('fresh target appeared before the admitted Cargo inventory')
        expected_target_identity = identity
    elif identity != expected_target_identity:
        raise RuntimeError('actual diagnostic target changed identity')
    return {'path': str(target), 'policy': target_policy, 'device': info.st_dev, 'inode': info.st_ino,
            'mode': oct(stat.S_IMODE(info.st_mode)), 'lexists': True, 'is_directory': True, 'is_symlink': False,
            'first_directory_observation_after_cargo': first,
            'scope': 'directory identity observation; not independent proof of every compiler environment'}

def command(root, expected_source, args, log, cap_seconds, command_env=None, requires_target=False, first_cargo_creation=False):
    global CURRENT_SOURCE_ROOT, SOURCE_OBSERVATIONS
    CURRENT_SOURCE_ROOT = root
    SOURCE_OBSERVATIONS = []
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        raise RuntimeError('independent diagnostic time budget exhausted')
    no_hold()
    target_snapshot(allow_missing=expected_target_identity is None)
    result = owned_run(args, log, timeout=min(cap_seconds, remaining), env=command_env or env,
                       cwd=root / 'codex-rs', expected_source=expected_source)
    result.update(source_commit=expected_source, source_observations=list(SOURCE_OBSERVATIONS),
                  owned_cleanup_completed=result['executed'],
                  process_owner_boundary='retained leader through last group signal; not a sandbox; escaped sessions and kernel cleanup latency outside contract')
    target_error = None
    try:
        result['target_observation'] = target_snapshot(allow_missing=not requires_target, allow_first_creation=first_cargo_creation)
    except (OSError, RuntimeError) as error:
        target_error = str(error)
        result['target_observation'] = {'path': str(target), 'error': target_error}
    result['target_required_for_this_command'] = requires_target
    result['target_condition_met'] = target_error is None
    payload = read_stable(log)
    result['log_bytes'] = len(payload)
    result['log_sha256'] = hashlib.sha256(payload).hexdigest()
    write(log.with_suffix(log.suffix + '.receipt.json'), json.dumps(result, indent=2))
    emit({'phase': 'diagnostic_command_finished', **result})
    if not all(result.get(k) is True for k in ('executed', 'source_before_verified', 'source_after_verified', 'source_verified', 'owned_cleanup_completed')):
        raise RuntimeError('diagnostic source or owner failed; no following command')
    if target_error is not None:
        raise RuntimeError('diagnostic target condition failed; receipt preserved; no following command')
    return result, payload

def parent_list(root, sha):
    return git(root, 'show', '-s', '--format=%P', sha).split()

def inventory_matches(payload):
    value = json.loads(payload)
    if not isinstance(value, dict) or not isinstance(value.get('rust-suites'), dict):
        raise RuntimeError('Unknown nextest inventory schema')
    if value.get('rust-build-meta', {}).get('target-directory') != str(target):
        raise RuntimeError('inventory target does not bind the observed private target')
    matches = []
    for binary_id, suite in value['rust-suites'].items():
        if not isinstance(suite, dict) or suite.get('binary-id') != binary_id or not isinstance(suite.get('testcases'), dict):
            raise RuntimeError('Unknown nextest suite schema')
        for name, case in suite['testcases'].items():
            if not isinstance(case, dict) or type(case.get('ignored')) is not bool or not isinstance(case.get('filter-match'), dict):
                raise RuntimeError('Unknown nextest case schema')
            status = case['filter-match'].get('status')
            if status not in ('matches', 'mismatch'):
                raise RuntimeError('Unknown nextest filter status')
            if status == 'matches':
                matches.append({'binary_id': binary_id, 'package': suite.get('package-name'), 'suite_status': suite.get('status'), 'test_name': name, 'ignored': case['ignored']})
    if len(matches) != 1 or matches[0]['package'] != 'codex-hepta-automation' or matches[0]['suite_status'] != 'listed' or matches[0]['test_name'] != test_name or matches[0]['ignored'] is not False:
        raise RuntimeError('inventory did not select exactly the one existing concurrent test')
    return matches


reviewed_v12 = read_stable(prior_evidence / 'qualified-wrapper-program.txt', {
    'bytes': 70671, 'sha256': '483f5d46913306717097805c533fcfbde5b45360139d7ceebbbb3ecbdfcf1aa7'})
v12_helpers = {'apply_candidate', 'identity_map', 'effective_identity', 'snapshot_hooks'}
v12_ast = ast.parse(reviewed_v12.decode('utf-8'))
v12_definitions = [n for n in v12_ast.body if isinstance(n, ast.FunctionDef) and n.name in v12_helpers]
if len(v12_definitions) != len(v12_helpers) or {n.name for n in v12_definitions} != v12_helpers:
    raise RuntimeError('reviewed v12 helper selection changed')
exec(compile(ast.Module(body=v12_definitions, type_ignores=[]), '<exact-reviewed-v12-helpers>', 'exec'))
identity_pattern = r'^(user\..*|commit\..*|gpg\..*|core\.hookspath|i18n\..*)$'

no_hold()
argv = pathlib.Path('/proc/self/cmdline').read_bytes().split(b'\0')
if len(argv) < 3 or argv[1] != b'-c' or hashlib.sha256(argv[2]).hexdigest() != data['wrapper_sha256']:
    raise RuntimeError('actual diagnostic program differs from fixed input')
prior_terminal_raw = data['prior_v12_terminal_raw'].encode('utf-8')
if hashlib.sha256(prior_terminal_raw).hexdigest() != data['prior_v12_terminal_sha256']:
    raise RuntimeError('prior v12 terminal bytes changed')
terminal = json.loads(prior_terminal_raw)
if terminal.get('job_id') != '1a1cfc6f0ef-2564-1ab0' or terminal.get('state') != 'succeeded' or terminal.get('exit_code') != 0 or not all(terminal.get(k) is True for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed')):
    raise RuntimeError('live or unconfirmed v12 owner prohibits diagnostic target reuse')
host_evidence = data['prior_host_evidence_sha']
if re.fullmatch(r'[0-9a-f]{40}', host_evidence) is None or parent_list(seed, host_evidence) != [source_sha] or parent_list(seed, source_sha) != [source_parent] or git(seed, 'rev-parse', source_sha + '^{tree}') != source_tree:
    raise RuntimeError('actual prior host source/evidence identity changed')
if parent_list(seed, source_parent) != ['b852e985605f9521ca52509d2e69ebf2b0188ed5', journal_evidence]:
    raise RuntimeError('actual reviewed host merge changed')
actor()
origin(seed)
clean(seed, host_evidence)
if remote_ref(seed, 'fix/hepta-provider-context-host-20261112-df05') != host_evidence:
    raise RuntimeError('published host evidence head changed')
if pathlib.Path(git(seed, 'rev-parse', '--path-format=absolute', '--git-common-dir')) != sourceprep / 'repo.git':
    raise RuntimeError('owned metadata changed')
if pathlib.Path(git(seed, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks')) != pathlib.Path('/home/qian-qi/work/ctrl-cargo-security-20261110-gpt6/.git/hooks'):
    raise RuntimeError('normal native checkout hook path changed')
source_map = tree_map(seed, source_sha)
evidence_map = tree_map(seed, host_evidence)
prefix = 'evidence/root-provider-context-20261112-df05/native-host-v12/'
added = set(evidence_map) - set(source_map)
if not added or any(not p.startswith(prefix) for p in added) or {p: v for p, v in evidence_map.items() if p not in added} != source_map:
    raise RuntimeError('previous evidence child changed complete source')
manifest_bytes = subprocess.check_output(gitcmd(seed, 'show', host_evidence + ':' + prefix + 'sha256-manifest.json'), env=env)
if read_stable(prior_evidence / 'host/sha256-manifest.json') != manifest_bytes:
    raise RuntimeError('previous local and published manifests differ')
manifest = json.loads(manifest_bytes)
snapshots = {}
for name, spec in manifest.items():
    if pathlib.PurePosixPath(name).name != name:
        raise RuntimeError('prior artifact name is not a single component')
    payload = read_stable(prior_evidence / 'host' / name, spec)
    if payload != subprocess.check_output(gitcmd(seed, 'show', host_evidence + ':' + prefix + name), env=env):
        raise RuntimeError('previous raw evidence differs from published bytes')
    if name in ('summary.json', 'commands.json'):
        snapshots[name] = payload
if set(snapshots) != {'summary.json', 'commands.json'}:
    raise RuntimeError('previous owner receipts missing')
prior_summary = json.loads(snapshots['summary.json'])
prior_commands = json.loads(snapshots['commands.json'])
packages = ['codex-hepta-automation', 'codex-model-provider', 'codex-hepta-agentd']
expected_commands = [['/home/qian-qi/.cargo/bin/just', 'test', '-p', p, '--status-level', 'all', '--final-status-level', 'all'] for p in packages]
expected_commands += [['/home/qian-qi/.cargo/bin/just', 'fix', '-p', p] for p in packages]
expected_commands.append(['/home/qian-qi/.cargo/bin/just', 'fmt', '--base', source_parent])
if [r['command'] for r in prior_commands] != expected_commands or [r['exit_code'] for r in prior_commands] != data['prior_command_exits']:
    raise RuntimeError('previous full-gate commands or outcomes changed')
for receipt in prior_commands:
    if receipt.get('source_commit') != source_sha or receipt.get('timed_out') or not all(receipt.get(k) is True for k in ('executed', 'source_before_verified', 'source_after_verified', 'source_verified', 'owned_cleanup_completed')):
        raise RuntimeError('previous full-gate owner or source remains unclosed')
    if receipt['command'][1] in ('test', 'fix') and (receipt.get('build_target_verified') is not True or receipt.get('build_target_observation') != {'path': str(prior_target), 'lexists': True, 'is_directory': True, 'is_symlink': False, 'device': 2067, 'inode': 47972373, 'mode': '0o700'}):
        raise RuntimeError('previous full-gate target was not observed')
if prior_summary['source_commit'] != source_sha or prior_summary['source_tree'] != source_tree or prior_summary['production_concurrency_fix_applied'] is not False or prior_summary['command_source_and_owner_integrity'] is not True:
    raise RuntimeError('previous source summary differs from reviewed full-gate source')
prior_diagnostic_raw = data['prior_diagnostic_terminal_raw'].encode('utf-8')
if hashlib.sha256(prior_diagnostic_raw).hexdigest() != 'cf866e3acf0ea34583d40ce17f09a977587c9a978d8530614e040217edf31ecf':
    raise RuntimeError('prior diagnostic terminal bytes changed')
prior_diagnostic_terminal = json.loads(prior_diagnostic_raw)
if prior_diagnostic_terminal.get('job_id') != '1a1cfed2efc-2564-1ae9' or prior_diagnostic_terminal.get('state') != 'succeeded' or prior_diagnostic_terminal.get('exit_code') != 0 or not all(prior_diagnostic_terminal.get(k) is True for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed')):
    raise RuntimeError('prior diagnostic owner not authoritatively closed')
diagnostic_summary_bytes = read_stable(prior_diagnostic / 'private/summary.json', {'bytes': 5387, 'sha256': '60148f905e0fc121a7b438aea68b303bdae5f0b8ffb915cfc888584b941cfa90'})
diagnostic_summary = json.loads(diagnostic_summary_bytes)
if diagnostic_summary['source_commit'] != source_sha or diagnostic_summary['completed_invocations'] != 1 or diagnostic_summary['actual_attempts_upper_bound'] != 2 or diagnostic_summary['stop_reason'] != 'first_failure_flaky_diagnostic_or_unknown_observation':
    raise RuntimeError('prior diagnostic source or stop boundary changed')
diagnostic_receipt_bytes = read_stable(prior_diagnostic / 'private/observation-01.log.receipt.json', {'bytes': 2367, 'sha256': '51f297db749cd440b3f20be514cbbc37f138358feade4c1e3aa7e379636fbc9d'})
diagnostic_receipt = json.loads(diagnostic_receipt_bytes)
if diagnostic_receipt['exit_code'] != 100 or diagnostic_receipt['source_commit'] != source_sha or not all(diagnostic_receipt.get(k) is True for k in ('source_before_verified', 'source_after_verified', 'source_verified', 'owned_cleanup_completed', 'target_condition_met')):
    raise RuntimeError('prior diagnostic execution owner not closed')
if diagnostic_receipt['target_observation']['path'] != str(prior_target) or tuple(diagnostic_receipt['target_observation'][k] for k in ('device', 'inode', 'mode')) != (2067, 47972373, '0o700'):
    raise RuntimeError('prior diagnostic actual target differs')
read_stable(prior_diagnostic / 'private/observation-01.log', {'bytes': 67362, 'sha256': '8164aad0874bb9755068f9d8e724b5ebd1950970fb78762e06cd62a6586da51c'})
clean(prior_diagnostic / 'source', source_sha)
clean(sourceprep / 'journal', journal_evidence)
if remote_ref(seed, 'fix/hepta-provider-context-journal-20261112-df05') != journal_evidence:
    raise RuntimeError('published journal evidence changed')
files = data['files']
fixture_path = 'codex-rs/hepta-automation/tests/support/authorized_provider_receipt_tests.rs'
production_path = 'codex-rs/hepta-automation/src/taskflow_step.rs'
fixture_sha256 = '895b06c4989476040f9163e973f191c0feb70034a142cfe64737b0bb779eb182'
if set(files) != {fixture_path} or hashlib.sha256(files[fixture_path].encode('utf-8')).hexdigest() != fixture_sha256:
    raise RuntimeError('reviewed control fixture input changed')
journal_map = tree_map(seed, journal_evidence)
if journal_map[fixture_path] != ('100644', 'blob', 'ccd5f8b09d6caed77d7f575d70eee43bfb39f5a3') or journal_map[production_path] != ('100644', 'blob', 'f359763d2eba77d956448e62af1f184a29e61c08'):
    raise RuntimeError('control preimages differ from exact prior source')
preparation = json.loads(read_stable(sourceprep / 'PREPARED.json', {'bytes': 2703, 'sha256': '689ddd47c9792769b1fffcf34c987557bb0046b715e935cc9550804ef48bd79b'}))
original_identity = identity_map(read_stable(pathlib.Path('/data/root-provider-context-20261112-df05-v9-failure-inspection/host-identity-signing-config-original.bin'), {'bytes': 54, 'sha256': '699f091aef10ffc9aa6b33f3d5f8aabb625b0c31fac5ac791ffec05982928734'}))
hooks = pathlib.Path(preparation['normal_hook_path'])
if hashlib.sha256(json.dumps(snapshot_hooks(hooks), sort_keys=True).encode()).hexdigest() != preparation['normal_hook_snapshot_sha256'] or effective_identity(seed) != {**original_identity, 'core.hookspath': str(hooks)}:
    raise RuntimeError('normal native identity/signing or hooks changed')
target_admission = select_target()
if shutil.disk_usage(control.parent).free < 10 * 1024**3:
    raise RuntimeError('diagnostic target capacity reserve failed')
if os.path.lexists(control):
    raise RuntimeError('diagnostic directory exists; reconcile original operation')
control.mkdir(mode=0o700)
evidence.mkdir(mode=0o700)
write(evidence / 'qualified-program.py', argv[2])
write(evidence / 'input-original.json', input_bytes)
write(evidence / 'target-admission.json', json.dumps(target_admission, indent=2))
write(evidence / 'prior-v12-terminal-original.json', prior_terminal_raw)
write(evidence / 'prior-host-summary.json', snapshots['summary.json'])
write(evidence / 'prior-host-commands.json', snapshots['commands.json'])
write(evidence / 'prior-diagnostic-terminal-original.json', prior_diagnostic_raw)
write(evidence / 'prior-diagnostic-summary.json', diagnostic_summary_bytes)
write(evidence / 'prior-diagnostic-command.json', diagnostic_receipt_bytes)
write(evidence / 'reviewed-fixture.rs', files[fixture_path])
prepared, _ = command(seed, host_evidence, gitcmd(seed, 'worktree', 'add', '--detach', str(source), journal_evidence), evidence / 'checkout.log', 600)
if prepared['exit_code']:
    raise RuntimeError('normal control checkout failed')
materialize(source, journal_evidence, evidence / 'materialization.json')
clean(source, journal_evidence)
if tree_map(source, journal_evidence) != journal_map or effective_identity(source) != {**original_identity, 'core.hookspath': str(hooks)}:
    raise RuntimeError('control checkout differs from original tree or native identity')
if journal_map.get('codex-rs/rustfmt.toml') != ('100644', 'blob', 'f9686f9732d3d48311c41c4fd06b40781928b8ec'):
    raise RuntimeError('original repository formatter configuration changed')
format_receipt, _ = command(source, journal_evidence,
    ['/home/qian-qi/.cargo/bin/rustfmt', '--check', '--config-path', str(source / 'codex-rs/rustfmt.toml'),
     '--config', 'skip_children=true', str(evidence / 'reviewed-fixture.rs')],
    evidence / 'fixture-format-check.log', 60)
if format_receipt['exit_code'] != 0 or read_stable(evidence / 'reviewed-fixture.rs') != files[fixture_path].encode('utf-8'):
    raise RuntimeError('native original-config formatter check failed or fixture changed before C')
source_sha = apply_candidate(source, journal_evidence, [fixture_path], 'test(automation): expose step writer admission under controlled contention')
source_tree = git(source, 'rev-parse', source_sha + '^{tree}')
source_parent = journal_evidence
source_map = tree_map(source, source_sha)
expected_control_map = dict(journal_map)
expected_control_map[fixture_path] = ('100644', 'blob', oid_bytes(files[fixture_path].encode('utf-8')))
if source_map != expected_control_map or source_map[production_path] != journal_map[production_path] or parent_list(source, source_sha) != [journal_evidence]:
    raise RuntimeError('control source changed production or unexpected tree entries')
proof = verify_source(source, source_sha)
pins = {
    'justfile': '5636206c53b44385e731b885eeefa7abedf32493',
    'scripts/run-nextest.py': '952fd964e36af1e713eae04b54d4887695e6dd43',
    'codex-rs/.config/nextest.toml': '26576a3b8ab4575db262c4614227a85eb3068b6c',
}
if any(source_map.get(p, ())[1:] != ('blob', b) for p, b in pins.items()):
    raise RuntimeError('reviewed just, nextest runner or profile changed')
commit_bytes = subprocess.check_output(gitcmd(source, 'cat-file', 'commit', source_sha), env=env)
if hashlib.sha1(b'commit ' + str(len(commit_bytes)).encode() + b'\0' + commit_bytes).hexdigest() != source_sha:
    raise RuntimeError('control commit raw identity changed')
write(evidence / 'source-commit.txt', commit_bytes)
write(evidence / 'source-change.patch', subprocess.check_output(gitcmd(source, 'diff', '--no-ext-diff', '--binary', journal_evidence, source_sha), env=env))
write(evidence / 'source-manifest.json', json.dumps({'source_commit': source_sha, 'source_tree': source_tree, 'source_parent': source_parent, 'complete_mode_blob_map_sha256': tree_digest(source_map), 'physical_source': proof, 'runner_blobs': pins, 'production_preimage': {'path': production_path, 'entry': source_map[production_path]}, 'only_fixture_changed': fixture_path, 'fixture_sha256': fixture_sha256, 'production_concurrency_fix_applied': False}, indent=2))
emit({'phase': 'control_source_frozen', 'source_commit': source_sha, 'source_tree': source_tree, 'source_parent': source_parent, 'fixture_sha256': fixture_sha256, 'production_concurrency_fix_applied': False})

list_exec = "import os,sys\nfd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)\nos.dup2(fd,1)\nos.close(fd)\nos.execvpe(sys.argv[2],sys.argv[2:],os.environ)\n"
inventory_argv = ['/home/qian-qi/.cargo/bin/cargo', 'nextest', 'list', '-p', 'codex-hepta-automation', '-E', selector, '--message-format', 'json']
list_env = {**env, 'NEXTEST_PROFILE': 'local', 'RUST_MIN_STACK': '8388608',
            'CODEX_REPO_ROOT': str(source), 'JUST_SHELL': str(source / 'scripts/just-shell.py')}
inventory_path = evidence / 'inventory.json'
write(evidence / 'inventory-exec-adapter.py', list_exec)
inventory_receipt, _ = command(source, source_sha, ['/usr/bin/python3', '-c', list_exec, str(inventory_path), *inventory_argv], evidence / 'inventory-stderr.log', 600, list_env, requires_target=True, first_cargo_creation=True)
if inventory_receipt['exit_code']:
    raise RuntimeError('inventory command failed; no observations are authorized')
inventory_payload = read_stable(inventory_path)
matches = inventory_matches(inventory_payload)
write(evidence / 'selection.json', json.dumps({'actual_inventory_argv': inventory_argv, 'exec_adapter_sha256': hashlib.sha256(list_exec.encode()).hexdigest(), 'inventory_bytes': len(inventory_payload), 'inventory_sha256': hashlib.sha256(inventory_payload).hexdigest(), 'matches': matches, 'profile': 'local', 'original_default_retries': 1, 'max_attempts_per_invocation': 2, 'nextest_test_threads': 2, 'rust_min_stack': 8388608, 'inventory_is_not_test_execution': True}, indent=2))
emit({'phase': 'diagnostic_inventory_verified', 'source_commit': source_sha, 'selected': matches, 'profile': 'local', 'original_retries': 1})

args = ['/home/qian-qi/.cargo/bin/just', 'test', '-p', 'codex-hepta-automation', '-E', selector, '--status-level', 'all', '--final-status-level', 'all']
receipt, payload = command(source, source_sha, args, evidence / 'control-test.log', 600, requires_target=True)
log_text = re.sub(r'\x1b\[[0-9;]*m', '', payload.decode('utf-8'))
expected_message = 'step write returned before writer admission: Ok(Err(Unavailable))'
try_ids = sorted(set(int(n) for n in re.findall(r'^\s*TRY\s+(\d+)(?:/\d+)?\s+FAIL\b[^\n]*\b' + re.escape(test_name) + r'\s*$', log_text, re.MULTILINE)))
expected_failure = (receipt['exit_code'] == 100 and receipt['timed_out'] is False and try_ids == [1, 2]
                    and log_text.count(expected_message) == 2
                    and bool(re.search(r'^\s*Summary\s+\[[^\n]*\]\s+1 test(?:s)? run:\s+0 passed,\s+1 failed,\s+[0-9]+ skipped\s*$', log_text, re.MULTILINE))
                    and not re.search(r'^\s*(?:PASS|FLAKY)\b[^\n]*\b' + re.escape(test_name) + r'\s*$', log_text, re.MULTILINE))
summary = {
    'schema_version': 1, 'scope': 'one old-production control invocation with the new writer-admission regression; not a full package qualification',
    'source_commit': source_sha, 'source_tree': source_tree, 'source_parent': source_parent,
    'fixture_sha256': fixture_sha256, 'production_preimage_blob': source_map[production_path][2],
    'production_concurrency_fix_applied': False, 'expected_failure_observed': expected_failure,
    'native_candidate_format_check': format_receipt,
    'expected_error': expected_message, 'observed_try_numbers': try_ids,
    'completed_invocations': 1, 'maximum_actual_attempts': 2, 'original_nextest_retries': 1,
    'inherited_nextest_retries_override_present': False, 'receipt': receipt,
    'source_after_physical': verify_source(source, source_sha),
    'target_admission': target_admission, 'final_target_observation': target_snapshot(),
    'elapsed_ns': time.monotonic_ns() - started_ns, 'independent_total_budget_seconds': 1800,
    'publication_performed': False,
    'result_limit': 'The control observes typed Unavailable before writer release; it does not expose the old SQLite extended error code.',
}
write(evidence / 'summary.json', json.dumps(summary, indent=2))
artifact_names = [p for p in sorted(evidence.iterdir()) if p.is_file()]
manifest = {p.name: {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p in artifact_names for b in [read_stable(p)]}
write(evidence / 'sha256-manifest.json', json.dumps(manifest, indent=2))
write(control / 'FINISHED.json', json.dumps({'state': 'EXPECTED_FAILURE_OBSERVED' if expected_failure else 'UNEXPECTED_CONTROL_RESULT', 'source_commit': source_sha, 'source_tree': source_tree, 'source_parent': source_parent, 'fixture_sha256': fixture_sha256, 'summary_path': str(evidence / 'summary.json')}, indent=2))
emit({'phase': 'step_control_complete', 'source_commit': source_sha, 'expected_failure_observed': expected_failure, 'exit_code': receipt['exit_code'], 'completed_invocations': 1, 'maximum_actual_attempts': 2})
if not expected_failure:
    raise RuntimeError('control did not observe the required old failure; preserve and stop without another invocation')
