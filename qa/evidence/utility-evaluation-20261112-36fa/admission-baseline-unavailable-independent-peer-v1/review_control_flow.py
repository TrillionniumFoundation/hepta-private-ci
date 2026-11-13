"""Exact delta and memory-only finish/error-classification review. No native I/O."""
from pathlib import Path
import ast
import copy
import hashlib
import json
import types


SOURCE = Path('/tmp/hepta-36fa-admission-baseline-unavailable-increment-v1')
OUT = Path(__file__).resolve().parent
WRAPPERS = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/inputs')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def definitions(raw, name):
    tree = ast.parse(raw)
    assert all(isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef, ast.ClassDef))
               or isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
               and isinstance(n.value.value, str) for n in tree.body)
    module = types.ModuleType(name)
    exec(compile(tree, '<definitions only; no Admission construction>', 'exec'), module.__dict__)
    return module


def function_map(raw):
    tree = ast.parse(raw)
    lines = raw.decode().splitlines(keepends=True)
    result = {}
    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                key = '.'.join(scope + [child.name])
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min([child.lineno] + [x.lineno for x in child.decorator_list])
                    assert key not in result
                    result[key] = ''.join(lines[start - 1:child.end_lineno])
                visit(child, scope + [child.name])
            else:
                visit(child, scope)
    visit(tree, [])
    return result


def main():
    before = (SOURCE / 'qualification-admission.before.py').read_bytes()
    after = (SOURCE / 'qualification-admission.after.py').read_bytes()
    assert identity(before)['git_blob'] == '299c3d79987abcde03e83c271bee91c568e0a5ab'
    assert identity(after)['git_blob'] == 'fd67cb043f7b6cb8cf042104ac202cb5f0842196'
    replacements = json.loads((SOURCE / 'EXACT_REPLACEMENTS.json').read_bytes())
    inverse = after.decode()
    for row in reversed(replacements):
        assert inverse.count(row['new']) == 1
        inverse = inverse.replace(row['new'], row['old'], 1)
    assert inverse.encode() == before
    old_map, new_map = function_map(before), function_map(after)
    assert set(old_map) == set(new_map)
    changed = [name for name in old_map if old_map[name] != new_map[name]]
    assert changed == ['Admission.finish']
    old, new = definitions(before, 'old_frozen_admission'), definitions(after, 'new_classification_proposal')
    assert issubclass(new.InitialBaselineUnavailable, RuntimeError)
    assert not issubclass(new.InitialBaselineUnavailable, new.SourceChanged)

    # All following values are explicitly synthetic control-flow fixtures.
    # The actual H 65a failure and historical files are never modified or reclassified.
    subject = {'repo': '/synthetic/repository/data-only', 'source': 'commit-data-only', 'tree': 'tree-data-only'}
    git = {'head': 'synthetic-current-head', 'index_sha256': 'synthetic-current-index'}
    source_identity = {'head': subject['source'], 'tree': subject['tree'], 'status': ''}
    inventory = {'source': source_identity, 'files': [{'path': 'a.rs', 'sha256': 'synthetic-body', 'mode': 420}]}

    def run(module, *, initial_git=git, initial_inventory=inventory, final_inventory=inventory,
            current_git=git, live_error=None, initial_read_error=None):
        events, records = [], {}
        class MemorySide:
            input_pins, commands = {}, []
            def __init__(self, side):
                self.side = side
            def verify_original_inputs(self):
                events.append(self.side + '.verify_original_inputs')
                if self.side == 'm' and initial_read_error:
                    raise RuntimeError(initial_read_error)
            def jwrite(self, name, value):
                events.append(self.side + '.jwrite:' + name)
                records[self.side + '/' + name] = copy.deepcopy(value)
            def git_state(self):
                events.append(self.side + '.git_state')
                return copy.deepcopy(current_git)
            def gzrecord(self, name, raw):
                events.append(self.side + '.gzrecord:' + name)
                records[self.side + '/' + name] = raw.hex()
        obj = object.__new__(module.Admission)
        obj.m, obj.h = MemorySide('m'), MemorySide('h')
        obj.current_lock = lambda: events.append('current_lock')
        obj._verify_transport_stability = lambda: events.append('transport_stability')
        def metadata(name):
            events.append('live_metadata:' + name)
            if live_error:
                raise RuntimeError(live_error)
        obj._require_live_metadata = metadata
        obj.cfg = copy.deepcopy(subject)
        obj.initial_git = copy.deepcopy(initial_git)
        obj.initial_raw = None if initial_inventory is None else (
            initial_inventory if isinstance(initial_inventory, bytes) else json_bytes(initial_inventory))
        def current_inventory(path):
            assert str(path) == subject['repo']
            events.append('full_inventory_memory_only')
            return json_bytes(final_inventory)
        obj.inventory = types.SimpleNamespace(inventory=current_inventory)
        try:
            outcome = {'return': obj.finish()}
        except Exception as error:
            outcome = {'error_type': type(error).__name__, 'message': str(error)}
        return {'outcome': outcome, 'events': events, 'records': records}

    cases = []
    def same(name, **kwargs):
        a, b = run(old, **kwargs), run(new, **kwargs)
        assert a == b
        cases.append({'name': name, 'scope': 'synthetic memory-only fixture',
                      'old_equals_new': True, 'observed': b})
    same('known full baseline and unchanged current data still returns the identical complete result')
    same('known Git inequality remains SourceChanged', current_git={'head': 'different'})
    same('empty known Git object is not treated as an unavailable None baseline', initial_git={})
    changed_source = copy.deepcopy(inventory); changed_source['source']['head'] = 'different'
    same('known final identity mismatch remains SourceChanged even when initial_raw is None',
         initial_inventory=None, final_inventory=changed_source)
    changed_row = copy.deepcopy(inventory); changed_row['files'][0]['sha256'] = 'different'
    same('a changed physical row remains SourceChanged', final_inventory=changed_row)
    missing = copy.deepcopy(inventory); missing['files'] = []
    same('a missing original physical row remains SourceChanged', final_inventory=missing)
    duplicate = copy.deepcopy(inventory); duplicate['files'].append(copy.deepcopy(duplicate['files'][0]))
    same('duplicate current paths remain SourceChanged', final_inventory=duplicate)
    extra = copy.deepcopy(inventory); extra['files'].append({'path': 'ignored-output', 'sha256': 'extra', 'mode': 420})
    same('existing additional-physical-entry reporting stays unchanged', final_inventory=extra)
    same('earlier original-input rejection stays prior to both new classifications', initial_read_error='original input drift')
    same('complete live metadata rejection remains unchanged', live_error='complete metadata differs')
    same('non-None malformed baseline remains a JSON parse rejection', initial_inventory=b'')
    old_git_missing, new_git_missing = run(old, initial_git=None), run(new, initial_git=None)
    assert old_git_missing['outcome']['error_type'] == 'SourceChanged'
    assert new_git_missing['outcome']['error_type'] == 'InitialBaselineUnavailable'
    assert new_git_missing['events'] == old_git_missing['events']
    assert new_git_missing['records'] == old_git_missing['records']
    assert 'm/GIT_STATE.after.json' in new_git_missing['records']
    assert not any(event.startswith('live_metadata:') for event in new_git_missing['events'])
    cases.append({'name': 'unestablished Git baseline retains actual-after record then refuses equality as Unknown',
                  'scope': 'synthetic memory-only fixture', 'old': old_git_missing, 'new': new_git_missing})
    old_physical_missing, new_physical_missing = run(old, initial_inventory=None), run(new, initial_inventory=None)
    assert old_physical_missing['outcome']['error_type'] == 'TypeError'
    assert new_physical_missing['outcome']['error_type'] == 'InitialBaselineUnavailable'
    assert new_physical_missing['events'] == old_physical_missing['events']
    assert new_physical_missing['records'] == old_physical_missing['records']
    assert 'm/SOURCE_FINAL.complete.inventory.json.gz' in new_physical_missing['records']
    cases.append({'name': 'unestablished physical baseline retains final inventory and rejects before parsing None',
                  'scope': 'synthetic memory-only fixture', 'old': old_physical_missing, 'new': new_physical_missing})

    wrapper_results = []
    for filename, pin, marker, result_name, module_name in [
        ('SOURCE_WRAPPER_8607.py', '8607fa4bf00fc8cf535849de04d1eb6ff29429b3',
         'final_evidence_error', 'result', 'module'),
        ('NATIVE_WRAPPER_DE3.py', 'de3e9dc5e7eb30f47929f9e1ba9f460035a94fae',
         'full_physical_evidence_error', 'record', 'admission'),
    ]:
        raw = (WRAPPERS / filename).read_bytes()
        assert identity(raw)['git_blob'] == pin
        tree = ast.parse(raw)
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
                    and any((isinstance(n, ast.Constant) and n.value == marker)
                            or (isinstance(n, ast.keyword) and n.arg == marker) for n in ast.walk(node))]
        assert len(handlers) == 1
        exact_handler = compile(ast.Module(body=handlers[0].body, type_ignores=[]),
                                '<exact original wrapper evidence-error handler only>', 'exec')
        for state in ('unknown', 'failed', 'passed'):
            record = {'status': state}
            namespace = {result_name: record, module_name: new,
                         'error': new.InitialBaselineUnavailable('synthetic incomplete baseline')}
            exec(exact_handler, namespace)
            expected = 'unknown' if state == 'passed' else state
            assert record['status'] == expected
            assert record[marker].startswith('InitialBaselineUnavailable:')
            wrapper_results.append({'wrapper': pin, 'initial_status': state, 'after_status': record['status'],
                                    'error_class': 'InitialBaselineUnavailable', 'qualification': False})
    report = {
        'format': 'hepta-unestablished-baseline-classification-independent-peer-v1',
        'status': 'NO_CONCRETE_STATIC_BLOCKER_WITHIN_THIS_EXACT_DELTA',
        'before': identity(before), 'after': identity(after),
        'patch': identity((SOURCE / 'SOURCE_DELTA.patch').read_bytes()),
        'exact_full_inverse_equal': True, 'replacement_count': len(replacements),
        'qualified_original_functions': len(old_map), 'changed_original_functions': changed,
        'all_other_original_function_bytes_unchanged': True,
        'new_error_is_not_a_SourceChanged_subclass': True,
        'synthetic_control_flow_cases': cases, 'original_wrapper_handler_cases': wrapper_results,
        'actual_old65a_result_rewritten': False, 'current_stage_contract_changed': False,
        'H_calls': 0, 'filesystem_or_lock_methods_executed': False,
        'Admission_constructor_called': False, 'native_or_source_main_called': False,
        'not_an_execution_approval': True, 'qualification': False,
        'remaining_gate': 'Future source exact control must explicitly select and pin this successor; the historical 299c candidate and 65a failure remain unchanged.',
        'first_reviewer_attempt': 'Retained exit 1: the selector initially recognized dictionary string keys only; the unchanged native wrapper uses a keyword argument. The review selector was expanded to those two exact AST spellings. Candidate and wrappers were not modified.',
        'limitation': 'Only exact source bytes and memory-only branch outcomes were reviewed. No live source/Git/environment, staging or gate behavior was observed.'
    }
    path = OUT / 'REVIEW.json'
    with path.open('xb') as stream:
        stream.write(json_bytes(report))
    print(json.dumps({'review': identity(path.read_bytes()), 'script': identity(Path(__file__).read_bytes()),
                      'function_count': len(old_map), 'control_flow_cases': len(cases),
                      'wrapper_cases': len(wrapper_results), 'H_calls': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
