"""Verify exact candidate, diagnostics, native cases and original source/binary receipts."""
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
from hashlib import sha256
import json,re

root=Path(__file__).resolve().parent
candidate='6d65e2ee95f37d1f4983e3ba7393ed8ac2163c80'
cases=json.loads((root/'original-tests.json').read_bytes())
strict_base=json.loads((root/'strict-base.json').read_bytes())
def digest(data):return sha256(data).hexdigest()
def unpack(name):
    data=(root/name).read_bytes()
    with ZipFile(root/name) as z:
        raw={p:z.read(p) for p in z.namelist()}
    assert raw['source.txt'].decode().strip()==candidate
    return digest(data),raw

s_sha,s=unpack('strict.zip')
assert s_sha=='cd63f4134fb365e0e2bd9523aaee7e9126f219903ad50b0c1b0b145a0a71722c'
assert int(s['strict.exit'])==101
text=s['strict.log'].decode()
assert not re.search(r'^error\[E[0-9]+\]',text,re.M)
def key(row):return tuple(row[k] for k in ('path','line','column','diagnostic'))
before=Counter(map(key,strict_base));after=Counter()
for err in re.split(r'^error: ',text,flags=re.M)[1:]:
    message=err.splitlines()[0]
    if message.startswith('could not compile'):continue
    loc=re.search(r'^\s*--> (.+?):(\d+):(\d+)\s*$',err,re.M)
    assert loc
    after[('codex-rs/'+loc[1].removeprefix('codex-rs/'),int(loc[2]),int(loc[3]),message)]+=1
assert after-before=={} and list((before-after).elements())==[('codex-rs/hepta-agentd/src/circuit_feature_current.rs',161,1,'large size difference between variants')]
paired=json.loads(s['strict-comparison.json'])
assert before.total()==paired['base_count']==115 and after.total()==paired['candidate_count']==114
n_sha,n=unpack('native.zip')
assert n_sha=='39cc832c2b9ca5019aa0ebf8560ad98a49972d917c8d84dac5f3eb4316cffcfe'
guards=json.loads(n['guards.json'])
assert guards==json.loads((root/'guards-base.json').read_bytes())==json.loads((root/'guards-candidate.json').read_bytes())
assert b'Build completed successfully' in n['build.log']
native=json.loads(n['native.json'])
native_text=n['native.log'].decode()
results=re.findall(r'^test ([^ ]+) \.\.\. (ok|FAILED)$',native_text,re.M)
assert Counter(results)==Counter((name,'ok') for name in cases)
assert 'test result: ok. 6 passed; 0 failed; 0 ignored;' in native_text
assert native['results']==dict(results) and native['exit']==0 and re.fullmatch(r'[0-9a-f]{64}',native['sha256'])
listed=set(re.findall(r'^(.+): test$',n['listing.txt'].decode(),re.M))
assert set(cases)<=listed
base=json.loads((root/'baseline.json').read_bytes())
assert set(base['musl_tests'])==set(base['startup_tests'])==set(cases)
print(json.dumps({'candidate':candidate,'candidate_native_sha256':native['sha256'],'native_artifact_sha256':n_sha,'strict_artifact_sha256':s_sha,'native_test_count':len(results),'native_results':dict(results),'strict_count':{'base':before.total(),'candidate':after.total()},'large_enum':{'base':sum(n for k,n in before.items() if k[3]=='large size difference between variants'),'candidate':sum(n for k,n in after.items() if k[3]=='large size difference between variants')},'removed':list((before-after).elements()),'other_changes_to_diagnostics':0,'compiler_exit':101,'guard':guards},sort_keys=True,indent=2))
