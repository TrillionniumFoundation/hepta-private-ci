#!/usr/bin/env python3
"""Restore the exact main67-0319 packet without network or product execution."""
import base64, hashlib, io, json, pathlib, stat, sys, zipfile
def ident(b):
    return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def safe_name(name):
    p=pathlib.PurePosixPath(name)
    if p.is_absolute() or any(x in ("",".","..") for x in p.parts) or "\\" in name:raise ValueError("unsafe_path")
    return p
def check(b,row):
    if any(ident(b)[k]!=row[k] for k in ("bytes","sha256","git_blob")):raise ValueError("identity_mismatch")
def extract(z, dest, names):
    if z.testzip() is not None:raise ValueError("zip_crc")
    infos=z.infolist()
    if len(infos)!=len(names) or {x.filename for x in infos}!=set(names):raise ValueError("zip_inventory")
    for info in infos:
        rel=safe_name(info.filename)
        if info.is_dir() or stat.S_ISLNK(info.external_attr>>16):raise ValueError("not_regular_file")
        data=z.read(info);check(data,names[info.filename])
        p=dest.joinpath(*rel.parts);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
def main():
    manifest_path,parts_path,dest=map(pathlib.Path,sys.argv[1:4])
    if dest.exists() and any(dest.iterdir()):raise ValueError("destination_not_empty")
    dest.mkdir(parents=True,exist_ok=True)
    m=json.loads(manifest_path.read_text())
    encoded=[]
    for row in m["parts"]:
        p=parts_path/row["file_name"];data=p.read_bytes();check(data,row);encoded.append(data)
    raw=base64.b64decode(b"".join(encoded),validate=True);check(raw,m["archive"])
    members={row["path"]:row for row in m["members"]}
    physical={p:r for p,r in members.items() if r["storage"]=="outer_zip"}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:extract(z,dest,physical)
    original=dest/m["nested_original_zip"]["path"];check(original.read_bytes(),m["nested_original_zip"])
    nested={p.removeprefix(m["nested_original_zip"]["restore_prefix"]):r for p,r in members.items() if r["storage"]=="original_artifact_zip"}
    with zipfile.ZipFile(original) as z:extract(z,dest/m["nested_original_zip"]["restore_prefix"],nested)
    for p,row in members.items():check((dest/p).read_bytes(),row)
    print(json.dumps({"schema":"hepta-main67-0319-restoration-v1","member_count":len(members),
      "outer_zip_members":len(physical),"original_artifact_members":len(nested),
      "all_members_full_bytes_verified":True,"archive":m["archive"]},indent=2))
if __name__=="__main__":main()
