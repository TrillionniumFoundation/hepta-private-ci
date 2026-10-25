"""Generate four reviewed patch replacements and matching Bazel facts; never publish."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib
import urllib.request
import dependency_patch_support as support

BRANCH = 'research/dot-tls-patch-lock-generation-e4ee-20261025'
BASE_TREE = '1370b500afd30d73ab4b762ddad6a6457590bb12'
BASE = 'e4ee552d37040a62e8cee6ef4172aae8b6680204'
LOCKS = ('codex-rs/Cargo.lock', 'MODULE.bazel.lock')
BLOBS = {
    LOCKS[0]: '8a9eab30d8957daab7dd027e86e88ca792e04a1c',
    LOCKS[1]: 'b511f2f09a21057a3d3654e441a69835cbd91ce9',
    'codex-rs/Cargo.toml': 'd2703b590935ab17316e6c258657c0ce5ab7412a',
    'codex-rs/deny.toml': '677f941360b2d82ab96aa4d419d97f4616cc2194',
    'MODULE.bazel': 'a49ef6c1cf4cf6b12f76296cd488c93f0753905b',
    '.bazelrc': '0ce81ff3d71d30aeedd7240ee001dd8166364ee2',
    '.bazelversion': 'f7ee06693c17a06e2a0f51ef7eb2a61866e77b8e',
    'justfile': 'a215a76cf407ace9715bca39c20497014e7dd4dc',
    'tools/argument-comment-lint/Cargo.lock': '1795ff683b86672de2bd2a48a41b4274e3f63d2a',
}
CRATE_FACTS = '@@rules_rs+//rs:extensions.bzl%crate'
REGISTRY = 'registry+https://github.com/rust-lang/crates.io-index'
TARGETS = json.loads(Path(__file__).with_name('dependency_patch_targets.json').read_text())['targets']


class GateError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, reason):
    if not condition:
        raise GateError(reason)


def error_code(error):
    return error.code if isinstance(error, GateError) else 'unexpected_exception'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def read_lock(path):
    require(path.is_file() and not path.is_symlink(), 'lock_missing_or_symlink')
    require(path.stat().st_size <= 8 * 1024**2, 'lock_size_limit')
    return path.read_bytes()


def typed_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(typed_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(typed_equal(x, y) for x, y in zip(a, b))
    return a == b


def package_key(package):
    return package['name'], package['version'], package.get('source')


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise GateError('nonfinite_json_number')
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), 'nonfinite_json_number')
        return number
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant,
                      parse_float=finite_float)


def cargo_lexical_gate(original, updated):
    """No opaque TOML comments/trivia may add content outside parsed closure.
    Restrict to Cargo-generated single-line basic strings and ASCII syntax.
    Parser below independently validates the complete values and structure.
    """
    known_comments = {line.strip() for line in original.decode().splitlines()
                      if line.strip().startswith('#')}
    for line in updated.decode().splitlines():
        stripped = line.strip(' \t\r')
        if stripped.startswith('#'):
            require(stripped in known_comments, 'unexpected_cargo_comment')
            continue
        # No literal/multiline strings, inline comments, or non-ASCII syntax.
        remainder = re.sub(r'"(?:[^"\\\r\n]|\\.)*"', '""', line)
        require(re.fullmatch(r'[a-zA-Z0-9_=\[\],." \t\r-]*', remainder) is not None,
                'unreviewed_cargo_lexical_content')


def known_lock_content(before, after):
    cargo_lexical_gate(before[LOCKS[0]], after[LOCKS[0]])
    cargo_delta(before[LOCKS[0]], after[LOCKS[0]], TARGETS)
    bazel_delta(before[LOCKS[1]], after[LOCKS[1]])


def cargo_delta(original, updated, processed):
    """Only four registry records may change; other edge labels normalize exactly."""
    a, b = tomllib.loads(original.decode()), tomllib.loads(updated.decode())
    require(typed_equal({k:v for k,v in a.items() if k != 'package'},
            {k:v for k,v in b.items() if k != 'package'}), 'cargo_nonpackage_drift')
    old = {package_key(x): x for x in a['package']}
    new = {package_key(x): x for x in b['package']}
    require(len(old) == len(a['package']) and len(new) == len(b['package']), 'duplicate_packages')
    expected_keys = set(old)
    replacements = {}
    for target in processed:
        before = target['name'], target['old'], REGISTRY
        after = target['name'], target['new'], REGISTRY
        require(before in expected_keys, 'original_target_missing')
        expected_keys.remove(before)
        expected_keys.add(after)
        replacements[target['name'] + ' ' + target['old']] = target['name'] + ' ' + target['new']
        require(after in new, 'precise_target_missing')
        require(new[after].get('checksum') == target['checksum'], 'target_checksum_mismatch')
    require(expected_keys == set(new), 'unexpected_package_added_removed_or_version')
    target_keys = {(x['name'], x['old'], REGISTRY) for x in processed}
    changes = []
    for key, package in old.items():
        expected = copy.deepcopy(package)
        expected['dependencies'] = [replacements.get(d, d) for d in package.get('dependencies', [])]
        if 'dependencies' not in package:
            expected.pop('dependencies')
        if key in target_keys:
            target = next(x for x in processed if (x['name'], x['old'], REGISTRY) == key)
            current = new[(target['name'], target['new'], REGISTRY)]
            # Only the target's outgoing edges may change, and every destination must
            # resolve uniquely within the unchanged finite package roster.
            expected.update(version=target['new'], checksum=target['checksum'])
            expected_edges = list(expected.get('dependencies', []))
            require(current.get('dependencies', []) == expected_edges, 'unexpected_target_dependency_edges')
            expected['dependencies'] = expected_edges
            if 'dependencies' not in current:
                expected.pop('dependencies')
            require(typed_equal(expected, current), 'unexpected_target_record_fields')
            changes.append({'name': target['name'], 'old': target['old'], 'new': target['new'],
                            'old_dependencies': package.get('dependencies', []),
                            'new_dependencies': current.get('dependencies', [])})
        else:
            require(typed_equal(expected, new[key]), 'unexpected_nontarget_record_change')
    for package in b['package']:
        for dep in package.get('dependencies', []):
            parts = dep.split(' ', 2)
            candidates = [k for k in new if k[0] == parts[0]]
            if len(parts) > 1:
                candidates = [k for k in candidates if k[1] == parts[1]]
            if len(parts) > 2:
                candidates = [k for k in candidates if k[2] == parts[2].strip('()')]
            require(len(candidates) == 1, 'dependency_edge_not_unique')
    return changes


def bazel_delta(original, updated):
    """Only four crate facts may change; every other Bazel section stays exact."""
    a, b = strict_json(original), strict_json(updated)
    expected = copy.deepcopy(a)
    facts = expected.get('facts', {}).get(CRATE_FACTS)
    require(isinstance(facts, dict), 'bazel_schema_not_reviewed')
    actual = b.get('facts', {}).get(CRATE_FACTS, {})
    for target in TARGETS:
        old_key, new_key = target['name'] + '_' + target['old'], target['name'] + '_' + target['new']
        require(old_key in facts and new_key not in facts, 'bazel_original_target_fact_missing')
        require(new_key in actual and old_key not in actual, 'bazel_target_fact_not_replaced')
        require(json.dumps(strict_json(actual[new_key]), sort_keys=True) == json.dumps(target['fact'], sort_keys=True), 'bazel_fact_not_registry_exact')
        del facts[old_key]
        facts[new_key] = actual[new_key]
    require(json.dumps(expected, sort_keys=True) == json.dumps(b, sort_keys=True), 'unexpected_bazel_registry_extension_or_fact_drift')


def configuration_gate(repo):
    """Never turn opt-in agreement/remote/security knobs into implicit acceptance."""
    require(not (repo / 'user.bazelrc').exists(), 'user_bazelrc_present')
    rc = (repo / '.bazelrc').read_text()
    for line in rc.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if re.search(r'(?i)(EULA|accept.*agreement|credential|api.key|authorization)', stripped):
            raise GateError('bazel_legal_or_credential_configuration')
        # Endpoint-bearing opt-in configurations may exist but are never selected.
        head = stripped.split()[0]
        if ':' not in head:
            require(not re.search(r'--(?:remote_executor|remote_cache|bes_backend|remote_header|config)=', stripped),
                    'implicit_remote_configuration')
    module = (repo / 'MODULE.bazel').read_text()
    active = '\n'.join(line for line in module.splitlines() if not line.lstrip().startswith('#'))
    require('BAZEL_MSVC_RUNTIME_VISUAL_STUDIO_EULA=1' not in active, 'implicit_eula_acceptance')
    require(not re.search(r'use_home_cargo_credentials\s*=\s*True', active), 'home_credentials_enabled')
    triples = re.findall(r'platform_triples\s*=\s*\[(.*?)\]', active, re.S)
    require(len(triples) == 2 and all(len(re.findall(r'"[a-z0-9_-]+"', x)) == 10 for x in triples),
            'platform_roster_changed')


def registry_recheck():
    """Recheck exact official sparse records: --precise can otherwise select yanked."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise GateError('registry_redirect_not_authorized')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    records = []
    for target in TARGETS:
        name = target['name']
        url = 'https://index.crates.io/' + name[:2] + '/' + name[2:4] + '/' + name
        request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
        with opener.open(request, timeout=30) as response:
            data = response.read(2 * 1024**2 + 1)
        require(len(data) <= 2 * 1024**2, 'registry_record_size_limit')
        matches = [row for row in map(json.loads, data.splitlines())
                   if row.get('name') == name and row.get('vers') == target['new']]
        require(len(matches) == 1, 'registry_target_missing_or_duplicate')
        row = matches[0]
        require(row.get('yanked') is False and row.get('cksum') == target['checksum'],
                'registry_yanked_or_checksum_mismatch')
        records.append({'url': url, 'index_bytes': len(data), 'index_sha256': digest(data),
                        'package': name, 'version': target['new'], 'yanked': False,
                        'checksum': row['cksum']})
    return records


CONTROL_FILES = (
    '.github/workflows/tls-patch-generation.yml',
    '.github/scripts/dependency_patch_generator.py',
    '.github/scripts/dependency_patch_support.py',
    '.github/scripts/dependency_patch_targets.json',
    '.github/scripts/test_dependency_patch_generator.py',
)


def control_gate(control, env, before=None):
    sha, workflow_sha = os.environ.get('GITHUB_SHA', ''), os.environ.get('GITHUB_WORKFLOW_SHA', '')
    require(bool(re.fullmatch('[0-9a-f]{40}', sha)) and sha == workflow_sha, 'control_event_workflow_sha_mismatch')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'push'
            and os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH,
            'control_trigger_mismatch')
    require(os.environ.get('GITHUB_WORKFLOW_REF') ==
            'TrillionniumFoundation/hepta-private-ci/.github/workflows/tls-patch-generation.yml@refs/heads/' + BRANCH,
            'control_workflow_ref_mismatch')
    support.identity(control, sha, None, env)
    tree = support.git(control, env, 'rev-parse', 'HEAD^{tree}').decode().strip()
    require(bool(re.fullmatch('[0-9a-f]{40}', tree)), 'control_tree_invalid')
    receipt = {'event_sha': sha, 'workflow_sha': workflow_sha, 'tree': tree, 'branch': BRANCH, 'event': 'push', 'files': {}}
    for path in CONTROL_FILES:
        expected = support.git(control, env, 'rev-parse', 'HEAD:' + path).decode().strip()
        data = read_lock(control / path)
        require(blob(data) == expected, 'control_file_blob_mismatch')
        receipt['files'][path] = {'git_blob': expected, 'sha256': digest(data)}
    require(before is None or receipt == before, 'control_changed')
    return receipt


def publication_allowed(report):
    return (report.get('qualified') is True and report.get('source_after_confirmed') is True
            and report.get('known_lock_content_confirmed') is True
            and report.get('control_after') == report.get('control_before')
            and report.get('control_before') is not None
            and all(command.get('cleanup', {}).get('confirmed') is True
                    and command.get('stop') is None
                    and command.get('exit') == 0
                    for command in report['commands']))


def metadata_commands():
    return [
        ['cargo', '+1.95.0', 'metadata', '--locked', '--all-features', '--format-version=1'],
        ['cargo', '+1.95.0', 'metadata', '--locked', '--offline', '--all-features', '--format-version=1'],
    ]


def main(repo, out, control):
    repo, out, control = repo.resolve(), out.resolve(), control.resolve()
    out.mkdir(parents=True, exist_ok=True)
    public = out / 'public'
    public.mkdir(exist_ok=True)
    for retained in public.iterdir():
        if retained.name not in {'before-Cargo.lock', 'before-MODULE.bazel.lock', 'report.json'} and retained.is_file():
            retained.unlink()  # Own output directory: never retain prior-run derived bytes.
    report = {'source_commit': BASE, 'source_tree': BASE_TREE, 'raw_stream_policy': 'never_publish', 'qualified': False, 'publish_allowed': False,
              'historical_cause_claim': False, 'commands': [], 'phases': [],
              'resource_limits': {'command_seconds': 1800, 'preflight_free_GiB': 20,
                                  'floor_GiB': 4, 'soft_total_disk_growth_GiB': 8,
                                  'quota_enforced': False}}
    before = {}
    env = {k: os.environ[k] for k in ['PATH', 'RUSTUP_HOME'] if k in os.environ}
    env.update(HOME=str(out / 'home'), CARGO_HOME=str(out / 'cargo'),
               RUSTUP_HOME=os.environ.get('RUSTUP_HOME', str(Path.home() / '.rustup')),
               LANG='C.UTF-8', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_TERMINAL_PROMPT='0', CARGO_NET_GIT_FETCH_WITH_CLI='true',
               ASPECT_TOOLS_TELEMETRY='-all', PYTHONDONTWRITEBYTECODE='1')
    Path(env['HOME']).mkdir(exist_ok=True)
    Path(env['CARGO_HOME']).mkdir(exist_ok=True)
    original_cwd = Path.cwd()

    def run(argv, seconds=1800, cwd=None):
        if cwd:
            os.chdir(cwd)
        result, streams = support.capture(argv, env, seconds, disk=out)
        report['commands'].append(result)
        require(result['exit'] == 0 and result['stop'] is None and result['cleanup']['confirmed'], 'owned_command_failed')
        return streams[0].retained()

    def no_unexpected_mutation():
        changed = support.git(repo, env, 'diff', 'HEAD', '--name-only').decode().splitlines()
        require(set(changed) <= set(LOCKS), 'source_mutated_outside_lock_allowlist')
        require(not support.git(repo, env, 'ls-files', '--others', '--exclude-standard'), 'unexpected_untracked_source')
        require(support.git(repo, env, 'rev-parse', 'HEAD').decode().strip() == BASE, 'source_head_changed')

    try:
        require(shutil.disk_usage(out).free >= 20 * 1024**3, 'preflight_disk_below_20GiB')
        support.DISK_INITIAL_FREE = shutil.disk_usage(out).free
        report['control_before'] = control_gate(control, env)
        support.identity(repo, BASE, None, env)
        require(support.git(repo, env, 'rev-parse', 'HEAD^{tree}').decode().strip() == BASE_TREE, 'source_tree_mismatch')
        for path, expected in BLOBS.items():
            require(blob(read_lock(repo / path)) == expected, 'immutable_input_blob_mismatch')
        require(support.input_gate(repo, env), 'complete_cargo_input_gate_failed')
        configuration_gate(repo)
        before = {path: read_lock(repo / path) for path in LOCKS}
        report['source_before'] = {p: {'sha256': digest(b), 'git_blob': blob(b)} for p,b in before.items()}
        for path, data in before.items():
            (public / ('before-' + Path(path).name)).write_bytes(data)
        for tool in ['cargo', 'rustc', 'bazel']:
            resolved = shutil.which(tool, path=env['PATH'])
            require(resolved is not None, 'required_tool_missing')
            report.setdefault('tool_paths', {})[tool] = {'sha256': digest(Path(resolved).read_bytes())}
        require(run(['cargo', '+1.95.0', '-V'], 60, repo).startswith(b'cargo 1.95.0 '), 'cargo_version_mismatch')
        require(run(['rustc', '+1.95.0', '-Vv'], 60, repo).startswith(b'rustc 1.95.0 '), 'rustc_version_mismatch')
        for tool in ['cargo', 'rustc']:
            actual = Path(run(['rustup', 'which', '--toolchain', '1.95.0', tool], 60, repo).decode().strip())
            require(actual.is_file(), 'toolchain_binary_missing')
            report['tool_paths'][tool + '-actual'] = {'sha256': digest(actual.read_bytes())}
        bazel = ['bazel', '--batch', '--nosystem_rc', '--nohome_rc',
                 '--output_user_root=' + str(out / 'bazel-root'),
                 '--output_base=' + str(out / 'bazel-output'),
                 '--noexperimental_remote_repo_contents_cache']
        require(run(bazel + ['--version'], 120, repo).strip() == b'bazel 9.0.0', 'bazel_version_mismatch')
        report['current_registry_records'] = registry_recheck()
        processed = []
        for target in TARGETS:
            run(['cargo', '+1.95.0', 'update', '-p', target['name'] + '@' + target['old'],
                 '--precise', target['new']], cwd=repo / 'codex-rs')
            processed.append(target)
            no_unexpected_mutation()
            require(read_lock(repo / LOCKS[1]) == before[LOCKS[1]], 'bazel_lock_changed_during_cargo')
            delta = cargo_delta(before[LOCKS[0]], read_lock(repo / LOCKS[0]), processed)
            report['phases'].append({'target': target['name'], 'cargo_delta': delta})
        cargo_after = read_lock(repo / LOCKS[0])
        bazel_flags = ['--repository_cache=' + str(out / 'bazel-repository'),
                       '--repo_contents_cache=' + str(out / 'bazel-contents'), '--disk_cache=']
        # Exact just bazel-lock-update recipe, with only isolated storage/startup flags.
        run(bazel + ['mod', 'deps', '--lockfile_mode=update'] + bazel_flags, cwd=repo)
        no_unexpected_mutation()
        require(read_lock(repo / LOCKS[0]) == cargo_after, 'bazel_mutated_cargo_lock')
        bazel_delta(before[LOCKS[1]], read_lock(repo / LOCKS[1]))
        final_hashes = {path: digest(read_lock(repo / path)) for path in LOCKS}
        run(bazel + ['mod', 'deps', '--lockfile_mode=error'] + bazel_flags, cwd=repo)
        no_unexpected_mutation()
        require(final_hashes == {path: digest(read_lock(repo / path)) for path in LOCKS}, 'qualification_lock_drift')
        # Full all-features graph resolution, without host filtering. First pass
        # may fetch only source-gated public dependencies under existing budgets.
        # Offline replay proves those resolution inputs are locally sufficient.
        # Neither command builds/tests dependencies or compiles V8.
        for argv in metadata_commands():
            run(argv, cwd=repo / 'codex-rs')
            no_unexpected_mutation()
            require(final_hashes == {path: digest(read_lock(repo / path)) for path in LOCKS}, 'qualification_lock_drift')
        report['qualified'] = True
        report['qualification_scope'] = 'lock generation, full all-features Cargo metadata plus offline replay, exact registry facts and ten-triple Bazel resolution; no build/runtime/security-clear claim'
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        report['hold'] = error_code(error)
    finally:
        os.chdir(original_cwd)
        # Retain bounded records privately until all commands are quiescent and
        # both independent checkouts have passed their final provenance gates.
        try:
            require(not support.OWNERSHIP_UNCERTAIN, 'cleanup_unconfirmed')
            no_unexpected_mutation()
            report['source_after_confirmed'] = True
            report['control_after'] = control_gate(control, env, report.get('control_before'))
        except Exception as error:
            report['qualified'] = False
            report['final_gate_hold'] = error_code(error)
        after = {}
        for path in LOCKS:
            try:
                data = read_lock(repo / path)
                after[path] = data
                report.setdefault('source_after', {})[path] = {'sha256': digest(data), 'git_blob': blob(data)}
            except Exception:
                report.setdefault('unavailable_files', []).append(path)
        diff = b''
        if report.get('qualified'):
            try:
                require(final_hashes == {path: digest(after[path]) for path in LOCKS}, 'final_snapshot_lock_drift')
                known_lock_content(before, after)
                report['known_lock_content_confirmed'] = True
                import difflib
                diff = ''.join(''.join(difflib.unified_diff(before[path].decode().splitlines(True),
                    after[path].decode().splitlines(True), fromfile='before/'+path, tofile='after/'+path))
                    for path in LOCKS).encode()
                report['diff_sha256'] = digest(diff)
                # Exact known-input content closure replaces raw-output screening.
                # No command output participates in the emitted lock bytes or diff.
            except Exception as error:
                report['qualified'] = False
                report['final_gate_hold'] = error_code(error)
        allowed = publication_allowed(report)
        report['publication_gate_passed'] = allowed
        if allowed:
            # Raw command streams are NEVER emitted, even on full success.
            for path, data in after.items():
                (public / ('after-' + Path(path).name)).write_bytes(data)
            (public / 'locks.diff').write_bytes(diff)
        else:
            report['qualified'] = False
            report['withheld'] = 'all_raw_diff_generated_locks'
            for key in ('tool_paths', 'phases', 'current_registry_records'):
                report.pop(key, None)
        (public / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    return 0 if report['qualified'] else 1


def preflight(repo, out, control):
    repo, out, control = repo.resolve(), out.resolve(), control.resolve()
    public = out / 'public'
    public.mkdir(parents=True, exist_ok=True)
    env = {'PATH': os.environ['PATH'], 'HOME': str(out / 'home'),
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
    Path(env['HOME']).mkdir(exist_ok=True)
    result = {'source_commit': BASE, 'source_tree': BASE_TREE, 'raw_stream_policy': 'never_publish', 'qualified': False, 'publish_allowed': False,
              'phase': 'preflight_only', 'historical_cause_claim': False}
    try:
        require(shutil.disk_usage(out).free >= 20 * 1024**3, 'preflight_disk_below_20GiB')
        result['control_before'] = control_gate(control, env)
        support.identity(repo, BASE, None, env)
        require(support.git(repo, env, 'rev-parse', 'HEAD^{tree}').decode().strip() == BASE_TREE, 'source_tree_mismatch')
        for path, expected in BLOBS.items():
            require(blob(read_lock(repo / path)) == expected, 'immutable_input_blob_mismatch')
        require(support.input_gate(repo, env), 'complete_cargo_input_gate_failed')
        configuration_gate(repo)
        for path in LOCKS:
            data = read_lock(repo / path)
            (public / ('before-' + Path(path).name)).write_bytes(data)
            result.setdefault('source_before', {})[path] = {'sha256': digest(data), 'git_blob': blob(data)}
        result['control_after'] = control_gate(control, env, result['control_before'])
        result['preflight_passed'] = True
    except (ValueError, OSError, KeyError) as error:
        result['hold'] = error_code(error)
    (public / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result.get('preflight_passed') else 1


if __name__ == '__main__':
    if sys.argv[1] == '--preflight':
        raise SystemExit(preflight(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
