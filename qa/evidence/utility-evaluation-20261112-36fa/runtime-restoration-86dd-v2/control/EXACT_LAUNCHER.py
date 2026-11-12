import ast,hashlib,json,os,stat,sys
from pathlib import Path
ROOT=Path("/home/qian-qi/hepta-utility-36fa-evidence/runtime-materials-restore-86dd-v1")
PINS={"driver-v4.py":(49448,"1d2448596a1226c59724d5666f90f074e5fd39fac548ff62ba94efb6b5d6344e","b1d214e4fe3c036884f5c0bf99e1dc9d618a5d56"),"APPROVED_CONFIG_V2.json":(3304,"0885798995e84d79cc1b67e0298ac3577398557f2d96d1331dbe564fc95cbeb8","f2e4263898ecc064d2cf8e6f35c14e3ffad6f42b")}
def need(v,m):
 if not v:raise ValueError(m)
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def read(p,limit=200000):
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd);need(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid==os.getuid() and s.st_size<=limit,"regular owned bounded input")
  chunks=[];n=0
  while True:
   c=os.read(fd,65536)
   if not c:break
   n+=len(c);need(n<=limit,"file bound");chunks.append(c)
  z=os.fstat(fd);need((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns),"stable read")
  b=b"".join(chunks);need(len(b)==s.st_size,"full read");return b
 finally:os.close(fd)
def save(name,b):
 p=ROOT/name
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
 need(read(p)==b,"create-only launcher evidence readback")
need(os.getuid()==1000,"configured operator uid")
p=Path(ROOT.anchor)
for part in ROOT.parts[1:]:
 p=p/part;s=p.lstat();need(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode),"real input parent")
need(ROOT.stat().st_uid==1000 and not os.path.lexists(ROOT/"run-v2"),"owned fresh operation control")
raw={}
for name,(size,digest,object_id) in PINS.items():
 b=read(ROOT/name);need(len(b)==size and sha(b)==digest and oid(b)==object_id,"exact approved "+name);raw[name]=b
config=json.loads(raw["APPROVED_CONFIG_V2.json"]);need(config["status"]=="ROOT_APPROVED_TO_EXECUTE" and config["root_execution_approved"] is True,"actual explicit approval")
ast.parse(raw["driver-v4.py"]);compile(raw["driver-v4.py"],str(ROOT/"driver-v4.py"),"exec")
original=list(sys.orig_argv);need("-c" in original,"actual fixed -c launch")
actual_code=original[original.index("-c")+1].encode("utf-8")
save("ACTUAL_LAUNCHER_V2.py",actual_code)
save("ACTUAL_LAUNCHER_ARGV_V2.json",(json.dumps({"argv":original,"cwd":os.getcwd(),"pins":PINS,"driver_main_started":False,"qualification":False},sort_keys=True,indent=2)+"\n").encode())
print(json.dumps({"event":"fixed_runtime_restoration_launcher_verified","driver_sha256":PINS["driver-v4.py"][1],"config_sha256":PINS["APPROVED_CONFIG_V2.json"][1],"qualification":False},sort_keys=True),flush=True)
os.execv("/usr/bin/python3",["/usr/bin/python3","-B",str(ROOT/"driver-v4.py")])
