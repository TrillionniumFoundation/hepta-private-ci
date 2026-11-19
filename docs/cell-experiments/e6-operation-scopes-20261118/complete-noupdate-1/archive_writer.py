import pathlib,json,hashlib,tarfile,io,os,stat,time,sys
base=pathlib.Path('/home/qq/work/hepta-e6-operation-scope-20261118-2e9b');source=base/'complete-noupdate-1';out=base/'retained-complete-noupdate-1'
assert os.geteuid()==0 and not out.exists()
assert hashlib.sha256((source/'result.json').read_bytes()).hexdigest()=='2a33bd0236ff63efdb5a8174e4840927bf60763fe2db1cbd02a85c5b358786b9'
v=json.loads((source/'result.json').read_text());assert v['status']=='completed' and not v['successful'] and v['source_unchanged'] and v['mount_cleanup_successful']
rows=[];contents={}
def add(p,name,expected=None):
 st=p.lstat();assert stat.S_ISREG(st.st_mode) and not p.is_symlink(),str(p)
 b=p.read_bytes();h=hashlib.sha256(b).hexdigest();after=p.stat();assert (st.st_ino,st.st_dev,st.st_size,st.st_mtime_ns)==(after.st_ino,after.st_dev,after.st_size,after.st_mtime_ns)
 if expected:assert h==expected['sha256'] and len(b)==expected['bytes']
 assert name not in contents;contents[name]=b;rows.append({'member':name,'original_path':str(p),'bytes':len(b),'sha256':h,'mode':oct(stat.S_IMODE(st.st_mode)),'uid':st.st_uid,'gid':st.st_gid,'mtime_ns':st.st_mtime_ns})
for p in sorted(source.rglob('*')):
 if p.is_file():add(p,'owner/'+str(p.relative_to(source)))
for f in json.loads(sys.argv[1]):
 p=pathlib.Path(f['path']);add(p,'native-child-logs/'+p.parent.name+'/'+p.name,f)
job=pathlib.Path('/home/qq/.local/state/hepta-runtime-mac-worker/jobs/1a1f05d7f3b-ffbe-78e')
for name in ['request.json','started.json','exit.json','exit.witness.json']:
 p=job/name
 if p.exists():add(p,'original-execution/'+name)
for p in [base/'complete-noupdate-DEPLOYMENT.json',base/'noupdate1-permission-readback.json']:
 add(p,'bindings/'+p.name)
index={'schema':'hepta.original-failed-noupdate-archive.v1','created_at_ns':time.time_ns(),'source_commit':'ab12b8bc1e6761efc16ea8c64e839721739cef5f','original_result_sha256':'2a33bd0236ff63efdb5a8174e4840927bf60763fe2db1cbd02a85c5b358786b9','originals':rows,'scope':'Complete first failed owner directory, all six retained original native child stdout/stderr files, original job identity/exit files when present, exact deployment and permission readback. Large compiled executables stay at their original pinned paths and hashes in the original manifests. This is not a whole-host snapshot.','archive_headers_normalized':True,'original_files_or_modes_modified':False}
ib=(json.dumps(index,sort_keys=True,indent=2)+'\n').encode();out.mkdir(mode=0o700);os.chown(out,1000,1000)
p=out/'originals.tar.gz'
with tarfile.open(p,'w:gz',format=tarfile.PAX_FORMAT) as t:
 for name,b in sorted({**contents,'INDEX.json':ib}.items()):
  info=tarfile.TarInfo(name);info.size=len(b);info.mode=0o644;info.uid=info.gid=0;info.mtime=0;t.addfile(info,io.BytesIO(b))
with tarfile.open(p,'r:gz') as t:
 expected={**contents,'INDEX.json':ib};assert set(t.getnames())==set(expected)
 for name,b in expected.items():assert t.extractfile(name).read()==b
for row in rows:assert hashlib.sha256(pathlib.Path(row['original_path']).read_bytes()).hexdigest()==row['sha256']
(out/'INDEX.json').write_bytes(ib)
receipt={'archive_path':str(p),'archive_bytes':p.stat().st_size,'archive_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'index_sha256':hashlib.sha256(ib).hexdigest(),'original_files':len(rows),'all_members_verified':True,'all_originals_rechecked':True,'zero_model_or_native_calls':True,'created_at_ns':time.time_ns()}
(out/'ARCHIVE.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
for f in out.iterdir():os.chown(f,1000,1000)
print(json.dumps(receipt))
