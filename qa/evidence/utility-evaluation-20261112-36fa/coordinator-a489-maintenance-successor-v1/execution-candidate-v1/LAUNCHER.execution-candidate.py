import ast,datetime,fcntl,hashlib,json,os,stat,sys
from pathlib import Path
ROOT=Path("/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1")
PINS={'driver-maintenance.py': (68520, '2e8501f584a6905a07124f04bb623c2674c1ec77299b89fbc76ef06610c589ed', '59461030d4160f7ad6a978df5a7b6aaeb33fb2a6'), 'APPROVED_MAINTENANCE_CONFIG.json': (13693, '3ab98f7c35ce030439773f2035b7d6e4b8f9c4b11b3f6e8f93b431ea369286d7', '7bddb6c423afbe739bc36a7df2516730911a9337')}
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
need(ROOT.stat().st_uid==1000 and not os.path.lexists(ROOT/"run"),"owned fresh operation control")
raw={}
for name,(size,digest,object_id) in PINS.items():
 b=read(ROOT/name);need(len(b)==size and sha(b)==digest and oid(b)==object_id,"exact approved "+name);raw[name]=b
config=json.loads(raw["APPROVED_MAINTENANCE_CONFIG.json"]);need(config["status"]=="ROOT_APPROVED_TO_EXECUTE" and config["root_execution_approved"] is True,"actual explicit approval")
ast.parse(raw["driver-maintenance.py"]);compile(raw["driver-maintenance.py"],str(ROOT/"driver-maintenance.py"),"exec")
# This fresh lease covers only this launch; the already observed cooperative lock is reused.
LOCK=Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock")
p=Path(LOCK.anchor)
for part in LOCK.parts[1:-1]:
 p=p/part;s=p.lstat();need(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode),"real existing lock parent")
created=False
lock_fd=os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)
lock_info=os.fstat(lock_fd)
need(config["coordination_lock"]["path"]==str(LOCK) and config["coordination_lock"]["mode"]=="LOCK_EX","same actual cooperative lock")
need({k:getattr(lock_info,k) for k in ("st_dev","st_ino","st_mode","st_uid","st_gid","st_nlink","st_size","st_mtime_ns","st_ctime_ns")}==config["coordination_lock"]["stat"],"exact actual lock inode/stat; no replacement lock")
need(stat.S_ISREG(lock_info.st_mode) and lock_info.st_uid==1000 and lock_info.st_nlink==1 and stat.S_IMODE(lock_info.st_mode)==0o600,"owned exact coordination lock")
fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
os.set_inheritable(lock_fd,True)
lease={"format":"hepta-source-coordination-exclusive-lease-v1","at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"path":str(LOCK),"source_repo":"/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1","scope":"Cooperative source writers hold EX; actual source collectors hold SH on this same inode. Full before/after inventories remain mandatory. No historical coverage is claimed.","pid":os.getpid(),"fd":lock_fd,"created":created,"device":lock_info.st_dev,"inode":lock_info.st_ino,"uid":lock_info.st_uid,"gid":lock_info.st_gid,"mode":stat.S_IMODE(lock_info.st_mode),"nlink":lock_info.st_nlink,"lock_acquired":"LOCK_EX|LOCK_NB","inheritable":os.get_inheritable(lock_fd),"held_until":"The original maintenance main process exits; the descriptor is deliberately retained across exec.","qualification":False}
save("SOURCE_COORDINATION_EX.json",(json.dumps(lease,sort_keys=True,indent=2)+"\n").encode())
original=list(sys.orig_argv);need("-c" in original,"actual fixed -c launch")
actual_code=original[original.index("-c")+1].encode("utf-8")
save("ACTUAL_LAUNCHER.py",actual_code)
save("ACTUAL_LAUNCHER_ARGV.json",(json.dumps({"argv":original,"cwd":os.getcwd(),"pins":PINS,"driver_main_started":False,"qualification":False},sort_keys=True,indent=2)+"\n").encode())
print(json.dumps({"event":"fixed_original_maintenance_coordinator_a489_launcher_verified","driver_sha256":PINS["driver-maintenance.py"][1],"config_sha256":PINS["APPROVED_MAINTENANCE_CONFIG.json"][1],"qualification":False},sort_keys=True),flush=True)
os.execv("/usr/bin/python3",["/usr/bin/python3","-B",str(ROOT/"driver-maintenance.py")])
