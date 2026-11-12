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
repository = 'TrillionniumFoundation/hepta-private-ci'
base = 'c809b4cec93bd7daa64c2bfe0a2d7af5c886f2b9'
base_branch = 'fix/hepta-provider-operation-binding-20261030'
branches = {
    'journal': 'fix/hepta-provider-context-journal-20261112-df05',
    'host': 'fix/hepta-provider-context-host-20261112-df05',
}
old_sources = {
    'journal': 'feee5752f7be21edec65eb78927fac75fbcb562d',
    'host': '52ff33898e12c56ce3e11d16398b1e662a57730e',
}
old_trees = {
    'journal': 'ae5a60df73df32d0250734591130116cfde22723',
    'host': '42a9caa5687258dc80acbad2ad71ba4e993a4a23',
}
old_evidence = {
    'journal': '021848e76829d6e84c9d2e5d42156010e81b611d',
    'host': 'a0ee4d04490a74d90aedad82d61dd91dd648d9fb',
}
pr_numbers = {'journal': 6242, 'host': 6244}
sourceprep = pathlib.Path('/data/root-provider-context-20261112-df05-v10-sourceprep')
seed = sourceprep / 'journal'
failed_host_dir = sourceprep / 'host'
seal_root = pathlib.Path('/data/root-provider-context-20261112-df05-v13-failure-seal')
host_dir = seal_root / 'source'
local_branch = 'fix/hepta-provider-context-host-failure-v13-20261112-df05'
journal_dir = sourceprep / 'journal'
prior_v6_host_dir = pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v6')
prior_v6_journal_dir = pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v6-journal')
prior_host_dir = pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v3')
prior_v4_evidence = pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v4-evidence')
prior_v5_evidence = pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v5-evidence')
prior_evidence = pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v6-evidence')
prior_v7_planned_evidence = pathlib.Path('/home/qian-qi/work/root-provider-context-20261112-df05-v7-evidence')
prior_v7_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v7-evidence')
prior_v8_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v8-evidence')
prior_v9_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v9-evidence')
prior_v10_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v10-evidence')
prior_v11_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v11-evidence')
prior_v12_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v12-evidence')
prior_v13_evidence = pathlib.Path('/data/root-provider-context-20261112-df05-v13-evidence')
evidence = seal_root / 'private'
archive = evidence / 'stage'
prefix = 'evidence/root-provider-context-20261112-df05/native-host-v13-failure/'
control_root = pathlib.Path('/data/root-provider-context-20261112-df05-step-control-v1')
diagnostic_root = pathlib.Path('/data/root-provider-context-20261112-df05-concurrency-v1')
target = pathlib.Path('/data/root-provider-context-20261112-df05-v10-target')
if 'NEXTEST_RETRIES' in os.environ:
    raise RuntimeError('unreviewed NEXTEST_RETRIES override')
env = {
    **{k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
    'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0', 'GH_HOST': 'github.com',
    'PATH': '/home/qian-qi/.cargo/bin:' + os.environ.get('PATH', ''),
    'RUSTUP_TOOLCHAIN': '1.96.0', 'CARGO_BUILD_JOBS': '2',
    'CARGO_PROFILE_DEV_DEBUG': '0', 'CARGO_PROFILE_TEST_DEBUG': '0',
    'CARGO_INCREMENTAL': '0', 'NEXTEST_TEST_THREADS': '2',
    'CARGO_TERM_COLOR': 'never', 'CARGO_TARGET_DIR': str(target),
}
ROOT = seed
Path = pathlib.Path
SOURCE_OBSERVATIONS = []
CURRENT_SOURCE_ROOT = None
PUBLIC_HISTORY_NAMES = ('resume-final-stdout.log', 'resume-final-stderr.log', 'v7-admission-stdout.log', 'v7-admission-stderr.log', 'v8-admission-stdout.log', 'v8-admission-stderr.log', 'v9-failure-stderr.log')

# Import only exact previously reviewed helper definitions, never the old main,
# old publisher, or its precommit formatter. The old wrapper file is immutable
# input authenticated by its full SHA256 before any of its definitions execute.
reused_program = (prior_evidence / 'qualified-wrapper-program.txt').read_bytes()
reused_sha256 = 'c65534e21bdd9b00fcb3985a90d0d33cb0fc226e969626726cb83e984c18e61b'
if hashlib.sha256(reused_program).hexdigest() != reused_sha256:
    raise RuntimeError('reviewed native helper program changed')
parsed = ast.parse(reused_program.decode('utf-8'))
helper_names = {
    'emit', 'gitcmd', 'git', 'plain_git_bytes', 'plain_git', 'write', 'actor',
    'origin', 'tree_map', 'sized_tree_map', 'tree_digest', 'oid_bytes',
    'no_hold', 'repository_guard', 'flags_clear', 'ancestor_guard',
    '_fingerprint', '_tracked_blob', 'physical', 'verify_source', 'clean',
    '_source_error', '_wait_without_reaping', '_darwin_only_exited_leader',
    'owned_run', 'materialize', 'remote_ref', 'pr_listing',
}
definitions = [node for node in parsed.body
               if isinstance(node, ast.FunctionDef) and node.name in helper_names]
if {node.name for node in definitions} != helper_names or len(definitions) != len(helper_names):
    raise RuntimeError('reviewed helper set mismatch')
exec(compile(ast.Module(body=definitions, type_ignores=[]), '<exact-reviewed-v6-helpers>', 'exec'))

def no_hold():
    if os.path.lexists(sourceprep / 'PREPARATION_HOLD'):
        raise RuntimeError('explicit preparation HOLD exists')
    for root in (host_dir, failed_host_dir, journal_dir, prior_host_dir, prior_v6_host_dir, prior_v6_journal_dir, control_root / 'source', diagnostic_root / 'source'):
        if os.path.lexists(root / 'ROOT_PROVIDER_CONTEXT_VALIDATION_HOLD'):
            raise RuntimeError('explicit source/publication HOLD exists')
    for output in (evidence, prior_v4_evidence, prior_v5_evidence, prior_evidence, prior_v7_planned_evidence, prior_v7_evidence, prior_v8_evidence, prior_v9_evidence, prior_v10_evidence, prior_v11_evidence, prior_v12_evidence, control_root, control_root / 'private', diagnostic_root, diagnostic_root / 'private', prior_v13_evidence, seal_root):
        if os.path.lexists(output / 'PUBLICATION_HOLD'):
            raise RuntimeError('explicit publication HOLD exists')


def parent_list(path, commit):
    return git(path, 'show', '-s', '--format=%P', commit).split()


def snapshot_hooks(path):
    if not os.path.lexists(path):
        return {'path': str(path), 'exists': False, 'entries': {}}
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError('original hook directory has unsupported type')
    entries = {}
    for item in sorted(path.iterdir()):
        info = item.lstat()
        value = {'mode': oct(stat.S_IMODE(info.st_mode)), 'uid': info.st_uid, 'gid': info.st_gid}
        if stat.S_ISREG(info.st_mode):
            value.update(kind='file', bytes=info.st_size, sha256=hashlib.sha256(item.read_bytes()).hexdigest())
        elif stat.S_ISLNK(info.st_mode):
            value.update(kind='symlink', target=os.readlink(item))
        elif stat.S_ISDIR(info.st_mode):
            value.update(kind='directory')
        else:
            raise RuntimeError('original hooks contain unsupported object')
        entries[item.name] = value
    return {'path': str(path), 'exists': True, 'entries': entries}


def identity_map(raw):
    result = {}
    for entry in raw.split(b'\0'):
        if entry:
            key, value = entry.split(b'\n', 1)
            result[key.decode('utf-8')] = value.decode('utf-8')
    return result


def effective_identity(path):
    result = subprocess.run(gitcmd(path, 'config', '--null', '--get-regexp', identity_pattern), env=env, capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError('effective native identity could not be read')
    return identity_map(result.stdout)


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


def current_pr(stage, expected_head):
    base_name = base_branch if stage == 'journal' else branches['journal']
    matches = pr_listing(branches[stage], base_name, 'all')
    if len(matches) != 1:
        raise RuntimeError('existing Draft identity is ambiguous')
    observed = matches[0]
    if observed['number'] != pr_numbers[stage] or observed['state'] != 'OPEN' or not observed['isDraft'] or observed['headRefOid'] != expected_head:
        raise RuntimeError('existing Draft identity or head drifted')
    expected_url = 'https://github.com/' + repository + '/pull/' + str(pr_numbers[stage])
    if observed['url'] != expected_url:
        raise RuntimeError('existing Draft URL mismatch')
    return observed


def publish_update(stage, path, source, sealed, summary):
    no_hold()
    clean(path, sealed)
    actor()
    origin(path)
    branch = branches[stage]
    base_name = base_branch if stage == 'journal' else branches['journal']
    expected_base = base if stage == 'journal' else results['journal']['evidence_commit']
    previous = old_evidence[stage]
    if remote_ref(path, base_name) != expected_base or remote_ref(path, branch) != previous:
        raise RuntimeError('remote candidate/base changed before FF update')
    existing = current_pr(stage, previous)
    original_body = (existing.get('body') or '').encode('utf-8')
    accepted_original = data['prior_pr_bodies'][stage].encode('utf-8')
    if original_body not in (accepted_original, accepted_original.rstrip(b'\n')):
        raise RuntimeError('Draft body changed since reviewed readback')
    write(evidence / (stage + '-previous-pr.json'), json.dumps(existing, indent=2))
    if subprocess.run(gitcmd(path, 'merge-base', '--is-ancestor', previous, sealed), env=env).returncode:
        raise RuntimeError('candidate publication is not fast forward')
    write(evidence / (stage + '-push-intent.json'), json.dumps({
        'state': 'MayHaveBeenSent',
        'operation_id': 'github-ref-fast-forward:' + repository + ':' + branch + ':' + previous + ':' + sealed,
        'repository': repository, 'host': 'github.com', 'branch': branch,
        'previous_commit': previous, 'source_commit': source, 'payload_commit': sealed,
        'refspec': sealed + ':refs/heads/' + branch,
    }, indent=2))
    actor()
    origin(path)
    clean(path, sealed)
    no_hold()
    pushed = subprocess.run(gitcmd(path, '-c', 'credential.helper=', '-c', 'credential.helper=!/usr/bin/gh auth git-credential',
                                  'push', '--porcelain', 'origin', sealed + ':refs/heads/' + branch),
                            env=env, capture_output=True)
    write(evidence / (stage + '-push.log'), pushed.stdout + pushed.stderr)
    if remote_ref(path, branch) != sealed:
        raise RuntimeError('FF push unconfirmed; reconcile original intent instead of replay')
    after_push = current_pr(stage, sealed)
    if (after_push.get('body') or '').encode('utf-8') != original_body:
        raise RuntimeError('Draft body drifted during push')
    rows = []
    for package, receipt in summary['package_commands'].items():
        rows.append('| ' + package + ' | ' + str(receipt['test']['exit_code']) + ' | ' + str(receipt['fix']['exit_code']) + ' |')
    body = (
        '## Provider context and current qualification\n\n'
        'The provider context and journal protections remain in this Draft. The current source is actual merge ' + source + ', tree ' + source_tree + ', with parents ' + ', '.join(source_parents) + '.\n\n'
        '## Preserved v13 failure — DRAFT HOLD\n\n'
        '- Original native driver: failed with exit 1.\n'
        '- The three package tests and three Clippy fix commands returned 0 with before/after physical source checks and owner cleanup.\n'
        '- The original formatter command was `just fmt --base a0ee4d04490a74d90aedad82d61dd91dd648d9fb`. Its child returned 0, but the source-after gate returned wrapper exit 125.\n'
        '- The formatter changed only the archived `native-journal-v13/control-reviewed-fixture.rs` layout. The original archive bytes, path and manifest remain intact in the fresh source used for sealing. The dirty failed worktree, index and actual after-image were preserved separately.\n'
        '- Full qualification remains FAIL_OR_UNCONFIRMED. No source-after failure or original result has been rewritten as a pass.\n'
        '- This evidence-only child is ' + sealed + ', sole parent ' + source + '. It reconstructs the exact original source and preserves the failure; it does not run or claim a replacement test/fix/fmt suite.\n'
        '- The summary and seven-command index are explicitly derived after the original driver stopped, from its original individual receipts and logs. They were not generated by the interrupted original stage.\n'
        '- Derived required-name observations: ' + json.dumps(summary['expected_regressions_observed'], sort_keys=True) + '.\n'
        '- Critical-case first-attempt observations: ' + json.dumps(summary['concurrency_first_attempt_clean'], sort_keys=True) + '.\n'
        '- Raw logs, receipts, complete source maps, exact format diff and both archive byte images: `' + prefix + '`. New archive byte copies use `.rs.txt` and retain their original-name/hash mapping.\n\n'
        '| Package | Original test exit | Original Clippy fix exit |\n| --- | ---: | ---: |\n' + '\n'.join(rows) + '\n\n'
        'The prior v13 Journal source feee5752f7be21edec65eb78927fac75fbcb562d still records a first-attempt concurrent failure followed by a retry pass, with a Reconciled step and one provider reconciliation. Its result remains FAIL_OR_UNCONFIRMED. '
        'The existing step-writer correction and its separate negative control remain in history; the subsequent run-writer correction and new run control are not present in this source.\n\n'
        '## Next validation boundary\n\n'
        'Any subsequent corrected source must receive its own full qualification. When this evidence child becomes the next formatter baseline, the inherited old archive is unchanged relative to that baseline; this does not retroactively pass the original formatter command. '
        'The formatter implementation, selection rules and original qualification receipts were not altered.\n\n'
        'The existing operation key is scoped by provider scope plus owner/run/step. A context digest is not a reconnectable provider configuration snapshot and does not prove the service behind DNS or a PoN store incarnation. '
        'Provider atomic deduplication/retention and independent Root state survival remain assumptions. No unlimited exactly-once guarantee, production activation, actual payment/message, deployment or production branch merge is claimed.\n'
    )
    body_bytes = body.encode('utf-8')
    payload = json.dumps({'body': body}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    write(evidence / (stage + '-pr-body.md'), body_bytes)
    write(evidence / (stage + '-pr-update-payload.json'), payload)
    write(evidence / (stage + '-pr-update-intent.json'), json.dumps({
        'state': 'MayHaveBeenSent',
        'operation_id': 'github-pr-body-update:' + repository + ':' + str(pr_numbers[stage]) + ':' + sealed,
        'repository': repository, 'host': 'github.com', 'pr_number': pr_numbers[stage],
        'source_commit': source, 'evidence_commit': sealed,
        'previous_body_sha256': hashlib.sha256(original_body).hexdigest(),
        'body_bytes': len(body_bytes), 'body_sha256': hashlib.sha256(body_bytes).hexdigest(),
        'payload_bytes': len(payload), 'payload_sha256': hashlib.sha256(payload).hexdigest(),
        'payload_transport': 'immutable stdin JSON bytes',
        'final_hold_check_is_not_cross_service_CAS': True,
    }, indent=2))
    actor()
    origin(path)
    clean(path, sealed)
    if remote_ref(path, branch) != sealed or remote_ref(path, base_name) != expected_base:
        raise RuntimeError('remote head/base drift before body update')
    if (current_pr(stage, sealed).get('body') or '').encode('utf-8') != original_body:
        raise RuntimeError('Draft body drift before body update')
    no_hold()
    edited = subprocess.run(['/usr/bin/gh', 'api', '--hostname', 'github.com', '--method', 'PATCH',
                             'repos/' + repository + '/pulls/' + str(pr_numbers[stage]), '--input', '-'],
                            input=payload, env=env, capture_output=True)
    write(evidence / (stage + '-pr-update.log'), edited.stdout + edited.stderr)
    observed = current_pr(stage, sealed)
    remote_body = (observed.get('body') or '').encode('utf-8')
    if remote_body not in (body_bytes, body_bytes.rstrip(b'\n')):
        raise RuntimeError('PR update unconfirmed; reconcile original operation instead of replay')
    receipt = {
        'url': observed['url'], 'number': pr_numbers[stage], 'source_commit': source,
        'evidence_commit': sealed, 'remote_head_verified': sealed,
        'body_comparison': 'exact' if remote_body == body_bytes else 'trailing_LF_only',
        'body_sha256': hashlib.sha256(body_bytes).hexdigest(),
        'remote_body_sha256': hashlib.sha256(remote_body).hexdigest(),
        'push_exit': pushed.returncode, 'body_update_exit': edited.returncode,
        'state': 'Confirmed', 'draft': True,
    }
    write(evidence / (stage + '-publication-receipt.json'), json.dumps(receipt, indent=2))
    emit({'phase': 'draft_updated', 'stage': stage, **receipt})
    return receipt


identity_pattern = r'^(user\..*|commit\..*|gpg\..*|core\.hookspath|i18n\..*)$'
source_sha = '52ff33898e12c56ce3e11d16398b1e662a57730e'
source_tree = '42a9caa5687258dc80acbad2ad71ba4e993a4a23'
source_parents = ['a0ee4d04490a74d90aedad82d61dd91dd648d9fb', '021848e76829d6e84c9d2e5d42156010e81b611d']
archive_relative = 'evidence/root-provider-context-20261112-df05/native-journal-v13/control-reviewed-fixture.rs'
before_spec = {'bytes': 19236, 'sha256': '895b06c4989476040f9163e973f191c0feb70034a142cfe64737b0bb779eb182'}
after_spec = {'bytes': 19004, 'sha256': 'df5844fb495b102da62555e6ec1e16720d510dd01d095821b528f57419e7d81e'}
before_blob = '6f08c6f60a4e251972c92f76b730675d4efe2bef'
after_blob = '1cd5093cb3b722dfce2546005e0ce894aedc5c5c'
patch_spec = {'bytes': 4208, 'sha256': '463c90e4bcc4ac8b5d7dde7e9a24c864d1bb83e2dddda23404b2e0ebff520c68'}
fmt_receipt_spec = {'bytes': 1404, 'sha256': '8da996e9a98c86cd013aba34794420db7ed6f3c287f027cb34951850f7da5b00'}

def checked_input(name, size, digest):
    value = data[name].encode('utf-8')
    if len(value) != size or hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError('original input bytes changed: ' + name)
    return value

def old_snapshot():
    repository_guard(failed_host_dir)
    flags_clear(failed_host_dir)
    if git(failed_host_dir, 'rev-parse', 'HEAD') != source_sha or plain_git(failed_host_dir, 'symbolic-ref', '--short', 'HEAD') != branches['host']:
        raise RuntimeError('failed Host HEAD or original local branch changed')
    if pathlib.Path(git(failed_host_dir, 'rev-parse', '--path-format=absolute', '--git-common-dir')) != metadata:
        raise RuntimeError('failed Host metadata changed')
    index = pathlib.Path(git(failed_host_dir, 'rev-parse', '--path-format=absolute', '--git-path', 'index'))
    index_before = read_stable(index)
    stages = plain_git_bytes(failed_host_dir, 'ls-files', '--stage', '-z')
    flags = plain_git_bytes(failed_host_dir, 'ls-files', '-v', '-z')
    if plain_git(failed_host_dir, 'diff', '--cached', '--name-only') or plain_git(failed_host_dir, 'ls-files', '--others', '--exclude-standard'):
        raise RuntimeError('failed Host has additional staged or untracked state')
    if plain_git(failed_host_dir, 'diff', '--name-only').splitlines() != [archive_relative]:
        raise RuntimeError('failed Host dirty path set differs from the observed format failure')
    diff = subprocess.check_output(gitcmd(failed_host_dir, 'diff', '--no-ext-diff', '--binary'), env=env)
    if len(diff) != patch_spec['bytes'] or hashlib.sha256(diff).hexdigest() != patch_spec['sha256']:
        raise RuntimeError('failed Host original diff changed')
    payload = read_stable(failed_host_dir / archive_relative, after_spec)
    if oid_bytes(payload) != after_blob:
        raise RuntimeError('failed archive after-image Git identity changed')
    expected = sized_tree_map(failed_host_dir, source_sha)
    if expected[archive_relative] != ('100644', 'blob', before_blob, before_spec['bytes']):
        raise RuntimeError('failed archive original Git entry changed')
    expected[archive_relative] = ('100644', 'blob', after_blob, len(payload))
    proof = physical(failed_host_dir, expected)
    if read_stable(index) != index_before:
        raise RuntimeError('read-only failed-worktree inspection changed the index')
    return {
        'head': source_sha, 'local_branch': branches['host'], 'index_path': str(index),
        'index_bytes': index_before, 'staged_entries': stages, 'flags': flags,
        'diff': diff, 'after_bytes': payload, 'physical_known_dirty_tree': proof,
        'archive_stat': dict(zip(('device', 'inode', 'mode', 'size', 'mtime_ns', 'ctime_ns', 'nlink'),
            (lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink))((failed_host_dir / archive_relative).lstat()))),
    }

def public_old_snapshot(snapshot):
    return {key: value for key, value in snapshot.items() if key not in ('index_bytes', 'staged_entries', 'flags', 'diff', 'after_bytes')} | {
        key: {'bytes': len(snapshot[key]), 'sha256': hashlib.sha256(snapshot[key]).hexdigest(), 'private_reference': key}
        for key in ('index_bytes', 'staged_entries', 'flags', 'diff', 'after_bytes')
    }

def checkout_owned():
    global CURRENT_SOURCE_ROOT, SOURCE_OBSERVATIONS
    CURRENT_SOURCE_ROOT = journal_dir
    SOURCE_OBSERVATIONS = []
    argv = gitcmd(journal_dir, 'worktree', 'add', '-b', local_branch, str(host_dir), source_sha)
    log = evidence / 'checkout.log'
    result = owned_run(argv, log, timeout=600, env=env, cwd=journal_dir / 'codex-rs', expected_source=old_evidence['journal'])
    result.update(source_commit=old_evidence['journal'], source_observations=list(SOURCE_OBSERVATIONS), owned_cleanup_completed=result['executed'])
    raw = read_stable(log)
    result.update(log_bytes=len(raw), log_sha256=hashlib.sha256(raw).hexdigest())
    write(evidence / 'checkout.log.receipt.json', json.dumps(result, indent=2))
    if result['exit_code'] or not all(result.get(k) is True for k in ('executed', 'source_before_verified', 'source_after_verified', 'source_verified', 'owned_cleanup_completed')):
        raise RuntimeError('normal fresh checkout failed its source/owner gates')
    materialize(host_dir, source_sha, evidence / 'materialization.json')
    return result

no_hold()
own_argv = pathlib.Path('/proc/self/cmdline').read_bytes().split(b'\0')
if len(own_argv) < 3 or own_argv[1] != b'-c' or hashlib.sha256(own_argv[2]).hexdigest() != data['wrapper_sha256']:
    raise RuntimeError('actual failure-sealer program differs from fixed request')
if sys.platform != 'linux' or not all(hasattr(os, name) for name in ('waitid', 'P_PID', 'WEXITED', 'WNOHANG', 'WNOWAIT', 'killpg')):
    raise RuntimeError('reviewed retained-leader owner unavailable')
terminal_raw = checked_input('original_terminal_raw', 734, '476c53b9e071abac51da148b61de2178383e4f5d065c1620f436e9d69a98c487')
stdout_raw = checked_input('original_stdout_raw', 21002, '0d9e2ff71fd448cd1a7bd50f7a780832cc832c909d0659afe96e7f6b5fe626fc')
stderr_raw = checked_input('original_stderr_raw', 258, '23a84f12a8529f89000915b6dc4a333dbd1f54d3c4b31cce61a0d7007731f1f0')
terminal = json.loads(terminal_raw)
if terminal.get('job_id') != '1a1d006e103-2564-1b0c' or terminal.get('state') != 'failed' or terminal.get('exit_code') != 1 or terminal.get('timed_out') is not False or terminal.get('cancelled') is not False or not all(terminal.get(k) is True for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed')):
    raise RuntimeError('original failed owner is not authoritatively closed')
if terminal['log_bytes']['stdout'] != {'seen': len(stdout_raw), 'stored': len(stdout_raw)} or terminal['log_bytes']['stderr'] != {'seen': len(stderr_raw), 'stored': len(stderr_raw)}:
    raise RuntimeError('original failed stdout/stderr are incomplete')
if set(data['prior_pr_bodies']) != {'host'} or not isinstance(data['prior_pr_bodies']['host'], str):
    raise RuntimeError('one exact original Host Draft body is required')
if os.path.lexists(seal_root):
    raise RuntimeError('failure-sealer output exists; reconcile original operation')
actor()
origin(seed)
metadata = sourceprep / 'repo.git'
if metadata.is_symlink() or not metadata.is_dir() or metadata.stat().st_uid != os.geteuid() or pathlib.Path(git(seed, 'rev-parse', '--path-format=absolute', '--git-common-dir')) != metadata:
    raise RuntimeError('owned source metadata changed')
if remote_ref(seed, base_branch) != base or remote_ref(seed, branches['journal']) != old_evidence['journal'] or remote_ref(seed, branches['host']) != old_evidence['host']:
    raise RuntimeError('actual base or candidate remote changed')
clean(journal_dir, old_evidence['journal'])
if git(seed, 'rev-parse', source_sha + '^{tree}') != source_tree or parent_list(seed, source_sha) != source_parents:
    raise RuntimeError('original actual merge identity changed')
existing = current_pr('host', old_evidence['host'])
accepted_body = data['prior_pr_bodies']['host'].encode('utf-8')
if (existing.get('body') or '').encode('utf-8') not in (accepted_body, accepted_body.rstrip(b'\n')):
    raise RuntimeError('Host Draft body changed before failure sealing')
preparation_raw = read_stable(sourceprep / 'PREPARED.json', {'bytes': 2703, 'sha256': '689ddd47c9792769b1fffcf34c987557bb0046b715e935cc9550804ef48bd79b'})
preparation = json.loads(preparation_raw)
normal_identity = identity_map(read_stable(pathlib.Path('/data/root-provider-context-20261112-df05-v9-failure-inspection/host-identity-signing-config-original.bin'), {'bytes': 54, 'sha256': '699f091aef10ffc9aa6b33f3d5f8aabb625b0c31fac5ac791ffec05982928734'}))
hooks = pathlib.Path(preparation['normal_hook_path'])
normal_config = {**normal_identity, 'core.hookspath': str(hooks)}
if preparation['program_sha256'] != 'd8326fe3b3e9f8ba3ff13c0d26a7ea4dfd433fa7c03c6c3687cfc5a36784f32a' or effective_identity(seed) != normal_config or effective_identity(failed_host_dir) != normal_config or hashlib.sha256(json.dumps(snapshot_hooks(hooks), sort_keys=True).encode()).hexdigest() != preparation['normal_hook_snapshot_sha256']:
    raise RuntimeError('normal native identity/signing or hooks changed')
original_program = read_stable(prior_v13_evidence / 'qualified-wrapper-program.txt', {'bytes': 60118, 'sha256': 'c80b8d0bfbb53e76d5cc91f8cd592257f73773d05b95f0a7207d92daefbddb3a'})
snapshot_before = old_snapshot()
original_before = subprocess.check_output(gitcmd(seed, 'cat-file', 'blob', before_blob), env=env)
if len(original_before) != before_spec['bytes'] or hashlib.sha256(original_before).hexdigest() != before_spec['sha256'] or oid_bytes(original_before) != before_blob:
    raise RuntimeError('original archive blob bytes changed')
source_map = tree_map(seed, source_sha)
if source_map[archive_relative] != ('100644', 'blob', before_blob):
    raise RuntimeError('original archive path does not bind the verified blob')
if source_map['scripts/format.py'][1:] != ('blob', 'd4eabe70b68605933240e9129245f7f4cccbde5d'):
    raise RuntimeError('original formatter owner changed')
if shutil.disk_usage(seal_root.parent).free < 10 * 1024**3:
    raise RuntimeError('fresh-source capacity reserve failed')

packages = ['codex-hepta-automation', 'codex-model-provider', 'codex-hepta-agentd']
expected_commands = [['/home/qian-qi/.cargo/bin/just', 'test', '-p', p, '--status-level', 'all', '--final-status-level', 'all'] for p in packages]
expected_commands += [['/home/qian-qi/.cargo/bin/just', 'fix', '-p', p] for p in packages]
expected_commands += [['/home/qian-qi/.cargo/bin/just', 'fmt', '--base', old_evidence['host']]]
original_events = [json.loads(line) for line in stdout_raw.decode().splitlines()]
command_events = [event for event in original_events if event.get('phase') == 'command_finished' and event.get('source_commit') == source_sha]
if len(command_events) != 7 or [event['command'] for event in command_events] != expected_commands:
    raise RuntimeError('original seven-command event sequence changed')
expected_log_names = [p + '-test.log' for p in packages] + [p + '-clippy-fix.log' for p in packages] + ['fmt.log']
receipt_rows = []
command_provenance = []
original_artifacts = {}
for i, event in enumerate(command_events):
    receipt = {key: value for key, value in event.items() if key not in ('phase', 'wrapper_revision')}
    if event.get('wrapper_revision') != 'reviewed-v13' or receipt['log'] != expected_log_names[i] or receipt['cwd'] != str(failed_host_dir / 'codex-rs') or receipt['expected_source'] != source_sha or receipt['timed_out'] or not all(receipt.get(k) is True for k in ('executed', 'source_before_verified', 'owned_cleanup_completed')):
        raise RuntimeError('original command admission/owner changed')
    if i < 6:
        if receipt['exit_code'] != 0 or receipt['process_exit_code'] != 0 or receipt['source_after_verified'] is not True or receipt['source_verified'] is not True or receipt.get('build_target_verified') is not True or receipt.get('build_target_observation') != {'path': '/data/root-provider-context-20261112-df05-v10-target', 'lexists': True, 'is_directory': True, 'is_symlink': False, 'device': 2067, 'inode': 47972373, 'mode': '0o700'}:
            raise RuntimeError('one of the six original test/fix gates differs')
    elif receipt['exit_code'] != 125 or receipt['process_exit_code'] != 0 or receipt['source_after_verified'] is not False or receipt['source_verified'] is not False or receipt.get('source_failure_phase') != 'after' or receipt.get('source_error') != 'source checkout is not clean':
        raise RuntimeError('original formatter source-after failure changed')
    receipt_name = expected_log_names[i] + '.receipt.json'
    receipt_path = prior_v13_evidence / 'host' / receipt_name
    receipt_raw = read_stable(receipt_path)
    if receipt_raw != json.dumps(receipt, indent=2).encode('utf-8'):
        raise RuntimeError('native individual receipt differs from its original stdout event')
    if i == 6 and (len(receipt_raw) != fmt_receipt_spec['bytes'] or hashlib.sha256(receipt_raw).hexdigest() != fmt_receipt_spec['sha256']):
        raise RuntimeError('original formatter receipt byte identity changed')
    log_path = prior_v13_evidence / 'host' / expected_log_names[i]
    log_raw = read_stable(log_path)
    if i == 6 and log_raw != b'':
        raise RuntimeError('original formatter log changed')
    original_artifacts[expected_log_names[i]] = log_raw
    original_artifacts[receipt_name] = receipt_raw
    receipt_rows.append(json.loads(receipt_raw))
    command_provenance.append({'name': expected_log_names[i], 'original_receipt_path': str(receipt_path), 'receipt': {'bytes': len(receipt_raw), 'sha256': hashlib.sha256(receipt_raw).hexdigest()}, 'original_log_path': str(log_path), 'log': {'bytes': len(log_raw), 'sha256': hashlib.sha256(log_raw).hexdigest()}})
original_patch = read_stable(prior_v13_evidence / 'host/fmt.log.source-after.patch', patch_spec)
if original_patch != snapshot_before['diff']:
    raise RuntimeError('saved formatter diff differs from the preserved dirty worktree')
original_source_manifest = read_stable(prior_v13_evidence / 'host/source-manifest.json')
old_manifest = json.loads(original_source_manifest)
if old_manifest['source_commit'] != source_sha or old_manifest['source_tree'] != source_tree or old_manifest['source_parents'] != source_parents or old_manifest['actual_merge_commit'] != source_sha or old_manifest['complete_mode_blob_map_sha256'] != tree_digest(source_map):
    raise RuntimeError('original pre-command source manifest changed')
journal_summary_raw = subprocess.check_output(gitcmd(seed, 'show', old_evidence['journal'] + ':evidence/root-provider-context-20261112-df05/native-journal-v13/summary.json'), env=env)
if len(journal_summary_raw) != 9397 or hashlib.sha256(journal_summary_raw).hexdigest() != 'e03e25cb7f930c2c2551139e32ccf0bb56a8f7acfd8d5922865ab38cbea63062':
    raise RuntimeError('published Journal history changed')
journal_summary = json.loads(journal_summary_raw)
if journal_summary['old_production_control_source'] != '60fdb3ef91ee9df6ab87a11ddcc7e34c178e7737' or journal_summary['old_production_control_expected_failure_observed'] is not True or journal_summary['controlled_fixture_sha256'] != before_spec['sha256']:
    raise RuntimeError('actual prior step-control evidence changed')

seal_root.mkdir(mode=0o700)
evidence.mkdir(mode=0o700)
archive.mkdir(mode=0o700)
write(evidence / 'qualified-program.py', own_argv[2])
write(evidence / 'input-original.json', input_bytes)
write(evidence / 'original-terminal-sdk-native.json', terminal_raw)
write(evidence / 'original-complete-stdout.log', stdout_raw)
write(evidence / 'original-complete-stderr.log', stderr_raw)
for name, key in [('failed-host-index-original.bin', 'index_bytes'), ('failed-host-stages-original.bin', 'staged_entries'), ('failed-host-flags-original.bin', 'flags')]:
    write(evidence / name, snapshot_before[key])
write(evidence / 'failed-worktree-before.json', json.dumps(public_old_snapshot(snapshot_before), indent=2))
write(evidence / 'failed-archive-after.rs.txt', snapshot_before['after_bytes'])
write(evidence / 'original-archive-before.rs.txt', original_before)
write(evidence / 'original-format-change.patch', original_patch)
checkout = checkout_owned()
if plain_git(host_dir, 'symbolic-ref', '--short', 'HEAD') != local_branch or effective_identity(host_dir) != normal_config:
    raise RuntimeError('fresh worktree branch or normal identity/signing changed')
fresh_proof = verify_source(host_dir, source_sha)
if tree_map(host_dir, source_sha) != source_map or read_stable(host_dir / archive_relative, before_spec) != original_before:
    raise RuntimeError('fresh source differs from the exact original merge or archive')

required = {
    'codex-hepta-automation': [
        'preopened_v22_writer_cannot_append_barrier_or_bind_accepted_without_context_profile',
        'altered_append_default_fails_reopen_with_triggers_and_migration_checksums_intact',
        'taskflow_provider_identity_mixed_history_is_rejected_before_lookup_and_reopen',
        'taskflow_provider_receipt_reopen_rejects_terminal_binding_without_observation',
        'taskflow_provider_receipt_reopen_rejects_reconciliation_without_uncertainty',
        'taskflow_provider_receipt_migration_preserves_legacy_recovery_material',
        'taskflow_provider_receipt_storage_rejects_oversized_binding_without_partial_write',
        'taskflow_provider_receipt_lost_ack_then_accepted_is_bounded_and_concurrent_safe',
        'taskflow_step_reconcile_waits_for_writer_without_blocking_reads',
    ],
    'codex-model-provider': ['http_contract_rejects_legacy_duplicate_header_attestations', 'http_contract_unique_header_digest_retains_v1_encoding', 'attested_http_adapter_binds_dispatch_and_lookup_on_fixture'],
    'codex-hepta-agentd': ['host_recovery_keeps_original_target_across_signed_provider_reconfiguration', 'host_recovery_missing_original_context_never_queries_current_provider', 'host_duplicate_headers_leave_original_unknown_unqueried'],
}
observed = {}
critical = {}
for package, names in required.items():
    text = re.sub(r'\x1b\[[0-9;]*m', '', original_artifacts[package + '-test.log'].decode('utf-8'))
    observed[package] = {name: bool(re.search(r'^\s*PASS\b[^\n]*\b' + re.escape(name) + r'\s*$', text, re.MULTILINE)) for name in names}
    if package == 'codex-hepta-automation':
        for name in names[-2:]:
            nonclean = re.search(r'^\s*(?:TRY\s+\d+(?:/\d+)?|FAIL|FLAKY|TIMEOUT|LEAK|ABORT|EXECFAIL)\b[^\n]*\b' + re.escape(name) + r'\s*$', text, re.MULTILINE)
            critical[name] = observed[package].get(name) is True and nonclean is None
package_commands = {package: {'test': receipt_rows[i], 'fix': receipt_rows[i + 3]} for i, package in enumerate(packages)}
derived_provenance = {
    'derived_after_failed_native_validation': True,
    'description': 'This index is created after the original driver stopped. Each row is the unchanged JSON object from its original individual native receipt, also verified against the original complete stdout event.',
    'original_stdout': {'bytes': len(stdout_raw), 'sha256': hashlib.sha256(stdout_raw).hexdigest()},
    'entries': command_provenance,
}
summary = {
    'schema_version': 3, 'stage': 'host', 'source_commit': source_sha, 'source_tree': source_tree,
    'source_parents': source_parents, 'actual_merge_commit': source_sha,
    'journal_evidence_in_source': old_evidence['journal'], 'evidence_prefix': prefix,
    'derived_after_failed_native_validation': True,
    'summary_provenance': 'Derived after the original failed driver stopped before writing a stage summary; not an original v13 stage summary.',
    'commands_provenance': 'Derived index of seven unchanged original individual receipt objects; not an original v13 commands.json.',
    'native_scope_pass': False, 'source_after_equal': False, 'command_source_and_owner_integrity': False,
    'all_command_owners_closed': True, 'original_driver_state': 'failed', 'original_driver_exit_code': 1,
    'package_commands': package_commands, 'fmt': receipt_rows[-1],
    'expected_regressions_observed': observed, 'concurrency_first_attempt_clean': critical,
    'production_concurrency_fix_applied': True, 'writer_admission_corrections': ['step_append'],
    'run_writer_correction_applied': False,
    'old_production_control_source': journal_summary['old_production_control_source'],
    'old_production_control_expected_failure_observed': journal_summary['old_production_control_expected_failure_observed'],
    'controlled_fixture_sha256': journal_summary['controlled_fixture_sha256'],
    'reconstructed_source_verified': True, 'reconstructed_source_physical': fresh_proof,
    'failed_worktree_preserved': True, 'formatter_changed_only_archive': True,
    'original_changed_archive_path': archive_relative, 'before_archive': {**before_spec, 'git_blob': before_blob},
    'after_archive': {**after_spec, 'git_blob': after_blob}, 'original_formatter_patch': patch_spec,
    'original_nonmechanical_source_changed_lines': old_manifest['nonmechanical_source_changed_lines'],
    'no_new_test_fix_fmt_execution': True, 'future_formatter_baseline_does_not_retroactively_pass_old_command': True,
    'production_activation': False, 'production_merge_authority': False,
    'process_owner_boundary': 'Original retained-leader cleanup closed; escaped sessions and kernel cleanup latency are not certified.',
}
terminal_projection = {
    **{key: terminal[key] for key in ('state', 'exit_code', 'timed_out', 'cancelled', 'output_complete', 'output_durable', 'terminal_publication_confirmed')},
    'original': {'bytes': len(terminal_raw), 'sha256': hashlib.sha256(terminal_raw).hexdigest(), 'private_reference': str(evidence / 'original-terminal-sdk-native.json')},
    'original_driver_failure_preserved': True,
}
public_payloads = dict(original_artifacts)
public_payloads.update({
    'summary.json': json.dumps(summary, indent=2).encode(),
    'commands.json': json.dumps(receipt_rows, indent=2).encode(),
    'commands-provenance.json': json.dumps(derived_provenance, indent=2).encode(),
    'original-source-manifest.json': original_source_manifest,
    'source-manifest.json': json.dumps({'source_commit': source_sha, 'source_tree': source_tree, 'source_parents': source_parents, 'fresh_physical': fresh_proof, 'complete_mode_blob_map_sha256': tree_digest(source_map), 'derived_reconstruction_record_not_original_test_receipt': True}, indent=2).encode(),
    'original-driver-terminal-projection.json': json.dumps(terminal_projection, indent=2).encode(),
    'original-driver-stderr.log': stderr_raw,
    'fmt.log.source-after.patch': original_patch,
    'original-archive-before.rs.txt': original_before,
    'failed-archive-after.rs.txt': snapshot_before['after_bytes'],
    'artifact-name-map.json': json.dumps({'original-archive-before.rs.txt': {'original_name': archive_relative, 'source_commit': source_sha, **before_spec, 'git_blob': before_blob}, 'failed-archive-after.rs.txt': {'original_name': archive_relative, 'failed_worktree': str(failed_host_dir), **after_spec, 'git_blob': after_blob}, 'storage_note': 'Opaque original Rust byte copies use .rs.txt. The existing tracked archive path and bytes are unchanged.'}, indent=2).encode(),
    'failed-worktree-preservation.json': json.dumps(public_old_snapshot(snapshot_before), indent=2).encode(),
    'qualified-program.py': own_argv[2],
    'original-driver-program.txt': original_program,
    'checkout.log': read_stable(evidence / 'checkout.log'),
    'checkout.log.receipt.json': read_stable(evidence / 'checkout.log.receipt.json'),
})
for name, payload in public_payloads.items():
    if pathlib.PurePosixPath(name).name != name:
        raise RuntimeError('public artifact is not in the flat explicit allowlist')
    write(archive / name, payload)
if {p.name for p in archive.iterdir()} != set(public_payloads):
    raise RuntimeError('public archive contains an unexpected file')
hashes = {name: {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()} for name, payload in public_payloads.items()}
manifest_raw = json.dumps(hashes, indent=2).encode()
write(archive / 'sha256-manifest.json', manifest_raw)
public_payloads['sha256-manifest.json'] = manifest_raw
snapshot_rechecked = old_snapshot()
if snapshot_rechecked != snapshot_before:
    raise RuntimeError('failed worktree changed before evidence sealing')
clean(host_dir, source_sha)
allowed = {}
for name, payload in public_payloads.items():
    relative = prefix + name
    if relative in source_map or os.path.lexists(host_dir / relative):
        raise RuntimeError('failure evidence would overwrite an existing path')
    write(host_dir / relative, payload)
    allowed[relative] = ('100644', 'blob', oid_bytes(payload))
git(host_dir, 'add', '-f', '--', *allowed)
if set(git(host_dir, 'diff', '--cached', '--name-only').splitlines()) != set(allowed):
    raise RuntimeError('failure evidence staged allowlist differs')
expected_evidence_map = {**source_map, **allowed}
if tree_map(host_dir, git(host_dir, 'write-tree')) != expected_evidence_map:
    raise RuntimeError('failure evidence index changed the original complete source')
git(host_dir, 'commit', '-m', 'evidence: preserve failed v13 Host formatter source gate')
sealed = git(host_dir, 'rev-parse', 'HEAD')
if parent_list(host_dir, sealed) != [source_sha] or tree_map(host_dir, sealed) != expected_evidence_map:
    raise RuntimeError('failure evidence child changed original source or parent')
sealed_physical = verify_source(host_dir, sealed)
if read_stable(host_dir / archive_relative, before_spec) != original_before or effective_identity(host_dir) != normal_config or hashlib.sha256(json.dumps(snapshot_hooks(hooks), sort_keys=True).encode()).hexdigest() != preparation['normal_hook_snapshot_sha256']:
    raise RuntimeError('original archive, normal identity or hooks changed during sealing')
snapshot_after = old_snapshot()
if snapshot_after != snapshot_before:
    raise RuntimeError('failed worktree or index changed during fresh sealing')
seal_record = {
    'schema_version': 1, 'source_commit': source_sha, 'source_tree': source_tree, 'source_parents': source_parents,
    'evidence_commit': sealed, 'evidence_prefix': prefix, 'fresh_host_root': str(host_dir),
    'local_branch': local_branch, 'public_branch': branches['host'], 'native_archive_directory': str(archive),
    'program_sha256': data['wrapper_sha256'], 'archive_manifest': {'bytes': len(manifest_raw), 'sha256': hashlib.sha256(manifest_raw).hexdigest()},
    'source_preserved_complete_tree': True, 'failed_worktree_preserved': True,
    'native_scope_pass': False, 'derived_after_failed_native_validation': True,
    'original_failed_terminal': {'bytes': len(terminal_raw), 'sha256': hashlib.sha256(terminal_raw).hexdigest()},
    'source_mode_blob_map_sha256': tree_digest(source_map), 'allowed_evidence': allowed,
    'sealed_physical': sealed_physical,
}
write(evidence / 'SEALED.json', json.dumps(seal_record, indent=2))
results = {'journal': {'evidence_commit': old_evidence['journal']}}
publication = publish_update('host', host_dir, source_sha, sealed, summary)
if old_snapshot() != snapshot_before or git(failed_host_dir, 'rev-parse', 'refs/heads/' + branches['host']) != source_sha:
    raise RuntimeError('failed source or its local branch changed after publication')
verify_source(host_dir, sealed)
finished = {**seal_record, 'publication': publication, 'state': 'FAILED_VALIDATION_FAITHFULLY_SEALED', 'original_native_result_changed': False, 'new_full_qualification_performed': False}
write(seal_root / 'FINISHED.json', json.dumps(finished, indent=2))
emit({'phase': 'failure_evidence_complete', 'source_commit': source_sha, 'evidence_commit': sealed, 'fresh_host_root': str(host_dir), 'local_branch': local_branch, 'public_branch': branches['host'], 'native_scope_pass': False, 'original_driver_exit_code': 1, 'original_fmt_exit_code': 125, 'derived_after_failed_native_validation': True, 'publication': publication})
