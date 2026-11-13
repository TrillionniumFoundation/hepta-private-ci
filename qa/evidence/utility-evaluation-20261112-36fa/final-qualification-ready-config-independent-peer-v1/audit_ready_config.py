#!/usr/bin/env python3
"""Pure immutable configuration review. Never import or invoke an input module."""
from pathlib import Path
from types import SimpleNamespace
import ast
import copy
import difflib
import hashlib
import json

HERE = Path(__file__).resolve().parent
PARENT = Path('/tmp/hepta-36fa-final-qualification-actual-binding-independent-peer-v1')
CODE = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(path, expected=None):
    raw = path.read_bytes()
    if expected is not None:
        assert identity(raw)['git_blob'] == expected, str(path)
    return raw


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def changes(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        assert before.keys() == after.keys(), prefix
        rows = []
        for key in sorted(before):
            rows.extend(changes(before[key], after[key], prefix + '/' + key))
        return rows
    return [] if before == after else [{'path': prefix, 'before': before, 'after': after}]


pins = {
    'QUALIFICATION_CONFIG.candidate.json': '720abbdfa96bca8c7e6aaf633a800693960d80db',
    'SOURCE_GATES_CONFIG.candidate.json': 'b97682c5a95bb7f09241e54f0b3d13bf7fa791a4',
    'EXECUTION_CONFIG_DELTA.patch': 'f8243a1399006539bf734a48c178e2bf2930d16a',
    'PERMISSION_FIELD_INVERSE_REVIEW.json': 'fbea5faf8be6a56c3491a847adc61f75674425e2',
}
get_rows = []
for name, expected in pins.items():
    raw = read(HERE / 'inputs' / name, expected)
    sdk = json.loads(read(HERE / 'github' / (name + '.GET.original.json')))
    obj = sdk['structuredContent']; obj = obj.get('structuredContent', obj)
    assert sdk.get('isError') is not True and obj['content'].encode() == raw
    get_rows.append({'name': name, **identity(raw), 'actual_full_get_equal': True})

oldq = read(PARENT / 'inputs' / 'QUALIFICATION_CONFIG.HOLD.json', '083694f6a08cb7a9fbaeea2227b2f60f8608219a')
olds = read(PARENT / 'inputs' / 'SOURCE_GATES_CONFIG.HOLD.json', '0d3c48853572dc89a823ca9afb5d5487868189e6')
newq = read(HERE / 'inputs' / 'QUALIFICATION_CONFIG.candidate.json')
news = read(HERE / 'inputs' / 'SOURCE_GATES_CONFIG.candidate.json')
bq, bs, aq, ass = map(json.loads, [oldq, olds, newq, news])
qchanges, schanges = changes(bq, aq), changes(bs, ass)
assert [row['path'] for row in qchanges] == ['/root_execution_approved', '/source_gates_config_pin/bytes',
    '/source_gates_config_pin/git_blob', '/source_gates_config_pin/sha256', '/state']
assert [row['path'] for row in schanges] == ['/state']
assert bq['root_execution_approved'] is False and aq['root_execution_approved'] is True
assert bq['state'] == bs['state'] == 'HOLD_FOR_EXACT_ROOT_QUALIFICATION_APPROVAL'
assert aq['state'] == 'READY_FOR_FINAL_SOURCE_QUALIFICATION'
assert ass['state'] == 'READY_FOR_EXACT_SOURCE_RUN'
assert aq['source_gates_config_pin'] == identity(news)
assert bq['source_gates_config_pin'] == identity(olds)
reverseq, reverses = copy.deepcopy(aq), copy.deepcopy(ass)
reverseq['state'] = bq['state']
reverseq['root_execution_approved'] = bq['root_execution_approved']
reverseq['source_gates_config_pin'] = bq['source_gates_config_pin']
reverses['state'] = bs['state']
assert encoded(reverseq) == oldq and encoded(reverses) == olds
delta = b''
for name, before, after in [('QUALIFICATION_CONFIG', oldq, newq), ('SOURCE_GATES_CONFIG', olds, news)]:
    delta += ''.join(difflib.unified_diff(before.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True), fromfile='actual-HOLD/' + name + '.HOLD.json',
        tofile='execution-candidate/' + name + '.execution-candidate.json')).encode()
assert delta == read(HERE / 'inputs' / 'EXECUTION_CONFIG_DELTA.patch')
authors = json.loads(read(HERE / 'inputs' / 'PERMISSION_FIELD_INVERSE_REVIEW.json'))
assert authors['qualification_changes'] == qchanges and authors['source_gates_changes'] == schanges

code_raw = read(CODE / 'qualification-admission.HOLD.py', 'c77e3be6230d3267c08333be582f69f23c016fb9')
wrapper_raw = read(CODE / 'inputs' / 'SOURCE_WRAPPER_8607.py', '8607fa4bf00fc8cf535849de04d1eb6ff29429b3')
tree = ast.parse(code_raw)
admission = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Admission')
constructor = next(n for n in admission.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
guard = constructor.body[0]
assert isinstance(guard, ast.Expr) and isinstance(guard.value, ast.Call) and ast.unparse(guard.value.func) == 'check'
expression = guard.value.args[0]
evaluate = lambda expr, values: eval(compile(ast.Expression(expr), '<existing-pure-data-expression-only>', 'eval'), {}, values)
assert evaluate(expression, {'cfg': bq}) is False
assert evaluate(expression, {'cfg': aq}) is True
inventory_pin = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
    and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'INVENTORY_PIN')
wrapper_tree = ast.parse(wrapper_raw)
matches = [node for node in ast.walk(wrapper_tree) if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute) and ast.unparse(node.func) == 'module.check'
    and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)
    and node.args[1].value == 'unaltered original exact-source gate inputs']
assert len(matches) == 1
wrapper_expression = matches[0].args[0]
assert evaluate(wrapper_expression, {'cfg': ass, 'INPUT': aq, 'module': SimpleNamespace(INVENTORY_PIN=inventory_pin)}) is True
assert evaluate(wrapper_expression, {'cfg': bs, 'INPUT': bq, 'module': SimpleNamespace(INVENTORY_PIN=inventory_pin)}) is False
assert aq['admission_pin'] == identity(code_raw)
assert aq['normal_native_and_source_results'] is None
assert aq['qualification_execution_dispatched'] is False and aq['not_an_execution_approval'] is True
assert ass['budgets_seconds'] == bs['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}
out = {
    'format': 'hepta-final-qualification-ready-config-independent-proof-v1',
    'status': 'EXACT_PERMISSION_BYTES_ONLY_NOT_A_DISPATCH_APPROVAL',
    'input_full_get': get_rows, 'qualification_before': identity(oldq), 'qualification_after': identity(newq),
    'source_before': identity(olds), 'source_after': identity(news),
    'qualification_changes': qchanges, 'source_changes': schanges,
    'all_keys_preserved': True, 'complete_inverse_bytes_equal': True, 'complete_diff_bytes_equal': True,
    'frozen_code': identity(code_raw), 'frozen_source_wrapper': identity(wrapper_raw),
    'existing_constructor_first_data_expression': ast.unparse(expression),
    'existing_source_wrapper_data_expression': ast.unparse(wrapper_expression),
    'data_expression_results': {'HOLD_constructor_guard': False, 'candidate_constructor_guard': True,
        'HOLD_source_input_check': False, 'candidate_source_input_check': True},
    'whole_input_modules_imported': 0, 'constructors_acquire_finish_called': 0, 'live_observers_called': 0,
    'H_calls': 0, 'native_source_gate_execution': 0, 'source_or_ref_writes': 0,
    'future_results_still_null': True, 'qualification_execution_dispatched': False,
    'qualification': False, 'execution_approval': False,
    'remaining_review': 'No typed request or bootstrap is supplied in this two-config layer. A separately frozen exact source request and Root decision are still required.',
}
path = HERE / 'EXACT_PERMISSION_DATAFLOW.json'
path.open('xb').write(encoded(out))
print(json.dumps({'proof': identity(path.read_bytes()), 'qualification_changes': 5, 'source_changes': 1,
                  'scope': 'only immutable configuration and pure expression review'}, sort_keys=True))
