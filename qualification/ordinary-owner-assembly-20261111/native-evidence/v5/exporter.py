import os,json,hashlib,subprocess,tarfile,io,stat,base64,traceback,sys
from pathlib import Path
C=json.loads(sys.argv[1])
WORK=Path(C['work']);assert not WORK.exists(),'Retain the original export';WORK.mkdir(mode=0o700)
r={'schema':'hepta.ordinary-owner-assembly.multi-source-native-export.v1','status':'running','anchor_source':C['head'],'anchor_tree':C['tree'],'files':[],'excluded':[],'business_acceptance':False}
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def save(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
def identity():
 p=C['source']
 return {k:subprocess.check_output(['git','-C',p,*a],text=True).strip() for k,a in [('head',['rev-parse','HEAD']),('tree',['rev-parse','HEAD^{tree}']),('status',['status','--porcelain=v1','--untracked-files=all'])]}
try:
 before=identity();assert before=={'head':C['head'],'tree':C['tree'],'status':''};r['source_before']=before
 payloads={};bindings=[]
 for src in C['sources']:
  directory=Path(src['path']);raw=(directory/src['terminal']).read_bytes();terminal=json.loads(raw)
  assert terminal.get('status')!='running',src['name']
  if src['sha256'] is not None:assert sha(raw)==src['sha256'],src['name']
  for k,v in src['expected'].items():assert terminal[k]==v,(src['name'],k)
  r.setdefault('terminal_records',[]).append({'name':src['name'],'terminal':src['terminal'],'sha256':sha(raw),'status':terminal.get('status'),'exit':terminal.get('exit'),'source_sha':terminal.get('source_sha')})
  for p in sorted(directory.rglob('*')):
   st=p.lstat()
   if stat.S_ISDIR(st.st_mode):continue
   assert stat.S_ISREG(st.st_mode) and st.st_nlink==1,str(p)
   rel=p.relative_to(directory)
   if len(rel.parts)>=2 and rel.parts[:2]==('helpers','bin'):
    r['excluded'].append({'path':src['name']+'/'+str(rel),'reason':'helper executable is bound by its original custody manifest and native build logs'});continue
   assert st.st_size<=32*1024*1024,str(p)
   data=p.read_bytes();key=src['name']+'/'+str(rel);assert key not in payloads;payloads[key]=data
   meta={'path':key,'original_path':str(p),'bytes':len(data),'sha256':sha(data),'git_blob':blob(data),'mtime_ns':st.st_mtime_ns}
   r['files'].append(meta);bindings.append((p,st,meta['sha256']))
 for category,values in [('requests',C['requests']),('observations',C['observations'])]:
  for name,value in values.items():
   data=(json.dumps(value,indent=2,sort_keys=True)+'\n').encode();key=category+'/'+name+'.json';payloads[key]=data
   r['files'].append({'path':key,'bytes':len(data),'sha256':sha(data),'git_blob':blob(data),'origin':'exact retained operator request or read-only observation'})
 assert sum(map(len,payloads.values()))<=128*1024*1024
 r['source_after']=identity();assert r['source_after']==before
 for p,st,digest in bindings:
  now=p.lstat();assert (now.st_ino,now.st_dev,now.st_size,now.st_mtime_ns)==(st.st_ino,st.st_dev,st.st_size,st.st_mtime_ns),str(p)
  assert sha(p.read_bytes())==digest,str(p)
 r['status']='verified-original-record-export'
 manifest=(json.dumps(r,indent=2,sort_keys=True)+'\n').encode();payloads['MANIFEST.json']=manifest
 archive=WORK/'original-records.tar.xz'
 with tarfile.open(archive,'w:xz',preset=6) as tf:
  for name,data in sorted(payloads.items()):
   item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o644;item.mtime=0;tf.addfile(item,io.BytesIO(data))
 with tarfile.open(archive,'r:xz') as tf:
  assert set(tf.getnames())==set(payloads)
  for item in tf:assert item.isfile() and tf.extractfile(item).read()==payloads[item.name]
 data=archive.read_bytes();encoded=base64.b64encode(data).decode();parts=[]
 for offset in range(0,len(encoded),48000):
  p=WORK/('part-%03d.txt'%(offset//48000));p.write_text(encoded[offset:offset+48000]);parts.append(str(p))
 meta={'schema':r['schema'],'status':r['status'],'archive':str(archive),'bytes':len(data),'sha256':sha(data),'git_blob':blob(data),'members':len(payloads),'payload_files':len(r['files']),'excluded':r['excluded'],'base64_parts':parts,'manifest_sha256':sha(manifest),'source_before':before,'source_after':r['source_after']}
 save(WORK/'export.json',meta);print(json.dumps(meta),flush=True)
except BaseException as e:
 save(WORK/'failure.json',{'error':repr(e),'traceback':traceback.format_exc()});raise
