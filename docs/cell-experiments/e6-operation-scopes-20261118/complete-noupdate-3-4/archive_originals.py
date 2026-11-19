import pathlib,json,hashlib,tarfile,io,os,stat,time
base=pathlib.Path('/home/qq/work/hepta-e6-operation-scope-20261118-2e9b');out=base/'retained-complete-noupdate-3-4'
assert os.geteuid()==0 and not out.exists()
expected={3:'b29560d8ec41398f2837b30effc5cd57aff00a65750a0e95e164be9af1dc7178',4:'78b1c6accdecdee1f7f95460393abbf1bc8d59322dded72d197db7a6f3004925'}
rows=[];contents={}
def add(p,name):
 st=p.lstat();assert stat.S_ISREG(st.st_mode) and not p.is_symlink(),str(p)
 b=p.read_bytes();h=hashlib.sha256(b).hexdigest();after=p.stat();assert (st.st_ino,st.st_dev,st.st_size,st.st_mtime_ns)==(after.st_ino,after.st_dev,after.st_size,after.st_mtime_ns)
 assert name not in contents;contents[name]=b;rows.append({'member':name,'original_path':str(p),'bytes':len(b),'sha256':h,'mode':oct(stat.S_IMODE(st.st_mode)),'uid':st.st_uid,'gid':st.st_gid,'mtime_ns':st.st_mtime_ns})
for n,h in expected.items():
 source=base/('complete-noupdate-'+str(n));assert hashlib.sha256((source/'result.json').read_bytes()).hexdigest()==h
 for p in sorted(source.rglob('*')):
  if p.is_file():add(p,'owner-'+str(n)+'/'+str(p.relative_to(source)))
 for filename in ['run_complete_noupdate'+str(n)+'.py','complete-noupdate'+str(n)+'-PROTOCOL.json','complete-noupdate'+str(n)+'-DEPLOYMENT.json']:add(base/filename,'bindings/'+filename)
for name in ['lptbJT','w1P27K','ZNVrMc','SLCmyc','syxo1z','eQLoHa']:
 p=pathlib.Path('/tmp/ordinary-q24-original-process-'+name)
 for filename in ['stdout.log','stderr.log']:add(p/filename,'native-child-logs/'+p.name+'/'+filename)
terminals=pathlib.Path('/home/qq/.local/state/hepta-runtime-mac-worker/terminals')
for key,tid in [('noupdate3','dpty-35c8a05de8741324cc26059bb9c156c0ef0b313159de79b3605c4f3461f850f2'),('noupdate4','dpty-364e58c84e2a284539cebb8cff7f7710cfe5c7d5d1b2229e07d1ebb843f7236b'),('readback4','dpty-18e9513d723f99d8-ffbe-16')]:
 for name in ['output.log','request.json','started.json','exit.json','exit.witness.json','status.json']:
  p=terminals/tid/name
  if p.is_file():add(p,'original-execution/'+key+'/'+name)
source=base/'reuse-metadata-corrected-list-preflight'
for p in sorted(source.rglob('*')):
 if p.is_file():add(p,'corrected-list-preflight/'+str(p.relative_to(source)))
index={'schema':'hepta.original-failed-noupdate-archive.v1','created_at_ns':time.time_ns(),'source_commit':'ab12b8bc1e6761efc16ea8c64e839721739cef5f','original_result_sha256':expected,'originals':rows,'scope':'Complete third preparation failure and fourth actual native failure owner directories, all twelve original fourth native child stdout/stderr files, terminal identity/output files when present, exact original drivers/protocols/deployments, and corrected read-only metadata listing. Large compiled binaries remain at original pinned paths. Raw native failure XML is retained; the original JUnit collector refused reused metadata command binding, so no collector success is asserted. This is not a whole-host snapshot.','archive_headers_normalized':True,'original_files_or_modes_modified':False}
ib=(json.dumps(index,sort_keys=True,indent=2)+'\n').encode();out.mkdir(mode=0o700);os.chown(out,1000,1000);p=out/'originals.tar.gz'
with tarfile.open(p,'w:gz',format=tarfile.PAX_FORMAT) as t:
 for name,b in sorted({**contents,'INDEX.json':ib}.items()):
  info=tarfile.TarInfo(name);info.size=len(b);info.mode=0o644;info.uid=info.gid=0;info.mtime=0;t.addfile(info,io.BytesIO(b))
with tarfile.open(p,'r:gz') as t:
 expected_members={**contents,'INDEX.json':ib};assert set(t.getnames())==set(expected_members)
 for name,b in expected_members.items():assert t.extractfile(name).read()==b
for row in rows:assert hashlib.sha256(pathlib.Path(row['original_path']).read_bytes()).hexdigest()==row['sha256']
(out/'INDEX.json').write_bytes(ib)
receipt={'archive_path':str(p),'archive_bytes':p.stat().st_size,'archive_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'index_sha256':hashlib.sha256(ib).hexdigest(),'original_files':len(rows),'all_members_verified':True,'all_originals_rechecked':True,'zero_model_or_native_calls':True,'created_at_ns':time.time_ns()}
(out/'ARCHIVE.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
for f in out.iterdir():os.chown(f,1000,1000)
print(json.dumps(receipt),flush=True)
