from pathlib import Path
import json,base64,hashlib,gzip
P=Path('/tmp/hepta-36fa-a96-recovery');Q=Path('/tmp/hepta-36fa-root-postformat-review')
maps=json.loads((P/'SNAPSHOT_LEAVES.recovered.json').read_bytes())
parts=b''.join((Q/f'prepared.part{i}.jsonfrag').read_bytes()[:-1] for i in range(5))
assert hashlib.sha256(parts).hexdigest()=='05e3a7b01f5814e0816fe8d521c68f55fddc64536e62fcedca7934e0832cb055'
packet=json.loads(parts);meta={r['sha']:{k:r[k] for k in ('bytes','sha256')} for rows in maps.values() for r in rows}
for o in packet['objects']:
 r=base64.b64decode(o['raw_base64'],validate=True)
 assert len(r)==o['bytes'] and hashlib.sha256(r).hexdigest()==o['sha256']
 assert hashlib.sha1(o['type'].encode()+b' '+str(len(r)).encode()+b'\0'+r).hexdigest()==o['sha']
 if o['type']=='blob':meta[o['sha']]={k:o[k] for k in ('bytes','sha256')}
final={r['path']:r for r in maps['a96d1b821d10ed3d9e99dd06c5141f9f242ae318']}
for c in packet['changes']:
 before={k:final[c['path']][k] for k in ('path','mode','type','sha')} if c['path'] in final else None
 assert before==c['before']
 assert c['after'] is not None
 final[c['path']]={**c['after'],**meta[c['after']['sha']]}
assert len(final)==15188
files=[]
for path,r in sorted(final.items()):
 assert r['mode'] in ('100644','100755','120000')
 files.append({'path':path,'index_mode':r['mode'],'index_blob':r['sha'],'permissions':0o777 if r['mode']=='120000' else 0o755 if r['mode']=='100755' else 0o644,'kind':'symlink' if r['mode']=='120000' else 'file','bytes':r['bytes'],'sha256':r['sha256'],'working_blob':r['sha'],'stable':True,'matches_index':True})
source={'head':'86dd56a930277e0d1aef3e475e35c2b5d60b43b7','tree':'383ab85c39ef9d848252ef5c25922d13d9fae6c6','status':''}
value={'schema':'hepta.utility.desktop-source-gates.v1.inventory','source':source,'tracked_entries':15188,'filesystem_entries':15188,'files':files}
raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
result=json.loads((P/'fresh86dd-v2-actual-result.json').read_bytes());expected=result['destination_inventory']
def blob(r):return hashlib.sha1(b'blob '+str(len(r)).encode()+b'\0'+r).hexdigest()
assert len(raw)==expected['bytes'] and hashlib.sha256(raw).hexdigest()==expected['sha256'] and blob(raw)==expected['git_blob']
(P/'MATERIALIZED_86DD_INVENTORY.recovered.json').write_bytes(raw)
artifact=next(x for x in result['artifacts'] if x['name']=='TARGET.final.inventory.json.gz')
gz=gzip.compress(raw,mtime=0)
assert len(gz)==artifact['bytes'] and hashlib.sha256(gz).hexdigest()==artifact['sha256'] and blob(gz)==artifact['git_blob']
(P/'MATERIALIZED_86DD_INVENTORY.recovered.json.gz').write_bytes(gz)
originals={r['name']:r for r in result['artifacts']};out=P/'materialized-inventory-original-parts';out.mkdir(exist_ok=True);index=[]
for i,off in enumerate(range(0,len(gz),262144),1):
 name=f'TARGET.final.inventory.json.gz.part-{i:03d}.b64';encoded=base64.b64encode(gz[off:off+262144])+b'\n';e=originals[name]
 assert len(encoded)==e['bytes'] and hashlib.sha256(encoded).hexdigest()==e['sha256'] and blob(encoded)==e['git_blob']
 (out/name).write_bytes(encoded);index.append({'name':name,'path':str(out/name),'bytes':len(encoded),'sha256':e['sha256'],'git_blob':e['git_blob']})
(P/'materialized-inventory-original-part-index.json').write_text(json.dumps(index,indent=2)+'\n')
review={'scope':'Exact recovery of actual native final physical inventory; not a new physical observation or a replacement of actual original hashes','actual_result':'456f749e7558e18df99172d9c9273cda890b8feb','actual_native_job':'1a1d0c6996e-2564-1bc8','source':source,'raw_bytes':len(raw),'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_git_blob':blob(raw),'gzip_bytes':len(gz),'gzip_sha256':hashlib.sha256(gz).hexdigest(),'gzip_git_blob':blob(gz),'full_original_raw_and_gzip_identities_matched':True,'file_count':len(files),'encoded_parts':len(index),'qualification':False}
(P/'MATERIALIZED_INVENTORY_RECOVERY_REVIEW.json').write_text(json.dumps(review,indent=2)+'\n');print(json.dumps(review))
