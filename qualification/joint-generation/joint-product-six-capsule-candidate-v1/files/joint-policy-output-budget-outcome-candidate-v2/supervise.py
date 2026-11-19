import sys,os,json,time,signal,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from common import *
from owned_process import spawn,wait as child_wait,cleanup
from output_budget_verifier import verify as inspect
lock=open(sys.argv[1],'rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def timeout(signum,frame):raise TimeoutError('supervisor wall deadline')
signal.signal(signal.SIGALRM,timeout)
FOLDER.mkdir();SESSION.mkdir();owned=[];receipts=[];events=[];error=None;complete=False;checks=[]
def check(n,v):
 if not v:raise AssertionError(n)
 checks.append(n)
def launch(role):
 with(FOLDER/(role+'.stdout')).open('xb')as f,(FOLDER/(role+'.stderr')).open('xb')as e:
  env=os.environ.copy();env['MANIFESTS_PIN']=pin
  return spawn([sys.executable,'-I','-B',str(ROOT/'worker.py'),role],f.fileno(),e.fileno(),role=role,alarm_seconds=30,env=env,owned=owned,events=events)
try:
 all_inputs();origin=time.monotonic_ns();write('CLOCK.json',{'origin_ns':origin,'deadline_ns':origin+45_000_000_000});manifests={}
 for name in ('known','uncommitted'):
  payload,artifact,raw=case_expected(name);r=json.loads(raw)
  manifests[name]={'schema':'local-live-control-v1','run_epoch':os.urandom(16).hex(),'origin_ns':origin,'deadline_ns':r['deadline_ns'],'request_sha256':sha(raw),'artifact_sha256':artifact,'namespace':sha(canonical({'objective_id':r['objective_id'],'run_id':r['run_id']})),'source_freeze':FREEZE,'root_instance':inst(SESSION)}
 write('MANIFESTS.json',manifests);pin=sha(canonical(manifests))
 p=launch('producer')
 if child_wait(p,receipts,events)!=0:raise ValueError('producer failed')
 producer=json.loads((FOLDER/'PRODUCER_RESULT.json').read_bytes());summaries={}
 for name,m in manifests.items():
  payload,artifact,raw=case_expected(name);ns=m['namespace'];rp=SESSION/ns/'reserved.json';rr={'namespace':ns,'name':'reserved.json',**file_ref(rp)};reject=SESSION/ns/'output-budget-rejected.json'
  if inst(SESSION)!=m['root_instance']:raise ValueError('root changed')
  s=inspect(raw,payload,FREEZE,m,sha(canonical(m)),m['run_epoch'],rp.read_bytes(),rr,reject.read_bytes()if reject.exists()else None,read('old_wire'),read('old_route'));summaries[name]=s
  check(name+'_full_reconstruction',s==producer['cases'][name]['summary'])
 write('HANDOFF.json',{'summaries':summaries,'root_instance':inst(SESSION),'lock_instance':inst(SESSION/'.hepta-writer.lock'),'producer_pid':p.pid})
 q=launch('recover')
 if child_wait(q,receipts,events)!=0:raise ValueError('recovery failed')
 recovery=json.loads((FOLDER/'RECOVERY_RESULT.json').read_bytes());check('recovery_exact',recovery['summaries']==summaries)
 for v in (producer,recovery):
  if v['limits']!={'CPU':[2,2],'AS':[256*2**20]*2,'FSIZE':[2*2**20]*2}:raise ValueError('worker limits')
 n=len(checks)+len(producer['checks'])+len(recovery['checks']);nf=len(producer['refusals'])+len(recovery['refusals'])
 if n!=24 or nf!=5:raise ValueError(('fixed counts',n,nf))
 all_inputs()
 # Class limits support the conditional success capacity calculation.
 for x in OUT.rglob('*'):
  if not x.is_file():continue
  if x.name in ('output-budget-rejected.json','BAD-allowed.json','BAD-reserved.json'):cap=256*1024
  elif x.suffix=='.npz':cap=2*2**20
  elif x.suffix=='.wire':cap=256*1024
  else:cap=65536
  if x.stat().st_size>cap:raise ValueError('success class capacity')
 out={'status':'PASS_TYPED_KNOWN_OUTPUT_REJECTION_AND_UNCOMMITTED_UNKNOWN','checks':n,'refusals':nf,'supervisor_checks':checks,'producer_work':producer['work'],'recovery_work':recovery['work'],'new_allocations':2,'new_inferences':2,'new_Adam':0,'events':events,'role_receipts':receipts,'source_freeze_sha256':FREEZE,'scope':'known generated result not no-effect;output rejected0prefix;injected prewrite failure remainsunknown;readonlyrecovery no authority'}
 (OUT/'RESULT.json').write_bytes(canonical(out));complete=True
except BaseException as e:error=type(e).__name__+': '+str(e)
finally:
 signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(15)
 cleanup(owned,receipts,events);lock.close()
 with(OUT/'ROLE_RECEIPTS.json').open('xb')as f:f.write(canonical({'complete':complete,'error':error,'receipts':receipts,'events':events,'cleanup_boundary':'own registered children only;hard ancestor/kernel/storage failure outside guarantee'}))
if error:print(error,file=sys.stderr)
raise SystemExit(0 if complete else 1)
