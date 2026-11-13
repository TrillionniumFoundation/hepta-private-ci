#!/usr/bin/env python3
"""Independent offline parser of captured 5a9 bytes. No Git command or live lstat."""
from pathlib import Path
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
import re
import struct

HERE = Path(__file__).resolve().parent
NATIVE = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
RECOVERY = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1')
ROOT_INPUTS = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1')
CURRENT = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
def ident(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def pin(raw, expected):
    assert ident(raw)=={key:expected[key] for key in ('bytes','sha256','git_blob')}, (ident(raw),expected)
def rawpin(row):return {key:row['raw_'+key] for key in ('bytes','sha256','git_blob')}
def oid(kind,raw):return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def get(name):return (HERE/'inputs'/name).read_bytes()
def getj(name):return json.loads(get(name))

fetch_index=json.loads((HERE/'FULL_GET_CONTENT_INDEX.json').read_text())
fetched=[]
for row in fetch_index:
    raw=get(row['name']);assert ident(raw)['git_blob']==row['git_blob']
    fetched.append({'name':row['name'],**ident(raw),'independent_actual_full_get':True})
catalog_rows=getj('ARTIFACTS.json'); catalog={r['name']:r for r in catalog_rows}
assert len(catalog)==len(catalog_rows)
actual=getj('RESULT.json')
assert actual['source_repo']==CURRENT

def restore_index(label):
    name='INDEX.'+label+'.raw.gz'; row=catalog[name]; compressed=[]; offset=0
    for part in row['parts']:
        text=get(part['name']);pin(text,part)
        assert text.endswith(b'\n') and text.count(b'\n')==1
        raw=base64.b64decode(text[:-1],validate=True)
        assert part['decoded_offset']==offset and part['decoded_bytes']==len(raw)
        assert hashlib.sha256(raw).hexdigest()==part['decoded_sha256']
        assert base64.b64encode(raw)+b'\n'==text
        compressed.append(raw);offset+=len(raw)
    compressed=b''.join(compressed);pin(compressed,row)
    raw=gzip.decompress(compressed);pin(raw,rawpin(row))
    assert compressed==(NATIVE/'artifacts'/name).read_bytes()
    assert raw==(NATIVE/'artifacts'/('INDEX.'+label+'.raw')).read_bytes()
    return raw, {'gzip':ident(compressed),'raw':ident(raw),'parts':[p['git_blob'] for p in row['parts']],
                 'exact_original_native_raw_equal':True,'new_native_read':False}

def parse_index(raw):
    assert len(raw)>=32 and raw[:4]==b'DIRC'
    version,count=struct.unpack_from('>II',raw,4)
    assert version==2 and count==15243 and hashlib.sha1(raw[:-20]).digest()==raw[-20:]
    at=12; entries={}; previous=None
    for _ in range(count):
        begin=at;assert at+62<=len(raw)-20
        numbers=struct.unpack_from('>10I',raw,at); blob=raw[at+40:at+60].hex(); flags=struct.unpack_from('>H',raw,at+60)[0]
        end=raw.index(b'\0',at+62,len(raw)-20); name=raw[at+62:end]
        path=name.decode('utf-8','strict'); assert path.encode()==name
        assert name and not name.startswith(b'/') and all(p not in (b'',b'.',b'..',b'.git') for p in name.split(b'/'))
        assert previous is None or previous<name;previous=name
        assert not flags&0xf000 and flags==min(len(name),0xfff)
        assert numbers[1]<1000000000 and numbers[3]<1000000000
        mode=format(numbers[6],'o');assert mode in ('100644','100755','120000')
        at=begin+((end+1-begin+7)//8)*8
        assert at<=len(raw)-20 and raw[end:at]==b'\0'*(at-end) and path not in entries
        entries[path]={'path':path,'mode':mode,'sha':blob,'flags':flags,'stat':list(numbers),
                       'raw_entry_sha256':hashlib.sha256(raw[begin:at]).hexdigest()}
    extensions=[]
    while at<len(raw)-20:
        assert at+8<=len(raw)-20
        label=raw[at:at+4].decode('ascii');size=struct.unpack_from('>I',raw,at+4)[0]
        end=at+8+size;assert end<=len(raw)-20
        extensions.append({'name':label,'bytes':size,'sha256':hashlib.sha256(raw[at:end]).hexdigest(),
                           'payload':raw[at+8:end]});at=end
    assert at==len(raw)-20 and len(entries)==count
    assert [r['name'] for r in extensions]==['TREE']
    return entries,extensions,{'signature':'DIRC','version':version,'entries':count,'checksum':raw[-20:].hex(),
                               'checksum_verified':True,'complete_payload_consumed':True,
                               'all_paths_unique_sorted_utf8':True,'normal_stage_zero_flags':True,
                               'extensions':[{k:v for k,v in r.items() if k!='payload'} for r in extensions]}

def merkle(entries):
    root={}
    for path,row in entries.items():
        parts=path.split('/');node=root
        for part in parts[:-1]:
            if part not in node:node[part]={}
            assert isinstance(node[part],dict);node=node[part]
        assert parts[-1] not in node;node[parts[-1]]=(row['mode'],row['sha'])
    trees={}
    def visit(node,path):
        chunks=[];leaves=0;children=0
        for name,value in sorted(node.items(),key=lambda pair:pair[0].encode()+ (b'/' if isinstance(pair[1],dict) else b'')):
            if isinstance(value,dict):
                sub=visit(value,path+'/'+name if path else name);mode='40000';digest=sub['sha'];leaves+=sub['entries'];children+=1
            else:mode,digest=value;leaves+=1
            chunks.append(mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(digest))
        body=b''.join(chunks);record={'path':path,'sha':oid('tree',body),'entries':leaves,'children':children}
        trees[path]=record;return record
    root_record=visit(root,'')
    return root_record['sha'],trees

def cache_tree(payload,expected):
    at=0;rows={};invalid=[]
    def read_node(parent,is_root=False):
        nonlocal at
        end=payload.index(b'\0',at);name=payload[at:end];at=end+1
        assert (is_root and name==b'') or (name and b'/' not in name and name not in (b'.',b'..'))
        end=payload.index(b'\n',at);counts=payload[at:end].split(b' ');at=end+1
        assert len(counts)==2 and re.fullmatch(rb'-?\d+',counts[0]) and re.fullmatch(rb'\d+',counts[1])
        count,children=map(int,counts);assert count>=-1
        path=name.decode('utf-8') if not parent else parent+'/'+name.decode('utf-8')
        digest=None
        if count>=0:
            assert at+20<=len(payload);digest=payload[at:at+20].hex();at+=20
        else:invalid.append(path)
        assert path not in rows; rows[path]={'path':path,'sha':digest,'entries':count,'children':children}
        for _ in range(children):read_node(path)
    read_node('',True);assert at==len(payload)
    assert set(rows)==set(expected), (len(rows),len(expected))
    assert not invalid, invalid
    for path,row in rows.items():assert row==expected[path],(path,row,expected[path])
    return rows,{'complete_payload_consumed':True,'records':len(rows),'invalid_records':len(invalid),
                 'all_directory_counts_and_typed_tree_ids_equal':True,
                 'full_records_sha256':hashlib.sha256(encoded([rows[k] for k in sorted(rows,key=os.fsencode)])).hexdigest()}

index={}; parsed={}; exts={}; tree_maps={}; caches={}; summaries={}; recovery={}
inventory={}; invpins={}
for label in ('before','final'):
    index[label],recovery[label]=restore_index(label)
    parsed[label],exts[label],summaries[label]=parse_index(index[label])
    root,tree_maps[label]=merkle(parsed[label]);caches[label],cache_summary=cache_tree(exts[label][0]['payload'],tree_maps[label])
    assert root==actual['before' if label=='before' else 'after']['tree']
    summaries[label].update(tree=root,tree_count=len(tree_maps[label]),cache_tree=cache_summary)
    inv_raw=(RECOVERY/('SOURCE.'+label+'.inventory.exact_recovered.json')).read_bytes()
    invpin=rawpin(catalog['SOURCE.'+label+'.inventory.json.gz']);pin(inv_raw,invpin)
    inv=json.loads(inv_raw);assert inv['tracked_entries']==inv['filesystem_entries']==len(inv['files'])==15243
    rows={r['path']:r for r in inv['files']};assert len(rows)==15243 and set(rows)==set(parsed[label])
    for path,row in rows.items():
        ent=parsed[label][path]
        assert (row['index_mode'],row['index_blob'])==(ent['mode'],ent['sha'])
        if label=='final':
            assert row['matches_index'] is True and row['stable'] is True and row['working_blob']==ent['sha']
            mode='120000' if row['kind']=='symlink' else '100755' if row['permissions']&0o111 else '100644'
            assert mode==ent['mode']
    inventory[label]=rows;invpins[label]=ident(inv_raw)
    assert invpins[label]=={k:actual['before' if label=='before' else 'after']['inventory'][k] for k in ('bytes','sha256','git_blob')}
assert all({k:v for k,v in row.items() if k not in ('index_mode','index_blob','matches_index')}==
           {k:v for k,v in inventory['final'][p].items() if k not in ('index_mode','index_blob','matches_index')}
           for p,row in inventory['before'].items())

changed=[p for p in parsed['before'] if parsed['before'][p]['raw_entry_sha256']!=parsed['final'][p]['raw_entry_sha256']]
delta=[]
for p in changed:
    a,b=parsed['before'][p],parsed['final'][p]
    row={'path':p}
    for side,value in [('before',a),('after',b)]:
        row.update({side+'_mode':value['mode'],side+'_sha':value['sha'],side+'_flags':value['flags'],
                    side+'_stat':value['stat'],side+'_raw_sha256':value['raw_entry_sha256']})
    delta.append(row)
assert len(delta)==21 and delta==getj('INDEX.complete-entry-delta.json') and encoded(delta)==get('INDEX.complete-entry-delta.json')
pin(get('INDEX.complete-entry-delta.json'),rawpin(catalog['INDEX.complete-entry-delta.json.gz']))
audit_raw=(NATIVE/'recovered-index-audit/INDEX.final.audit.json').read_bytes()
pin(audit_raw,rawpin(catalog['INDEX.final.audit.json.gz']))
audit=json.loads(audit_raw)
assert audit['entry_count']==15243 and audit['all_entries_equal_canonical_tree'] is True
assert audit['all_stat_fields_match_actual_files'] is True and actual['actual']['normal_stat_refresh_verified'] is True
assert audit['entries']==list(parsed['final'].values())
assert audit['extensions']==[{k:v for k,v in r.items() if k!='payload'} for r in exts['final']]
reconstructed_audit={'entry_count':15243,'all_entries_equal_canonical_tree':True,
 'all_stat_fields_match_actual_files':audit['all_stat_fields_match_actual_files'],
 'entries':list(parsed['final'].values()),'extensions':audit['extensions']}
assert encoded(reconstructed_audit)==audit_raw

def validate_metadata(value):
    assert set(value)=={'root','files'} and value['root']==CURRENT+'/.git'
    rows=value['files']; assert rows==sorted(rows,key=lambda row:os.fsencode(row['path']))
    bypath={}
    common={'path','kind','mode','uid','gid','device','inode','nlink','mtime_ns','ctime_ns'}
    for row in rows:
        p=row['path'];assert isinstance(p,str) and '\0' not in p and all(x not in ('','.','..') for x in p.split('/'))
        assert p not in bypath and row['kind'] in ('file','directory')
        assert set(row)==common|({'bytes','sha256'} if row['kind']=='file' else set())
        assert all(type(row[k]) is int for k in common-{'path','kind'})
        assert row['uid']==row['gid']==1000 and row['device']==2050 and row['nlink']>=1
        if row['kind']=='file':assert row['nlink']==1 and type(row['bytes']) is int and re.fullmatch('[0-9a-f]{64}',row['sha256'])
        bypath[p]=row
    for p in bypath:
        parent=p.rpartition('/')[0];assert not parent or parent in bypath and bypath[parent]['kind']=='directory'
    return bypath

metadata={}; states={}
for label in ('before','final'):
    raw=get('GIT_METADATA.'+label+'.json');pin(raw,rawpin(catalog['GIT_METADATA.'+label+'.json.gz']))
    metadata[label]=validate_metadata(json.loads(raw));states[label]=getj('GIT_STATE.'+label+'.json')
    state=states[label];meta=metadata[label]
    assert ident(index[label])['bytes']==state['index_bytes']==meta['index']['bytes']
    assert ident(index[label])['sha256']==state['index_sha256']==meta['index']['sha256']
    head=(state['head']+'\n').encode(); assert len(head)==meta['HEAD']['bytes']==41
    assert hashlib.sha256(head).hexdigest()==state['head_raw_sha256']==meta['HEAD']['sha256']
    assert (meta['config']['bytes'],meta['config']['sha256'])==(state['config_bytes'],state['config_sha256'])
    assert summaries[label]['tree']==state['tree'] and state==actual['before' if label=='before' else 'after']['git_state']
    assert state['refs_bytes']==0 and state['refs_sha256']==hashlib.sha256(b'').hexdigest()
    assert not any(p.startswith('refs/') and r['kind']=='file' for p,r in meta.items()) and 'packed-refs' not in meta
assert metadata['before']['config']==metadata['final']['config']
assert set(metadata['before'])<=set(metadata['final'])
metadata_delta=[{'path':p,'before':metadata['before'].get(p),'after':metadata['final'].get(p)}
                for p in sorted(set(metadata['before'])|set(metadata['final'])) if metadata['before'].get(p)!=metadata['final'].get(p)]
assert metadata_delta==getj('GIT_METADATA.allowed-actual-delta.json')==actual['git_metadata_actual_changes']
assert encoded(metadata_delta)==get('GIT_METADATA.allowed-actual-delta.json')

packet_raw=(ROOT_INPUTS/'CANONICAL_PACKET.json').read_bytes()
assert ident(packet_raw)['git_blob']=='bb4b4abd809047be4c9402b95fa2a2dc30b2ab78'
packet=json.loads(packet_raw);assert len(packet['objects'])==29
object_ids={obj['sha'] for obj in packet['objects']}; assert len(object_ids)==29
new=set(metadata['final'])-set(metadata['before'])
allowed_files={'objects/'+sha[:2]+'/'+sha[2:] for sha in object_ids}
allowed_dirs={'objects/'+sha[:2] for sha in object_ids}
assert new==allowed_files|allowed_dirs
for row in metadata_delta:
    p=row['path'];a,b=row['before'],row['after']
    if p in ('HEAD','index'):assert b['kind']=='file' and b['mode']==0o600 and b['nlink']==1
    elif a is None:assert p in allowed_files|allowed_dirs
    else:
        assert p=='objects' and b['kind']=='directory'
        assert all(a[k]==b[k] for k in a if k not in ('mtime_ns','ctime_ns','nlink'))

# Independently generate V5 DFS bytes, then compare the exact frozen admission's
# pure projector. Neither implementation observes native/current filesystem state.
def project_v5(value):
    rows={r['path']:r for r in value['files']};children={}
    for p in rows:children.setdefault(p.rpartition('/')[0],[]).append(p)
    result=[];stack=iter(())
    def visit(parent):
        for p in sorted(children.get(parent,[]),key=lambda p:os.fsencode(p.rsplit('/',1)[-1])):
            r=rows[p];result.append({k:v for k,v in r.items() if k not in ('uid','gid')})
            if r['kind']=='directory':visit(p)
    visit('');assert len(result)==len(rows)
    return (json.dumps({'format':'hepta-source-git-metadata-inventory-v1','root':value['root'],'files':result},
                       ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
code=(Path('/tmp/hepta-36fa-final-qualification-admission-code-independent-peer-v1/inputs/qualification-admission.HOLD.py')).read_bytes()
assert ident(code)['git_blob']=='c77e3be6230d3267c08333be582f69f23c016fb9'
tree=ast.parse(code);ns={'Path':Path,'CURRENT_REPO':CURRENT,'json':json,'os':os,'re':re}
for name in ['check','canonical_to_v5_projection']:
    node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<frozen-pure-metadata-projector>','exec'),ns)
projections={}
for label in ('before','final'):
    value=getj('GIT_METADATA.'+label+'.json');raw=project_v5(value)
    assert raw==ns['canonical_to_v5_projection'](value)
    projections[label]=ident(raw)
    if label=='before':
        assert ident(raw)['git_blob']=='42e3986f6a5f06d8518067f0d9dd2ec3e6b46c6a'
        old=Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/inputs/MAINTENANCE_41E_GIT_METADATA.json').read_bytes()
        assert raw==old
    else:
        with (HERE/'CANONICAL_FINAL_V5_PROJECTION.derived.json').open('xb') as f:f.write(raw)

cache_changed=[{'path':p,'before':caches['before'][p],'after':caches['final'][p]}
               for p in sorted(caches['before'],key=os.fsencode) if caches['before'][p]!=caches['final'][p]]
field_counts={k:sum(parsed['before'][p][k]!=parsed['final'][p][k] for p in parsed['before']) for k in ('mode','sha','flags','stat')}
result={'format':'hepta-5a9-index-metadata-independent-dataflow-v1',
 'scope':'Captured original bytes only; independent binary index/cache-tree/Merkle parser plus literal-data projection. No live lstat, Git command, H, project command, constructor or admission invocation.',
 'inputs_full_get':fetched,'indexes':summaries,'index_transport':recovery,
 'source_inventory_pins':invpins,'complete_physical_rows_equal':True,
 'entry_delta':{'count':len(delta),'unchanged_raw_entries':15243-len(delta),'fields_changed':field_counts,
                'full_original_delta_bytes_equal':True,'pin':ident(get('INDEX.complete-entry-delta.json')),'rows':delta},
 'cache_tree_changed':cache_changed,
 'recovered_audit':{'pin':ident(audit_raw),'all_15243_parsed_entries_equal':True,'full_raw_bytes_equal':True,
                    'original_artifact_raw_pin_equal':True,'stat_values_parsed_from_original_index':True,
                    'all_stat_fields_match_actual_files_claim_origin':'Unchanged original e8d606 validate_canonical_index used native lstat at 5a9; copied from original producer proof, not established by a new observer here.',
                    'new_lstat_calls':0},
 'metadata':{'before_pin':ident(get('GIT_METADATA.before.json')),'final_pin':ident(get('GIT_METADATA.final.json')),
              'before_rows':len(metadata['before']),'final_rows':len(metadata['final']),'delta_count':len(metadata_delta),
              'full_delta_bytes_equal':True,'removed_paths':[],
              'new_files':sorted(allowed_files),'new_directories':sorted(allowed_dirs),
              'changed_existing_paths':[r['path'] for r in metadata_delta if r['before'] is not None],
              'all_uid_gid_preserved_as_python_integers':True,'all_current_uid_gid':[1000,1000],
              'complete_raw_git_states_equal_result':True,'config_and_empty_refs_unchanged':True,
              'canonical_packet':ident(packet_raw),'v5_projections':projections,
              'before_projection_equals_actual_50f_42e398':True,
              'final_projection_is_derived_not_actual_v5_read':True},
 'H_calls':0,'live_filesystem_observer_calls':0,'project_commands':0,'qualification':False,
 'not_reviewed_here':['Same-job dispatch/normal and full command/intent/input chain (Root scope).','Runtime admission/qualification and the final late-bound request (separate review).']}
with (HERE/'INDEX_METADATA_DATAFLOW.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps({'indexes':2,'entries_each':15243,'before_tree':summaries['before']['tree'],'final_tree':summaries['final']['tree'],
 'cache_records_each':len(caches['final']),'cache_changed':len(cache_changed),'entry_delta':len(delta),'fields_changed':field_counts,
 'metadata_before':len(metadata['before']),'metadata_after':len(metadata['final']),'metadata_delta':len(metadata_delta),
 'final_v5_projection':projections['final'],'audit_raw_equal':True,'qualification':False},sort_keys=True))
