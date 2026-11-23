import collections,hashlib,json,os,re,subprocess,sys
from pathlib import Path
T=Path(os.environ['RUNNER_TEMP']);E=T/'enum-evidence';cases=json.loads((T/'enum-cases.json').read_text())
if sys.argv[1]=='strict':
    def load(arm):
        output=(E/f'strict-{arm}.log').read_text(); rows=[]
        assert not re.search(r'(?m)^error\[E\d+\]',output)
        for block in re.split(r'(?m)^error: ',output)[1:]:
            msg=block.splitlines()[0]
            if msg.startswith('could not compile'):continue
            match=re.search(r'(?m)^\s*--> ([^:\n]+):(\d+):(\d+)\s*$',block);assert match,(arm,msg)
            rows.append((match[1],msg))
        assert rows and 'error: could not compile' in output
        return collections.Counter(rows)
    b,c=load('base'),load('candidate');removed=sorted((b-c).elements());added=sorted((c-b).elements());report={'base':sum(b.values()),'candidate':sum(c.values()),'removed':removed,'added':added,'status':{arm:int((E/f'strict-{arm}.exit').read_text()) for arm in ('base','candidate')}}
    (E/'strict.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    target=['root_independent_b_client','authority_host_publication_completed','authority_host_learning_resident_gate','cell_q24_model_command_connection','cell_q24_training_command_connection'];expect=sorted(('hepta-agentd/src/'+name+'.rs','large size difference between variants')for name in target);assert removed==expect and not added
elif sys.argv[1]=='native':
    records={arm:json.loads((E/f'native-{arm}.json').read_text()) for arm in ('base','candidate')};(E/'native.json').write_text(json.dumps(records,indent=2)+'\n')
    assert all(all(item['code']==0 and all(s=='ok' for s in item['tests'].values())for item in arm.values()) for arm in records.values())
else:
    arm=sys.argv[2];assert arm in ('base','candidate');root=T/f'enum-{arm}';bin=T/f'agentd-enum-{arm}';available=subprocess.check_output([bin,'--list'],cwd=root,text=True);alltests=set(re.findall(r'^(.+): test$',available,re.M));results={}
    for mode,files in cases.items():
        names=sorted(n for row in files.values()for n in row);assert len(names)==len(set(names)) and set(names)<=alltests
        flags=[bin,'--exact','--test-threads=1'];prefix=[]
        if mode=='uid0':
            flags+=['--ignored'];envvars=('HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT','HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE','HEPTA_CHECKPOINT_TEST_ROOT','HEPTA_Q24_FACTORY_WITNESS_BIND','HEPTA_Q24_FACTORY_WITNESS_SOURCE');prefix=['sudo','-n','env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin',*[key+'='+os.environ[key] for key in envvars],'python3','-c',"import os,sys;assert os.getuid()==os.geteuid()==0;print('libtest actual real/effective UID:',os.getuid(),os.geteuid(),flush=True);os.execv(sys.argv[1],sys.argv[1:])"]
        else:
            assert os.getuid()!=0 and os.geteuid()!=0
        log=E/f'{arm}-{mode}.log'
        with log.open('wb')as fp: proc=subprocess.run([*prefix,*flags,*names],cwd=root,stdout=fp,stderr=subprocess.STDOUT)
        txt=log.read_text();observed=dict(re.findall(r'^test ([^ ]+) \.\.\. (ok|FAILED|ignored)\b',txt,re.M));results[mode]={'code':proc.returncode,'tests':{n:observed.get(n) for n in names},'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'ELF':hashlib.sha256(bin.read_bytes()).hexdigest(),'libtest_summary':re.findall(r'^test result:.+',txt,re.M)};print(arm,mode,results[mode]['libtest_summary'],flush=True)
    (E/f'native-{arm}.json').write_text(json.dumps(results,indent=2)+'\n')
