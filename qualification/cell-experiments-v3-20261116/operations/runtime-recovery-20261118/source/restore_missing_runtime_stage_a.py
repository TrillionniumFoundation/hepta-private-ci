from pathlib import Path
import concurrent.futures, gzip, hashlib, json, os, shutil, sys, time, urllib.request, zipfile

ROOT=Path('/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a')
OLD=ROOT/'operations/recovery-03'
VENV=ROOT/'venv'
OUT=ROOT/'operations/recovery-20261118-e4'
OUT.mkdir(exist_ok=False)
(OUT/'wheelhouse').mkdir()
started=time.time()
def emit(event):
    print(json.dumps(event,sort_keys=True),flush=True)
    with (OUT/'EVENTS.jsonl').open('a') as f:
        f.write(json.dumps(event,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(8*1024*1024):h.update(b)
    return h.hexdigest()
def save(name,value):
    with (OUT/name).open('x') as f:json.dump(value,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
try:
    manifest=json.loads((OLD/'DOWNLOAD_MANIFEST.json').read_text())
    wheels={x['name']:x for x in manifest['items']}
    missing={}
    for p in sorted(OLD.glob('INSTALLED_FILES_*.json.gz')):
        m=json.loads(gzip.decompress(p.read_bytes()))
        items=[]
        for x in m['files']:
            dst=VENV/x['path']
            if not dst.exists():
                if dst.is_symlink():raise ValueError('refuse symlink '+str(dst))
                items.append(x)
        if items:
            missing[m['distribution']]={'version':m['version'],'items':items,
                'manifest_path':str(p),'manifest_sha256':sha(p)}
    total=sum(x['bytes'] for m in missing.values() for x in m['items'])
    new_wheels=sum(wheels[n]['bytes'] for n in missing if not (ROOT/wheels[n]['path']).is_file())
    free=shutil.disk_usage(ROOT).free
    if free<total+new_wheels+2*1024**3:raise ValueError('insufficient reserved free disk')
    save('PLAN.json',{'schema':'hepta.exact-missing-runtime-restore.v1','missing':missing,
        'expected_missing_bytes':total,'expected_download_bytes':new_wheels,'free_bytes_at_start':free,
        'old_download_manifest_sha256':sha(OLD/'DOWNLOAD_MANIFEST.json'),
        'existing_file_overwrite':False,'package_versions_changed':False,'automatic_retry':False})
    emit({'event':'PLAN','packages':len(missing),'missing_files':sum(len(m['items']) for m in missing.values()),
          'missing_bytes':total,'download_bytes':new_wheels})
    def get_wheel(name):
        w=wheels[name]; old=ROOT/w['path']
        if old.is_file():
            if old.stat().st_size!=w['bytes'] or sha(old)!=w['sha256']:raise ValueError('retained wheel differs '+name)
            emit({'event':'WHEEL_REUSED','package':name,'bytes':w['bytes'],'sha256':w['sha256']})
            return old
        dest=OUT/'wheelhouse'/w['filename']
        with urllib.request.urlopen(w['url'],timeout=60) as response, dest.open('xb') as f:
            if response.status!=200:raise ValueError('full download status '+str(response.status))
            h=hashlib.sha256();size=0;t=time.monotonic();last=t
            while b:=response.read(8*1024*1024):
                f.write(b);h.update(b);size+=len(b)
                if size>w['bytes']:raise ValueError('upstream overrun '+name)
                if time.monotonic()-last>20:
                    emit({'event':'DOWNLOAD_PROGRESS','package':name,'bytes':size,'expected':w['bytes']});last=time.monotonic()
            f.flush();os.fsync(f.fileno())
        if size!=w['bytes'] or h.hexdigest()!=w['sha256']:raise ValueError('download identity differs '+name)
        emit({'event':'WHEEL_VERIFIED','package':name,'bytes':size,'sha256':h.hexdigest(),
              'wall_seconds':time.monotonic()-t})
        return dest
    restored=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(get_wheel,n):n for n in missing}
        for future in concurrent.futures.as_completed(futures):
            name=futures[future];wheel=future.result()
            with zipfile.ZipFile(wheel) as z:
                for item in missing[name]['items']:
                    dst=VENV/item['path']
                    if dst.exists() or dst.is_symlink():raise ValueError('destination appeared '+str(dst))
                    if dst.parent.resolve()!=dst.parent:raise ValueError('symlinked parent '+str(dst))
                    relative=Path(item['path']).relative_to('lib/python3.12/site-packages').as_posix()
                    info=z.getinfo(relative)
                    if info.file_size!=item['bytes']:raise ValueError('wheel member length '+relative)
                    temp=dst.with_name(dst.name+'.restore-20261118-e4')
                    h=hashlib.sha256()
                    with z.open(info) as source,temp.open('xb') as f:
                        while b:=source.read(8*1024*1024):f.write(b);h.update(b)
                        f.flush();os.fsync(f.fileno())
                    if temp.stat().st_size!=item['bytes'] or h.hexdigest()!=item['sha256']:
                        raise ValueError('restored member identity '+relative)
                    os.chmod(temp,(info.external_attr>>16)&0o777 or 0o755)
                    os.link(temp,dst)
                    temp.unlink()
                    if sha(dst)!=item['sha256']:raise ValueError('published member identity '+relative)
                    row={'package':name,'path':item['path'],'bytes':item['bytes'],'sha256':item['sha256']}
                    restored.append(row);emit({'event':'RESTORED',**row})
    save('RESTORED.json',{'status':'COMPLETE','restored':restored,'wall_seconds':time.time()-started,
                         'existing_file_overwrite':False,'package_versions_changed':False})
    emit({'event':'COMPLETE','files':len(restored),'bytes':sum(x['bytes'] for x in restored),
          'free_bytes_after':shutil.disk_usage(ROOT).free})
except BaseException as e:
    save('FAILED.json',{'error_type':type(e).__name__,'error':str(e),'automatic_retry':False,
                        'wall_seconds':time.time()-started})
    emit({'event':'FAILED','error_type':type(e).__name__,'error':str(e)})
    raise
