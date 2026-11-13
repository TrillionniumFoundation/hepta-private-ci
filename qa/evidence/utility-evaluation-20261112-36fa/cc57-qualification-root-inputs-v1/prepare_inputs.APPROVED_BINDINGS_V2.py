import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-cc57-qualification-root-inputs-v1')
HOLD = Path('/tmp/hepta-36fa-final-qualification-hold-v1')
ALIGN = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1')
FMT = Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1')
PREP = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1')
NATIVE_CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v1'
NATIVE_ALIGNMENT = '/home/qian-qi/hepta-utility-36fa-evidence/source-repair-canonical-alignment-v1'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(directory, name):
    raw = (directory / name).read_bytes()
    return raw, json.loads(raw)


def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return pin(raw)


def normal(raw, job):
    envelope = json.loads(raw)
    assert envelope['isError'] is False and len(envelope['content']) == 1
    assert envelope['content'][0]['type'] == 'text'
    value = json.loads(envelope['content'][0]['text'])
    assert value['job_id'] == job and value['state'] == 'succeeded' and value['exit_code'] == 0
    assert all(value[k] is False for k in ('timed_out', 'cancelled', 'automatic_retry'))
    assert all(value[k] is True for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed'))
    assert not any(value['log_truncated'].values())
    return value


def main():
    aligned_raw, aligned = read(ALIGN, 'RESULT.json')
    aligned_normal_raw = (ALIGN / 'STATUS_01.original.json').read_bytes()
    terminal = normal(aligned_normal_raw, '1a1d223a60b-2564-1ca3')
    assert aligned['format'] == 'hepta-final-canonical-alignment-result-v1'
    assert aligned['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
    assert aligned['local_head_advanced'] is True and aligned['physical_source_writes_dispatched'] == 0
    for key in ('source_branch_refs_updated', 'remote_ref_updates', 'dependency_installation_started',
                'cargo_or_formatter_started', 'qualification', 'automatic_retry'):
        assert aligned[key] is False
    assert aligned['test_commands_dispatched'] == 0
    assert {x['check']: x['status'] for x in aligned['final_audits']} == {
        'source': 'verified', 'git': 'verified', 'inputs': 'verified'}
    for key in ('physical_equals_canonical_before_index_change', 'physical_bytes_unchanged',
                'physical_modes_unchanged', 'complete_source_clean', 'detached', 'index_equals_tree',
                'normal_stat_refresh_verified'):
        assert aligned['actual'][key] is True
    assert aligned['actual']['verified_canonical_objects'] == 10
    after = aligned['after']
    assert after['commit'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
    assert after['tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
    assert after['parents'] == ['246d8cb614770252ee42029a5c014f2a4904176a']
    actual_clean_raw = (PREP / 'CANONICAL_CLEAN_INVENTORY.expected.json').read_bytes()
    assert {k: after['inventory'][k] for k in ('bytes', 'sha256', 'git_blob')} == pin(actual_clean_raw)
    assert after['inventory']['tracked_entries'] == after['inventory']['filesystem_entries'] == 15188
    fmt_raw, fmt = read(FMT, 'RESULT.original.json')
    fmt_normal_raw = (FMT / 'STATUS_01.original.json').read_bytes()
    normal(fmt_normal_raw, '1a1d2107dce-2564-1c98')
    assert fmt['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
    assert fmt['formatter_changed_paths'] == [] and fmt['format_source_stable'] is True
    assert aligned['final_format']['job_id'] == '1a1d2107dce-2564-1c98'
    assert aligned['final_format']['result'] == pin(fmt_raw)
    assert aligned['final_format']['supervisor'] == pin(fmt_normal_raw)
    projection_path = Path('/tmp/hepta-36fa-native-compact-projection-cc57-v1/PROJECTION_REPORT.json')
    projection_raw = projection_path.read_bytes()
    projection = json.loads(projection_raw)
    assert pin(projection_raw)['git_blob'] == 'e7c1af7d58e266b43f6111287616e0d1acd910b8'
    assert projection['full_expected_input'] == pin(actual_clean_raw)
    assert projection['source_expected'] == {'head': after['commit'], 'tree': after['tree'], 'status': ''}
    assert projection['compact_expected']['sha256'] == '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9'
    # Recompute the exact compact format independently. This remains an expected
    # value until the original native snapshot reads and hashes the checkout.
    rows = []
    for r in sorted(json.loads(actual_clean_raw)['files'], key=lambda r: r['path'].encode()):
        assert r['matches_index'] is True and r['stable'] is True
        mode = '120000' if r['kind'] == 'symlink' else ('100755' if r['permissions'] & 0o111 else '100644')
        rows.append({'path': r['path'], 'mode': mode, 'bytes': r['bytes'], 'sha256': r['sha256'], 'blob': r['working_blob']})
    compact = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    assert pin(compact) == {k: projection['compact_expected'][k] for k in ('bytes', 'sha256', 'git_blob')} and len(rows) == 15188
    assert compact == Path('/tmp/hepta-36fa-native-compact-projection-cc57-v1/NATIVE_COMPACT_INVENTORY.projected.json').read_bytes()
    runtime_path = Path('/tmp/hepta-36fa-maintenance-v5-root-approval/APPROVED_CONFIG_V5.json')
    runtime_raw = runtime_path.read_bytes()
    previous = json.loads(runtime_raw)
    assert pin(runtime_raw)['git_blob'] == 'a66ab71a3504f29240da6048ca2c45ca3735e89b'
    runtime_keys = ('runtime_restoration', 'environment', 'tool_files', 'v8_files',
                    'formatter_tool_files', 'create_target_if_absent', 'minimum_target_free_bytes',
                    'inherited_source_environment', 'tool_identity_projection')
    runtime_guard = {k: previous[k] for k in runtime_keys}
    assert runtime_guard['minimum_target_free_bytes'] == 32 * 1024**3
    assert runtime_guard['create_target_if_absent'] is False
    assert len(runtime_guard['environment']) == 17
    source_cfg = read(HOLD, 'SOURCE_GATES_CONFIG.HOLD.json')[1]
    source_cfg.update({
        'state': 'READY_FOR_EXACT_SOURCE_RUN',
        'source_sha': after['commit'], 'source_tree': after['tree'],
        'source_checkout': '/home/qian-qi/hepta-utility-36fa-source-gates-cc57-v1',
        'records': NATIVE_CONTROL + '/source-gates-records',
        'run_identity': 'hepta-utility-36fa-source-gates-cc57-v1',
    })
    assert source_cfg['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}
    source_pin = save('APPROVED_FINAL_SOURCE_GATES_CONFIG.json', source_cfg)
    cfg = read(HOLD, 'QUALIFICATION_INPUT.HOLD.json')[1]
    cfg.update({
        'state': 'READY_FOR_FINAL_SOURCE_QUALIFICATION', 'root_execution_approved': True,
        'source': after['commit'], 'tree': after['tree'], 'parents': after['parents'],
        'actual_final_format_postimages_reviewed': True, 'reviewed_formatter_changed_paths': [],
        'full_physical_inventory': after['inventory'],
        'expected_inventory_sha256': projection['compact_expected']['sha256'],
        'admission_path': NATIVE_CONTROL + '/qualification-admission.py',
        'native_driver_path': NATIVE_CONTROL + '/native-driver.original.py',
        'plan_path': NATIVE_CONTROL + '/PLAN.original.json',
        'records': NATIVE_CONTROL + '/native-records',
        'root_parent': '/run/hepta-utility-36fa-final-cc57-v1',
        'run_identity': 'hepta-utility-36fa-native-cc57-v1',
        'source_gates_config_path': NATIVE_CONTROL + '/APPROVED_SOURCE_GATES_CONFIG.json',
        'source_gates_config_pin': source_pin,
        'source_gates_handoff_records': NATIVE_CONTROL + '/source-handoff',
        'runtime_guard': runtime_guard,
        'final_format': {
            'job_id': '1a1d2107dce-2564-1c98',
            'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/source-repair-246d-fmt-v1/RESULT.json',
            'result': pin(fmt_raw),
            'supervisor_path': NATIVE_ALIGNMENT + '/FINAL_FORMAT_NORMAL.original.json',
            'supervisor': pin(fmt_normal_raw),
        },
        'canonical_alignment': {
            'job_id': terminal['job_id'], 'result_path': NATIVE_ALIGNMENT + '/run/RESULT.json',
            'result': pin(aligned_raw),
            'supervisor_path': NATIVE_CONTROL + '/CANONICAL_ALIGNMENT_NORMAL.original.json',
            'supervisor': pin(aligned_normal_raw),
        },
    })
    assert not any(v is None for v in cfg.values())
    cfg_pin = save('APPROVED_FINAL_QUALIFICATION_INPUT.json', cfg)
    review = {
        'format': 'hepta-root-final-qualification-input-approval-v1',
        'status': 'ACTUAL_FINAL_SOURCE_AND_INPUTS_VERIFIED_EXACT_LAUNCH_REVIEW_REQUIRED',
        'source': cfg['source'], 'tree': cfg['tree'], 'parents': cfg['parents'],
        'actual_alignment': cfg['canonical_alignment'], 'actual_final_format': cfg['final_format'],
        'actual_aligned_full_inventory': cfg['full_physical_inventory'],
        'exact_full_inventory_recovery': 'The previously prepared complete original-serializer bytes now match the successful native alignment RESULT in length, SHA256 and Git blob. This is exact recovery, not a second native full read.',
        'native_compact_expected': projection['compact_expected'],
        'native_compact_status': 'Expected only; actual original native snapshot remains mandatory.',
        'native_compact_independent_projection': pin(projection_raw),
        'runtime_guard_source': pin(runtime_raw), 'runtime_guard_exact_projected_keys': list(runtime_keys),
        'configuration': cfg_pin, 'source_gates_configuration': source_pin,
        'source_driver': cfg['inventory_driver_path'],
        'frozen_controls': {
            'admission': cfg['admission_pin'], 'native_driver': cfg['native_driver_pin'],
            'plan': cfg['plan_pin'],
            'source_wrapper': pin((HOLD / 'source-gates-wrapper.HOLD.py').read_bytes()),
            'native_wrapper': pin((HOLD / 'native-wrapper.HOLD.py').read_bytes()),
        },
        'root_review': 'Root read the complete admission/source/native wrappers and independent163c7b4 review. Original b92,5118,recorder,collector,14 phase limits,8MiB stack,nextest default/overrides,retries0 and source/original-owner assertions remain unchanged.',
        'required_execution_order': ['Complete original source5118 clone/freeze/source-closure600/self-test300/verify4800 and retain all actual outcomes', 'Then original native unfiltered eval3600,focused7200 within12000,all ordinary7200 thenRoot7200 within21000'],
        'source_wrapper_outer_timeout': 'Original7200seconds, recovered from actual historical typed request eae8d46956ac3afd89bf18b30d69997cbe925788 and already preserved in the actual246d source launch; no budget increase or phase-sum inference.',
        'exact_launch_review_still_required': True,
        'source_gates_started': False, 'native_tests_started': False,
        'qualified': False, 'real_qualified_task_chain_results': 0,
    }
    review_pin = save('ROOT_FINAL_QUALIFICATION_INPUT_APPROVAL.json', review)
    print(json.dumps({'configuration': cfg_pin, 'source_gates_configuration': source_pin,
                      'approval': review_pin, 'actual_alignment': pin(aligned_raw)}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
