#!/usr/bin/env python3
"""Independent expected inventory derivation from complete graph; no native observation."""
import copy, hashlib, json, os
from pathlib import Path
R=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
G=Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1')
E=G/'expected-inventory-v1'
def oid(t,b): return hashlib.sha1(t.encode()+b' '+str(len(b)).encode()+b'\0'+b).hexdigest()
def pin(b): return {'bytes':len(b),'git_blob':oid('blob',b),'sha256':hashlib.sha256(b).hexdigest()}
def compact(d,lf=False): return (json.dumps(d,sort_keys=True,separators=(',',':'))+('\n' if lf else '')).encode()
base_raw=Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1/CC57_INVENTORY.json').read_bytes()
base=json.loads(base_raw); assert compact(base,True)==base_raw and pin(base_raw)['git_blob']=='7f94788b70546a8b8030dfd2b9182a7d9287c537'
graph_raw=(G/'CANDIDATE_FILE_GRAPH.json').read_bytes(); assert pin(graph_raw)['git_blob']=='097282896b5881614498faf2231e4c8c0da393c3'
graph=json.loads(graph_raw)
raw_commit=(R/'CANDIDATE_D2567544_COMMIT.raw').read_bytes()
commit=oid('commit',raw_commit); assert commit=='d25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
headers=raw_commit.split(b'\n\n',1)[0].splitlines()
assert headers[0]==b'tree a489b394666b8141840275128a780605b024cde0'
assert [x for x in headers if x.startswith(b'parent ')]==[b'parent cc57c7198db6293ccca562253c42fffbe2a04633']
def native(rows):
    return [{'path':e['path'],'mode':e['index_mode'],'bytes':e['bytes'],'sha256':e['sha256'],'blob':e['working_blob']} for e in sorted(rows,key=lambda e:os.fsencode(e['path']))]
baseline_native=compact(native(base['files']))
assert hashlib.sha256(baseline_native).hexdigest()=='20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9'
old={e['path']:e for e in base['files']}
rows=[]
for e in graph['files']:
    if e['kind']=='symlink':
        row=copy.deepcopy(old[e['path']])
        assert row['working_blob']==e['git_blob'] and row['index_mode']==e['mode'] and row['sha256']==e['sha256'] and row['bytes']==e['bytes']
    else:
        row={'bytes':e['bytes'],'index_blob':e['git_blob'],'index_mode':e['mode'],'kind':e['kind'],'matches_index':True,'path':e['path'],'permissions':int(e['mode'][-3:],8),'sha256':e['sha256'],'stable':True,'working_blob':e['git_blob']}
    rows.append(row)
rows.sort(key=lambda e:os.fsencode(e['path']))
expected=copy.deepcopy(base)
expected.update(files=rows,tracked_entries=len(rows),filesystem_entries=len(rows),source={'head':commit,'status':'','tree':graph['tree']})
full=compact(expected,True); projected=compact(native(rows))
assert full==(E/'EXPECTED_CLEAN_INVENTORY.json').read_bytes()
assert projected==(E/'EXPECTED_NATIVE_FIVE_FIELD.json').read_bytes()
assert pin(full)['git_blob']=='f1e2d72f99093581403a2dcc91b55da22a33f905'
assert pin(projected)['git_blob']=='7647480c5ed06525e1661ac451d0ac0ff2b23ea7'
report={'format':'hepta-root-independent-expected-d256-inventory-review-v1','qualification':False,'expected_only_not_native_observation':True,'commit':commit,'tree':graph['tree'],'sole_parent':'cc57c7198db6293ccca562253c42fffbe2a04633','full_graph':pin(graph_raw),'base_complete_inventory':pin(base_raw),'baseline_native_projection':pin(baseline_native),'actual_commit_raw':pin(raw_commit),'expected_complete_inventory':pin(full),'expected_native_projection':pin(projected),'files':len(rows),'all_complete_expected_bytes_equal':True,'mode_kind_path_byte_and_blob_fields_verified':True,'non_executable_symlink_inventory_row_preserved_exactly':True,'H_calls':0,'tests_executed':0,'source_mutations':0,'real_authorized_task_chains':0}
out=(json.dumps(report,indent=2,sort_keys=True)+'\n').encode()
(R/'ROOT_D256_EXPECTED_INVENTORY_REVIEW.json').write_bytes(out)
print(json.dumps({'report':pin(out),'expected_complete':pin(full),'native':pin(projected),'status':'EXPECTED_ONLY_EXACT'}))
