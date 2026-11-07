#!/usr/bin/env python3
"""Build an inert exporter from fixed source text; never imports a runner."""
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path

D = Path(__file__).resolve().parent
B = D.parent


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def write(name, raw):
    path = D / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {'path': name, **pin(raw)}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def functions(text):
    return {node.name: ast.get_source_segment(text, node) for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}


def replace_one(text, before, after):
    assert text.count(before) == 1, before[:150]
    return text.replace(before, after, 1)


def main():
    old_path = B / 'r30-export-preparation/export-r30-closed-template.py'
    producer_path = B / 'source53-r31-binding/native-run-r31.py'
    contract_path = B / 'native-validation-results/r31-export-contract/CONTRACT.json'
    old_raw, producer_raw, contract_raw = old_path.read_bytes(), producer_path.read_bytes(), contract_path.read_bytes()
    assert pin(old_raw)['sha256'] == '45e64afcdffd597de793c12158f90f605bb2274667b2774ad39d431a4af3700a'
    assert pin(producer_raw)['sha256'] == '2dc7b84b7dad0d6e150817e0dfc4105c4bb4d343103aacef0fb932eab698a6f9'
    assert pin(contract_raw)['sha256'] == 'dd00d0ce0f33554b9ce07ba527ca5f7707dd96ad7396c4f3e559d718e0efd3ec'
    write('references/export-r30-closed-template.py', old_raw)
    write('references/native-run-r31.py', producer_raw)
    write('references/R31-PRODUCER-CONTRACT.json', contract_raw)
    old, producer = old_raw.decode(), producer_raw.decode()
    old_funcs, prod_funcs = functions(old), functions(producer)
    contract = json.loads(contract_raw)
    header = old[:old.index('def require(')]
    header = replace_one(header, 'Inert R30 closed app-server evidence exporter', 'Inert R31 closed default-workspace evidence exporter')
    header = replace_one(header, 'The archive preserves actual originals, including unsuccessful or incomplete\nphases, and never fabricates the 19-file successful closure.',
                         'The archive preserves actual originals, including unsuccessful or incomplete\nexecution, and never fabricates the 18-file successful closure.')
    for before, after in (
        ("PREFIX = 'native-source53-project-r30'", "PREFIX = 'native-workspace-r31'"),
        ("JOB_ID = '1a1b25b399f-fc05-7daa'", "JOB_ID = '1a1b275ba33-fc05-7e17'"),
        ("JOB_KEY = 'cell-source53-project-r30-20261106-v1'", "JOB_KEY = 'cell-source53-workspace-r31-20261106-v1'"),
        ("RUNNER_NAME = 'native-run-r30.py'", "RUNNER_NAME = 'native-run-r31.py'"),
        ("RUNNER_PIN = {'bytes': 61214, 'sha256': 'b72407252efdaf81d8e3bc5280c3fa7ad9afb36fa398869e8023daaa392ff3c8', 'git_blob': '3c41e24997e2113f0028a58b70f8e646b76ac47e'}", 'RUNNER_PIN = ' + repr(pin(producer_raw))),
        ("CONTROLLER_PREFIX = 'r30-controller-closed-'", "CONTROLLER_PREFIX = 'r31-controller-closed-'"),
        ("OUT = E / 'checkpoint-r30-closed.tar.gz'", "OUT = E / 'checkpoint-r31-closed.tar.gz'"),
        ("DERIVED = E / 'r30-closed-export'", "DERIVED = E / 'r31-closed-export'"),
        ("RESULT = E / 'checkpoint-r30-export.json'", "RESULT = E / 'checkpoint-r31-export.json'"),
    ):
        header = replace_one(header, before, after)
    old_success_line = next(line for line in header.splitlines() if line.startswith('SUCCESS_SUFFIXES = '))
    suffixes = [name[len('native-workspace-r31'):] for name in contract['successful_originals']]
    header = replace_one(header, old_success_line, 'SUCCESS_SUFFIXES = set(' + repr(suffixes) + ')')
    constants = {}
    for node in ast.parse(producer).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    extra = {
        'EXPECTED_COMMIT': contract['source_commit'], 'EXPECTED_TREE': contract['source_tree'],
        'SOURCE52_COMMIT': constants['SOURCE52_COMMIT'], 'SOURCE52_TREE': constants['SOURCE52_TREE'],
        'SOURCE52_CHANGED_COUNT': constants['SOURCE52_CHANGED_COUNT'], 'FRAMEWORK_PARENT': constants['FRAMEWORK_PARENT'],
        'CARGO_LOCK_SHA256': constants['CARGO_LOCK_SHA256'], 'BAZEL_LOCK_SHA256': constants['BAZEL_LOCK_SHA256'],
        'R30_PREFIX': constants['R30_PREFIX'], 'R30_JOB_ID': constants['R30_JOB_ID'],
        'R28_PREFIX': constants['R28_PREFIX'], 'R28_JOB_ID': constants['R28_JOB_ID'],
        'HISTORICAL_FOUR_PACKAGES': constants['HISTORICAL_FOUR_PACKAGES'],
        'PYTHON_TEST_COUNT': constants['PYTHON_TEST_COUNT'],
        'R29_WORKSPACE_BASELINE_INPUT_PINS': constants['R29_WORKSPACE_BASELINE_INPUT_PINS'],
        'METADATA_COMMAND': contract['metadata_command'], 'COMMAND': contract['workspace_command'],
    }
    header += '\n'.join(name + ' = ' + repr(value) for name, value in extra.items()) + '\n\n'

    shared = ['require', 'sha', 'data_pin', 'safe_relative', 'check_pin', 'stable_read', 'git',
              'natural_terminal', 'source_guard', 'recorded_guard', 'clean_lines', 'check_bindings', 'write_new']
    parsers = ['review_tests', 'review_python', 'verify_inherited_guard', 'review_inherited_tests',
               'review_original_workspace', 'review_workspace']
    assert old_funcs['clean_lines'] == prod_funcs['clean_lines']
    assert old_funcs['review_tests'] == prod_funcs['review_tests']
    custom = (D / 'workspace_readback_functions.py').read_text()
    custom_funcs = functions(custom)

    export = old_funcs['export_closed']
    export = replace_one(export, '# These three inputs were already closed at strict-start;',
                         '# These inputs were already closed at the actual metadata/workspace start;')
    export = replace_one(export,
        "require(pre['patch_application_performed_by_this_runner'] is False and pre['lock_update_performed_by_this_runner'] is False and pre['python_suite_reexecuted'] is False, 'original gate action scope differs')",
        "require(pre['patch_application_performed'] is False and pre['lock_update_performed'] is False and pre['python_suite_reexecuted'] is False and pre['fix_fmt_executed'] is False and pre['workspace_test_command'] == COMMAND and pre['historical_project_pass_substitutes_for_r30'] is False, 'original workspace action scope differs')\n    require(env['source_manifest'] == SOURCE_NAME and env['source_manifest_sha256'] == SOURCE_PIN['sha256'] and env['original_default_workspace_selection'] is True and env['fresh_current_source_metadata_required'] is True and env['outer_timeout_seconds_contract'] == 9600 and env['test_deadlines_features_filters_retries_unchanged'] is True and env['sandbox_or_network_protection_environment_overridden'] is False, 'original workspace environment differs')\n    for key, value in {'RUSTUP_TOOLCHAIN': '1.96.0', 'CARGO_BUILD_JOBS': '2', 'NEXTEST_TEST_THREADS': '2', 'CARGO_TARGET_DIR': str(T / 'target'), 'CARGO_PROFILE_TEST_DEBUG': '0', 'CARGO_PROFILE_DEV_DEBUG': '0', 'NEXTEST_PROFILE': None, 'HEPTA_NEXTTEST_FULL_METADATA': None, 'CARGO_INCREMENTAL': None, 'CARGO_BUILD_TARGET': None, 'RUSTFLAGS': None, 'PYTHONOPTIMIZE': None}.items():\n        require(env['selection'][key] == value, 'original selection environment differs: ' + key)")
    start = export.index("    baseline_raw = pinned_input(pre['baseline']")
    end = export.index("    source50 = json.loads", start)
    export = export[:start] + """    baseline, baseline_readback = preserve_r29_baseline(pre, pinned_input)
    baseline_proof = pre['original_r29_workspace_baseline']
    prerequisites = {kind: preserve_prior_project(pre, env, pinned_input, kind) for kind in ('r30', 'r28')}
""" + export[end:]
    export = replace_one(export, "readback = review_closed_originals(closed, terminal, baseline)",
                         "readback = review_closed_workspace(closed, terminal, baseline, baseline_proof, prerequisites)")
    export = replace_one(export,
        "end = rows[i + 1]['byte_offset'] if i + 1 < len(rows) else review['summary']['byte_offset']",
        "end = rows[i + 1]['byte_offset'] if i + 1 < len(rows) else (review['summary']['byte_offset'] if review['summary'] is not None else len(log))\n            require(row['byte_offset'] <= end <= len(log), 'failure block range differs')")
    export = replace_one(export,
        "if len(footer) != len(ids) or {(r['binary'], r['name'], r['status']) for r in footer} != ids:",
        "if review['complete_execution_accounting'] and (len(footer) != len(ids) or {(r['binary'], r['name'], r['status']) for r in footer} != ids):")
    export = replace_one(export,
        "'counts': None if review is None else review['counts'], 'reported_skipped': None if review is None else review['reported_skipped'],\n              'readback_errors': readback['readback_errors'], 'workspace_qualification': 'NOT_ESTABLISHED_BY_THIS_PROJECT_EXPORT'",
        "'original_workspace_exit': readback['original_workspace_exit'], 'effective_workspace_exit': readback['effective_workspace_exit'],\n              'counts': None if review is None else review['terminal_counts'], 'reported_skipped': None if review is None else review['reported_skipped'],\n              'complete_execution_accounting': None if review is None else review['complete_execution_accounting'],\n              'nextest_started': None if review is None else review['nextest_started'],\n              'readback_errors': readback['readback_errors'], 'all_platforms_features_external_services_qualified': False,\n              'fresh_metadata_rerun_by_exporter': False, 'fix_fmt_executed_by_exporter': False,\n              'archive_export_success_is_not_a_gate_pass': True")
    export = replace_one(export,
        "'source_modified_by_exporter': False, 'rust_or_formatter_executed': False}",
        "'source_modified_by_exporter': False, 'rust_or_formatter_executed': False, 'metadata_executed': False, 'current_R30_project_prerequisite': prerequisites['r30'], 'historical_source52_R28_project_prerequisite': prerequisites['r28'], 'original_failed_R29_baseline': baseline_readback, 'fresh_metadata': readback['metadata']}")
    export = replace_one(export,
        "'original_test_review': review, 'phase_results': readback['phases']",
        "'original_workspace_review': review, 'metadata_raw_exit': readback['metadata_raw_exit'], 'metadata_receipt_exit': readback['metadata_receipt_exit']")
    export = replace_one(export, "'nextest_complete_summary_present': review is not None",
                         "'nextest_complete_summary_present': bool(review is not None and review['complete_execution_accounting'])")
    export = export.replace("'hepta.r30-", "'hepta.r31-")
    export = replace_one(export, "'schema': 'hepta.source53-project-closed-index.v1'", "'schema': 'hepta.source53-workspace-closed-index.v1'")
    export = replace_one(export, "'classification': 'DIAGNOSTIC_ONLY_ORIGINAL_APP_SERVER_GATE'", "'classification': 'DIAGNOSTIC_ONLY_ORIGINAL_DEFAULT_WORKSPACE_GATE'")
    text = header + '\n\n\n'.join([old_funcs[name] for name in shared]
        + [prod_funcs[name] for name in parsers]
        + list(custom_funcs.values()) + [export, old_funcs['main']]) + "\n\n\nif __name__ == '__main__':\n    main()\n"
    parsed = ast.parse(text)
    result = write('export-r31-closed-template.py', text.encode())
    write('r30-to-r31-template.patch', ''.join(difflib.unified_diff(old.splitlines(True), text.splitlines(True),
        fromfile='export-r30-closed-template.py', tofile='export-r31-closed-template.py')).encode())
    new_funcs = functions(text)
    readback = {
        'schema': 'hepta.r31-export-template-mechanical-readback.v1',
        'template': result, 'FROZEN': False, 'unknown_closure_maps': ['TERMINAL_PIN', 'CLOSED_ORIGINAL_PINS', 'CONTROLLER_ORIGINAL_PINS'],
        'AST_parsed': True, 'runner_imported_or_executed': False,
        'exact_R30_exporter_helpers': [{'name': name, 'sha256': hashlib.sha256(old_funcs[name].encode()).hexdigest(),
            'byte_equal': old_funcs[name] == new_funcs[name]} for name in shared],
        'exact_actual_R31_parsers_and_guard': [{'name': name, 'sha256': hashlib.sha256(prod_funcs[name].encode()).hexdigest(),
            'byte_equal': prod_funcs[name] == new_funcs[name]} for name in parsers],
        'source_count': 197, 'metadata_members': 193, 'baseline_count_only_after_execution': 20228,
        'expected_successful_original_count': len(suffixes), 'expected_successful_originals': contract['successful_originals'],
        'producer': {'path': str(producer_path.relative_to(B)), **pin(producer_raw)},
        'old_exporter': {'path': str(old_path.relative_to(B)), **pin(old_raw)},
        'producer_contract': {'path': str(contract_path.relative_to(B)), **pin(contract_raw)},
    }
    assert all(row['byte_equal'] for row in readback['exact_R30_exporter_helpers'] + readback['exact_actual_R31_parsers_and_guard'])
    values = {}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ('FROZEN', 'TERMINAL_PIN', 'CLOSED_ORIGINAL_PINS', 'CONTROLLER_ORIGINAL_PINS'):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    assert values == {'FROZEN': False, 'TERMINAL_PIN': None, 'CLOSED_ORIGINAL_PINS': None, 'CONTROLLER_ORIGINAL_PINS': None}
    write('MECHANICAL-READBACK.json', encode(readback))
    print(json.dumps({'template': result, 'exact_helpers': len(shared), 'exact_producer_functions': len(parsers), 'inert': values}))


if __name__ == '__main__':
    main()
