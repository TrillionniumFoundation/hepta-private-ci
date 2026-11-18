#!/usr/bin/env python3
"""Review-only native Exec diagnostic; no publication and no process signals."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import urllib.parse

sys.dont_write_bytecode = True
_SPEC = importlib.util.spec_from_file_location('exec_format_guard', Path(__file__).with_name('a32_exec_authorized_read_format.py'))
F = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(F)
MANIFEST = '.github/fixtures/a32-exec-authorized-read-native/source-manifest.json'
OWNERS = ['//codex-rs/exec-server:exec-server-unit-tests', '//codex-rs/exec-server:exec-server-file_system_unix-test', '//codex-rs/exec-server:exec-server-authorized_read_rpc-test']
BINARIES = [OWNERS[0] + '-bin', *OWNERS[1:]]
DOTSLASH = {'url': 'https://github.com/facebook/dotslash/releases/download/v0.5.9/dotslash-macos-arm64.v0.5.9.tar.gz', 'bytes': 600404, 'sha256': 'eef15be1b554de7b1409cb0c69c24f2cd04f19c0f101ad69fcdf9d66d4d51639'}
CRITICAL = {
    OWNERS[0]: [
        'diagnostic_macos_arm_stable_handle_capability_is_required',
        'authorized_read_failure_metadata_roundtrips_without_remote_messages',
        'absent_malformed_unknown_and_wrong_method_metadata_is_not_classified',
        'recognized_metadata_requires_matching_legacy_error_code',
        'authorized_read_call_preserves_only_recognized_metadata_and_transport_behavior',
        'authorized_read_call_does_not_classify_old_or_unrecognized_peer_errors',
        'typed_authorized_read_errors_preserve_fixed_kind_and_message',
        'authorized_read_transport_errors_are_fixed',
        'authorized_read_classification_does_not_change_generic_fs_errors',
        'authorized_reads_use_cached_capability_and_preserve_wire_authority',
        'authorized_reads_reject_oversized_and_invalid_responses',
        'authorized_read_redacts_all_remote_server_errors',
        'authorized_read_rejects_invalid_bounds_before_connecting',
        'authorized_reads_fail_closed_for_legacy_or_disabled_capability',
        'authorized_reads_fail_closed_for_explicit_false_capability_on_fresh_connection',
        'authorized_read_recognized_metadata_survives_framed_rpc_without_fallback',
        'authorized_read_unrecognized_metadata_keeps_legacy_errors_without_read_fallback',
        'stable_handle_read_rejects_hardlink_provenance_ambiguity',
        'stable_handle_read_authorizes_resolved_symlink_target',
        'stable_handle_read_applies_deny_glob_to_resolved_target',
        'stable_handle_read_rejects_parent_symlink_replacement',
        'stable_handle_read_rejects_parent_directory_decoy',
        'stable_handle_read_rejects_file_path_identity_aba',
        'stable_handle_read_is_bound_to_opened_inode_after_path_replacement',
        'stable_handle_read_keeps_authorized_handle_after_later_hardlink',
        'stable_handle_read_rejects_hardlink_added_before_reopen',
        'stable_handle_read_redacts_missing_target_path',
        'stable_handle_read_rejects_unlinked_initial_handle',
        'stable_handle_bounded_read_never_returns_oversize_prefix',
    ],
    OWNERS[1]: [
        'file_system_bounded_authorized_read_enforces_limit_without_prefix::test_case_1_local',
        'file_system_bounded_authorized_read_enforces_limit_without_prefix::test_case_2_remote',
        'file_system_bounded_authorized_read_rejects_symlink_and_parent_escape::test_case_1_local',
        'file_system_bounded_authorized_read_rejects_symlink_and_parent_escape::test_case_2_remote',
    ],
    OWNERS[2]: ['authorized_read_rpc_is_capability_gated_and_denies_outside_root'],
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def require_native_host():
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'requires real macOS ARM host, not an unsupported-host skip')
    require(os.environ.get('RUNNER_OS') == 'macOS' and os.environ.get('RUNNER_ARCH') == 'ARM64', 'runner identity is not macOS ARM64')
    for name in ('CODEX_BAZEL_TEST_SKIP_FILTERS', 'TEST_FILTER', 'TESTBRIDGE_TEST_ONLY'):
        require(not os.environ.get(name), f'forbidden test selection environment: {name}')


def is_forbidden_v8_closure_label(label):
    """Examine Bazel repository/package and rule names, never source basenames.

    UUID version 8 uses src/v8.rs, and ARM crypto uses armv8 assembly files.
    Neither is a V8 JavaScript runtime. Genuine V8 repositories, workspace
    packages and named build targets remain forbidden.
    """
    package, colon, target = label.partition(':')
    if re.search(r'//codex-rs/(?:core|cli|code-mode|code_mode|v8-poc)(?:/|$)', package, re.I):
        return True
    if re.search(r'(^|[/@_+])(?:rusty_)?v8(?:[/_:~+.-]|$)', package, re.I):
        return True
    # A bare Bazel rule :v8 or :rusty_v8 is executable/library identity;
    # :src/v8.rs is merely a source file inside some other crate.
    source_suffixes = ('.rs', '.c', '.cc', '.cpp', '.h', '.hpp', '.S', '.s', '.asm', '.pl')
    return bool(
        colon
        and '/' not in target
        and not target.endswith(source_suffixes)
        and re.match(r'^(?:rusty_)?v8(?:$|[_+~.-])', target, re.I)
    )


def validate_closure(data):
    labels = sorted({line.split()[0] for line in data.decode().splitlines() if line.startswith(('//', '@'))})
    require(all(owner in labels for owner in OWNERS), 'configured closure missing an owning test target')
    forbidden = [x for x in labels if is_forbidden_v8_closure_label(x)]
    require(not forbidden, f'unreviewed V8/full-CLI closure; stop, do not prune dependencies: {forbidden}')
    return labels


def parse_test_log(label, data):
    lines = data.decode().splitlines()
    starts = [(i, re.fullmatch(r'running (\d+) tests?', line)) for i, line in enumerate(lines) if line.startswith('running ')]
    ends = [(i, re.fullmatch(r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in (\d+(?:\.\d+)?)s', line)) for i, line in enumerate(lines) if line.startswith('test result:')]
    require(len(starts) == len(ends) == 1 and starts[0][1] and ends[0][1] and starts[0][0] < ends[0][0], f'missing, malformed or repeated libtest boundaries: {label}')
    begin, running = starts[0]; end, final = ends[0]
    cases = {}; counts = dict(zip(('passed', 'failed', 'ignored', 'measured', 'filtered'), map(int, final.groups()[1:6])))
    listed = dict.fromkeys(('passed', 'failed', 'ignored', 'measured'), 0)
    for i, line in enumerate(lines):
        if not line.startswith('test ') or line.startswith('test result:'):
            continue
        match = re.fullmatch(r'test (.+?) \.\.\. (ok|FAILED|ignored(?:, .+)?|bench: .+)', line)
        require(begin < i < end and match is not None, f'incomplete/malformed or out-of-suite case line: {label}: {line}')
        name, status = match.groups()
        require(name not in cases, f'duplicate case in single owner suite: {label}: {name}')
        kind = 'passed' if status == 'ok' else 'failed' if status == 'FAILED' else 'ignored' if status.startswith('ignored') else 'measured'
        cases[name] = kind; listed[kind] += 1
    require(listed == {k: counts[k] for k in listed}, f'listed case statuses contradict final counts: {label}')
    require(int(running.group(1)) == len(cases) == sum(listed.values()), f'running/listed/final count mismatch: {label}')
    require((final.group(1) == 'ok') == (counts['failed'] == 0), f'libtest status/count contradiction: {label}')
    return {'running': len(cases), 'counts': counts, 'status': final.group(1), 'cases': cases, 'elapsed_seconds': final.group(7)}


def validate_test_log(label, data):
    result = parse_test_log(label, data)
    require(result['status'] == 'ok' and result['counts']['filtered'] == 0, f'not an unfiltered successful owner suite: {label}')
    names = {name for name, status in result['cases'].items() if status == 'passed'}
    for expected in CRITICAL[label]:
        require(any(name == expected or name.endswith('::' + expected) for name in names), f'missing executed passing case: {label} {expected}')
    return result


def proto_int(mapping, key):
    value = mapping.get(key, 0)  # Proto3 JSON omits default-valued int32 fields.
    require(type(value) is int and value >= 0, f'invalid BEP int32: {key}')
    return value


def validate_bep(data, process_exit, logs):
    require(process_exit == 0, 'Bazel process did not exit successfully')
    events = [json.loads(line) for line in data.decode().splitlines()]
    require(events and events[-1].get('lastMessage') is True and sum(e.get('lastMessage') is True for e in events) == 1, 'BEP is interrupted or has multiple terminal events')
    ids = [json.dumps(e['id'], sort_keys=True) for e in events]
    require(len(ids) == len(set(ids)), 'duplicate BEP event identity')
    by_id = dict(zip(ids, events))
    require(json.dumps({'started': {}}, sort_keys=True) in by_id, 'missing BEP invocation start')
    started = by_id[json.dumps({'started': {}}, sort_keys=True)].get('started', {})
    require(started.get('command') == 'test' and started.get('buildToolVersion') == '9.3.0', 'BEP does not identify the pinned Bazel test invocation')
    pending = [json.dumps({'started': {}}, sort_keys=True)]; reached = set()
    while pending:
        key = pending.pop()
        if key in reached: continue
        require(key in by_id, 'BEP announced child never completed')
        reached.add(key)
        pending.extend(json.dumps(child, sort_keys=True) for child in by_id[key].get('children', []))
    require(reached == set(ids), 'BEP contains unlinked events')
    require(not any('aborted' in e for e in events), 'BEP contains aborted work')
    finished = [e['finished'] for e in events if 'buildFinished' in e['id'] and 'finished' in e]
    require(len(finished) == 1 and 'exitCode' in finished[0] and finished[0]['exitCode'].get('name') == 'SUCCESS' and proto_int(finished[0]['exitCode'], 'code') == process_exit, 'Bazel process/BEP completion exit mismatch')
    results = {}; summaries = {}
    for event in events:
        for key, destination in [('testResult', results), ('testSummary', summaries)]:
            if key not in event['id']: continue
            identity = event['id'][key]; label = identity['label']
            require(label in OWNERS and label not in destination and key in event, 'unexpected/repeated owner result, run, shard or attempt')
            destination[label] = (identity, event[key])
    require(set(results) == set(summaries) == set(OWNERS), 'missing full owner result or summary')
    receipts = {}
    for label in OWNERS:
        identity, result = results[label]; summary_id, summary = summaries[label]
        require(identity.get('configuration') and identity['configuration'] == summary_id.get('configuration'), f'owner configuration mismatch: {label}')
        # Bazel 9.3 BuildEventIdUtil adds one to internal run and shard indices;
        # TestSummary.shardCount remains zero for an unsharded target.
        require((proto_int(identity, 'run'), proto_int(identity, 'shard'), proto_int(identity, 'attempt')) == (1, 1, 1), f'not the sole unsharded first attempt: {label}')
        require(result.get('status') == summary.get('overallStatus') == 'PASSED', f'BEP owner did not pass: {label}')
        require(result.get('cachedLocally', False) is False and proto_int(summary, 'totalNumCached') == 0, f'cached local/summary test result: {label}')
        require(tuple(proto_int(summary, key) for key in ('totalRunCount', 'runCount', 'attemptCount', 'shardCount')) == (1, 1, 1, 0), f'retried/repeated/sharded owner summary: {label}')
        info = result.get('executionInfo')
        require(isinstance(info, dict) and info.get('strategy') in ('local', 'standalone', 'sandboxed', 'darwin-sandbox'), f'missing native local execution evidence: {label}')
        require(info.get('cachedRemotely', False) is False and proto_int(info, 'exitCode') == 0, f'cached/nonzero native test action: {label}')
        log_path, log_bytes = logs[label]
        def check_log_reference(item):
            uri = urllib.parse.urlparse(item.get('uri', ''))
            require(uri.scheme == 'file' and not uri.netloc and not uri.query and not uri.fragment and Path(urllib.parse.unquote(uri.path)).resolve() == log_path.resolve(), f'BEP does not bind collected owner log: {label}')
            if 'length' in item: require(str(item['length']) == str(len(log_bytes)), f'BEP log length mismatch: {label}')
            if item.get('digest'): require(item['digest'] == digest(log_bytes), f'BEP log SHA256 mismatch: {label}')
        outputs = [item for item in result.get('testActionOutput', []) if item.get('name') == 'test.log']
        require(len(outputs) == 1 and len(summary.get('passed', [])) == 1 and not summary.get('failed'), f'missing/ambiguous BEP owner log reference: {label}')
        check_log_reference(outputs[0]); check_log_reference(summary['passed'][0])
        receipts[label] = {'result_identity': identity, 'result': result, 'summary': summary, 'native_test_action_exit': proto_int(info, 'exitCode'), 'log_sha256': digest(log_bytes), 'log_bytes': len(log_bytes)}
    return {'bazel_process_exit': process_exit, 'finished': finished[0], 'event_count': len(events), 'all_announced_events_completed': True, 'owners': receipts}


def require_arm64_macho(path):
    with path.open('rb') as stream:
        header = stream.read(8)
    require(len(header) == 8 and header[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack('<I', header[4:])[0] == 0x0100000C, f'not a native ARM64 Mach-O test binary: {path}')


def extract_dotslash(data):
    require(len(data) == DOTSLASH['bytes'] and digest(data) == DOTSLASH['sha256'], 'DotSlash archive does not match immutable release asset')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name == 'dotslash']
        require(len(members) == 1, 'DotSlash archive must contain one regular executable member')
        item = members[0]
        require(item.isfile() and not item.issym() and not item.islnk() and Path(item.name).name == 'dotslash' and item.size <= 8 * 1024 * 1024, 'invalid DotSlash member')
        binary = archive.extractfile(item).read(8 * 1024 * 1024 + 1)
        require(len(binary) == item.size, 'invalid DotSlash binary length')
    return binary


class Observer:
    def __init__(self, repo, out, artifact_root):
        self.repo, self.out = repo, out
        self.live = Path(tempfile.mkdtemp(prefix='a32-exec-live-', dir=artifact_root.parent))
        require(artifact_root not in self.live.parents and self.live != artifact_root, 'live output may not be uploaded')
        self.commands, self.abort_latched = [], False

    def command(self, name, argv, seconds, cwd=None):
        require(not self.abort_latched, 'unsettled writer: no subsequent command is permitted')
        live = self.live / (name + '.log')
        started = time.monotonic(); timed_out = False; error = None; exit_code = None
        with live.open('wb') as stream:
            try:
                proc = subprocess.Popen(argv, cwd=cwd or self.repo, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    proc.wait(timeout=seconds)
                except subprocess.TimeoutExpired:
                    timed_out = self.abort_latched = True
                exit_code = proc.poll()
            except OSError as exc:
                error = str(exc); stream.write((error + '\n').encode())
            stream.flush(); os.fsync(stream.fileno())
        data = immutable_prefix(live)
        (self.out / (name + '.log')).write_bytes(data)
        rc = 124 if timed_out else (127 if error else exit_code)
        self.commands.append({'name': name, 'argv': argv, 'cwd': str(cwd or self.repo), 'observation_seconds': seconds, 'elapsed_seconds': round(time.monotonic() - started, 3), 'exit_code': rc, 'process_exit_code': exit_code, 'writer_unsettled': timed_out, 'log_is_partial': timed_out, 'log_sha256': digest(data), 'log_bytes': len(data), 'live_log_not_uploaded': str(live), 'signals_sent': False, 'spawn_error': error})
        return rc, data


def immutable_prefix(path):
    with path.open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        return stream.read(size)


def seal_formatter_output(observer, live_dir, destination):
    # The outer collector and every Rust writer must have actually exited.
    # An observation timeout is never permission to copy a changing directory.
    require(not observer.abort_latched, 'outer formatter unsettled; live directory must not be copied')
    command = observer.commands[-1]
    require(command['name'] == 'formatter' and type(command['process_exit_code']) is int and not command['writer_unsettled'], 'formatter process completion was not observed')
    manifest = live_dir / 'manifest.json'
    try:
        manifest_bytes = manifest.read_bytes(); receipt = json.loads(manifest_bytes)
        settled = receipt.get('writer_unsettled') is False and receipt.get('abort_latched') is False
        settled = settled and all(c.get('writer_settled') is True and not c.get('timed_out') and (type(c.get('process_exit_code')) is int or c.get('spawn_error')) for c in receipt['commands'])
    except Exception:
        observer.abort_latched = True  # A missing/invalid receipt cannot establish child completion.
        raise
    if not settled:
        observer.abort_latched = True
        raise RuntimeError('inner formatter writer unsettled; live directory must not be copied')
    require(not destination.exists(), 'refuse to overwrite sealed formatter evidence')
    expected = receipt['artifact_files']
    actual = set()
    for parent, directories, files in os.walk(live_dir, followlinks=False):
        for name in directories + files:
            require(not (Path(parent) / name).is_symlink(), 'formatter evidence must not contain symlinks')
        actual.update((Path(parent) / name).relative_to(live_dir).as_posix() for name in files)
    require(actual == set(expected) | {'manifest.json'}, 'formatter evidence inventory changed')
    staging = observer.live / 'sealed-formatter-staging'
    staging.mkdir()
    for relative, record in expected.items():
        path = Path(relative)
        require(not path.is_absolute() and '..' not in path.parts, 'invalid formatter evidence path')
        data = (live_dir / path).read_bytes()
        require(len(data) == record['bytes'] and digest(data) == record['sha256'], 'formatter evidence bytes disagree with settled receipt')
        target = staging / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
    require(manifest.read_bytes() == manifest_bytes, 'formatter manifest changed during sealing')
    (staging / 'manifest.json').write_bytes(manifest_bytes)
    # Only the verifier owns staging; rename publishes a complete verified copy.
    staging.rename(destination)
    return receipt


def checked_input(repo, sha):
    tree = F.git(repo, 'rev-parse', sha + '^{tree}').decode().strip()
    entries = F.inventory(repo, sha, tree)
    frozen, _, allowed = F.verify_reviewed_input(repo, entries, sha, MANIFEST)
    F.boundary(repo, sha, tree, entries)
    raw = F.snapshot(repo, entries)
    require(all(raw[p]['blob'] == v['blob'] and raw[p]['mode'] == v['mode'] for p, v in entries.items()), 'raw checkout differs from committed input')
    return tree, entries, raw, allowed, frozen


def materialize_formatted_commit(repo, sha, tree, entries, allowed, format_dir, out):
    receipt = json.loads((format_dir / 'manifest.json').read_text())
    require(receipt['complete'] and receipt['generated_artifacts_accepted'] and not receipt['writer_unsettled'] and not receipt['abort_latched'], 'formatter artifacts are rejected or unsettled')
    require(receipt['source_sha'] == sha and receipt['source_tree'] == tree, 'formatter source identity mismatch')
    F.boundary(repo, sha, tree, entries)
    raw = F.snapshot(repo, entries)
    require(raw == json.loads((format_dir / 'final-files.json').read_text()), 'formatter final raw bytes changed')
    changed = [p for p in entries if raw[p]['blob'] != entries[p]['blob'] or raw[p]['mode'] != entries[p]['mode']]
    require(set(changed) <= allowed, 'format changes exceed frozen source allowlist')
    expected_tree = F.tree_hash({p: {'mode': v['mode'], 'blob': v['blob']} for p, v in raw.items()})
    new_sha = sha
    if changed:
        for path in changed:
            data = (repo / path).read_bytes()
            blob = subprocess.check_output(['git', '--no-replace-objects', 'hash-object', '-w', '--stdin'], cwd=repo, input=data).decode().strip()
            require(blob == raw[path]['blob'], 'raw/index object mismatch')
            F.git(repo, 'update-index', '--cacheinfo', f"{raw[path]['mode']},{blob},{path}")
        actual_tree = F.git(repo, 'write-tree').decode().strip()
        require(actual_tree == expected_tree, 'generated index tree differs from exact raw source tree')
        env = os.environ.copy(); timestamp = F.git(repo, 'show', '-s', '--format=%ct', sha).decode().strip()
        env.update(GIT_AUTHOR_NAME='Exec native diagnostic', GIT_AUTHOR_EMAIL='diagnostic@invalid', GIT_COMMITTER_NAME='Exec native diagnostic', GIT_COMMITTER_EMAIL='diagnostic@invalid', GIT_AUTHOR_DATE=f'@{timestamp} +0000', GIT_COMMITTER_DATE=f'@{timestamp} +0000')
        new_sha = subprocess.check_output(['git', '--no-replace-objects', 'commit-tree', actual_tree, '-p', sha], cwd=repo, env=env, input=b'Diagnostic-only generated Exec formatting; never published\n').decode().strip()
        F.git(repo, 'update-ref', '--no-deref', 'HEAD', new_sha, sha)
    final_entries = F.inventory(repo, new_sha, expected_tree)
    F.boundary(repo, new_sha, expected_tree, final_entries)
    require(F.snapshot(repo, final_entries) == raw, 'generated commit/raw checkout mismatch')
    (out / 'generated-source-files.json').write_text(json.dumps(raw, sort_keys=True) + '\n')
    (out / 'generated-source-index.bin').write_bytes(F.git(repo, 'ls-files', '--stage', '-z'))
    result = {'input_sha': sha, 'input_tree': tree, 'native_source_sha': new_sha, 'native_source_tree': expected_tree, 'local_detached_commit_only': changed != [], 'published': False, 'format_changed_paths': changed, 'original_input_format_check_exit': receipt['input_format_check_exit'], 'generated_format_check_exit': receipt['generated_format_check_exit'], 'formatter_patch_sha256': receipt['generated_patch_sha256']}
    (out / 'generated-source-identity.json').write_text(json.dumps(result, indent=2) + '\n')
    return new_sha, expected_tree, final_entries, raw, result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['preflight', 'install-tools', 'run']); parser.add_argument('--repo', type=Path, required=True); parser.add_argument('--source-sha', required=True); parser.add_argument('--out', type=Path, required=True); parser.add_argument('--artifact-root', type=Path, required=True)
    args = parser.parse_args(); repo = args.repo.resolve(); out = args.out.resolve(); root = args.artifact_root.resolve()
    require(__debug__, 'optimized Python disables imported guards')
    require(not out.exists() and root in out.parents and repo not in root.parents and root != repo, 'evidence must be fresh and outside checkout')
    out.mkdir(parents=True); observer = Observer(repo, out, root)
    receipt = {'complete': False, 'qualified': False, 'publication': False, 'signals_sent': False, 'stage': args.stage, 'source_sha': args.source_sha, 'host': {'system': platform.system(), 'machine': platform.machine(), 'python_version': platform.python_version(), **{k: os.environ.get(k) for k in ['RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB']}}, 'commands': observer.commands}
    testlogs = None
    try:
        require_native_host()
        require(platform.python_version() == '3.12.10', 'wrong pinned Python version')
        tree, entries, raw, allowed, frozen = checked_input(repo, args.source_sha)
        receipt.update(source_tree=tree, reviewed_product_tree=frozen['product_tree'], input_verified=True)
        if args.stage == 'preflight':
            receipt['complete'] = True; return 0
        if args.stage == 'install-tools':
            with urllib.request.urlopen(DOTSLASH['url'], timeout=30) as response:
                data = response.read(DOTSLASH['bytes'] + 1)
            binary = extract_dotslash(data); (out / 'dotslash.archive.sha256').write_text(digest(data) + '\n')
            dest = Path(os.environ['RUNNER_TEMP']) / 'a32-exec-tools'; dest.mkdir(exist_ok=True)
            require(not dest.is_symlink(), 'tool directory symlink')
            target = dest / 'dotslash'; require(not target.exists(), 'refuse tool overwrite')
            target.write_bytes(binary); target.chmod(0o755); require_arm64_macho(target)
            rc, version = observer.command('dotslash-version', [str(target), '--version'], 30)
            require(rc == 0 and version.strip() == b'DotSlash 0.5.9', 'wrong DotSlash version')
            checked_input(repo, args.source_sha)
            receipt.update(complete=True, archive=DOTSLASH, binary_sha256=digest(binary), tool_path=str(target)); return 0
        live_format_root = observer.live / 'formatter-evidence-root'
        live_format = live_format_root / 'format'
        receipt['formatter_evidence'] = {'sealed': False, 'live_directory_not_uploaded': str(live_format_root)}
        rc, _ = observer.command('formatter', [sys.executable, '-I', '-B', str(Path(__file__).with_name('a32_exec_authorized_read_format.py')), '--repo', str(repo), '--source-sha', args.source_sha, '--source-tree', tree, '--out', str(live_format), '--artifact-root', str(live_format_root), '--source-manifest', MANIFEST], 1050)
        format_receipt = seal_formatter_output(observer, live_format, root / 'format')
        receipt['formatter_evidence'].update(sealed=True, manifest_sha256=digest((root / 'format/manifest.json').read_bytes()), accepted=format_receipt['generated_artifacts_accepted'])
        require(rc in (0, 1), 'formatter rejected input or generated output')
        sha, tree, entries, expected, generated = materialize_formatted_commit(repo, args.source_sha, tree, entries, allowed, root / 'format', out)
        receipt['generated_source'] = generated
        def guard():
            F.boundary(repo, sha, tree, entries)
            require(F.snapshot(repo, entries) == expected, 'native command changed tracked raw bytes')
        def command(name, argv, seconds):
            guard(); rc, data = observer.command(name, argv, seconds)
            if observer.abort_latched:
                raise RuntimeError('bounded observation expired; immutable partial log retained; runner owns teardown')
            guard(); return rc, data
        rc, rustc = command('native-rust-host', ['rustc', '--version', '--verbose'], 30)
        require(rc == 0 and rustc.startswith(b'rustc 1.95.0 ') and b'host: aarch64-apple-darwin' in rustc, 'wrong native Rust host/toolchain')
        for name, argv in [('macos-version', ['sw_vers']), ('xcode-version', ['xcodebuild', '-version']), ('sdk-version', ['xcrun', '--show-sdk-version'])]:
            rc, _ = command(name, argv, 30)
            require(rc == 0, f'host tool identity unavailable: {name}')
        output = (Path(os.environ['RUNNER_TEMP']) / 'a32-exec-bazel').resolve(); output.mkdir(exist_ok=True); (output / 'links').mkdir(exist_ok=True)
        bazel = ['bazel', '--output_base=' + str(output / 'output'), '--output_user_root=' + str(output / 'user')]
        flags = ['--config=ci-macos', '--lockfile_mode=error', '--noenable_runfiles', '--jobs=2', '--symlink_prefix=' + str(output / 'links') + '/', '--remote_cache=', '--remote_executor=', '--bes_backend=']
        rc, version = command('bazel-version', bazel + ['version', '--gnu_format'], 120)
        require(rc == 0 and b'bazel 9.3.0' in version.lower(), 'wrong repository Bazel version')
        rc, dotslash = command('installed-dotslash-version', ['/usr/local/bin/dotslash', '--version'], 30)
        require(rc == 0 and dotslash.strip() == b'DotSlash 0.5.9', 'required pinned DotSlash not installed')
        rc, closure = command('configured-dependency-closure', bazel + ['cquery', 'deps(set(' + ' '.join(OWNERS) + '))', *flags, '--output=label'], 900)
        require(rc == 0, 'configured dependency analysis failed')
        labels = validate_closure(closure); (out / 'configured-dependency-labels.json').write_text(json.dumps(labels, indent=2) + '\n')
        rc, _ = command('compile-original-owners', bazel + ['build', *flags, '--', *OWNERS], 2700)
        require(rc == 0, 'real Bazel owner compilation failed')
        rc, execution = command('execution-root', bazel + ['info', '--config=ci-macos', '--lockfile_mode=error', 'execution_root'], 120)
        require(rc == 0, 'execution root unavailable')
        execution_roots = [Path(line) for line in execution.decode().splitlines() if line.startswith(str(output))]
        require(len(execution_roots) == 1, 'unexpected execution root output')
        execution_root = execution_roots[0]
        rc, binaries = command('native-binary-inventory', bazel + ['cquery', 'set(' + ' '.join(BINARIES) + ')', *flags, '--output=files'], 300)
        require(rc == 0, 'native binary inventory failed')
        paths = [line for line in binaries.decode().splitlines() if line.startswith('bazel-out/')]
        require(len(paths) == 3 and {Path(p).name for p in paths} == {p.split(':')[1] for p in BINARIES}, 'unexpected owning test binaries')
        for path in paths: require_arm64_macho(execution_root / path)
        receipt['native_arm64_macho_binaries'] = []
        for path in paths:
            binary = execution_root / path
            with binary.open('rb') as stream:
                binary_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            receipt['native_arm64_macho_binaries'].append({'path': path, 'bytes': binary.stat().st_size, 'sha256': binary_digest})
        rc, logs = command('testlog-root', bazel + ['info', '--config=ci-macos', '--lockfile_mode=error', 'bazel-testlogs'], 120)
        require(rc == 0, 'testlog root unavailable')
        roots = [Path(line) for line in logs.decode().splitlines() if line.startswith(str(output))]
        require(len(roots) == 1, 'unexpected testlog root output'); testlogs = roots[0]
        bep = observer.live / 'native.bep.json'
        rc, _ = command('full-native-owners', bazel + ['test', *flags, '--nocache_test_results', '--test_output=all', '--build_event_json_file=' + str(bep), '--', *OWNERS], 1200)
        if bep.exists(): (out / 'native.bep.json').write_bytes(immutable_prefix(bep))
        log_snapshots = {}; parsed = {}; parse_errors = {}
        receipt['owner_test_results'] = parsed; receipt['owner_log_errors'] = parse_errors
        for label in OWNERS:
            directory = testlogs / label.removeprefix('//').replace(':', '/')
            log = directory / 'test.log'; require(log.is_file(), f'missing native test log: {label}')
            data = immutable_prefix(log); (out / (label.split(':')[1] + '.test.log')).write_bytes(data)
            log_snapshots[label] = (log, data)
            xml = directory / 'test.xml'
            if xml.is_file(): (out / (label.split(':')[1] + '.test.xml')).write_bytes(immutable_prefix(xml))
            try: parsed[label] = parse_test_log(label, data)
            except Exception as exc: parse_errors[label] = f'{type(exc).__name__}: {exc}'
        require(rc == 0, 'one or more full native owners failed')
        require(not parse_errors, 'inconsistent or incomplete libtest execution evidence')
        for label, (_, data) in log_snapshots.items(): validate_test_log(label, data)
        receipt['bep_validation'] = validate_bep((out / 'native.bep.json').read_bytes(), rc, log_snapshots)
        guard(); receipt.update(complete=True, qualified=True, tested_owners=OWNERS, qualification_scope='this exact generated diagnostic source on native macOS ARM only; no union57/Memory/Windows transfer')
        return 0
    except Exception as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        return 2
    finally:
        receipt.update(abort_latched=observer.abort_latched, writer_unsettled=observer.abort_latched, evidence_consistency='partial immutable prefixes only; no settled final source claimed' if observer.abort_latched else 'settled command observations')
        # Snapshot only known evidence paths; never upload mutable writer destinations.
        def preserve(path, destination):
            try:
                if path.is_file() and not destination.exists(): destination.write_bytes(immutable_prefix(path))
            except OSError as exc:
                receipt.setdefault('evidence_collection_errors', []).append({'path': str(path), 'error': str(exc)})
                receipt['qualified'] = False
        if testlogs is not None:
            for label in OWNERS:
                for name in ('test.log', 'test.xml'):
                    p = testlogs / label.removeprefix('//').replace(':', '/') / name
                    dest = out / (label.split(':')[1] + '.' + name)
                    preserve(p, dest)
        bep = observer.live / 'native.bep.json'
        preserve(bep, out / 'native.bep.json')
        receipt['artifact_files'] = {p.relative_to(out).as_posix(): {'bytes': p.stat().st_size, 'sha256': digest(p.read_bytes())} for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    sys.exit(main())
