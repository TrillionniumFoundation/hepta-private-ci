#!/usr/bin/env python3
"""Check frozen bytes only; does not run or import Rust/project tests."""
import hashlib
import json
import re
import difflib
from pathlib import Path
OUT=Path(__file__).resolve().parent
E2=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
L=E2/'bootstrap-receipt-tests-layer-v1'
V3=Path('/tmp/hepta-36fa-root-product-composition-v3')
P='codex-rs/hepta-agentd/src/'
def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def read(p):
    p=Path(p);a=p.stat();b=p.read_bytes();c=p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(c.st_dev,c.st_ino,c.st_size,c.st_mtime_ns,c.st_ctime_ns)
    return b
packet=read(L/'SOURCE_PACKET.json')
assert pin(packet)=={'bytes':35549,'sha256':'b1412eb987ffc9ca2a86bbc593808e158f7ef0a11f2346cb53dc7fca07c2194a','git_blob':'3ce8abde6fd4ddb09d1b020d0be1eb004cabbc54'}
j=json.loads(packet);assert len(j['entries'])==2
entries={e['path']:e for e in j['entries']};assert len(entries)==2
manifest_raw=read(L/'MANIFEST.json');manifest=json.loads(manifest_raw)
assert manifest['packet']==pin(packet)
assert manifest['entries']==[{k:e[k] for k in ('path','mode','before','after')} for e in j['entries']]
metadata=[]
for key,name in [('patch','SOURCE_DELTA.patch'),('review','REVIEW.json'),('registration','REGISTRATION_IMPACT.json')]:
    b=read(L/name);assert pin(b)==manifest[key];metadata.append({'path':str(L/name),**pin(b)})
ipc_raw=read(E2/'ipc-layer-v1/SOURCE_PACKET.json');assert pin(ipc_raw)['git_blob']=='06dafdbdeb53eb5ccf6480993596bbb4d939f203'
ipc={e['path']:e for e in json.loads(ipc_raw)['entries']}
parent=entries[P+'circuit_task_driver_tests.rs']
before=parent['before_utf8'].encode();after=parent['after_utf8'].encode()
assert pin(before)==parent['before']==ipc[parent['path']]['after']
assert before==ipc[parent['path']]['after_utf8'].encode()==read(E2/'ipc-layer-v1/after'/parent['path'])
mount=b'\n#[cfg(target_os = "linux")]\n#[path = "circuit_task_original_root_bootstrap_tests.rs"]\nmod original_root_bootstrap;\n'
assert after==before+mount and pin(after)==parent['after']
assert before==read(L/'before'/parent['path']) and after==read(L/'after'/parent['path'])
new=entries[P+'circuit_task_original_root_bootstrap_tests.rs']
assert new['before'] is None and new['before_utf8'] is None
newraw=new['after_utf8'].encode()
assert pin(newraw)==new['after'] and newraw==read(L/'after'/new['path'])
assert not (V3/'after'/new['path']).exists()
inv=Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
invraw=read(inv);assert pin(invraw)['git_blob']=='457adb9bf9ba3a844e9dfa149be49460bb306998'
assert new['path'] not in {e['path'] for e in json.loads(invraw)['files']}
patch=[]
for entry in j['entries']:
    a=entry['before_utf8'] or ''; b=entry['after_utf8']
    patch.extend(difflib.unified_diff(a.splitlines(True),b.splitlines(True),
        fromfile='a/'+entry['path'] if entry['before'] else '/dev/null',tofile='b/'+entry['path']))
assert ''.join(patch).encode()==read(L/'SOURCE_DELTA.patch')
methods=re.findall(rb'#\[(tokio::)?test\]\s*(?:async\s+)?fn\s+(\w+)\s*\(',newraw)
assert len(methods)==4 and sum(bool(a) for a,b in methods)==2
names=[b.decode() for a,b in methods]
registration=json.loads(read(L/'REGISTRATION_IMPACT.json'))
prefix='circuit_task::driver::tests::original_root_bootstrap::'
assert registration['new_test_fqns']==[prefix+n for n in names]
assert registration['production_boundaries_added']==[] and registration['ignored_root'] is False
assert newraw.count(b'driver.store.close().await;')==2
assert newraw.count(b'let body: anyhow::Result<()> = async {')==2
assert newraw.count(b'}.await;')==2
assert b'CircuitTaskReceiptV1 {' not in newraw
assert b'tokio::spawn' not in newraw and b'spawn_blocking' not in newraw
assert b'publish_original_remote_completion' not in newraw
dependencies=[]
for name in ['circuit_task_driver.rs','circuit_task_source_remote.rs']:
    path=P+name;body=read(E2/'ipc-layer-v1/after'/path)
    assert pin(body)==ipc[path]['after'] and body==ipc[path]['after_utf8'].encode()
    assert body==read(V3/'after'/path)
    dependencies.append({'path':str(E2/'ipc-layer-v1/after'/path),**pin(body),'same_current_v3_bytes':True})
ordinary_raw=read(E2/'ordinary-handoff-layer-v1/SOURCE_PACKET.json')
assert pin(ordinary_raw)['git_blob']=='65e62f807885cd890d8fa9944c58e232dc55ae01'
ordinary={e['path']:e for e in json.loads(ordinary_raw)['entries']}
for name in ['circuit_cell_registry_bootstrap.rs','circuit_task_root_bootstrap_cell.rs','circuit_task_root_bootstrap_codec.rs','circuit_task_source_codec.rs']:
    path=P+name;body=read(E2/'ordinary-handoff-layer-v1/after'/path)
    assert pin(body)==ordinary[path]['after'] and body==ordinary[path]['after_utf8'].encode()
    assert body==read(V3/'after'/path)
    dependencies.append({'path':str(E2/'ordinary-handoff-layer-v1/after'/path),**pin(body),'same_current_v3_bytes':True})
out={'format':'hepta-e2-bootstrap-receipt-test-layer-independent-byte-proof-v1',
 'packet':{'path':str(L/'SOURCE_PACKET.json'),**pin(packet)},'manifest':{'path':str(L/'MANIFEST.json'),**pin(manifest_raw)},
 'metadata':metadata,'entries':manifest['entries'],'parent_exact_original_prefix':True,'only_parent_suffix':mount.decode(),
 'patch_exact':True,'new_path_absent_canonical_and_v3':True,'methods':names,'ordinary_tests':2,'async_tests':2,
 'new_production_hooks':0,'dependencies':dependencies,
 'scope':'Static test-source semantics and complete bytes only. No test or project code executed.',
 'not_performed':['H','source/ref mutation','Rust compilation','fmt/fix','QA','test execution']}
b=(json.dumps(out,indent=2,sort_keys=True)+'\n').encode();(OUT/'BYTE_REVIEW.json').open('xb').write(b)
print(json.dumps({'result':'complete','report':str(OUT/'BYTE_REVIEW.json'),**pin(b),'test_methods':len(methods)}))
