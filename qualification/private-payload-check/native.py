"""Run the original forms under ordinary user and the original UID0 fixture."""
from pathlib import Path
from hashlib import sha256
import json,os,re,subprocess,sys

binary,roster,evidence=map(Path,sys.argv[1:])
binary=binary.resolve()
groups=json.loads(roster.read_bytes())
assert len(groups['ordinary'])==6 and len(groups['uid0'])==1
listing=subprocess.check_output([binary,'--list'],text=True)
(evidence/'listing.txt').write_text(listing)
assert all(listing.splitlines().count(n+': test')==1 for ns in groups.values() for n in ns)
with binary.open('rb') as stream:
    h=sha256()
    while data:=stream.read(1024*1024):h.update(data)
summary={'binary_sha256':h.hexdigest(),'groups':{}}
for mode,names in groups.items():
    start=[]
    flags=[binary,'--exact','--test-threads=1']
    if mode=='uid0':
        retained=('HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT','HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE','HEPTA_CHECKPOINT_TEST_ROOT','HEPTA_Q24_FACTORY_WITNESS_BIND','HEPTA_Q24_FACTORY_WITNESS_SOURCE')
        start=['sudo','-n','env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin','RUST_MIN_STACK=8388608',*[f'{k}={os.environ[k]}' for k in retained],'python3','-c',"import os,sys;assert os.getuid()==os.geteuid()==0;print('libtest real and effective UID 0',flush=True);os.execv(sys.argv[1],sys.argv[1:])"]
        flags+=['--ignored']
    run=subprocess.run([*start,*flags,*names],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (evidence/(mode+'.log')).write_text(run.stdout)
    blocks = re.split(r'^test (\S+) \.\.\. ', run.stdout.split('test result:', 1)[0], flags=re.M)
    result = {}
    for name, body in zip(blocks[1::2], blocks[2::2], strict=True):
        if name in result:
            raise RuntimeError(f"duplicate original case {name}")
        result[name] = body.rstrip().splitlines()[-1].strip()
    summary['groups'][mode]={'exit':run.returncode,'status':result}
    print(run.stdout,flush=True)
    (evidence/'native.json').write_text(json.dumps(summary,indent=2)+'\n')
    if run.returncode or result!=dict.fromkeys(names,'ok') or not re.search(r'^test result: ok\. '+str(len(names))+r' passed; 0 failed; 0 ignored;',run.stdout,re.M):
        raise SystemExit(run.returncode or 2)
