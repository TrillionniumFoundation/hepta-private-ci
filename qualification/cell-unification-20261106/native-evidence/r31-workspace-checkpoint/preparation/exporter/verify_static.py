#!/usr/bin/env python3
"""Only parse source/closed historical records; never import or execute a runner."""
import ast
import builtins
import difflib
import hashlib
import json
import os
import symtable
from pathlib import Path

D = Path(__file__).resolve().parent
B = D.parent


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def source_functions(text):
    return {node.name: ast.get_source_segment(text, node) for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}


def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with (D / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return pin(raw)


def main():
    path = D / 'export-r31-closed-template.py'
    raw = path.read_bytes(); text = raw.decode(); parsed = ast.parse(text)
    assert pin(raw)['sha256'] == '0a0b60ec209527b03cf54a7d7566409c9714aca13c4423fc8ef9dd0cc88be910'
    funcs = source_functions(text)
    original = source_functions((D / 'references/export-r30-closed-template.py').read_text())
    producer = source_functions((D / 'references/native-run-r31.py').read_text())
    mechanical = json.loads((D / 'MECHANICAL-READBACK.json').read_bytes())
    for row in mechanical['exact_R30_exporter_helpers']:
        assert funcs[row['name']] == original[row['name']]
    for row in mechanical['exact_actual_R31_parsers_and_guard']:
        assert funcs[row['name']] == producer[row['name']]
    assert funcs['main'] == original['main']
    constants = {}
    defined = set()
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.Import):
            defined |= {alias.asname or alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            defined |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.Assign):
            defined |= {n.id for target in node.targets for n in ast.walk(target) if isinstance(n, ast.Name)}
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    constants[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    if node.targets[0].id == 'SUCCESS_SUFFIXES':
                        assert isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'set'
                        constants['SUCCESS_SUFFIXES'] = set(ast.literal_eval(node.value.args[0]))
    assert {name: constants[name] for name in ('FROZEN', 'TERMINAL_PIN', 'CLOSED_ORIGINAL_PINS', 'CONTROLLER_ORIGINAL_PINS')} == {
        'FROZEN': False, 'TERMINAL_PIN': None, 'CLOSED_ORIGINAL_PINS': None, 'CONTROLLER_ORIGINAL_PINS': None}
    missing = []
    def walk(table):
        for symbol in table.get_symbols():
            if symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in defined | set(dir(builtins)):
                missing.append((table.get_name(), symbol.get_name()))
        for child in table.get_children():
            walk(child)
    walk(symtable.symtable(text, str(path), 'exec'))
    assert missing == []
    subprocess_calls = [n for n in ast.walk(parsed) if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'subprocess']
    assert len(subprocess_calls) == 1 and ast.unparse(subprocess_calls[0]) == "subprocess.check_output(['git', '--no-optional-locks', *args], cwd=S)"
    contract = json.loads((D / 'references/R31-PRODUCER-CONTRACT.json').read_bytes())
    assert {constants['PREFIX'] + suffix for suffix in constants['SUCCESS_SUFFIXES']} == set(contract['successful_originals'])
    assert len(constants['SUCCESS_SUFFIXES']) == 18
    assert constants['JOB_ID'] == contract['job_id'] and constants['JOB_KEY'] == contract['key']
    assert constants['COMMAND'] == contract['workspace_command'] and constants['METADATA_COMMAND'] == contract['metadata_command']
    assert constants['RUNNER_PIN'] == pin((D / 'references/native-run-r31.py').read_bytes())

    # This narrow expression reader evaluates no function or runner code.
    # It confirms historical argv against already closed actual raw returns.
    prior = ast.parse(funcs['preserve_prior_project']).body[0]
    assignment = next(n for n in ast.walk(prior) if isinstance(n, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'commands' for target in n.targets))
    command_values = dict(zip((ast.literal_eval(key) for key in assignment.value.keys), assignment.value.values))
    def list_literal(node, args):
        assert isinstance(node, ast.List)
        result = []
        for part in node.elts:
            if isinstance(part, ast.Starred):
                assert isinstance(part.value, ast.Name) and part.value.id == 'args'
                result.extend(args)
            else:
                result.append(ast.literal_eval(part))
        return result
    argv_readback = []
    for historical, directory, prefix, packages in (
        (True, 'native-validation-results/r28-archive-closed/original/evidence', 'native-source52-project-r28', constants['HISTORICAL_FOUR_PACKAGES']),
        (False, 'native-validation-results/r30-closed-input/evidence', 'native-source53-project-r30', constants['PACKAGES']),
    ):
        args = [item for package in packages for item in ('-p', package)]
        for phase in (('python-runner', 'strict', 'tests') if historical else ('strict', 'tests')):
            expression = command_values[phase]
            if isinstance(expression, ast.IfExp):
                assert ast.unparse(expression.test) == 'historical'
                expression = expression.body if historical else expression.orelse
            expected = list_literal(expression, args)
            file = B / directory / (prefix + '-' + phase + '-raw-process-result.json')
            original_raw = file.read_bytes(); value = json.loads(original_raw)
            assert expected == value['command']
            argv_readback.append({'path': str(file.relative_to(B)), **pin(original_raw), 'command': value['command'],
                                  'exact_actual_order': True, 'runner_not_executed': True})
    initial = (D / 'initial-build/export-r31-closed-template.py').read_bytes()
    before = "'tests': ['just', 'test', '--locked', '--retries', '0', *args],"
    after = "'tests': (['just', 'test', '--locked', *args, '--retries', '0'] if historical\n                  else ['just', 'test', '--locked', '--retries', '0', *args]),"
    assert initial.decode().replace(before, after) == text
    patch = ''.join(difflib.unified_diff(initial.decode().splitlines(True), text.splitlines(True),
        fromfile='initial-build/export-r31-closed-template.py', tofile='export-r31-closed-template.py')).encode()
    with (D / 'initial-build-correction.patch').open('xb') as stream:
        stream.write(patch); stream.flush(); os.fsync(stream.fileno())
    correction = {'schema': 'hepta.r31-export-initial-static-correction.v1', 'before': pin(initial), 'after': pin(raw),
        'reason': 'Original R28 tests argv has package selectors before --retries 0; R30 has retries before the single package selector. Compare each original order without changing either command.',
        'only_exporter_readback_expression_changed': True, 'neither_exporter_version_executed': True,
        'original_raw_commands': argv_readback, 'patch': pin(patch)}
    write('INITIAL-BUILD-CORRECTION.json', correction)
    report = {'schema': 'hepta.r31-export-static-self-review.v1', 'result': 'STATIC_CLEAR_PENDING_INDEPENDENT_REVIEW_AND_ACTUAL_TERMINAL',
        'template': pin(raw), 'AST_parse': True, 'undefined_global_symbols': missing,
        'exact_R30_exporter_helpers': 13, 'exact_actual_R31_functions': 6,
        'success_original_count': 18, 'future_closure_maps': {name: constants[name] for name in ('TERMINAL_PIN', 'CLOSED_ORIGINAL_PINS', 'CONTROLLER_ORIGINAL_PINS')},
        'FROZEN': False, 'scope': {'source_count': 197, 'members': 193, 'default_members': 193,
            'source_commit': contract['source_commit'], 'source_tree': contract['source_tree']},
        'direct_file_launch_and_controller_byte_ranges_preserved': True,
        'raw_success_failure_and_missing_receipt_preserved': True,
        'compile_or_incomplete_terminal_counts_are_null': True,
        'complete_success_requires_actual18_and_natural_outer0': True,
        'original_r29_20227_PASS_1_FAIL_is_failed_baseline_not_current_result': True,
        'R30_same_source19_and_R28_historical26_separate': True,
        'source_guard_and_dual_locks_before_after_archive': True,
        'deterministic_gzip_tar_create_only_readback_and_fsync_preserved': True,
        'shared_free_space_not_measured_or_attributed': True,
        'only_subprocess': 'allowlisted Git source reads; no gate/metadata/formatter execution',
        'subprocess_was_executed_during_this_review': False,
        'actual_r31_result': None, 'exporter_executed': False, 'metadata_Rust_fix_fmt_executed': False,
        'diagnostic_only': True, 'behavior_repair_claimed': False,
        'boundaries': ['Archive creation success is not gate qualification.',
                       'Future missing or invalid original receipts are retained as missing/readback errors, never synthesized.',
                       'Actual source drift stops export instead of resetting source.',
                       'Future exact closure maps and explicit root authorization remain required.']}
    output_pin = write('STATIC-SELF-REVIEW.json', report)
    print(json.dumps({'template': pin(raw), 'static_readback': output_pin, 'historical_command_rows': len(argv_readback)}))


if __name__ == '__main__':
    main()
