import pathlib,json,hashlib,urllib.request,urllib.error,urllib.parse,time,zipfile,io,base64,csv,stat,resource
root=pathlib.Path('/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b/future-dependencies-1');root.mkdir(exist_ok=False)
started=time.perf_counter();cpu=time.process_time();url='https://pypi.org/pypi/bracex/3.2.2/json'
(root/'INTENT.json').write_text(json.dumps({'url':url,'requested_name':'bracex','requested_exact_version':'3.2.2','basis':'original wcmatch pyproject.toml dependencies bracex>=3.2.2, SHA a51a94a0ee9d13a2183dd83acf51eecafdf74e73f7ff1b3b9bded1ea74a445c3','install_hooks_executed':False,'old_venv_modified':False,'started_at_ns':str(time.time_ns()),'new_model_calls':0,'new_native_children':0},sort_keys=True)+'\n')
def get(url,label,cap):
 t=time.perf_counter()
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Hepta-authorized-research-material-replay'}),timeout=60) as response:
   data=response.read(cap+1);status=response.status;headers=dict(response.headers)
 except urllib.error.HTTPError as e:
  data=e.read(cap+1);status=e.code;headers=dict(e.headers)
 (root/(label+'.body')).write_bytes(data);(root/(label+'.HTTP.json')).write_text(json.dumps({'url':url,'status':status,'headers':headers,'body_bytes':len(data),'body_sha256':hashlib.sha256(data).hexdigest(),'wall_seconds':time.perf_counter()-t},sort_keys=True)+'\n')
 if status!=200 or len(data)>cap:raise ValueError('bounded official artifact fetch failed: '+label)
 return data
try:
 metadata_raw=get(url,'PYPI',2*1024*1024);metadata=json.loads(metadata_raw)
 assert metadata['info']['name'].lower()=='bracex' and metadata['info']['version']=='3.2.2'
 wheels=[x for x in metadata['urls'] if x['filename']=='bracex-3.2.2-py3-none-any.whl' and x['packagetype']=='bdist_wheel']
 assert len(wheels)==1
 wheel=wheels[0];assert urllib.parse.urlparse(wheel['url']).hostname=='files.pythonhosted.org'
 raw=get(wheel['url'],'WHEEL',1024*1024);assert hashlib.sha256(raw).hexdigest()==wheel['digests']['sha256'] and len(raw)==wheel['size']
 (root/wheel['filename']).write_bytes(raw);target=root/'site';target.mkdir();rows=[]
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  names=z.namelist();assert len(names)==len(set(names))
  assert sum(x.file_size for x in z.infolist())<=2*1024*1024
  records=list(csv.reader(io.StringIO(z.read('bracex-3.2.2.dist-info/RECORD').decode())))
  inventory={row[0]:row[1:] for row in records}
  for info in z.infolist():
   if info.is_dir():continue
   name=info.filename;p=pathlib.PurePosixPath(name)
   assert not p.is_absolute() and '..' not in p.parts and '\\' not in name and not stat.S_ISLNK(info.external_attr>>16)
   assert p.parts[0] in {'bracex','bracex-3.2.2.dist-info'} and not name.endswith('.pth')
   data=z.read(name);digest,size=inventory[name]
   if name!='bracex-3.2.2.dist-info/RECORD':
    assert digest.startswith('sha256=') and base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()==digest.split('=',1)[1] and int(size)==len(data)
   dest=target/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
   rows.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 manifest={'schema':'hepta.readonly-wheel-dependency.v1','name':'bracex','version':'3.2.2','directory':str(target),'wheel_filename':wheel['filename'],'wheel_sha256':hashlib.sha256(raw).hexdigest(),'wheel_bytes':len(raw),'pypi_metadata_sha256':hashlib.sha256(metadata_raw).hexdigest(),'files':rows,'wheel_RECORD_hashes_verified':True,'source_archive_extraction_only':True,'old_venv_modified':False,'install_hooks_executed':False,'new_model_calls':0,'new_native_children':0,'wall_seconds':time.perf_counter()-started,'self_cpu_seconds':time.process_time()-cpu,'http_body_bytes_observed':len(metadata_raw)+len(raw),'total_network_bytes_unknown':True}
 (root/'BUNDLE.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n');print(json.dumps({'path':str(root/'BUNDLE.json'),'sha256':hashlib.sha256((root/'BUNDLE.json').read_bytes()).hexdigest(),'files':len(rows),'wheel_sha256':manifest['wheel_sha256'],'wheel_bytes':len(raw)}),flush=True)
 for row in rows:
  if 'LICENSE' in row['path'].upper() or row['path'].endswith('/METADATA'):
   text=(target/row['path']).read_text();print(json.dumps({'path':row['path'],'sha256':row['sha256'],'text':text[:12000]}),flush=True)
except BaseException as e:
 (root/'FAILED.json').write_text(json.dumps({'error_type':type(e).__name__,'error':str(e),'wall_seconds':time.perf_counter()-started,'self_cpu_seconds':time.process_time()-cpu,'new_model_calls':0,'new_native_children':0},sort_keys=True)+'\n');raise
