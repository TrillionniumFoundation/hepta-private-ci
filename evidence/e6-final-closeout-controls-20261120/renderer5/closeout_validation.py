"""Finite evidence admission only: retained bytecode data and actual terminals.

Nothing here imports, unmarshals, compiles or executes retained bytecode. The
terminal validator does not make an experiment pass; a real failure is retained
as failure and an intermediate status is not a completed RESULT.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import math
import re

BYTECODE = {
    'path': 'e6_owner_work/historical_startup_native_resume/rev1/wrapper-full-originals-1/originals/__pycache__/ORIGINAL_HARNESS.cpython-314.pyc',
    'bytes': 55592,
    'sha256': 'e1c10e9e525044f40feeefebe22b1d9d2b0178a6ed415787c0899758bd8ab8b9',
    'git_blob': '3158ed87c75a23e03f02472aa5126aebfac264c5',
}
RETAINED_BYTECODE = (BYTECODE, {'path': 'e6_owner_work/observation_io_diagnostic_native/rev2/wrapper-full-originals-1/originals/__pycache__/ORIGINAL_HARNESS.cpython-314.pyc', 'bytes': 55592, 'sha256': '2a4fa4e078e50d6a4c482f3dba9122eebf6be7de70be7164e149567290554c5c', 'git_blob': '027a11d133e97255b137d5083fab2498d82fb87e'})
REMOTE_BASE = '/home/qq/work/hepta-e6-first-error-20261120-2e9b/'
STAGES4_REFERENCE = {
    'path': 'e6_final_blob_gate_work/OBSERVATION_IO_SOURCE_STAGES.json',
    'bytes': 3619,
    'sha256': '4692fe4143ba5a8b74f7ad82cf7c7ae854954e8f83241ab5c0a6c80c48831e2e',
    'git_blob': '0d56739934966e4919fb8d4359548015714ae588',
}
TERMINAL_PROFILES = {
    'bounded_compile_continuation': {
        'statuses': ('completed', 'failed'),
        'source_fields': {'/source_before_compile_sha256': 'inventory', '/source_after_sha256': 'inventory'},
        'optional_source_fields': {'source_candidate_commit': 'commit', 'source_candidate_tree': 'tree'},
    },
    'original_source_gate': {
        'statuses': ('completed', 'failed'),
        'source_fields': {'/original_source_sha256': 'inventory', '/source_after_sha256': 'inventory'},
        'optional_source_fields': {'source_candidate_commit': 'commit', 'source_candidate_tree': 'tree'},
    },
    'source_freeze': {
        'statuses': None,
        'source_fields': {'/source': 'commit', '/source_inventory_sha256': 'inventory'},
        'optional_source_fields': {'tree': 'tree', 'source_tree': 'tree'},
    },
    'native15': {
        'statuses': ('completed', 'stopped'),
        'source_fields': {'/source': 'commit', '/source_inventory_sha256': 'inventory'},
        'optional_source_fields': {'tree': 'tree', 'source_tree': 'tree'},
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def retained_bytecode(path, expected, root):
    """Return one exact allowed identity, or reject an unlisted bytecode path."""
    path = Path(path)
    if not (path.name.lower().endswith(('.pyc', '.pyo')) or '__pycache__' in path.parts):
        return None
    require(path.is_absolute(), 'bytecode path must be an explicit absolute evidence path')
    relative = path.relative_to(root).as_posix()
    require('..' not in Path(relative).parts, 'noncanonical bytecode path')
    # Second form is the unchanged restore output: <fresh-dir>/originals/<logical>.
    matches = [item for item in RETAINED_BYTECODE
               if relative == item['path'] or relative.endswith('/originals/' + item['path'])]
    require(len(matches) == 1, 'unlisted bytecode logical path')
    allowed = matches[0]
    require(expected is not None and expected.get('bytes') == allowed['bytes']
            and expected.get('sha256') == allowed['sha256'], 'bytecode expected identity is incomplete or differs')
    expected_git = expected.get('git_blob', expected.get('git_blob_sha1'))
    require(expected_git is None or expected_git == allowed['git_blob'], 'bytecode expected Git identity differs')
    return allowed


def verify_bytecode(actual, allowed):
    if allowed is not None:
        require(all(actual[k] == allowed[k] for k in ('bytes', 'sha256', 'git_blob')),
                'retained bytecode bytes differ from the original runtime inventory')


def _object(reference, reader):
    body, actual = reader(reference)
    return json.loads(body), {'path': reference['path'], **actual}, body


def _rpc(reference, reader):
    outer, pin, _ = _object(reference, reader)
    require(outer.get('isError') is False, 'owner/capture RPC was an error')
    content = outer.get('content')
    require(isinstance(content, list), 'expected retained original MCP content')
    texts = [item['text'] for item in content if item.get('type') == 'text']
    require(len(texts) == 1, 'ambiguous original RPC payload')
    value = json.loads(texts[0])
    require(isinstance(value, dict), 'original RPC payload is not an object')
    return value, pin


def _positive_ns(value, label):
    require(type(value) in (str, int) and str(value).isdigit(), label + ' missing')
    value = int(value)
    require(value > 0, label + ' invalid')
    return value


def _complete_reference(reference):
    require(isinstance(reference, dict), 'explicit reference object required')
    require(type(reference.get('bytes')) is int and reference['bytes'] >= 0,
            'reference byte length missing')
    for name, length in (('sha256', 64), ('git_blob', 40)):
        require(isinstance(reference.get(name), str)
                and re.fullmatch('[0-9a-f]{' + str(length) + '}', reference[name]),
                'complete reference identity missing: ' + name)
    path = PurePosixPath(reference.get('path', ''))
    require(bool(reference.get('path')) and not path.is_absolute()
            and str(path) == reference['path'] and '..' not in path.parts
            and '\\' not in reference['path'] and '\0' not in reference['path'],
            'reference must use an exact relative workspace path')


def _same_reference(left, right):
    return all(left.get(k) == right.get(k) for k in ('path', 'bytes', 'sha256', 'git_blob'))


def _source_identity(value):
    require(isinstance(value, dict) and set(value) == {'commit', 'tree', 'inventory'},
            'source identity must explicitly bind commit, tree and inventory')
    for name, length in (('commit', 40), ('tree', 40), ('inventory', 64)):
        require(isinstance(value[name], str)
                and re.fullmatch('[0-9a-f]{' + str(length) + '}', value[name]),
                'invalid source identity: ' + name)


def validate_source_contract(reference, reader, root):
    """Read a separately pinned Root decision; never choose a future source.

    The contract is reviewed input, not a credential or an execution grant.
    A stage may explicitly describe a historical source; this is preserved as
    historical_only and never transferred to the contract's final source.
    """
    _complete_reference(reference)
    contract, contract_pin, _ = _object(reference, reader)
    require(contract.get('schema') == 'hepta-reviewed-source-stages-2'
            and contract.get('state') == 'ROOT_REVIEWED_EXACT_SOURCE_AND_STAGE_CONTRACT',
            'final source/stage contract is absent or not reviewed')
    final_source = contract['final_source']
    _source_identity(final_source)
    _complete_reference(contract['source_stages'])
    stages, stages_pin, _ = _object(contract['source_stages'], reader)
    old_stages, old_pin, _ = _object(STAGES4_REFERENCE, reader)
    require(isinstance(stages, list) and len(stages) >= len(old_stages)
            and stages[:len(old_stages)] == old_stages,
            'the original four source stages were replaced or reclassified')
    evidence = [contract_pin, stages_pin, old_pin]
    raw_sources = {}
    previous = None
    for stage in stages:
        require(stage['kind'] == 'source' and stage['head'] not in raw_sources,
                'source stage is reclassified or duplicated')
        bodies = {}
        for field in ('head_api', 'head_raw', 'files_manifest'):
            path = Path(stage[field])
            require(path.is_absolute(), 'source-stage artifact needs its original absolute path')
            relative = path.relative_to(root).as_posix()
            body, actual = reader({'path': relative, 'sha256': stage[field + '_sha256']})
            evidence.append({'path': relative, **actual})
            bodies[field] = body
        raw = bodies['head_raw']
        require(hashlib.sha1(b'commit ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == stage['head'],
                'raw source commit Git identity differs')
        header = raw.split(b'\n\n', 1)[0].splitlines()
        trees = [line[5:].decode('ascii') for line in header if line.startswith(b'tree ')]
        parents = [line[7:].decode('ascii') for line in header if line.startswith(b'parent ')]
        require(len(trees) == 1 and re.fullmatch('[0-9a-f]{40}', trees[0])
                and len(parents) == 1, 'source raw commit tree/parent schema differs')
        if previous is not None:
            require(parents == [previous], 'source stages do not form the original direct-parent chain')
        previous = stage['head']
        raw_sources[stage['head']] = trees[0]
        # The whole-tree blob gate is separate. Here all declared changed
        # source bytes are retained and tied to their original Git blob IDs.
        file_rows = json.loads(bodies['files_manifest'])
        require(isinstance(file_rows, list) and file_rows
                and len({row['path'] for row in file_rows}) == len(file_rows),
                'source file manifest is empty or duplicated')
        for row in file_rows:
            local = Path(row['local_path'])
            require(local.is_absolute() and row.get('mode') in ('100644', '100755'),
                    'source manifest file schema differs')
            ref = {'path': local.relative_to(root).as_posix(),
                   **{k: row[k] for k in ('bytes', 'sha256', 'git_blob')}}
            _, actual = reader(ref)
            evidence.append({'path': ref['path'], **actual})
    require(previous == final_source['commit'] and raw_sources[previous] == final_source['tree'],
            'final source is not the exact last raw commit/tree')
    require(isinstance(contract.get('stages'), dict)
            and set(contract['stages']) <= set(TERMINAL_PROFILES), 'unknown stage contract')
    remote_paths = set()
    for identifier, stage in contract['stages'].items():
        _source_identity(stage['source'])
        require(raw_sources.get(stage['source']['commit']) == stage['source']['tree'],
                'actual stage source is not retained in the reviewed raw commit chain')
        relation = 'exact_final' if stage['source'] == final_source else 'historical_only'
        require(stage.get('source_relation') == relation, 'stage source relation is not explicit')
        for field in ('runner', 'owner_start'):
            _complete_reference(stage[field])
            body, actual = reader(stage[field])
            evidence.append({'path': stage[field]['path'], **actual})
        require(stage['runner']['path'].endswith('.py'), 'runner is a pinned source file, never retained bytecode')
        remote = stage['remote_result_path']
        path = PurePosixPath(remote)
        require(remote.startswith(REMOTE_BASE) and path.name == 'RESULT.json'
                and str(path) == remote and '..' not in path.parts and remote not in remote_paths,
                'stage needs one unique exact original RESULT path')
        remote_paths.add(remote)
        require(stage.get('source_binding_mode') in ('same_result', 'unbound_failure_only'),
                'source binding mode was not explicitly reviewed')
    unique = {}
    for pin in evidence:
        prior = unique.setdefault(pin['path'], pin)
        require(_same_reference(prior, pin), 'reviewed source contract contains conflicting file identities')
    return {'contract': contract, 'reference': contract_pin, 'evidence': list(unique.values()),
            'final_source': final_source, 'actual_source_stages': len(stages),
            'whole_tree_gate_executed': False, 'qualification_transferred': False}


def validate_terminal_slot(slot, reader):
    """Bind RESULT, source, full capture, one real owner and its final PTY."""
    require(slot['id'] in TERMINAL_PROFILES and slot['state'] == 'terminal', 'unknown actual stage')
    profile = TERMINAL_PROFILES[slot['id']]
    source_contract = validate_source_contract(slot['reviewed_source_contract'], reader,
                                              Path('/workspace/scratch/e9e051ab0825'))
    require(slot['id'] in source_contract['contract']['stages'], 'actual stage has no reviewed source/runner binding')
    stage = source_contract['contract']['stages'][slot['id']]
    for field in ('result', 'owner_start', 'owner_terminal', 'result_capture'):
        _complete_reference(slot[field])
    require(_same_reference(slot['owner_start'], stage['owner_start']),
            'terminal uses a different owner from the reviewed stage')
    require(slot['source_binding_mode'] == stage['source_binding_mode'], 'source binding mode changed')
    result, result_pin, body = _object(slot['result'], reader)
    require(type(result.get('successful')) is bool, 'actual RESULT has no success boolean')
    if 'runner_sha256' in result:
        require(result['runner_sha256'] == stage['runner']['sha256'], 'RESULT runner differs from reviewed code')
    if profile['statuses'] is not None:
        require(result.get('status') in profile['statuses'], 'intermediate or unknown RESULT status')
        started = _positive_ns(result.get('started_at_ns'), 'RESULT start')
        ended = _positive_ns(result.get('finished_at_ns'), 'RESULT finish')
        require(ended >= started, 'RESULT time order differs')
        wall = result.get('owner_wall_seconds')
        require(type(wall) in (int, float) and math.isfinite(wall) and wall >= 0,
                'terminal owner duration missing')
        if result['successful']:
            require(result['status'] == 'completed', 'successful RESULT is not completed')
    else:
        # The exact freeze writer has no intermediate RESULT writes. Its error
        # schema intentionally lacks a source identity and final timestamp.
        require('status' not in result, 'freeze RESULT schema differs')
        started = None
        if result['successful']:
            ended = _positive_ns(result.get('frozen_at_ns'), 'freeze completed time')
            wall = result.get('owner_wall_seconds')
            require(type(wall) in (int, float) and math.isfinite(wall) and wall >= 0, 'freeze duration missing')
            require(result['original_blob_policy_tests']['exit_code'] == 0
                    and result['exact_source_blob_policy']['exit_code'] == 0, 'freeze success gates differ')
        else:
            require(set(result) == {'successful', 'error', 'native_runs'} and result['native_runs'] == 0
                    and isinstance(result['error'], str) and result['error'], 'unknown freeze failure schema')
            ended = None

    start, start_pin = _rpc(slot['owner_start'], reader)
    terminal, terminal_pin = _rpc(slot['owner_terminal'], reader)
    require(start.get('reused') is False and start['status']['state'] == 'running', 'not the original unique owner start')
    require(start['session_id'] == terminal['session_id'] and start.get('host') == terminal.get('host'), 'owner identities differ')
    owner_start, owner_end = start['status'], terminal['status']
    for key in ('boot', 'created_unix_ms', 'owner_pid', 'pid'):
        require(owner_start.get(key) is not None and owner_start[key] == owner_end.get(key), 'owner status binding differs')
    require(owner_end.get('state') == 'exited' and owner_end.get('output_complete') is True
            and terminal.get('output_complete') is True and owner_end.get('capture_error') is None,
            'owner has not truly completed')
    require(type(owner_end.get('exit_code')) is int, 'owner exit code absent')
    require((owner_end['exit_code'] == 0) == result['successful'], 'owner exit and RESULT disagree')
    chunk = bytes.fromhex(terminal['bytes_hex'])
    require(hashlib.sha256(chunk).hexdigest() == terminal['chunk_sha256'], 'terminal PTY chunk differs')
    require(len(chunk) == terminal['next_offset'] - terminal['offset']
            and terminal['next_offset'] == terminal['available_end'], 'terminal PTY is not the observed end')
    created_ns = owner_start['created_unix_ms'] * 1_000_000
    if started is not None:
        require(started >= created_ns, 'RESULT belongs to an earlier owner window')
    if ended is not None:
        require(ended >= created_ns, 'RESULT finished before this owner existed')

    capture, capture_pin = _rpc(slot['result_capture'], reader)
    remote_path = stage['remote_result_path']
    matches = [row for row in capture.get('files', []) if row.get('path') == remote_path]
    require(len(matches) == 1, 'exact stage RESULT capture missing')
    row = matches[0]
    require(row.get('eof') is True and row.get('size') == result_pin['bytes']
            and row.get('sha256') == result_pin['sha256'] and row.get('text', '').encode('utf-8') == body,
            'captured remote RESULT is not the admitted complete body')
    version = row.get('version', '').split(':')
    require(len(version) == 5 and all(v.isdigit() for v in version), 'fixed-version RESULT capture missing')
    require(int(version[2]) == len(body) and int(version[3]) >= created_ns,
            'RESULT file predates this owner')
    if ended is not None:
        require(int(version[3]) >= ended, 'captured RESULT precedes its finish field')

    checks = slot.get('source_checks', [])
    unbound_failure = slot.get('source_binding_mode') == 'unbound_failure_only'
    if unbound_failure:
        require(result['successful'] is False and not checks,
                'unbound source may only preserve an actual failure without source qualification')
    else:
        require(slot.get('source_binding_mode') == 'same_result'
                and len(checks) == len(profile['source_fields'])
                and {check['pointer'] for check in checks} == set(profile['source_fields']),
                'terminal needs every required top-level source check on the same RESULT')
        for field, source_key in profile['optional_source_fields'].items():
            if field in result:
                require(result[field] == stage['source'][source_key], 'additional RESULT source identity contradicts the contract')
    observed_checks = []
    for check in checks:
        require(_same_reference(check['result'], result_pin), 'source check borrows a different RESULT')
        address = check['pointer']
        require(address in profile['source_fields']
                and check['expected'] == stage['source'][profile['source_fields'][address]],
                'source pointer is not an allowed exact top-level identity')
        value = result.get(address[1:])
        require(type(value) is str and value == check['expected'], 'same RESULT source identity differs')
        observed_checks.append({'result': result_pin, 'pointer': address, 'observed': value})
    return {'result': result_pin, 'evidence': [start_pin, terminal_pin, capture_pin] + source_contract['evidence'],
            'source_checks': observed_checks, 'source_binding_verified': not unbound_failure,
            'failure_with_unbound_source_is_only_archival': unbound_failure,
            'expected_stage_source': stage['source'],
            'actual_stage_source': None if unbound_failure else stage['source'],
            'source_relation': 'unverified_failure' if unbound_failure else stage['source_relation'],
            'matches_final_source': None if unbound_failure else stage['source_relation'] == 'exact_final',
            'source_qualification_transferred': False,
            'owner_session_id': start['session_id'], 'terminal_exit_code': owner_end['exit_code'],
            'intermediate_state_accepted': False, 'experiment_qualification_inferred': False}
