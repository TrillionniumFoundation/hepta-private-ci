"""Read-only static checks for the isolated qualification-clock candidate."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
ORIGINAL = ROOT / 'original'
BASE = ROOT.parent / 'mem8-repair-source-v2/root-readback/records'
SCANNER = ROOT.parent / 'mem-integrated-ci-watch-2ae/build-test-failure/original-source/scripts/verify_hepta_callers.py'


def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build_calls(text, function):
    return [node.value for node in ast.parse(text).body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name) and node.value.func.id == function]


def keywords(call):
    return {item.arg: item.value for item in call.keywords}


def literal_assignment(text, name):
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def function_body(text, name):
    start = text.index('fn ' + name + '(')
    opening = text.index('{', start)
    depth = 1
    for index in range(opening + 1, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if depth == 0:
            return text[start:index + 1]
    raise AssertionError(name)


def main():
    manifest = json.loads((ROOT / 'CANDIDATE_MANIFEST.json').read_text())
    assert manifest['base_tree'] == 'e253b99e0a5c3b3a680569da0d224fabff0781ba'
    base_tree = {}
    for row in (BASE / 'BASE_TREE.ls-tree').read_bytes().split(b'\0'):
        if row:
            metadata, path = row.split(b'\t', 1)
            base_tree[path.decode()] = metadata.decode().split()[2]
    formatted = json.loads((BASE / 'FORMATTED_CAPSULE.json').read_text())
    for row in formatted['files']:
        base_tree[row['path']] = row['postimage_git_blob']
    for row in manifest['files']:
        raw = (SOURCE / row['path']).read_bytes()
        assert (len(raw), sha(raw), blob(raw)) == (row['bytes'], row['sha256'], row['postimage_git_blob'])
        assert base_tree.get(row['path']) == row['preimage_git_blob'], row['path']
        if row['preimage_git_blob'] is not None:
            assert blob((ORIGINAL / row['path']).read_bytes()) == row['preimage_git_blob']
    helper_path = 'bazel/rules/testing/qualification_lease_clock.bzl'
    helper = (SOURCE / helper_path).read_text()
    replacements = literal_assignment(helper, 'LEASE_CLOCK_TEST_DEPENDENCIES')
    graph = json.loads((ROOT / 'EXACT_ROOT_DEV_CARGO_DAG.json').read_text())['normal_transitive_clock_library_closure']
    package_paths = {name: Path(row['path']).parent.as_posix() for name, row in graph.items()}
    assert set(replacements) == {'//' + path for path in package_paths.values()}
    edges = []
    for name, row in graph.items():
        package = package_paths[name]
        assert package + '/build.rs' not in base_tree
        assert package + '/src/lib.rs' in base_tree
        build_path = package + '/BUILD.bazel'
        before = (ORIGINAL / build_path).read_text()
        after = (SOURCE / build_path).read_text()
        old_normal = build_calls(before, 'codex_rust_crate')
        new_normal = build_calls(after, 'codex_rust_crate')
        assert len(old_normal) == len(new_normal) == 1
        if name == 'codex-hepta-memory-extension':
            new_normal[0].keywords = [x for x in new_normal[0].keywords if x.arg != 'unit_test_dependency_replacements']
        assert ast.dump(old_normal[0]) == ast.dump(new_normal[0]), build_path
        variant = build_calls(after, 'qualification_lease_clock_library')
        assert len(variant) == 1
        attrs = keywords(variant[0])
        target = ast.literal_eval(attrs['name']) + '-qualification-clock-lib'
        assert replacements['//' + package] == '//' + package + ':' + target
        if name in ['codex-hepta-memory', 'codex-hepta-agentd']:
            assert ast.dump(attrs['compile_data']) == ast.dump(keywords(old_normal[0])['compile_data'])
        for dep in row['affected_direct_normal_deps']:
            assert '//' + package_paths[dep] in replacements
            edges.append({'from': name, 'to': dep, 'replacement': replacements['//' + package_paths[dep]]})
    assert 'testonly = True' in helper
    assert 'base_replacements | LEASE_CLOCK_TEST_DEPENDENCIES' in helper
    agent_build = (SOURCE / 'codex-rs/hepta-agentd/BUILD.bazel').read_text()
    old_agent_build = (ORIGINAL / 'codex-rs/hepta-agentd/BUILD.bazel').read_text()
    assert literal_assignment(agent_build, '_UNIT_TEST_DEPENDENCIES') == literal_assignment(old_agent_build, '_UNIT_TEST_DEPENDENCIES')
    assert '_QUALIFICATION_CLOCK_DEPENDENCIES = _UNIT_TEST_DEPENDENCIES | LEASE_CLOCK_TEST_DEPENDENCIES' in agent_build
    for function in ['rust_library', 'rust_test', 'rust_binary', 'workspace_root_test']:
        old = build_calls(old_agent_build, function)
        new = build_calls(agent_build, function)
        assert len(old) == len(new)
        for a, b in zip(old, new):
            a.keywords = [x for x in a.keywords if x.arg != 'deps']
            b.keywords = [x for x in b.keywords if x.arg != 'deps']
            assert ast.dump(a) == ast.dump(b), function
    for package in ['codex-rs/hepta-agentd', 'codex-rs/ext/hepta-memory']:
        before = tomllib.loads((ORIGINAL / package / 'Cargo.toml').read_text())
        after = tomllib.loads((SOURCE / package / 'Cargo.toml').read_text())
        assert after['dev-dependencies']['codex-hepta-memory']['features'] == ['qualification-lease-clock']
        assert before.get('features', {}) == after.get('features', {})
        del after['dev-dependencies']['codex-hepta-memory']
        assert before == after
    memory_before = tomllib.loads((ORIGINAL / 'codex-rs/hepta-memory/Cargo.toml').read_text())
    memory_after = tomllib.loads((SOURCE / 'codex-rs/hepta-memory/Cargo.toml').read_text())
    assert memory_after.pop('features') == {'qualification-lease-clock': []}
    assert memory_before == memory_after
    clock = (SOURCE / 'codex-rs/hepta-memory/src/cognitive_lease_clock.rs').read_text()
    assert '#[default]\n    Real,' in clock
    assert 'now: Weak<AtomicU64>' in clock
    assert 'target >= current' in clock
    assert clock.count('store.local_lease_clock =') == 1
    time_checks = {'local_lease_outbox.rs': 3, 'logical_turn_registry.rs': 4, 'h7_trajectory_store.rs': 3}
    for filename, count in time_checks.items():
        path = 'codex-rs/hepta-memory/src/' + filename
        before = (ORIGINAL / path).read_text(); after = (SOURCE / path).read_text()
        assert after.count('.local_lease_now_unix_seconds()') + after.count('.local_lease_now_unix_i64()') == count
        assert function_body(before, 'now_unix_seconds') == function_body(after, 'now_unix_seconds')
        old_audit = re.findall(r'\.bind\(now_unix_(?:seconds|i64)\(\)\?\)', before)
        assert old_audit == re.findall(r'\.bind\(now_unix_(?:seconds|i64)\(\)\?\)', after)
    constructors = (SOURCE / 'codex-rs/hepta-memory/src/cognitive_store.rs').read_text()
    recovery = (SOURCE / 'codex-rs/hepta-memory/src/cognitive_store_recovery.rs').read_text()
    assert constructors.count('local_lease_clock: lease_clock::LocalLeaseClock::default()') == 2
    assert recovery.count('local_lease_clock: super::lease_clock::LocalLeaseClock::default()') == 1
    spec = importlib.util.spec_from_file_location('clock_caller_delta', SCANNER)
    module = importlib.util.module_from_spec(spec);sys.modules[spec.name] = module;spec.loader.exec_module(module)
    data = module._load_manifest(SOURCE / 'CALLERS.toml'); boundaries = module._boundary_rows(data)
    ignored = tuple(data['ignored_path_fragments'])
    paths = [x['path'] for x in manifest['files'] if x['path'].endswith('.rs')]
    indices = []
    for directory in [ORIGINAL, SOURCE]:
        indices.append({p: module._strip_cfg_test_items(module._strip_rust_non_code((directory / p).read_text() if (directory / p).exists() else '')) for p in paths})
    for boundary in boundaries:
        matches = []; fields = []
        for index in indices:
            current_fields = module.authority_fields(index, boundary.receiver_type) if boundary.receiver_type else {}
            fields.append(current_fields); found = []
            pattern = re.compile(boundary.call_pattern or re.escape(boundary.symbol) + r'\s*\(')
            for p, code in index.items():
                if p == boundary.definition_path or module._is_ignored(p, ignored):continue
                seen = any(module.has_authority_call(code, boundary.receiver_type, method, current_fields) for method in (boundary.receiver_methods or (boundary.symbol.rsplit('::',1)[-1],))) if boundary.receiver_type else bool(pattern.search(code))
                if seen:found.append(p)
            matches.append(sorted(found))
        assert matches[0] == matches[1] and fields[0] == fields[1], boundary.identifier
        definition = SOURCE / boundary.definition_path
        if definition.is_file():assert all(marker in definition.read_text() for marker in boundary.definition_markers)
    assert not [row for row in data['protected_file'] if row['path'] in paths]
    assert (SOURCE / 'CALLERS.toml').read_bytes() == (ORIGINAL / 'CALLERS.toml').read_bytes()
    return {'schema':'mem8.qualification-clock.static-review.v1','status':'PASS_STATIC_REVIEW_ONLY','base_tree':manifest['base_tree'],'files':len(manifest['files']),'added':manifest['added'],'deleted':manifest['deleted'],'source_preimages_exact':True,'bazel_package_variants':len(replacements),'type_edges':edges,'ordinary_bazel_macro_calls_unchanged_except_extension_unit_dependency':True,'ordinary_agentd_test_graph_unchanged':True,'existing_qualification_target_features_and_commands_unchanged':True,'cargo_normal_dependencies_and_defaults_unchanged':True,'expiry_check_counts':time_checks,'audit_wall_clock_helpers_and_timestamp_inserts_unchanged':True,'ordinary_recovery_read_only_clock_defaults':'Real','caller_boundaries_checked_for_delta':len(boundaries),'caller_deltas':[],'caller_manifest_unchanged':True,'native_executed':False,'full_repo_caller_gate_executed':False,'formatter_executed':False,'bazel_lock_regenerated':False,'limitations':['Static closure and source checks do not prove Rust compilation or Bazel target analysis.','Existing full caller/source gate must run on the eventual combined source.','Original expiry failures remain recorded; no native result is replaced.']}


if __name__ == '__main__':
    print(json.dumps(main(), indent=2, sort_keys=True))
