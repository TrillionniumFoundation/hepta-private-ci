"""Run real macro/helper functions against explicit dependency and platform fixtures.

This source-level regression executes the repository's Python-compatible
Starlark functions. It does not claim Bazel analysis or native Rust compilation.
"""
import argparse
import ast
import fnmatch
import hashlib
import json
from pathlib import Path
import tomllib
import types


def functions(source, environment, names):
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<real Starlark functions>', 'exec'), environment)


def label(value):
    if value.startswith('//') and ':' not in value:
        return value + ':' + value.rsplit('/', 1)[-1]
    return value


def emit(definitions, helper, test_helper, package, platform, shard=False, build=None):
    yaml = '@crates//:serde_norway-0.9.42'
    normal = '//fixture/normal:normal'
    qualified = '//fixture/normal:qualified'
    dev = '//fixture/dev:dev'
    build_dep = '//fixture/build:build'
    windows = '//fixture/windows:windows'
    linux_dev = '//fixture/linux-dev:linux-dev'
    names = {yaml: 'serde_yaml', normal: 'renamed_normal', dev: 'renamed_dev',
             build_dep: 'renamed_build', windows: 'renamed_windows', linux_dev: 'renamed_linux_dev'}
    data = {'aliases': names, 'binaries': {'fixture-bin': 'src/main.rs'},
            'deps': [yaml, normal], 'dev_deps': [dev, normal], 'build_deps': [build_dep],
            'deps_by_platform': {'//fixture:windows': [windows]},
            'dev_deps_by_platform': {'//fixture:linux': [linux_dev]}}
    records = {}
    choices = lambda values: values.get(platform, values.get('//conditions:default'))

    def cargo(normal=False, normal_dev=False, build=False, cargo_only=False):
        kinds = (['dev_deps'] if normal_dev else []) + (['build_deps'] if build else [])
        if normal or not kinds:
            kinds.append('deps')
        selected = []
        for kind in kinds:
            selected += data.get(kind, []) + data.get(kind + '_by_platform', {}).get(platform, [])
        return list(dict.fromkeys(d for d in selected if not cargo_only or d.startswith('@crates//:')))

    def record(kind):
        def call(**kwargs):
            assert kwargs['name'] not in records
            records[kwargs['name']] = dict(kind=kind, **kwargs)
        return call

    all_files = ['build.rs', 'src/lib.rs', 'src/main.rs', 'tests/selected.rs', 'tests/neighbor.rs']

    def files(include, exclude=(), allow_empty=True):
        def matches(name, pattern):
            return fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name, pattern.replace('**/', ''))
        return [name for name in all_files
                if any(matches(name, pattern) for pattern in include)
                and not any(matches(name, pattern) for pattern in exclude)]

    environment = dict(DEP_DATA={package: data}, Label=label, aliases=lambda: names,
                       all_crate_deps=cargo, select=choices, glob=files,
                       native=types.SimpleNamespace(glob=files, package_name=lambda: package,
                                                    filegroup=record('filegroup')),
                       WINDOWS_RUSTC_LINK_FLAGS=[], WINDOWS_GNULLVM_INCOMPATIBLE=[],
                       WINDOWS_GNULLVM_ONLY=[], WINE_TEST_TARGET_COMPATIBLE_WITH=[],
                       MACOS_WEBRTC_RUSTC_LINK_FLAGS=[],
                       fail=lambda message: (_ for _ in ()).throw(ValueError(message)))
    for kind in ('rust_library', 'rust_proc_macro', 'rust_binary', 'rust_test',
                 'workspace_root_test', 'cargo_build_script', 'foreign_platform_binary'):
        environment[kind] = record(kind)
    functions(test_helper, environment, ['rust_test_dependencies'])
    functions(helper, environment, ['_aliases_for_dependencies', 'rust_crate_aliases'])
    functions(definitions, environment, ['codex_rust_crate', '_test_shard_count'])
    if build:
        tree = ast.parse(build)
        call = next(node.value for node in tree.body if isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == 'codex_rust_crate')
        kwargs = {arg.arg: eval(compile(ast.Expression(arg.value), '<real BUILD>', 'eval'), environment)
                  for arg in call.keywords}
    else:
        kwargs = dict(name='fixture', crate_name='fixture',
                      unit_test_dependency_replacements={normal: qualified},
                      integration_test_dependency_replacements={'selected': {normal: qualified}})
        if shard:
            kwargs['test_shard_counts'] = {'fixture-selected-test': 2}
    environment['codex_rust_crate'](**kwargs)
    return records, environment, dict(yaml=yaml, normal=normal, qualified=qualified, dev=dev,
                                     build_dep=build_dep, windows=windows, linux_dev=linux_dev)


def run(before, candidate, output):
    before_defs = (before / 'defs.bzl').read_text()
    after_defs = (candidate / 'defs.bzl').read_text()
    helper = (candidate / 'bazel/rules/rust_crate_aliases.bzl').read_text()
    test_helper = (before / 'bazel/rules/testing/rust_test_dependencies.bzl').read_text()
    checks = []
    for platform in ('//conditions:default', '//fixture:linux', '//fixture:windows'):
        for shard in (False, True):
            args = (helper, test_helper, 'codex-rs/alias-fixture', platform, shard)
            old, _, _ = emit(before_defs, *args)
            new, env, dep = emit(after_defs, *args)
            assert old.keys() == new.keys()
            for target, record in new.items():
                without_alias = {key: value for key, value in record.items() if key != 'aliases'}
                assert without_alias == old[target], (platform, shard, target, 'unrelated target attribute changed')
                if 'aliases' in record:
                    selected = {label(value) for value in record['deps']}
                    assert set(record['aliases']) <= selected, (target, 'alias adds a dependency edge')
            for target in ('fixture', 'fixture-bin'):
                assert new[target]['aliases'][dep['yaml']] == 'serde_yaml'
                assert new[target]['aliases'][dep['normal']] == 'renamed_normal'
                assert dep['qualified'] not in new[target]['aliases']
                assert dep['dev'] not in new[target]['aliases']
            for target in ('fixture-test-lib', 'fixture-unit-tests-bin'):
                assert new[target]['aliases'][dep['qualified']] == 'renamed_normal'
                assert dep['normal'] not in new[target]['aliases']
            assert env['rust_crate_aliases'](replacements={dep['yaml']: '//fixture/invalid:external'}) == env['rust_crate_aliases']()
            assert new['fixture-build-script']['aliases'] == {dep['build_dep']: 'renamed_build'}
            assert dep['yaml'] not in new['fixture-bin-bin-unit-tests-bin']['aliases']
            assert new['fixture-bin-bin-unit-tests-bin']['aliases'][dep['dev']] == 'renamed_dev'
            selected = 'fixture-selected-test' + ('-bin' if shard else '')
            for target in (selected, 'fixture-selected-test-windows-cross-bin'):
                assert new[target]['aliases'][dep['qualified']] == 'renamed_normal'
                assert new[target]['aliases'][dep['yaml']] == 'serde_yaml'
                assert dep['normal'] not in new[target]['aliases']
            assert new['fixture-neighbor-test']['aliases'][dep['normal']] == 'renamed_normal'
            assert dep['qualified'] not in new['fixture-neighbor-test']['aliases']
            assert (dep['windows'] in new['fixture']['aliases']) == (platform == '//fixture:windows')
            assert (dep['linux_dev'] in new['fixture-unit-tests-bin']['aliases']) == (platform == '//fixture:linux')
            try:
                env['_aliases_for_dependencies']([dep['normal'], dep['dev']],
                                                  {dep['normal']: 'one', dep['dev']: 'two'},
                                                  {dep['normal']: dep['dev']})
                raise AssertionError('Conflicting replacement aliases accepted')
            except ValueError:
                pass
            checks.append({'platform': platform, 'sharded': shard, 'emitted_targets': len(new),
                           'unchanged_non_alias_attributes': True, 'aliases_subset_selected_deps': True,
                           'test_replacement_aliases_follow_selected_identity': True,
                           'external_replacement_ignored_like_dependency_helper': True})
    paths = ['codex-rs/skills', 'codex-rs/core-plugins', 'codex-rs/ext/skills',
             'codex-rs/external-agent-migration']
    lock = tomllib.loads((before / 'codex-rs/Cargo.lock').read_text())
    consumers = sorted(package['name'] for package in lock['package']
                       if any(dep.split()[0] == 'serde_norway' for dep in package.get('dependencies', [])))
    observed = []
    for package in paths:
        manifest = tomllib.loads((before / package / 'Cargo.toml').read_text())
        assert manifest['dependencies']['serde_yaml']['workspace'] is True
        observed.append(manifest['package']['name'])
        build = (before / package / 'BUILD.bazel').read_text()
        records, _, dep = emit(after_defs, helper, test_helper, package, '//conditions:default', build=build)
        libraries = [row for row in records.values() if row['kind'] == 'rust_library']
        assert libraries and all(row['aliases'].get(dep['yaml']) == 'serde_yaml' for row in libraries)
    assert sorted(observed) == consumers
    receipt = {'scope': 'Real macro/helper target emission with explicit synthetic external dependency/platform fixtures; not Bazel analysis or Rust compilation.',
               'real_macro_executed': True, 'real_alias_helper_executed': True,
               'real_test_dependency_helper_executed': True,
               'checks': checks, 'cargo_lock_complete_yaml_consumers': consumers,
               'four_actual_consumer_build_invocations_checked': True,
               'all_non_alias_target_attributes_unchanged': True,
               'source_sha256': {name: hashlib.sha256(value.encode()).hexdigest()
                                 for name, value in [('before_defs', before_defs), ('after_defs', after_defs),
                                                     ('alias_helper', helper), ('test_dependency_helper', test_helper)]},
               'native_remote_compilation_gate': 'Still required on the followup head'}
    output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-root', type=Path, required=True)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.before_root, args.candidate_root, args.output)
