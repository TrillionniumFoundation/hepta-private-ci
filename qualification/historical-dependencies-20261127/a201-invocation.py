import pathlib,sys,tarfile,hashlib,os,json,traceback
root=pathlib.Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5')
archive=root/'historical-helper-v4.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='ed9287dd74c3743e19fd345b74b2931ebc5e6e18579f4db0529b383212c331fd'
helper=root/'historical-helper-v4'
helper.mkdir(exist_ok=False)
with tarfile.open(archive,'r:gz') as t:t.extractall(helper,filter='data')
sys.path.insert(0,str(helper))
sys.dont_write_bytecode=True
from file_update_oracle import historical
env=os.environ.copy()
env.update(CARGO_TARGET_DIR=str(root/'target'),CARGO_BUILD_JOBS='2',PYTHONDONTWRITEBYTECODE='1')
env['PATH']='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin'+os.pathsep+env.get('PATH','')
receipt={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'status':'running','scope':'historical dependency graph only; no native equivalence claimed'}
try:
 graph,packages,record=historical.capture(root/'file-update-original','a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095',pathlib.Path('/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin/rustc'),env,root/'historical-a201-probe-v2')
 receipt.update(status='passed',qualification=record,library_units=len(graph['units']),library_files=len(graph['files']))
except Exception as error:
 receipt.update(status='failed',error=type(error).__name__+': '+str(error))
 traceback.print_exc()
finally:
 with (root/'historical-a201-probe-v2-receipt.json').open('x') as f:json.dump(receipt,f,indent=2)
 print(json.dumps({k:v for k,v in receipt.items() if k!='qualification'}),flush=True)
if receipt['status']=='passed':
 from test_historical_dependency_admission import controls
 result=controls(record,root/'historical-a201-admission-controls-v2')
 result['input_receipt']=historical.bind(root/'historical-a201-probe-v2-receipt.json')
 with (root/'historical-a201-admission-controls-v2.json').open('x') as f:json.dump(result,f,indent=2)
 print(json.dumps({'controls_passed':result['passed'],'rejection_count':result['rejection_count']}),flush=True)
sys.exit(0 if receipt['status']=='passed' else 1)
