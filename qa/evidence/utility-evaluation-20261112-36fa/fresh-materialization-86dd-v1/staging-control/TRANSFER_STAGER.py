import ast,datetime,hashlib,json,os,pathlib,stat,sys,traceback
ROOT=pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-source-materialization-86dd-v1")
ALLOWED={"driver.py","inventory-driver-v2.py","ROOT_INDEPENDENT_REVIEW.json","CANONICAL_TERMINAL_SDK.json","ROOT_CONTROL_REVIEW.json","APPROVED_CONFIG.json","WAITING_CONFIG.json","CONTROL_PLAN.md","CONTROL_PACKAGE_MANIFEST.json","TRANSFER_STAGER.py","prepared-input/PREPARED_MANIFEST.json","prepared-input/prepared-86dd.part-005.json-fragment.txt"}
def need(c,m):
    if not c: raise RuntimeError(m)
def digest(b): return hashlib.sha256(b).hexdigest()
def gitblob(b): return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def safe_parent(p):
    q=pathlib.Path(p.anchor)
    for s in p.parts[1:]:
        q=q/s
        z=q.lstat()
        need(stat.S_ISDIR(z.st_mode) and not stat.S_ISLNK(z.st_mode),"non-real directory "+str(q))
def read(p):
    f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a=os.fstat(f);need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and a.st_uid==os.getuid(),"not owned single regular input")
        need(a.st_size<=1048576,"input size")
        blocks=[]
        while True:
            b=os.read(f,65536)
            if not b:break
            blocks.append(b)
        b=b"".join(blocks);z=os.fstat(f)
        need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns),"input changed")
        need(len(b)==a.st_size,"short read")
        return b
    finally:os.close(f)
def create(p,b):
    try:f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:
        need(read(p)==b,"existing bytes differ "+str(p))
        return "existing_equal"
    with os.fdopen(f,"wb") as s:
        s.write(b);s.flush();os.fchmod(s.fileno(),0o400);os.fsync(s.fileno())
    need(read(p)==b,"full create readback differs")
    return "created"
raw=sys.stdin.buffer.read(1048577);need(len(raw)<=1048576,"stdin too large")
payload=json.loads(raw);need(payload["format"]=="hepta-create-only-input-staging-v1","schema")
items=payload["files"];need(len(items)==len({x["name"] for x in items}),"duplicate path")
for x in items:
    need(x["name"] in ALLOWED,"path outside fixed input allowlist")
    b=x["text"].encode("utf-8")
    need(len(b)==x["bytes"] and digest(b)==x["sha256"] and gitblob(b)==x["git_blob"],"input identity")
    if x["name"].endswith(".py"):ast.parse(b)
safe_parent(ROOT.parent)
if not os.path.lexists(ROOT):os.mkdir(ROOT,0o700)
safe_parent(ROOT)
sub=ROOT/"prepared-input"
if not os.path.lexists(sub):os.mkdir(sub,0o700)
safe_parent(sub)
result={"format":"hepta-fresh-materialization-input-staging-result-v1","at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"target":str(ROOT),"main_driver_executed":False,"git_imported":False,"cargo_started":False,"input_bytes":len(raw),"input_sha256":digest(raw),"files":[]}
try:
    for x in items:
        b=x["text"].encode("utf-8");p=ROOT/x["name"]
        action=create(p,b);s=p.lstat()
        result["files"].append({"name":x["name"],"path":str(p),"bytes":len(b),"sha256":digest(b),"git_blob":gitblob(b),"action":action,"uid":s.st_uid,"nlink":s.st_nlink,"mode":stat.S_IMODE(s.st_mode),"full_readback_equal":True})
    result["status"]="inputs_staged_only"
except BaseException as e:
    result.update(status="failed_staging",error=repr(e),traceback=traceback.format_exc())
finally:
    out=(json.dumps(result,sort_keys=True,separators=(",",":"))+"\n").encode()
    try:create(ROOT/"TRANSFER_SETUP_RESULT.json",out)
    except BaseException as e:result["record_error"]=repr(e)
    print(json.dumps(result,sort_keys=True),flush=True)
sys.exit(0 if result["status"]=="inputs_staged_only" and "record_error" not in result else 1)
