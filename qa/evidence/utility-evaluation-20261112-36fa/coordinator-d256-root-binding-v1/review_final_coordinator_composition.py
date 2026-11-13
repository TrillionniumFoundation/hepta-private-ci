#!/usr/bin/env python3
"""Root independent byte composition and mode-aware Git Merkle verification; no execution of project code."""
import base64, gzip, hashlib, json
from collections import Counter
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
G = Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1')
B = Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1/CC57_INVENTORY.json')
A = R / 'ACTUAL_FMT_FINAL_INVENTORY.reconstructed.json'
OLD = Path('/tmp/hepta-36fa-at-b-composed-candidate-v1/EXACT_COMPOSED_OVERLAY.json')
PIN_FIELDS = ('bytes','git_blob','sha256')
ROW_FIELDS = ('path','kind','mode','bytes','git_blob','sha256')

def oid(kind, raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def pin(raw):
    return {'bytes':len(raw),'git_blob':oid('blob',raw),'sha256':hashlib.sha256(raw).hexdigest()}

def check(raw, expected):
    got = pin(raw)
    assert all(got[k] == expected[k] for k in PIN_FIELDS), (got,expected)
    return got

def read_json(path, expected_blob=None):
    raw=Path(path).read_bytes()
    if expected_blob:
        assert oid('blob',raw)==expected_blob, (str(path),pin(raw),expected_blob)
    return json.loads(raw),pin(raw)

def inventory_rows(d):
    result={}
    for e in d['files']:
        path=e['path']
        assert path not in result and e['stable']
        mode='120000' if e['kind']=='symlink' else format(0o100000 | (e['permissions'] & 0o777),'06o')
        assert mode in ('100644','100755','120000')
        result[path]={'path':path,'kind':e['kind'],'mode':mode,'bytes':e['bytes'],'git_blob':e['working_blob'],'sha256':e['sha256']}
    return result

def merkle(rows):
    nodes={'':{}}
    for path,e in rows.items():
        parts=path.split('/')
        assert not path.startswith('/') and all(x not in ('','.','..') for x in parts)
        parent=''
        for part in parts[:-1]:
            child=parent+'/'+part if parent else part
            nodes.setdefault(child,{})
            old=nodes[parent].setdefault(part,{'mode':'040000','type':'tree','path':part,'directory':child})
            assert old['type']=='tree'
            parent=child
        assert parts[-1] not in nodes[parent]
        nodes[parent][parts[-1]]={'mode':e['mode'],'type':'blob','path':parts[-1],'sha':e['git_blob']}
    out={}
    for directory in sorted(nodes,key=lambda x:(x.count('/')+(1 if x else 0),x),reverse=True):
        entries=[]
        for e in nodes[directory].values():
            e=dict(e)
            if e['type']=='tree':
                e['sha']=out[e.pop('directory')]['sha']
            entries.append(e)
        entries.sort(key=lambda e:(e['path']+('/' if e['type']=='tree' else '')).encode())
        raw=b''.join((('40000' if e['type']=='tree' else e['mode'])+' '+e['path']).encode()+b'\0'+bytes.fromhex(e['sha']) for e in entries)
        out[directory]={'sha':oid('tree',raw),'raw':raw,'entries':entries}
    return out

def bundle_check(folder, manifest_name):
    d,_=read_json(folder/manifest_name)
    result=[]
    for bundle in d['bundles']:
        chunks=[]; offset=0
        for e in bundle['parts']:
            raw=Path(e['path']).read_bytes()
            check(raw,e)
            decoded=base64.b64decode(raw,validate=True)
            check(decoded,e['decoded'])
            assert e.get('decoded_offset',e.get('offset'))==offset
            offset+=len(decoded);chunks.append(decoded)
        compressed=b''.join(chunks)
        check(compressed,bundle['gzip'])
        recovered=gzip.decompress(compressed)
        check(recovered,bundle['raw'])
        result.append({'name':bundle['name'],'parts':len(chunks),'raw':pin(recovered),'gzip':pin(compressed)})
    return result

base,base_pin=read_json(B,'7f94788b70546a8b8030dfd2b9182a7d9287c537')
actual,actual_pin=read_json(A,'e1e48f35bb6cf5a3dd86c59472da77df87154b6a')
old,old_pin=read_json(OLD,'148e9efc242f3ee3ee4e525281ec170feecf3f19')
overlay,overlay_pin=read_json(G/'EXACT_COMPOSED_OVERLAY.json','9f6949a4b9fd6573f694ae20aa130453bebae00c')
graph,graph_pin=read_json(G/'CANDIDATE_FILE_GRAPH.json','097282896b5881614498faf2231e4c8c0da393c3')
plan,plan_pin=read_json(G/'TREE_OBJECT_PLAN.json','2a4a3f3330ac032e7e3d09c74e02f4449450dde5')
base_rows=inventory_rows(base); actual_rows=inventory_rows(actual); current=dict(actual_rows)
base_trees=merkle(base_rows); actual_trees=merkle(actual_rows)
assert base_trees['']['sha']=='b7b357c07b5539769a068c6b9b009629f5612d1e'
assert actual_trees['']['sha']=='f905b18e6b05de1582024548179725a05d932536'
covered={e['path'] for e in old['rust_files']+old['non_rust_prepared']}
assert len(covered)==110
actual_transitions=[]
for packet_path, expected_pin in [
('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json',overlay['actual_fmt62_packet']),
('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1/final.postimages.json',overlay['actual_retained_witness_packet'])]:
    raw=Path(packet_path).read_bytes();check(raw,expected_pin);d=json.loads(raw)
    for e in d['changes']:
        covered.add(e['path'])
        after=inventory_rows({'files':[e['after']]})[e['path']]
        assert actual_rows[e['path']]==after
        check(base64.b64decode(e['after_raw_base64'],validate=True),after)
    actual_transitions.append({'packet':pin(raw),'paths':len(d['changes'])})
layers=[]
for path,sha,tree in [
('/tmp/hepta-36fa-coordinator-f905-preparation-v1/SOURCE_PACKET.json','773d67128190fd2e1c3271c372f72e2a5537d1e8','a0bd2241a3a005b68a4682a339d2be016fa3fa72'),
('/tmp/hepta-36fa-coordinator-original-metadata-getters-v1/SOURCE_PACKET.json','5279a43b99aa7031343578a21dba895f5eac3188','2b423171ef3f1057ebaa081daf3ce42b78f467d7'),
('/tmp/hepta-36fa-coordinator-f905-registration-frozen-v1/SOURCE_PACKET.json','e01b6c1689e1d834701a0d4565c5da662936ea80','a489b394666b8141840275128a780605b024cde0')]:
    d,d_pin=read_json(path,sha); seen=set()
    for e in d['source_changes']:
        p=e['path']; assert p not in seen;seen.add(p);covered.add(p)
        before=e['before']; before_raw=e.get('before_base64')
        if before is None:
            assert p not in current and before_raw in (None,'')
        else:
            raw=base64.b64decode(before_raw,validate=True);check(raw,before)
            assert {k:current[p][k] for k in PIN_FIELDS}=={k:before[k] for k in PIN_FIELDS}
            assert current[p]['mode']==e['mode']
        raw=base64.b64decode(e['after_base64'],validate=True);check(raw,e['after'])
        current[p]={'path':p,'kind':'file','mode':e['mode'],**{k:e['after'][k] for k in PIN_FIELDS}}
    derived=merkle(current)['']['sha'];assert derived==tree
    layers.append({'packet':d_pin,'path_count':len(seen),'resulting_tree':derived})
final_trees=merkle(current)
expected_rows={e['path']:e for e in graph['files']}
assert len(expected_rows)==len(graph['files'])==15243
assert current==expected_rows
assert graph['tree']==final_trees['']['sha']=='a489b394666b8141840275128a780605b024cde0'
assert graph['base_commit']=='cc57c7198db6293ccca562253c42fffbe2a04633' and graph['candidate_commit'] is None
assert not graph['canonical_source_deletions']
coverage=overlay['rust_files']+overlay['non_rust_prepared']
assert {e['path'] for e in coverage}==covered and len(coverage)==len(covered)==119
for e in coverage:
    row={k:e[k] for k in ROW_FIELDS}
    assert current[e['path']]==row
    check(Path(e['local_source']).read_bytes(),e)
    assert e['mode']=='100644'
updates={}
for label,rows,fn,count in [('cc57',base_rows,'EXACT_UPDATE_ENTRIES_CC57.json',118),('f905',actual_rows,'EXACT_UPDATE_ENTRIES_F905.json',16)]:
    assert rows.keys()<=current.keys()
    changed=sorted(p for p in current if current[p]!=rows.get(p))
    recorded,_=read_json(G/fn)
    assert [e['path'] for e in recorded]==changed and len(changed)==count
    for e in recorded:
        assert e['before']==rows.get(e['path']) and e['after']==current[e['path']]
        assert e['change']==('added' if e['before'] is None else 'modified')
    updates[label]={'count':len(changed),'added':sum(p not in rows for p in changed),'modified':sum(p in rows for p in changed)}
changed_dirs={p for p in final_trees if p not in base_trees or base_trees[p]['sha']!=final_trees[p]['sha']}
assert changed_dirs=={e['directory'] for e in plan['trees']} and len(changed_dirs)==10
for e in plan['trees']:
    actual_tree=final_trees[e['directory']]
    raw=base64.b64decode(e['raw_base64'],validate=True)
    assert raw==actual_tree['raw'] and e['entries']==actual_tree['entries']
    check(raw,e['raw'])
    assert e['sha']==oid('tree',raw)==actual_tree['sha']
    assert e['base_tree']==base_trees[e['directory']]['sha']
counts={'files':len(current),'kinds':dict(Counter(e['kind'] for e in current.values())),'modes':dict(Counter(e['mode'] for e in current.values())),
        'rust_all_repository':sum(p.endswith('.rs') for p in current),'rust_under_codex_rs':sum(p.startswith('codex-rs/') and p.endswith('.rs') for p in current),
        'rust_outside_codex_rs':sum(not p.startswith('codex-rs/') and p.endswith('.rs') for p in current),'unique_blob_objects':len({e['git_blob'] for e in current.values()})}
assert counts==graph['counts']==overlay['full_repository_expected_counts']
bundles=bundle_check(G,'MANIFEST.json')+bundle_check(Path('/tmp/hepta-36fa-coordinator-f905-registration-frozen-v1'),'MANIFEST.json')
out={'format':'hepta-root-independent-final-candidate-composition-review-v1','qualification':False,'status':'EXACT_IMMUTABLE_SOURCE_COMPOSITION_VERIFIED_NOT_EXECUTED','base_inventory':base_pin,'actual_f905_inventory':actual_pin,'old_overlay':old_pin,'final_overlay':overlay_pin,'final_graph':graph_pin,'tree_plan':plan_pin,'layers':layers,'actual_retained_transitions':actual_transitions,'root_verifier_diagnostic_history':['Initial independent coverage union omitted the retained actual fix witness; assertion stopped. Corrected by verifying and including both original actual transition packets. No project source, H request, or evidence result was altered.'],'full_source_tree':final_trees['']['sha'],'counts':counts,'updates':updates,'covered_paths':119,'changed_directory_trees':10,'unchanged_directory_trees':len(final_trees)-10,'full_bounded_bundle_roundtrips':bundles,'all_other_source_rows_preserved':True,'deletions':[],'source_ref_writes':0,'H_calls':0,'tests_executed':0,'normal_root_host_wiring_complete':False,'real_authorized_task_chains':0}
(R/'ROOT_FINAL_COORDINATOR_COMPOSITION_REVIEW.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
print(json.dumps({'result':'PASS exact byte and tree composition only','tree':out['full_source_tree'],'counts':counts,'updates':updates,'report':pin((R/'ROOT_FINAL_COORDINATOR_COMPOSITION_REVIEW.json').read_bytes())}))
