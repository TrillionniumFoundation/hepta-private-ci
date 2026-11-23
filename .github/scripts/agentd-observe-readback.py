"""Run only the unchanged parent case; preserve every verdict and the observation variant."""
from pathlib import Path
from hashlib import sha256
import json,os,re,subprocess,sys,time
root=Path(os.environ['RUNNER_TEMP']);epoch=Path(os.environ['OBS_FIXTURE']);out=root/'queue-observation-evidence';out.mkdir(exist_ok=True)
case='authority_host_service::resident::authority::tests::resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel'
paths={'HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT':'bind','HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE':'source','HEPTA_CHECKPOINT_TEST_ROOT':'checkpoints','HEPTA_Q24_FACTORY_WITNESS_BIND':'witness-bind','HEPTA_Q24_FACTORY_WITNESS_SOURCE':'witness-source'}
prefix=['sudo','-n','env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin',*[k+'='+str(epoch/d)for k,d in paths.items()],'python3','-c',"import os,sys;assert os.getuid()==os.geteuid()==0;os.execv(sys.argv[1],sys.argv[1:])"]
records=[]
for i in range(1,11):
 for arm in ('observation',):
  exe=root/f'queue-only-{arm}';log=out/f'{i:02d}-{arm}.log';t=time.monotonic();
  with log.open('wb')as fp:r=subprocess.run([*prefix,exe,'--exact','--ignored','--test-threads=1','--nocapture',case],cwd=root/f'queue-{arm}',stdout=fp,stderr=subprocess.STDOUT)
  txt=log.read_text();marker=re.findall(r'queued original readback error after peer EOF: Some\(([^)]+)\)',txt);m=re.search(r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; 0 ignored;',txt);assert m and int(m[2])+int(m[3])==1 and ((r.returncode==0)==(m[1]=='ok')),(arm,txt[-300:]);assert (len(marker)==1)==(arm=='observation'),(arm,marker)
  records.append({'pair':i,'arm':arm,'exit':r.returncode,'marker':marker,'sha256':sha256(log.read_bytes()).hexdigest(),'wall_s':time.monotonic()-t});(out/'runs.json').write_text(json.dumps(records,indent=2)+'\n')
print({arm:[r['marker'] if arm=='observation'else r['exit'] for r in records if r['arm']==arm]for arm in ['observation']})
