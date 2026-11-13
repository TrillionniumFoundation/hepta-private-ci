import base64,gzip,hashlib,json
from pathlib import Path
D=Path(__file__).parent
def pins(b):
 return dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),git_blob=hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest())
def put(n,b):
 p=D/n
 if p.exists(): assert p.read_bytes()==b,(n,"existing mismatch")
 else:
  with p.open("xb") as f:f.write(b)
def canon(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
def payload(raw):
 s=json.loads(raw);assert not s.get("isError"),s
 if s.get("structuredContent") is not None:return s["structuredContent"]
 a=[x["text"] for x in s["content"] if x.get("type")=="text"];assert len(a)==1
 return json.loads(a[0])
A=json.loads((D/"ARTIFACTS.json").read_bytes());files={x["name"]:x for x in A["files"]};assert len(files)==len(A["files"])
review={"schema":"hepta-original-postimage-readback-v1","job_id":"1a1d47cebc8-392-41e","qualification":False,"source_write":False,"packets":[]}
for n in ["fix.after.postimages.json.gz","fmt.after.postimages.json.gz","final.postimages.json.gz"]:
 row=files[n];chunks=[];off=0;version=None;sdks=[]
 for i in [1,2]:
  sn=n+".READ_"+str(i).zfill(2)+".original.json";sb=(D/sn).read_bytes();r=payload(sb);b=base64.b64decode(r["data_base64"],validate=True)
  assert r["offset"]==off and r["next_offset"]==off+len(b) and r["size"]==row["bytes"]
  assert r["path"]=="/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/"+n
  assert hashlib.sha256(b).hexdigest()==r["chunk_sha256"]
  if version is None:version=r["version"]
  else:assert version==r["version"]
  off+=len(b);chunks.append(b);sdks.append(dict(name=sn,**pins(sb),offset=r["offset"],next_offset=off,eof=r["eof"],version=version))
 assert r["eof"] and off==row["bytes"]
 z=b"".join(chunks);assert pins(z)=={k:row[k] for k in pins(z)};put(n,z)
 raw=gzip.decompress(z);assert pins(raw)==dict(bytes=row["raw_bytes"],sha256=row["raw_sha256"],git_blob=row["raw_git_blob"]);put(n[:-3],raw)
 partrows=[]
 for part in row["parts"]:
  start=part["decoded_offset"]; b=z[start:start+part["decoded_bytes"]]; pb=base64.b64encode(b)+b"\n"
  assert len(b)==part["decoded_bytes"] and hashlib.sha256(b).hexdigest()==part["decoded_sha256"]
  assert pins(pb)=={k:part[k] for k in pins(pb)};put(part["name"],pb);partrows.append(dict(name=part["name"],**pins(pb)))
 packet=json.loads(raw)
 review["packets"].append(dict(name=n,version=version,compressed=pins(z),raw_name=n[:-3],raw=pins(raw),original_record_parts=partrows,actual_binary_read_sdks=sdks,packet_top_level_keys=sorted(packet)))
# One contiguous original stdout interval is accepted only if all actual raw-log pins match.
stdout=(D/"STDOUT.complete.original.txt").read_bytes();r=files["fix.raw.log"];N=r["bytes"];hits=[i for i in range(len(stdout)-N+1) if hashlib.sha256(stdout[i:i+N]).hexdigest()==r["sha256"]];assert len(hits)==1,hits
b=stdout[hits[0]:hits[0]+N];assert pins(b)=={k:r[k] for k in pins(b)};put("fix.raw.log.exact_extracted.txt",b)
review["fix_log"]={"source":"complete actual supervisor stdout","claim":"exact original raw log bytes recovered from one contiguous stdout interval; not a second H raw-file read","stdout":pins(stdout),"offset":hits[0],"end_offset":hits[0]+N,"output":"fix.raw.log.exact_extracted.txt",**pins(b)}
put("POSTIMAGES_AND_RAW_LOG_READBACK_REVIEW.json",canon(review))
print(json.dumps({"review":pins(canon(review)),"packets":[{k:r[k] for k in ["name","version","raw","original_record_parts","packet_top_level_keys"]} for r in review["packets"]],"fix_log":review["fix_log"]},indent=2))
