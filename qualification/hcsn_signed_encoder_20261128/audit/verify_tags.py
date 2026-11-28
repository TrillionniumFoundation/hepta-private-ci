"""Hash raw annotated tag objects, including nested tags, from the pinned ls-remote snapshot."""
from datetime import datetime,timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

base = Path.home()/".local/state/hepta-hcsn-1140569-audit"
hist = base/"historical-closure-9de7"
source = base/"refs-namespace/delta/recovery_9de7/new_snapshot/advertisement.tsv.gz"
out = hist/"annotated-tags"
out.mkdir(exist_ok=True)
advertisement = gzip.decompress(source.read_bytes())
sha = lambda x: hashlib.sha256(x).hexdigest()
assert sha(advertisement) == "e766e7f70bfe56b9b07259ff51b55b70a2a1a6bb5343544f8df650e943f23133"
refs = {ref:oid for oid,ref in (row.split(b"\t") for row in advertisement.splitlines()) if ref.startswith(b"refs/tags/")}
direct = {k:v for k,v in refs.items() if not k.endswith(b"^{}")}
annotated = {k:v for k,v in direct.items() if k+b"^{}" in refs}
env = {**os.environ,"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_TERMINAL_PROMPT":"0"}
rows = {}
with tempfile.TemporaryDirectory(dir=out) as d:
    scratch = Path(d)
    git = ["git","-C",d]
    subprocess.run(git+["init","--bare","--quiet"],check=True)
    (scratch/"objects/info/alternates").write_text(str((hist/"objects.git/objects").resolve())+"\n")
    def get(oid):
        a = subprocess.run(git+["cat-file","tag",oid.decode()],capture_output=True,env=env)
        if a.returncode:
            subprocess.run(git+["-c","gc.auto=0","fetch","--quiet","--depth=1","--filter=tree:0","--no-tags","--no-write-fetch-head","https://github.com/TrillionniumFoundation/hepta-private-ci.git",oid.decode()],check=True,timeout=120,env=env)
            raw = subprocess.check_output(git+["cat-file","tag",oid.decode()],env=env)
        else:
            raw = a.stdout
        assert hashlib.sha1(b"tag "+str(len(raw)).encode()+b"\0"+raw).hexdigest().encode() == oid
        return raw
    for ref,oid0 in sorted(annotated.items()):
        oid = oid0
        while True:
            if oid not in rows:
                v = get(oid)
                first,second = v.splitlines()[:2]
                assert first.startswith(b"object ") and second.startswith(b"type ")
                rows[oid] = (len(v),sha(v),first.split()[1],second.split()[1])
            _,_,target,kind = rows[oid]
            if kind != b"tag":
                assert kind == b"commit" and target == refs[ref+b"^{}"]
                break
            oid = target
payload = b"".join(o+b"\t"+str(n).encode()+b"\t"+digest.encode()+b"\t"+target+b"\t"+kind+b"\n" for o,(n,digest,target,kind) in sorted(rows.items()))
(out/"verified.tsv.gz").write_bytes(gzip.compress(payload,mtime=0))
summary = dict(utc=datetime.now(timezone.utc).isoformat(),advertisement_sha256=sha(advertisement),tag_refs=len(direct),annotated_refs=len(annotated),lightweight_refs=len(direct)-len(annotated),unique_tag_objects=len(rows),raw_tag_bytes=sum(v[0] for v in rows.values()),ledger_sha256=sha(payload),all_peeled_types="commit",nested_tag_links=sum(v[3]==b"tag" for v in rows.values()))
(out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
print(summary,flush=True)
