"""Execute the real macro's Python-compatible Starlark subset with recorded rules.

This validates target emission, not Rust compilation or Bazel analysis. External
Cargo dependency selection is represented by a small explicit fixture. The real
dependency replacement helper and the complete macro function are executed.
"""

import argparse
import ast
import hashlib
import fnmatch
import glob
import json
from pathlib import Path
import types
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repository-root', type=Path, default=Path('.'))
parser.add_argument('--before-ref', required=True)
parser.add_argument('--candidate-definitions', type=Path)
parser.add_argument('--candidate-build', type=Path)
parser.add_argument('--dependency-helper', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
REPO = args.repository_root.resolve()


def git_source(path):
    return subprocess.check_output(['git', 'show', f'{args.before_ref}:{path}'],
                                   cwd=REPO, text=True)


helper_path = args.dependency_helper or REPO / 'bazel/rules/testing/rust_test_dependencies.bzl'
HELPER = helper_path.read_text() if helper_path.is_file() else git_source('bazel/rules/testing/rust_test_dependencies.bzl')
PACKAGE = 'codex-rs/hepta-agentd'
DEFAULT = '//codex-rs/hepta-learning-ledger:hepta-learning-ledger'
QUALIFIED = '//codex-rs/hepta-learning-ledger:hepta-learning-ledger-qualification-lib'
EXTERNAL = '@crates//:fixture_external'


def label(value):
    if value.startswith('//') and ':' not in value:
        return value + ':' + value.rsplit('/', 1)[-1]
    return value


def load_functions(source, namespace, names):
    tree = ast.parse(source)
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<actual Starlark macro>', 'exec'), namespace)


def emit(definitions, build, shard=False):
    records = {}

    def record(kind):
        def call(**kwargs):
            assert kwargs['name'] not in records
            records[kwargs['name']] = dict(kind=kind, **kwargs)
        return call

    def files(patterns, exclude=(), allow_empty=True):
        selected = set()
        for pattern in patterns:
            for name in glob.glob(str(REPO / PACKAGE / pattern), recursive=True):
                path = Path(name)
                relative = path.relative_to(REPO / PACKAGE).as_posix()
                if path.is_file() and not any(fnmatch.fnmatch(relative, item) for item in exclude):
                    selected.add(relative)
        return sorted(selected)

    def cargo(normal=True, normal_dev=False, cargo_only=False, **kwargs):
        return [EXTERNAL] + ([] if cargo_only else [DEFAULT])

    data = {PACKAGE: {'binaries': {'codex-hepta-agentd': 'src/main.rs'},
                      'deps': [DEFAULT, EXTERNAL], 'dev_deps': [DEFAULT]}}
    environment = dict(DEP_DATA=data, Label=label, all_crate_deps=cargo,
                       native=types.SimpleNamespace(glob=files,
                            package_name=lambda: PACKAGE,
                            filegroup=record('filegroup')),
                       select=lambda choices: choices.get('//conditions:default', []),
                       WINDOWS_RUSTC_LINK_FLAGS=[], WINDOWS_GNULLVM_INCOMPATIBLE=[],
                       WINDOWS_GNULLVM_ONLY=[], WINE_TEST_TARGET_COMPATIBLE_WITH=[],
                       MACOS_WEBRTC_RUSTC_LINK_FLAGS=[],
                       fail=lambda message: (_ for _ in ()).throw(ValueError(message)))
    for kind in ('rust_library', 'rust_proc_macro', 'rust_binary', 'rust_test',
                 'workspace_root_test', 'cargo_build_script', 'foreign_platform_binary'):
        environment[kind] = record(kind)
    load_functions(HELPER, environment, ['rust_test_dependencies'])
    load_functions(definitions, environment, ['codex_rust_crate', '_test_shard_count'])
    tree = ast.parse(build)
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == '_UNIT_TEST_DEPENDENCIES'
                for target in statement.targets):
            exec(compile(ast.Module(body=[statement], type_ignores=[]), '<actual BUILD.bazel>', 'exec'), environment)
    call = next(statement.value for statement in tree.body
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name)
                and statement.value.func.id == 'codex_rust_crate')
    kwargs = {argument.arg: eval(compile(ast.Expression(argument.value), '<actual BUILD.bazel>', 'eval'), environment)
              for argument in call.keywords}
    if shard:
        kwargs['test_shard_counts'] = {'hepta-agentd-plasticity_process_e2e-test': 2}
    environment['codex_rust_crate'](**kwargs)
    return records


before_definitions = git_source('defs.bzl')
before_build = git_source(PACKAGE + '/BUILD.bazel')
after_definitions = (args.candidate_definitions or REPO / 'defs.bzl').read_text()
after_build = (args.candidate_build or REPO / PACKAGE / 'BUILD.bazel').read_text()
before = emit(before_definitions, before_build)
after = emit(after_definitions, after_build)
sharded = emit(after_definitions, after_build, shard=True)
native = 'hepta-agentd-plasticity_process_e2e-test'
windows = native + '-windows-cross-bin'
neighbor = 'hepta-agentd-terminal_cell_owner-test'
checks = {}
for target in (native, windows):
    assert DEFAULT in before[target]['deps'] and QUALIFIED not in before[target]['deps']
    assert QUALIFIED in after[target]['deps'] and DEFAULT not in after[target]['deps']
    assert EXTERNAL in after[target]['deps']
    checks[target] = {'before': before[target]['deps'], 'after': after[target]['deps']}
for target in (native + '-bin', windows):
    assert QUALIFIED in sharded[target]['deps'] and DEFAULT not in sharded[target]['deps']
checks['sharded_native_and_windows'] = True
for target in ('hepta-agentd', 'codex-hepta-agentd', neighbor):
    assert before[target] == after[target]
    assert DEFAULT in after[target]['deps'] and QUALIFIED not in after[target]['deps']
checks['product_library_binary_and_neighbor_unchanged'] = True
changed_targets = sorted(target for target in before if before[target] != after[target])
assert changed_targets == sorted([native, windows])
checks['only_targeted_integration_rules_changed'] = changed_targets
receipt = dict(kind='source-level-target-emission-not-Bazel-build',
               real_macro_executed=True, real_dependency_helper_executed=True,
               synthetic_external_dependencies=True,
               baseline_ref=args.before_ref,
               input_sha256={name: hashlib.sha256(value.encode()).hexdigest()
                             for name, value in [('before_defs', before_definitions),
                                                 ('after_defs', after_definitions),
                                                 ('before_build', before_build),
                                                 ('after_build', after_build),
                                                 ('existing_dependency_helper', HELPER)]},
               emitted_target_count=len(after), checks=checks,
               actual_bazel_analysis_run=False, rust_compilation_run=False)
if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
