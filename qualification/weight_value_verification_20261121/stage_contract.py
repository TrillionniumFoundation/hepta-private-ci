"""Identity and durable-record primitives for one separately budgeted verification."""
import ast
import datetime as dt
import hashlib
import inspect
import json
import os
from pathlib import Path

SCHEMA = 'hepta-verification-only-frozen-v1'
FITS = (11, 23, 37, 53, 71)
LIMITS = dict(CPU_soft=175, CPU_hard=180, wall_hard=300,
              address_space_bytes=536870912, affinity=[7], threads=1,
              automatic_retry=False)
ORIGINAL_PROTOCOL_SHA = '6eb24982b997a0372744e9302976e5a1e60e9b5815642c12409ca4ff7fd2c99f'
ORIGINAL_READER_SHA = 'c91026ce624564021ec11982265fefcd4d37bc43823a3bdcba3fdb4a502c4bd0'
OVERRIDES = ('configure_budget', 'main_fit_check', 'confirmation_fit_check', 'primary_check')
SOURCE_FILES = ('stage_contract.py', 'fit_journal.py', 'source_loader.py', 'run_verification.py',
                'supervise_verification.py', 'freeze_contract.py', 'test_stage_controls.py', 'README.md')
FORBIDDEN_NEW_WORK = dict(model_candidates=0, public_worlds=0, solver_calls=0,
                         gradient_updates=0, quality_comparisons=0,
                         model_selection=0, financial_labels=0, production_writes=0)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON field: ' + key)
        result[key] = value
    return result


def load_json(path):
    def reject(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique_pairs,
                      parse_constant=reject)


def pin(path):
    path = Path(path).resolve()
    checksum = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
            size += len(block)
    return dict(path=str(path), bytes=size, sha256=checksum.hexdigest())


def verify_pin(expected):
    require(set(('path', 'bytes', 'sha256')) <= expected.keys(), 'incomplete identity')
    require(Path(expected['path']).is_absolute(), 'absolute input identity required')
    actual = pin(expected['path'])
    require(all(actual[key] == expected[key] for key in actual),
            'pinned bytes changed: ' + expected['path'])
    return actual


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def save_new(path, value):
    """Create, flush and fsync a record; never replace an earlier outcome."""
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(canonical(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return pin(path)


def embedded_pins(value):
    if isinstance(value, dict):
        if {'path', 'bytes', 'sha256'} <= value.keys() and isinstance(value['path'], str):
            yield {key: value[key] for key in ('path', 'bytes', 'sha256')}
        for child in value.values():
            yield from embedded_pins(child)
    elif isinstance(value, list):
        for child in value:
            yield from embedded_pins(child)


def check_execution_admission(expected, source_pins, attempt_root):
    verify_pin(expected)
    admission = load_json(expected['path'])
    require(admission['schema'] == 'hepta-verification-execution-admission-v1' and
            admission['status'] == 'READY_FOR_ONE_REAL_EXECUTION' and
            admission['no_real_prior_launch'] is True and
            admission['source_pins'] == source_pins and admission['attempt_root'] == attempt_root,
            'typed one-run admission and exact new source')
    for name in ('authorization_pin', 'qualification_pin', 'peer_review_pin'):
        verify_pin(admission[name])
    authorization = load_json(admission['authorization_pin']['path'])
    require(authorization['schema'] == 'hepta-verification-only-authorization-and-scope-v1' and
            authorization['status'] == 'AUTHORIZED_NEW_SEPARATE_STAGE' and
            authorization['old_phase_immutable'] is True, 'explicit separate-stage authorization')
    qualification = load_json(admission['qualification_pin']['path'])
    require(qualification['status'] == 'COMPLETED' and qualification['returncode'] == 0 and
            qualification['wall_timeout'] is False and
            qualification['source_before'] == qualification['source_after'] == source_pins,
            'successful final-source engineering process')
    verify_pin(qualification['result_pin'])
    suite = load_json(qualification['result_pin']['path'])
    require(suite['schema'] == 'hepta-verification-synthetic-suite-v1' and suite['status'] == 'PASS' and
            suite['tests_run'] == 13 and suite['failures'] == suite['errors'] == suite['skipped'] == 0 and
            suite['real_model_or_array_inputs'] is False and suite['new_real_scientific_calls'] == 0 and
            suite['source_pins'] == source_pins, 'exact synthetic suite outcome')
    peer = load_json(admission['peer_review_pin']['path'])
    require(peer['status'] == 'PASS_STATIC_NO_SCIENTIFIC_EXECUTION' and
            peer['source_pins'] == source_pins, 'complete final-source peer review')
    return admission


def check_contract(path):
    identity = pin(path)
    contract = load_json(path)
    require(contract['schema'] == SCHEMA and contract['status'] == 'FROZEN', 'frozen stage required')
    require(contract['stage_id'] == 'hepta-value-verification-only-20261121-attempt001', 'stage identity')
    require(contract['limits'] == LIMITS and contract['forbidden_new_work'] == FORBIDDEN_NEW_WORK,
            'fixed one-shot verification scope')
    require(contract['fits'] == list(FITS) and contract['allowed_binding_overrides'] == list(OVERRIDES),
            'fixed queue and adapter scope')
    old = contract['original']
    require(old['protocol']['sha256'] == ORIGINAL_PROTOCOL_SHA and
            old['reader_source']['sha256'] == ORIGINAL_READER_SHA, 'original frozen identities')
    require(Path(contract['attempt_root']).is_absolute(), 'fixed absolute attempt destination')
    require(contract['mathematics_and_thresholds_unchanged'] is True, 'unchanged mathematical contract')
    require(set(contract['source_pins']) == set(SOURCE_FILES), 'complete fixed new source set')
    expected_old_keys = {'protocol', 'reader_source', 'main_results', 'main_launch', 'main_process',
                        'selection_seal', 'diagnostics_seal', 'confirmation_results', 'confirmation_launch',
                        'confirmation_process', 'entropy', 'worlds_seal', 'prior_failure',
                        'analysis_provenance', 'proposal'}
    require(set(old) == expected_old_keys and set(old['prior_failure']) == {'launch', 'process', 'failure'},
            'complete original-stage provenance')
    require(not Path(contract['forbidden_prior_reader_result']).exists(), 'original failed attempt changed role')
    closure = {p['path']: p for p in contract['input_closure']}
    require(len(closure) == len(contract['input_closure']), 'unique input closure')
    mandatory = [value for key, value in old.items() if key != 'prior_failure'] + list(old['prior_failure'].values())
    for expected in mandatory:
        require(closure.get(expected['path']) == expected, 'original mandatory input omitted from closure')
    verify_pin(old['protocol'])
    for expected in embedded_pins(load_json(old['protocol']['path'])):
        require(closure.get(expected['path']) == expected, 'original protocol dependency omitted from closure')
    old_attempts = [Path(old[key]['path']).parent.parent for key in ('main_results', 'confirmation_results')]
    old_attempts.append(Path(old['prior_failure']['process']['path']).parent)
    current_members = sorted(str(p.resolve()) for directory in old_attempts
                             for p in directory.rglob('*') if p.is_file())
    require(current_members == contract['original_attempt_members'], 'original attempt inventory changed')
    require(all(name in closure for name in current_members), 'original attempt member omitted from closure')
    for expected in contract['source_pins'].values():
        verify_pin(expected)
    verify_pin(contract['source_reuse_proof'])
    require(bool(contract['pre_execution_evidence']), 'pre-execution evidence required')
    for expected in contract['pre_execution_evidence']:
        verify_pin(expected)
    check_execution_admission(contract['execution_admission_pin'], contract['source_pins'],
                              contract['attempt_root'])
    for expected in contract['input_closure']:
        verify_pin(expected)
    return contract, identity


def source_ast_identities(path):
    """Static provenance only: no original module is executed here."""
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    return {node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
            for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def function_bindings(module):
    return {name: value for name, value in vars(module).items()
            if inspect.isfunction(value) and value.__module__ == module.__name__}


def check_binding_reuse(module, original, replacements):
    require(set(replacements) == set(OVERRIDES), 'only declared wrappers may replace bindings')
    for name, function in original.items():
        require(getattr(module, name) is replacements.get(name, function),
                'original reader function binding changed: ' + name)
    require(module.ARRAY_TOLERANCE == 2e-12 and module.METRIC_TOLERANCE == 2e-11 and
            module.FITS == FITS, 'original tolerances or fit queue changed')
