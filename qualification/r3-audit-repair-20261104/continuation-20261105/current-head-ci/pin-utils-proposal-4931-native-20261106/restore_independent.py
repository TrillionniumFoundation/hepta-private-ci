#!/usr/bin/env python3
import argparse,base64,gzip,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path,PurePosixPath
def ident(b):
 return {"bytes":len(b),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(),"sha256":hashlib.sha256(b).hexdigest()}
p=argparse.ArgumentParser();p.add_argument("--packet",type=Path,default=Path(__file__).resolve().parent);p.add_argument("--native",type=Path,required=True);p.add_argument("--destination",type=Path,required=True);a=p.parse_args()
d=a.destination.resolve();d.mkdir(parents=True,exist_ok=False);m=json.loads((a.packet/"independent.archive-manifest.json").read_bytes());chunks=[]
for x in m["parts"]:
 b=(a.packet/x["path"]).read_bytes();assert ident(b)==x["file_identity"];raw=base64.b64decode(b.strip(),validate=True);assert ident(raw)==x["decoded_identity"];chunks.append(raw)
gz=b"".join(chunks);assert ident(gz)==m["archive_identity"];raw=gzip.decompress(gz);assert ident(raw)==m["tar_identity"];expected={r["path"]:r for r in m["members"]}
with tarfile.open(fileobj=io.BytesIO(raw),mode="r:") as t:
 members=t.getmembers();assert len(members)==len(expected) and {r.name for r in members}==set(expected)
 for item in members:
  path=PurePosixPath(item.name);assert item.isfile() and not path.is_absolute() and ".." not in path.parts and str(path)==item.name
  b=t.extractfile(item).read();assert ident(b)==expected[item.name]["identity"] and item.mode==expected[item.name]["mode"]
  f=d/item.name;f.parent.mkdir(exist_ok=True,parents=True);f.write_bytes(b);f.chmod(item.mode)
review=d/"independent-review";run=subprocess.run([sys.executable,str(review/"replay_independent.py"),"--native",str(a.native.resolve()),"--frozen",str(review),"--output",str(d/"replayed")],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
(d/"stdout.original.json").write_bytes(run.stdout);(d/"stderr.original.txt").write_bytes(run.stderr)
assert run.returncode==0 and run.stderr==b"" and run.stdout==(review/"portable-replay-01.stdout.original.json").read_bytes()
proof={"schema":"independent-review-increment-packet-replay-v1","members":len(expected),"member_bytes":sum(x["identity"]["bytes"] for x in expected.values()),"review_actual_blob":m["formal_actual_review_blob"],"portable_replay_exit":0,"stderr_bytes":0,"all_reviewer_portable_stdout_bytes_equal":True,"stdout_identity":ident(run.stdout),"native_product_execution":False}
(d/"RESTORE_VERIFICATION.json").write_text(json.dumps(proof,indent=2)+"\n");print(json.dumps(proof,indent=2))
