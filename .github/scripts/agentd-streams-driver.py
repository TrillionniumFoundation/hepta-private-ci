import collections
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
T=Path(os.environ['RUNNER_TEMP'])
E=T/'streams-lint-evidence'
cases=json.loads((T/'streams-cases.json').read_text())
names=sorted(n for group in cases.values() for n in group)
if sys.argv[1]=='native':
    records={arm:json.loads((E/f'native-{arm}.json').read_text()) for arm in ('base','candidate')}
    (E/'native.json').write_text(json.dumps(records,indent=2)+'\n')
    assert all(not v['code'] and len(v['cases'])==14 and all(s=='ok' for s in v['cases'].values()) for v in records.values())
elif sys.argv[1]=='native-arm':
    assert len(names)==len(set(names))==14
    records={}
    for arm in (sys.argv[2],):
        assert arm in ('base','candidate')
        binary=T/f'agentd-streams-{arm}'
        root=T/f'streams-{arm}'
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
    names = ("circuit_selection_command.rs","circuit_next_use_command.rs")
    expected = sorted(("hepta-agentd/src/"+f, "this function has too many arguments (8/7)") for f in names)
    assert removed == expected and not added
    assert result["original_exit_codes"]=={"base":101,"candidate":101}
