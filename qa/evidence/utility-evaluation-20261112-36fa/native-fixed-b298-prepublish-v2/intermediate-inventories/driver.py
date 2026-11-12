from pathlib import Path
from datetime import datetime,timezone
import base64,gzip,hashlib,json,os,stat,sys,traceback,zlib
P=INPUT
out=Path(P["out"]);out.mkdir(mode=0o700)
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def put(name,b):
 if isinstance(b,str):b=b.encode()
 fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
 return {"path":str(out/name),"bytes":len(b),"sha256":sha(b),"git_blob_sha":oid(b)}
def save(name,x):return put(name,json.dumps(x,sort_keys=True,indent=2)+"\n")
put("driver.py",P["driver"]);save("INPUT.json",P)
result={"started_at":datetime.now(timezone.utc).isoformat(),"status":"running","purpose":"Read retained original inventory bytes; no source mutation, compiler, or tests","qualification":False,"observations":[]}
try:
 if os.geteuid()==0:raise RuntimeError("ordinary operator required")
 original=Path(P["original_result"]).read_bytes()
 if sha(original)!="16b444ef1b727062153dbb16e57bd489413fecc834e3107fb8f5fce4a67f58e6":raise RuntimeError("original terminal result differs")
 terminal=json.loads(original)
 if terminal["status"]!="prepublication_maintenance_complete" or not terminal["commands_passed"] or terminal["tests_started"]:raise RuntimeError("original maintenance not completed without tests")
 result["original_result"]={"path":P["original_result"],"bytes":len(original),"sha256":sha(original),"git_blob_sha":oid(original)}
 baseline=None
 for item in P["files"]:
  path=Path(item["path"]);s=path.lstat()
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise RuntimeError("inventory is not a private regular file")
  packed=path.read_bytes();t=path.lstat()
  if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns,t.st_ctime_ns):raise RuntimeError("inventory version changed")
  if len(packed)!=item["gzip_bytes"] or sha(packed)!=item["gzip_sha256"]:raise RuntimeError("original gzip differs")
  raw=gzip.decompress(packed)
  if sha(raw)!=item["raw_sha256"]:raise RuntimeError("original raw inventory differs")
  rows=json.loads(raw)
  if len(rows)!=14851 or rows!=sorted(rows,key=lambda r:os.fsencode(r["path"])) or any(set(r)!={"path","mode","bytes","sha256","blob"} for r in rows):raise RuntimeError("inventory shape differs")
  if json.dumps(rows,sort_keys=True,separators=(",",":")).encode()!=raw:raise RuntimeError("original compact serialization differs")
  mapping={r["path"]:r for r in rows}
  if len(mapping)!=len(rows):raise RuntimeError("duplicate inventory path")
  observation={"label":item["label"],"path":str(path),"file_version":{"device":s.st_dev,"inode":s.st_ino,"size":s.st_size,"mtime_ns":s.st_mtime_ns,"ctime_ns":s.st_ctime_ns},"gzip_bytes":len(packed),"gzip_sha256":sha(packed),"gzip_git_blob_sha":oid(packed),"raw_bytes":len(raw),"raw_sha256":sha(raw),"raw_git_blob_sha":oid(raw),"files":len(rows),"gzip_header_base64":base64.b64encode(packed[:10]).decode(),"gzip_trailer_base64":base64.b64encode(packed[-8:]).decode(),"deflate_bytes":len(packed)-18,"deflate_sha256":sha(packed[10:-8]),"exact_gzip_compress_mtime0_reproduction":gzip.compress(raw,mtime=0)==packed}
  if baseline is None:
   baseline=mapping;observation["baseline"]=True;observation["delta"]=[]
  else:observation["delta"]=[{"path":p,"before":baseline.get(p),"after":mapping.get(p)} for p in sorted(set(baseline)|set(mapping),key=os.fsencode) if baseline.get(p)!=mapping.get(p)]
  result["observations"].append(observation)
 result["python_version"]=sys.version
 result["zlib_version"]=zlib.ZLIB_VERSION
 result["zlib_runtime_version"]=zlib.ZLIB_RUNTIME_VERSION
 result["source_files_read"]=False
 result["status"]="observed_exact_original_inventory_differences"
except BaseException as e:
 result["status"]="failed";result["error"]=type(e).__name__+": "+str(e);put("exception.txt",traceback.format_exc())
result["finished_at"]=datetime.now(timezone.utc).isoformat()
identity=save("RESULT.json",result)
print(json.dumps({"status":result["status"],"result":identity,"differences":[{"label":x["label"],"paths":[d["path"] for d in x["delta"]]} for x in result["observations"]]},sort_keys=True),flush=True)
raise SystemExit(0 if result["status"]=="observed_exact_original_inventory_differences" else 1)
