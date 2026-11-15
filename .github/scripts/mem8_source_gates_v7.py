"""Qualify one immutable source tree in an isolated GitHub runner checkout.

Only format, diff, caller verification and complete-tree checks run here.
This operation does not reconcile or replay an unknown remote-host execution.
"""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import tomllib
import traceback

HEAD = '63a4c2492848e9560750c32bebaacce2762bf2a2'
TREE = '7592d3546c460ba1a2f543167be27eeba973c2b7'
BASE = '2ae5215beaf8d7b7df111a090b82134beae2683d'
BASE_TREE = '12159640adcf073b51f3837e75575e11f5c20233'
INPUT_SHA = '81bdc4cf1e93df3c8b9322f8a10f9a075eb1ad289c04bd2945fb523e54da099d'
INPUT_BYTES = 373068
PATH_COUNT = 114
GOLDEN_SHA = '17ac4ede6046ccde7f2a2952d2e3e699ff75258089e195b3783638ac9735fc96'
GOLDEN_BYTES = 75046
CALLERS_BLOB = 'c1a1b945171cdb20723e398cabe6a7888fa0abdb'
EXPECTED_RUST_FILES = 6204
REGRESSION_CASES = {'scripts/test_hepta_typed_callers.py': ['TypedAuthorityCallTests.test_absent_method_does_not_parse_unbalanced_owner', 'TypedAuthorityCallTests.test_arbitrary_parameter_and_borrowed_clone_alias', 'TypedAuthorityCallTests.test_arbitrary_typed_variable_field_without_authority_import', 'TypedAuthorityCallTests.test_arc_clone_preserves_the_original_authority_receiver', 'TypedAuthorityCallTests.test_constructor_binding_never_depends_on_receiver_name', 'TypedAuthorityCallTests.test_explicit_unrelated_type_does_not_manufacture_authority', 'TypedAuthorityCallTests.test_field_owner_is_visible_across_split_impl_module', 'TypedAuthorityCallTests.test_local_type_import_alias_and_type_alias_remain_target', 'TypedAuthorityCallTests.test_malformed_matching_owner_still_refuses', 'TypedAuthorityCallTests.test_opaque_possible_authority_receiver_refuses_closed', 'TypedAuthorityCallTests.test_qualified_use_does_not_hide_an_opaque_receiver', 'TypedAuthorityCallTests.test_same_variable_name_in_other_function_does_not_hide_call', 'TypedAuthorityCallTests.test_shared_clone_of_explicit_other_type_is_not_authority', 'TypedAuthorityCallTests.test_trait_impl_keeps_typed_authority_field', 'TypedAuthorityCallTests.test_type_alias_declared_in_another_module_remains_authority', 'TypedAuthorityCallTests.test_unknown_shared_clone_cannot_hide_possible_authority'], 'scripts/test_hepta_caller_cache.py': ['InvocationFieldIndexTests.test_no_method_call_does_not_suppress_global_field_index_failure', 'InvocationFieldIndexTests.test_two_boundary_proof_rejects_changed_source_on_next_invocation']}
AGENTS_BLOB = 'faa57cc0db48123e1011f1eb47692cd3bbbcfc3a'
LOCKS = {
    'codex-rs/Cargo.lock': '98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69',
    'MODULE.bazel.lock': '783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def info(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def listing(data):
    result = {}
    for record in data.split(b'\0'):
        if not record:
            continue
        meta, path = record.split(b'\t', 1)
        mode, kind, digest = meta.decode().split()
        name = path.decode()
        if name in result:
            raise RuntimeError('duplicate complete-tree path')
        result[name] = {'mode': mode, 'type': kind, 'git_blob': digest}
    return result


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())



def strict_json(raw):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON object key: ' + key)
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('non-JSON constant: ' + value)

    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
                      parse_constant=invalid_constant)


def canonical_json(value):
    # Preserve array ordering and scalar types; in particular false is not 0.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def rust_source_inventory(tree_entries, manifest_bytes):
    manifest = tomllib.loads(manifest_bytes.decode('utf-8'))
    roots = manifest['source_roots']
    if not isinstance(roots, list) or not roots or not all(isinstance(x, str) for x in roots):
        raise RuntimeError('invalid frozen caller source_roots')
    paths, by_root = [], []
    for root in roots:
        relative = PurePosixPath(root)
        if relative.is_absolute() or '..' in relative.parts or '.git' in relative.parts:
            raise RuntimeError('unsafe caller source root')
        prefix = relative.as_posix().rstrip('/') + '/'
        selected = []
        for name, row in sorted(tree_entries.items()):
            if name.startswith(prefix) and name.endswith('.rs'):
                if row['type'] != 'blob' or row['mode'] not in ('100644', '100755'):
                    raise RuntimeError('nonregular frozen Rust source: ' + name)
                selected.append(name)
        # Match _source_files exactly: each root contributes all *.rs paths;
        # ignored_path_fragments do not reduce rustFilesScanned.
        paths.extend(selected)
        by_root.append({'root': root, 'rust_files': len(selected)})
    return {'source_roots': roots, 'count_by_root': by_root, 'paths': sorted(paths),
            'rust_files': len(paths), 'ignored_path_fragments_applied': False}


def regression_counts(raw, expected, command_exit):
    text = raw.decode('utf-8')
    summaries = re.findall(r'^Ran (\d+) tests? in [0-9.]+s$', text, re.MULTILINE)
    named = []
    for method, identifier, outcome in re.findall(
        r'^(test_[A-Za-z0-9_]+) \(([^()\r\n]+)\) \.\.\. (.+)$', text, re.MULTILINE
    ):
        named.append({'method': method, 'id': identifier, 'outcome': outcome})
    expected_ids = ['__main__.' + case for case in expected]
    observed_ids = [row['id'] for row in named]
    passed = (command_exit == 0 and summaries == [str(len(expected))]
              and len(named) == len(expected)
              and len(observed_ids) == len(set(observed_ids))
              and sorted(observed_ids) == sorted(expected_ids)
              and all(row['outcome'] == 'ok' and row['id'].endswith('.' + row['method']) for row in named)
              and text.rstrip().endswith('\nOK'))
    return {'status': 'PASS' if passed else 'FAIL', 'command_exit': command_exit,
            'expected_case_ids': expected_ids, 'named_cases': named,
            'ran_test_summaries': summaries,
            'actual_named_pass': sum(row['outcome'] == 'ok' for row in named),
            'actual_named_fail': sum(row['outcome'] in ('FAIL', 'ERROR', 'unexpected success') for row in named),
            'actual_named_skip': sum(row['outcome'].startswith('skipped') for row in named),
            'raw': info(raw), 'no_native_or_model_execution': True}


def main():
    parser = argparse.ArgumentParser()
    for flag in ('source', 'output', 'input', 'golden', 'expected-head', 'expected-tree', 'base'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--timeout-seconds', required=True, type=int)
    args = parser.parse_args()
    if (args.expected_head, args.expected_tree, args.base, args.timeout_seconds) != (HEAD, TREE, BASE, 600):
        raise RuntimeError('qualification identity or budget differs from frozen request')
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    input_path = Path(args.input)
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    if source != workspace / 'source' or output != Path(os.environ['RUNNER_TEMP']).resolve() / 'mem8-source-gates-v7':
        raise RuntimeError('unexpected isolated checkout or record directory')
    if input_path.is_symlink() or not input_path.is_file():
        raise RuntimeError('input is not a regular capsule')
    start = datetime.now(timezone.utc)
    deadline = time.monotonic() + 600
    output.mkdir(mode=0o700)
    records = output / 'records'
    records.mkdir(mode=0o700)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', GIT_OPTIONAL_LOCKS='0',
                       GIT_TERMINAL_PROMPT='0', RUSTUP_TOOLCHAIN='1.96.0',
                       CODEX_REPO_ROOT=str(source))
    for key in list(environment):
        if key.startswith(('GIT_TRACE', 'HEPTA_LOCAL_PROVIDER_', 'HEPTA_MEM_CONTEXT_', 'HEPTA_MEM_NATIVE_')) or key in {
            'GIT_CURL_VERBOSE', 'CARGO_BIN_EXE_codex', 'HEPTA_EPISODIC_DRAIN_REGRESSION_CASE'
        }:
            environment.pop(key)

    def save(name, value):
        write(records / name, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())

    def git(*argv):
        remaining = min(30, deadline - time.monotonic() - 2)
        if remaining <= 0:
            raise TimeoutError('source-only deadline exhausted before Git read')
        return subprocess.check_output(['git', '--no-replace-objects', *argv], cwd=source,
                                       env=environment, timeout=remaining)

    def identity():
        return {'head': git('rev-parse', 'HEAD').decode().strip(),
                'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
                'status': git('status', '--porcelain=v1', '--untracked-files=all').decode()}

    def command(label, argv, *, cwd=source, allowed=(0,)):
        remaining = deadline - time.monotonic() - 3
        if remaining <= 0:
            raise TimeoutError('source-only deadline exhausted before ' + label)
        raw_path = records / (label + '.raw.log')
        started = now()
        timed_out = False
        cleanup = None
        with raw_path.open('xb') as stream:
            child = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                code = child.wait(timeout=max(0.1, min(2, deadline - time.monotonic())))
                cleanup = {'owned_process_group': child.pid, 'signal': 'SIGKILL', 'reaped_exit_code': code}
            stream.flush()
            os.fsync(stream.fileno())
        raw = raw_path.read_bytes()
        receipt = {'command': argv, 'cwd': str(cwd), 'started_at': started,
                   'finished_at': now(), 'exit_code': code, 'timed_out': timed_out,
                   'cleanup': cleanup, 'raw_file': raw_path.name, **info(raw)}
        save(label + '.json', receipt)
        print(json.dumps({'phase': label, **receipt}), flush=True)
        if timed_out or code not in allowed:
            raise RuntimeError(label + ' failed; original receipt and output retained')
        return raw

    def pins(label, rows):
        result = []
        for row in rows:
            path = source / row['path']
            if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
                raise RuntimeError('missing or unsafe reviewed source: ' + row['path'])
            data = path.read_bytes()
            mode = '100755' if path.stat().st_mode & 0o111 else '100644'
            if mode != row['mode']:
                raise RuntimeError('source mode changed: ' + row['path'])
            write(records / label / row['path'], data)
            result.append({'path': row['path'], 'mode': mode, 'group': row['group'],
                           'preimage_git_blob': row['preimage_git_blob'], **info(data)})
        save(label + '-FILES.json', result)
        return result

    def lock_pins():
        result = []
        for path, digest in LOCKS.items():
            data = (source / path).read_bytes()
            if info(data)['sha256'] != digest:
                raise RuntimeError('unexpected source-only lock drift: ' + path)
            result.append({'path': path, **info(data)})
        return result

    status, failure, completed = 'failed', None, []
    source_before = source_after = candidate_tree = None
    rows = []
    source_python_regressions = {}
    caller_equivalence = None
    try:
        encoded = input_path.read_bytes()
        if (len(encoded), info(encoded)['sha256']) != (INPUT_BYTES, INPUT_SHA):
            raise RuntimeError('frozen V7 input bytes differ')
        config_bytes = lzma.decompress(encoded)
        config = json.loads(config_bytes)
        rows = config['files']
        expected = {row['path'] for row in rows}
        if (config['base_sha'], config['base_tree'], config['source_gate_run_version']) != (BASE, BASE_TREE, 7):
            raise RuntimeError('unexpected source capsule lineage')
        if config['ready_to_execute'] is not True or config['execution_scope'] != 'source-only-format-caller-and-full-tree-scan':
            raise RuntimeError('capsule not frozen for source-only execution')
        if len(expected) != len(rows) or len(rows) != PATH_COUNT:
            raise RuntimeError('unexpected reviewed path inventory')
        golden_path = Path(args.golden)
        if (golden_path.is_symlink() or not golden_path.is_file()
                or golden_path.resolve() != workspace / 'harness' / 'qualification' / 'memory-cell-mem8-source-gates-v7' / 'GOLDEN_CALLER_RECEIPT.json'):
            raise RuntimeError('golden caller receipt is not the separate frozen harness input')
        golden_bytes = golden_path.read_bytes()
        write(records / 'GOLDEN_CALLER_RECEIPT.json', golden_bytes)
        if (len(golden_bytes), info(golden_bytes)['sha256']) != (GOLDEN_BYTES, GOLDEN_SHA):
            raise RuntimeError('golden caller receipt exact bytes differ')
        golden = strict_json(golden_bytes)
        if (golden.get('schema'), golden.get('status'), golden.get('authorityGranted'),
                golden.get('rustFilesScanned')) != (
                'hepta.caller-proof-receipt.v2', 'PASS_HEPTA_CALLER_CLOSED_SET', False, 6200):
            raise RuntimeError('unexpected original golden caller receipt')
        if config['expected_initial_tree'] != TREE or len(config['case_renames']) != 13:
            raise RuntimeError('initial tree or original whole-tree rename inventory differs')
        if {key: config['reference_caller_receipt'][key] for key in ('bytes', 'sha256', 'git_blob')} != info(golden_bytes):
            raise RuntimeError('capsule golden reference differs from retained original')
        write(records / 'DRIVER.py', Path(__file__).read_bytes())
        write(records / 'INPUT.json.xz', encoded)
        write(records / 'INPUT.json', config_bytes)
        source_before = identity()
        if source_before != {'head': HEAD, 'tree': TREE, 'status': ''}:
            raise RuntimeError('checkout is not the exact clean qualification candidate')
        agents = (source / 'AGENTS.md').read_bytes()
        if info(agents)['git_blob'] != AGENTS_BLOB:
            raise RuntimeError('repository instructions changed')
        write(records / 'AGENTS.md', agents)
        base_listing = git('ls-tree', '-r', '-z', BASE)
        initial_listing = git('ls-tree', '-r', '-z', HEAD)
        if git('rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            raise RuntimeError('comparison base tree differs')
        write(records / 'BASE_TREE.ls-tree', base_listing)
        write(records / 'INITIAL_TREE.ls-tree', initial_listing)
        expected_tree = listing(base_listing)
        for row in rows:
            path = PurePosixPath(row['path'])
            if path.is_absolute() or '..' in path.parts or '.git' in path.parts or row['mode'] != '100644':
                raise RuntimeError('unsafe input path or mode')
            if not (source / path).resolve().is_relative_to(source):
                raise RuntimeError('reviewed path escapes source')
            pre = expected_tree.get(row['path'])
            if (pre or {}).get('git_blob') != row['preimage_git_blob']:
                raise RuntimeError('capsule preimage differs from exact base')
            if pre:
                write(records / 'base' / row['path'], git('cat-file', 'blob', pre['git_blob']))
            data = (source / row['path']).read_bytes()
            if info(data) != {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['input_git_blob']}:
                raise RuntimeError('candidate postimage differs from reviewed capsule: ' + row['path'])
            if data != row['content'].encode():
                raise RuntimeError('candidate content differs from frozen bytes')
            expected_tree[row['path']] = {'mode': row['mode'], 'type': 'blob', 'git_blob': row['input_git_blob']}
        if listing(initial_listing) != expected_tree:
            raise RuntimeError('complete initial tree differs from base plus frozen 114-path overlay')
        if set(git('diff', '--name-only', BASE, HEAD).decode().splitlines()) != expected:
            raise RuntimeError('initial changed-path set differs from capsule')
        caller_manifest = (source / 'CALLERS.toml').read_bytes()
        if info(caller_manifest)['git_blob'] != CALLERS_BLOB or expected_tree['CALLERS.toml']['git_blob'] != CALLERS_BLOB:
            raise RuntimeError('frozen caller manifest changed')
        write(records / 'CALLERS.toml', caller_manifest)
        caller_inventory = rust_source_inventory(expected_tree, caller_manifest)
        if caller_inventory['rust_files'] != EXPECTED_RUST_FILES:
            raise RuntimeError('full frozen tree Rust source count differs from reviewed inventory')
        save('CALLER_SOURCE_INVENTORY.json', {
            'initial_commit': HEAD, 'initial_tree': TREE, 'caller_manifest': info(caller_manifest),
            'original_golden_count': golden['rustFilesScanned'],
            'derived_count_delta': caller_inventory['rust_files'] - golden['rustFilesScanned'],
            'only_allowed_receipt_field_change': 'rustFilesScanned', **caller_inventory})
        locks_before = lock_pins()
        save('START.json', {'started_at': start.isoformat(), 'deadline_utc': (start + timedelta(seconds=600)).isoformat(),
             'source_before': source_before, 'source_input': info(encoded), 'locks': locks_before,
             'workflow_commit': os.environ['GITHUB_SHA'], 'workflow_run': os.environ['GITHUB_RUN_ID'],
             'workflow_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
             'native_tests_executed': 0, 'model_requests_executed': 0,
             'donor_used': False, 'source_origin': 'exact immutable Git commit; no borrowed host checkout'})
        before_format = pins('pre-format', rows)
        write(records / 'candidate-before-format.patch', git('diff', '--binary', BASE))
        just = command('just-version', ['just', '--version'])
        rustfmt = command('rustfmt-version', ['rustfmt', '--version'], cwd=source / 'codex-rs')
        if just.strip() != b'just 1.51.0' or rustfmt.strip() != b'rustfmt 1.9.0-stable (ac68faa20c 2026-05-25)':
            raise RuntimeError('source formatter version differs from frozen tool versions')
        tools = []
        for name in ('just', 'rustfmt', 'uv', 'dotslash'):
            resolved = shutil.which(name, path=environment['PATH'])
            if not resolved:
                raise RuntimeError('missing formatter prerequisite: ' + name)
            physical = Path(resolved).resolve()
            if name == 'dotslash' and (physical.stat().st_size, info(physical.read_bytes())['sha256']) != (
                1642752, '54a03b42f0337eba584bc33563237d45aeca11a34de2e7159f76d7695fe5b936'
            ):
                raise RuntimeError('DotSlash binary differs from qualified v0.5.9 bytes')
            tools.append({'name': name, 'kind': 'PATH entry, potentially a launcher',
                          'path': str(physical), **info(physical.read_bytes())})
        rustfmt_path = command('rustfmt-physical-path', ['rustup', 'which', '--toolchain', '1.96.0', 'rustfmt'])
        physical_rustfmt = Path(rustfmt_path.decode().strip()).resolve()
        if not physical_rustfmt.is_file():
            raise RuntimeError('qualified rustfmt physical binary is missing')
        tools.append({'name': 'rustfmt', 'kind': 'Rust 1.96.0 toolchain binary',
                      'path': str(physical_rustfmt), **info(physical_rustfmt.read_bytes())})
        save('CI_TOOL_IDENTITIES.json', tools)
        command('format', ['just', 'fmt', '--base', BASE])
        completed.append('format')
        postimages = pins('post-format', rows)
        if set(git('diff', '--name-only', BASE).decode().splitlines()) != expected:
            raise RuntimeError('formatter changed unexpected source paths')
        if git('ls-files', '--others', '--exclude-standard') or lock_pins() != locks_before:
            raise RuntimeError('formatter left unexpected files or lock drift')
        save('FORMAT_RESULT.json', {'status': 'passed', 'before': before_format, 'after': postimages,
             'formatter_changed_paths': [a['path'] for a, b in zip(before_format, postimages) if a != b],
             'yaml_note': 'Repository just fmt has no YAML formatter; reviewed bytes stay pinned.'})
        command('diff-check', ['git', 'diff', '--check', BASE])
        write(records / 'candidate-after-format.patch', git('diff', '--binary', BASE))
        rename_args = ['git', 'grep', '-n', '-I', '-w', '-F']
        for old in sorted(config['case_renames']):
            rename_args.extend(['-e', old])
        rename_raw = command('full-tree-old-case-name-scan', [*rename_args, '--'], allowed=(0, 1))
        matches = []
        for line in rename_raw.decode('utf-8', errors='replace').splitlines():
            path, number, text = line.split(':', 2)
            matches.append({'path': path, 'line': int(number), 'text': text,
                            'historical_qualification_path': path.startswith('qualification/')})
        save('FULL_TREE_RENAME_SCAN.json', {'scope': 'all tracked text files, whole-word fixed strings, no path exclusion',
             'renames': config['case_renames'], 'matches': matches, 'review_required': bool(matches),
             'historical_sources_must_not_be_rewritten': True})
        completed.append('full-tree-rename-scan')
        for script, expected_cases in REGRESSION_CASES.items():
            label = 'python-' + Path(script).stem
            raw = command(label, [sys.executable, '-B', script, '-v'], allowed=(0, 1))
            phase = strict_json((records / (label + '.json')).read_bytes())
            counts = regression_counts(raw, expected_cases, phase['exit_code'])
            source_python_regressions[label] = counts
            save(label + '-COUNTS.json', counts)
            if counts['status'] != 'PASS':
                raise RuntimeError('source Python regression identities/counts/OK check failed: ' + label)
            completed.append(label)
        self_test_raw = command('caller-self-test', [sys.executable, '-B', 'scripts/verify_hepta_callers.py', 'self-test'])
        self_test = strict_json(self_test_raw)
        if canonical_json(self_test) != canonical_json({'status': 'PASS_HEPTA_CALLER_PROOF_SELF_TEST'}):
            raise RuntimeError('caller self-test receipt differs from the original exact status')
        save('CALLER_SELF_TEST_CHECK.json', {'status': 'PASS', 'receipt': self_test, 'raw': info(self_test_raw)})
        completed.append('caller-self-test')
        caller_raw = command('caller-verify', [sys.executable, '-B', 'scripts/verify_hepta_callers.py', 'verify'])
        actual_caller = strict_json(caller_raw)
        expected_caller = strict_json(golden_bytes)
        expected_caller['rustFilesScanned'] = caller_inventory['rust_files']
        save('EXPECTED_CALLER_RECEIPT.json', expected_caller)
        equal = canonical_json(actual_caller) == canonical_json(expected_caller)
        caller_equivalence = {
            'status': 'PASS' if equal else 'FAIL', 'full_json_comparison': True,
            'array_order_and_scalar_types_preserved': True, 'duplicate_object_keys_rejected': True,
            'ignored_receipt_fields': [], 'only_derived_field': 'rustFilesScanned',
            'original_golden': info(golden_bytes), 'actual_original_raw': info(caller_raw),
            'original_golden_count': golden['rustFilesScanned'],
            'derived_frozen_tree_count': caller_inventory['rust_files'],
            'explicit_count_delta': caller_inventory['rust_files'] - golden['rustFilesScanned'],
            'expected_canonical_sha256': info(canonical_json(expected_caller))['sha256'],
            'actual_canonical_sha256': info(canonical_json(actual_caller))['sha256']}
        save('CALLER_GOLDEN_COMPARISON.json', caller_equivalence)
        if not equal:
            raise RuntimeError('full caller JSON differs beyond the frozen-tree-derived Rust count')
        completed.append('caller-verify')
        for row in postimages:
            if info((source / row['path']).read_bytes()) != {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}:
                raise RuntimeError('source changed during caller verification')
        if lock_pins() != locks_before:
            raise RuntimeError('locks changed during source qualification')
        command('stage-formatted-candidate', ['git', 'add', '--', *sorted(expected)])
        if git('diff', '--name-only') or git('ls-files', '--others', '--exclude-standard'):
            raise RuntimeError('unreviewed unstaged or untracked source remains')
        current = identity()
        if (current['head'], current['tree']) != (HEAD, TREE):
            raise RuntimeError('source HEAD moved during qualification')
        if set(git('diff', '--cached', '--name-only', BASE).decode().splitlines()) != expected:
            raise RuntimeError('staged delta differs from all 114 reviewed paths')
        for row in postimages:
            path = source / row['path']
            mode = '100755' if path.stat().st_mode & 0o111 else '100644'
            if path.is_symlink() or mode != row['mode'] or info(path.read_bytes()) != {
                key: row[key] for key in ('bytes', 'sha256', 'git_blob')
            }:
                raise RuntimeError('final source bytes or mode differ from formatted postimage')
            expected_tree[row['path']] = {'mode': row['mode'], 'type': 'blob', 'git_blob': row['git_blob']}
        candidate_tree = git('write-tree').decode().strip()
        candidate_listing = git('ls-tree', '-r', '-z', candidate_tree)
        write(records / 'CANDIDATE_TREE.ls-tree', candidate_listing)
        if listing(candidate_listing) != expected_tree:
            raise RuntimeError('complete formatted tree differs from exact base plus reviewed overlay')
        save('COMPLETE_TREE_OVERLAY.json', {'base_tree': BASE_TREE, 'candidate_tree': candidate_tree,
             'base_plus_overlay_matches_all_candidate_entries': True,
             'complete_candidate_entry_count': len(expected_tree), 'overlay_paths': len(postimages)})
        capsule = {'base_commit': BASE, 'base_tree': BASE_TREE, 'candidate_tree': candidate_tree,
                   'initial_commit': HEAD, 'initial_tree': TREE, 'native_tests_executed': 0,
                   'model_requests': 0, 'source_refs_modified': False, 'unresolved': config['unresolved'], 'files': []}
        for row in postimages:
            data = (source / row['path']).read_bytes()
            capsule['files'].append({'path': row['path'], 'mode': row['mode'],
                'preimage_git_blob': row['preimage_git_blob'], 'postimage_git_blob': row['git_blob'],
                'postimage_bytes': row['bytes'], 'postimage_sha256': row['sha256'],
                'content_base64': base64.b64encode(data).decode()})
        save('FORMATTED_CAPSULE.json', capsule)
        source_after = identity()
        if time.monotonic() >= deadline:
            raise TimeoutError('source-only qualification exceeded its original 600-second deadline')
        status = 'passed_source_gates_only_review_remaining'
    except Exception:
        failure = traceback.format_exc()
        write(records / 'DRIVER_FAILURE.txt', failure.encode())
    finally:
        if status != 'passed_source_gates_only_review_remaining':
            # Preserve partially rewritten reviewed files even when fmt failed.
            # This observation cannot turn a failure into qualification.
            partial = {'status': 'UNQUALIFIED_FAILURE_OBSERVATION', 'observed_at': now(),
                       'scope': 'at most 114 reviewed paths, not a complete dirty-tree claim',
                       'paths': [], 'complete_reviewed_path_capture': True,
                       'git_observation': 'not_attempted', 'errors': []}
            remaining_bytes = 16 * 1024 * 1024
            for row in rows:
                observed = {'path': row['path']}
                try:
                    path = source / row['path']
                    stat = path.lstat()
                    observed['observed_size'] = stat.st_size
                    observed['observed_mode'] = oct(stat.st_mode)
                    if not path.is_file() or path.is_symlink() or stat.st_nlink != 1:
                        raise RuntimeError('unsafe or nonregular reviewed path')
                    if stat.st_size > min(2 * 1024 * 1024, remaining_bytes):
                        raise RuntimeError('partial capture byte bound exceeded')
                    data = path.read_bytes()
                    if len(data) != stat.st_size:
                        raise RuntimeError('reviewed file changed during partial observation')
                    write(records / 'failure-observation' / row['path'], data)
                    remaining_bytes -= len(data)
                    observed.update(info(data))
                except Exception as error:
                    partial['complete_reviewed_path_capture'] = False
                    observed['capture_error'] = str(error)
                partial['paths'].append(observed)
            if rows and deadline - time.monotonic() > 2:
                try:
                    source_after = identity()
                    write(records / 'failure-source-status.txt', source_after['status'].encode())
                    write(records / 'candidate-at-failure.patch', git('diff', '--binary', BASE))
                    partial['git_observation'] = 'original_deadline_bounded_identity_and_patch_saved'
                except Exception as error:
                    partial['git_observation'] = 'incomplete'
                    partial['errors'].append(str(error))
            else:
                partial['git_observation'] = 'not_run_original_deadline_exhausted_or_input_unvalidated'
            save('FAILURE_SOURCE_OBSERVATION.json', partial)
        result = {'status': status, 'failure': failure, 'started_at': start.isoformat(), 'finished_at': now(),
                  'deadline_utc': (start + timedelta(seconds=600)).isoformat(), 'completed': completed,
                  'initial_commit': HEAD, 'initial_tree': TREE, 'base_commit': BASE, 'base_tree': BASE_TREE,
                  'source_before': source_before, 'source_after': source_after, 'candidate_tree': candidate_tree,
                  'source_python_regressions': source_python_regressions,
                  'caller_golden_comparison': caller_equivalence,
                  'source_candidate_committed': False, 'source_refs_modified': False, 'donor_used': False,
                  'native_tests_executed': 0, 'model_requests_executed': 0,
                  'scope': 'Independent CI source-only operation; no remote execution reconciliation or native qualification'}
        save('RESULT.json', result)
        print(json.dumps(result), flush=True)
        inventory = []
        for path in sorted(records.rglob('*')):
            if path.is_symlink():
                raise RuntimeError('unsafe record member')
            if path.is_file():
                inventory.append({'path': path.relative_to(records).as_posix(), **info(path.read_bytes())})
        save('FILE_MANIFEST.json', {'schema': 'hepta.mem8.ci-source.records.v1', 'members': inventory})
        archive = output / 'mem8-source-gates-v7-records.tar.xz'
        with archive.open('xb') as stream:
            with tarfile.open(fileobj=stream, mode='w:xz', preset=6) as tar:
                for path in sorted(records.rglob('*')):
                    if path.is_file():
                        data = path.read_bytes()
                        member = tarfile.TarInfo(path.relative_to(records).as_posix())
                        member.size, member.mode, member.mtime = len(data), 0o600, 0
                        tar.addfile(member, io.BytesIO(data))
            stream.flush()
            os.fsync(stream.fileno())
        write(output / 'ARCHIVE_INFO.json', (json.dumps({'path': archive.name,
              'members': len(inventory) + 1, **info(archive.read_bytes())}, indent=2) + '\n').encode())
    return 0 if status == 'passed_source_gates_only_review_remaining' else 1


if __name__ == '__main__':
    sys.exit(main())
