import datetime,hashlib,json,os,pathlib,stat,subprocess,traceback
SOURCE=pathlib.Path("/home/qian-qi/hepta-utility-36fa-source-gates-c0f78493-v1")
FIRST=SOURCE/".git"/"objects"
KNOWN=pathlib.Path("/home/qian-qi/hepta-utility-36fa-review-19aa/.git/objects")
ENV=os.environ.copy()
for k in ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE","GIT_OBJECT_DIRECTORY","GIT_ALTERNATE_OBJECT_DIRECTORIES","GIT_SHALLOW_FILE","GIT_REPLACE_REF_BASE","GIT_CONFIG_COUNT","GIT_CONFIG_PARAMETERS"):
    if ENV.get(k):raise RuntimeError("unexpected inherited Git override "+k)
ENV.update(GIT_OPTIONAL_LOCKS="0",GIT_NO_REPLACE_OBJECTS="1",GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL="/dev/null",GIT_CONFIG_SYSTEM="/dev/null")
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def gitblob(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def read(path,maximum=1048576):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a=os.fstat(fd)
        if not stat.S_ISREG(a.st_mode) or a.st_nlink!=1 or a.st_size>maximum:raise RuntimeError("invalid file "+str(path)+" size="+str(a.st_size)+" nlink="+str(a.st_nlink)+" mode="+str(a.st_mode))
        raw=b""
        while True:
            b=os.read(fd,65536)
            if not b:break
            raw+=b
        z=os.fstat(fd)
        fields=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if fields(a)!=fields(z) or len(raw)!=a.st_size:raise RuntimeError("file changed")
        return raw,{"path":str(path),"bytes":len(raw),"sha256":sha(raw),"git_blob":gitblob(raw),"version":":".join(str(x) for x in fields(a)),"uid":a.st_uid,"nlink":a.st_nlink,"mode":stat.S_IMODE(a.st_mode)}
    finally:os.close(fd)
commands=[]
def git(args):
    argv=["/usr/bin/git","--no-optional-locks","-C",str(SOURCE),*args]
    r=subprocess.run(argv,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=False)
    rec={"argv":argv,"returncode":r.returncode,"stdout":r.stdout.decode("utf-8"),"stdout_bytes":len(r.stdout),"stdout_sha256":sha(r.stdout),"stderr":r.stderr.decode("utf-8"),"stderr_bytes":len(r.stderr)}
    commands.append(rec)
    if r.returncode:raise RuntimeError("git read failed")
    return r.stdout
def state():
    b,_=read(SOURCE/".git"/"index",maximum=40000000)
    return {"head":git(["rev-parse","HEAD"]).decode().strip(),"tree":git(["rev-parse","HEAD^{tree}"]).decode().strip(),"index_bytes":len(b),"index_sha256":sha(b),"refs_sha256":sha(git(["for-each-ref","--format=%(refname) %(objectname)"]))}
def graph():
    rows=[];seen=set();queue=[FIRST]
    while queue:
        root=queue.pop(0)
        if str(root) in seen:continue
        if len(seen)>=16:raise RuntimeError("alternate graph bound")
        if not str(root).startswith("/home/qian-qi/") or pathlib.Path(os.path.realpath(root))!=root:raise RuntimeError("unapproved or symlink object root")
        d=root.lstat()
        if not stat.S_ISDIR(d.st_mode):raise RuntimeError("object root not directory")
        seen.add(str(root));path=root/"info"/"alternates"
        item={"object_directory":str(root),"realpath":os.path.realpath(root),"directory_uid":d.st_uid,"directory_mode":stat.S_IMODE(d.st_mode),"directory_device":d.st_dev,"directory_inode":d.st_ino}
        try:raw,meta=read(path)
        except FileNotFoundError:
            item.update(alternates_present=False,alternates_path=str(path),resolved_children=[])
        else:
            text=raw.decode("utf-8")
            if b"\0" in raw or b"\r" in raw:raise RuntimeError("alternate syntax not simple path lines")
            children=[]
            for line in text.splitlines():
                if not line or line.startswith('"'):raise RuntimeError("non-simple alternate line")
                child=pathlib.Path(line)
                if not child.is_absolute():child=pathlib.Path(os.path.abspath(root/child))
                children.append(str(child));queue.append(child)
            item.update(alternates_present=True,alternates={**meta,"text":text},resolved_children=children)
        rows.append(item)
    return rows
res={"format":"hepta-existing-source-alternates-readonly-observation-v1","started_at":now(),"source":str(SOURCE),"git_writes":False,"physical_source_inventory":False,"cargo_started":False,"commands":commands}
try:
    res["git_before"]=state()
    res["graph_before"]=graph()
    first=res["graph_before"][0]
    if first.get("alternates",{}).get("sha256")!="6a68044ee04f004ea14022b8da7abcc402347ecc83ca53736c877d5018cc3b2f" or first["resolved_children"]!=[str(KNOWN)]:raise RuntimeError("original source alternates changed")
    res["git_count_objects_raw"]=git(["count-objects","-v"]).decode()
    res["graph_after"]=graph()
    res["git_after"]=state()
    res["graph_equal"]=res["graph_before"]==res["graph_after"]
    res["git_state_equal"]=res["git_before"]==res["git_after"]
    if not res["graph_equal"] or not res["git_state_equal"]:raise RuntimeError("observation changed")
    res["status"]="existing_readonly_alternates_observed"
except BaseException as e:res.update(status="failed_or_unknown",error=repr(e),traceback=traceback.format_exc())
res["finished_at"]=now()
print(json.dumps(res,sort_keys=True,separators=(",",":")),flush=True)
raise SystemExit(0 if res["status"]=="existing_readonly_alternates_observed" else 1)
