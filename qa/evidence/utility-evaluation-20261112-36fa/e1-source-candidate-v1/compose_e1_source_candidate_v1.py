from pathlib import Path
import hashlib
import json

BASE_HEAD='b6084394a4a38ab495c16eaba09e879f04a96f8e'
BASE_TREE='8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
R=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
P=Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
D=Path('/tmp/hepta-36fa-e1-source-candidate-v1')

def pin(b):
    return {'bytes':len(b),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'sha256':hashlib.sha256(b).hexdigest()}

def encode(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()

def write(name,b):
    path=D/name
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(b)
    assert path.read_bytes()==b
    return pin(b)

def trees(files):
    root={}
    for path,row in files.items():
        at=root
        parts=path.split('/')
        for name in parts[:-1]:at=at.setdefault(name,{})
        assert parts[-1] not in at
        at[parts[-1]]=(row['mode'],row['git_blob'])
    entries={}
    def node(at,path):
        out=[]
        for name,value in at.items():
            if isinstance(value,dict):
                out.append({'path':name,'mode':'040000','type':'tree','sha':node(value,(path+'/' if path else '')+name)})
            else:out.append({'path':name,'mode':value[0],'type':'blob','sha':value[1]})
        out.sort(key=lambda e:(e['path']+('/' if e['type']=='tree' else '')).encode())
        body=b''.join((('40000' if e['type']=='tree' else e['mode'])+' '+e['path']).encode()+b'\0'+bytes.fromhex(e['sha']) for e in out)
        sha=hashlib.sha1(b'tree '+str(len(body)).encode()+b'\0'+body).hexdigest()
        entries[path]={'sha':sha,'entries':out}
        return sha
    return node(root,''),entries

graph_path=R/'PROPOSED_NONRUST_8EBB_GRAPH.json'
graph_raw=graph_path.read_bytes()
base={row['path']:row for row in json.loads(graph_raw)['files']}
assert len(base)==15243
actual_base_tree,base_trees=trees(base)
assert actual_base_tree==BASE_TREE
packets={}
for name in ('assembled-source-v1','request-type-import-increment-v1','registration-proposal-v1'):
    raw=(P/name/'SOURCE_PACKET.json').read_bytes()
    packets[name]={'pin':pin(raw),'value':json.loads(raw)}
assembled=packets['assembled-source-v1']['value']
assert assembled['manifest']['baseline']=={'head':BASE_HEAD,'status':'','tree':BASE_TREE}
images={}
for image in assembled['images']:
    path=image['path'];assert path not in images
    assert path.startswith('codex-rs/hepta-agentd/src/') and path.endswith('.rs')
    images[path]=dict(image)
    old=image['before']
    if old is None:assert path not in base
    else:
        expected=base[path];assert pin(old.encode())=={k:expected[k] for k in ('bytes','git_blob','sha256')}
for image in packets['request-type-import-increment-v1']['value']['images']:
    assert images[image['path']]['after']==image['before']
    images[image['path']]['after']=image['after']
for image in packets['registration-proposal-v1']['value']['images']:
    path=image['path'];assert path not in images
    old=image['before']
    if old is None:assert path not in base
    else:
        expected=base[path];assert pin(old.encode())=={k:expected[k] for k in ('bytes','git_blob','sha256')}
    images[path]=dict(image)
assert len(images)==19
full=dict(base);delta=[]
D.mkdir(mode=0o700)
for path,image in sorted(images.items()):
    raw=image['after'].encode();after=pin(raw)
    if path in base:assert base[path]['mode']=='100644'
    before=None if image['before'] is None else pin(image['before'].encode())
    assert before!=after
    full[path]={'path':path,'kind':'file','mode':'100644',**after}
    write('after/'+path,raw)
    delta.append({'path':path,'mode':'100644','before':before,'after':after})
root,all_trees=trees(full)
changed={path:node for path,node in all_trees.items() if path not in base_trees or base_trees[path]['sha']!=node['sha']}
assert len(full)==15251
for path,row in base.items():
    if path not in images:assert full[path]==row
manifest={'format':'hepta-e1-exact-source-candidate-v1','status':'PREQUALIFICATION_SOURCE_CANDIDATE_NOT_FORMATTED_COMPILED_EXECUTED_OR_DEPLOYED','base_head':BASE_HEAD,'base_tree':BASE_TREE,'base_graph':pin(graph_raw),'input_packets':{k:v['pin'] for k,v in packets.items()},'files':delta,'files_before':len(base),'files_after':len(full),'unchanged_original_files':len(base)-sum(x['before'] is not None for x in delta),'modified_original_files':sum(x['before'] is not None for x in delta),'new_files':sum(x['before'] is None for x in delta),'tree':root,'changed_tree_nodes':len(changed),'source_branch_updated':False,'H_directory_changed':False,'qualification':False,'real_qualified_task_chains':0,'original_b608_execution_contract_unchanged':True,'candidate_execution_request':None}
man=write('MANIFEST.json',encode(manifest))
tr=write('EXPECTED_CHANGED_TREES.json',encode(changed))
write('EXPECTED_FULL_SOURCE_GRAPH.json',encode({'format':'hepta-e1-expected-source-graph-v1','base':BASE_HEAD,'tree':root,'qualification':False,'files':[full[x] for x in sorted(full)]}))
print(json.dumps({'manifest':man,'tree':root,'changed_trees':tr,'files_before':len(base),'files_after':len(full),'delta':len(delta),'unchanged_original_files':manifest['unchanged_original_files'],'modified_original_files':manifest['modified_original_files'],'new_files':manifest['new_files'],'changed_tree_nodes':len(changed)},sort_keys=True))
