#!/usr/bin/env python3
"""One-owner, fixed-matrix Mac eval qualification. No signals or command deadlines."""
import argparse
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

_spec = importlib.util.spec_from_file_location('a32_eval_lock_log', Path(__file__).with_name('a32_eval_lock_log.py'))
logs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(logs)

BASE = 'a32d73f00cfc292ff1ed4ac5cef958ca9f238020'
BASE_TREE = '603a3e5b69258e37653a828dda625efe45365d7e'
PRODUCT_TREE = '69a6353f6c6d565c25867d6a2411f23540f5b606'
BRANCH = 'diagnostic/a32-eval-lock-native-20261022'
REPOSITORY = 'TrillionniumFoundation/hepta-private-ci'
TARGET = '//codex-rs/hepta-intelligence-eval:hepta-intelligence-eval-unit-tests'
BINARY = TARGET + '-bin'
QUALIFIER = '//codex-rs/hepta-learning-ledger:hepta-learning-ledger-qualification-lib'
TEST_LIB = '//codex-rs/hepta-intelligence-eval:hepta-intelligence-eval-test-lib'
MANIFEST = '.github/fixtures/a32-eval-lock-native/source-manifest.json'
AUXILIARY = {MANIFEST, '.github/scripts/a32_eval_lock_native.py', '.github/scripts/a32_eval_lock_log.py', '.github/workflows/a32-eval-lock-native.yml'}
ROUNDS = 21
DOTSLASH = {'url': 'https://github.com/facebook/dotslash/releases/download/v0.5.9/dotslash-macos-arm64.v0.5.9.tar.gz', 'bytes': 600404, 'sha256': 'eef15be1b554de7b1409cb0c69c24f2cd04f19c0f101ad69fcdf9d66d4d51639'}
PINNED_BAZEL = {'url': 'https://github.com/bazelbuild/bazel/releases/download/9.3.0/bazel-9.3.0-darwin-arm64', 'bytes': 71524530, 'sha256': 'f29ca3f3bf577eb1619aeeed401b64a10901c8da8031aaa4add54a4ad0e99e3a', 'version': '9.3.0', 'asset_id': 619247856}


FORBIDDEN_ENV = ('RUST_TEST_THREADS', 'CODEX_BAZEL_TEST_SKIP_FILTERS', 'TEST_FILTER', 'TESTBRIDGE_TEST_ONLY', 'TEST_TOTAL_SHARDS', 'TEST_SHARD_INDEX', 'HEPTA_FENCED_CAS_CHILD', 'HEPTA_FENCED_CAS_EXPECT_BUSY', 'HEPTA_HOLDOUT_REOPEN_PATH', 'HEPTA_HOLDOUT_REOPEN_HEAD', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'BAZEL_OPTS', 'BAZEL_ARGS', 'BAZELISK_BAZEL_FLAGS', 'USE_BAZEL_VERSION', 'BAZELISK_BASE_URL', 'BAZELISK_FORMAT_URL', 'BAZELISK_WRAPPER', 'BAZELISK_GITHUB_TOKEN')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '--no-replace-objects', *args], cwd=repo)


def inventory(repo, revision):
    result = {}
    for row in git(repo, 'ls-tree', '-rz', '--full-tree', revision).split(b'\0'):
        if not row:
            continue
        header, raw_path = row.split(b'\t', 1)
        mode, kind, value = header.decode().split()
        path = os.fsdecode(raw_path)
        require(kind == 'blob' and mode in ('100644', '100755', '120000'), 'unsupported source entry')
        require(not Path(path).is_absolute() and '..' not in Path(path).parts and path not in result, 'invalid/duplicate source path')
        result[path] = {'mode': mode, 'blob': value}
    return result


def tree_hash(entries):
    root = {}
    for path, item in entries.items():
        node = root
        parts = path.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (item['mode'], item['blob'])

    def visit(node):
        records = []
        for name, value in node.items():
            mode, value = ('40000', visit(value)) if isinstance(value, dict) else value
            records.append((name.encode() + (b'/' if mode == '40000' else b''), mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(value)))
        payload = b''.join(record for _, record in sorted(records))
        return hashlib.sha1(b'tree ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
    return visit(root)


def snapshot(repo, entries):
    result = {}
    for path, item in entries.items():
        file = repo / path
        require(not any(p.is_symlink() for p in file.parents if p != repo and repo in p.parents), 'source symlink ancestor')
        if item['mode'] == '120000':
            require(file.is_symlink(), 'source symlink changed')
            data, mode = os.fsencode(os.readlink(file)), '120000'
        else:
            require(file.is_file() and not file.is_symlink(), 'source file type changed')
            data = file.read_bytes()
            mode = '100755' if file.stat().st_mode & stat.S_IXUSR else '100644'
        require({'mode': mode, 'blob': blob(data)} == item, 'source bytes/mode drift: ' + path)
        result[path] = {'mode': mode, 'blob': item['blob'], 'sha256': digest(data), 'bytes': len(data)}
    return result


def checked_source(repo, sha):
    require(re.fullmatch('[0-9a-f]{40}', sha) is not None, 'invalid source SHA')
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == sha, 'wrong checkout HEAD')
    require(git(repo, 'rev-list', '--parents', '-n', '1', sha).decode().split() == [sha, BASE], 'source must have sole a32 parent')
    require(git(repo, 'rev-parse', BASE + '^{tree}').decode().strip() == BASE_TREE, 'wrong base tree')
    entries = inventory(repo, sha)
    tree = git(repo, 'rev-parse', sha + '^{tree}').decode().strip()
    require(tree_hash(entries) == tree, 'complete source tree mismatch')
    stage = {}
    for row in git(repo, 'ls-files', '--stage', '-z').split(b'\0'):
        if row:
            header, raw_path = row.split(b'\t', 1)
            mode, value, number = header.decode().split()
            path = os.fsdecode(raw_path)
            require(number == '0' and path not in stage, 'unmerged/duplicate index')
            stage[path] = {'mode': mode, 'blob': value}
    require(stage == entries, 'index changed')
    require(all(not row or row[:1] == b'H' for row in git(repo, 'ls-files', '-v', '-f', '-z').split(b'\0')), 'hidden index flags')
    require(not git(repo, 'ls-files', '--others', '-z'), 'untracked source additions')
    manifest = json.loads(git(repo, 'show', sha + ':' + MANIFEST))
    require(manifest['schema'] == 'a32.eval-lock-native.v2' and manifest['status'] == 'frozen', 'unfrozen manifest')
    require((manifest['base'], manifest['base_tree'], manifest['product_tree'], manifest['branch'], manifest['rounds']) == (BASE, BASE_TREE, PRODUCT_TREE, BRANCH, ROUNDS), 'manifest identity/matrix changed')
    require(set(manifest['auxiliary_paths']) == AUXILIARY and len(manifest['auxiliary_paths']) == len(AUXILIARY), 'auxiliary allowlist changed')
    require(manifest['tool_assets'] == {'bazel': PINNED_BAZEL, 'dotslash': DOTSLASH}, 'tool asset identity changed')
    files = {item['path']: item for item in manifest['files']}
    require(len(files) == len(manifest['files']) == 8 and not set(files) & AUXILIARY, 'product allowlist changed')
    changed = {os.fsdecode(p) for p in git(repo, 'diff', '--name-only', '--no-renames', '-z', BASE, sha).split(b'\0') if p}
    require(changed == set(files) | AUXILIARY, 'unexpected changed paths')
    baseline = inventory(repo, BASE)
    for path, record in files.items():
        require(baseline.get(path, {}).get('blob') == record['base_blob'], 'product preimage mismatch')
        require(entries[path] == {'mode': record['mode'], 'blob': record['blob']}, 'product postimage mismatch')
        require(digest(git(repo, 'show', sha + ':' + path)) == record['sha256'], 'product digest mismatch')
    for path in AUXILIARY:
        require(path not in baseline and entries[path]['mode'] == '100644', 'auxiliary overwrites baseline')
    require(tree_hash({p: v for p, v in entries.items() if p not in AUXILIARY}) == PRODUCT_TREE, 'wrong complete product tree')
    require(set(manifest['controls']) == AUXILIARY - {MANIFEST}, 'control digest allowlist mismatch')
    for path, value in manifest['controls'].items():
        require(digest(git(repo, 'show', sha + ':' + path)) == value, 'control digest mismatch')
    require(set(manifest['locks']) == {'codex-rs/Cargo.lock', 'MODULE.bazel.lock'}, 'lock allowlist mismatch')
    logs.nameset(manifest['expected_census'])
    for path, value in manifest['locks'].items():
        require(digest(git(repo, 'show', BASE + ':' + path)) == value == digest(git(repo, 'show', sha + ':' + path)), 'lock changed')
    raw = snapshot(repo, entries)
    return {'sha': sha, 'tree': tree, 'files': raw, 'manifest': manifest}


def host_guard():
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'requires actual Darwin ARM host')
    require(os.environ.get('RUNNER_OS') == 'macOS' and os.environ.get('RUNNER_ARCH') == 'ARM64', 'wrong runner architecture')
    require(platform.python_version() == '3.12.10', 'wrong Python version')
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and os.environ.get('GITHUB_EVENT_NAME') == 'push' and os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH, 'wrong repository/event/ref')
    require(all(name not in os.environ for name in FORBIDDEN_ENV), 'test/compiler override environment present')
    # Fail closed instead of suppressing or editing host configuration. The
    # workspace rc is frozen, including its absent/untracked user.bazelrc.
    for path in (Path('/etc/bazel.bazelrc'), Path.home() / '.bazelrc'):
        require(not path.exists() and not path.is_symlink(), 'external Bazel rc requires separate review: ' + str(path))


def closure_labels(data):
    labels = {line.split()[0] for line in data.decode().splitlines() if line.startswith(('//', '@'))}
    for label in labels:
        match = re.fullmatch(r'(?:(@{1,2}[^/]*))?//([^:]*):([^:]+)', label)
        require(match is not None, 'malformed dependency label')
        repository, package, target = match.groups()
        require(not re.match(r'^codex-rs/(core|cli|state|hepta-memory|hepta-operator-acceptance|code-mode|v8-poc)(/|$)', package), 'unrelated product closure: ' + label)
        identity = (repository or '') + '/' + package
        require(not re.search(r'(^|[/@_+~.-])(?:lib)?(?:rusty[_-]?)?(?:v8|sqlite3?|wasmtime|deno_core)(?=$|[/_+~.-])', identity, re.I), 'unreviewed runtime closure: ' + label)
    return labels


def validate_closure(data):
    labels = closure_labels(data)
    require({TARGET, BINARY, QUALIFIER, TEST_LIB, '@@rules_rs++toolchains+rustc_macos_aarch64_1_95_0//:rustc', '@@rules_rs++toolchains+cargo_macos_aarch64_1_95_0//:cargo'} <= labels, 'missing original target/qualification library/pinned hermetic Rust toolchain')
    return sorted(labels)


def proto_int(mapping, key):
    value = mapping.get(key, 0)
    require(type(value) is int and value >= 0, 'invalid BEP int: ' + key)
    return value


def validate_effective_options(options, census=False):
    require(options.get('invocationPolicy', {}) == {}, 'unreviewed invocation policy')
    command = options.get('cmdLine')
    require(isinstance(command, list) and all(isinstance(a, str) for a in command), 'missing effective Bazel options')
    def values(key):
        return [a.split('=', 1)[1] for a in command if a.startswith(key + '=')]
    require(values('--test_env') == ['PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin', 'RUST_MIN_STACK=8388608'], 'effective test environment changed')
    require(values('--test_arg') == (['--list'] if census else []), 'effective test args changed')
    require(values('--test_output') == ['errors', 'all'], 'effective output mode changed')
    require(values('--cache_test_results') == ['0'], 'effective test caching changed')
    require(values('--jobs') == ['30'], 'original repo build concurrency changed')
    require(values('--config') == ['ci-macos', 'ci-bazel', 'ci'], 'effective configuration changed')
    require(values('--strategy') == ['TestRunner=darwin-sandbox,local'], 'effective test strategy changed')
    for argument in command:
        key = argument.split('=', 1)[0]
        if key.startswith(('--test_', '--notest_')):
            require(key in ('--test_env', '--test_arg', '--test_output') and '=' in argument, 'unreviewed/noncanonical effective test option: ' + key)
        require(key not in ('--local_test_jobs', '--runs_per_test', '--flaky_test_attempts'), 'effective scheduling/retry override')
    return {'test_env': values('--test_env'), 'test_arg': values('--test_arg'), 'jobs': values('--jobs'), 'configs': values('--config'), 'strategy': values('--strategy'), 'invocation_policy': {}}


def validate_bep(data, process_exit, log_path, log_bytes, census=False):
    require(process_exit == 0, 'Bazel process failed')
    events = [json.loads(line) for line in data.decode().splitlines()]
    require(events and events[-1].get('lastMessage') is True and sum(e.get('lastMessage') is True for e in events) == 1, 'incomplete BEP stream')
    ids = [json.dumps(e['id'], sort_keys=True) for e in events]
    require(len(ids) == len(set(ids)), 'duplicate BEP identity')
    by_id = dict(zip(ids, events))
    started_key = json.dumps({'started': {}}, sort_keys=True)
    require(started_key in by_id, 'missing invocation start')
    started = by_id[started_key].get('started', {})
    require(started.get('command') == 'test' and started.get('buildToolVersion') == '9.3.0', 'wrong Bazel test invocation')
    pending, reached = [started_key], set()
    while pending:
        key = pending.pop()
        if key in reached:
            continue
        require(key in by_id, 'announced BEP child absent')
        reached.add(key)
        pending.extend(json.dumps(child, sort_keys=True) for child in by_id[key].get('children', []))
    require(reached == set(ids) and not any('aborted' in e for e in events), 'unlinked/aborted BEP')
    option_events = [e for e in events if 'optionsParsed' in e['id']]
    require(len(option_events) == 1 and 'optionsParsed' in option_events[0], 'missing/duplicate effective options')
    effective = validate_effective_options(option_events[0]['optionsParsed'], census=census)
    finished = [e['finished'] for e in events if 'buildFinished' in e['id'] and 'finished' in e]
    require(len(finished) == 1 and finished[0].get('exitCode', {}).get('name') == 'SUCCESS' and proto_int(finished[0]['exitCode'], 'code') == 0, 'BEP finish failed')
    results = [e for e in events if 'testResult' in e['id']]
    summaries = [e for e in events if 'testSummary' in e['id']]
    require(len(results) == len(summaries) == 1, 'wrong result/summary count')
    identity, result = results[0]['id']['testResult'], results[0]['testResult']
    summary_id, summary = summaries[0]['id']['testSummary'], summaries[0]['testSummary']
    require(identity.get('label') == summary_id.get('label') == TARGET, 'wrong test owner')
    require(identity.get('configuration') and identity['configuration'] == summary_id.get('configuration'), 'test configuration mismatch')
    require(tuple(proto_int(identity, k) for k in ('run', 'shard', 'attempt')) == (1, 1, 1), 'not sole first unsharded attempt')
    require(result.get('status') == summary.get('overallStatus') == 'PASSED', 'native test failed')
    require(result.get('cachedLocally', False) is False and proto_int(summary, 'totalNumCached') == 0, 'cached test')
    require(tuple(proto_int(summary, k) for k in ('totalRunCount', 'runCount', 'attemptCount', 'shardCount')) == (1, 1, 1, 0), 'retried/repeated/sharded test')
    info = result.get('executionInfo', {})
    require(info.get('strategy') in ('local', 'standalone', 'sandboxed', 'darwin-sandbox') and info.get('cachedRemotely', False) is False and proto_int(info, 'exitCode') == 0, 'not successful uncached local native execution')
    references = [item for item in result.get('testActionOutput', []) if item.get('name') == 'test.log']
    require(len(references) == 1 and len(summary.get('passed', [])) == 1 and not summary.get('failed'), 'ambiguous/missing test logs')
    for reference in references + summary['passed']:
        uri = urllib.parse.urlparse(reference.get('uri', ''))
        require(uri.scheme == 'file' and not uri.netloc and not uri.query and not uri.fragment and Path(urllib.parse.unquote(uri.path)).resolve() == log_path.resolve(), 'BEP log path mismatch')
        require('length' not in reference or str(reference['length']) == str(len(log_bytes)), 'BEP log length mismatch')
        require(not reference.get('digest') or reference['digest'] == digest(log_bytes), 'BEP log digest mismatch')
    return {'effective_options': effective, 'event_count': len(events), 'result_identity': identity, 'result': result, 'summary': summary, 'log_sha256': digest(log_bytes), 'complete_event_graph': True}


def macho(path):
    require(path.is_file() and not path.is_symlink(), 'native binary absent/linked')
    data = path.read_bytes()
    require(len(data) >= 8 and data[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack('<I', data[4:8])[0] == 0x0100000C, 'not native ARM64 Mach-O')
    return {'path': str(path), 'bytes': len(data), 'sha256': digest(data)}


def validate_bazel_asset(data):
    require(len(data) == PINNED_BAZEL['bytes'] and digest(data) == PINNED_BAZEL['sha256'], 'official Bazel asset mismatch')
    require(data[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack('<I', data[4:8])[0] == 0x0100000C, 'Bazel asset is not native ARM64 Mach-O')
    return data


def checked_bazel_tool(path):
    require(path.is_absolute() and path.name == 'bazel' and path.parent.name == 'a32-eval-tools', 'wrong task-local Bazel path')
    require(path.is_file() and not path.is_symlink(), 'Bazel tool absent/linked')
    validate_bazel_asset(path.read_bytes())
    require(path.stat().st_mode & stat.S_IXUSR, 'Bazel tool is not executable')
    return macho(path)


def extract_dotslash(data):
    require(len(data) == DOTSLASH['bytes'] and digest(data) == DOTSLASH['sha256'], 'official DotSlash asset mismatch')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = [m for m in archive.getmembers() if Path(m.name).name == 'dotslash']
        require(len(members) == 1 and members[0].isfile() and not members[0].issym() and not members[0].islnk() and 0 < members[0].size <= 8 * 1024 * 1024, 'invalid DotSlash member')
        result = archive.extractfile(members[0]).read(8 * 1024 * 1024 + 1)
        require(len(result) == members[0].size, 'invalid DotSlash payload length')
    return result


class Observer:
    def __init__(self, repo, out, artifact_root):
        self.repo, self.out = repo, out
        self.live = Path(tempfile.mkdtemp(prefix='a32-eval-live-', dir=artifact_root.parent))
        require(self.live != artifact_root and artifact_root not in self.live.parents, 'live outputs must not be uploaded')
        self.commands = []

    def command(self, name, argv):
        require(re.fullmatch('[a-z0-9-]+', name) is not None and not any(c['name'] == name for c in self.commands), 'duplicate/invalid command name')
        stdout, stderr = self.live / (name + '.stdout'), self.live / (name + '.stderr')
        started = time.monotonic()
        record = {'name': name, 'argv': argv, 'cwd': str(self.repo), 'settled': False, 'signals_sent': False}
        self.commands.append(record)
        self.save()
        with stdout.open('wb') as output, stderr.open('wb') as error:
            try:
                completed = subprocess.run(argv, cwd=self.repo, stdout=output, stderr=error)
                rc = completed.returncode
            except OSError as exc:
                rc = 127
                error.write((str(exc) + '\n').encode())
        # No observation timeout: all writers have settled before copying logs.
        out, err = stdout.read_bytes(), stderr.read_bytes()
        (self.out / (name + '.stdout')).write_bytes(out)
        (self.out / (name + '.stderr')).write_bytes(err)
        record.update(settled=True, exit_code=rc, elapsed_seconds=round(time.monotonic() - started, 3), stdout_sha256=digest(out), stderr_sha256=digest(err))
        self.save()
        return rc, out, err

    def save(self):
        (self.out / 'commands.json').write_text(json.dumps(self.commands, indent=2) + '\n')


def validate_arguments(argv, census=False):
    require(len(argv) == (17 if census else 16), 'unexpected native argument count')
    dynamic = {1: '--output_base=', 2: '--output_user_root=', 7: '--symlink_prefix=', 13: '--build_event_json_file='}
    for position, prefix in dynamic.items():
        require(argv[position].startswith(prefix) and Path(argv[position][len(prefix):]).is_absolute(), 'invalid isolated output argument')
    require(Path(argv[0]).is_absolute() and Path(argv[0]).name == 'bazel' and Path(argv[0]).parent.name == 'a32-eval-tools', 'not task-local direct Bazel')
    expected = [argv[0], argv[1], argv[2], 'test', '--config=ci-macos', '--lockfile_mode=error', '--noenable_runfiles', argv[7], '--remote_cache=', '--remote_executor=', '--bes_backend=', '--nocache_test_results', '--test_output=all', argv[13]]
    if census:
        expected += ['--test_arg=--list']
    expected += ['--', TARGET]
    require(argv == expected, 'native argv differs from exact unfiltered/default-parallel contract')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('preflight', 'install-tools', 'run'))
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--artifact-root', type=Path, required=True)
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.artifact_root.resolve()
    require(repo != root and repo not in root.parents, 'evidence must be outside checkout')
    out = root / args.stage
    require(not out.exists(), 'refuse evidence overwrite')
    out.mkdir(parents=True)
    observer = Observer(repo, out, root)
    receipt = {'schema': 'a32.eval-lock-native-receipt.v2', 'stage': args.stage, 'complete': False, 'qualified': False, 'source_sha': args.source_sha, 'rounds_preregistered': ROUNDS, 'signals_sent': False, 'results': []}
    before = None
    try:
        host_guard()
        require(args.source_sha == os.environ.get('GITHUB_SHA'), 'not exact event SHA')
        before = checked_source(repo, args.source_sha)
        (out / 'source-before.json').write_text(json.dumps(before, sort_keys=True) + '\n')
        receipt.update(source_tree=before['tree'], product_tree=PRODUCT_TREE, host={k: os.environ.get(k) for k in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')}, environment={k: os.environ.get(k) for k in FORBIDDEN_ENV + ('CODEX_SANDBOX', 'CODEX_SANDBOX_NETWORK_DISABLED', 'RUSTUP_TOOLCHAIN')})
        if args.stage == 'preflight':
            receipt['complete'] = True
            return 0
        tool_dir = root.parent / 'a32-eval-tools'
        if args.stage == 'install-tools':
            # Direct official assets only. No Bazelisk discovery, install script,
            # host rc edits, default GitHub token, or executable from a redirect
            # is used before the pinned final bytes and architecture are checked.
            with urllib.request.urlopen(DOTSLASH['url']) as response:
                archive = response.read(DOTSLASH['bytes'] + 1)
            dotslash = extract_dotslash(archive)
            with urllib.request.urlopen(PINNED_BAZEL['url']) as response:
                bazel_data = validate_bazel_asset(response.read(PINNED_BAZEL['bytes'] + 1))
            require(not tool_dir.exists(), 'refuse existing tool directory')
            tool_dir.mkdir()
            dot_tool, bazel_tool = tool_dir / 'dotslash', tool_dir / 'bazel'
            for path, data in ((dot_tool, dotslash), (bazel_tool, bazel_data)):
                path.write_bytes(data)
                path.chmod(0o755)
            dot_info, bazel_info = macho(dot_tool), checked_bazel_tool(bazel_tool)
            rc, stdout, _ = observer.command('dotslash-version', [str(dot_tool), '--version'])
            require(rc == 0 and stdout.strip() == b'DotSlash 0.5.9', 'wrong DotSlash version')
            rc, stdout, _ = observer.command('direct-bazel-version', [str(bazel_tool), '--version'])
            require(rc == 0 and stdout.strip() == b'bazel 9.3.0', 'wrong direct Bazel version')
            receipt.update(complete=True, tools={'dotslash': {'asset': DOTSLASH, 'binary': dot_info}, 'bazel': {'asset': PINNED_BAZEL, 'binary': bazel_info}}, tool_directory=str(tool_dir))
            return 0
        bazel_tool = tool_dir / 'bazel'
        receipt['direct_bazel'] = checked_bazel_tool(bazel_tool)
        output_base = root.parent / 'a32-eval-bazel'
        require(not output_base.exists(), 'refuse prior Bazel output directory')
        output_base.mkdir()
        bazel = [str(bazel_tool), '--output_base=' + str(output_base / 'output'), '--output_user_root=' + str(output_base / 'user')]
        flags = ['--config=ci-macos', '--lockfile_mode=error', '--noenable_runfiles', '--symlink_prefix=' + str(output_base / 'links') + '/', '--remote_cache=', '--remote_executor=', '--bes_backend=']
        rc, output, _ = observer.command('bazel-version', bazel + ['version', '--gnu_format'])
        require(rc == 0 and b'bazel 9.3.0' in output.lower(), 'wrong Bazel version')
        rc, output, _ = observer.command('configured-closure', bazel + ['cquery', 'deps(' + TARGET + ')', *flags, '--output=label'])
        require(rc == 0, 'locked configured closure failed')
        receipt['closure'] = validate_closure(output)
        rc, output, _ = observer.command('qualification-edge', bazel + ['cquery', 'deps(' + TEST_LIB + ', 1)', *flags, '--output=label'])
        require(rc == 0, 'qualification edge query failed')
        direct = closure_labels(output)
        require(QUALIFIER in direct and '//codex-rs/hepta-learning-ledger:hepta-learning-ledger' not in direct, 'qualification-lib replacement lost')
        rc, _, _ = observer.command('compile-original-target', bazel + ['build', *flags, '--', TARGET])
        require(rc == 0, 'native compilation failed')
        rc, output, _ = observer.command('execution-root', bazel + ['info', *flags, 'execution_root'])
        require(rc == 0, 'execution root unavailable')
        execution_root = Path(output.decode().strip()).resolve()
        require(output_base.resolve() in execution_root.parents, 'execution root outside isolated output')
        rc, output, _ = observer.command('binary-inventory', bazel + ['cquery', BINARY, *flags, '--output=files'])
        require(rc == 0, 'binary query failed')
        paths = [line for line in output.decode().splitlines() if line.startswith('bazel-out/')]
        require(len(paths) == 1 and '..' not in Path(paths[0]).parts, 'ambiguous/unsafe native binary')
        binary_path = (execution_root / paths[0]).resolve()
        require(execution_root in binary_path.parents, 'binary outside execution root')
        binary = macho(binary_path)
        receipt['binary'] = binary
        rc, output, _ = observer.command('testlog-root', bazel + ['info', *flags, 'bazel-testlogs'])
        require(rc == 0, 'testlog root unavailable')
        testlog_root = Path(output.decode().strip()).resolve()
        require(output_base.resolve() in testlog_root.parents, 'testlogs outside isolated output')
        testdir = testlog_root / 'codex-rs/hepta-intelligence-eval/hepta-intelligence-eval-unit-tests'
        census = None
        for number in range(ROUNDS + 1):
            host_guard()
            require(checked_bazel_tool(bazel_tool) == receipt['direct_bazel'], 'Bazel tool drift before invocation')
            require(checked_source(repo, args.source_sha) == before, 'source drift before native invocation')
            require(macho(binary_path) == binary, 'binary drift before native invocation')
            name = 'census' if number == 0 else f'full-{number:02}'
            bep = observer.live / (name + '.bep.json')
            argv = bazel + ['test', *flags, '--nocache_test_results', '--test_output=all', '--build_event_json_file=' + str(bep)]
            if number == 0:
                argv += ['--test_arg=--list']
            argv += ['--', TARGET]
            validate_arguments(argv, census=number == 0)
            rc, _, _ = observer.command(name, argv)
            result = {'name': name, 'exit_code': rc, 'qualified': False}
            receipt['results'].append(result)
            try:
                require(bep.is_file() and not bep.is_symlink(), 'BEP missing/invalid')
                bep_data = bep.read_bytes()
                (out / (name + '.bep.json')).write_bytes(bep_data)
                log = testdir / 'test.log'
                require(log.is_file() and not log.is_symlink(), 'native log missing/invalid')
                raw = log.read_bytes()
                (out / (name + '.test.log')).write_bytes(raw)
                xml = testdir / 'test.xml'
                require(xml.is_file() and not xml.is_symlink(), 'wrapper XML missing/invalid')
                (out / (name + '.test.xml')).write_bytes(xml.read_bytes())
                result['bep'] = validate_bep(bep_data, rc, log, raw, census=number == 0)
                if number == 0:
                    census = logs.parse_census(raw, before['manifest']['expected_census'])
                    result['census'] = census
                else:
                    result['observations'] = logs.parse_full(raw, census)
                result['qualified'] = True
            except Exception as exc:
                result['error'] = f'{type(exc).__name__}: {exc}'
            require(checked_bazel_tool(bazel_tool) == receipt['direct_bazel'], 'Bazel tool drift after invocation')
            require(checked_source(repo, args.source_sha) == before, 'source drift after native invocation')
            require(macho(binary_path) == binary, 'binary drift after native invocation')
            (out / 'results.json').write_text(json.dumps(receipt['results'], indent=2) + '\n')
            if number == 0:
                require(result['qualified'], 'compiled census prerequisite failed')
            # Always complete the preregistered 21 full runs, even after a test
            # or parser failure. They are separate observations, never retries.
        receipt['complete'] = True
        receipt['qualified'] = len(receipt['results']) == ROUNDS + 1 and all(r['qualified'] for r in receipt['results'])
        return 0 if receipt['qualified'] else 1
    except Exception as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        return 1
    finally:
        if before is not None:
            try:
                after = checked_source(repo, args.source_sha)
                (out / 'source-after.json').write_text(json.dumps(after, sort_keys=True) + '\n')
                require(before == after, 'final source/lock drift')
                receipt['source_unchanged'] = True
            except Exception as exc:
                receipt.update(qualified=False, source_unchanged=False, final_error=str(exc))
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if before is not None and receipt.get('source_unchanged') is not True:
            raise ValueError('final source verification failed')


if __name__ == '__main__':
    status = main()
    # A finally-stage identity failure must not leave a successful exit code.
    # The workflow also requires qualified=true from the final run receipt.
    sys.exit(status)
