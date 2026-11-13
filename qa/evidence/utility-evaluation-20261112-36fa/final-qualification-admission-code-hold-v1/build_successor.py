"""Pure source/data generation; never imports the original controls or runs gates."""
from pathlib import Path
import ast
import copy
import difflib
import hashlib
import json
import pprint
import textwrap

BASE = Path(__file__).resolve().parent
INPUT = BASE / 'inputs'
SPEC = Path('/tmp/hepta-36fa-final-qualification-admission-successor-hold-v1')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(name):
    return json.loads((INPUT / name).read_bytes())


def write(name, raw):
    (BASE / name).write_bytes(raw)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def source_span(raw, node):
    lines = raw.splitlines(keepends=True)
    start = min([node.lineno] + [item.lineno for item in getattr(node, 'decorator_list', [])])
    return ''.join(lines[start-1:node.end_lineno])


def main():
    original = (INPUT / 'ADMISSION_23D412.original.py').read_text()
    assert identity(original.encode())['git_blob'] == '23d412ed67927a6cbfa5f521884e891afc93eb6f'
    cfg = json.loads((SPEC / 'QUALIFICATION_BINDINGS.HOLD.json').read_bytes())
    runtime = copy.deepcopy(cfg['runtime_guard'])
    control_root = Path('/home/qian-qi/hepta-utility-36fa-evidence')
    material = control_root / 'provider-coordinator-a489-isolated-materialization-v1'
    maintenance = control_root / 'provider-coordinator-a489-maintenance-v1'
    final = control_root / 'provider-coordinator-a489-final-nonrust-format-v1'
    canonical = control_root / 'provider-coordinator-a489-final-canonical-alignment-v1'
    archive = control_root / 'v8-single-archive-restore-v3' / 'run'
    names = {
        'MATERIALIZER_3BB': ('MATERIALIZER_3BB.original.py', material / 'driver.py'),
        'MATERIALIZATION_3BB_PACKET': ('MATERIALIZATION_3BB_PACKET.json', material / 'MATERIALIZATION_PACKET.json'),
        'MATERIALIZATION_3BB_CONFIG': ('MATERIALIZATION_3BB_CONFIG.json', material / 'APPROVED_CONFIG.json'),
        'MATERIALIZATION_3BB_COMMANDS': ('MATERIALIZATION_3BB_COMMANDS.json', material / 'run' / 'COMMANDS.json'),
        'MATERIALIZATION_3BB_MUTATION_INTENTS': ('MATERIALIZATION_3BB_MUTATION_INTENTS.json', material / 'run' / 'MUTATION_INTENTS.json'),
        'MATERIALIZATION_3BB_INPUT_IDENTITIES': ('MATERIALIZATION_3BB_INPUT_IDENTITIES.json', material / 'run' / 'INPUT_IDENTITIES.before.json'),
        'MATERIALIZATION_3BB_ARTIFACTS': ('MATERIALIZATION_3BB_ARTIFACTS.json', material / 'run' / 'ARTIFACTS.json'),
        'MAINTENANCE_41E_DRIVER': ('MAINTENANCE_41E.original.py', maintenance / 'driver-maintenance.py'),
        'MAINTENANCE_41E_CONFIG': ('MAINTENANCE_41E_CONFIG.json', maintenance / 'APPROVED_MAINTENANCE_CONFIG.json'),
        'MAINTENANCE_41E_INPUT_IDENTITIES': ('MAINTENANCE_41E_INPUT_IDENTITIES.json', maintenance / 'run' / 'INPUT_IDENTITIES.json'),
        'MAINTENANCE_41E_ARTIFACTS': ('MAINTENANCE_41E_ARTIFACTS.json', maintenance / 'run' / 'ARTIFACTS.json'),
        'ARCHIVE_V3_READBACK': ('ARCHIVE_V3_READBACK.json', archive / 'ARCHIVE_READBACK.json'),
        'ARCHIVE_V3_ARTIFACTS': ('ARCHIVE_V3_ARTIFACTS.json', archive / 'ARTIFACTS.json'),
        'HISTORICAL_ENVIRONMENT_READY': ('HISTORICAL_ENVIRONMENT_READY.json', Path(runtime['runtime_restoration']['environment_path'])),
        'FINAL_FORMAT_DRIVER': ('FINAL_NONRUST_TEMPLATE_27C0.HOLD.py', final / 'driver.py'),
        'FINAL_FORMAT_CONFIG': ('FINAL_NONRUST_CONFIG.execution-candidate.json', final / 'APPROVED_CONFIG.json'),
        'FINAL_FORMAT_ARTIFACTS': ('FINAL_FORMAT_50F_ARTIFACTS.json', final / 'run' / 'ARTIFACTS.json'),
    }
    fixed = {name: {'path': str(path), 'pin': identity((INPUT / filename).read_bytes())}
             for name, (filename, path) in names.items()}
    final_proof = {
        'job_id': '1a1d4a979d9-392-50f', 'result_path': str(final / 'run' / 'RESULT.json'),
        'result': identity((INPUT / 'FINAL_FORMAT_50F_RESULT.json').read_bytes()),
        'supervisor_path': str(canonical / 'FINAL_FORMAT_NORMAL.original.json'),
        'supervisor': identity((INPUT / 'FINAL_FORMAT_50F_NORMAL.json').read_bytes()),
    }
    known_proofs = {'materialization': cfg['isolated_materialization'], 'maintenance': cfg['actual_maintenance'],
                    'archive': cfg['archive_restoration'], 'runtime': runtime['runtime_restoration'],
                    'final_format': final_proof}
    known_proofs = {name: {key: value[key] for key in (
        'job_id', 'result_path', 'result', 'supervisor_path', 'supervisor')}
                    for name, value in known_proofs.items()}
    source = read('MATERIALIZATION_3BB_PACKET.json')
    final_result = read('FINAL_FORMAT_50F_RESULT.json')
    maintenance_result = read('MAINTENANCE_41E_RESULT.json')
    final_subject = {'commit': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
                     'tree': '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638',
                     'parents': ['d25675445c39f76db69a7bd8e71a1a72e1cd5b9f']}
    marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
    workflow = (INPUT / 'WORKFLOW_D256.yml').read_text()
    assert workflow.count(marker) == 1
    embedded = textwrap.dedent(workflow.split(marker, 1)[1].split('          PY\n', 1)[0])
    workflow_constants = {}
    for node in ast.parse(embedded).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], 'id', None)
            if name in ('parents', 'packages'):
                assert name not in workflow_constants
                workflow_constants[name] = ast.literal_eval(node.value)
    assert len(workflow_constants['parents']) == len(set(workflow_constants['parents'])) == 48
    override = copy.deepcopy(cfg['source_control_pin_overrides'][0])
    override['final_actual_confirmed'] = True
    constants = {
        'HISTORICAL_REPO': cfg['historical_source_repo'], 'DONOR_REPO': cfg['provenance_donor_repo'],
        'CURRENT_REPO': cfg['repo'], 'MATERIALIZED_SUBJECT': cfg['materialized_subject'],
        'DONOR_SUBJECT': {key: source['donor'][key] for key in ('commit', 'tree', 'parents')},
        'FINAL_SUBJECT': final_subject, 'RUNTIME_GUARD': runtime, 'COORDINATION_LOCK': cfg['coordination_lock'],
        'FIXED_INPUTS': fixed, 'ACTUAL_PROOFS': known_proofs,
        'MATERIALIZATION_RECORDS': {'command_records': 'MATERIALIZATION_3BB_COMMANDS',
            'mutation_records': 'MATERIALIZATION_3BB_MUTATION_INTENTS',
            'input_records': 'MATERIALIZATION_3BB_INPUT_IDENTITIES', 'artifact_records': 'MATERIALIZATION_3BB_ARTIFACTS'},
        'ARCHIVE_ACTUAL': read('ARCHIVE_V3_READBACK.json'),
        'MATERIALIZED_GIT_STATE': read('MAINTENANCE_41E_GIT_STATE.json'),
        'MATERIALIZED_GIT_PIN': identity((INPUT / 'MAINTENANCE_41E_GIT_STATE.json').read_bytes()),
        'MAINTENANCE_METADATA_PIN': identity((INPUT / 'MAINTENANCE_41E_GIT_METADATA.json').read_bytes()),
        'MAINTENANCE_FINAL_PIN': maintenance_result['actual_final_source']['inventory'],
        'MAINTENANCE_TREE': maintenance_result['actual_final_source']['postimages']['all_actual_physical_tree'],
        'FINAL_FORMAT_PIN': final_result['actual_final_source']['inventory'],
        'FINAL_NONRUST_PATHS': final_result['applied_paths'],
        'CANONICAL_DRIVER_PIN': identity((INPUT / 'CANONICAL_TEMPLATE_E8D606.HOLD.py').read_bytes()),
        'ORIGINAL_ORDINARY_PACKAGES': workflow_constants['packages'], 'WORKFLOW_OVERRIDE_READY': override,
        'FIX_ARGV': maintenance_result['stages'][0]['argv'], 'FMT_ARGV': maintenance_result['stages'][1]['argv'],
    }
    constant_text = '\n'.join(name + ' = ' + pprint.pformat(value, width=110, sort_dicts=True)
                              for name, value in constants.items()) + '\n'
    for name, value in [('MATERIALIZATION_CONTROL', material), ('MAINTENANCE_CONTROL', maintenance),
                         ('FINAL_FORMAT_CONTROL', final), ('CANONICAL_CONTROL', canonical)]:
        constant_text += name + ' = Path(' + repr(str(value)) + ')\n'
    start = original.index("HISTORICAL_REPO = ")
    end = original.index('\n\n\nclass SourceChanged', start)
    new = original[:start] + constant_text.rstrip() + original[end:]
    new = new.replace('from pathlib import Path\n', 'from pathlib import Path\nimport ast\nimport io\nimport textwrap\n', 1)
    methods_raw = (BASE / 'successor_methods.py').read_text()
    methods_class = next(node for node in ast.parse(methods_raw).body if isinstance(node, ast.ClassDef))
    replacements = {node.name: source_span(methods_raw, node) for node in methods_class.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    changed = {'__init__', 'acquire_and_validate', 'validate_materialization', 'finish'}
    original_class = next(node for node in ast.parse(original).body if isinstance(node, ast.ClassDef) and node.name == 'Admission')
    for node in original_class.body:
        if isinstance(node, ast.FunctionDef) and node.name in changed:
            before = source_span(original, node)
            assert new.count(before) == 1
            new = new.replace(before, replacements[node.name], 1)
    new += '\n\n' + '\n\n'.join(raw for name, raw in replacements.items() if name not in changed) + '\n'
    helpers_raw = (BASE / 'successor_helpers.py').read_text()
    helpers = '\n\n'.join(source_span(helpers_raw, node) for node in ast.parse(helpers_raw).body
                          if isinstance(node, ast.FunctionDef))
    assert new.count('\nclass Admission:\n') == 1
    new = new.replace('\nclass Admission:\n', '\n' + helpers + '\n\n\nclass Admission:\n', 1)
    ast.parse(new)
    write('qualification-admission.HOLD.py', new.encode())
    write('ADMISSION_DELTA.patch', ''.join(difflib.unified_diff(original.splitlines(True), new.splitlines(True),
        fromfile='admission23d412.original.py', tofile='qualification-admission.HOLD.py')).encode())
    cfg['expected_canonical_subject'] = final_subject
    cfg['final_format'].update(final_proof)
    cfg['final_format'].update({
        'actual_physical_tree': final_subject['tree'], 'complete_git_metadata': constants['MAINTENANCE_METADATA_PIN'],
        'final_inventory': constants['FINAL_FORMAT_PIN'], 'git_state': constants['MATERIALIZED_GIT_PIN'],
        'artifacts': identity((INPUT / 'FINAL_FORMAT_50F_ARTIFACTS.json').read_bytes()),
        'artifacts_path': str(final / 'run' / 'ARTIFACTS.json')})
    cfg['reviewed_formatter_changed_paths'] = []
    cfg['canonical_alignment'].update({key: None for key in (
        'before_git_metadata_raw', 'complete_entry_delta', 'allowed_metadata_delta', 'commands', 'progress',
        'inputs', 'approved_config', 'canonical_packet')})
    cfg['admission_pin'] = identity(new.encode())
    cfg['admission_path'] = None
    cfg['qualification_execution_dispatched'] = False
    cfg['not_an_execution_approval'] = True
    cfg['prepared_canonical_commit_is_not_actual_alignment'] = True
    write('QUALIFICATION_CONFIG.HOLD.json', encoded(cfg))
    write('SOURCE_GATES_CONFIG.HOLD.json', (SPEC / 'SOURCE_GATES_CONFIG.HOLD.json').read_bytes())
    old_tree, new_tree = ast.parse(original), ast.parse(new)
    def definitions(text, tree):
        result = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef): result[node.name] = source_span(text, node)
            if isinstance(node, ast.ClassDef) and node.name == 'Admission':
                for child in node.body:
                    if isinstance(child, ast.FunctionDef): result['Admission.' + child.name] = source_span(text, child)
        return result
    old_defs, new_defs = definitions(original, old_tree), definitions(new, new_tree)
    changed_full = {'Admission.' + name for name in changed}
    assert len(old_defs) == 13
    rows = []
    for name, before in old_defs.items():
        after = new_defs[name]
        same = before == after
        assert same == (name not in changed_full)
        rows.append({'name': name, 'disposition': 'byte-identical' if same else 'explicit migration',
                     'before': identity(before.encode()), 'after': identity(after.encode()),
                     'ast_identical': ast.dump(ast.parse(textwrap.dedent(before)), include_attributes=False)
                                      == ast.dump(ast.parse(textwrap.dedent(after)), include_attributes=False)})
    write('ORIGINAL_FUNCTION_PRESERVATION.json', encoded({'format': 'hepta-admission-thirteen-function-migration-v1',
        'original': identity(original.encode()), 'candidate': identity(new.encode()), 'original_definitions': 13,
        'unchanged_original_definitions': 9, 'explicitly_migrated_original_definitions': 4,
        'new_helpers': sorted(set(new_defs)-set(old_defs)), 'functions': rows,
        'no_original_driver_or_wrapper_modified': True, 'execution_dispatched': False}))
    write('FIXED_INPUT_BINDINGS.json', encoded({'inputs': fixed, 'actual_proofs': known_proofs,
        'native_path_provenance': 'Original pinned input maps and producer templates; no new host observation.',
        'expected_canonical_subject': final_subject, 'actual_canonical': None}))
    write('GENERATED_CONSTANTS.json', encoded(constants))
    write('EXACT_WORKFLOW_PARENT_BINDINGS.json', encoded({'workflow': identity(workflow.encode()),
        'original_plan': identity((INPUT/'PLAN_3AEF.json').read_bytes()), 'constants': workflow_constants,
        'scope': 'Full workflow pin fixes these exact 48 names; runtime uses the original AST extraction and unchanged b92 JUnit checks.'}))
    print(json.dumps({'candidate': identity(new.encode()), 'config': identity((BASE/'QUALIFICATION_CONFIG.HOLD.json').read_bytes()),
                      'preserved_functions': 9, 'migrated_functions': 4, 'actual_canonical': None}))


if __name__ == '__main__':
    main()
