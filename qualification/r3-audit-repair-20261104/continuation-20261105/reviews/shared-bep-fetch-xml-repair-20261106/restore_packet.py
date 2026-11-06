#!/usr/bin/env python3
"""Restore the immutable candidate snapshot; no product/native command is run."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

def identity(data):
    return {"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()}

def safe_name(name):
    path=PurePosixPath(name)
    assert name and not path.is_absolute() and "\\" not in name
    assert all(part not in ("",".","..") for part in path.parts)
    return path

def main():
    assert len(sys.argv)==3, "usage: restore_packet.py manifest.json NEW_DESTINATION"
    manifest_path=Path(sys.argv[1]).resolve()
    manifest=json.loads(manifest_path.read_bytes())
    encoded=[]
    for item in manifest["parts"]:
        path=manifest_path.parent/safe_name(item["path"])
        data=path.read_bytes()
        assert identity(data)=={k:item[k] for k in ("bytes","sha256","git_blob")}
        encoded.append(data)
    archive=base64.b64decode(b"".join(encoded),validate=True)
    assert identity(archive)==manifest["archive"]
    destination=Path(sys.argv[2]).resolve()
    assert not destination.exists(),"destination must be new"
    destination.mkdir(parents=True)
    expected={m["path"]:m for m in manifest["members"]}
    assert len(expected)==len(manifest["members"])
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert len(z.namelist())==len(set(z.namelist()))==len(expected)
        assert set(z.namelist())==set(expected)
        for name in z.namelist():
            member=expected[name];info=z.getinfo(name)
            target=destination/safe_name(name)
            assert target.resolve().is_relative_to(destination)
            mode=info.external_attr>>16
            if member["kind"]=="directory":
                assert info.is_dir() and stat.S_ISDIR(mode)
                target.mkdir(parents=True,exist_ok=True)
                target.chmod(member["mode"])
            else:
                assert not info.is_dir() and stat.S_ISREG(mode)
                data=z.read(name)
                assert identity(data)=={k:member[k] for k in ("bytes","sha256","git_blob")}
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open("xb") as f:f.write(data)
                target.chmod(member["mode"])
    files=[m for m in manifest["members"] if m["kind"]=="file"]
    for m in files:
        assert identity((destination/m["path"]).read_bytes())=={k:m[k] for k in ("bytes","sha256","git_blob")}
    print(json.dumps({"schema":"shared-fetch-xml-lossless-restore-v1","all_member_bytes_equal":True,
                      "files":len(files),"directories":len(manifest["members"])-len(files),
                      "archive":manifest["archive"],"native_execution":False},indent=2,sort_keys=True))

if __name__=="__main__":main()
