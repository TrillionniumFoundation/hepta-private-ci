#!/usr/bin/env python3
"""Restore the exact fixed bundle. No network/native operations."""
import argparse,base64,gzip,hashlib,io,json
from pathlib import Path,PurePosixPath
import tarfile
def identity(b):return {"bytes":len(b),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(),"sha256":hashlib.sha256(b).hexdigest()}
def check(body,expected):
 actual=identity(body)
 assert all(actual[k]==expected[k] for k in actual),(actual,expected)
def restore(bundle,out):
 manifest=json.loads((bundle/"bundle-manifest.json").read_bytes());blocks=[]
 for part in manifest["parts"]:
  body=(bundle/part["path"]).read_bytes();check(body,part["encoded"])
  binary=base64.b64decode(body,validate=True);check(binary,part["decoded"]);blocks.append(binary)
 packed=b"".join(blocks);check(packed,manifest["gzip"]);data=gzip.decompress(packed);check(data,manifest["tar"])
 expected={x["path"]:x for x in manifest["members"]};assert len(expected)==len(manifest["members"])
 assert not out.exists();out.mkdir(parents=True)
 seen=set()
 with tarfile.open(fileobj=io.BytesIO(data),mode="r:") as archive:
  for member in archive:
   name=member.name;p=PurePosixPath(name)
   assert member.isfile() and not p.is_absolute() and all(x not in ("",".","..") for x in p.parts)
   assert name in expected and name not in seen
   body=archive.extractfile(member).read();check(body,expected[name])
   destination=out.joinpath(*p.parts);destination.parent.mkdir(parents=True,exist_ok=True);destination.open("xb").write(body);seen.add(name)
 assert seen==set(expected)
 return {"result":"EXACT_ARCHIVE_MEMBERS_RESTORED","members":len(seen),"member_bytes":sum(x["bytes"] for x in manifest["members"]),"gzip":manifest["gzip"],"no_network_native_or_ref":True}
if __name__=="__main__":
 parser=argparse.ArgumentParser();parser.add_argument("--bundle",type=Path,default=Path(__file__).resolve().parent);parser.add_argument("--output",type=Path,required=True);a=parser.parse_args()
 print(json.dumps(restore(a.bundle,a.output),indent=2,sort_keys=True))

