#!/usr/bin/env python3
"""Restore only this narrow assessment, then run its offline verifier."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

def ident(b):
    return {"bytes":len(b),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(),"sha256":hashlib.sha256(b).hexdigest()}

def check(b,x):
    for k,v in ident(b).items(): assert x[k]==v,(k,x.get(k),v)

packet=Path(sys.argv[1]).resolve()
output=Path(sys.argv[2]).resolve()
assert not output.exists(),"Use a new empty restore path"
m=json.loads((packet/"archive.json").read_bytes())
joined=[]
for row in m["parts"]:
    b=(packet/row["path"]).read_bytes();check(b,row);joined.append(b)
raw=base64.b64decode(b"".join(joined),validate=True)
check(raw,m["archive"])
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    assert z.testzip() is None
    names=z.namelist()
    assert sorted(names)==sorted(x["path"] for x in m["members"])
    assert len(names)==len(set(names))
    output.mkdir(parents=True)
    for row in m["members"]:
        name=row["path"];p=Path(name)
        assert not p.is_absolute() and ".." not in p.parts
        b=z.read(name);check(b,row)
        target=output/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
freeze=json.loads((output/"freeze-manifest.json").read_bytes())
for row in freeze["files"]:check((output/row["path"]).read_bytes(),row)
r=subprocess.run([sys.executable,"-B",str(output/"verify_review.py"),str(output)],cwd=output,capture_output=True)
assert r.returncode==0 and r.stderr==b"",(r.returncode,r.stderr.decode(errors="replace"))
assert r.stdout==(output/"verification.stdout.json").read_bytes()
print(json.dumps({"schema":"hepta-b21-readonly-causal-packet-restore-v1","members_restored":len(m["members"]),"freeze_members_verified":len(freeze["files"]),"archive":ident(raw),"offline_verifier_exit":r.returncode,"offline_verifier_stderr_bytes":len(r.stderr),"offline_verifier_stdout":ident(r.stdout),"replay_scope":"Only compact source ancestry, exact original excerpt, source/primary identities and stated fact invariants. Does not rerun original CI, tested Rust, full job, or original large packet.","B21":"OPEN","ledger_transitions":[]},indent=2))

