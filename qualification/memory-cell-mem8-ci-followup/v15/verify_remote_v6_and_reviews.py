#!/usr/bin/env python3
"""Verify immutable evidence bytes; never execute native tests or model calls."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

BASE = Path(__file__).resolve().parent
REF = "605f7959c6e00b981dad54cc69d913014ab65bab"
def strict(data):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            assert key not in out, key
            out[key] = value
        return out
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
def identity(data):
    return {"bytes":len(data), "sha256":hashlib.sha256(data).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()}
def safe(name):
    p = PurePosixPath(name)
    assert name and not p.is_absolute() and ".." not in p.parts and "\\" not in name
    return p
def decoded(path):
    record = strict(path.read_bytes())
    data = base64.b64decode(record["content"]) if record.get("encoding") == "base64" else record["content"].encode()
    assert identity(data)["git_blob"] == record["sha"]
    return data
def unpack(data, destination, count, manifest_name, member_key):
    destination.mkdir(parents=True,exist_ok=True)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data),mode="r:xz") as archive:
        for member in archive:
            safe(member.name)
            assert member.isfile() and member.name not in files
            raw = archive.extractfile(member).read()
            assert len(raw) == member.size
            files[member.name] = raw
            path = destination/member.name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)
    assert len(files) == count
    manifest = strict(files[manifest_name])
    rows = manifest[member_key]
    assert len(rows) == count-1 and len({x["path"] for x in rows}) == len(rows)
    assert set(files) == {manifest_name, *(x["path"] for x in rows)}
    for row in rows:
        assert identity(files[row["path"]]) == {k:row[k] for k in ("bytes","sha256","git_blob")}
    return files
def save(section, audit):
    (BASE/section/"ROOT_REMOTE_ARCHIVE_AUDIT.json").write_text(json.dumps(audit,indent=2)+"\n")

section="source-ci-v6"
rr=BASE/section/"remote-readback"
pubraw=decoded(rr/"PUBLICATION.json.json")
assert identity(pubraw)=={"bytes":7786,"sha256":"a19116f424eb31b82eb51ac877b0f4a25e499bb39afbc689a1c5d48c0126f179","git_blob":"2b19c83422bd1499c3223965cde369240cbbee23"}
pub=strict(pubraw)
chunks=[]
for part in pub["parts"]:
    assert part["actual_created"] is True and part["offset"] == sum(map(len,chunks))
    raw=decoded(rr/(part["path"]+".json"))
    assert identity(raw)=={k:part[k] for k in ("bytes","sha256","git_blob")}
    chunks.append(raw)
raw=b"".join(chunks)
assert identity(raw)=={"bytes":pub["archive"]["bytes"],"sha256":pub["archive"]["sha256"],"git_blob":pub["archive"]["computed_git_blob"]}
path=BASE/section/pub["archive"]["path"];path.write_bytes(raw)
dest=BASE/section/"root-extracted"
files=unpack(raw,dest,22,"MANIFEST.json","members")
for row in pub["texts"]:
    data=decoded(rr/(row["path"]+".json"))
    assert identity(data)=={k:row[k] for k in ("bytes","sha256","git_blob")}
    assert data==files[row["path"]]
# These exact verifier bytes were reviewed before invocation. The source-record
# verifier matches the previously independently reviewed and replayed original.
assert identity(files["verify_package.py"])["sha256"]=="86ba5b800b1967f614423af69c1b76b6272232ecfa486d94ab3204fe7de4009a"
assert identity(files["verify_source_records.py"])["sha256"]=="f4c63d00d3def7a99449afd74831c3d611957f3b5b45f2b7cc3c723f996a1993"
completed=subprocess.run([sys.executable,str(dest/"verify_package.py"),str(dest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
assert completed.returncode==0,completed.stderr.decode()
result=strict(completed.stdout)
(BASE/section/"ROOT_PACKAGE_REPLAY.json").write_bytes(completed.stdout)
save(section,{"schema":"mem8.v6.root-full-remote-audit.v1","immutable_commit":REF,"actual_parts":13,
              "archive":identity(raw),"outer_members":22,"original_artifact":identity(files["ORIGINAL_ARTIFACT.zip"]),
              "full_raw_job":identity(files["ORIGINAL_JOB.log"]),"offline_replay":result,
              "whole_archive_created_as_blob":False,"native_executions":0,"model_calls":0})
print(section,result)

section="elevated-capability";rr=BASE/section/"remote-readback"
raw=decoded(rr/"ORIGINAL_AND_PINNED_SOURCE.tar.xz.json")
assert identity(raw)=={"bytes":83004,"sha256":"3c26804288fe01143b6c156cc3308deca64adb68846435f129bad5c3bdb4dfcc","git_blob":"14faadee966c4db19f2c4a60cc70535d20aadae4"}
dest=BASE/section/"root-extracted"; files=unpack(raw,dest,31,"FILE_MANIFEST.json","files")
for name in ["PRODUCT_REPAIR_FEASIBILITY.json","REPORT.md","CURRENT_ORIGINAL_ACL_AUDIT.json","FILE_MANIFEST.json","verify_review.py"]:
    assert decoded(rr/(name+".json"))==files[name]
assert identity(files["verify_review.py"])["sha256"]=="5a31de2804a5fc6590c7087ac4661053d4be40873c209bdcd417dd83dbf547c2"
completed=subprocess.run([sys.executable,str(dest/"verify_review.py")],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
assert completed.returncode==0,completed.stderr.decode()
result=strict(completed.stdout)
(BASE/section/"ROOT_VERIFIER_REPLAY.json").write_bytes(completed.stdout)
save(section,{"schema":"mem8.elevated.root-full-remote-byte-audit.v1","immutable_commit":REF,"archive":identity(raw),
              "outer_members":31,"offline_replay":result,"mechanism_review":"separate from byte verification",
              "product_repaired":False,"native_executions":0,"model_calls":0})
print(section,result)

section="fence";rr=BASE/section/"remote-readback"
raw=base64.b64decode((rr/"ORIGINAL_AND_PINNED_SOURCE.tar.xz.b64").read_bytes())
assert identity(raw)=={"bytes":140444,"sha256":"830d20bf8c8b996622464d8a1e3f18433e38b5d30ed9106e4e3c7993b7142768","git_blob":"de540cd7badf8c1029f42a6048cc32e99dd164df"}
dest=BASE/section/"root-extracted";files=unpack(raw,dest,23,"FILE_MANIFEST.json","files")
for remote,inner in [("REPORT.json","READ_ONLY_REVIEW.json"),("README.md","REPORT.md"),("MANIFEST.json","FILE_MANIFEST.json")]:
    assert (rr/remote).read_bytes()==files[inner]
save(section,{"schema":"mem8.fence.root-full-remote-byte-audit.v1","immutable_commit":"6cad9bff3510dbe18e33709dea50be693c51f3a5",
              "archive":identity(raw),"outer_members":23,"manifested_members":22,
              "mechanism_review":"separate from byte verification","original_inventory_snapshot_recovered":False,
              "native_executions":0,"model_calls":0})
print(section,{"members":23,"bytes":len(raw),"status":"PASS_REMOTE_BYTES"})
