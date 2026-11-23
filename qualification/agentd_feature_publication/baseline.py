"""Read original c12 strict diagnostics and two independent native executions."""
from collections import Counter
from hashlib import sha256
import json, re, sys
from pathlib import Path
from zipfile import ZipFile

root=Path(__file__).resolve().parent
musl, startup, strict_a, strict_b=map(Path,sys.argv[1:])
targets=json.loads((root/'original-tests.json').read_bytes())
def digest(p): return sha256(p.read_bytes()).hexdigest()
assert digest(musl)=='1bd9f7d8550cab47ba77089de6362a32bf99191ddc0bff8d970c1f5fd9ebe563'
assert digest(startup)=='2946327047596b49f097857dcd548fc26a35e7c18c597e80216dffdf39a334aa'
with ZipFile(musl) as z:
    results={}
    for name in z.namelist():
        if name.startswith('7016/') and '/files/' in name and name.endswith('.log'):
            raw=z.read(name)
            for target in targets:
                matches=re.findall(r'^test '+re.escape(target)+r' \.\.\. (ok|FAILED)$',raw.decode(errors='replace'),re.M)
                if matches:
                    assert matches==['ok'] and target not in results
                    results[target]={'status':'ok','member':name,'sha256':sha256(raw).hexdigest()}
    assert set(results)==set(targets)
with ZipFile(startup) as z:
    assert z.read('tested-commit.txt').decode().strip()=='c12ee03f3185d5a13949faca54f066dfd634e509'
    log=z.read('all-agentd-unit-tests.log')
    native={}
    for target in targets:
        lines=[s for s in log.decode().splitlines() if s.rstrip().endswith(' '+target)]
        assert len(lines)==1 and lines[0].lstrip().startswith('PASS [')
        native[target]='PASS'
all_strict={}
for path in [strict_a,strict_b]:
    s=re.sub(r'^\S+Z ', '', path.read_text(),flags=re.M)
    lst=[]
    for m in re.finditer(r'^error: (.+)\n\s*--> ([^:]+):(\d+):(\d+)',s,re.M):
        lst.append(dict(path='codex-rs/'+m[2],line=int(m[3]),column=int(m[4]),diagnostic=m[1]))
    assert len(lst)==115
    frozen=json.loads((root/'strict-base.json').read_bytes())
    def key(x):return tuple(sorted(x.items()))
    assert Counter(map(key,lst))==Counter(map(key,frozen))
    all_strict[path.name]=dict(sha256=digest(path),count=len(lst),large_variants=sum(x['diagnostic']=='large size difference between variants' for x in lst))
print(json.dumps({'musl_source':'ae404b2935fa0b7ea39bf09ef1016917a507f6d5','musl_tree':'9554ddb1b5cca7502b58b7bacfc446671fe5289c','musl_archive':digest(musl),'musl_tests':results,'startup_archive':digest(startup),'startup_log':sha256(log).hexdigest(),'startup_tests':native,'strict':all_strict},sort_keys=True,indent=2))
