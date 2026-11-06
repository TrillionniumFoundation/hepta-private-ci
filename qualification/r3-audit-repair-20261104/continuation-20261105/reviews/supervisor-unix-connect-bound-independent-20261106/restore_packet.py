#!/usr/bin/env python3
"""Restore the independent reviewer increment and verify exact file custody only."""
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
freeze=json.loads((output/"DELIVERY-MANIFEST.json").read_bytes())
for row in freeze["files"]:check((output/row["path"]).read_bytes(),row)
assert len(freeze["files"]) == 16
assert ident((output/"REVIEW.json").read_bytes())["git_blob"] == "35b07140231fa056026ca00088930873a4812b55"
print(json.dumps({
    "schema":"hepta-supervisor-unix-connect-independent-increment-restore-v1",
    "members_restored":len(m["members"]),
    "frozen_reviewer_files_verified":len(freeze["files"]),
    "archive":ident(raw),
    "scope":"Exact archive/member identity restoration only. This restorer does not execute the independent verifier.",
    "independent_review":"35b07140231fa056026ca00088930873a4812b55",
    "external_required_inputs_for_full_verifier":{
        "author_registry":"b336a8470de7111b0bb037a3c1d801bcadaba0d2",
        "old_terminal_registry":"23e67ce20a439e2968eb63ae4e9a74a214ccd081"
    },
    "original_failure_cause":"UNKNOWN",
    "Rust_fmt_native_CI_executed":False,
    "ledger_transitions":[]
},indent=2))
