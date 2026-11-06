from pathlib import Path
import ast, difflib, hashlib, json
B = Path('/workspace/scratch/08f5efd48967')
D = B / 'r29-export-preparation'
old_path = B / 'r28-export-preparation/export-r28-closed-template-v2.py'
runner_path = B / 'native-validation-results/r29-bound-input/native-run-r29.py'
old_raw, runner_raw = old_path.read_bytes(), runner_path.read_bytes()
assert hashlib.sha256(old_raw).hexdigest() == '4568d25b1d122e209ce59d9f1a4015e65ca77246f23b2ece4f86b07a6398d4d8'
assert hashlib.sha256(runner_raw).hexdigest() == '26bb2c31806895b19410f290e1f20232ee3be2dbe09321e081857dddefac1fa2'
old, runner = old_raw.decode(), runner_raw.decode()
old_tree, runner_tree = ast.parse(old), ast.parse(runner)
of = {n.name: ast.get_source_segment(old,n) for n in old_tree.body if isinstance(n,ast.FunctionDef)}
rf = {n.name: ast.get_source_segment(runner,n) for n in runner_tree.body if isinstance(n,ast.FunctionDef)}
header = old[:old.index('\ndef require(')]
replacements = {
    'Closed r28 evidence exporter.': 'Closed r29 workspace evidence exporter.',
    "PREFIX = 'native-source52-project-r28'": "PREFIX = 'native-workspace-r29'",
    "JOB_ID = '1a1b1e9bee0-fc05-7b7c'": "JOB_ID = '1a1b1f83e4b-fc05-7bcd'",
    "RUNNER_PIN = {'bytes':54455,'sha256':'a7b64eb8ff8ec2b5bc75ae836e3ff423ce31ee86d5c4daf64b7543a8fa7aae9e','git_blob':'9f1a10e6eb0998b9c5e297a2d0a5382f0a289f0d'}":
        "RUNNER_PIN = {'bytes':82985,'sha256':'26bb2c31806895b19410f290e1f20232ee3be2dbe09321e081857dddefac1fa2','git_blob':'c67a237136a0fcf28c0c001ea71fd5262f70e888'}",
    "CONTROLLER_PREFIX = 'r28-controller-closed-'": "CONTROLLER_PREFIX = 'r29-controller-closed-'",
    "OUT = E / 'checkpoint-r28-closed.tar.gz'": "OUT = E / 'checkpoint-r29-closed.tar.gz'",
    "DERIVED = E / 'r28-closed-export'": "DERIVED = E / 'r29-closed-export'",
    "RESULT = E / 'checkpoint-r28-export.json'": "RESULT = E / 'checkpoint-r29-export.json'",
}
for before, after in replacements.items():
    assert header.count(before) == 1, before
    header = header.replace(before, after)
header += "\nEXPECTED_TREE = TREE\nEXPECTED_COMMIT = COMMIT\n"
header += "COMMAND = ['just', 'test', '--locked', '--retries', '0']\n"
header += "METADATA_COMMAND = ['cargo', 'metadata', '--locked', '--no-deps', '--format-version', '1']\n"
header += "R28_PREFIX = 'native-source52-project-r28'\nR28_JOB_ID = '1a1b1e9bee0-fc05-7b7c'\n"
header += "R28_RUNNER_PIN = {'bytes':54455,'sha256':'a7b64eb8ff8ec2b5bc75ae836e3ff423ce31ee86d5c4daf64b7543a8fa7aae9e','git_blob':'9f1a10e6eb0998b9c5e297a2d0a5382f0a289f0d'}\n"
common = ['require','sha','data_pin','safe_relative','check_pin','check_bindings','stable_read','git','source_guard','recorded_guard','natural_terminal','clean_lines']
code = header.rstrip() + '\n\n\n' + '\n\n\n'.join(of[name] for name in common)
code += '\n\n\n' + rf['review_workspace'] + '\n\n\n' + (D / 'export-body.py.txt').read_text().rstrip() + '\n'
tree = ast.parse(code)
fn = {n.name: ast.get_source_segment(code,n) for n in tree.body if isinstance(n,ast.FunctionDef)}
assert all(fn[name] == of[name] for name in common)
assert fn['review_workspace'] == rf['review_workspace']
values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
          and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
          and isinstance(n.value,(ast.Constant,ast.Dict,ast.List))}
assert values['FROZEN'] is False
assert all(values[name] is None for name in ('TERMINAL_PIN','CLOSED_ORIGINAL_PINS','CONTROLLER_ORIGINAL_PINS'))
assert len([v for v in values.values() if v is None]) == 3
for n in ast.walk(tree):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess':
        assert n.func.attr=='check_output', ast.dump(n)
def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
p = D / 'export-r29-closed-template.py'
with p.open('xb') as output: output.write(code.encode())
patch = ''.join(difflib.unified_diff(old.splitlines(keepends=True),code.splitlines(keepends=True),
                                   fromfile='r28-export-preparation/export-r28-closed-template-v2.py',
                                   tofile='r29-export-preparation/export-r29-closed-template.py'))
with (D / 'r28-v2-to-r29.patch').open('x') as output: output.write(patch)
report = {
    'schema':'hepta.r29-export-inert-ast-readback.v1',
    'template':{'path':str(p),**pin(code.encode())},
    'source_r28_v2':{'path':str(old_path),**pin(old_raw)},
    'source_r29_actual_runner':{'path':str(runner_path),**pin(runner_raw)},
    'ast_parse':'PASS','common_export_functions_exact':common,
    'actual_workspace_parser_exact':True,
    'unknown_maps':['TERMINAL_PIN','CLOSED_ORIGINAL_PINS','CONTROLLER_ORIGINAL_PINS'],
    'FROZEN':False,'script_imported_or_executed':False,'native_read_or_write':False,
    'rust_or_formatter_executed':False,
    'only_subprocess_api':'subprocess.check_output in Git read allowlist',
    'fixed_actual_source':{'commit':values['COMMIT'],'tree':values['TREE'],'job':values['JOB_ID']},
    'change_scope':['r29 natural terminal and current-source raw original pins',
                    'actual fresh193 metadata/scope original readback; never rerun metadata',
                    'original no-p raw rc/receipt/resources/guards and complete/incomplete',
                    'actual r29 parser byte reuse; compile failure has null terminal counts',
                    'r28 original26 prerequisites archived by their fixed precondition pins',
                    'current195source/HEAD/dual locks checked before and after',
                    'create-only archive/derived files, full byte readback'],
}
raw=(json.dumps(report,indent=2)+'\n').encode()
with (D / 'AST-READBACK.json').open('xb') as output:output.write(raw)
print(json.dumps({'template':pin(code.encode()),'report':pin(raw),'common_functions':len(common),'unknown_maps':3}))
