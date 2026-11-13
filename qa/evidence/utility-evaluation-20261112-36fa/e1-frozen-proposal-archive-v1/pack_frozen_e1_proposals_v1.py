from pathlib import Path
import base64
import gzip
import hashlib
import json
import os

SOURCE = Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
DEST = Path('/tmp/hepta-36fa-e1-frozen-proposal-archive-v1')
LAYERS = (
    'publication-layer-v1', 'lease-observation-increment-v1',
    'task-factory-layer-v1', 'protected-host-tests-layer-v1',
    'binding-request-increment-v1', 'assembled-source-v1',
    'request-type-import-increment-v1', 'registration-proposal-v1',
    'complete-review-v1',
)

def pin(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest()}

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()

def stat_key(value):
    return tuple(getattr(value, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink'))

def create(name, data):
    path=DEST/name
    with path.open('xb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    assert path.read_bytes()==data
    return {'name': name, **pin(data)}

records=[]
for layer in LAYERS:
    for path in sorted((SOURCE/layer).rglob('*')):
        if path.is_dir():
            continue
        assert path.is_file() and not path.is_symlink()
        before=path.stat()
        raw=path.read_bytes()
        assert stat_key(before)==stat_key(path.stat())
        records.append({'path': str(path.relative_to(SOURCE)), 'content_base64': base64.b64encode(raw).decode('ascii'), **pin(raw)})
assert len({x['path'] for x in records})==len(records)
packet=canonical({'format':'hepta-frozen-e1-proposal-bytes-v1','source_subject':'b6084394a4a38ab495c16eaba09e879f04a96f8e','status':'LOCAL_SOURCE_PROPOSAL_NOT_FORMATTED_COMPILED_EXECUTED_OR_INTEGRATED','qualification':False,'records':records})
compressed=gzip.compress(packet, compresslevel=9, mtime=0)
assert gzip.decompress(compressed)==packet
DEST.mkdir(mode=0o700)
parts=[]
for offset in range(0,len(compressed),300000):
    raw=compressed[offset:offset+300000]
    name=f'PACKET.json.gz.part-{len(parts)+1:03d}.b64'
    artifact=create(name,base64.b64encode(raw)+b'\n')
    parts.append({'offset':offset,'decoded':pin(raw),'artifact':artifact})
assert b''.join(base64.b64decode((DEST/p['artifact']['name']).read_bytes(),validate=False) for p in parts)==compressed
manifest={'format':'hepta-frozen-e1-proposal-archive-manifest-v1','layers':list(LAYERS),'input_files':len(records),'input_raw_bytes':sum(r['bytes'] for r in records),'packet':pin(packet),'gzip':pin(compressed),'parts':parts,'files':[{k:v for k,v in row.items() if k!='content_base64'} for row in records],'source_subject':'b6084394a4a38ab495c16eaba09e879f04a96f8e','source_tree':'8ebb37e523ad3932a58cf016af0a9f4e0eeb6638','source_ref_modified':False,'project_code_or_tests_executed':False,'qualification':False,'real_qualified_task_chains':0,'note':'Exact local proposal bytes retained before execution. This archive is not source integration or H approval.'}
artifact=create('MANIFEST.json',canonical(manifest))
print(json.dumps({'manifest':artifact,'parts':[p['artifact'] for p in parts],'input_files':len(records),'input_raw_bytes':manifest['input_raw_bytes'],'packet':manifest['packet'],'gzip':manifest['gzip']},sort_keys=True))
