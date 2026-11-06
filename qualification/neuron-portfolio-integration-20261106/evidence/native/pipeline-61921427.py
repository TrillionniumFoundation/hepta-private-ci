import datetime,hashlib,json,os,pathlib,shutil,subprocess,sys,time
root=pathlib.Path('/home/qq/work/hepta-portfolio-816d-20261106');source=root/'source';records=root/'records';expected='61921427dc19223fd8c9d0ded1a4723b255c5df5';tree='31d99be67393619aca47436d82f9dca909cba359'
env=os.environ.copy();env.update(json.loads((root/'env.json').read_text()));env.update(GIT_TERMINAL_PROMPT='0',GIT_LFS_SKIP_SMUDGE='1')
state={'source_head':expected,'source_tree':tree,'stages':[],'state':'preparing','cpu_cost':'unknown where not measured'}
def save():
 (records/'pipeline-61921427.json').write_text(json.dumps(state,indent=2)+'\n')
def git(*args):return subprocess.check_output(['git',*args],cwd=source,env=env,text=True)
def step(name,command):
 assert shutil.disk_usage(root).free>=8*1024**3,'insufficient disk before stage '+name
 assert git('rev-parse','HEAD').strip()==expected and git('rev-parse','HEAD^{tree}').strip()==tree
 assert git('status','--porcelain','--untracked-files=all').strip()==''
 label='formal-61921427-'+name;state['state']='running';state['active_stage']=label;save();print(json.dumps({'stage':label,'event':'starting'}),flush=True)
 rc=subprocess.call(['/usr/bin/python3',str(root/'native-command-v2.py'),expected,tree,label,json.dumps(command)],env=env)
 state['stages'].append({'name':name,'label':label,'exit_code':rc,'receipt':str(records/label/'receipt.json')});save()
 if rc:state['state']='failed';save();raise SystemExit(rc)
 return records/label
try:
 dirty=git('status','--porcelain','--untracked-files=all').strip()
 if dirty:
  assert dirty=='M codex-rs/hepta-intelligence/src/joint_generation_plan_v1_tests.rs',dirty
  assert git('diff','--binary','HEAD')==(records/'formal-27928bf8-fix/source.diff').read_text()
  subprocess.run(['git','restore','--worktree','--','codex-rs/hepta-intelligence/src/joint_generation_plan_v1_tests.rs'],cwd=source,env=env,check=True)
 with (records/'source-61921427-fetch.log').open('wb') as log:
  subprocess.run(['git','fetch','--filter=blob:none','--no-tags','--depth=5','origin',expected],cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
  subprocess.run(['git','checkout','--detach',expected],cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
 state['source_status']=git('status','--porcelain','--untracked-files=all').strip();state['resource_before']={'disk_free':shutil.disk_usage(root).free,'meminfo':pathlib.Path('/proc/meminfo').read_text().splitlines()[:5]};save()
 packages=['-p','codex-hepta-neuron','-p','codex-hepta-intelligence','-p','codex-hepta-agentd']
 step('fix',['just','fix','--locked','--offline',*packages])
 step('strict',['cargo','clippy','--tests','--locked','--offline',*packages,'-p','codex-hepta-infer-worker-host','--','-D','warnings'])
 helper_output=records/'formal-61921427-joint-helper'/'helpers'
 helper_dir=step('joint-helper',['python3','../scripts/hepta_cell_test_helpers.py','--output-dir',str(helper_output),'--package','codex-hepta-infer-worker-host'])
 agentd_dir=step('agentd-helper',['cargo','build','--locked','--offline','-p','codex-hepta-agentd','--bin','codex-hepta-agentd','--message-format=json'])
 manifest=json.loads((helper_output/'manifest.json').read_text());helper_env=json.loads((helper_output/'env.json').read_text())
 assert manifest['complete'] and manifest['source_sha']==manifest['source_sha_after']==expected
 found=[];finished=False
 for line in (agentd_dir/'stdout.log').read_text().splitlines():
  try:item=json.loads(line)
  except ValueError:continue
  if item.get('reason')=='build-finished':finished=item.get('success') is True
  if item.get('reason')=='compiler-artifact' and item.get('target',{}).get('name')=='codex-hepta-agentd' and item.get('executable'):
   found.append(item)
 assert finished and len(found)==1
 artifact=found[0];path=pathlib.Path(artifact['executable']);assert path.is_relative_to(root/'target')
 digest=hashlib.sha256()
 with path.open('rb') as handle:
  for block in iter(lambda:handle.read(1048576),b''):digest.update(block)
 manifest['artifacts']['codex-hepta-agentd']={'package':'codex-hepta-agentd','package_id':artifact['package_id'],'executable':str(path),'profile':artifact['profile'],'sha256':digest.hexdigest(),'bytes':path.stat().st_size}
 manifest['additional_build_receipt']=str(agentd_dir/'receipt.json');manifest['combined_manifest_note']='Joint repository-builder manifest plus actual agentd Cargo compiler-artifact; original manifests and stdout are retained.'
 helper_env['CARGO_BIN_EXE_codex-hepta-agentd']=str(path);helper_env['CARGO_BIN_EXE_codex_hepta_agentd']=str(path)
 (records/'current-helper-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(records/'current-helper-env.json').write_text(json.dumps(helper_env,indent=2)+'\n')
 step('tests',['just','test','--locked','--offline',*packages,'-p','codex-hepta-infer-worker-host'])
 state['state']='succeeded';state['source_after']={'head':git('rev-parse','HEAD').strip(),'tree':git('rev-parse','HEAD^{tree}').strip(),'status':git('status','--porcelain','--untracked-files=all').strip()};state['resource_after']={'disk_free':shutil.disk_usage(root).free,'meminfo':pathlib.Path('/proc/meminfo').read_text().splitlines()[:5]};save();print(json.dumps(state),flush=True)
except Exception as exc:
 state['state']='failed';state['error']=repr(exc);save();raise
