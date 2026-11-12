import ast
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-after2268-20261112')
LAUNCH = Path('/tmp/hepta-36fa-final-source-qualification-launch-v1')
HOLD = Path('/tmp/hepta-36fa-final-qualification-hold-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def functions(source):
    lines = source.splitlines(keepends=True)
    return {node.name: ''.join(lines[node.lineno-1:node.end_lineno]) for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)}


def main():
    code_raw = (LAUNCH / 'ACTUAL_SOURCE_BOOTSTRAP.py').read_bytes()
    code = code_raw.decode()
    manifest_raw = (LAUNCH / 'EXACT_SOURCE_LAUNCH_MANIFEST.json').read_bytes()
    manifest = json.loads(manifest_raw)
    for row in manifest['files']:
        assert pin((LAUNCH / row['name']).read_bytes()) == {k:row[k] for k in ('bytes','sha256','git_blob')}
    original = Path('/tmp/hepta-36fa-final-canonical-alignment-plan-v1/BOOTSTRAP_TEMPLATE.HOLD.py').read_text()
    f, old = functions(code), functions(original)
    assert set(f) == {'check','identity','real_parents','retain'}
    assert all(f[name] == old[name] for name in f)
    pins = None
    for node in ast.parse(code).body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id == 'PINS':
            pins = ast.literal_eval(node.value)
    assert pins == manifest['eight_input_pins']
    expected_paths = {
        'qualification-admission.py': HOLD / 'qualification-admission.HOLD.py',
        'source-gates-wrapper.py': HOLD / 'source-gates-wrapper.HOLD.py',
        'native-wrapper.py': HOLD / 'native-wrapper.HOLD.py',
        'native-driver.original.py': HOLD / 'native-driver.original.py',
        'PLAN.original.json': Path('/tmp/hepta-36fa-exact-source-qualification-plan-v2/PLAN.json'),
        'APPROVED_QUALIFICATION_INPUT.json': ROOT / 'APPROVED_FINAL_QUALIFICATION_INPUT.json',
        'APPROVED_SOURCE_GATES_CONFIG.json': ROOT / 'APPROVED_FINAL_SOURCE_GATES_CONFIG.json',
        'CANONICAL_ALIGNMENT_NORMAL.original.json': Path('/tmp/hepta-36fa-final-canonical-alignment-launch-v1/STATUS_01.original.json'),
    }
    stdin_raw = (LAUNCH / 'ACTUAL_SOURCE_STDIN.json').read_bytes()
    payload = json.loads(stdin_raw)
    assert len(stdin_raw) <= 1048576
    assert set(payload) == {'format','files'} and payload['format'] == 'hepta-final-source-qualification-bootstrap-v1'
    assert set(payload['files']) == set(expected_paths) == set(pins)
    for name, path in expected_paths.items():
        decoded = base64.b64decode(payload['files'][name],validate=True)
        assert decoded == path.read_bytes() and pin(decoded) == pins[name]
        assert str(path) == manifest['input_local_sources'][name]
    typed_raw = (LAUNCH / 'ACTUAL_SOURCE_PROCESS_INPUT.json').read_bytes()
    typed = json.loads(typed_raw)
    assert set(typed) == {'args','cwd','executable','host','idempotency_key','stdin','timeout_seconds'}
    assert typed['host'] == 'desktop' and typed['cwd'] == '/home/qian-qi'
    assert typed['executable'] == '/usr/bin/python3' and typed['args'] == ['-B','-c',code]
    assert typed['stdin'].encode() == stdin_raw
    assert typed['idempotency_key'] == 'hepta-utility-36fa-final-source-gates-246d-v1'
    assert typed['timeout_seconds'] == manifest['outer_seconds'] == 7200
    budget_raw = (ROOT / 'ROOT_FINAL_SOURCE_OUTER_BUDGET_ADDENDUM.json').read_bytes()
    assert pin(budget_raw)['git_blob'] == 'c84d7fab51a24841090f92484ee5b90ebafd6072'
    cfg = json.loads(expected_paths['APPROVED_QUALIFICATION_INPUT.json'].read_bytes())
    scfg = json.loads(expected_paths['APPROVED_SOURCE_GATES_CONFIG.json'].read_bytes())
    assert cfg['source_gates_config_pin'] == pins['APPROVED_SOURCE_GATES_CONFIG.json']
    assert cfg['source'] == scfg['source_sha'] == manifest['source'] == '246d8cb614770252ee42029a5c014f2a4904176a'
    assert cfg['tree'] == scfg['source_tree'] == manifest['tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    assert scfg['budgets_seconds'] == manifest['original_gate_budgets'] == {'source-closure':600,'self-test':300,'verify':4800}
    assert pins['APPROVED_QUALIFICATION_INPUT.json']['git_blob'] == '83b87db774f7ce591c647fb86641bbdb4006491e'
    assert pins['source-gates-wrapper.py']['git_blob'] == '8607fa4bf00fc8cf535849de04d1eb6ff29429b3'
    top = ast.parse(code).body
    exec_nodes = [node for node in top if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
                  and isinstance(node.value.func,ast.Name) and node.value.func.id == 'exec']
    assert len(exec_nodes) == 1 and exec_nodes[0] is top[-1]
    assert ast.unparse(exec_nodes[0].value.args[0]) == "compile(files['source-gates-wrapper.py'], str(source_wrapper_path), 'exec')"
    report = {
        'format':'hepta-root-final-source-qualification-exact-launch-review-v1',
        'status':'APPROVED_ONE_EXACT_SOURCE_QUALIFICATION_REQUEST',
        'source':cfg['source'],'tree':cfg['tree'],
        'bootstrap':pin(code_raw),'stdin':pin(stdin_raw),'typed_request':pin(typed_raw),
        'manifest':pin(manifest_raw),'eight_original_inputs':pins,
        'idempotency_key':typed['idempotency_key'],'outer_seconds':7200,
        'original_source_gate_seconds':scfg['budgets_seconds'],
        'actual_original_outer_budget_addendum':pin(budget_raw),
        'root_input_approval':'09b8c0ed0737013a1265548c627c35cd46d86a22',
        'reviewed_staging':'Root read the complete6316-byte bootstrap; four original helper functions are byte-identical. Eight pinned inputs are staged create-only under the exact new private external control directory with whole readback and fsync. No source file is written by staging.',
        'execution':'After staging, only original source wrapper8607 executes once outside the staging exception handler. Its original5118 main creates the fresh shared/no-hardlinks clone, freezes it, inventories it and runs all original source gates with their own unchanged failure/retention rules.',
        'preserved_controls':'Actual format/alignment proofs, original V5 environment,32GiB floor,unchanged live build guard and actual SH lock; source controls/original assertions,5118,b92,recorders,phase limits and8MiB stack remain pinned.',
        'native_wrapper':'Pinned file is staged for later review only. This request does not execute native wrapper, Cargo tests, fix or formatter.',
        'dispatch_authorization':'One exact seven-field7200-second request after native verifies Git readbacks. Admission uncertainty permits only reconciliation of the same exact key and request; no automatic new attempt.',
        'next_native_dispatch':'Only after complete original source wrapper outcomes and authoritative terminal are collected, and Root separately reviews the exact native request.',
        'qualification_result':None,'real_qualified_task_chain_results':0,
    }
    raw = (json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
    path = ROOT / 'ROOT_FINAL_SOURCE_EXACT_LAUNCH_REVIEW.json'
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    print(json.dumps(pin(raw),sort_keys=True,indent=2))


if __name__ == '__main__':
    main()
