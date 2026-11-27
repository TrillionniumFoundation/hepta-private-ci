import ast,copy,hashlib,json,os,sys,time,traceback,fcntl,math
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from equality import equal
OUT=ROOT/'RUN_ONCE';OLD=ROOT.parent/'segmented-actor-validation128-candidate-v1';DATA=OLD/'RUN_ONCE/clean/session'
report={'status':'STARTED','scope':'saved128 stdlib history comparator only; no model, no training, no256, no strict complete-budget certification','tests':[],'measurements':[]}
def dump():
 (OUT/'RESULT.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
def verify():
 for n,h in json.loads((ROOT/'FREEZE.json').read_text()).items():
  if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('source freeze '+n)
 for n,h in json.loads((ROOT/'INPUTS.json').read_text()).items():
  if hashlib.sha256((ROOT.parent/n).read_bytes()).hexdigest()!=h:raise ValueError('input binding '+n)
def require(x,msg):
 if not x:raise ValueError(msg)
def extract(path,names):
 tree=ast.parse(path.read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
 require({n.name for n in nodes}==set(names),'extract exact functions');return ast.Module(body=nodes,type_ignores=[])
try:
 lock=os.open('/workspace/shared/rgb-class-preservation-20261030/benchmark.lock',os.O_RDONLY);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 verify();report['pre_barrier']=True
 work={k:0 for k in ('history_walks','history_leaves_validated','payload_bytes_read','payload_read_calls')}
 env={'json':json,'hashlib':hashlib,'Path':Path,'WORK':work}
 exec(compile(extract(OLD/'stages.py',['canonical','sha','detached','read']),'frozen_stage_functions','exec'),env)
 exec(compile(extract(OLD/'actor.py',['bytes_get']),'frozen_bytes_get','exec'),env)
 tree=ast.parse((OLD/'actor.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ActorSegments');original=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='history')
 # Exactly the two equality sites; all boundary hashing and IO stay original.
 class Change(ast.NodeTransformer):
  count=0
  def visit_Compare(self,n):
   if len(n.ops)==1 and isinstance(n.ops[0],ast.NotEq) and isinstance(n.left,ast.Call) and isinstance(n.left.func,ast.Name) and n.left.func.id=='canonical' and len(n.comparators)==1 and isinstance(n.comparators[0],ast.Call) and isinstance(n.comparators[0].func,ast.Name) and n.comparators[0].func.id=='canonical':
    self.count+=1;return ast.copy_location(ast.UnaryOp(op=ast.Not(),operand=ast.Call(func=ast.Name(id='equal',ctx=ast.Load()),args=[n.left.args[0],n.comparators[0].args[0]],keywords=[])),n)
   return self.generic_visit(n)
 change=Change();candidate=change.visit(copy.deepcopy(original));require(change.count==2,'exact two sites');env['equal']=equal
 funcs={}
 for name,node in [('original',original),('candidate',candidate)]:
  local=dict(env);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'frozen_history_'+name,'exec'),local);funcs[name]=local['history']
 canonical=env['canonical'];sha=env['sha'];read=env['read']
 init=read(DATA/'segment-0000/manifest.json')[0]['initial'];latest,ref=read(DATA/'history/action-0127.json');state={**latest['after'],'history_tip':ref}
 obj=SimpleNamespace(identity=state['job'],total=128,root=DATA,payloads=DATA/'payloads',initial=lambda:copy.deepcopy(init))
 bounds=[(0,sha(canonical(init)))];pairs=[]
 for i in range(128):
  b,r=read(DATA/'history'/f'action-{i:04d}.json');s={**b['after'],'history_tip':r}
  if (i+1)%8==0:bounds.append((i+1,sha(canonical(s))))
  pairs.append((b['after'],copy.deepcopy(b['after'])))
 literals=[None,False,True,0,1,-1,0.0,-0.0,1.0,1e-300,'','é',[],{},[0,False],{'a':0,'b':-0.0},{'b':-0.0,'a':0},'\U0001f600','\ud83d\ude00',{'\U0001f600':1},{'\ud83d\ude00':1},5e-324,sys.float_info.max,2**53+1,{'a':[True]},{'a':[1]}]
 for a in literals:
  for b in literals:require(equal(a,b)==(canonical(a)==canonical(b)),'literal equivalence')
 deep=0
 for _ in range(450):deep=[deep]
 require(equal(deep,json.loads(canonical(deep))) and canonical(deep)==canonical(json.loads(canonical(deep))),'deep finite JSON')
 for a,b in pairs:
  require(equal(a,b) and canonical(a)==canonical(b),'saved equality');b['global_cursor']+=1;require(not equal(a,b) and canonical(a)!=canonical(b),'saved mutation');b['global_cursor']=bool(a['global_cursor']);require(not equal(a,b) and canonical(a)!=canonical(b),'saved type mismatch')
 for v in (float('nan'),float('inf'),float('-inf')):
  for fn in (lambda:equal({'x':v},{'x':v}),lambda:canonical({'x':v})):
   try:fn()
   except ValueError:pass
   else:raise ValueError('nonfinite accepted')
 report['tests'].append({'name':'strict_json_equivalence','literal_pairs':len(literals)**2,'saved_pairs':len(pairs),'saved_negative_pairs':2*len(pairs),'nonfinite_refusals':6,'deep_equal_depth':450})
 def call(name,s,bs):
  before=dict(work);start=time.process_time_ns();error=None
  try:funcs[name](obj,s,bs)
  except ValueError as e:error=str(e)
  return {'mode':name,'CPU_ns':time.process_time_ns()-start,'error':error,'work':{k:work[k]-before[k] for k in work}}
 pos=[call(n,state,bounds) for n in funcs];require(all(x['error']is None for x in pos),'positive');require(pos[0]['work']==pos[1]['work'],'positive IO parity');report['tests'].append({'name':'complete128_fresh_walk','results':pos})
 cases=[]
 for name,key,value in [('wrong_job','job','0'*64),('bool_cursor','global_cursor',True),('last_loss','last_loss',-1)]:
  s=copy.deepcopy(state);s[key]=value;cases.append((name,s,[x for x in bounds if x[0]!=128] if name=='last_loss' else bounds))
 s=copy.deepcopy(state);s['history_tip']['sha256']='0'*64;cases.append(('tip_hash',s,[x for x in bounds if x[0]!=128]))
 for cursor in (0,64):cases.append(('boundary_'+str(cursor),state,[(c,'0'*64 if c==cursor else h) for c,h in bounds]))
 for label,s,bs in cases:
  rows=[call(n,s,bs) for n in funcs];require(all(r['error']is not None for r in rows),'refusal '+label);require(rows[0]['error']==rows[1]['error'] and rows[0]['work']==rows[1]['work'],'refusal equivalence '+label);report['tests'].append({'name':label,'results':rows})
 for order in [('original','candidate'),('candidate','original'),('original','candidate'),('candidate','original')]:
  block=[call(n,state,bounds) for n in order];require(all(r['error']is None for r in block),'benchmark success');require(block[0]['work']==block[1]['work'],'benchmark IO');report['measurements'].append(block)
 totals={n:sum(r['CPU_ns'] for b in report['measurements'] for r in b if r['mode']==n) for n in funcs}
 report['timing']={'fixed_four_blocks_CPU_ns':totals,'candidate_over_original':totals['candidate']/totals['original'],'scope':'single fixed saved128 history workload, no significance or full-controller inference','positive_screen':totals['candidate']<=.95*totals['original']}
 verify();report['post_barrier']=True;report['work']=work;report['status']='COMPLETE';report['transformed_comparisons']=change.count;report['model_imported']=any(k=='numpy' or k.startswith('fashion_research') for k in sys.modules);require(not report['model_imported'],'model imports');report['CPU_prefix_seconds']=time.process_time();dump()
except BaseException as e:
 report['status']='FAILED';report['failure']={'type':type(e).__name__,'message':str(e)};report['CPU_prefix_seconds']=time.process_time();dump();raise
