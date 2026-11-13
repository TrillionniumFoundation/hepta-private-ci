#!/usr/bin/env python3
"""Offline, main-free adaptation of the exact 24d preparation control."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
OLD = Path('/tmp/hepta-36fa-final-nonrust-fmt-v2/driver.HOLD.py')
ORIGINALS = Path('/tmp/hepta-36fa-final-source-qualification-launch-v1')
QUAL = json.loads(Path('/tmp/hepta-36fa-after2268-20261112/APPROVED_FINAL_QUALIFICATION_INPUT.json').read_text())

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def write(name, data):
    raw = data.encode() if isinstance(data, str) else data
    with (HERE/name).open('xb') as stream: stream.write(raw)
    return pin(raw)

old = OLD.read_text()
assert pin(old.encode()) == {'bytes':22679,'sha256':'a0cb7e886255c53e34f21002051209580bdb8e2089d4a892f6789ae95d15ea04','git_blob':'24d705376fe042f040d87b6a5fc72a67780b01fa'}
new = old

def replace(before, after):
    global new
    assert new.count(before) == 1, before[:160]
    new = new.replace(before, after)

replace("CONTROL = EVIDENCE / 'final-nonrust-fmt-control-v2'", "CONTROL = EVIDENCE / 'source-repair-246d-fmt-control-v1'")
replace("OUT = EVIDENCE / 'final-nonrust-fmt-v2'", "OUT = EVIDENCE / 'source-repair-246d-fmt-v1'")
start = new.index("CAPTURE = EVIDENCE")
stop = new.index("V5_JOB =", start)
source_dir = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-246d-v1'
const = "CURRENT_HEAD = '246d8cb614770252ee42029a5c014f2a4904176a'\nCURRENT_TREE = 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'\nCURRENT_PARENTS = ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']\n"
const += 'CANONICAL_ALIGNMENT = '+repr(QUAL['canonical_alignment'])+'\n'
const += 'SOURCE_RUN = Path('+repr(source_dir)+')\n'
const += "SOURCE_JOB = '1a1d1e83bd4-2564-1c86'\n"
proof_files = {
 'handoff': ('source-handoff/RESULT.json','source-handoff.RESULT.original.json'),
 'original_run': ('source-handoff/ORIGINAL_RUN_RESULT.json','source-handoff.ORIGINAL_RUN_RESULT.original.json'),
 'git_after': ('source-handoff/admission/GIT_STATE.after.json','origin.GIT_STATE.after.json'),
 'full_comparison': ('source-handoff/admission/FULL_PHYSICAL_COMPARISON.json','origin.FULL_PHYSICAL_COMPARISON.json'),
}
proofs = {k:{'path':v[0],**pin((ORIGINALS/v[1]).read_bytes())} for k,v in proof_files.items()}
const += 'SOURCE_PROOFS = '+repr(proofs)+'\n'
const += 'SOURCE_NORMAL_PIN = '+repr(pin((ORIGINALS/'SOURCE_STATUS_05.original.json').read_bytes()))+'\n'
paths = sorted(['.github/blob-size-allowlist.txt','CALLERS.toml',
 'qa/b4-no-bypass/test_original_circuit_observer_source_closure.py',
 'qa/b4-no-bypass/test_original_selection_readback_source_closure.py',
 'qa/b4-no-bypass/test_resident_root_source_closure.py'])
const += 'REPAIR_PATHS = '+repr(paths)+'\n'
new = new[:start]+const+new[stop:]
replace("BASELINE = {'bytes': 5614211, 'sha256': '3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f', 'git_blob': '1563de8825fc183d345d10d03e68d79b2d9211ca'}",
        "BASELINE = {'bytes': 5611184, 'sha256': 'df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e', 'git_blob': '663373f936c2ff130aec96ad34654cc9811773c2'}")
replace("BASELINE_TREE = '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'", 'BASELINE_TREE = CURRENT_TREE')
replace("V5_GIT_PIN = {'bytes': 489, 'sha256': 'e8ec74c83f7f671727d417e722da27a1337e70b0ef14b3a0481bd5d0ef609e14', 'git_blob': 'be108e81e8becd1b6dd3f4cac302b5f855d51b41'}\n", '')
replace('    module.OUT = OUT\n', '    module.OUT = OUT\n    module.HEAD = CURRENT_HEAD; module.TREE = CURRENT_TREE; module.PARENTS = CURRENT_PARENTS\n')

start = new.index('def prove_actual_capture(m):')
stop = new.index('\ndef prepare(m, control, original):', start)
proof_function = r'''def prove_actual_clean_source(m):
    """Require the real clean alignment and preserve the completed FAILED gate."""
    aligned_raw = m.read_input(Path(CANONICAL_ALIGNMENT['result_path']), CANONICAL_ALIGNMENT['result'])
    aligned = m.parse(aligned_raw)
    normal_raw = m.read_input(Path(CANONICAL_ALIGNMENT['supervisor_path']), CANONICAL_ALIGNMENT['supervisor'])
    normal = m.parse_supervisor(normal_raw)
    m.check(normal['job_id'] == CANONICAL_ALIGNMENT['job_id']
            and aligned['format'] == 'hepta-final-canonical-alignment-result-v1'
            and aligned['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
            and aligned['source_repo'] == str(m.REPO)
            and aligned['qualification'] is False
            and aligned['physical_source_writes_dispatched'] == 0
            and aligned['cargo_or_formatter_started'] is False
            and aligned['test_commands_dispatched'] == 0
            and aligned['remote_ref_updates'] is False
            and aligned['source_branch_refs_updated'] is False
            and aligned['automatic_retry'] is False, 'actual normal clean canonical alignment')
    m.check({r['check']: r['status'] for r in aligned['final_audits']} ==
            {'source': 'verified', 'git': 'verified', 'inputs': 'verified'}, 'complete canonical audits')
    after = aligned['after']
    m.check(after['commit'] == CURRENT_HEAD and after['tree'] == CURRENT_TREE
            and after['parents'] == CURRENT_PARENTS
            and all(after['inventory'][key] == value for key, value in BASELINE.items())
            and after['inventory']['tracked_entries'] == after['inventory']['filesystem_entries'] == 15188,
            'actual canonical full clean source identity')
    m.check(all(aligned['actual'][key] is True for key in (
            'complete_source_clean', 'detached', 'index_equals_tree', 'normal_stat_refresh_verified',
            'physical_bytes_unchanged', 'physical_modes_unchanged')), 'actual complete canonical properties')
    m.write('CANONICAL_ALIGNMENT.RESULT.original.json', aligned_raw)
    m.write('CANONICAL_ALIGNMENT.NORMAL.original.json', normal_raw)
    values = {}
    for name, item in SOURCE_PROOFS.items():
        raw = m.read_input(SOURCE_RUN / item['path'], item)
        values[name] = m.parse(raw)
        m.write('FAILED_SOURCE.'+name+'.original.json', raw)
    terminal_raw = m.read_input(CONTROL / 'SOURCE_GATES_NORMAL.original.json', SOURCE_NORMAL_PIN)
    outer = m.parse(terminal_raw)
    m.check(('resultType' not in outer or outer['resultType'] == 'complete')
            and outer.get('isError') is False and len(outer.get('content', [])) == 1
            and outer['content'][0].get('type') == 'text', 'actual failed-source terminal SDK')
    terminal = m.parse(outer['content'][0]['text'].encode())
    m.check(terminal.get('job_id') == SOURCE_JOB and terminal.get('state') == 'failed'
            and terminal.get('exit_code') == 1 and terminal.get('timed_out') is False
            and terminal.get('cancelled') is False and terminal.get('automatic_retry') is False
            and terminal.get('output_complete') is True and terminal.get('output_durable') is True
            and terminal.get('terminal_publication_confirmed') is True
            and not any(terminal.get('log_truncated', {}).values()), 'known complete failed source terminal, never PASS')
    handoff = values['handoff']; run = values['original_run']
    m.check(handoff['format'] == 'hepta-final-source-gates-handoff-v1'
            and handoff['status'] == handoff['original_run_status'] == 'failed'
            and handoff['source'] == CURRENT_HEAD and handoff['tree'] == CURRENT_TREE
            and handoff['qualification'] is False and handoff['driver_main_entered'] is True
            and handoff['driver_returncode'] == 1
            and handoff['actual_origin_full_physical_observation'] == {
                'extra_physical_entries': 0, 'full_physical_bytes_equal': True,
                'original_source_rows_unchanged': True}, 'actual failed source run with unchanged origin')
    expected = ['source-closure', 'self-test', 'verify']
    m.check(run['schema'] == 'hepta.utility.desktop-source-gates.v1'
            and run['source_sha'] == CURRENT_HEAD and run['source_tree'] == CURRENT_TREE
            and run['status'] == 'failed' and run['actual_A_B_C_qualification'] is False
            and run['attempted'] == run['entrypoints_started'] == expected and run['not_run'] == []
            and [(r['gate'], r['status']) for r in run['gates']] ==
                [('source-closure', 'failed'), ('self-test', 'passed'), ('verify', 'passed')],
            'all original source gates completed; closure failure is retained')
    for row in run['gates']:
        m.check(row['source_sha'] == CURRENT_HEAD and row['source_changed'] is False
                and row['before_inventory_sha256'] == row['after_inventory_sha256'] ==
                    '4db429ba1d54aa7ed6d6ad199694b7410d654ee7f788a631d7f392d7552fc79b'
                and row['execution_error'] is None and row['record_read_error'] is None
                and row['after_inventory_error'] is None
                and row['lifecycle'] == {'attempted': True, 'entrypoint_started': True,
                                        'package': 'completed', 'terminal_observed': True},
                'complete original gate evidence without source changes')
    m.check(values['git_after'] == after['git_state']
            and values['full_comparison']['full_bytes_equal'] is True
            and values['full_comparison']['original_rows_identical'] is True
            and values['full_comparison']['additional_physical_entries'] == [],
            'source-run actual origin Git and physical source still equal the clean alignment')
    m.write('FAILED_SOURCE.NORMAL.original.json', terminal_raw)
    m.result['previous_source_gate_status'] = 'failed'
    m.result['previous_source_gate_job'] = SOURCE_JOB
    m.result['failed_source_result_retained_without_reclassification'] = True
    return aligned

'''
new = new[:start]+proof_function+new[stop:]
replace("            'HEAD identity and actual dirty baseline remain separate')", "            'actual clean canonical HEAD and complete physical baseline')")
replace('    captured, capture_packet = prove_actual_capture(m)\n', '    aligned = prove_actual_clean_source(m)\n')
replace("    old_git = m.parse(m.read_input(EVIDENCE / 'run-v5' / 'final.git-state.json', V5_GIT_PIN))\n    m.check(m.initial_git_state == old_git, 'exact original Git state unchanged after V5')",
        "    m.check(m.initial_git_state == aligned['after']['git_state'], 'exact current Git state unchanged after source gates')")
replace("    m.pin_bytes(m.initial_inventory, BASELINE, 'actual complete dirty baseline')", "    m.pin_bytes(m.initial_inventory, BASELINE, 'actual complete clean canonical baseline')")
replace("    m.check(snapshot['source'] == captured['source_identity'] and snapshot['tracked_entries'] == 15188\n            and snapshot['filesystem_entries'] == 15188, 'actual full baseline source identity and counts')",
        "    m.check(snapshot['source'] == {'head': CURRENT_HEAD, 'tree': CURRENT_TREE, 'status': ''}\n            and snapshot['tracked_entries'] == snapshot['filesystem_entries'] == 15188\n            and all(row.get('matches_index') is True for row in snapshot['files']),\n            'actual complete clean source identity and all index-bound leaves')")
replace("    m.result['actual_capture_job'] = CAPTURE_JOB\n", "    m.result['actual_canonical_alignment_job'] = CANONICAL_ALIGNMENT['job_id']\n")
replace("            and packet['source_identity'] == captured['source_identity'] and packet['base_inventory'] == BASELINE", "            and packet['source_identity'] == snapshot['source'] and packet['base_inventory'] == BASELINE")
replace("    safe = {row['path'] for row in capture_packet['files'] if\n            row['path'] in ('CALLERS.toml', '.github/blob-size-allowlist.txt') or\n            (row['path'].startswith('qa/b4-no-bypass/') and row['path'].endswith('.py'))}\n    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] and paths\n            and set(paths) <= safe, 'exact approved existing non-Rust paths only')",
        "    m.check(paths == sorted(set(paths)) and paths == control['allowed_paths'] == REPAIR_PATHS,\n            'only the five reviewed existing non-Rust source-repair paths')")
ast.parse(new); compile(new, str(HERE/'driver.HOLD.py'), 'exec')
driver = write('driver.HOLD.py',new)
write('driver.original-24d.py',old)
diff = write('FROM_24D.diff',''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='24d705376fe042f040d87b6a5fc72a67780b01fa',tofile='source-repair-246d-HOLD')))
def defs(text):
    return {n.name:ast.get_source_segment(text,n) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
olddefs=defs(old);newdefs=defs(new)
review={'original_driver':pin(old.encode()),'driver':driver,'diff':diff,
 'unchanged_definitions':[n for n in olddefs if olddefs[n]==newdefs.get(n)],
 'changed_definitions':[n for n in olddefs if n in newdefs and olddefs[n]!=newdefs[n]],
 'replaced_definitions':{'prove_actual_capture':'prove_actual_clean_source'},
 'exact_source':QUAL['source'],'tree':QUAL['tree'],'whole_physical_source':QUAL['full_physical_inventory'],
 'approved_source_paths_waiting_final_packet':paths,'code_preparation_only':True,'driver_main_executed':False,
 'H_calls':0,'source_writes':0,'test_commands':0,'budget_changes':False,
 'budgets':{'preflight':600,'fmt':900,'record':300,'H_outer':2100},
 'static_call_scope':'Unchanged original V5 environment/capture/stage/finalize helpers; only fmt is dispatched, never main/initial_preflight/fix. This successor preserves the known failed source gate and cannot assert qualification.',
 'new_control':'/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/source-repair-246d-fmt-control-v1',
 'new_output':'/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/source-repair-246d-fmt-v1'}
cfg=json.loads(Path('/tmp/hepta-36fa-final-nonrust-fmt-v2/WAITING_CONFIG.json').read_text())
cfg.update(status='HOLD_SOURCE_REPAIR_PACKET_AND_ROOT_APPROVAL_REQUIRED',root_execution_approved=False,
 driver=driver,head=QUAL['source'],head_tree=QUAL['tree'],baseline_physical_tree=QUAL['tree'],
 baseline_inventory={k:QUAL['full_physical_inventory'][k] for k in ('bytes','sha256','git_blob')},
 allowed_paths=paths,nonrust_packet=None,expected_after_physical_tree=None,
 peer_semantic_review_blob=None,root_input_review_blob=None,source_proposal_version='source-repair-246d-v1')
write('WAITING_CONFIG.json',json.dumps(cfg,indent=2,sort_keys=True)+'\n')
write('STATIC_REVIEW_SCOPE.json',json.dumps(review,indent=2,sort_keys=True)+'\n')
print(json.dumps(review,indent=2))
