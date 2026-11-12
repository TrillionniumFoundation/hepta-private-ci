#!/usr/bin/env python3
"""Prepare exact call-site registration; source fences remain pending actual fmt."""
import copy
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT = Path('/tmp/hepta-36fa-evaluated-ordinary-nonrust-v1')
SRC = 'codex-rs/hepta-agentd/src/'
source_tree = '02103ded93173dd17aef645ddfcaa5fc6f674042'
baseline = (ROOT / 'baseline/CALLERS.toml').read_text()
data = tomllib.loads(baseline)
assert len(data['boundary']) == 541 and len(data['protected_file']) == 412
events = json.loads((ROOT / 'CHANGED_CALL_SITE_ANALYSIS.json').read_text())['events']
changes = {}
for event in events:
    i, path = event['boundary_position'], event['path']
    call = event['after_changed_file_parse'].get('call')
    if call is True and not event['registered_in_baseline']:
        changes.setdefault(i, {'add': [], 'remove': []})['add'].append(path)
    elif call is False and event['registered_in_baseline']:
        changes.setdefault(i, {'add': [], 'remove': []})['remove'].append(path)
for i in (450, 484):
    changes.setdefault(i, {'add': [], 'remove': []})['add'].append(SRC + 'circuit_retained_version_prepared.rs')

def row(identifier, owner, method, definition, callers):
    return {'id': identifier, 'symbol': owner + '::' + method,
            'receiver_type': owner, 'definition_path': SRC + definition,
            'definition_markers': ['fn ' + method + '('],
            'product_callers': [SRC + name for name in callers], 'caller_markers': []}

new = []
def add(*args):
    new.append(row(*args))

candidate = 'OriginalCellQ24CandidateStageOwnersV1'
add('learning_original_candidate_retained_stage_route', candidate, 'require_evaluated_retained_stage', 'cell_q24_candidate_stage_retained.rs', ['authority_host_learning_resident_stages.rs', 'cell_q24_candidate_stage_retained_execute.rs'])
add('learning_original_candidate_retained_stage_execute', candidate, 'execute_evaluated_retained_stage', 'cell_q24_candidate_stage_retained_execute.rs', ['cell_q24_candidate_stage_owners.rs'])
add('learning_original_candidate_retained_stage_readback', candidate, 'read_evaluated_retained_prefix', 'cell_q24_candidate_stage_retained_readback.rs', ['cell_q24_candidate_stage_owners.rs'])
add('learning_original_candidate_retained_stage_attestation', candidate, 'retained_attestation', 'cell_q24_candidate_stage_retained_readback.rs', ['cell_q24_candidate_stage_owners.rs'])
add('learning_original_evaluated_read_next_use_binding', 'OriginalCircuitLearningReadClientV1', 'require_original_evaluated_next_use', 'circuit_evaluated_learning_read.rs', ['circuit_evaluated_next_use_command_service.rs', 'circuit_evaluated_next_use_remote.rs'])
add('learning_original_evaluated_selector_command_context', 'OriginalCircuitSelectionCommandContextV1', 'from_original_evaluation', 'circuit_evaluated_selection_command.rs', [])
add('learning_original_evaluated_selector_command_recover', 'OriginalCircuitSelectionCommandClientV1', 'recover_from_original_evaluated_stream', 'circuit_evaluated_selection_command.rs', [])
add('learning_original_evaluated_selector_command_owner_profile', 'OriginalCircuitSelectionReceiptOwnerV1', 'original_evaluated_command_context', 'circuit_evaluated_selection_command_owner_adapter.rs', ['circuit_evaluated_selection_command_service.rs'])
add('learning_original_evaluated_selector_command_owner_factory', 'OriginalCircuitSelectionCommandOwnerV1', 'from_original_evaluated_receipt_owner', 'circuit_evaluated_selection_command_service.rs', ['circuit_evaluated_selection_command_owner_adapter.rs'])
add('learning_original_evaluated_selector_command_owner_transfer', 'OriginalCircuitSelectionReceiptOwnerV1', 'into_evaluated_command_owner', 'circuit_evaluated_selection_command_owner_adapter.rs', [])
add('learning_original_evaluated_selector_command_receipt', 'OriginalCircuitEvaluatedSelectionReceiptV1', 'from_original_command_response', 'circuit_evaluated_selection_command_owner_adapter.rs', ['circuit_evaluated_selection_command.rs'])
add('learning_original_evaluated_selector_readback_binding', 'OriginalCircuitSelectionReadbackConnectionV1', 'bind_original_evaluated_selection', 'circuit_selection_command_readback.rs', [])
add('learning_original_evaluated_selector_stage_binding', 'OriginalCircuitSelectionCommandClientV1', 'bind_original_evaluated_stage_channel', 'circuit_selection_command_stage_binding.rs', ['cell_q24_candidate_stage_retained.rs'])
add('learning_original_evaluated_next_use_command_context', 'OriginalCircuitNextUseCommandContextV1', 'from_original_evaluated_selection', 'circuit_evaluated_next_use_command.rs', [])
add('learning_original_evaluated_next_use_command_recover', 'OriginalCircuitNextUseCommandClientV1', 'recover_from_original_evaluated_stream', 'circuit_evaluated_next_use_command.rs', [])
add('learning_original_evaluated_next_use_command_owner_profile', 'OriginalCircuitNextUseReceiptOwnerV1', 'original_evaluated_command_selection', 'circuit_evaluated_next_use_remote.rs', ['circuit_evaluated_next_use_command_service.rs'])
add('learning_original_evaluated_next_use_command_owner_factory', 'OriginalCircuitNextUseCommandOwnerV1', 'from_original_evaluated_receipt_owner', 'circuit_evaluated_next_use_command_service.rs', ['circuit_evaluated_next_use_remote.rs'])
add('learning_original_evaluated_next_use_command_owner_transfer', 'OriginalCircuitNextUseReceiptOwnerV1', 'into_evaluated_command_owner', 'circuit_evaluated_next_use_remote.rs', [])
add('learning_original_evaluated_next_use_remote_attest', 'OriginalCircuitNextUseReceiptOwnerV1', 'attest_original_evaluated_remote_completion', 'circuit_evaluated_next_use_remote.rs', ['circuit_evaluated_next_use_command_service.rs'])
add('learning_original_evaluated_next_use_remote_readback', 'OriginalCircuitNextUseReceiptOwnerV1', 'readback_evaluated_remote_completion', 'circuit_evaluated_next_use_remote.rs', ['circuit_evaluated_next_use_command_service.rs'])
add('learning_original_evaluated_next_use_stage_binding', 'OriginalCircuitNextUseCommandClientV1', 'bind_original_evaluated_stage_channel', 'circuit_next_use_command_stage_binding.rs', ['cell_q24_candidate_stage_retained.rs'])
add('learning_original_evaluated_c_readiness_binding', 'OriginalCircuitCompletionReadinessClientV1', 'bind_original_evaluated_stage_channel', 'circuit_learning_completion_readiness.rs', ['cell_q24_candidate_stage_retained.rs'])
add('learning_original_evaluated_c_readiness_serve', 'OriginalCircuitLearningReadOwnerV1', 'serve_evaluated_completion_readiness', 'circuit_learning_completion_readiness_service.rs', [])
add('learning_retained_version_evaluated_selection_channel', 'OriginalCircuitLearningReadOwnerV1', 'serve_original_evaluated_retained_channel', 'circuit_learning_read_service.rs', ['circuit_retained_version_service.rs'])
add('learning_retained_version_evaluated_client_bind', 'OriginalCircuitRetainedVersionClientV1', 'bind_original_evaluated_stage_channel', 'circuit_retained_version_client.rs', ['cell_q24_candidate_stage_retained.rs'])
add('learning_retained_version_evaluated_client_recover', 'OriginalCircuitRetainedVersionClientV1', 'recover_original_evaluated_stage_channel', 'circuit_retained_version_client.rs', ['cell_q24_candidate_stage_retained.rs'])
add('learning_retained_version_evaluated_host_create', 'OriginalCircuitRetainedVersionHostV1', 'from_original_evaluated_owners', 'circuit_retained_version_host.rs', [])
add('learning_retained_version_evaluated_host_recover', 'OriginalCircuitRetainedVersionHostV1', 'recover_from_original_evaluated_owners', 'circuit_retained_version_host.rs', [])
assert len(new) == 28
assert not {r['id'] for r in new} & {r['id'] for r in data['boundary']}

matches = list(re.finditer(r'(?m)^\[\[boundary\]\]\s*$', baseline))
first_protected = baseline.index('[[protected_file]]')
header = baseline[:matches[0].start()]
blocks = [baseline[m.start():matches[i+1].start() if i+1 < len(matches) else first_protected] for i,m in enumerate(matches)]
assert len(blocks) == 541
updated = copy.deepcopy(data['boundary'])
audited_changes = []
for i, change in sorted(changes.items()):
    old = updated[i]['product_callers']
    assert len(set(change['add'])) == len(change['add']) and len(set(change['remove'])) == len(change['remove'])
    assert set(change['remove']) <= set(old)
    assert not set(change['add']) & set(old)
    after = [name for name in old if name not in change['remove']] + sorted(change['add'])
    block = blocks[i]
    m = re.search(r'(?m)^product_callers = \[(?:[^\]"\n]|"(?:[^"\\]|\\.)*"|\n)*\]', block)
    assert m, i
    blocks[i] = block[:m.start()] + 'product_callers = ' + json.dumps(after) + block[m.end():]
    updated[i]['product_callers'] = after
    assert tomllib.loads(blocks[i])['boundary'] == [updated[i]]
    audited_changes.append({'position':i,'id':updated[i]['id'],**change,'before':old,'after':after})

inventory = data['privileged_inventory']['required_boundary_ids']
m = re.search(r'(?m)^required_boundary_ids = \[.*\]$', header)
assert m
header = header[:m.start()] + 'required_boundary_ids = ' + json.dumps(inventory+[r['id'] for r in new]) + header[m.end():]
def render_boundary(value):
    return '[[boundary]]\n' + ''.join(key+' = '+json.dumps(item)+'\n' for key,item in value.items()) + '\n\n'
candidate_text = header + ''.join(blocks) + ''.join(render_boundary(r) for r in new) + baseline[first_protected:]
parsed = tomllib.loads(candidate_text)
assert parsed['boundary'] == updated + new
assert parsed['protected_file'] == data['protected_file']
assert parsed['authority'] == data['authority'] and all(v is False for v in parsed['authority'].values())
for key in data.keys() - {'boundary','privileged_inventory'}:
    assert parsed[key] == data[key]
out = ROOT / 'structural-candidate';out.mkdir(exist_ok=True)
(out/'CALLERS.toml').write_text(candidate_text)
plan = {'status':'structural_only_pending_actual_fmt_full_source_checks_and_qa_alignment',
        'source_tree_unformatted':source_tree,'base_callers_blob':'cf194d0ef743ca0e7cf7b0125b52ceec914649dd',
        'original_boundaries_retained':541,'new_boundaries':new,'changed_existing_boundaries':audited_changes,
        'existing_protected_rows_retained_unchanged_at_this_stage':412,
        'pending_new_protected_paths':[SRC+n for n in ['cell_q24_candidate_stage_retained.rs','cell_q24_candidate_stage_retained_execute.rs','cell_q24_candidate_stage_retained_readback.rs','circuit_evaluated_selection_command.rs','circuit_evaluated_selection_command_owner_adapter.rs','circuit_evaluated_selection_command_service.rs','circuit_evaluated_next_use_command.rs','circuit_evaluated_next_use_command_service.rs','circuit_evaluated_next_use_remote.rs','circuit_retained_version_prepared.rs']],
        'expected_final_protected_row_count':422,'authority_flags_unchanged_false':True,
        'full_collector_gate_run':False,'strict_membership_equality_unchanged':True,
        'limits':['Changed-file pure parsing is source planning only, not full-source verification.','The prior two enum-arm ambiguities are addressed only by the separately reviewed Prepared UFCS postimage b62728f.','The new cross-file Self call is represented by the separately reviewed original-owner UFCS postimage 0e24b809.','Exact source fences, all corresponding original QA attacks and the allowlist await the actual formatted source.','No actual authorized A/B/C, real adoption, deployment or native runtime result is asserted.']}
(ROOT/'STRUCTURAL_REGISTRATION_PLAN.json').write_text(json.dumps(plan,indent=2)+'\n')
print(json.dumps({'status':plan['status'],'boundary_count':len(parsed['boundary']),'existing_rows_changed':len(changes),'new_members':sum(len(v['add']) for v in changes.values()),'moved_out_members':sum(len(v['remove']) for v in changes.values()),'protected_rows_pending_sync':len(json.loads((ROOT/'STRUCTURAL_SCOPE.json').read_text())['existing_affected_protected_rows']),'planned_new_protected_rows':10}))
