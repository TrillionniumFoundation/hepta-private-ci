import os,json,subprocess,time,hashlib
from pathlib import Path
root=Path('/home/qian-qi/work/hepta-e5-final-verification-20261120-e9e051')
repo=root/'source';stage=root/'candidate-bytes-staging-1';out=root/'candidate-object-restore-1';out.mkdir(exist_ok=False)
base='e4b4eb5028578be87d5cad0829103632f2bff3a3';candidate='b6822f9afe283e1e1b4493173ee98cc2f740ef0a';head='1818fde55d964a87cfc8aed49f26a6a866a0e0a5'
env=os.environ.copy();env['GIT_NO_LAZY_FETCH']='1'
start=time.monotonic();cpu=time.process_time()
report={'schema':'hepta.e5-candidate-original-object-restoration.v1','base':base,'candidate':candidate,'expected_tree':'ace010f9ff23207de53c5941db73c11079fc8034','checkout_head':head,'manifest_sha256':'9f5cd4aeebe498239cdc104aa1a15951b9c031d47b8d6db8439179d5fb355218','objects':[],'model_calls':0,'training_updates':0,'native_task_children':0}
def run(argv,data=None):
 r=subprocess.run(argv,cwd=repo,env=env,input=data,capture_output=True,timeout=10)
 if r.returncode:raise RuntimeError({'argv':argv,'code':r.returncode,'stderr':r.stderr.decode('utf-8','replace')})
 return r.stdout
def stat_record(path):
 s=path.stat();return {'dev':s.st_dev,'ino':s.st_ino,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
try:
 assert run(['git','rev-parse','HEAD']).decode().strip()==head
 assert run(['git','rev-parse',candidate+'^{tree}']).decode().strip()==report['expected_tree']
 refs_before=hashlib.sha256(run(['git','show-ref'])).hexdigest()
 config=Path(run(['git','rev-parse','--git-path','config']).decode().strip())
 if not config.is_absolute():config=repo/config
 index=Path(run(['git','rev-parse','--git-path','index']).decode().strip())
 if not index.is_absolute():index=repo/index
 config_before=stat_record(config);index_before=stat_record(index)
 raw=(stage/'BUNDLES.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==report['manifest_sha256']
 manifest=json.loads(raw);assert manifest['candidate']==candidate and manifest['objects']==56 and len(manifest['bundles'])==22
 report['refs_before_sha256']=refs_before
 (out/'INTENT.json').write_text(json.dumps(report,indent=2)+'\n')
 entries=[e for b in manifest['bundles'] for e in b['entries']]
 assert len(entries)==56 and len({e['git_sha'] for e in entries})==56
 for bundle in manifest['bundles']:
  data=(stage/bundle['name']).read_bytes()
  assert len(data)==bundle['bytes'] and hashlib.sha256(data).hexdigest()==bundle['sha256']
  for e in bundle['entries']:
   payload=data[e['offset']:e['offset']+e['bytes']]
   assert len(payload)==e['bytes'] and hashlib.sha256(payload).hexdigest()==e['sha256']
   assert hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\x00'+payload).hexdigest()==e['git_sha']
   t=time.monotonic();gitsha=run(['git','hash-object','-w','--stdin'],payload).decode().strip()
   assert gitsha==e['git_sha']
   report['objects'].append({**e,'bundle':bundle['name'],'written_git_sha':gitsha,'wall_seconds':time.monotonic()-t})
  print(json.dumps({'restored':len(report['objects']),'bundle':bundle['name']}),flush=True)
 paths=run(['git','diff','--name-only','--diff-filter=AM','--no-renames','-z',base,candidate]).split(b'\x00')
 paths=[x.decode() for x in paths if x]
 (out/'changed-paths.json').write_text(json.dumps(paths,indent=2)+'\n')
 tree=run(['git','ls-tree','-r','-z',candidate,'--',*paths])
 (out/'changed-tree.raw').write_bytes(tree)
 records=[]
 for line in tree.split(b'\x00'):
  if not line:continue
  metadata,path=line.split(b'\t',1);mode,kind,oid=metadata.decode().split()
  assert kind=='blob'
  records.append({'path':path.decode(),'git_sha':oid,'mode':mode})
 assert set(paths)=={x['path'] for x in records}
 checks=run(['git','cat-file','--batch-check'], ''.join(x['git_sha']+'\n' for x in records).encode())
 (out/'changed-blob-closure.stdout').write_bytes(checks)
 lines=checks.decode().splitlines();assert len(lines)==len(records)
 for record,line in zip(records,lines):
  oid,kind,size=line.split();assert oid==record['git_sha'] and kind=='blob'
  record['bytes']=int(size)
 report['changed_blobs']=records
 report['full_pr_changed_paths']=len(paths)
 report['max_changed_blob_bytes']=max(x['bytes'] for x in records)
 report['all_full_pr_changed_objects_present']=True
 report['head_unchanged']=run(['git','rev-parse','HEAD']).decode().strip()==head
 report['refs_unchanged']=hashlib.sha256(run(['git','show-ref'])).hexdigest()==refs_before
 report['config_stat_unchanged']=stat_record(config)==config_before
 report['index_stat_unchanged']=stat_record(index)==index_before
 assert all(report[x] for x in ['head_unchanged','refs_unchanged','config_stat_unchanged','index_stat_unchanged'])
 report['status']='PASS'
except BaseException as e:
 report['status']='FAIL';report['error_type']=type(e).__name__;report['error']=str(e)
finally:
 report['wall_seconds']=time.monotonic()-start;report['owner_self_cpu_seconds']=time.process_time()-cpu
 (out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k not in ('objects','changed_blobs')}),flush=True)
raise SystemExit(0 if report['status']=='PASS' else 1)
