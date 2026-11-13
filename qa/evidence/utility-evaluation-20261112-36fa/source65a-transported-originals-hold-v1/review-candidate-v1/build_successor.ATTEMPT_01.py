#!/usr/bin/env python3
"""Build reviewed-input candidates only. Never import or run a gate/guard/stager."""
from pathlib import Path
import ast
import base64
import copy
import difflib
import hashlib
import json
import pprint

HERE = Path(__file__).resolve().parent
OLD = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')
CFG = Path('/tmp/hepta-36fa-final-qualification-admission-execution-candidate-v1')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def jbytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

def retain(name, raw):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ('create-only candidate conflict', str(path))
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), **identity(raw)}

def replace_once(source, before, after):
    assert source.count(before) == 1, ('one exact replacement', before[:120], source.count(before))
    return source.replace(before, after)

def definitions(source):
    lines = source.splitlines(keepends=True)
    result = {}
    def visit(node, prefix=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min([child.lineno] + [item.lineno for item in child.decorator_list])
                    result[name] = ''.join(lines[start-1:child.end_lineno])
                visit(child, name + '.')
            else:
                visit(child, prefix)
    visit(ast.parse(source))
    return result

def diff(name, old, new):
    return retain(name, ''.join(difflib.unified_diff(old.splitlines(keepends=True),
                  new.splitlines(keepends=True), fromfile='original', tofile='HOLD-successor')).encode())

def constants(values):
    return '\n'.join(name + ' = ' + pprint.pformat(value, sort_dicts=True, width=110)
                     for name, value in values.items()) + '\n'

def main():
    manifest_raw = (HERE / 'TRANSPORT_MANIFEST.HOLD.json').read_bytes()
    manifest = json.loads(manifest_raw)
    transport, source_control = manifest['control'], manifest['source_control']
    rows = {row['role']: row for row in manifest['rows']}
    role_by_path = {row['original_path']: row['role'] for row in manifest['rows']}
    manifest_path = transport + '/TRANSPORT_MANIFEST.json'
    hguard_path = transport + '/historical-runtime-guard.py'
    stages = json.loads((HERE / 'STAGING_WRITE_MANIFEST.HOLD.json').read_bytes())
    parts = [{'path': row['native_path'], 'pin': row['decoded_pin']} for row in stages['writes']]
    original_v5 = (OLD / 'inputs/V5_GUARD_6632.original.py').read_text()
    old_v5_pin = identity(original_v5.encode())
    assert old_v5_pin['git_blob'] == '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'
    hroles = {name: rows[name] for name in (
        'runtime.result', 'runtime.supervisor', 'runtime.environment_ready', 'historical_environment.started')}
    hconstants = constants({'HISTORY_TRANSPORT_CONTROL': transport,
                           'HISTORY_MANIFEST_PATH': manifest_path,
                           'HISTORY_MANIFEST_PIN': identity(manifest_raw),
                           'HISTORY_RUNTIME_ROLES': hroles})
    hfunctions = (HERE / 'historical_v5_transport_functions.py').read_text()
    hinsertion = hconstants + '\n' + hfunctions + '\n\n'
    hguard = replace_once(original_v5, 'def validate_runtime_restoration():', hinsertion + 'def validate_runtime_restoration():')
    replacements = [
        ('    raw=read_input(proof["result_path"],proof["result"])',
         '    raw=read_transported_historical_input("runtime.result",proof["result_path"],proof["result"])'),
        ('    terminal_raw=read_input(proof["supervisor_path"],proof["supervisor"])',
         '    terminal_raw=read_transported_historical_input("runtime.supervisor",proof["supervisor_path"],proof["supervisor"])'),
        ('    environment_raw=read_input(proof["environment_path"],proof["environment"])',
         '    environment_raw=read_transported_historical_input("runtime.environment_ready",proof["environment_path"],proof["environment"])'),
        ('    historical=parse(read_input(ENVIRONMENT_FILE,HISTORICAL_ENV_PIN,100000))',
         '    historical=parse(read_transported_historical_input("historical_environment.started",ENVIRONMENT_FILE,HISTORICAL_ENV_PIN,100000))'),
    ]
    for before, after in replacements:
        hguard = replace_once(hguard, before, after)
    restored = hguard
    for before, after in reversed(replacements):
        restored = replace_once(restored, after, before)
    restored = replace_once(restored, hinsertion, '')
    assert restored == original_v5
    old_defs, new_defs = definitions(original_v5), definitions(hguard)
    changed_v5 = [name for name in old_defs if old_defs[name] != new_defs[name]]
    assert changed_v5 == ['validate_runtime_restoration', 'environment_preflight']
    hpin = retain('historical-runtime-guard.HOLD.py', hguard.encode())
    hdiff = diff('HISTORICAL_V5_FROM_6632.patch', original_v5, hguard)
    template = (HERE / 'transport_stager.template.py').read_text()
    stageconstants = ('BASE = pathlib.Path(' + repr(transport) + ')\n'
                     'ORIGINALS = BASE / "originals"\n') + constants({
                         'MANIFEST_PIN': identity(manifest_raw), 'HISTORICAL_GUARD_PIN': identity(hguard.encode()),
                         'PACKET_PIN': stages['packet'], 'GZIP_PIN': stages['gzip'], 'PART_INPUTS': parts,
                         'ORIGINAL_NAMES': [row['role'] + '.original' for row in manifest['rows']]})
    stager = replace_once(template, '# FROZEN_CONSTANTS\n', stageconstants)
    compile(stager, 'TRANSPORT_STAGER.HOLD.py', 'exec')
    stagepin = retain('TRANSPORT_STAGER.HOLD.py', stager.encode())
    stageargv = ['/usr/bin/python3', '-B', '-c', stager]
    argvpin = identity(jbytes(stageargv))
    stagecfg = {'format': 'hepta-closed-history-transport-staging-input-v1',
                'status': 'HOLD_ROOT_EXACT_REVIEW_REQUIRED', 'root_execution_approved': False,
                'manifest_base64': base64.b64encode(manifest_raw).decode(),
                'historical_guard_base64': base64.b64encode(hguard.encode()).decode()}
    stdin = jbytes(stagecfg)
    assert len(stdin) <= 1048576
    retain('STAGING_INPUT.HOLD.json', stdin)
    stage_request = {'host': 'desktop', 'executable': '/usr/bin/python3', 'args': ['-B', '-c', stager],
                     'cwd': '/home/qian-qi', 'stdin': stdin.decode(),
                     'idempotency_key': 'hepta-utility-36fa-final-b608-transported-originals-staging-v1',
                     'timeout_seconds': 900}
    stage_typed = jbytes(stage_request)
    assert len(stage_typed) <= 1048576 and 'env' not in stage_request
    stage_request_pin = retain('STAGING_PROCESS_INPUT.HOLD.json', stage_typed)
    admission = (OLD / 'qualification-admission.HOLD.py').read_text()
    original_admission = admission
    assert identity(admission.encode())['git_blob'] == 'c77e3be6230d3267c08333be582f69f23c016fb9'
    literal_fixed = next(ast.literal_eval(node.value) for node in ast.parse(admission).body
                         if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name)
                         and n.id == 'FIXED_INPUTS' for n in node.targets))
    fixed_roles = {name: role_by_path[value['path']] for name, value in literal_fixed.items()}
    artifact_roles = {row['original_path']: row['role'] for row in manifest['rows']
                      if any(consumer.startswith('captured ARTIFACTS + _artifact:')
                             for consumer in row['original_consumers'])}
    newconstants = constants({
        'HISTORY_EVIDENCE_PARENT': '/home/qian-qi/hepta-utility-36fa-evidence',
        'HISTORY_TRANSPORT_CONTROL': transport, 'SOURCE_TRANSPORT_CONTROL': source_control,
        'HISTORY_MANIFEST_PATH': manifest_path, 'HISTORY_MANIFEST_PIN': identity(manifest_raw),
        'HISTORY_ROLES': [row['role'] for row in manifest['rows']],
        'HISTORY_RUNTIME_GUARD_PATH': hguard_path, 'HISTORY_RUNTIME_GUARD_PIN': identity(hguard.encode()),
        'HISTORY_STAGER_PIN': identity(stager.encode()), 'HISTORY_STAGER_ARGV_PIN': argvpin,
        'HISTORY_PACKET_PIN': stages['packet'], 'HISTORY_GZIP_PIN': stages['gzip'], 'HISTORY_PART_INPUTS': parts,
        'HISTORY_PROOF_ROLES': {'CANONICAL_ALIGNMENT': ['canonical.result', 'canonical.supervisor'],
            'ISOLATED_MATERIALIZATION': ['materialization.result', 'materialization.supervisor'],
            'ARCHIVE_V3': ['archive.result', 'archive.supervisor'],
            'MAINTENANCE_41E': ['maintenance.result', 'maintenance.supervisor'],
            'FINAL_FORMAT': ['final_format.result', 'final_format.supervisor']},
        'HISTORY_FIXED_ROLES': fixed_roles, 'HISTORY_ARTIFACT_ROLES': artifact_roles,
    })
    admission = replace_once(admission, 'class SourceChanged(RuntimeError):',
                              newconstants + '\n\nclass SourceChanged(RuntimeError):')
    ops = [
      ("        self._require_complete_bindings(cfg)\n", "        self._require_complete_bindings(cfg)\n        self._require_transport_bindings(cfg)\n"),
      ("        self._fixed_raw = {}\n", "        self._fixed_raw = {}\n        self._transport_stats = {}\n"),
      ("        self.h = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_historical_runtime_environment')",
       "        self.h = load(cfg['historical_runtime_guard_path'], HISTORY_RUNTIME_GUARD_PIN, 'fixed_history_transport_v5_historical_runtime_environment')"),
      ("        # Keep the historical module, including its 86dd SEED, completely original.",
       "        # Keep all historical subjects and guard statements; only four closed historical read locations differ."),
      ("        self.h.read_input(cfg['maintenance_guard_path'], V5_PIN)\n",
       "        self.h.read_input(cfg['maintenance_guard_path'], V5_PIN)\n        self.h.read_input(cfg['historical_runtime_guard_path'], HISTORY_RUNTIME_GUARD_PIN)\n        self._history_rows = self._load_transport_manifest()\n"),
      ("        original = self.read(value['result_path'], value['result'], prefix + '.RESULT.original.json')\n        raw = self.m.read_input(value['supervisor_path'], value['supervisor'])",
       "        check(prefix in HISTORY_PROOF_ROLES, 'fixed historical result/supervisor role pair')\n        result_role, supervisor_role = HISTORY_PROOF_ROLES[prefix]\n        original = self.read_historical(result_role, value['result_path'], value['result'], prefix + '.RESULT.original.json')\n        raw = self._read_historical(supervisor_role, value['supervisor_path'], value['supervisor'])"),
      ("        plan = self.read(cfg['plan_path'], PLAN_PIN, 'PLAN.original.json')",
       "        self._require_transport_staging()\n        plan = self.read(cfg['plan_path'], PLAN_PIN, 'PLAN.original.json')"),
      ("            raw = self.m.read_input(spec['path'], spec['pin'])",
       "            raw = self._read_historical(HISTORY_FIXED_ROLES[name], spec['path'], spec['pin'])"),
      ("        raw = self.m.read_input(Path(root) / name, pin_fields(row))",
       "        original_path = str(Path(root) / name)\n        check(original_path in HISTORY_ARTIFACT_ROLES, 'one fixed original artifact role')\n        raw = self._read_historical(HISTORY_ARTIFACT_ROLES[original_path], original_path, pin_fields(row))"),
      ("        m.read_input(CANONICAL_CONTROL / 'driver.py', CANONICAL_DRIVER_PIN)",
       "        self._read_historical('canonical.driver', CANONICAL_CONTROL / 'driver.py', CANONICAL_DRIVER_PIN)"),
      ("        control = self.read(CANONICAL_CONTROL / 'APPROVED_CONFIG.json', proof['approved_config'], 'CANONICAL_CONFIG.original.json')",
       "        control = self.read_historical('canonical.config', CANONICAL_CONTROL / 'APPROVED_CONFIG.json', proof['approved_config'], 'CANONICAL_CONFIG.original.json')"),
      ("        m.read_input(CANONICAL_CONTROL / 'CANONICAL_PACKET.json', proof['canonical_packet'])",
       "        self._read_historical('canonical.packet', CANONICAL_CONTROL / 'CANONICAL_PACKET.json', proof['canonical_packet'])"),
      ("        artifacts = self.read(CANONICAL_CONTROL / 'run' / 'ARTIFACTS.json', proof['artifacts'], 'CANONICAL_ARTIFACTS.original.json')",
       "        artifacts = self.read_historical('canonical.artifacts', CANONICAL_CONTROL / 'run' / 'ARTIFACTS.json', proof['artifacts'], 'CANONICAL_ARTIFACTS.original.json')"),
      ("        commands = self.read(root / 'COMMANDS.json', proof['commands'], 'CANONICAL_COMMANDS.original.json')",
       "        commands = self.read_historical('canonical.commands', root / 'COMMANDS.json', proof['commands'], 'CANONICAL_COMMANDS.original.json')"),
      ("        progress = self.read(root / 'MUTATION_PROGRESS.json', proof['progress'], 'CANONICAL_PROGRESS.original.json')",
       "        progress = self.read_historical('canonical.progress', root / 'MUTATION_PROGRESS.json', proof['progress'], 'CANONICAL_PROGRESS.original.json')"),
      ("        original_inputs = self.read(root / 'INPUTS.final.json', proof['inputs'], 'CANONICAL_INPUTS.original.json')",
       "        original_inputs = self.read_historical('canonical.inputs', root / 'INPUTS.final.json', proof['inputs'], 'CANONICAL_INPUTS.original.json')"),
      ("        self.current_lock()\n\n    def finish(self):", "        self.current_lock()\n        self._verify_transport_stability()\n\n    def finish(self):"),
      ("    def finish(self):\n        self.current_lock()\n", "    def finish(self):\n        self.current_lock()\n        self._verify_transport_stability()\n"),
    ]
    for before, after in ops:
        admission = replace_once(admission, before, after)
    methods = (HERE / 'admission_transport_methods.py').read_text()
    admission += '\n\n' + methods
    compile(admission, 'qualification-admission.HOLD.py', 'exec')
    inverse = admission.removesuffix('\n\n' + methods)
    for before, after in reversed(ops):
        inverse = replace_once(inverse, after, before)
    inverse = replace_once(inverse, newconstants + '\n\n', '')
    assert inverse == original_admission
    old_adm_defs, new_adm_defs = definitions(original_admission), definitions(admission)
    changed_adm = [name for name in old_adm_defs if old_adm_defs[name] != new_adm_defs[name]]
    expected_changed = {'Admission.__init__', 'Admission.observed_proof', 'Admission.acquire_and_validate',
        'Admission.before_native_stage', 'Admission.finish', 'Admission._fixed', 'Admission._artifact',
        'Admission._validate_canonical'}
    assert set(changed_adm) == expected_changed
    apin = retain('qualification-admission.HOLD.py', admission.encode())
    adiff = diff('ADMISSION_FROM_C77E.patch', original_admission, admission)
    source_before = (CFG / 'SOURCE_GATES_CONFIG.execution-candidate.json').read_bytes()
    source_cfg = json.loads(source_before)
    source_cfg.update(state='HOLD_ROOT_EXACT_SOURCE_REVIEW_REQUIRED',
                      records=source_control + '/source-gates-records',
                      source_checkout='/home/qian-qi/hepta-utility-36fa-source-gates-b608-v2',
                      run_identity='hepta-utility-36fa-final-b608-v2')
    source_cfg_raw = jbytes(source_cfg)
    retain('SOURCE_GATES_CONFIG.HOLD.json', source_cfg_raw)
    before_cfg = (CFG / 'QUALIFICATION_CONFIG.execution-candidate.json').read_bytes()
    cfg = json.loads(before_cfg)
    cfg.update(state='HOLD_ROOT_EXACT_SOURCE_REVIEW_REQUIRED', root_execution_approved=False,
               admission_path=source_control + '/qualification-admission.py', admission_pin=identity(admission.encode()),
               plan_path=source_control + '/PLAN.original.json',
               native_driver_path=source_control + '/native-driver.original.py',
               records=source_control + '/native-records',
               source_gates_config_path=source_control + '/SOURCE_GATES_CONFIG.json',
               source_gates_config_pin=identity(source_cfg_raw),
               source_gates_handoff_records=source_control + '/source-handoff',
               root_parent='/run/hepta-utility-36fa-final-b608-v2',
               run_identity='hepta-utility-36fa-final-b608-v2',
               historical_runtime_guard_path=hguard_path,
               historical_runtime_guard_pin=identity(hguard.encode()),
               history_transport={'control': transport, 'manifest_path': manifest_path,
                   'manifest': identity(manifest_raw), 'staging_result_path': transport + '/STAGING_READBACK.json',
                   'staging_result': None, 'staging_supervisor_path': source_control + '/TRANSPORT_SUPERVISOR.original.json',
                   'staging_supervisor': None, 'staging_job_id': None, 'staging_payload': None})
    cfg_raw = jbytes(cfg)
    cfgpin = retain('QUALIFICATION_CONFIG.HOLD.json', cfg_raw)
    diff('QUALIFICATION_CONFIG_FROM_720ABB.patch', before_cfg.decode(), cfg_raw.decode())
    diff('SOURCE_CONFIG_FROM_B976.patch', source_before.decode(), source_cfg_raw.decode())
    review = {'format': 'hepta-transported-original-successor-static-byte-review-v1',
              'H_calls': 0, 'gate_or_guard_functions_executed': 0, 'qualification': False,
              'root_execution_approved': False, 'historical_v5': identity(hguard.encode()),
              'historical_v5_original': old_v5_pin, 'historical_v5_exact_inverse': True,
              'historical_v5_original_function_count': len(old_defs), 'historical_v5_changed_original_definitions': changed_v5,
              'historical_v5_all_other_definitions_byte_equal': True, 'historical_v5_exact_read_site_count': 4,
              'current_v5_original_file_unmodified': True, 'current_v5_load_and_live_reads_unchanged': True,
              'admission': identity(admission.encode()), 'admission_original': identity(original_admission.encode()),
              'admission_exact_inverse': True, 'admission_original_definition_count': len(old_adm_defs),
              'admission_changed_original_definitions': changed_adm,
              'admission_all_other_original_definitions_byte_equal': True,
              'admission_replacement_count': len(ops), 'historical_json_bytes_rewritten': False,
              'runtime_guard_cfg_unchanged': cfg['runtime_guard'] == json.loads(before_cfg)['runtime_guard'],
              'current_repo_lock_inventory_git_and_runtime_contracts_unchanged': all(cfg[k] == json.loads(before_cfg)[k] for k in (
                  'repo','source','tree','parents','coordination_lock','current_final_git_state','full_physical_inventory',
                  'full_native_inventory','canonical_complete_git_metadata','canonical_original_index',
                  'maintenance_guard_path','inventory_driver_path','runtime_guard','expected_inventory_sha256')),
              'original_source_wrapper_driver_native_wrapper_driver_plan_unchanged': True,
              'original_14_phases_48_root_parents_and_all_budgets_unchanged': True,
              'stage_only_script': identity(stager.encode()), 'stage_HOLD_input': identity(stdin),
              'stage_HOLD_request': identity(stage_typed), 'stage_outer_seconds': 900,
              'stage_typed_fields': list(stage_request), 'no_env': 'env' not in stage_request,
              'max_typed_input_bytes': 1048576,
              'actual_successful_stage_bindings': 'four null fields; source successor cannot construct or execute',
              'new_source_typed_request': None, 'native_typed_request': None,
              'limitations': ['No live original path availability is asserted.',
                  'No historical receipt grants current tool/material/source/lock availability.',
                  'All original live guards remain mandatory before any source gate.',
                  '65a remains failed preflight with no source-driver entry.']}
    retain('STATIC_SUCCESSOR_REVIEW.json', jbytes(review))
    print(json.dumps(review, sort_keys=True))

if __name__ == '__main__':
    main()
