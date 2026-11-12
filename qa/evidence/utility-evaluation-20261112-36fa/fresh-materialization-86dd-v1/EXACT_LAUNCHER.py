import ast,hashlib,json,os,pathlib,stat,sys
ROOT=pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-source-materialization-86dd-v1")
def read_exact(name,size,want):
    p=ROOT/name
    q=pathlib.Path(p.anchor)
    for s in p.parts[1:-1]:
        q=q/s;z=q.lstat()
        if not stat.S_ISDIR(z.st_mode) or stat.S_ISLNK(z.st_mode):raise RuntimeError("non-real input parent")
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a=os.fstat(fd)
        if not stat.S_ISREG(a.st_mode) or a.st_nlink!=1 or a.st_uid!=os.getuid() or a.st_size!=size:raise RuntimeError("input file identity")
        raw=b""
        while len(raw)<=size:
            b=os.read(fd,min(65536,size+1-len(raw)))
            if not b:break
            raw+=b
        z=os.fstat(fd)
        if (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)!=(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns):raise RuntimeError("input changed")
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=want:raise RuntimeError("input exact bytes mismatch")
        return raw
    finally:os.close(fd)
driver=read_exact("driver.py",64399,"7787562e1bdd744b54eb73c59233810013135a55e966eeaa05317fb807ef6c16")
config=read_exact("APPROVED_CONFIG.json",1056,"a7f931e7a63e3e157dee6d914f53763188e04dd779d4a30256530a00497084af")
cfg=json.loads(config)
if cfg["execution_key"]!="hepta-utility-36fa-fresh-materialization-86dd-v1" or cfg["outer_timeout_seconds"]!=900:raise RuntimeError("approved unique execution identity")
code=compile(ast.parse(driver,filename=str(ROOT/"driver.py")),str(ROOT/"driver.py"),"exec")
print(json.dumps({"event":"exact_materialization_launcher_admitted","driver_path":str(ROOT/"driver.py"),"driver_bytes":len(driver),"driver_sha256":hashlib.sha256(driver).hexdigest(),"config_path":str(ROOT/"APPROVED_CONFIG.json"),"config_bytes":len(config),"config_sha256":hashlib.sha256(config).hexdigest(),"execution_key":cfg["execution_key"],"qualification":False,"cargo_started":False},sort_keys=True),flush=True)
sys.argv=[str(ROOT/"driver.py")]
exec(code,{"__name__":"__main__","__file__":str(ROOT/"driver.py")})
