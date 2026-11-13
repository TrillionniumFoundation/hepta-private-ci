#!/usr/bin/env python3
"""Root exact successor comparison: no controller, native action, or source gate is executed."""
import ast, hashlib, json
from pathlib import Path
R=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
O=Path('/tmp/hepta-36fa-new-source-materializer-hold-v1')
N=Path('/tmp/hepta-36fa-coordinator-a489-materializer-hold-v1')
def pin(raw): return {'bytes':len(raw),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),'sha256':hashlib.sha256(raw).hexdigest()}
old_raw=(O/'driver.HOLD.py').read_bytes(); new_raw=(N/'driver.HOLD.py').read_bytes()
assert pin(old_raw)['git_blob']=='6d1537fcd58540da64c18916369f4f04d2a0dce1'
assert pin(new_raw)['git_blob']=='2044db8282eb8db8d5627519a425a49f636377da'
old=old_raw.decode(); new=new_raw.decode()
old_packet_raw=(O/'MATERIALIZATION_PACKET.HOLD.json').read_bytes(); new_packet_raw=(N/'MATERIALIZATION_PACKET.HOLD.json').read_bytes()
assert pin(old_packet_raw)['git_blob']=='728a9251a3ee0e5fca4dd4cc43e8629bbfa9185c'
assert pin(new_packet_raw)['git_blob']=='b05c78c478bbd55219fea7869b1c7871617509c7'
pairs=[
("TARGET = pathlib.Path('/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1')","TARGET = pathlib.Path('/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1')"),
("CONTROL = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-isolated-materialization-v1')","CONTROL = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1')"),
("STAGING_PREFIX = '/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-materialization-v1'","STAGING_PREFIX = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-materialization-v1'"),
("HEAD = '0c59aaca0b4932507f068c723f73da2f96729b3d'","HEAD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'"),
("TREE = '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'","TREE = 'a489b394666b8141840275128a780605b024cde0'"),
("LEAVES = 15237","LEAVES = 15243"),
("PACKET_PIN = "+repr(pin(old_packet_raw)),"PACKET_PIN = "+repr(pin(new_packet_raw))),
("    check(len(covered) == packet['overlay']['covered_paths'] == 110 and added == packet['overlay']['new_paths'] == 49 and changed == packet['overlay']['modified_paths'] == 60 and unchanged == packet['overlay']['unchanged_covered_paths'] == 1, 'exact complete reviewed 110-path overlay')",
 "    check(len(covered) == packet['overlay']['covered_paths'] == 119 and added == packet['overlay']['new_paths'] == 55 and changed == packet['overlay']['modified_paths'] == 63 and unchanged == packet['overlay']['unchanged_covered_paths'] == 1, 'exact complete reviewed 119-path overlay')"),
("    candidate_provided = add_provided(candidate_input, 120)","    candidate_provided = add_provided(candidate_input, 129)"),
("    check(len(object_index) == packet['object_scope']['union_objects'] == 16652 and counts == packet['object_scope']['counts'] == {'blob': 14796, 'tree': 1852, 'commit': 4}, 'complete exact four-snapshot union, not ancestry')",
 "    check(len(object_index) == packet['object_scope']['union_objects'] == 16661 and counts == packet['object_scope']['counts'] == {'blob': 14805, 'tree': 1852, 'commit': 4}, 'complete exact four-snapshot union, not ancestry')")
]
# Pin assignment field order is frozen in the original driver.
for i,(a,b) in enumerate(pairs):
    if a.startswith('PACKET_PIN = '):
        def assignment(p):
            return "PACKET_PIN = "+repr({'bytes':p['bytes'],'sha256':p['sha256'],'git_blob':p['git_blob']})
        pairs[i]=(assignment(pin(old_packet_raw)),assignment(pin(new_packet_raw)))
expected=old
for a,b in pairs:
    assert expected.count(a)==1,(a,'not unique original line')
    expected=expected.replace(a,b,1)
assert expected==new,'Unreviewed source delta outside ten exact substitutions'
restored=new
for a,b in reversed(pairs):
    assert restored.count(b)==1
    restored=restored.replace(b,a,1)
assert restored==old
def definitions(s):
    return {n.name:ast.get_source_segment(s,n) for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
od=definitions(old); nd=definitions(new)
assert od.keys()==nd.keys() and len(od)==56
changed=[k for k in od if od[k]!=nd[k]]
assert changed==['derive_candidate_inventory','expected_graphs']
same=[k for k in od if od[k]==nd[k]]
assert len(same)==54
op=json.loads(old_packet_raw); np=json.loads(new_packet_raw)
preserved=['donor','donor_git','donor_proof','format','format_base','git_tool','original_inventory','parent_snapshot','seed_raw_commits','source_repo']
for k in preserved: assert op[k]==np[k],k
assert np['qualification'] is False and np['expected_not_native_observed'] is True
assert np['current']['commit']=='d25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
assert np['current']['parents']==['cc57c7198db6293ccca562253c42fffbe2a04633']
assert np['current']['tree']=='a489b394666b8141840275128a780605b024cde0'
assert np['current']['inventory']['git_blob']=='f1e2d72f99093581403a2dcc91b55da22a33f905'
assert np['current']['native_inventory']['git_blob']=='7647480c5ed06525e1661ac451d0ac0ff2b23ea7'
for name in ('base','candidate'):
    assert np['provided_inputs'][name]['maximum_decoded_part']==524288
    assert len(np['provided_inputs'][name]['parts'])==(2 if name=='base' else 3)
    for p in np['provided_inputs'][name]['parts']:
        assert p['bytes']<=524288 and p['mode']==0o600
cfg=json.loads((N/'WAITING_CONFIG.json').read_text())
assert cfg['root_execution_approved'] is False and cfg['automatic_retry'] is False and cfg['qualification'] is False
assert cfg['action_seconds']==600 and cfg['record_seconds']==180 and cfg['driver']==pin(new_raw)
assert cfg['source_repo']=='/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
assert cfg['destination_repo']=='/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
assert cfg['control']=='/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1'
report={'format':'hepta-root-exact-a489-materializer-successor-review-v1','qualification':False,'H_calls':0,'native_or_project_functions_invoked':0,'status':'EXACT_FIXED_SUCCESSOR_STATIC_ONLY_EXECUTION_REQUEST_STILL_PENDING','original':pin(old_raw),'successor':pin(new_raw),'exact_substitutions':[{'before':a,'after':b} for a,b in pairs],'entire_inverse_bytes_equal':True,'top_level_definitions':len(od),'unchanged_definition_names':same,'changed_fixed_count_definition_names':changed,'packet':pin(new_packet_raw),'unchanged_complete_packet_fields':preserved,'original_clean_donor_not_dirty_0c59':True,'original_action_seconds':600,'original_record_seconds':180,'original_outer_seconds_required':900,'decoded_part_cap':524288,'typed_input_cap_required':1048576,'parts':[2,3],'waiting_config':pin((N/'WAITING_CONFIG.json').read_bytes()),'scope_limit':'This is not final main typed request approval, native materialization, a compiler/test result or real task chain.'}
raw=(json.dumps(report,indent=2,sort_keys=True)+'\n').encode()
(R/'ROOT_A489_MATERIALIZER_SUCCESSOR_REVIEW.json').write_bytes(raw)
print(json.dumps({'report':pin(raw),'exact_changes':len(pairs),'unchanged_definitions':len(same),'status':report['status']}))
