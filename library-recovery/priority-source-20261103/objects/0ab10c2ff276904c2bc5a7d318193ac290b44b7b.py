import os,json,subprocess,signal,time,http.client,hashlib
from pathlib import Path
root=Path('/workspace/shared/ui-product-foundation/apps/hepta-control-ui');out=Path('/workspace/shared/ui-product-plan');binary=Path('/workspace/shared/hepta-targets/main/debug/examples/ui_product_preview')
source=json.loads(Path(str(binary)+'.hepta-build.json').read_text());head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip();assert source['sourceCommit']==head
assert hashlib.sha256(binary.read_bytes()).hexdigest()==source['binarySha256']
env=dict(os.environ,HEPTA_GATEWAY_EXAMPLE=str(binary));log=open(out/'gateway-dc7-http-entry.log','w');p=subprocess.Popen(['python3','tools/run-product-preview.py'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
checks=[]
def get(path,expected,method='GET',headers=None):
 c=http.client.HTTPConnection('127.0.0.1',4175,timeout=3);c.request(method,path,headers=headers or {});r=c.getresponse();b=r.read();h=dict(r.getheaders());assert r.status==expected,(path,r.status);checks.append({'path':path,'method':method,'status':r.status,'headers':h,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()});c.close();return h,b
try:
 deadline=time.monotonic()+15
 while True:
  try:h,b=get('/',200);break
  except ConnectionRefusedError:
   if time.monotonic()>deadline:raise
   time.sleep(.1)
 assert 'text/html' in h['Content-Type'] and 'Content-Security-Policy' in h
 _,b=get('/api/hepta/owner-status',200);assert json.loads(b)=={'schema':'hepta.owner-lease-observation.v1','observation':{'status':'not_attached'}}
 for path in ['/healthz','/api/hepta/runtime']:get(path,503)
 get('/api/hepta/owner-status',405,'POST');get('/absent.wasm',404);get('/',403,headers={'Host':'attacker.example'})
 raw=(root/'dist/build-manifest.json').read_bytes();m=json.loads(raw);wasm=next(n for n in m['files'] if n.endswith('.wasm'));h,b=get('/'+wasm,200);assert h['Content-Type']=='application/wasm' and b==(root/'dist'/wasm).read_bytes()
finally:
 p.send_signal(signal.SIGTERM)
 try:code=p.wait(timeout=10)
 except subprocess.TimeoutExpired:p.kill();p.wait();raise
 log.close()
assert code==0
receipt={'source':source,'uiSourceIdentity':m['sourceIdentity']['sha256'],'uiManifestSha256':hashlib.sha256(raw).hexdigest(),'checks':checks,'previewExitCode':code,'browserPixels':False,'productionOwnerAttached':False}
(out/'gateway-dc7-http-entry.json').write_text(json.dumps(receipt,indent=2)+'\n');print(head,': eight actual HTTP checks passed; exit0; empty state retained')
