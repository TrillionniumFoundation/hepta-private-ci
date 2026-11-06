#!/usr/bin/env python3
"""Read-only projection of all five original compact logs; donor decoder is preserved."""
from pathlib import Path
import collections,hashlib,importlib.util,json,subprocess
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fixed_decoder',ROOT/'borrowed/decode_compact.py')
D=importlib.util.module_from_spec(spec);spec.loader.exec_module(D)
IDS=[13475811429,13475001412,13475231392,13474964431,13474454125]
def one(aid):
 root=ROOT/'artifacts'/f'artifact-{aid}'
 compact,=root.rglob('*.zst')
 p=subprocess.run(['zstd','-q','-d','-c','--no-pass-through','--',str(compact)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=False)
 assert p.returncode==0
 data=p.stdout;pos=0;count=0;outputs={};seen=set();types=collections.Counter();mnemonics=collections.Counter();runner=collections.Counter();invocation=[];retained=[];failed=[];test_count=0
 while pos<len(data):
  size,pos=D.varint(data,pos);raw=data[pos:pos+size];pos+=size
  assert len(raw)==size
  f=D.fields(raw);eid=D.scalar(f,1);payload=[n for n in f if n!=1];assert len(payload)==1
  typ=payload[0];types[typ]+=1;g=D.msg(f,typ);count+=1
  if eid:assert eid not in seen;seen.add(eid)
  if typ==2:invocation.append({'hash_function_name':D.string(g,1),'workspace_runfiles_directory':D.string(g,2),'sibling_repository_layout':bool(D.scalar(g,3)),'invocation_id':D.string(g,4)})
  elif typ==3:outputs[eid]={'type':'file',**D.file_data(g)}
  elif typ==4:outputs[eid]={'type':'directory','path':D.string(g,1),'files':[D.file_data(x) for x in D.msgs(g,2)]}
  elif typ==5:outputs[eid]={'type':'unresolved_symlink','path':D.string(g,1),'target_path':D.string(g,2)}
  elif typ==7:
   s={'sequence':count,**D.spawn(g,outputs)};mnemonics[s['mnemonic']]+=1
   if s['mnemonic']=='TestRunner':
    test_count+=1;runner[f"{s['runner']}|cache_hit={s['cache_hit']}"]+=1;retained.append(s)
   elif s['exit_code']!=0:failed.append(s)
  elif typ not in (6,8,9,10):raise AssertionError(('unknown_entry_type',typ))
 assert len(invocation)==1
 manifests=[]
 for m in sorted(root.rglob('manifest.json')):
  md=json.loads(m.read_bytes())
  assert md['complete_for_selected_targets'] is True and md['errors']==[]
  assert md['source']=={'commit':'b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae','tracked_worktree_dirty':False,'tree':'3982ba56dc5a3f1da0c1de7ea57992f88125c359'}
  for f in md['files']:
   b=(m.parent/f['archive_relative_path']).read_bytes()
   assert len(b)==f['bytes'] and hashlib.sha256(b).hexdigest()==f['sha256']
  manifests.append({'path':str(m.relative_to(root)),'files':len(md['files']),'selected_targets':md['selected_targets'],'source':md['source'],'complete_for_selected_targets':True})
 summary={'artifact_id':aid,'compact_path':str(compact.relative_to(ROOT)),'compressed_bytes':compact.stat().st_size,'compressed_sha256':hashlib.sha256(compact.read_bytes()).hexdigest(),'decompressed_bytes':len(data),'record_count':count,'type_counts':dict(sorted(types.items())),'nonzero_ids':len(seen),'invocation':invocation[0],'mnemonic_counts':dict(mnemonics),'test_runner_count':test_count,'test_runner_runner_cache_counts':dict(runner),'failed_non_test_spawns':len(failed),'collector_manifests':manifests}
 out=ROOT/'derived'/str(aid);out.mkdir(parents=True,exist_ok=True)
 for name,obj in [('compact-summary.json',summary),('all-test-runners.json',retained),('failed-nontest-spawns.json',failed)]:
  (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:summary[k] for k in ['artifact_id','record_count','decompressed_bytes','test_runner_count','test_runner_runner_cache_counts','failed_non_test_spawns']}),flush=True)
for i in IDS:one(i)

