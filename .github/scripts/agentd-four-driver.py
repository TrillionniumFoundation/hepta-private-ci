import collections
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
T=Path(os.environ['RUNNER_TEMP'])
E=T/'four-lint-evidence'
cases=json.loads((T/'four-cases.json').read_text())
names=sorted(n for group in cases.values() for n in group)
if sys.argv[1]=='native':
    records={arm:json.loads((E/f'native-{arm}.json').read_text()) for arm in ('base','candidate')}
    (E/'native.json').write_text(json.dumps(records,indent=2)+'\n')
    assert all(not v['code'] and len(v['cases'])==51 and all(s=='ok' for s in v['cases'].values()) for v in records.values())
elif sys.argv[1]=='native-arm':
    assert len(names)==len(set(names))==51
    records={}
    for arm in (sys.argv[2],):
        assert arm in ('base','candidate')
        binary=T/f'agentd-four-{arm}'
        root=T/f'four-{arm}'
        listed=subprocess.check_output([binary,'--list'],cwd=root,text=True)
        available=set(re.findall(r'^(.+): test$',listed,re.M))
        assert not set(names)-available
        log=E/f'native-{arm}.log'
        with log.open('wb') as out:
            run=subprocess.run([binary,'--exact','--test-threads=1',*names],cwd=root,stdout=out,stderr=subprocess.STDOUT)
        out=log.read_text()
        verdicts=dict(re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)\b',out,re.M))
        records[arm]={'code':run.returncode,'cases':{k:verdicts.get(k) for k in names},'sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'summary':re.findall(r'^test result:.+',out,re.M)}
        print(arm,records[arm]['summary'],flush=True)
        (E/f'native-{arm}.json').write_text(json.dumps(records[arm],indent=2)+'\n')
else:
    def read(arm):
        out=(E/f'strict-{arm}.log').read_text()
        rows=[]
        for block in re.split(r'(?m)^error: ',out)[1:]:
            msg=block.splitlines()[0]
            if msg.startswith('could not compile'): continue
            m=re.search(r'(?m)^\s*--> ([^:\n]+):(\d+):(\d+)\s*$',block)
            assert m,(arm,msg)
            rows.append((m[1],msg))
        assert rows and 'error: could not compile' in out
        return collections.Counter(rows)
    before=read('base');after=read('candidate'); removed=sorted((before-after).elements());added=sorted((after-before).elements())
    result={'base_diagnostics':sum(before.values()),'candidate_diagnostics':sum(after.values()),'removed':removed,'added':added,
            'original_exit_codes':{arm:int((E/f'strict-{arm}.exit').read_text())for arm in ('base','candidate')}}
    (E/'strict.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    expected={'cell_split_owner.rs':'doc list item without indentation','circuit_task_source_codec.rs':'this argument (8 byte) is passed by reference','cell_q24_training_bootstrap_service.rs':'this `if` has identical blocks','neuron_cell_evaluation_panel_member.rs':'call to `std::mem::drop` with a value that does not implement `Drop`'}
    assert not added and len(removed)==4
    assert all(any(path=='hepta-agentd/src/'+p and msg.startswith(m)for path,msg in removed)for p,m in expected.items())
