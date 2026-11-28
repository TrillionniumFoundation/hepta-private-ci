"""Search all pinned tip text blobs previously observed to contain HCSN, preserving evidence scope."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import sqlite3
import sys

R=Path.home()/".local/state/hepta-hcsn-1140569-audit"
H=R/"historical-closure-9de7"
D=H/"hcsn-longtext"
D.mkdir(exist_ok=True)
terms={
    "wikitext":rb"wiki[\s._-]*text(?:[\s._-]*(?:103|2))?",
    "fineweb":rb"fine[\s._-]*web",
    "pg19":rb"\bpg[\s._-]*19\b|project gutenberg",
    "openwebtext":rb"open[\s._-]*web[\s._-]*text",
    "pile":rb"eleutherai[/ _-]+(?:the[ _-]+)?pile|\bthe[ _-]pile\b|\bpile-(?:cc|uncopyrighted)\b",
    "c4_dataset":rb"colossal clean crawled corpus|allenai[/ ]c4|c4/(?:en|multilingual)|['\"]c4['\"]",
    "dolma":rb"\bdolma\b",
    "lambada":rb"\blambada\b",
    "redpajama":rb"red[ _-]*pajama",
    "long_language":rb"causal[ _-]*language[ _-]*model|long[ _-]*(?:form natural|context language)|autoregressive[ _-]*language|next[ _-]*(?:word|token)[ _-]*(?:predict|loss|objective)|language[ _-]*model[ _-]*pretrain",
    "token_loss":rb"perplexity|\blm[ _-]*head\b|\bbits per (?:byte|character)\b|\bcausal[_ ]lm\b"
}
ledger=gzip.decompress((H/"tip-evidence/verified_objects.tsv.gz").read_bytes())
assert hashlib.sha256(ledger).hexdigest()=="3f2e6aa0c03599b2872990b6db7fe26d73a82065a2b523a95cd70c704c15e267"
target={oid.decode() for oid,n,fl,nu,sha,source in (row.split(b'\t') for row in ledger.splitlines()[1:]) if int(fl)>=0 and int(fl)&1}
assert len(target)==17669
roster=D/"roster.txt.gz"
raw="".join(s+"\n" for s in sorted(target)).encode()
roster.write_bytes(gzip.compress(raw,mtime=0))
sys.path.insert(0,str(R))
import screen
screen.REGEX=[re.compile(s) for s in terms.values()]
os.environ["HEPTA_AUDIT_OUTPUT"]=str(D)
sys.argv=[str(H/"history_payloads.py"),str(roster),"2","data"]
runpy.run_path(str(H/"history_payloads.py"),run_name="__main__")
with sqlite3.connect(D/"data/results.sqlite") as db:
    rows=list(db.execute("select * from files order by oid"))
hits={key:[] for key in terms}
for oid,n,sha,nul,flags in rows:
    if flags>=0:
        for i,key in enumerate(terms):
            if flags&(1<<i):hits[key].append(oid)
summary=dict(input_ledger_sha256=hashlib.sha256(ledger).hexdigest(),target=len(target),target_set_sha256=hashlib.sha256(raw).hexdigest(),read=len(rows),bytes=sum(x[1] for x in rows),missing=len(target)-len(rows),counts={k:len(v) for k,v in hits.items()},hit_ids=hits)
(D/"result.json").write_text(json.dumps(summary,indent=2)+"\n")
print({k:v for k,v in summary.items() if k!="hit_ids"},flush=True)
