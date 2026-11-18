from pathlib import Path
import concurrent.futures,gzip,hashlib,json,os,shutil,threading,time,zipfile
import requests
ROOT=Path('/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a')
OLD=ROOT/'operations/recovery-03'
VENV=ROOT/'venv'
OUT=ROOT/'operations/recovery-20261118-e4b'
LOCAL=Path('/home/qian-qi/gpu-unlock-bench-20261114/lib/python3.12/site-packages')
OUT.mkdir(exist_ok=False);(OUT/'wheelhouse').mkdir()
lock=threading.Lock();thread=threading.local();started=time.time()
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while b:=f.read(8*1024*1024):h.update(b)
 return h.hexdigest()
def emit(v):
 with lock:
  print(json.dumps(v,sort_keys=True),flush=True)
  with (OUT/'EVENTS.jsonl').open('a') as f:f.write(json.dumps(v,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
def save(n,v):
 with (OUT/n).open('x') as f:json.dump(v,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
def publish(source,dst,item):
 if dst.exists() or dst.is_symlink() or dst.parent.resolve()!=dst.parent:raise ValueError('target not absent regular parent '+str(dst))
 tmp=dst.with_name(dst.name+'.restore-20261118-e4b')
 h=hashlib.sha256()
 with tmp.open('xb') as f:
  while b:=source.read(8*1024*1024):f.write(b);h.update(b)
  f.flush();os.fsync(f.fileno())
 if tmp.stat().st_size!=item['bytes'] or h.hexdigest()!=item['sha256']:raise ValueError('member hash mismatch')
 os.chmod(tmp,0o755);os.link(tmp,dst);tmp.unlink()
 if sha(dst)!=item['sha256']:raise ValueError('published hash mismatch')
 restored.append(item);emit({'event':'RESTORED',**item})
try:
 wheels={v['name']:v for v in json.loads((OLD/'DOWNLOAD_MANIFEST.json').read_text())['items']}
 missing={};restored=[];all_items={}
 for p in sorted(OLD.glob('INSTALLED_FILES_*.json.gz')):
  m=json.loads(gzip.decompress(p.read_bytes()))
  for x in m['files']:
   old=all_items.setdefault(x['path'],x)
   if old!=x:raise ValueError('conflicting package path')
   if not (VENV/x['path']).exists():missing.setdefault(m['distribution'],[]).append(x)
 save('PLAN.json',{'prior_operation':'recovery-20261118-e4','prior_stop_observed_exit_code':-15,
  'prior_stop_reason':'replace slow sequential downloads with exact local bytes and bounded parallel HTTP ranges',
  'prior_artifacts_preserved':True,'missing':missing,'parallel_range_workers':12,'range_bytes':1048576,
  'existing_file_overwrite':False,'package_versions_changed':False,'automatic_experiment_retry':False})
 remaining={}
 for name,items in missing.items():
  for item in items:
   rel=Path(item['path']).relative_to('lib/python3.12/site-packages');src=LOCAL/rel
   if src.is_file() and src.stat().st_size==item['bytes'] and sha(src)==item['sha256']:
    emit({'event':'LOCAL_SOURCE_VERIFIED','source':str(src),'sha256':item['sha256']})
    with src.open('rb') as f:publish(f,VENV/item['path'],item)
   else:remaining.setdefault(name,[]).append(item)
 emit({'event':'DOWNLOAD_PLAN','packages':list(remaining),'bytes':sum(wheels[n]['bytes'] for n in remaining)})
 def get_range(task):
  name,w,path,lo,hi=task
  if not hasattr(thread,'session'):thread.session=requests.Session()
  for attempt in range(3):
   try:
    response=thread.session.get(w['url'],headers={'Range':f'bytes={lo}-{hi}','Accept-Encoding':'identity'},timeout=(20,35))
    expected=f"bytes {lo}-{hi}/{w['bytes']}"
    if response.status_code!=206 or response.headers.get('Content-Range')!=expected:raise ValueError('range identity differs')
    raw=response.content
    if len(raw)!=hi-lo+1:raise ValueError('range length differs')
    with path.open('r+b',buffering=0) as f:
     written=os.pwrite(f.fileno(),raw,lo)
     if written!=len(raw):raise ValueError('short range write')
    return {'name':name,'start':lo,'end':hi,'sha256':hashlib.sha256(raw).hexdigest(),'attempts':attempt+1}
   except Exception:
    if attempt==2:raise
    thread.session.close();thread.session=requests.Session()
 tasks=[];paths={}
 for name in remaining:
  w=wheels[name];path=OUT/'wheelhouse'/w['filename'];paths[name]=path
  with path.open('xb') as f:f.truncate(w['bytes'])
  for lo in range(0,w['bytes'],1048576):tasks.append((name,w,path,lo,min(lo+1048575,w['bytes']-1)))
 with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
  futures=[pool.submit(get_range,t) for t in tasks]
  done=0;received=0
  with (OUT/'RANGES.jsonl').open('x') as log:
   for f in concurrent.futures.as_completed(futures):
    row=f.result();done+=1;received+=row['end']-row['start']+1
    log.write(json.dumps(row,sort_keys=True)+'\n');log.flush()
    if done%32==0:emit({'event':'RANGE_PROGRESS','completed':done,'total':len(tasks),'received_bytes':received,'seconds':time.time()-started})
 for name,items in remaining.items():
  w=wheels[name];p=paths[name]
  if p.stat().st_size!=w['bytes'] or sha(p)!=w['sha256']:raise ValueError('complete wheel hash differs '+name)
  emit({'event':'WHEEL_VERIFIED','package':name,'sha256':w['sha256'],'bytes':w['bytes']})
  with zipfile.ZipFile(p) as z:
   for item in items:
    rel=Path(item['path']).relative_to('lib/python3.12/site-packages').as_posix()
    with z.open(rel) as f:publish(f,VENV/item['path'],item)
 check_started=time.time();missing_end=[];different=[];checked=0;checked_bytes=0
 for name,item in sorted(all_items.items()):
  p=VENV/name
  if not p.is_file():missing_end.append(name);continue
  if p.stat().st_size!=item['bytes'] or sha(p)!=item['sha256']:different.append(name)
  checked+=1;checked_bytes+=item['bytes']
 final={'status':'COMPLETE' if not missing_end and not different else 'FAILED_VERIFICATION','restored':restored,
  'checked_files':checked,'checked_bytes':checked_bytes,'missing':missing_end,'different':different,
  'verification_seconds':time.time()-check_started,'wall_seconds':time.time()-started,
  'free_bytes_after':shutil.disk_usage(ROOT).free,'existing_file_overwrite':False,'package_versions_changed':False}
 save('RESULT.json',final);emit({k:v for k,v in final.items() if k!='restored'})
 if missing_end or different:raise ValueError('original environment identity not fully restored')
except BaseException as e:
 save('FAILED.json',{'error':str(e),'type':type(e).__name__,'wall_seconds':time.time()-started})
 emit({'event':'FAILED','error':str(e),'type':type(e).__name__});raise
