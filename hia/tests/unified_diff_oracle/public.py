"""Compare real complete original and actual Cargo owner public APIs byte for byte."""
from file_update_oracle.dependencies import verify_workspace_sources
from collections import Counter
import json
from pathlib import Path

from .common import bind, DRIVER_SHA, snapshot
from .corpus import prepare_cases
from .original import extract_original, original_args, options


def verify(context):
    OUT, REPO, RUSTC, REPORT, common = context.output, context.repo, context.rustc, context.report, context
    DRIVER = Path(__file__).with_name("driver.rs")
    assert bind(DRIVER)["sha256"] == DRIVER_SHA
    REPORT["driver"] = bind(DRIVER)
    REPORT["entry"] = bind(Path(__file__))
    REPORT["policies"] = []
    REPORT["full_original_unit_suite_executed_by_this_gate"] = False
    before = context.before
    execute = context.run
    root, original_sources = extract_original(context)
    cases = prepare_cases(context)
    positive_report = json.loads(context.args.policy_report.read_bytes())
    assert positive_report['passed'] and positive_report['source_unchanged'] and positive_report['native_inputs_unchanged']
    assert positive_report['native_inputs'] == context.native_before
    assert context.bind(positive_report['source_before']['path']) == positive_report['source_before']
    assert json.loads(Path(positive_report['source_before']['path']).read_bytes()) == context.before
    assert positive_report['configuration'] == context.report['configuration']
    assert positive_report['negatives']['rejection_count'] == 8
    REPORT['policy_qualification'] = context.bind(context.args.policy_report)
    env = context.env
    helper, cfg = context.helper, context.helper_cfg
    all_outputs = []
    for mode in (0, 1):
        directory = OUT / f'policy-{mode}'
        directory.mkdir()
        positive = positive_report['policies'][str(mode)]
        assert positive['passed']
        for dependency in positive['actual_owner_extern_inputs'].values():
            for field in ('selected', 'link_library'):
                assert common.bind(dependency[field]['path']) == dependency[field]
        receipt_path = Path(positive['actual_owner_receipt']['path'])
        assert common.bind(receipt_path) == positive['actual_owner_receipt']
        receipt = json.loads(receipt_path.read_bytes())
        native_library = next(x for x in receipt['artifacts'] if x['path'].endswith('.rlib'))
        actual, verified = helper.select_receipt(cfg, native_library['path'], 'consumer')
        assert actual == native_library and verified['policy_mode'] == mode
        original_environment = dict(env, CARGO_MANIFEST_DIR=str(root), CARGO_PKG_NAME='codex-apply-patch',
                                    CARGO_PKG_VERSION='0.0.0')
        source_args = original_args(receipt, root, directory)
        mutation_checks = []
        for name, mutated in [
            ('missing', [x for x in receipt['argv'] if x != 'apply-patch/src/lib.rs']),
            ('duplicate', receipt['argv'] + ['apply-patch/src/lib.rs']),
            ('absolute-candidate', [str(REPO / 'codex-rs/apply-patch/src/lib.rs') if x == 'apply-patch/src/lib.rs' else x for x in receipt['argv']]),
            ('additional-source', receipt['argv'] + ['another.rs']),
        ]:
            try:
                original_args(dict(receipt, argv=mutated), root, directory)
            except AssertionError as error:
                mutation_checks.append({'name': name, 'rejected': True, 'reason': str(error)})
            else:
                raise AssertionError('source-entry mutation was accepted: ' + name)
        REPORT.setdefault('original_source_entry_admission', []).append({
            'mode': mode, 'actual_source': str(root / 'src/lib.rs'),
            'exact_source_occurrences': source_args.count(str(root / 'src/lib.rs')),
            'mutation_checks': mutation_checks})
        compiled = execute(f'original-compile-{mode}', [RUSTC, *source_args], original_environment)
        events = [json.loads(x) for x in Path(compiled['stderr']['path']).read_text().splitlines()]
        original_libraries = [x['artifact'] for x in events if x.get('$message_type') == 'artifact'
                              and x.get('emit') == 'link' and x['artifact'].endswith('.rlib')]
        assert len(original_libraries) == 1
        original_library = common.bind(Path(original_libraries[0]))
        actual_args = receipt['argv']
        dependency_paths = []
        for value in options(actual_args, '-L'):
            dependency_paths.extend(['-L', value])
        externs = dict(x.split('=', 1) for x in options(actual_args, '--extern'))
        direct = {}
        cargo_rows = [json.loads(x) for x in Path(positive['build']['stdout']['path']).read_text().splitlines()]
        for name in ('codex_exec_server', 'codex_utils_path_uri', 'tokio'):
            selected = Path(externs[name]).with_suffix('.rlib')
            assert any(row.get('reason') == 'compiler-artifact' and row['target']['name'] == name
                       and str(selected) in row['filenames'] for row in cargo_rows)
            direct[name] = common.bind(selected)
        policy = {'mode': mode, 'actual_owner_receipt': positive['actual_owner_receipt'],
                  'native_library': native_library, 'original_library': original_library,
                  'actual_owner_extern_inputs': positive['actual_owner_extern_inputs'],
                  'direct_dependency_rlibs': direct, 'public_executions': []}
        transcripts = []
        for label, library in [('original', original_library), ('native', native_library)]:
            binary = directory / label
            command = [RUSTC, '--crate-name', 'public_owner_driver', '--edition=2024', DRIVER,
                       '--check-cfg', 'cfg(hia_count)', '-C', 'debuginfo=0', '-C', 'opt-level=0',
                       '--extern', 'codex_apply_patch=' + library['path'], *dependency_paths, '-o', binary]
            for name, bound in direct.items():
                command.extend(['--extern', name + '=' + bound['path']])
            if label == 'native':
                command.extend(['--cfg', 'hia_count', '-C', 'link-arg=-Wl,--wrap=codex_hia_unified_diff'])
            execute(f'driver-compile-{mode}-{label}', command, env)
            binary_before = common.bind(binary)
            symbols = execute(f'symbols-{mode}-{label}', ['/usr/bin/nm', '-g', '--defined-only', binary], env)
            symbol_text = Path(symbols['stdout']['path']).read_text()
            assert (' T codex_hia_unified_diff\n' in symbol_text) == (label == 'native')
            count_path = directory / 'native-call-counts.tsv'
            outcome = execute(f'public-{mode}-{label}', [binary, OUT / 'fixtures', count_path], env, OUT / 'cases.bin')
            raw = Path(outcome['stdout']['path']).read_bytes()
            lines = raw.splitlines()
            assert len(lines) == len(cases) and [int(x.split(b'\t', 1)[0]) for x in lines] == list(range(len(cases)))
            assert Path(outcome['stderr']['path']).read_bytes() == b''
            counts = dict(Counter(x.split(b'\t')[1].decode() for x in lines))
            assert common.bind(binary) == binary_before
            policy['public_executions'].append({'binary': binary_before, 'binary_unchanged_across_execution': True, 'execution': outcome,
                                               'row_count': len(lines), 'statuses': counts})
            if label == 'native':
                call_rows = [tuple(map(int, x.split('\t'))) for x in count_path.read_text().splitlines()]
                assert len(call_rows) == len(cases)
                for index, ((identity, calls), row) in enumerate(zip(call_rows, lines)):
                    status = row.split(b'\t')[1]
                    assert identity == index and calls == (0 if status == b'error' else 2), (index, calls, status)
                policy['actual_hia_calls'] = sum(x[1] for x in call_rows)
                policy['native_call_counts'] = common.bind(count_path)
            transcripts.append(raw)
        assert transcripts[0] == transcripts[1], f'complete original/native transcript differs for policy {mode}'
        policy['paired_public_results'] = len(cases)
        REPORT['policies'].append(policy)
        all_outputs.append(transcripts[0].splitlines())
    REPORT['actual_cross_policy_differences'] = sum(left != right for left, right in zip(*all_outputs))
    assert REPORT['actual_cross_policy_differences'] > 0
    REPORT['paired_public_results'] = 2 * len(cases)
    REPORT['actual_hia_calls'] = sum(x['actual_hia_calls'] for x in REPORT['policies'])
    for policy in REPORT['policies']:
        rebound, verified = helper.select_receipt(cfg, policy['native_library']['path'], 'consumer')
        assert rebound == policy['native_library'] and verified['policy_mode'] == policy['mode']
        assert common.bind(Path(policy['original_library']['path'])) == policy['original_library']
        for bound in policy['direct_dependency_rlibs'].values():
            assert common.bind(Path(bound['path'])) == bound
        for dependency in policy['actual_owner_extern_inputs'].values():
            for field in ('selected', 'link_library'):
                assert common.bind(dependency[field]['path']) == dependency[field]
        for outcome in policy['public_executions']:
            assert common.bind(Path(outcome['binary']['path'])) == outcome['binary']
    assert common.bind(DRIVER) == REPORT['driver'] and common.bind(Path(__file__)) == REPORT['entry']
    REPORT['executed_driver_binaries_unchanged_at_gate_end'] = True
    REPORT['direct_dependency_rlibs_unchanged_at_gate_end'] = True
    REPORT['driver_and_runner_sources_unchanged'] = True
    REPORT['owner_artifacts_unchanged'] = True
    REPORT['original_sources_unchanged'] = all(common.bind(Path(x['path'])) == {k: x[k] for k in ('path', 'bytes', 'sha256')} for x in original_sources)
    REPORT['source_unchanged'] = snapshot(REPO) == before
    assert REPORT['source_unchanged'] and REPORT['original_sources_unchanged']
    verify_workspace_sources(context.dependency_source_admission)
    REPORT['dependency_source_inputs_unchanged'] = True
