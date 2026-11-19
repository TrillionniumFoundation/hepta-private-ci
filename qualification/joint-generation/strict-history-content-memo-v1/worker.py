import ast,copy,hashlib,json,os,sys,time,fcntl
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from content_memo import ContentMemo
OUT=ROOT/'RUN_ONCE';OLD=ROOT.parent/'segmented-actor-validation128-candidate-v1';DATA=OLD/'RUN_ONCE/clean/session'
report={'status':'STARTED','scope':'exact fresh-bytes payload SHA work diagnostic; no models, no256, no speed claim or strict total-CPU proof','tests':[]}
def require(x,msg):
 if not x:raise ValueError(msg)
def write_result():
 (OUT/'RESULT.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
def verify():
 for n,h in json.loads((ROOT/'FREEZE.json').read_text()).items():
  require(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h,'source '+n)
 for n,h in json.loads((ROOT/'INPUTS.json').read_text()).items():
  require(hashlib.sha256((ROOT.parent/n).read_bytes()).hexdigest()==h,'input '+n)
def extract(path,names):
 ns=[n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
 require({n.name for n in ns}==set(names),'exact extracted functions')
 return ast.Module(body=ns,type_ignores=[])
try:
 lock=os.open('/workspace/shared/rgb-class-preservation-20261030/benchmark.lock',os.O_RDONLY);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 verify();report['pre_barrier']=True
 work={k:0 for k in ['history_walks','history_leaves_validated','payload_bytes_read','payload_read_calls']}
 env={'json':json,'hashlib':hashlib,'Path':Path,'WORK':work}
 exec(compile(extract(OLD/'stages.py',['canonical','sha','detached','read']),'original_stage_helpers','exec'),env)
 payload_ast=extract(OLD/'actor.py',['bytes_get'])
 cls=next(n for n in ast.parse((OLD/'actor.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='ActorSegments')
 node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='history')
 history_ast=ast.Module(body=[node],type_ignores=[])
 canonical=env['canonical'];sha=env['sha'];read=env['read']
 init=read(DATA/'segment-0000/manifest.json')[0]['initial'];last,ref=read(DATA/'history/action-0127.json');state={**last['after'],'history_tip':ref}
 obj=SimpleNamespace(identity=state['job'],total=128,root=DATA,payloads=DATA/'payloads',initial=lambda:copy.deepcopy(init))
 bounds=[(0,sha(canonical(init)))];declared=[]
 for i in range(128):
  body,r=read(DATA/'history'/f'action-{i:04d}.json');current={**body['after'],'history_tip':r}
  if(i+1)%8==0:bounds.append((i+1,sha(canonical(current))))
  declared.append(body['after']['order_ref'])
 class CountSHA:
  def __init__(self):self.stats={'calls':0,'hash_calls':0,'hash_bytes':0,'hits':0,'entries':0,'retained_payload_bytes':0}
  def __call__(self,raw):
   self.stats['calls']+=1;self.stats['hash_calls']+=1;self.stats['hash_bytes']+=len(raw);return sha(raw)
 def payload_reader(counter):
  e=dict(env);e['sha']=counter;exec(compile(payload_ast,'original_bytes_get','exec'),e);return e['bytes_get']
 def history_call(mode,s,bs):
  counter=ContentMemo() if mode=='memo' else CountSHA()
  e=dict(env);e['bytes_get']=payload_reader(counter);exec(compile(history_ast,'original_history_unchanged','exec'),e)
  before=dict(work);error=None
  try:e['history'](obj,s,bs)
  except ValueError as ex:error=str(ex)
  finally:
   stats=dict(counter.stats)
   if mode=='memo':counter.cache.clear();require(not counter.cache,'cache cleared')
  return {'mode':mode,'error':error,'work':{k:work[k]-before[k] for k in work},'payload_SHA':stats,'cache_cleared_after_call':True if mode=='memo' else None}
 # Complete same saved128 chain; candidate never uses the previous equality change.
 rows=[history_call(n,state,bounds) for n in ['original','memo']]
 require(all(r['error']is None for r in rows),'full history accept');require(rows[0]['work']==rows[1]['work'],'fresh IO parity')
 require(rows[0]['payload_SHA']['hash_calls']==256 and rows[1]['payload_SHA']['hash_calls']==174 and rows[1]['payload_SHA']['hits']==82,'frozen expected work reduction')
 require(rows[0]['payload_SHA']['hash_bytes']-rows[1]['payload_SHA']['hash_bytes']==67732,'frozen hash-byte reduction')
 report['tests'].append({'name':'saved128_exact_original_comparison','results':rows})
 # A second fresh history-call cache must not inherit the first cache or skip reads.
 again=history_call('memo',state,bounds);require(again['error']is None and again['work']==rows[1]['work'] and again['payload_SHA']==rows[1]['payload_SHA'],'new call scope')
 report['tests'].append({'name':'second_call_fresh_cache','result':again})
 for cursor in [0,64,128]:
  bs=[(c,'0'*64 if c==cursor else h) for c,h in bounds];rs=[history_call(n,state,bs) for n in ['original','memo']]
  require(rs[0]['error']is not None and rs[0]['error']==rs[1]['error'] and rs[0]['work']==rs[1]['work'],'boundary refusal')
  report['tests'].append({'name':'boundary_'+str(cursor),'results':rs})
 # Actual temporary files, never historical payload mutations. Same fixed sequence both modes.
 def file_sequence(mode):
  directory=OUT/('literal-'+mode);directory.mkdir();counter=ContentMemo() if mode=='memo' else CountSHA();get=payload_reader(counter)
  a=b'old payload';b=b'new payload';p=directory/'a.bin';q=directory/'b.bin';p.write_bytes(a);q.write_bytes(a)
  def ref(name,raw):return {'name':name,'bytes':len(raw),'sha256':sha(raw)}
  ar=ref('a.bin',a);br=ref('b.bin',a);observations=[]
  def check(label,r,expected=None):
   start=dict(work);err=None;value=None
   try:value=get(directory,r)
   except ValueError as ex:err=str(ex)
   require((err is None)==(expected is not None),'expected admission '+label)
   if expected is not None:require(value==expected,'exact returned bytes '+label)
   observations.append({'case':label,'error':err,'returned_sha256':sha(value) if value is not None else None,'work':{k:work[k]-start[k] for k in work}})
  check('first',ar,a);check('different_path_identical_bytes',br,a)
  bad=dict(br);bad['sha256']='0'*64;check('cache_hit_wrong_expected_digest',bad)
  p.write_bytes(b);check('same_path_mutated_old_reference',ar);check('same_path_new_correct_reference',ref('a.bin',b),b)
  p.write_bytes(a);check('restored_content',ar,a)
  p.write_bytes(a+b'x');check('appended_byte',ar)
  p.write_bytes(a[:-1]);check('truncated_byte',ar)
  link=directory/'link.bin';link.symlink_to('b.bin');check('symlink_refusal',ref('link.bin',a))
  require(counter.stats['calls']==6,'literal digest attempts')
  stats=dict(counter.stats)
  if mode=='memo':counter.cache.clear();require(not counter.cache,'literal cache cleared')
  return {'observations':observations,'payload_SHA':stats,'cache_cleared_after_sequence':True if mode=='memo' else None}
 sequences=[file_sequence(n) for n in ['original','memo']]
 require(sequences[0]['observations']==sequences[1]['observations'],'file sequence equivalence')
 require(sequences[1]['payload_SHA']['hits']==4 and sequences[1]['payload_SHA']['hash_calls']==2,'literal cache hits')
 report['tests'].append({'name':'fresh_file_mutation_refusals','results':sequences})
 # Fixed caps and unsupported type. No unbounded retention or eviction.
 m=ContentMemo();small=[bytes([i])*4096 for i in range(17)]
 for raw in small:require(m(raw)==sha(raw),'cap digest')
 require(m.stats['entries']==16 and m.stats['retained_payload_bytes']==65536,'cache payload cap')
 for raw in [small[16],small[0],b'z'*4097,b'z'*4097]:require(m(raw)==sha(raw),'overflow/threshold digest')
 require(m.stats=={'calls':21,'hash_calls':20,'hash_bytes':81922,'hits':1,'entries':16,'retained_payload_bytes':65536},'fixed capacity ledger')
 try:m(bytearray(b'x'))
 except ValueError:pass
 else:raise ValueError('nonbytes admitted')
 report['tests'].append({'name':'bounded_capacity_and_type','stats':dict(m.stats),'rejected_nonbytes':True})
 verify();report['post_barrier']=True;report['status']='COMPLETE';report['work']=work;report['no_numpy_or_model_import']=not any(k=='numpy' or k.startswith('fashion_research') for k in sys.modules);require(report['no_numpy_or_model_import'],'model import');report['CPU_prefix_seconds']=time.process_time();write_result()
except BaseException as ex:
 report['status']='FAILED';report['failure']={'type':type(ex).__name__,'message':str(ex)};report['CPU_prefix_seconds']=time.process_time();write_result();raise
