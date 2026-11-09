import hashlib, io, json, os, re, stat, subprocess, tarfile, time
from pathlib import Path

work=Path('/workspace/scratch/d9bbb5ad0229/hepta-evidence-work')
ready=Path('/workspace/scratch/d9bbb5ad0229/hepta-evidence-ready')
ready.mkdir(exist_ok=True)
roots={
 'earlier-hepta-validation':Path('/workspace/scratch/ac851b3fedf0/hepta-validation'),
 'earlier-materials-probe':Path('/workspace/scratch/ac851b3fedf0/smollm-materials-probe'),
 'model-owner-readbacks':Path('/workspace/scratch/d9bbb5ad0229/model-validation'),
 'local-maintenance-validation':Path('/workspace/scratch/d9bbb5ad0229/hepta-scoped-validation'),
}
omitted=roots['earlier-hepta-validation']/'hepta-scoped-d81cb97c.tar.zst'
sha=lambda b:hashlib.sha256(b).hexdigest()
pattern=re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{30,}')
secret_fields={'private_key','secret_key','api_key','access_token','refresh_token','client_secret','password','signing_key'}
def secret_json(v):
 if isinstance(v,dict):
  for k,z in v.items():
   if k.lower() in secret_fields and isinstance(z,str) and len(z)>=8 and z not in ('redacted','REDACTED'):return True
   if secret_json(z):return True
 elif isinstance(v,list):return any(secret_json(z) for z in v)
 return False
records=[];exclusions=[];payloads={};counts={}
for label,root in roots.items():
 counts[label]={'files':0,'bytes':0};assert root.is_dir()
 for p in sorted(root.rglob('*')):
  st=p.lstat()
  if stat.S_ISDIR(st.st_mode):continue
  assert stat.S_ISREG(st.st_mode),p
  if p==omitted:continue
  with p.open('rb') as f:
   before=os.fstat(f.fileno());data=f.read();after=os.fstat(f.fileno())
  assert (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns),p
  rel=label+'/'+p.relative_to(root).as_posix();reasons=[]
  row={'path':rel,'source_path':str(p),'bytes':len(data),'sha256':sha(data),'source_mode':stat.S_IMODE(st.st_mode)}
  if pattern.search(data):reasons.append('credential-or-private-key-byte-pattern')
  if p.suffix=='.json':
   try:
    if secret_json(json.loads(data)):reasons.append('sensitive-json-field')
   except (UnicodeDecodeError,json.JSONDecodeError):pass
  counts[label]['files']+=1;counts[label]['bytes']+=len(data)
  if reasons:exclusions.append(dict(row,reasons=reasons))
  else:records.append(row);payloads[rel]=data
archive=ready/'local-validation-records.tar.zst';plain=work/'local-validation-records.tar'
assert not archive.exists() and not plain.exists()
with tarfile.open(plain,'w') as tf:
 for row in records:
  ti=tarfile.TarInfo(row['path']);ti.size=row['bytes'];ti.mode=row['source_mode'];ti.mtime=0
  tf.addfile(ti,io.BytesIO(payloads[row['path']]))
subprocess.run(['zstd','-8','--long=27','--threads=1','--quiet',str(plain),'-o',str(archive)],check=True)
unpacked=subprocess.run(['zstd','--decompress','--stdout',str(archive)],check=True,stdout=subprocess.PIPE).stdout
lookup={r['path']:r for r in records};seen=set()
with tarfile.open(fileobj=io.BytesIO(unpacked),mode='r:') as tf:
 for m in tf:
  assert m.isfile() and m.name in lookup and m.name not in seen
  data=tf.extractfile(m).read();row=lookup[m.name]
  assert len(data)==row['bytes'] and sha(data)==row['sha256'];seen.add(m.name)
assert seen==set(lookup)
for row in records+exclusions:assert sha(Path(row['source_path']).read_bytes())==row['sha256']
omitted_bytes=omitted.read_bytes()
index={
 'schema':'hepta-scoped-v2-local-record-recovery-v1','created_unix_ns':time.time_ns(),
 'status':'RAW_RECOVERED_AND_ARCHIVED_AFTER_WORKSPACE_RECONNECTED','roots':{k:str(v) for k,v in roots.items()},
 'groups':counts,'retained_files':len(records),'retained_bytes':sum(r['bytes'] for r in records),'files':records,'sensitive_exclusions':exclusions,
 'intentional_omissions':[{'path':str(omitted),'bytes':len(omitted_bytes),'sha256':sha(omitted_bytes),'reason':'compiled nextest archive excluded from source evidence; original metadata, contents inventory, ELF identity and transfer receipts retained'}],
 'archive':{'file':archive.name,'bytes':archive.stat().st_size,'sha256':sha(archive.read_bytes()),'compression':'zstd -8 --long=27 --threads=1'},
 'all_archive_member_sizes_and_hashes_verified':True,'all_original_hashes_still_equal':True,
 'historical_unavailable_observation_retained':'maintenance-records.index.json records the earlier unavailable observation; this recovery record supplements it without rewriting it',
 'model_or_test_reexecution':False,
}
(ready/'local-validation-records.index.json').write_text(json.dumps(index,indent=2)+'\n')
print(json.dumps({k:index[k] for k in ('status','groups','retained_files','retained_bytes','sensitive_exclusions','archive')},indent=2))
