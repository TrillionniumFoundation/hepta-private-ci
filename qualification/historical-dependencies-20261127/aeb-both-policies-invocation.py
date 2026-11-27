import pathlib,sys,hashlib,os,json,traceback,time
root=pathlib.Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5')
sys.path.insert(0,str(root/'historical-helper-v4'));sys.dont_write_bytecode=True
from file_update_oracle import historical
env=os.environ.copy()
env.update(CARGO_TARGET_DIR=str(root/'target'),CARGO_BUILD_JOBS='2',PYTHONDONTWRITEBYTECODE='1')
env['PATH']='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin'+os.pathsep+env.get('PATH','')
rustc=pathlib.Path('/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin/rustc')
for mode in (0,1):
 receipt={'status':'running','mode':mode,'started':time.time(),'helper_archive_sha256':'ed9287dd74c3743e19fd345b74b2931ebc5e6e18579f4db0529b383212c331fd','scope':'historical dependency graph only; complete formatter comparison remains required'}
 try:
  graph,packages,record=historical.capture(root/'unified-original','aeb88f596b83186456caac577080bcb2f253ad32',rustc,env,root/('historical-aeb-mode'+str(mode)+'-v1'),overflow_mode=mode)
  receipt.update(status='passed',qualification=record,library_units=len(graph['units']),library_files=len(graph['files']))
 except BaseException as error:
  receipt.update(status='failed',error=type(error).__name__+': '+str(error));traceback.print_exc()
 finally:
  receipt['finished']=time.time()
  with (root/('historical-aeb-mode'+str(mode)+'-v1-receipt.json')).open('x') as f:json.dump(receipt,f,indent=2)
  print(json.dumps({k:v for k,v in receipt.items() if k!='qualification'}),flush=True)
 if receipt['status']!='passed':raise SystemExit(1)
