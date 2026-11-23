from pathlib import Path
from hashlib import sha256
import json,os,re,statistics,subprocess,time
r=Path(os.environ['RUNNER_TEMP']);e=r/'sync-evidence';q=Path(os.environ['OBS_FIXTURE']);case='authority_host_service::resident::authority::tests::resident_root_queued_admit_cancellation_sends_no_frame_and_consumes_channel';loc={'HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT':'bind','HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE':'source','HEPTA_CHECKPOINT_TEST_ROOT':'checkpoints','HEPTA_Q24_FACTORY_WITNESS_BIND':'witness-bind','HEPTA_Q24_FACTORY_WITNESS_SOURCE':'witness-source'}
uid="import os,sys; assert os.getuid()==os.geteuid()==0; print('real_uid=0 effective_uid=0',flush=True); os.execv(sys.argv[1],sys.argv[1:])";cmd=['sudo','-n','env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin',*[k+'='+str(q/v) for k,v in loc.items()],'python3','-c',uid];results=[];start=time.monotonic()
for i in range(1,11):
 for arm in (('base','combined')if i%2 else ('combined','base')):
  b=r/f'sync-bin-{arm}';log=e/f'{i:02d}-{arm}.log';begin=time.monotonic()
  with log.open('wb')as output:o=subprocess.run([*cmd,b,'--ignored','--exact',case,'--test-threads=1'],cwd=r/f'sync-{arm}',stdout=output,stderr=subprocess.STDOUT)
  delta=time.monotonic()-begin;raw=log.read_bytes();s=raw.decode();m=re.search(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; 0 ignored;.*finished in ([0-9.]+)s$',s,re.M);assert m and int(m[2])+int(m[3])==1 and ((o.returncode==0)==(m[1]=='ok'));assert 'real_uid=0 effective_uid=0' in s
  results.append({'pair':i,'arm':arm,'code':o.returncode,'sha256':sha256(raw).hexdigest(),'wall_s':delta,'libtest_s':float(m[4]),'result':m[1]});(e/'runs.json').write_text(json.dumps(results,indent=2)+'\n')
summary={}
for arm in ['base','combined']:
 v=[x for x in results if x['arm']==arm];times=[x['wall_s'] for x in v];summary[arm]={'pass':sum(x['code']==0 for x in v),'fail':sum(x['code']!=0 for x in v),'wall_s_total':sum(times),'wall_s_median':statistics.median(times),'wall_s_min':min(times),'wall_s_max':max(times),'libtest_s_total':sum(x['libtest_s']for x in v)}
summary['all_wall_s']=time.monotonic()-start;(e/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));assert all(x['code']==0 for x in results)
