import base64,gzip,hashlib,io,json,os,stat,sys,time,traceback,urllib.parse,urllib.request,zipfile
from pathlib import Path,PurePosixPath
raw_request=sys.stdin.buffer.read(1048577)
cfg=json.loads(raw_request)
if os.getuid()!=1000 or os.geteuid()!=1000:raise RuntimeError("ordinary uid1000 required")
os.umask(0o077)
root=Path(cfg["root"]);root.mkdir(parents=True,exist_ok=False)
result={"schema":"hepta.original-github-artifact-ingest.v1","status":"FAILED","uid":os.getuid(),"euid":os.geteuid(),"source_sha":cfg["source_sha"],"request_sha256":hashlib.sha256(raw_request).hexdigest(),"native_build_started":False,"tests_started":False,"source_modified":False,"artifacts":[],"started_ns":str(time.time_ns())}
def sha(data):return hashlib.sha256(data).hexdigest()
def write_once(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if not path.parent.resolve().is_relative_to(root.resolve()):raise RuntimeError("evidence path escaped")
 with path.open("xb") as out:out.write(data);out.flush();os.fsync(out.fileno())
 after=path.stat()
 return {"path":str(path.relative_to(root)),"bytes":len(data),"sha256":sha(data),"stat":{"device":str(after.st_dev),"inode":str(after.st_ino),"mtime_ns":str(after.st_mtime_ns),"ctime_ns":str(after.st_ctime_ns)}}
def save(name,value):return write_once(root/name,(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n").encode())
def transfer(path,data,label):
 compressed=not path.endswith(".gz") and len(data)>32768
 payload=gzip.compress(data,compresslevel=6,mtime=0) if compressed else data
 parts=[]
 for offset in range(0,len(payload),24576):
  part=payload[offset:offset+24576];name="transfer/"+label+"-"+str(offset).zfill(9)+".b64";text=base64.b64encode(part)
  written=write_once(root/name,text)
  parts.append({"path":name,"offset":offset,"bytes":len(part),"sha256":sha(part),"base64_bytes":len(text),"base64_sha256":written["sha256"]})
 return {"codec":"gzip" if compressed else "identity","gzip_is_transfer_only":compressed,"bytes":len(payload),"sha256":sha(payload),"parts":parts}
try:
 save("PLAN.redacted.json",{**cfg,"artifacts":[{k:v for k,v in a.items() if k!="download_url"} for a in cfg["artifacts"]],"url_query_not_archived":True})
 for art in cfg["artifacts"]:
  url=urllib.parse.urlsplit(art["download_url"])
  if url.scheme!="https" or url.hostname!=art["download_host"]:raise RuntimeError("download URL identity")
  with urllib.request.urlopen(art["download_url"],timeout=45) as response:
   final=urllib.parse.urlsplit(response.geturl())
   if response.status!=200 or final.scheme!="https" or final.hostname!=art["download_host"]:raise RuntimeError("artifact download response identity")
   data=response.read(art["bytes"]+1)
  if len(data)!=art["bytes"] or sha(data)!=art["sha256"]:raise RuntimeError("original artifact ZIP size/SHA mismatch")
  zip_pin=write_once(root/("artifact-"+str(art["id"])+".zip"),data)
  receipt={"artifact_id":art["id"],"name":art["name"],"source_sha":cfg["source_sha"],"zip":zip_pin,"members":[]}
  with zipfile.ZipFile(io.BytesIO(data)) as archive:
   infos=archive.infolist()
   if len(infos)>4096 or sum(x.file_size for x in infos)>268435456:raise RuntimeError("artifact member bounds")
   seen=set()
   for number,info in enumerate(infos):
    name=PurePosixPath(info.filename)
    if name.is_absolute() or ".." in name.parts or "\\" in info.filename or info.filename in seen:raise RuntimeError("unsafe or duplicate artifact path")
    seen.add(info.filename)
    if info.flag_bits&1 or info.file_size>67108864:raise RuntimeError("encrypted or excessive artifact member")
    mode=(info.external_attr>>16)&0o170000
    if mode not in (0,stat.S_IFREG,stat.S_IFDIR):raise RuntimeError("artifact member is not a regular file/directory")
    if info.is_dir():continue
    if not name.parts or name.as_posix()==".":raise RuntimeError("invalid artifact member")
    original=archive.read(info)
    if len(original)!=info.file_size:raise RuntimeError("original member size differs")
    pin=write_once(root/("artifact-"+str(art["id"]))/ "originals"/name.as_posix(),original)
    receipt["members"].append({**pin,"member":info.filename,"zip_crc32":info.CRC,"zip_compressed_bytes":info.compress_size,"zip_datetime":list(info.date_time),"transport":transfer(info.filename,original,str(art["id"])+"-"+str(number).zfill(4))})
  result["artifacts"].append(receipt)
 result["status"]="ORIGINAL_ARTIFACT_BYTES_VERIFIED"
except BaseException as error:
 result["error"]={"type":type(error).__name__,"message":str(error)[:1000] if isinstance(error,RuntimeError) else "exception details omitted to keep download credentials private","http_status":getattr(error,"code",None)}
finally:
 result["finished_ns"]=str(time.time_ns())
 manifest=save("RESULT.json",result)
 print(json.dumps({"status":result["status"],"manifest":manifest,"artifact_count":len(result["artifacts"]),"error":result.get("error")},sort_keys=True),flush=True)
if result["status"]!="ORIGINAL_ARTIFACT_BYTES_VERIFIED":raise SystemExit(1)
