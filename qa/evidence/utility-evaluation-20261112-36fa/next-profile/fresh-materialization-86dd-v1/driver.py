#!/usr/bin/env python3
"""Create-only, offline materialization of exact PREPARATION/HOLD 86dd.
No source/ref publication, formatting, build, test, tool install, or old-repo writes.
Execution requires a separately approved, exact successful evidence-only review.
"""
from __future__ import annotations
import base64, datetime, gzip, hashlib, importlib.util, io, json, os, pathlib, re
import shutil, signal, stat, struct, subprocess, sys, time, traceback, types, zlib

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
SOURCE = pathlib.Path("/home/qian-qi/hepta-utility-36fa-source-gates-c0f78493-v1")
TARGET = pathlib.Path("/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1")
EVIDENCE = pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-source-materialization-86dd-v1")
OUT = EVIDENCE / "run"
CANONICAL_INPUT = pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/a96-canonical-independent-validation-v1")
CANONICAL_REVIEW = CANONICAL_INPUT / "validation" / "ROOT_REVIEW.json"
PREPARED_INPUT = EVIDENCE / "prepared-input"
CONFIG = EVIDENCE / "APPROVED_CONFIG.json"
INVENTORY_MODULE = EVIDENCE / "inventory-driver-v2.py"
GIT = "/usr/bin/git"
B298 = "b29869e856d08db1bfb066116a9c443376ccc57d"
B298_TREE = "906546af39b07474f0b9d046a6e780b6d3342743"
C0F = "c0f78493f815780f68b9bf5e390a21314d79311f"
C0F_TREE = "313ee34febc8ccc54c611ab56286e289518c63cb"
A96 = "a96d1b821d10ed3d9e99dd06c5141f9f242ae318"
A96_TREE = "f96bebefbc1e7d8187efadb62f88d524cdd18451"
PREPARED = "86dd56a930277e0d1aef3e475e35c2b5d60b43b7"
PREPARED_TREE = "383ab85c39ef9d848252ef5c25922d13d9fae6c6"
MANIFEST_395 = {"bytes":286428,"sha256":"33137b5f1d860e8268e73ec9fc1751c70aed0734f502af41a19c6fcb37c502eb","git_blob":"7781160ffff79c238c5955bd8ca2e320e7ef7c99"}
PACKET_395 = {"bytes":12080171,"sha256":"bcecb58bbaf97b6fbd83bb9f9bee9829c902d8c721b52f19aac2160a0a2b8af0","git_blob":"0d41eafb234db8442e8a4c2514456e33499453d6"}
MANIFEST_87 = {"bytes":90960,"sha256":"e71ce2d72d63524750fefd50af2dfabdd17d2481addd2cf9fc32a96b6ddc3275","git_blob":"d8ea5b18c429024b3ba2bdd3ee171a4fb0a58a98"}
PACKET_87 = {"bytes":3241174,"sha256":"05e3a7b01f5814e0816fe8d521c68f55fddc64536e62fcedca7934e0832cb055","git_blob":"a8a3963eaa48de964515b879e20b54e5febf3d1b"}
INVENTORY_PIN = {"bytes":22946,"sha256":"20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2","git_blob":"51181866cbbb6e0176aab04117efffa8b6792b31"}
CANONICAL_REVIEW_PIN = {"bytes":38525,"sha256":"e3fa2ee9c142b6360fb7994db28746d54b2abf9fc27ea362f08e6a80d37f7bdb","git_blob":"d7c135961dfacc04fe8b69697a66450e65566acb"}
ROOT_INDEPENDENT_PIN = {"bytes":3394,"sha256":"b1e3c533857dfb02536d10d90f999e4fcc109fc217ef868014cec6eef45c5e47","git_blob":"96406b978365a8414f9f76169421faa1f2e318d6"}
TERMINAL_SDK_PIN = {"bytes":912,"sha256":"95ad61f014f0f1aa6736c47811bb97001c5ceeb37f5871e08f507d1d2569ee71","git_blob":"e25a789e1f8ae2a08d7e512b20c81790493b141c"}
SOURCE_INVENTORY_PIN = {"bytes":5474911,"sha256":"cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57","git_blob":"5ed18452e2e967281ac368f934b9e4358627b9d3"}
IMPORT_SECONDS = 600
FINAL_RECORD_SECONDS = 180
HEX = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_CFG = {"source_sha":C0F,"source_tree":C0F_TREE}
TARGET_CFG = {"source_sha":PREPARED,"source_tree":PREPARED_TREE}

class PreconditionError(RuntimeError):
    pass

class SourceChanged(RuntimeError):
    pass

class InputChanged(RuntimeError):
    pass

class DestinationChanged(RuntimeError):
    pass

phase = "not_started"
result = {"format":"hepta-fresh-source-materialization-result-v1","status":"HOLD",
          "source_repo":str(SOURCE),"target_repo":str(TARGET),"source_commit":PREPARED,
          "source_tree":PREPARED_TREE,"parents":[C0F,A96],"qualification":False,
          "maintenance_started":False,"cargo_or_tests_started":False,
          "remote_ref_updates":False,"source_repo_writes_requested":False,
          "new_repo_created":False,"import_started":False,"physical_materialization_started":False,
          "historical_fsck":"Not run; prior whole-history fsck limitations remain. No shallow, grafts, or replace objects are introduced.",
          "budget_scope":"600 seconds for this new preparation operation, plus 180 seconds for final read-only audit and records; not a source/test gate budget."}
artifacts = []
commands = []
events = []
input_pins = {}
source_batch = None
target_batch = None
before_inventory = None
before_git_state = None
before_git_metadata = None
inventory_module = None
out_created = False
target_created = False
operation_completed = False
source_unmodified = None
closed_batches = set()
supplied = {}
existing = {}
retained_existing_raw = {}
import_index = {}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def sha256(b):
    return hashlib.sha256(b).hexdigest()

def oid(typ, b):
    return hashlib.sha1(typ.encode("ascii")+b" "+str(len(b)).encode("ascii")+b"\0"+b).hexdigest()

def check(cond, msg):
    if not cond:
        raise ValueError(msg)

def nodup(pairs):
    d = {}
    for k,v in pairs:
        check(k not in d, "duplicate JSON key: "+k)
        d[k] = v
    return d

def parse(b):
    return json.loads(b.decode("utf-8"), object_pairs_hook=nodup)

def regular_read(p, maximum=40000000):
    p = pathlib.Path(p)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        a = os.fstat(fd)
        check(stat.S_ISREG(a.st_mode) and a.st_nlink == 1, "non-single-link regular file: "+str(p))
        check(a.st_size <= maximum, "file size ceiling: "+str(p))
        chunks = []
        total = 0
        while True:
            c = os.read(fd, min(1048576, maximum+1-total))
            if not c:
                break
            chunks.append(c)
            total += len(c)
            check(total <= maximum, "read size ceiling")
        b = b"".join(chunks)
        z = os.fstat(fd)
        check((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns) ==
              (z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns), "file changed during read")
        check(len(b) == a.st_size, "short regular read")
        return b
    finally:
        os.close(fd)

def jbytes(x):
    return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")

def parse_tree(b):
    entries = []
    off = 0
    used = set()
    while off < len(b):
        sp = b.find(b" ",off)
        nul = b.find(b"\0",sp+1)
        check(sp > off and nul > sp+1 and nul+21 <= len(b),"malformed tree")
        mode = b[off:sp].decode("ascii")
        name = b[sp+1:nul]
        check(name not in used and name not in (b".",b"..") and b"/" not in name,"invalid tree name")
        check(mode in ("40000","100644","100755","120000"),"unsupported tree mode "+mode)
        name.decode("utf-8","strict")
        used.add(name)
        entries.append((mode,name,b[nul+1:nul+21].hex()))
        off = nul+21
    order = [name+(b"/" if mode=="40000" else b"") for mode,name,s in entries]
    check(order == sorted(order),"noncanonical tree ordering")
    return entries

def commit_fields(b):
    header, sep, message = b.partition(b"\n\n")
    check(sep == b"\n\n","missing commit header separator")
    lines = header.split(b"\n")
    trees = [x[5:].decode("ascii") for x in lines if x.startswith(b"tree ")]
    parents = [x[7:].decode("ascii") for x in lines if x.startswith(b"parent ")]
    check(len(trees) == 1 and HEX.fullmatch(trees[0]),"invalid commit tree")
    check(all(HEX.fullmatch(x) for x in parents),"invalid parent")
    return {"tree":trees[0],"parents":parents,"message_bytes":len(message),
            "message_ends_with_lf":message.endswith(b"\n"),
            "author_lines":[x.decode("utf-8") for x in lines if x.startswith(b"author ")],
            "committer_lines":[x.decode("utf-8") for x in lines if x.startswith(b"committer ")]}

def snapshot(tree,resolve):
    leaves = {}
    seen_trees = set()
    active = set()
    def visit(s,prefix):
        check(s not in active,"tree cycle")
        active.add(s)
        seen_trees.add(s)
        raw = resolve(s,"tree")
        for mode,name,child in parse_tree(raw):
            path = prefix+name
            if mode == "40000":
                visit(child,path+b"/")
            else:
                check(path not in leaves,"duplicate leaf")
                resolve(child,"blob")
                leaves[path] = {"path":path.decode("utf-8"),"mode":mode,"type":"blob","sha":child}
        active.remove(s)
    visit(tree,b"")
    return leaves, seen_trees



def pin_bytes(b, pin, label):
    check(set(("bytes", "sha256", "git_blob")) <= set(pin), label+" incomplete pin")
    check(len(b) == pin["bytes"] and sha256(b) == pin["sha256"] and oid("blob", b) == pin["git_blob"], label+" exact identity")
    return b

def read_input(path, pin=None, maximum=40000000):
    path = pathlib.Path(path)
    b = regular_read(path, maximum)
    if pin is not None:
        pin_bytes(b, pin, str(path))
    input_pins[str(path)] = {"bytes":len(b),"sha256":sha256(b),"git_blob":oid("blob",b)}
    return b

def check_real_parents(path):
    path = pathlib.Path(path)
    check(path.is_absolute(), "absolute path required")
    current = pathlib.Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        s = current.lstat()
        check(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode), "non-real parent directory: "+str(current))

def write(name, b):
    path = OUT / name
    check(path.parent == OUT and path.name == name, "one-level record name")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(b); f.flush(); os.fsync(f.fileno())
    check(regular_read(path, max(40000000,len(b))) == b, "record readback mismatch: "+name)
    meta = {"name":name,"bytes":len(b),"sha256":sha256(b),"git_blob":oid("blob",b)}
    artifacts.append(meta)
    return meta

def jwrite(name, value):
    return write(name, jbytes(value))

def gzrecord(name, raw):
    gz = gzip.compress(raw, mtime=0)
    check(gzip.decompress(gz) == raw, "record gzip roundtrip")
    meta = write(name, gz)
    meta.update(raw_bytes=len(raw), raw_sha256=sha256(raw), raw_git_blob=oid("blob",raw))
    meta["parts"] = []
    for i, off in enumerate(range(0,len(gz),262144),1):
        part = gz[off:off+262144]
        item = write(name+".part-%03d.b64"%i, base64.b64encode(part)+b"\n")
        item.update(decoded_offset=off, decoded_bytes=len(part), decoded_sha256=sha256(part))
        meta["parts"].append(item)
    return meta

def event(kind, **fields):
    row = {"event":kind,"at":now(),**fields}
    events.append(row)
    b = jbytes(row)
    fd = os.open(OUT/"EVENTS.jsonl", os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"ab") as f:
        f.write(b); f.flush(); os.fsync(f.fileno())
    print(b.decode("utf-8"),end="",flush=True)

def enter(name):
    global phase
    phase = name
    result.setdefault("attempted_phases",[]).append(name)
    event("phase_started",phase=name)
    jwrite("%02d-%s-started.json"%(len(result["attempted_phases"]),name),{"phase":name,"at":now()})

def sanitize_git_environment():
    forbidden = ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE","GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES","GIT_SHALLOW_FILE","GIT_REPLACE_REF_BASE",
                 "GIT_CONFIG_COUNT","GIT_CONFIG_PARAMETERS","GIT_CONFIG_GLOBAL","GIT_CONFIG_SYSTEM")
    present = [key for key in forbidden if os.environ.get(key)]
    if present:
        raise PreconditionError("inherited Git override names: "+repr(present))
    check(pathlib.Path(GIT).is_file(), "existing system Git executable unavailable")
    os.environ["PATH"] = "/usr/bin:/bin"
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
    os.environ["GIT_CONFIG_SYSTEM"] = "/dev/null"
    os.environ["GIT_CONFIG_COUNT"] = "3"
    for i,(key,val) in enumerate((("core.fsmonitor","false"),("core.untrackedCache","false"),("core.logAllRefUpdates","false"))):
        os.environ["GIT_CONFIG_KEY_"+str(i)] = key
        os.environ["GIT_CONFIG_VALUE_"+str(i)] = val
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True

def git(repo, args, mutates=False, stdin_file=None):
    check(repo == SOURCE or repo == TARGET, "fixed Git repo only")
    check(not mutates or (repo == TARGET and target_created), "no old repository Git writes")
    argv = [GIT,"--no-optional-locks","-C",str(repo),*args]
    record = {"argv":argv,"started_at":now(),"writes_new_repo_only":bool(mutates)}
    commands.append(record)
    try:
        completed = subprocess.run(argv,stdin=stdin_file,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=False)
        record.update(returncode=completed.returncode,stdout_bytes=len(completed.stdout),
                      stdout_sha256=sha256(completed.stdout),stderr_bytes=len(completed.stderr),
                      stderr_sha256=sha256(completed.stderr),finished_at=now())
        if mutates:
            write("git-%03d.stdout"%len(commands),completed.stdout)
            write("git-%03d.stderr"%len(commands),completed.stderr)
        check(completed.returncode == 0,"Git command failed: "+repr(args)+" stderr="+completed.stderr.decode("utf-8","replace")[:4000])
        return completed.stdout
    except BaseException as error:
        record.update(error=type(error).__name__+": "+str(error),finished_at=now())
        raise

def source_git_state():
    head = git(SOURCE,["rev-parse","--verify","HEAD"]).decode("ascii").strip()
    tree = git(SOURCE,["rev-parse","--verify","HEAD^{tree}"]).decode("ascii").strip()
    gitdir = pathlib.Path(git(SOURCE,["rev-parse","--absolute-git-dir"]).decode("utf-8").strip())
    common = pathlib.Path(git(SOURCE,["rev-parse","--path-format=absolute","--git-common-dir"]).decode("utf-8").strip())
    check(gitdir == SOURCE/".git" and common == gitdir, "source must be the actual independent source-gates repo")
    check_real_parents(gitdir)
    alt = gitdir/"objects"/"info"/"alternates"
    check(not alt.exists() or regular_read(alt,100000)==b"", "source alternates not admitted")
    index = regular_read(gitdir/"index",40000000)
    refs = git(SOURCE,["for-each-ref","--format=%(refname) %(objectname)"])
    return {"head":head,"tree":tree,"index_bytes":len(index),"index_sha256":sha256(index),
            "refs_bytes":len(refs),"refs_sha256":sha256(refs),"worktree_file_bytes_examined":False}

def metadata_inventory(root):
    rows = []
    def visit(directory):
        for entry in sorted(os.scandir(directory), key=lambda x:os.fsencode(x.name)):
            path = pathlib.Path(entry.path)
            s = path.lstat()
            row = {"path":path.relative_to(root).as_posix(),"mode":stat.S_IMODE(s.st_mode),
                   "device":s.st_dev,"inode":s.st_ino,"nlink":s.st_nlink,
                   "mtime_ns":s.st_mtime_ns,"ctime_ns":s.st_ctime_ns}
            if stat.S_ISDIR(s.st_mode):
                row["kind"]="directory"; rows.append(row); visit(path)
            elif stat.S_ISREG(s.st_mode):
                digest=hashlib.sha256()
                fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
                with os.fdopen(fd,"rb") as f:
                    before=os.fstat(f.fileno())
                    for chunk in iter(lambda:f.read(1048576),b""): digest.update(chunk)
                    after=os.fstat(f.fileno())
                check((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==
                      (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                      (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),"Git metadata changed while reading")
                row.update(kind="file",bytes=s.st_size,sha256=digest.hexdigest());rows.append(row)
            elif stat.S_ISLNK(s.st_mode):
                value=os.fsencode(os.readlink(path))
                row.update(kind="symlink",bytes=len(value),sha256=sha256(value));rows.append(row)
            else:
                raise PreconditionError("unsupported source Git metadata file "+str(path))
    visit(root)
    return jbytes({"format":"hepta-source-git-metadata-inventory-v1","root":str(root),"files":rows})

def exact_read(stream, count):
    blocks=[]
    while count:
        block=stream.read(min(count,1048576))
        check(bool(block),"unexpected cat-file EOF")
        blocks.append(block);count-=len(block)
    return b"".join(blocks)

class Batch:
    def __init__(self, repo, name):
        self.repo=repo;self.name=name;self.closed=False
        self.stderr_path=OUT/(name+".stderr.log")
        self.stderr=open(self.stderr_path,"xb")
        self.command={"argv":[GIT,"--no-optional-locks","-C",str(repo),"cat-file","--batch"],
                      "started_at":now(),"writes_new_repo_only":False}
        commands.append(self.command)
        self.process=subprocess.Popen(self.command["argv"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr)
        self.command["pid"]=self.process.pid
    def get(self, value, kind):
        check(not self.closed and HEX.fullmatch(value) and kind in ("blob","tree","commit"),"invalid cat-file request")
        self.process.stdin.write((value+"\n").encode("ascii"));self.process.stdin.flush()
        header=self.process.stdout.readline(512)
        fields=header.rstrip(b"\n").split(b" ")
        check(len(fields)==3 and fields[0].decode("ascii")==value,"missing/bad object "+value+": "+repr(header))
        check(fields[1].decode("ascii")==kind,"cat-file object type")
        size=int(fields[2]);check(0<=size<=1073741824,"object size ceiling")
        raw=exact_read(self.process.stdout,size)
        check(exact_read(self.process.stdout,1)==b"\n","cat-file terminator")
        check(oid(kind,raw)==value,"actual raw object SHA "+value)
        return raw
    def close(self):
        if self.closed:return
        self.closed=True
        try:
            self.process.stdin.close()
            rc=self.process.wait(timeout=10)
            self.command.update(returncode=rc,finished_at=now())
            check(rc==0,"cat-file helper exit")
        except BaseException:
            self.process.kill()
            self.process.wait(timeout=10)
            raise
        finally:
            self.stderr.close()
            raw=regular_read(self.stderr_path,1000000)
            artifacts.append({"name":self.stderr_path.name,"bytes":len(raw),"sha256":sha256(raw),"git_blob":oid("blob",raw)})

def object_meta(kind, value, raw):
    return {"type":kind,"sha":value,"bytes":len(raw),"sha256":sha256(raw)}

def source_object(value, kind):
    if value in retained_existing_raw:
        check(existing[value]["type"]==kind,"cached source object type")
        return retained_existing_raw[value]
    if value in existing and kind=="blob":
        check(existing[value]["type"]==kind,"cached blob type")
        return None
    raw=source_batch.get(value,kind)
    meta=object_meta(kind,value,raw)
    existing[value]=meta
    if kind in ("tree","commit"):retained_existing_raw[value]=raw
    return raw if kind in ("tree","commit") else None

def add_provided(packet, manifest, count, counts):
    expected={x["sha"]:x for x in manifest["object_index"]}
    check(len(expected)==count and len(manifest["object_index"])==count and len(packet["objects"])==count,"provided object count/index")
    result_objects={}
    for entry in packet["objects"]:
        value,kind=entry["sha"],entry["type"]
        check(HEX.fullmatch(value) and kind in ("blob","tree","commit") and value not in result_objects,"provided object shape")
        raw=base64.b64decode(entry["raw_base64"],validate=True)
        check(base64.b64encode(raw).decode("ascii")==entry["raw_base64"],"canonical object base64")
        check(len(raw)==entry["bytes"] and sha256(raw)==entry["sha256"] and oid(kind,raw)==value,"provided raw object identity")
        meta=object_meta(kind,value,raw)
        reference=expected[value]
        check(all(meta[k]==reference[k] for k in ("sha","type","bytes","sha256")),"object manifest mismatch")
        check(value not in supplied,"two provided packets must have disjoint identities")
        item={**meta,"raw":raw}
        result_objects[value]=item; supplied[value]=item
    check(set(result_objects)==set(expected),"exact provided object set")
    check({kind:sum(x["type"]==kind for x in result_objects.values()) for kind in counts}==counts,"provided object type counts")
    return result_objects

def supplied_raw(value,kind):
    item=supplied[value];check(item["type"]==kind,"supplied reference type");return item["raw"]

def manifest_part(directory, name):
    check(isinstance(name,str) and pathlib.Path(name).name==name and name not in (".",".."),"manifest part path")
    return directory/name

def load_canonical():
    mb=read_input(CANONICAL_INPUT/"CANONICAL_MANIFEST.json",MANIFEST_395,1000000)
    m=parse(mb);write("CANONICAL_MANIFEST.original.json",mb)
    check(m["repository"]==REPOSITORY and m["fixed_base"]==B298 and m["fixed_tip"]==A96 and m["fixed_tip_tree"]==A96_TREE,"395 manifest anchors")
    joined=[];offset=0
    for ordinal,p in enumerate(m["parts"],1):
        check(p["ordinal"]==ordinal and p["base64_offset"]==offset,"395 part order")
        b=read_input(manifest_part(CANONICAL_INPUT,p["name"]),p,1000000)
        check(b.endswith(b"\n") and b.count(b"\n")==1 and len(b)-1==p["base64_characters"],"395 part single final LF")
        joined.append(b[:-1]);offset+=len(b)-1
    check(len(joined)==5,"395 five parts")
    enc=b"".join(joined);pin_bytes(enc+b"\n",m["base64_stream"],"395 b64 stream")
    gz=base64.b64decode(enc,validate=True)
    check(base64.b64encode(gz)==enc,"395 canonical b64")
    pin_bytes(gz,m["gzip"],"395 gzip")
    with gzip.GzipFile(fileobj=io.BytesIO(gz),mode="rb") as stream:
        raw=stream.read(PACKET_395["bytes"]+1)
        check(len(raw)==PACKET_395["bytes"] and not stream.read(1),"395 gzip bound")
    pin_bytes(raw,PACKET_395,"395 raw JSON")
    p=parse(raw)
    check(p["format"]=="hepta-canonical-git-object-transport-v1" and p["repository"]==REPOSITORY,"395 schema")
    check(p["fixed_base"]==B298 and p["base_tree"]==B298_TREE and p["reuse_commit"]==C0F and p["reuse_tree"]==C0F_TREE and p["fixed_tip"]==A96 and p["fixed_tip_tree"]==A96_TREE,"395 packet anchors")
    check(p["native_import_performed"] is False and p["source_and_ref_writes_performed"] is False and p["test_execution"] is False,"395 original preparation flags")
    objs=add_provided(p,m,395,{"commit":7,"tree":80,"blob":308})
    return p,m,objs

def load_prepared():
    mb=read_input(PREPARED_INPUT/"PREPARED_MANIFEST.json",MANIFEST_87,1000000)
    m=parse(mb);write("PREPARED_MANIFEST.original.json",mb)
    check(m["format"]=="hepta-preparation-hold-git-object-delta-manifest-v1" and m["repository"]==REPOSITORY,"87 manifest schema")
    joined=[];offset=0
    for ordinal,p in enumerate(m["parts"],1):
        check(p["ordinal"]==ordinal and p["offset"]==offset,"87 exact fragment order")
        b=read_input(manifest_part(PREPARED_INPUT,p["name"]),p,1000000)
        joined.append(b);offset+=len(b)
    check(len(joined)==5,"87 five fragments")
    raw=b"".join(joined);pin_bytes(raw,PACKET_87,"87 exact raw JSON")
    p=parse(raw)
    check(p["format"]=="hepta-preparation-hold-git-object-delta-v1" and p["repository"]==REPOSITORY,"87 packet schema")
    for obj in (p,m):
        check(obj["source_commit"]==PREPARED and obj["source_tree"]==PREPARED_TREE and obj["parents"]==[C0F,A96],"87 exact commit/tree/ordered parents")
        check(obj["fixed_upstream"]==A96 and obj["fixed_upstream_tree"]==A96_TREE and obj["reuse_commit"]==C0F and obj["reuse_tree"]==C0F_TREE,"87 fixed parent snapshot pins")
        check(obj["leaf_count"]==15188 and obj["changed_paths_from_fixed_upstream"]==99 and obj["new_paths_from_fixed_upstream"]==27,"87 leaf/change counts")
        check(obj["status"]=="PREPARATION/HOLD" and obj["qualification"] is False,"87 hold scope")
    check(p["preparation_only"] is True and p["native_import_performed"] is False and p["source_ref_updated"] is False and p["evidence_ref_updated"] is False and p["pr_updated"] is False and p["maintenance_executed_on_this_tree"] is False and p["tests_executed_on_this_tree"] is False,"87 unexecuted scope")
    check(p["changes"]==m["changes"],"87 manifest complete changes")
    objs=add_provided(p,m,87,{"commit":1,"tree":9,"blob":77})
    return p,m,objs



def leaf_diff(before,after):
    return [{"path":p.decode("utf-8"),"before":before.get(p),"after":after.get(p)}
            for p in sorted(set(before)|set(after)) if before.get(p)!=after.get(p)]

def full_leaf_metadata(leaves):
    rows=[]
    for path in sorted(leaves):
        row=dict(leaves[path]);value=row["sha"]
        meta=supplied.get(value,existing.get(value))
        check(meta is not None and meta["type"]=="blob","leaf blob metadata")
        row.update(bytes=meta["bytes"],sha256=meta["sha256"])
        rows.append(row)
    return rows

def verify_graphs(packet395,manifest395,objects395,packet87,manifest87,objects87):
    braw=source_object(B298,"commit");craw=source_object(C0F,"commit")
    bfields=commit_fields(braw);cfields=commit_fields(craw)
    check(bfields["tree"]==B298_TREE,"actual b298 tree")
    check(cfields["tree"]==C0F_TREE and cfields["parents"]==["e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd",B298],"actual c0f tree and canonical parents")
    bmap,btrees=snapshot(B298_TREE,source_object)
    cmap,ctrees=snapshot(C0F_TREE,source_object)
    check(len(bmap)==14842 and len(cmap)==14851,"actual full parent snapshot leaves")
    trusted={value:meta["type"] for value,meta in existing.items()}
    check(len(trusted)==16136,"actual pinned old snapshot union")
    required={}
    for item in packet395["required_existing_objects"]:
        check(set(item)=={"sha","type"} and HEX.fullmatch(item["sha"]) and item["sha"] not in required,"395 prerequisite entry")
        check(trusted.get(item["sha"])==item["type"],"395 prerequisite outside original snapshot union")
        required[item["sha"]]=item["type"]
    check(len(required)==16082 and manifest395["required_existing_object_count"]==16082,"395 prerequisite exact count")
    needed={};used=set();maps={"base_b298":full_leaf_metadata(bmap),"fmt_base_c0f":full_leaf_metadata(cmap)}
    def resolve395(value,kind):
        if value in objects395:
            check(objects395[value]["type"]==kind,"395 provided tree child type")
            return objects395[value]["raw"]
        check(trusted.get(value)==kind and required.get(value)==kind,"395 unlisted snapshot prerequisite")
        needed[value]=kind
        return source_object(value,kind)
    order=packet395["canonical_commit_order"]
    check(order==manifest395["canonical_commits"] and len(order)==7 and len(packet395["per_commit_changed_paths"])==7,"395 ordered original commits")
    parent=B298;prior=bmap;audit=[]
    for i,item in enumerate(order):
        check(item["parents"]==[parent],"395 exact linear parent chain")
        fields=commit_fields(supplied_raw(item["sha"],"commit"))
        check(fields["tree"]==item["tree"] and fields["parents"]==[parent],"395 canonical raw headers")
        check(not fields["message_ends_with_lf"] and len(fields["author_lines"])==1 and len(fields["committer_lines"])==1 and fields["author_lines"][0].endswith(" -0500") and fields["committer_lines"][0].endswith(" -0500"),"395 original timezone/message ending")
        current,trees=snapshot(item["tree"],resolve395)
        delta=leaf_diff(prior,current)
        record=packet395["per_commit_changed_paths"][i]
        check(record["sha"]==item["sha"] and record["tree"]==item["tree"] and record["parent"]==parent,"395 diff record identity")
        check(record["leaf_count"]==len(current) and record["unique_tree_objects"]==len(trees),"395 exact complete snapshot size")
        check(sorted(record["changes"],key=lambda x:x["path"].encode("utf-8"))==delta,"395 full changed leaf map")
        summary=manifest395["per_commit_summary"][i]
        check(summary["sha"]==item["sha"] and summary["leaf_count"]==len(current) and summary["changed_paths"]==len(delta),"395 manifest snapshot summary")
        used.add(item["sha"]);used.update(trees & set(objects395));used.update(x["sha"] for x in current.values() if x["sha"] in objects395)
        maps[item["sha"]]=full_leaf_metadata(current)
        audit.append({**item,"leaf_count":len(current),"unique_tree_objects":len(trees),"changed_paths":len(delta),"raw_commit_fields":fields})
        parent,prior=item["sha"],current
    needed.update({B298:"commit",C0F:"commit"})
    check(needed==required and used==set(objects395),"395 exact required/provided reachability")
    check(parent==A96 and order[-1]["tree"]==A96_TREE and len(prior)==15161,"395 final a96 full snapshot")
    afields=commit_fields(supplied_raw(A96,"commit"))
    check(afields["tree"]==A96_TREE,"a96 raw tree")
    fields=commit_fields(supplied_raw(PREPARED,"commit"))
    check(fields["tree"]==PREPARED_TREE and fields["parents"]==[C0F,A96],"86dd original merge tree/ordered parents")
    check(not fields["message_ends_with_lf"] and len(fields["author_lines"])==1 and len(fields["committer_lines"])==1 and fields["author_lines"][0].endswith(" -0500") and fields["committer_lines"][0].endswith(" -0500"),"86dd original timezone/message ending")
    check(packet87["canonical_commit_order"]==[{"sha":PREPARED,"tree":PREPARED_TREE,"parents":[C0F,A96]}],"86dd canonical metadata")
    direct={}
    for value,obj in objects87.items():
        if obj["type"]=="tree":
            for mode,name,child in parse_tree(obj["raw"]):
                kind="tree" if mode=="40000" else "blob"
                if child not in objects87:
                    check(child not in direct or direct[child]==kind,"87 direct child type")
                    direct[child]=kind
    direct.update({C0F:"commit",A96:"commit"})
    listed={}
    for item in packet87["required_existing_direct_objects"]:
        check(set(item)=={"sha","type"} and HEX.fullmatch(item["sha"]) and item["sha"] not in listed,"87 direct-ref entry")
        listed[item["sha"]]=item["type"]
    check(direct==listed and len(direct)==1451 and manifest87["direct_existing_references"]==1451,"87 exact direct refs, not transitive closure")
    known={**trusted,**{value:obj["type"] for value,obj in objects395.items()}}
    for value,kind in direct.items():
        check(known.get(value)==kind,"87 direct ref outside validated snapshot/object domain")
    def resolve87(value,kind):
        if value in supplied:
            return supplied_raw(value,kind)
        check(trusted.get(value)==kind,"final tree outside validated old snapshot domain")
        return source_object(value,kind)
    final,trees=snapshot(PREPARED_TREE,resolve87)
    check(len(final)==15188,"86dd full final snapshot leaf count")
    delta=leaf_diff(prior,final)
    check(len(delta)==99 and sum(x["before"] is None for x in delta)==27,"86dd final exact delta sizes")
    check(sorted(packet87["changes"],key=lambda x:x["path"].encode("utf-8"))==delta,"86dd all 99 source changes")
    used87={PREPARED}|(trees & set(objects87))|{x["sha"] for x in final.values() if x["sha"] in objects87}
    check(used87==set(objects87),"87 supplied objects exactly final reachable")
    reused=[x for x in delta if x["after"] is not None and x["after"]["sha"] not in objects87]
    check(reused==packet87["reused_changed_leaf_objects"] and len(reused)==22,"22 already-reachable changed leaf objects")
    check(len(supplied)==482,"two provided object packets are disjoint")
    overlap=sorted(set(existing)&set(supplied))
    for value in overlap:
        check(existing[value]=={key:supplied[value][key] for key in ("sha","type","bytes","sha256")},"preexisting supplied object metadata conflict")
    import_index.update({value:dict(meta) for value,meta in existing.items()})
    import_index.update({value:{k:obj[k] for k in ("sha","type","bytes","sha256")} for value,obj in supplied.items()})
    check(len(import_index)==16136+482-len(overlap),"actual bounded import union")
    jwrite("PROVIDED_OLD_OBJECT_OVERLAP.json",{"provided_objects":482,"trusted_old_snapshot_objects":16136,
                                             "overlap":overlap,"unique_import_objects":len(import_index)})
    maps["prepared_86dd"]=full_leaf_metadata(final)
    gzrecord("ALL_SNAPSHOT_LEAVES.json.gz",jbytes(maps))
    jwrite("CANONICAL_COMMIT_CHECKS.json",{"upstream":audit,"prepared":fields,"full_parent_snapshots":{"b298":len(bmap),"c0f":len(cmap)},"older_parent_history_not_traversed":True})
    gzrecord("IMPORT_OBJECT_INDEX.json.gz",jbytes({"provided":482,"trusted_old_snapshot_objects":len(trusted),"all":[import_index[x] for x in sorted(import_index)]}))
    jwrite("FINAL_DELTA.json",delta)
    result["verified_graphs"]={"seven_upstream_snapshots":7,"original_parent_snapshot_leaves":{"b298":14842,"c0f":14851},"upstream_tip_leaves":15161,
                               "prepared_leaves":15188,"prepared_changes":99,"prepared_new_paths":27,
                               "provided_objects":482,"canonical_existing_required":16082,"prepared_direct_existing":1451,
                               "import_union":len(import_index),"provided_old_overlap":len(overlap),"whole_history_claimed":False}
    return final,trees,maps

def pack_entry_header(kind,size):
    type_id={"commit":1,"tree":2,"blob":3}[kind]
    first=(type_id<<4)|(size & 15);size >>= 4
    out=bytearray()
    if size:first |= 128
    out.append(first)
    while size:
        byte=size & 127;size >>= 7
        if size:byte |= 128
        out.append(byte)
    return bytes(out)

def disk_requirement(final):
    physical=sum(import_index[row["sha"]]["bytes"] for row in final.values())
    raw_total=sum(x["bytes"] for x in import_index.values())
    pack_upper=sum(x["bytes"]+x["bytes"]//1000+64 for x in import_index.values())+32
    required=2*pack_upper+physical+128*1024*1024+256*1024*1024
    available=shutil.disk_usage(TARGET.parent)
    result["disk_preflight"]={"free":available.free,"total":available.total,"used":available.used,
                              "uncompressed_object_bytes":raw_total,"physical_file_bytes":physical,
                              "conservative_pack_bytes":pack_upper,"required_free":required,
                              "includes_two_pack_copies_and_384MiB_record_headroom":True}
    jwrite("DISK_PREFLIGHT.json",result["disk_preflight"])
    check(available.free>=required,"insufficient actual free disk for new isolated repository")
    return physical

def create_and_import():
    global target_created
    check_real_parents(TARGET.parent)
    check(not os.path.lexists(TARGET),"target already exists; refuse overwrite/retry/rename")
    os.mkdir(TARGET,0o700);target_created=True;result["new_repo_created"]=True
    git(TARGET,["init","--quiet","--template="],mutates=True)
    git(TARGET,["config","--local","core.autocrlf","false"],mutates=True)
    git(TARGET,["config","--local","core.filemode","true"],mutates=True)
    git(TARGET,["config","--local","core.symlinks","true"],mutates=True)
    check(git(TARGET,["rev-parse","--absolute-git-dir"]).decode().strip()==str(TARGET/".git"),"new independent Git dir")
    for p in (TARGET/".git"/"objects"/"info"/"alternates",TARGET/".git"/"shallow",TARGET/".git"/"info"/"grafts"):
        check(not p.exists(),"no alternates/shallow/grafts in new repo")
    check(git(TARGET,["for-each-ref"])==b"","new repo has no inherited refs")
    pack_path=TARGET/".git"/"fresh-materialization-input.pack"
    stream_hash=hashlib.sha1();stream_sha256=hashlib.sha256();count=len(import_index)
    with open(pack_path,"xb") as f:
        def put(raw):
            f.write(raw);stream_hash.update(raw);stream_sha256.update(raw)
        put(b"PACK"+struct.pack(">II",2,count))
        for i,value in enumerate(sorted(import_index),1):
            expected=import_index[value];kind=expected["type"]
            raw=supplied[value]["raw"] if value in supplied else (
                retained_existing_raw[value] if value in retained_existing_raw else source_batch.get(value,kind))
            check(object_meta(kind,value,raw)==expected and oid(kind,raw)==value,"pack original raw object changed")
            put(pack_entry_header(kind,len(raw)));put(zlib.compress(raw))
            if i%512==0:event("pack_objects_encoded",completed=i,total=count)
        footer=stream_hash.digest()
        f.write(footer);stream_sha256.update(footer);f.flush();os.fsync(f.fileno())
        pack_bytes=f.tell()
    pack_sha=footer.hex()
    jwrite("PACK_INPUT.json",{"path":str(pack_path),"signature":"PACK","version":2,"count":count,
                             "object_types":{kind:sum(x["type"]==kind for x in import_index.values()) for kind in ("commit","tree","blob")},
                             "pack_checksum_sha1":pack_sha,"bytes":pack_bytes,"sha256":stream_sha256.hexdigest(),
                             "zlib_runtime":zlib.ZLIB_RUNTIME_VERSION,"delta_objects":0,"raw_commit_bytes_preserved":True})
    result["import_started"]=True
    with open(pack_path,"rb") as f:
        output=git(TARGET,["index-pack","--threads=1","--stdin"],mutates=True,stdin_file=f)
    check(output.strip()==("pack\t"+pack_sha).encode("ascii"),"index-pack actual checksum")
    actual_pack=TARGET/".git"/"objects"/"pack"/("pack-"+pack_sha+".pack")
    check(actual_pack.is_file(),"standard imported pack missing")
    with open(actual_pack,"rb") as f:
        head=f.read(12);digest=hashlib.sha256(head)
        for block in iter(lambda:f.read(1048576),b""):digest.update(block)
    check(head==b"PACK"+struct.pack(">II",2,count) and actual_pack.stat().st_size==pack_bytes and digest.hexdigest()==stream_sha256.hexdigest(),"stored Git pack exact byte identity")
    for retained in (actual_pack,actual_pack.with_suffix(".idx")):
        fd=os.open(retained,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    result["import_command_completed"]=True
    result["pack"]={"sha1":pack_sha,"sha256":stream_sha256.hexdigest(),"bytes":pack_bytes,"objects":count,
                    "stored_path":str(actual_pack),"input_copy_retained":str(pack_path)}
    return pack_sha

def verify_new_object_database():
    global target_batch
    target_batch=Batch(TARGET,"target-cat-file")
    audit=[];new_raw={}
    for i,value in enumerate(sorted(import_index),1):
        expected=import_index[value]
        raw=target_batch.get(value,expected["type"])
        check(object_meta(expected["type"],value,raw)==expected,"new database original raw byte identity")
        audit.append(expected)
        if expected["type"] in ("tree","commit"):new_raw[value]=raw
        if i%512==0:event("new_objects_read_back",completed=i,total=len(import_index))
    gzrecord("IMPORTED_OBJECT_READBACK.json.gz",jbytes({"every_raw_body_read":True,"objects":audit}))
    def resolve(value,kind):
        check(import_index.get(value,{}).get("type")==kind,"new snapshot closure undeclared object")
        return new_raw[value] if kind in ("tree","commit") else None
    summaries=[]
    for value in [B298,C0F]+[x["sha"] for x in canonical_order]+[PREPARED]:
        raw=resolve(value,"commit");fields=commit_fields(raw)
        leaves,trees=snapshot(fields["tree"],resolve)
        expected=all_maps["base_b298" if value==B298 else "fmt_base_c0f" if value==C0F else "prepared_86dd" if value==PREPARED else value]
        actual=[]
        for p in sorted(leaves):
            row=dict(leaves[p]);meta=import_index[row["sha"]]
            row.update(bytes=meta["bytes"],sha256=meta["sha256"]);actual.append(row)
        check(actual==expected,"new object database full snapshot mismatch "+value)
        summaries.append({"sha":value,"tree":fields["tree"],"parents":fields["parents"],"leaf_count":len(leaves),"unique_tree_objects":len(trees)})
    jwrite("NEW_DATABASE_SNAPSHOT_CLOSURES.json",summaries)
    result["new_database_verified"]={"objects":len(audit),"complete_snapshots":len(summaries),"full_c0f_snapshot":True,"final_leaves":15188}
    return summaries

def exact_index():
    raw=git(TARGET,["ls-files","--stage","-z"])
    rows={}
    for line in raw.split(b"\0"):
        if not line:continue
        metadata,path=line.split(b"\t",1)
        mode,value,stage=metadata.decode("ascii").split()
        check(stage=="0" and path not in rows,"new index exact stage/duplicate")
        rows[path]={"path":path.decode("utf-8"),"mode":mode,"type":"blob","sha":value}
    return rows

def physical_materialization(final):
    check(git(TARGET,["rev-parse","--verify",PREPARED+"^{tree}"]).decode().strip()==PREPARED_TREE,"exact new commit root")
    git(TARGET,["read-tree",PREPARED_TREE],mutates=True)
    git(TARGET,["-c","core.logAllRefUpdates=false","update-ref","--no-deref","HEAD",PREPARED],mutates=True)
    check(regular_read(TARGET/".git"/"HEAD",1000)==(PREPARED+"\n").encode("ascii"),"new detached HEAD raw identity")
    check(git(TARGET,["for-each-ref"])==b"","no branch or other ref created in new repo")
    check(exact_index()==final,"new complete index matches final tree")
    initial=inventory_module.inventory(TARGET)
    gzrecord("TARGET.before-physical.inventory.json.gz",initial)
    initial_value=parse(initial)
    check(initial_value["tracked_entries"]==15188 and initial_value["filesystem_entries"]==0 and all(row["kind"]=="missing" for row in initial_value["files"]),"new worktree is empty before materialization")
    result["physical_materialization_started"]=True
    space=shutil.disk_usage(TARGET)
    required=sum(import_index[row["sha"]]["bytes"] for row in final.values())+64*1024*1024
    check(space.free>=required,"actual remaining disk before physical writes")
    for i,path_bytes in enumerate(sorted(final),1):
        row=final[path_bytes];relative=pathlib.PurePosixPath(row["path"])
        check(not relative.is_absolute() and all(part not in ("",".","..") and part.lower()!=".git" for part in relative.parts),"unsafe physical path")
        parent=TARGET
        for part in relative.parts[:-1]:
            parent=parent/part
            if not os.path.lexists(parent):os.mkdir(parent,0o755)
            check(stat.S_ISDIR(parent.lstat().st_mode) and not parent.is_symlink(),"physical ancestor is not a real directory")
        path=TARGET/row["path"]
        check(not os.path.lexists(path),"physical leaf already exists")
        data=target_batch.get(row["sha"],"blob")
        check(object_meta("blob",row["sha"],data)==import_index[row["sha"]],"physical source blob changed")
        if row["mode"]=="120000":
            check(b"\0" not in data,"invalid original symlink bytes")
            os.symlink(os.fsdecode(data),path)
            check(os.fsencode(os.readlink(path))==data,"symlink raw bytes")
        else:
            check(row["mode"] in ("100644","100755"),"regular Git mode")
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,"wb") as f:
                f.write(data);f.flush()
                os.fchmod(f.fileno(),0o755 if row["mode"]=="100755" else 0o644)
                os.fsync(f.fileno())
        if i%512==0:event("physical_leaves_written",completed=i,total=len(final))
    for directory,children,files in os.walk(TARGET,topdown=False,followlinks=False):
        for name in children:
            child=pathlib.Path(directory)/name
            if child.is_symlink():continue
            fd=os.open(child,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
    fd=os.open(TARGET,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    after=inventory_module.inventory(TARGET)
    inventory_module.require_inventory(after,TARGET_CFG)
    value=parse(after)
    check(value["tracked_entries"]==15188 and value["filesystem_entries"]==15188 and len(value["files"])==15188,"full physical leaf set/count")
    for row in value["files"]:
        expected=final[row["path"].encode("utf-8")]
        check(row["index_blob"]==expected["sha"] and row["index_mode"]==expected["mode"] and row["working_blob"]==expected["sha"],"physical/index/original Git identity")
        check(row["sha256"]==import_index[expected["sha"]]["sha256"] and row["bytes"]==import_index[expected["sha"]]["bytes"],"physical exact raw body digest")
        check((row["kind"]=="symlink")==(expected["mode"]=="120000"),"physical Git type")
        if row["kind"]=="file":
            check(bool(row["permissions"] & 0o111)==(expected["mode"]=="100755"),"physical executable mode")
    check(exact_index()==final,"final index unchanged")
    check(git(TARGET,["write-tree"],mutates=True).decode().strip()==PREPARED_TREE,"final index Merkle root")
    check(git(TARGET,["rev-parse","HEAD"]).decode().strip()==PREPARED and git(TARGET,["rev-parse","HEAD^{tree}"]).decode().strip()==PREPARED_TREE,"final HEAD/tree")
    check(regular_read(TARGET/".git"/"HEAD",1000)==(PREPARED+"\n").encode("ascii") and git(TARGET,["for-each-ref"])==b"","final detached HEAD/no branches")
    for name in ("HEAD","index","config"):
        fd=os.open(TARGET/".git"/name,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    gzrecord("TARGET.after-physical.inventory.json.gz",after)
    result["destination_inventory"]={"bytes":len(after),"sha256":sha256(after),"git_blob":oid("blob",after),"tracked_entries":15188,"filesystem_entries":15188}
    result["materialized"]={"head":PREPARED,"tree":PREPARED_TREE,"index_equals_tree":True,"physical_bytes_equal":True,
                            "detached":True,"maintenance_or_tests_started":False,"qualification":False}



def timeout_handler(signum,frame):
    raise TimeoutError("bounded "+phase+" deadline")

def validate_approval_and_proofs():
    cfg_bytes=read_input(CONFIG,maximum=100000)
    cfg=parse(cfg_bytes)
    check(cfg.get("format")=="hepta-fresh-source-materialization-approval-v1","approval schema")
    if cfg.get("status")!="ROOT_APPROVED_TO_EXECUTE" or cfg.get("root_execution_approved") is not True:
        raise PreconditionError("HOLD: Root has not approved this exact fresh-materialization driver")
    actual_driver=read_input(__file__,maximum=200000)
    check(cfg.get("driver_sha256")==sha256(actual_driver) and cfg.get("driver_git_blob")==oid("blob",actual_driver),"approved driver exact identity")
    check(cfg.get("source_repo")==str(SOURCE) and cfg.get("target_repo")==str(TARGET)
          and cfg.get("source_commit")==PREPARED and cfg.get("source_tree")==PREPARED_TREE
          and cfg.get("parents")==[C0F,A96],"approved exact source/path/parents")
    check(cfg.get("operation_seconds")==IMPORT_SECONDS and cfg.get("final_record_seconds")==FINAL_RECORD_SECONDS,"approved separate operation budget")
    check(cfg.get("maintenance_or_tests_authorized") is False and cfg.get("remote_ref_updates_authorized") is False,"no maintenance/ref scope expansion")
    write("ACTUAL_DRIVER.py",actual_driver)
    write("APPROVED_CONFIG.original.json",cfg_bytes)
    review_bytes=read_input(CANONICAL_REVIEW,CANONICAL_REVIEW_PIN,1000000)
    review=parse(review_bytes);write("CANONICAL_ROOT_REVIEW.original.json",review_bytes)
    root_bytes=read_input(EVIDENCE/"ROOT_INDEPENDENT_REVIEW.json",ROOT_INDEPENDENT_PIN,1000000)
    independent=parse(root_bytes);write("ROOT_INDEPENDENT_REVIEW.original.json",root_bytes)
    sdk_bytes=read_input(EVIDENCE/"CANONICAL_TERMINAL_SDK.json",TERMINAL_SDK_PIN,1000000)
    outer=parse(sdk_bytes);write("CANONICAL_TERMINAL_SDK.original.json",sdk_bytes)
    check(outer.get("resultType")=="complete" and outer.get("isError") is False and len(outer.get("content",[]))==1 and outer["content"][0]["type"]=="text","actual canonical terminal SDK envelope")
    terminal=parse(outer["content"][0]["text"].encode("utf-8"))
    check(terminal.get("job_id")=="1a1d09b7b3e-2564-1ba7" and terminal.get("state")=="succeeded"
          and terminal.get("exit_code")==0 and terminal.get("timed_out") is False
          and terminal.get("cancelled") is False and terminal.get("automatic_retry") is False
          and terminal.get("output_complete") is True and terminal.get("output_durable") is True
          and terminal.get("terminal_publication_confirmed") is True
          and not any(terminal.get("log_truncated",{}).values()),"actual normal canonical validation terminal")
    check(review.get("kind")=="evidence_only_canonical_validation" and review.get("status")=="canonical_snapshot_closure_verified"
          and review.get("canonical_tip")==A96 and review.get("canonical_tip_tree")==A96_TREE
          and review.get("canonical_tip_leaf_count")==15161 and review.get("canonical_commit_count")==7
          and review.get("provided_raw_objects_verified")==395 and review.get("provided_exact_reachable_set") is True
          and review.get("source_git_state_equal") is True and review.get("cat_file_returncode")==0
          and review.get("git_object_imported") is False and review.get("cargo_or_tests_started") is False
          and review.get("source_or_ref_write_requested") is False and review.get("qualification") is False,"actual original evidence-only result")
    check(review["source_git_state_before"]==review["source_git_state_after"],"actual review before/after Git state")
    check(review["required_existing"]=={"count":16082,"counts":{"blob":14306,"commit":2,"tree":1774},
                                      "exact_needed_existing_set":True,"trusted_snapshot_membership":True},"actual canonical required set")
    check(independent.get("schema")=="hepta.root.actual-a96-canonical-validation-review.v1"
          and independent.get("job_id")==terminal["job_id"]
          and independent.get("actual_result_git_blob")==CANONICAL_REVIEW_PIN["git_blob"]
          and independent.get("result_bytes")==CANONICAL_REVIEW_PIN["bytes"]
          and independent.get("result_sha256")==CANONICAL_REVIEW_PIN["sha256"]
          and independent.get("complete_native_result_bytes_independently_checked") is True
          and independent.get("actual_status")=="canonical_snapshot_closure_verified"
          and independent.get("provided_objects_verified")==395 and independent.get("canonical_commits")==7
          and independent.get("required_existing_exact_set")==16082
          and independent.get("git_head_tree_index_refs_before_after_equal") is True
          and independent.get("source_worktree_physical_inventory_examined") is False
          and independent.get("native_import") is False and independent.get("Cargo") is False
          and independent.get("qualification") is False,"Root independent actual-result review")
    return review

def load_inventory_module():
    raw=read_input(INVENTORY_MODULE,INVENTORY_PIN,100000)
    write("INVENTORY_DRIVER.original.py",raw)
    module=types.ModuleType("hepta_frozen_source_inventory_v2")
    module.__file__=str(INVENTORY_MODULE)
    # Execute only the already hashed original bytes; no reopening race.
    # __name__ is not __main__, so the original main/freeze/gates cannot run.
    exec(compile(raw,str(INVENTORY_MODULE),"exec"),module.__dict__)
    check(callable(module.inventory) and callable(module.require_inventory),"original inventory interfaces")
    return module

def audit_input_stability():
    for name,pin in list(input_pins.items()):
        raw=regular_read(name,max(40000000,pin["bytes"]))
        if len(raw)!=pin["bytes"] or sha256(raw)!=pin["sha256"] or oid("blob",raw)!=pin["git_blob"]:
            raise InputChanged("exact input changed: "+name)
    return True

def close_batches():
    issues=[]
    for obj in (target_batch,source_batch):
        if obj is not None and not obj.closed:
            try:obj.close()
            except BaseException as error:issues.append(obj.name+": "+repr(error))
    return issues

def retain_final_record():
    result["finished_at"]=now()
    result["last_phase"]=phase
    result["source_repo_unmodified"]=source_unmodified
    result["no_automatic_retry"]=True
    result["new_directory_disposition"]="Preserve any partial new directory; do not overwrite, rename, or automatically rerun. Reconcile only this original execution identity."
    jwrite("COMMANDS.json",commands)
    jwrite("INPUT_IDENTITIES.json",input_pins)
    journal=regular_read(OUT/"EVENTS.jsonl",10000000) if (OUT/"EVENTS.jsonl").exists() else b""
    if journal:
        artifacts.append({"name":"EVENTS.jsonl","bytes":len(journal),"sha256":sha256(journal),"git_blob":oid("blob",journal)})
    jwrite("ARTIFACTS.json",{"artifacts":list(artifacts),"terminal_report":"RESULT.json",
                             "terminal_report_self_hash_not_included":True})
    result["artifacts"]=list(artifacts)
    # Actual normal supervisor exit 0 is also required; a RESULT file alone
    # is never sufficient if a later record/readback/terminal step failed.
    jwrite("RESULT.json",result)
    print(json.dumps({"event":"materialization_terminal","status":result["status"],
                      "source_commit":PREPARED,"source_tree":PREPARED_TREE,
                      "source_repo_unmodified":source_unmodified,
                      "new_repo_created":target_created,"qualification":False,
                      "maintenance_started":False,"cargo_or_tests_started":False,
                      "out":str(OUT)},sort_keys=True),flush=True)


def final_source_audit():
    global source_unmodified
    if result.get("source_before_verified") is not True:
        return {"status":"not_run","reason":"complete source preflight did not finish; no source-unchanged claim"}
    after_inventory=inventory_module.inventory(SOURCE)
    gzrecord("SOURCE.after.inventory.json.gz",after_inventory)
    if after_inventory!=before_inventory:
        source_unmodified=False
        raise SourceChanged("complete original source physical inventory differs")
    pin_bytes(after_inventory,SOURCE_INVENTORY_PIN,"final original c0f full physical inventory")
    inventory_module.require_inventory(after_inventory,SOURCE_CFG)
    after_git_state=source_git_state()
    jwrite("SOURCE_GIT_STATE.after.json",after_git_state)
    if after_git_state!=before_git_state:
        source_unmodified=False
        raise SourceChanged("source HEAD/tree/index/refs differ")
    after_metadata=metadata_inventory(SOURCE/".git")
    gzrecord("SOURCE_GIT_METADATA.after.json.gz",after_metadata)
    if after_metadata!=before_git_metadata:
        source_unmodified=False
        raise SourceChanged("source complete Git metadata/object files differ")
    source_unmodified=True
    return {"status":"verified","inventory":SOURCE_INVENTORY_PIN,"git_state_equal":True,"git_metadata_equal":True}

def final_destination_audit():
    if not target_created:
        return {"status":"not_run","reason":"new repository was not created"}
    head_path=TARGET/".git"/"HEAD";index_path=TARGET/".git"/"index"
    actual_head=regular_read(head_path,10000) if head_path.exists() else None
    index_raw=regular_read(index_path,40000000) if index_path.exists() else None
    jwrite("TARGET.final-state.json",{
        "head_bytes_base64":base64.b64encode(actual_head).decode("ascii") if actual_head is not None else None,
        "index_bytes":len(index_raw) if index_raw is not None else None,
        "index_sha256":sha256(index_raw) if index_raw is not None else None,
        "import_started":result["import_started"],
        "physical_materialization_started":result["physical_materialization_started"]})
    if actual_head==(PREPARED+"\n").encode("ascii") and index_raw is not None:
        final_inventory=inventory_module.inventory(TARGET)
        gzrecord("TARGET.final.inventory.json.gz",final_inventory)
        if operation_completed:
            expected=result["destination_inventory"]
            if len(final_inventory)!=expected["bytes"] or sha256(final_inventory)!=expected["sha256"] or oid("blob",final_inventory)!=expected["git_blob"]:
                raise DestinationChanged("new complete physical/index/HEAD inventory changed after verification")
            inventory_module.require_inventory(final_inventory,TARGET_CFG)
        return {"status":"verified" if operation_completed else "partial_state_retained",
                "inventory_bytes":len(final_inventory),"inventory_sha256":sha256(final_inventory)}
    if operation_completed:
        raise DestinationChanged("new detached HEAD/index disappeared")
    return {"status":"partial_state_retained","full_inventory_unavailable":"HEAD/index not yet established"}

def final_input_audit():
    audit_input_stability()
    result["inputs_unchanged"]=True
    return {"status":"verified","input_count":len(input_pins)}

def final_close_audit():
    issues=close_batches()
    if issues:
        raise RuntimeError("; ".join(issues))
    return {"status":"verified","owned_cat_file_helpers_closed":True}

def main():
    global out_created,inventory_module,before_inventory,before_git_state,before_git_metadata
    global source_batch,operation_completed,source_unmodified,canonical_order,all_maps
    result["started_at"]=now()
    check_real_parents(EVIDENCE)
    check_real_parents(SOURCE)
    check_real_parents(TARGET.parent)
    check(not os.path.lexists(OUT),"existing run directory; reconcile, never overwrite or retry")
    os.mkdir(OUT,0o700);out_created=True
    signal.signal(signal.SIGALRM,timeout_handler)
    signal.alarm(IMPORT_SECONDS)
    try:
        enter("preconditions")
        sanitize_git_environment()
        check(not os.path.lexists(TARGET),"target exists; no overwrite/rename/retry")
        review=validate_approval_and_proofs()
        inventory_module=load_inventory_module()
        before_git_state=source_git_state()
        jwrite("SOURCE_GIT_STATE.before.json",before_git_state)
        check(before_git_state==review["source_git_state_after"],"actual source Git state differs from successful canonical review")
        before_inventory=inventory_module.inventory(SOURCE)
        gzrecord("SOURCE.before.inventory.json.gz",before_inventory)
        result["observed_source_before_inventory"]={"bytes":len(before_inventory),"sha256":sha256(before_inventory),"git_blob":oid("blob",before_inventory)}
        pin_bytes(before_inventory,SOURCE_INVENTORY_PIN,"actual original c0f full physical inventory")
        inventory_module.require_inventory(before_inventory,SOURCE_CFG)
        before_git_metadata=metadata_inventory(SOURCE/".git")
        gzrecord("SOURCE_GIT_METADATA.before.json.gz",before_git_metadata)
        result["source_before_verified"]=True
        enter("packet_validation")
        packet395,manifest395,objects395=load_canonical()
        packet87,manifest87,objects87=load_prepared()
        canonical_order=packet395["canonical_commit_order"]
        enter("complete_snapshot_preflight")
        source_batch=Batch(SOURCE,"source-cat-file")
        final,final_trees,all_maps=verify_graphs(packet395,manifest395,objects395,packet87,manifest87,objects87)
        # The same exact old snapshots are retained for future --base c0f diff.
        # Original parent links remain; older history is not traversed or forged.
        history=[]
        for value in (B298,C0F):
            fields=commit_fields(retained_existing_raw[value])
            history.append({"commit":value,"original_parents":fields["parents"],
                            "parents_outside_import_scope":[p for p in fields["parents"] if p not in import_index]})
        jwrite("HISTORY_SCOPE.json",{"boundary_commits":history,"full_history_verified":False,
                                    "shallow_grafts_replace_created":False,"fmt_base_full_snapshot":C0F})
        audit_input_stability()
        check(source_git_state()==before_git_state,"source Git state changed before target creation")
        disk_requirement(final)
        enter("create_and_import_new_repository")
        create_and_import()
        enter("new_object_database_readback")
        verify_new_object_database()
        enter("materialize_exact_tree")
        physical_materialization(final)
        event("preparation_materialization_completed",leaf_count=15188,tests_run=0)
        operation_completed=True
    except PreconditionError as error:
        result.update(status="HOLD_PRECONDITION",error=type(error).__name__+": "+str(error),failure_phase=phase,traceback=traceback.format_exc())
    except (TimeoutError,subprocess.TimeoutExpired,KeyboardInterrupt) as error:
        result.update(status="UNKNOWN",error=type(error).__name__+": "+str(error),failure_phase=phase,traceback=traceback.format_exc())
    except BaseException as error:
        result.update(status="FAILED_PREPARATION",error=type(error).__name__+": "+str(error),failure_phase=phase,traceback=traceback.format_exc())
    finally:
        signal.alarm(0)
        # Independent final comparisons retain all available evidence. A
        # failed source check does not suppress a possible target/inputs read.
        final_deadline=time.monotonic()+FINAL_RECORD_SECONDS
        final_issues=[];final_reports=[]
        checks=[("close_owned_helpers",final_close_audit),("original_source",final_source_audit),
                ("new_destination",final_destination_audit),("original_inputs",final_input_audit)]
        final_timed_out=False
        for name,action in checks:
            remaining=final_deadline-time.monotonic()
            if final_timed_out or remaining<=0:
                final_timed_out=True
                final_reports.append({"check":name,"status":"unknown_not_attempted","reason":"final evidence deadline"})
                continue
            signal.alarm(max(1,int(remaining+0.999)))
            report={"check":name,"started_at":now(),"status":"attempted"}
            try:
                report.update(action())
            except (SourceChanged,InputChanged,DestinationChanged) as error:
                report.update(status="failed_integrity",error=type(error).__name__+": "+str(error),traceback=traceback.format_exc())
                final_issues.append(report["error"])
            except (TimeoutError,subprocess.TimeoutExpired,KeyboardInterrupt) as error:
                report.update(status="unknown",error=type(error).__name__+": "+str(error),traceback=traceback.format_exc())
                final_issues.append(report["error"]);final_timed_out=True
            except BaseException as error:
                report.update(status="unknown",error=type(error).__name__+": "+str(error),traceback=traceback.format_exc())
                final_issues.append(report["error"])
            finally:
                signal.alarm(0)
            report["finished_at"]=now();final_reports.append(report)
        result["final_audits"]=final_reports
        if final_issues or final_timed_out:
            result["final_audit_issues"]=final_issues
            result["status"]="UNKNOWN" if final_timed_out or any(x["status"]=="unknown" for x in final_reports) else "FAILED_INTEGRITY"
        elif operation_completed and source_unmodified is True:
            result["status"]="MATERIALIZED_FOR_MAINTENANCE_ONLY"
        elif operation_completed:
            result["status"]="UNKNOWN"
        try:
            retain_final_record()
        except BaseException as error:
            result["status"]="UNKNOWN"
            result["record_retention_error"]=repr(error)
            print(json.dumps({"event":"final_record_error","status":"UNKNOWN","error":repr(error),
                              "new_repo_created":target_created,"out":str(OUT),"maintenance_started":False},sort_keys=True),flush=True)
    return 0 if result["status"]=="MATERIALIZED_FOR_MAINTENANCE_ONLY" else 1

if __name__ == "__main__":
    try:
        exit_code=main()
    except BaseException as error:
        print(json.dumps({"event":"admission_rejected_or_unknown","status":"UNKNOWN","error":repr(error),
                          "new_repo_created":target_created,"out_created":out_created,
                          "target":str(TARGET),"automatic_retry":False},sort_keys=True),flush=True)
        exit_code=1
    sys.exit(exit_code)
