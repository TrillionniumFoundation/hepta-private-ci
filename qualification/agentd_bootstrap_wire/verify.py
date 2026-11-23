"""Independently read the original GitHub ZIPs. Run from a downloaded evidence directory."""
from collections import Counter
import hashlib
import json
import re
import sys
from pathlib import Path
from zipfile import ZipFile

base = '43e5da1bb81369e4e999adfa8558f5ccb5460eb6'
candidate = '2b75c8df6b804b87dd8c3cbca8d8a4b37d1d97d4'
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
baseline = root/'baseline-115.json'
sha = lambda data: hashlib.sha256(data).hexdigest()
assert sha(baseline.read_bytes()) == 'da02bc0a91f6e9e33913e8c914a697926276f820c9387eb4248e7249225a8922'
snapshot = json.loads(baseline.read_bytes())
assert snapshot['source']==base and snapshot['compiler_exit']==101
def load(name):
    content = (root/name).read_bytes()
    with ZipFile(root/name) as z:
        assert len(set(z.namelist())) == len(z.namelist())
        return sha(content), {i: z.read(i) for i in z.namelist()}

hashes = {}
hashes['strict.zip'], files = load('strict.zip')
assert files['commit.txt'].decode().strip()==candidate
assert int(files['strict.exit']) == 101
initial = sorted((d['path'], d['line'], d['column'], d['diagnostic']) for d in snapshot['diagnostics'])
clippy = files['strict.log'].decode()
after = []
for m in re.finditer(r'^error: (.+)\n\s*--> ([^\n:]+):(\d+):(\d+)$', clippy, re.M):
    msg, path, line, col = m.groups()
    after.append(('codex-rs/'+path.removeprefix('codex-rs/'),int(line),int(col),msg))
before, actual = Counter(initial), Counter(after)
diff = list((before-actual).elements())
assert [r[0] for r in diff] == ['codex-rs/hepta-agentd/src/authority_host_publication_bootstrap.rs']
assert diff[0][-1] == 'large size difference between variants'
assert before.total()==115 and actual.total()==114 and not actual-before
assert not re.search(r'^error\[E\d+\]',clippy,re.M)
assert len(re.findall(r'^error: (?!could not compile)',clippy,re.M)) == len(after)
selected = ('versioned_record_rejects_hybrid_unknown_fields_and_invalid_live_binding',
            'successor_deployment_requires_every_original_pin_and_bounded_context',
            'root_broker_late_enrolls_publishes_and_recovers_original_current')
wire = 'QUALIFIED_WIRE_OBJECT v1-positive=1 v2-positive=1 encoder-negative=2 decoder-negative=16 reencode-bytes=2'
arms = {}
normalized = {}
for arm, fixed in [('base',base),('candidate',candidate)]:
    hashes[f'{arm}.zip'], f = load(f'{arm}.zip')
    assert f['source.txt'].decode().strip()==fixed
    assert b'Ran 12 tests in ' in f['source-tests.log'] and f['source-tests.log'].strip().endswith(b'OK')
    originals=f['originals.txt'].decode().splitlines()
    assert len(originals)==3
    normalized[arm]={row.split('\t')[1]:row.split()[2] for row in originals}
    assert len(f['observer-hashes.txt'].decode().strip().splitlines())==3
    assert b'Build completed successfully' in f['build.log']
    out=json.loads(f[f'native-{arm}.json'])
    assert out['TEST-only observer'] and re.fullmatch(r'[0-9a-f]{64}',out['ELF_SHA256'])
    rows = {}
    for mode in ('ordinary','uid0'):
        data=f[f'{arm}-{mode}.log'];log=data.decode()
        assert out[mode]['log_sha256']==sha(data) and out[mode]['exit']==0
        observed = dict(re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)$',log,re.M))
        expected = selected[:2] if mode=='ordinary' else selected[2:]
        assert sorted(k.rsplit('::',1)[-1] for k in observed)==sorted(expected)
        assert all(s=='ok' for s in observed.values())
        assert f'test result: ok. {len(expected)} passed; 0 failed; 0 ignored;' in log
        rows[mode]=sorted(observed)
        if mode=='uid0':
            assert 'actual UID0' in log
            for terminal in ('StalePrepare','Revoked'):
                assert f'ROOT_PUBLICATION_ORIGINAL lifecycle=passed terminal={terminal}' in log
            rows['wire_observations']=log.count(wire)
            assert rows['wire_observations']==10
    arms[arm]={'fixed_source':fixed,'observer':f['observer-hashes.txt'].decode().splitlines(),'ELF_SHA256_host_receipt':out['ELF_SHA256'],**rows}
assert arms['candidate']['observer']==arms['base']['observer']
assert arms['candidate']['ELF_SHA256_host_receipt']!=arms['base']['ELF_SHA256_host_receipt']
assert set(normalized['candidate'])==set(normalized['base'])
assert [p for p in normalized['candidate'] if normalized['candidate'][p]!=normalized['base'][p]]==['codex-rs/hepta-agentd/src/authority_host_publication_bootstrap.rs']
result={'run':45140670897,'archives_sha256':hashes,'strict':{'before':115,'after':114,'base_and_candidate_compiler_exit':101,'removed':diff,'added':[]},'native':arms}
print(json.dumps(result,indent=2,sort_keys=True))
