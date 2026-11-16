from pathlib import Path
import urllib.request,hashlib,zipfile,json,sys,time,resource
out=Path(sys.argv[1]);out.mkdir(exist_ok=False)
t=time.monotonic();raw=urllib.request.urlopen(sys.argv[2],timeout=30).read(200000)
assert len(raw)==121491 and hashlib.sha256(raw).hexdigest()=='34e6215b003b7d6de550c3636cd364d01af2639ecb2cdb80220ec2a236083ae3'
p=out/'ORIGINAL.zip';p.write_bytes(raw)
with zipfile.ZipFile(p) as z:
 assert z.testzip() is None
 rows=[]
 for i in z.infolist():
  assert not i.is_dir() and not i.filename.startswith('/') and '..' not in Path(i.filename).parts
  b=z.read(i);rows.append({'path':i.filename,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
 r={'schema':'hcsn-ci-exact-byte-recovery-v1','artifact_id':13813185764,'run_id':42922677682,'run_attempt':1,'original_zip_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'members':rows,'crc_passed':True,'whole_download_and_scan_wall_prefix_seconds':time.monotonic()-t,'cost_scope':'main-entry prefix excludes imports, final receipt serialization and exit; original verifier receipt is not reconstructed','tests_rerun':False}
 (out/'RECOVERY.json').write_text(json.dumps(r,indent=2)+'\n')
 print(json.dumps(r))