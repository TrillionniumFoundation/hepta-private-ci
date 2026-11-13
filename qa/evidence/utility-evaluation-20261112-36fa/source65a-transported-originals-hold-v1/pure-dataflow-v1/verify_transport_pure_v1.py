"""Local immutable bytes only. Never constructs Admission or opens a native path."""
from pathlib import Path
import ast
import base64
import copy
import gzip
import hashlib
import io
import json
import pathlib
import types


BASE = Path(__file__).resolve().parent
FROZEN = BASE / 'review-candidate-v1'
OUT = BASE / 'pure-dataflow-v1'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def serialized(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def exact_definitions(source, names):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in found} == set(names)
    return ''.join(''.join(lines[node.lineno - 1:node.end_lineno]) + '\n\n' for node in found)


def main():
    manifest_raw = (FROZEN / 'MANIFEST.json').read_bytes()
    assert identity(manifest_raw)['git_blob'] == '7b7aa021cdc0f75f9a18edc210f7e540e55663c4'
    manifest = json.loads(manifest_raw)
    for row in manifest['files']:
        assert identity((FROZEN / row['name']).read_bytes()) == {
            key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    admission_raw = (FROZEN / 'qualification-admission.HOLD.py').read_bytes()
    admission_tree = ast.parse(admission_raw)
    assert all(isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                                ast.FunctionDef, ast.ClassDef))
               or isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
               and isinstance(node.value.value, str) for node in admission_tree.body)
    mod = types.ModuleType('frozen_transport_admission_definitions_only')
    exec(compile(admission_tree, '<frozen definitions; no constructor>', 'exec'), mod.__dict__)
    stage_source = (FROZEN / 'TRANSPORT_STAGER.HOLD.py').read_text()
    stage_tree = ast.parse(stage_source)
    stage_names = {'BASE', 'ORIGINALS', 'MANIFEST_PIN', 'HISTORICAL_GUARD_PIN',
                   'PACKET_PIN', 'GZIP_PIN', 'PART_INPUTS'}
    stage_nodes = [node for node in stage_tree.body if isinstance(node, ast.Assign)
                   and all(isinstance(t, ast.Name) and t.id in stage_names for t in node.targets)]
    stage_pure = exact_definitions(stage_source, ['check', 'identity', 'no_duplicates', 'parse', 'decode_packet'])
    stage = {'base64': base64, 'gzip': gzip, 'hashlib': hashlib, 'io': io,
             'json': json, 'pathlib': pathlib}
    exec(compile(ast.Module(stage_nodes, type_ignores=[]), '<frozen decoder constants>', 'exec'), stage)
    exec(compile(stage_pure, '<five exact frozen pure decoder definitions>', 'exec'), stage)
    compressed = b''.join(base64.b64decode((FROZEN / f'parts/PART_{i:03d}.b64').read_bytes(),
                                          validate=False) for i in range(1, 18))
    history_manifest_raw = (FROZEN / 'TRANSPORT_MANIFEST.HOLD.json').read_bytes()
    history_manifest, bodies = stage['decode_packet'](compressed, history_manifest_raw)
    assert len(bodies) == 55 and sum(map(len, bodies.values())) == 7976106
    assert len({identity(raw)['git_blob'] for raw in bodies.values()}) == 50
    checks = []

    def accepted(name, function, scope='actual retained data, memory only'):
        value = function()
        checks.append({'name': name, 'outcome': 'accepted', 'scope': scope})
        return value

    def rejected(name, function, scope='negative memory-only fixture'):
        try:
            function()
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError, AssertionError) as error:
            checks.append({'name': name, 'outcome': 'rejected', 'scope': scope,
                           'error_type': type(error).__name__, 'reason': str(error)})
        else:
            raise AssertionError('negative boundary accepted: ' + name)

    accepted('exact original 17-part package decoder restores 55 bodies / 50 distinct contents',
             lambda: stage['decode_packet'](compressed, history_manifest_raw))
    for name, changed in [('truncated gzip', compressed[:-1]), ('appended gzip byte', compressed + b'\0'),
                          ('one changed gzip byte', bytes([compressed[0] ^ 1]) + compressed[1:]),
                          ('gzip parts reordered', compressed[307200:614400] + compressed[:307200] + compressed[614400:])]:
        rejected(name, lambda changed=changed: stage['decode_packet'](changed, history_manifest_raw))
    rejected('manifest bytes changed', lambda: stage['decode_packet'](compressed, history_manifest_raw + b' '))
    rejected('duplicate JSON key', lambda: stage['parse'](b'{"role":1,"role":2}'))
    rejected('trailing JSON value', lambda: stage['parse'](b'{}{}'))
    rejected('truncated JSON', lambda: stage['parse'](b'{"role":'))
    decoder = next(node for node in stage_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'decode_packet')
    bounded_read = ast.parse("stream.read(PACKET_PIN['bytes'] + 1)", mode='eval').body
    assert any(ast.dump(node, include_attributes=False) == ast.dump(bounded_read, include_attributes=False)
               for node in ast.walk(decoder) if isinstance(node, ast.Call))

    # Only the following read adapter replaces native I/O in this separate review.
    # It is not installed into any candidate source file or existing native module.
    byte_map = {row['transport_path']: bodies[row['role']] for row in history_manifest['rows']}
    byte_map[mod.HISTORY_MANIFEST_PATH] = history_manifest_raw
    read_ledger = []
    old_guard = (Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1') /
                 'inputs/V5_GUARD_6632.original.py').read_text()
    pure_original = {'json': json, 'PreconditionError': RuntimeError}
    exec(compile(exact_definitions(old_guard, ['check', 'nodup', 'parse', 'parse_supervisor']),
                 '<four exact original V5 pure helpers>', 'exec'), pure_original)

    class MemoryOnly:
        def __init__(self):
            self.input_pins, self.records = {}, {}

        def read_input(self, path, expected, maximum=40000000):
            key = str(path)
            assert key in byte_map, 'review cannot access a live or unmapped native path'
            raw = byte_map[key]
            assert len(raw) <= maximum
            mod.pin(raw, expected, 'exact mapped original body')
            self.input_pins[key] = mod.pin_fields(expected)
            read_ledger.append({'path_as_data_only': key, **identity(raw)})
            return raw

        @staticmethod
        def parse(raw):
            return pure_original['parse'](raw)

        @staticmethod
        def parse_supervisor(raw):
            return pure_original['parse_supervisor'](raw)

        def write(self, name, raw):
            assert name not in self.records, 'review memory record cannot be replaced'
            self.records[name] = raw

        def jwrite(self, name, value):
            self.write(name, serialized(value))

    memory = MemoryOnly()
    reader = object.__new__(mod.Admission)  # No __init__, acquire, close or finish.
    reader.cfg = json.loads((FROZEN / 'QUALIFICATION_CONFIG.HOLD.json').read_bytes())
    reader.m = memory
    reader._fixed_raw = {}
    reader._read_transport_file = types.MethodType(
        lambda self, path, expected, maximum=40000000: memory.read_input(path, expected, maximum), reader)
    reader._history_rows = accepted('exact pinned manifest closed role parser', reader._load_transport_manifest)
    for role, row in reader._history_rows.items():
        assert reader._read_historical(role, row['original_path'], row['pin']) == bodies[role]
        rejected('wrong provenance path for ' + role,
                 lambda role=role, row=row: reader._read_historical(role, row['original_path'] + '.wrong', row['pin']))
        wrong_pin = dict(row['pin'], bytes=row['pin']['bytes'] + 1)
        rejected('wrong complete pin for ' + role,
                 lambda role=role, row=row, wrong_pin=wrong_pin: reader._read_historical(role, row['original_path'], wrong_pin))
    for name, path in [('live source', mod.CURRENT_REPO + '/AGENTS.md'),
                       ('live Git index', mod.CURRENT_REPO + '/.git/index'),
                       ('coordination lock', reader.cfg['coordination_lock']['path']),
                       ('unknown historic role', history_manifest['rows'][0]['original_path'])]:
        rejected(name + ' has no role mapping', lambda path=path: reader._read_historical(
            'not.in.closed.roles', path, history_manifest['rows'][0]['pin']))
    rejected('unmapped direct memory read cannot access a live index', lambda: memory.read_input(
        Path(mod.CURRENT_REPO) / '.git/index', reader.cfg['canonical_original_index']))

    canonical = memory.parse(bodies['canonical.result'])
    prefix = next(key for key, value in mod.HISTORY_PROOF_ROLES.items() if value[0] == 'canonical.result')
    assert accepted('actual canonical normal/result pair preserves original job and provenance',
                    lambda: reader.observed_proof(reader.cfg['canonical_alignment'], prefix)) == canonical
    reader.materialized = accepted('actual 3bb result and four records through fixed historical mapping',
                                  lambda: reader.validate_materialization(canonical))
    accepted('actual archive restoration keeps original runtime content contract', reader._validate_archive)
    maintenance = accepted('actual 3bb to 41e source / metadata / original single fix-fmt records',
                           lambda: reader._validate_maintenance(reader.materialized))
    final, final_raw, final_metadata = accepted('actual 41e to 50f four non-Rust paths / original fmt terminal',
                                               lambda: reader._validate_final_format(maintenance))
    canonical_cfg = memory.parse(bodies['canonical.config'])
    accepted('actual 50f to 5a9 canonical pure schema and budget contract',
             lambda: reader._check_canonical(canonical, final, reader.cfg, canonical_cfg))
    accepted('all existing actual canonical binding leaves remain complete',
             lambda: reader._require_complete_bindings(reader.cfg))
    rejected('four null actual transport fields keep the new contract on HOLD',
             lambda: reader._require_transport_bindings(reader.cfg))
    assert all(reader.cfg['history_transport'][key] is None for key in (
        'staging_result', 'staging_supervisor', 'staging_payload', 'staging_job_id'))
    assert reader.cfg['root_execution_approved'] is False
    for field in ('staging_result', 'staging_supervisor', 'staging_payload', 'staging_job_id'):
        fixture = copy.deepcopy(reader.cfg)
        # Syntactic-only pins are deliberately not receipts and never written as such.
        for key in ('staging_result', 'staging_supervisor', 'staging_payload'):
            fixture['history_transport'][key] = identity(b'')
        fixture['history_transport']['staging_job_id'] = 'synthetic-structural-fixture-only'
        fixture['history_transport'][field] = None
        rejected('missing actual transport leaf: ' + field,
                 lambda fixture=fixture: reader._require_transport_bindings(fixture),
                 'syntactic negative fixture; not a transport result or supervisor')

    # Execute only the unchanged historical validation logic and four role reads,
    # with exact local originals and memory-only I/O. No environment preflight.
    historical_source = (FROZEN / 'historical-runtime-guard.HOLD.py').read_text()
    historical_tree = ast.parse(historical_source)
    constant_names = {'REPO', 'EVIDENCE', 'ENVIRONMENT_FILE', 'C0F', 'A96', 'SEED_HEAD',
                      'SEED_TREE', 'SEED_PARENTS', 'TARGET', 'DEPOT', 'HISTORICAL_ENV_PIN',
                      'HISTORY_TRANSPORT_CONTROL', 'HISTORY_MANIFEST_PATH', 'HISTORY_MANIFEST_PIN',
                      'HISTORY_RUNTIME_ROLES'}
    constants = [node for node in historical_tree.body if isinstance(node, ast.Assign)
                 and all(isinstance(t, ast.Name) and t.id in constant_names for t in node.targets)]
    h = {'json': json, 'hashlib': hashlib, 'pathlib': pathlib, 'PreconditionError': RuntimeError}
    exec(compile(ast.Module(constants, type_ignores=[]), '<exact historical constants>', 'exec'), h)
    helper_names = ['check', 'nodup', 'parse', 'parse_supervisor', 'sha256', 'oid', 'pin_bytes',
                    'read_transported_historical_input', 'validate_runtime_restoration']
    exec(compile(exact_definitions(historical_source, helper_names),
                 '<nine exact pure historical definitions; no preflight>', 'exec'), h)
    history_memory_records = {}
    def history_write(name, raw):
        assert name not in history_memory_records
        history_memory_records[name] = raw
    h.update(cfg=copy.deepcopy(mod.RUNTIME_GUARD), result={}, write=history_write,
             _read_historical_transport_file=memory.read_input)
    actual_environment = accepted('original historical runtime validator: seed, job, six commands, three audits',
                                  h['validate_runtime_restoration'])
    assert actual_environment == memory.parse(bodies['runtime.environment_ready'])
    fourth = accepted('original historical ENVIRONMENT_FILE role reads all 1154 retained bytes',
                      lambda: h['read_transported_historical_input'](
                          'historical_environment.started', h['ENVIRONMENT_FILE'], h['HISTORICAL_ENV_PIN'], 100000))
    assert fourth == bodies['historical_environment.started']
    original_job = h['cfg']['runtime_restoration']['job_id']
    h['cfg']['runtime_restoration']['job_id'] = 'not-the-actual-historical-job'
    rejected('history runtime validator rejects a substituted producer job', h['validate_runtime_restoration'])
    h['cfg']['runtime_restoration']['job_id'] = original_job
    for role, row in h['HISTORY_RUNTIME_ROLES'].items():
        rejected('historical V5 wrong original path: ' + role,
                 lambda role=role, row=row: h['read_transported_historical_input'](
                     role, row['original_path'] + '.wrong', row['pin']))
    rejected('historical V5 cannot map an extra live role', lambda: h['read_transported_historical_input'](
        'live.index', mod.CURRENT_REPO + '/.git/index', reader.cfg['canonical_original_index']))
    assert set(h['HISTORY_RUNTIME_ROLES']) == {'runtime.result', 'runtime.supervisor',
                                              'runtime.environment_ready', 'historical_environment.started'}
    # The complete live canonical validator and live runtime checks are deliberately not invoked.
    untouched = [node for node in ast.walk(admission_tree) if isinstance(node, ast.FunctionDef)
                 and node.name in ('_validate_index_audit', '_require_live_metadata')]
    assert len(untouched) == 2
    report = {
        'format': 'hepta-transported-history-pure-dataflow-and-negative-boundaries-v1',
        'not_an_execution_approval': True, 'H_calls': 0, 'qualification': False,
        'source_subject': mod.FINAL_SUBJECT, 'immutable_candidate_manifest': identity(manifest_raw),
        'admission': identity(admission_raw),
        'historical_v5': identity(historical_source.encode()),
        'transport_manifest': identity(history_manifest_raw),
        'stage_decoder': identity(stage_source.encode()),
        'compressed_packet': identity(compressed),
        'historical_roles': 55, 'distinct_bodies': 50, 'original_bytes': 7976106,
        'actual_producers_replayed_as_data': ['historical runtime', 'archive-v3', '3bb', '41e', '50f', '5a9'],
        'checks': checks, 'accepted': sum(x['outcome'] == 'accepted' for x in checks),
        'rejected': sum(x['outcome'] == 'rejected' for x in checks),
        'transport_files_actually_created': False, 'stage_or_supervisor_success_created': False,
        'constructor_or_acquire_or_finish_called': False,
        'full_canonical_live_validator_called': False, 'environment_preflight_called': False,
        'native_source_git_or_material_paths_opened': False,
        'pure_adapters': ['separate review-only dictionary input reader', 'memory-only evidence writes'],
        'new_candidate_sources_changed_by_review': False,
        'current_V5_and_live_checks_unmodified': True,
        'actual_transport_four_fields_remain_null': True,
        'source_and_native_typed_requests': None,
        'memory_read_ledger': read_ledger,
        'complete_memory_retained_record_pins': {key: identity(value) for key, value in memory.records.items()},
        'history_memory_retained_record_pins': {key: identity(value) for key, value in history_memory_records.items()},
        'limitation': 'Exact retained data and pure predicates only. No observation of future staging, file ownership/stability, lock, live source/Git/environment, source gates or native phases.'
    }
    OUT.mkdir(exist_ok=False)
    with (OUT / 'REVIEW.json').open('xb') as stream:
        stream.write(serialized(report))
    with (OUT / 'verify_transport_pure_v1.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print(json.dumps({'review': identity((OUT / 'REVIEW.json').read_bytes()),
                      'script': identity((OUT / 'verify_transport_pure_v1.py').read_bytes()),
                      'checks': len(checks), 'accepted': report['accepted'],
                      'rejected': report['rejected'], 'H_calls': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
