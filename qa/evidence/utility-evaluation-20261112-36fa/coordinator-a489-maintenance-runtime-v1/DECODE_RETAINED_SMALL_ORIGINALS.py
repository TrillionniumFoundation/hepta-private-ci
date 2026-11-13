import base64,gzip,hashlib,json
from pathlib import Path
D=Path(__file__).parent
def pins(b):return dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),git_blob=hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest())
def put(n,b):
 p=D/n
 if p.exists():assert p.read_bytes()==b,n
 else:
  with p.open("xb") as f:f.write(b)
def canon(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
A={x["name"]:x for x in json.loads((D/"ARTIFACTS.json").read_bytes())["files"]}
names=["SOURCE_GIT_STATE.before.json","fix.after.git-state.json","fmt.after.git-state.json","final.git-state.json","SOURCE_GIT_METADATA.before.json.gz","SOURCE_GIT_METADATA.after.json.gz","READONLY_COMMANDS.json","INPUT_IDENTITIES.json","EVENTS.jsonl","SOURCE_ENTRY_SNAPSHOTS.json","ENVIRONMENT_PREFLIGHT.json","fix.attempt.json","fmt.attempt.json","fix.launch-source-entries.json","fmt.launch-source-entries.json","fix.process-preflight.json","fmt.process-preflight.json","fmt.raw.log"]
rows=[]
for n in names:
 sn=n+".READ_01.original.json";sb=(D/sn).read_bytes();sdk=json.loads(sb);assert not sdk.get("isError")
 r=sdk.get("structuredContent")
 if r is None:
  texts=[x["text"] for x in sdk["content"] if x.get("type")=="text"];assert len(texts)==1;r=json.loads(texts[0])
 b=base64.b64decode(r["data_base64"],validate=True);assert r["offset"]==0 and r["eof"] and r["next_offset"]==r["size"]==len(b)
 assert r["path"]=="/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/"+n
 assert hashlib.sha256(b).hexdigest()==r["chunk_sha256"]
 a=A[n];assert pins(b)=={k:a[k] for k in pins(b)};put(n,b)
 row=dict(name=n,**pins(b),version=r["version"],sdk=dict(name=sn,**pins(sb)))
 if n.endswith(".gz"):
  raw=gzip.decompress(b);assert pins(raw)==dict(bytes=a["raw_bytes"],sha256=a["raw_sha256"],git_blob=a["raw_git_blob"]);put(n[:-3],raw);row["raw"]={"name":n[:-3],**pins(raw)}
  for part in a["parts"]:
   partb=base64.b64encode(b[part["decoded_offset"]:part["decoded_offset"]+part["decoded_bytes"]])+b"\n";assert pins(partb)=={k:part[k] for k in pins(partb)};put(part["name"],partb)
 rows.append(row)
assert (D/"SOURCE_GIT_STATE.before.json").read_bytes()==(D/"fix.after.git-state.json").read_bytes()==(D/"fmt.after.git-state.json").read_bytes()==(D/"final.git-state.json").read_bytes()
assert (D/"SOURCE_GIT_METADATA.before.json").read_bytes()==(D/"SOURCE_GIT_METADATA.after.json").read_bytes()
review={"schema":"hepta-retained-small-native-originals-readback-v1","job_id":"1a1d47cebc8-392-41e","all_artifact_identities_match":True,"four_separate_original_git_state_paths_full_bytes_equal":True,"both_original_git_metadata_paths_full_bytes_equal":True,"metadata_integer_handling":"Only original bytes and Python integers; no JavaScript JSON roundtrip","files":rows}
put("SMALL_ORIGINALS_READBACK_REVIEW.json",canon(review));print(json.dumps({"review":pins(canon(review)),"files":[{k:r[k] for k in ["name","bytes","sha256","git_blob"]} for r in rows]},indent=2))
