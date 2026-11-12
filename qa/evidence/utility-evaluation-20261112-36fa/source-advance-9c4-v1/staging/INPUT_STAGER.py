import ast,datetime,hashlib,json,os,stat,sys
from pathlib import Path
ROOT=Path("/home/qian-qi/hepta-utility-36fa-evidence/source-advance-9c4-v1")
EXPECTED="5cf2afd0e222fd736e08ac56738efc65bf0e4ce2b7a1b3650599d9619047a94d"
def need(v,m):
 if not v: raise ValueError(m)
def h(b):return hashlib.sha256(b).hexdigest()
def oid(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def real(p,own=False):
 c=Path(p.anchor)
 for x in p.parts[1:]:
  c=c/x;s=c.lstat();need(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode),"real directory "+str(c))
 need(not own or p.stat().st_uid==os.getuid(),"owned directory")
def read(p):
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  a=os.fstat(fd);need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and a.st_uid==os.getuid() and a.st_size<=200000,"regular owned bounded input")
  b=b""
  while True:
   z=os.read(fd,65536)
   if not z:break
   b+=z;need(len(b)<=200000,"read bound")
  z=os.fstat(fd);need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns),"stable input")
  return b,z
 finally:os.close(fd)
def put(p,b):
 if not os.path.lexists(p):
  fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
  with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
 got,st=read(p);need(got==b,"exact full create-only readback")
 return st
need(os.getuid()==1000,"configured operator uid")
raw=sys.stdin.buffer.read(1048577);need(len(raw)<=1048576 and h(raw)==EXPECTED,"actual staging payload bytes")
v=json.loads(raw);need(v["format"]=="hepta-source-advance-hold-control-staging-v1","format")
need({x["filename"] for x in v["files"]}=={"driver.py","CANONICAL_PACKET.json","SOURCE_ADVANCE_CONTRACT.json"} and len(v["files"])==3,"exact three inputs")
for x in v["files"]:
 b=x["content"].encode("utf-8");need(len(b)==x["bytes"] and h(b)==x["sha256"] and oid(b)==x["git_blob"],"input identity "+x["filename"])
 if x["filename"]=="driver.py":ast.parse(b);compile(b,str(ROOT/"driver.py"),"exec")
real(ROOT.parent,True)
if not os.path.lexists(ROOT):os.mkdir(ROOT,0o700)
real(ROOT,True)
need(not os.path.lexists(ROOT/"run") and not os.path.lexists(ROOT/"APPROVED_CONFIG.json"),"no existing run or approved config; do not replay")
rows=[]
for x in v["files"]:
 p=ROOT/x["filename"];b=x["content"].encode("utf-8");st=put(p,b)
 rows.append({"path":str(p),"bytes":len(b),"sha256":h(b),"git_blob":oid(b),"uid":st.st_uid,"mode":stat.S_IMODE(st.st_mode),"nlink":st.st_nlink,"version":f"{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}","full_readback_equal":True})
r={"format":"hepta-source-advance-hold-control-staging-result-v1","status":"CONTROL_INPUTS_STAGED_ONLY","at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"payload_bytes":len(raw),"payload_sha256":h(raw),"files":rows,"approved_config_written":False,"driver_main_executed":False,"downloads":0,"installations":0,"cargo_or_tests":0}
b=(json.dumps(r,sort_keys=True,indent=2)+"\n").encode();put(ROOT/"INPUT_STAGING_V1.json",b)
fd=os.open(ROOT,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print(json.dumps(r,sort_keys=True),flush=True)
