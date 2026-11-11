#!/usr/bin/env python3
"""Verify actual remote original blocking bytes; no CI or native rerun."""
import base64, hashlib, io, json, subprocess, sys, tarfile
from pathlib import Path, PurePosixPath
ROOT=Path(__file__).resolve().parent
REMOTE=ROOT/"remote-readback"
def strict(data):
    def unique(pairs):
        out={}
        for k,v in pairs:
            assert k not in out
            out[k]=v
        return out
    return json.loads(data, object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
def identity(data):
    return {"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()}
def read(name):
    o=strict((REMOTE/(name+".json")).read_bytes())
    data=base64.b64decode(o["content"]) if o.get("encoding")=="base64" else o["content"].encode()
    assert identity(data)["git_blob"]==o["sha"]
    return data
def unpack(raw,dest,expected,key):
    files={}
    with tarfile.open(fileobj=io.BytesIO(raw),mode="r:xz") as t:
        for m in t:
            p=PurePosixPath(m.name)
            assert m.isfile() and m.name and not p.is_absolute() and ".." not in p.parts and "\\" not in m.name and m.name not in files
            data=t.extractfile(m).read()
            assert len(data)==m.size
            files[m.name]=data
            target=dest/m.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    manifest=strict(files["MANIFEST.json"])
    assert len(files)==expected
    assert set(files)=={"MANIFEST.json",*(r["path"] for r in manifest[key])}
    for r in manifest[key]: assert identity(files[r["path"]])=={k:r[k] for k in ("bytes","sha256","git_blob")}
    return files
pubraw=read("PUBLICATION.json")
assert identity(pubraw)["git_blob"]=="330eb97523e98373a59a36b02189f22020a196ad"
pub=strict(pubraw);parts=[]
for row in pub["parts"]:
    assert row["offset"]==sum(map(len,parts)) and row["actual_created"] is True
    data=read(row["path"])
    assert identity(data)=={k:row[k] for k in ("bytes","sha256","git_blob")}
    parts.append(data)
raw=b"".join(parts)
assert identity(raw)=={"bytes":pub["archive"]["bytes"],"sha256":pub["archive"]["sha256"],"git_blob":pub["archive"]["computed_git_blob"]}
(ROOT/pub["archive"]["path"]).write_bytes(raw)
dest=ROOT/"root-extracted";files=unpack(raw,dest,24,"members")
for row in pub["texts"]:
    data=read(row["path"]);assert data==files[row["path"]]
    assert identity(data)=={k:row[k] for k in ("bytes","sha256","git_blob")}
# Review both offline verifiers before executing the wrapper.
assert identity(files["verify_terminal_package.py"])["sha256"]=="c31ac7e402397e8c34bcf05db17362377bca5a727ffd0cdd02652e55bd756f16"
old=strict(files["EARLIER_CHECKPOINT_ARCHIVE_INDEX.json"])
old_files=unpack(files[old["name"]],ROOT/"root-inner-original",38,"files")
reviewed=ROOT.parent.parent/"mem-ci-9bd2-original/verify_blocking_checkpoint.py"
assert old_files["verify_blocking_checkpoint.py"]==reviewed.read_bytes()
completed=subprocess.run([sys.executable,str(dest/"verify_terminal_package.py"),str(dest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
assert completed.returncode==0,completed.stderr.decode()
result=strict(completed.stdout)
(ROOT/"ROOT_VERIFIER_REPLAY.json").write_bytes(completed.stdout)
audit={"schema":"mem8.blocking-9bd2.root-full-remote-audit.v1","immutable_commit":"c950c77887cc9a8865bd260a1eba56245ce1327b","archive":identity(raw),"actual_parts":25,"outer_members":24,"inner_members":38,"verifier":result,"whole_archive_git_blob_created":False,"original_mac_full_job_gap_retained":True,"native_commands":0,"model_requests":0}
(ROOT/"ROOT_REMOTE_ARCHIVE_AUDIT.json").write_text(json.dumps(audit,indent=2)+"\n")
print(json.dumps(result,indent=2))
