from pathlib import Path
import subprocess,time,resource,json,sys,hashlib,platform,os
root=Path('/home/qq/work/hepta-r1-4835-20261105-w0-r1')
ev=root/'evidence'
ev.mkdir(exist_ok=False)
source=root/'source'
sha='975e1a264c14ed3da02dcee23a64327825387e42'
spec=json.loads((root/'SOURCE_SUBSET.json').read_text())
def verify():
 for row in spec['files']:
  assert hashlib.sha256((source/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
verify()
start=time.perf_counter(); phases=[]
record={'schema':'hepta.r1-independent-execution.v1','source_sha':sha,'source_tree':spec['tree'],'host':'ai395','platform':platform.platform(),'launcher_python':sys.version,'python_environment_difference':'Python 3.12.16 instead of original Actions Python 3.12.14; all declared packages are pinned identically. Results belong to this exact environment only.','started_unix':time.time(),'source_manifest':spec,'phases':phases,'status':'started','semantic_acceptance':'not_inferred','training_performed':False,'production_qualified':False}
def save():
 (ev/'EXECUTION.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
save()
def phase(name,args):
 before=resource.getrusage(resource.RUSAGE_CHILDREN); t=time.perf_counter()
 with (ev/(name+'.log')).open('x') as out:
  proc=subprocess.run(args,cwd=source,stdout=out,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2','HF_HUB_DISABLE_TELEMETRY':'1'})
 after=resource.getrusage(resource.RUSAGE_CHILDREN)
 row={'name':name,'argv':args,'exit_code':proc.returncode,'wall_seconds':time.perf_counter()-t,'child_cpu_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,'cumulative_child_peak_rss_bytes':after.ru_maxrss*1024,'scope':'inclusive_child_wait','log_sha256':hashlib.sha256((ev/(name+'.log')).read_bytes()).hexdigest()}
 phases.append(row); save(); print(json.dumps(row),flush=True)
 if proc.returncode:raise RuntimeError(name+' failed; original log retained')
try:
 phase('create-env',['/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python','-m','venv',str(root/'venv')])
 py=str(root/'venv/bin/python')
 phase('install',[py,'-m','pip','install','--no-cache-dir','--disable-pip-version-check','--extra-index-url','https://download.pytorch.org/whl/cpu','torch==2.8.0+cpu','torchvision==0.23.0+cpu','numpy==2.3.5','Pillow==13.0.0','transformers==4.57.3','diffusers==0.35.2','accelerate==1.12.0','safetensors==0.7.0','num2words==0.5.14'])
 phase('freeze',[py,'-m','pip','freeze'])
 phase('acquisition',[py,'-B','-m','experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.acquire_models','--root',str(root/'models')])
 phase('diagnostics',[py,'-B','-m','experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.diagnostics','--models',str(root/'models'),'--original',str(source/'inputs/input.png'),'--generated',str(source/'inputs/direct.png'),'--output',str(ev/'diagnostics'),'--source-sha',sha,'--threads','2','--max-tokens','80'])
 verify()
 record['status']='completed'
except BaseException as e:
 record['status']='failed';record['error']={'type':type(e).__name__,'message':str(e)};raise
finally:
 record['wall_seconds']=time.perf_counter()-start
 child=resource.getrusage(resource.RUSAGE_CHILDREN);self=resource.getrusage(resource.RUSAGE_SELF)
 record['cpu_seconds_including_all_setup_and_children']=child.ru_utime+child.ru_stime+self.ru_utime+self.ru_stime
 record['cost_scope']='all recorded setup, downloads, verification, model runs and failures; excludes agent orchestration and transport; no energy meter'
 record['energy_joules']=None
 save()

