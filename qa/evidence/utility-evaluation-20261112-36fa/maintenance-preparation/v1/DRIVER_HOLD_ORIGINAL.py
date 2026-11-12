#!/usr/bin/env python3
"""Preparation-only control for original scoped just fix/fmt, after exact materialization.
No test commands, ref updates, source resets, automatic retries, or tool installation.
This driver must be separately approved by Root/native before a single launch.
"""
from __future__ import annotations
import base64, datetime, gzip, hashlib, json, os, pathlib, shutil, signal, stat
import subprocess, sys, tempfile, time, traceback, types

REPO=pathlib.Path("/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1")
EVIDENCE=pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1")
OUT=EVIDENCE/"run"
CONFIG=EVIDENCE/"APPROVED_CONFIG.json"
INVENTORY_FILE=EVIDENCE/"inventory-driver-v2.py"
ENVIRONMENT_FILE=EVIDENCE/"MAINTENANCE_STARTED.original.json"
GIT="/usr/bin/git"
HEAD="86dd56a930277e0d1aef3e475e35c2b5d60b43b7"
TREE="383ab85c39ef9d848252ef5c25922d13d9fae6c6"
C0F="c0f78493f815780f68b9bf5e390a21314d79311f"
C0F_TREE="313ee34febc8ccc54c611ab56286e289518c63cb"
A96="a96d1b821d10ed3d9e99dd06c5141f9f242ae318"
PARENTS=[C0F,A96]
LEAVES=15188
TARGET=pathlib.Path("/data/hepta-utility-36fa-final-native-target-v1")
FIX=["just","fix","-p","codex-hepta-intelligence-eval","-p","codex-hepta-agentd"]
FMT=["just","fmt","--base",C0F]
FIX_SECONDS=7200
FMT_SECONDS=900
MAXIMUM_LOG_BYTES=64*1024*1024
PREFLIGHT_SECONDS=600
RECORD_SECONDS=300
INVENTORY_PIN={"bytes":22946,"sha256":"20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2","git_blob":"51181866cbbb6e0176aab04117efffa8b6792b31"}
HISTORICAL_ENV_PIN={"bytes":1154,"sha256":"f9372b818186526929ae25be698d108a4fee17d6612a18f36b8e950172c02ce1","git_blob":"69a3d38ff1cf800813f1fbf1f30bca224157f223"}
SOURCE_PINS=[
    {
        "path": "AGENTS.md",
        "bytes": 22519,
        "sha256": "c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480",
        "git_blob": "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a"
    },
    {
        "path": "justfile",
        "bytes": 7838,
        "sha256": "74f869224eba12fc4212b043428e7f5b35b551d26f5b06161c25d8aca525f124",
        "git_blob": "a215a76cf407ace9715bca39c20497014e7dd4dc"
    },
    {
        "path": "scripts/format.py",
        "bytes": 16599,
        "sha256": "8d93d7a6261bbe5f2b9fceea228154f0be29f721015d05b4f538c30076dd80b3",
        "git_blob": "d4eabe70b68605933240e9129245f7f4cccbde5d"
    },
    {
        "path": "scripts/hepta_ci_exec.py",
        "bytes": 12863,
        "sha256": "9b2bfaa563fff018df4e4f10944f6fbc63d307fa4c4a7e167c392288edb5a5c1",
        "git_blob": "c9434b3a4afb31f80e323d543936386a2fa738de"
    },
    {
        "path": "scripts/just-shell.py",
        "bytes": 2030,
        "sha256": "444d6b328d44abf6453b77b6acce2a0c881fc162ff30b20f352c85067797fbe9",
        "git_blob": "bb2db6ebc4312a301ee39d2793fde16289d046d8"
    },
    {
        "path": "codex-rs/rust-toolchain.toml",
        "bytes": 78,
        "sha256": "e8b379eaa492bf59d35187de269afd1c4f55d85e0322f6fea32803a3fec1a380",
        "git_blob": "917d2492264a35bc9c0feaef41878d8825870866"
    }
]
ORIGINAL_ENVIRONMENT={
    "CARGO_BUILD_JOBS": "2",
    "CARGO_HOME": "/home/qian-qi/.cargo",
    "CARGO_INCREMENTAL": "0",
    "CARGO_NET_OFFLINE": "true",
    "CARGO_PROFILE_DEV_DEBUG": "0",
    "CARGO_PROFILE_TEST_DEBUG": "0",
    "CARGO_TARGET_DIR": "/home/qian-qi/hepta-utility-36fa-target",
    "PATH": "/home/qian-qi/hepta-learn-037c-tools/nextest-0.9.103-e999c122:/home/qian-qi/.cargo/bin:/usr/local/bin:/usr/bin:/bin",
    "RUSTUP_HOME": "/home/qian-qi/.rustup",
    "RUSTUP_TOOLCHAIN": "1.96.0",
    "RUSTY_V8_ARCHIVE": "/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/live-owners-full-c6a61dfb57cb-v1/v8-private-pins/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz",
    "RUSTY_V8_SRC_BINDING_PATH": "/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/live-owners-full-c6a61dfb57cb-v1/v8-private-pins/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs"
}
UV_KEYS=("UV_PROJECT_ENVIRONMENT","UV_CACHE_DIR","UV_OFFLINE","RUFF_CACHE_DIR")
EXPECTED={"source_sha":HEAD,"source_tree":TREE}
artifacts=[]
events=[]
commands=[]
input_pins={}
cfg=None
inventory_module=None
execute_module=None
initial_inventory=None
latest_inventory=None
initial_git_state=None
initial_git_metadata=None
initial_environment=None
raw_cache={}
attempted=[]
result={"format":"hepta-original-scoped-maintenance-result-v1","status":"HOLD",
        "source_repo":str(REPO),"source_commit":HEAD,"source_tree":TREE,"parents":PARENTS,
        "test_commands_dispatched":0,"qualification":False,"source_ref_updates":False,
        "automatic_retry":False,"cargo_target":str(TARGET),"stages":[],
        "budget_scope":"Original commands: fix 7200 seconds, fmt 900 seconds. Separate preparation/evidence overhead is not a test/source-gate budget."}

class PreconditionError(RuntimeError): pass
class IntegrityError(RuntimeError): pass


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


def pin_bytes(raw,pin,label):
    check(isinstance(pin,dict) and set(("bytes","sha256","git_blob")) <= set(pin),
          "incomplete exact pin: "+label)
    check(len(raw)==pin["bytes"] and sha256(raw)==pin["sha256"] and oid("blob",raw)==pin["git_blob"],
          "exact byte identity: "+label)
    return raw

def read_input(path,pin,maximum=40000000):
    path=pathlib.Path(path)
    raw=regular_read(path,maximum)
    pin_bytes(raw,pin,str(path))
    input_pins[str(path)]={k:pin[k] for k in ("bytes","sha256","git_blob")}
    return raw

def real_directory(path):
    path=pathlib.Path(path)
    check(path.is_absolute(),"absolute directory required")
    current=pathlib.Path(path.anchor)
    for part in path.parts[1:]:
        current=current/part
        info=current.lstat()
        check(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
              "non-real directory: "+str(current))

def external_directory(path,label,allow_create=False):
    value=pathlib.Path(path)
    check(value.is_absolute() and str(value)==os.path.normpath(str(value)),
          label+" must be a canonical absolute path")
    check(not value.is_relative_to(REPO) and not REPO.is_relative_to(value)
          and not value.is_relative_to(OUT),label+" is not outside source/evidence run")
    if not os.path.lexists(value):
        check(allow_create,label+" absent; explicit create-only approval is required")
        real_directory(value.parent)
        os.mkdir(value,0o700)
        event("approved_external_directory_created",path=str(value),purpose=label)
    real_directory(value)
    check(os.access(value,os.R_OK|os.W_OK|os.X_OK),label+" not accessible")
    info=value.lstat()
    disk=shutil.disk_usage(value)
    return {"path":str(value),"device":info.st_dev,"inode":info.st_ino,
            "mode":stat.S_IMODE(info.st_mode),"uid":info.st_uid,
            "disk_total":disk.total,"disk_used":disk.used,"disk_free":disk.free}

def run_readonly(argv,timeout=30):
    entry={"argv":list(argv),"started_at":now(),"purpose":"read-only preflight/evidence"}
    commands.append(entry)
    p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                     timeout=timeout,check=False,cwd=REPO)
    entry.update(returncode=p.returncode,finished_at=now(),
                 stdout_bytes=len(p.stdout),stdout_sha256=sha256(p.stdout),
                 stderr_bytes=len(p.stderr),stderr_sha256=sha256(p.stderr))
    write("readonly-%03d.stdout"%len(commands),p.stdout)
    write("readonly-%03d.stderr"%len(commands),p.stderr)
    check(p.returncode==0,"read-only command failure: "+repr(argv))
    return p.stdout

def git(*args):
    return run_readonly([GIT,"--no-optional-locks","-c","core.fsmonitor=false",
                         "-c","core.untrackedCache=false","-C",str(REPO),*args],120)

def git_state():
    real_directory(REPO/".git")
    check(git("rev-parse","--absolute-git-dir").decode().strip()==str(REPO/".git")
          and git("rev-parse","--path-format=absolute","--git-common-dir").decode().strip()==str(REPO/".git"),
          "independent actual maintenance repository")
    check(not os.path.lexists(REPO/".git"/"objects"/"info"/"alternates"),
          "new maintenance source must remain independent of alternates")
    check(not os.path.lexists(REPO/".git"/"shallow") and
          not os.path.lexists(REPO/".git"/"info"/"grafts"),"no synthetic history boundary")
    head=regular_read(REPO/".git"/"HEAD",1000)
    index=regular_read(REPO/".git"/"index",40000000)
    config=regular_read(REPO/".git"/"config",1000000)
    refs=git("for-each-ref","--format=%(refname) %(objectname)")
    check(head==(HEAD+"\n").encode() and not refs,"unchanged detached HEAD/no refs")
    check(git("rev-parse","HEAD").decode().strip()==HEAD
          and git("rev-parse","HEAD^{tree}").decode().strip()==TREE,"exact preparation commit/tree")
    return {"head_raw_sha256":sha256(head),"head":HEAD,"tree":TREE,
            "index_bytes":len(index),"index_sha256":sha256(index),
            "config_bytes":len(config),"config_sha256":sha256(config),
            "refs_bytes":len(refs),"refs_sha256":sha256(refs)}

def verify_original_inputs():
    for path,pin in list(input_pins.items()):
        pin_bytes(regular_read(path,max(40000000,pin["bytes"])),pin,path)
    return {"input_count":len(input_pins),"unchanged":True}

def load_module(path,pin,name):
    raw=read_input(path,pin)
    module=types.ModuleType(name)
    module.__file__=str(path)
    # The exact original bytes are executed only to define their functions.
    # A non-main module name prevents the original CLI and gate wrappers.
    exec(compile(raw,str(path),"exec"),module.__dict__)
    return module

def parse_supervisor(raw):
    outer=parse(raw)
    check(("resultType" not in outer or outer["resultType"]=="complete")
          and outer.get("isError") is False and len(outer.get("content",[]))==1
          and outer["content"][0].get("type")=="text","actual terminal SDK envelope")
    terminal=parse(outer["content"][0]["text"].encode())
    check(terminal.get("state")=="succeeded" and terminal.get("exit_code")==0
          and terminal.get("timed_out") is False and terminal.get("cancelled") is False
          and terminal.get("automatic_retry") is False
          and terminal.get("output_complete") is True and terminal.get("output_durable") is True
          and terminal.get("terminal_publication_confirmed") is True
          and not any(terminal.get("log_truncated",{}).values()),"actual complete normal supervisor terminal")
    return terminal

def validate_materialization():
    materialization=cfg.get("materialization")
    check(isinstance(materialization,dict),"actual materialization proof required")
    source=read_input(materialization["result_path"],materialization["result"])
    terminal_raw=read_input(materialization["supervisor_path"],materialization["supervisor"])
    observed=parse(source);terminal=parse_supervisor(terminal_raw)
    check(terminal.get("job_id")==materialization["job_id"],"actual materialization job")
    check(observed.get("format")=="hepta-fresh-source-materialization-result-v2"
          and observed.get("status")=="MATERIALIZED_FOR_MAINTENANCE_ONLY"
          and observed.get("target_repo")==str(REPO)
          and observed.get("source_commit")==HEAD and observed.get("source_tree")==TREE
          and observed.get("parents")==PARENTS,"exact successful materialization identity")
    for key in ("new_repo_created","import_started","physical_materialization_started",
                "source_before_verified","source_repo_unmodified","source_object_lookup_unchanged","inputs_unchanged"):
        check(observed.get(key) is True,"materialization actual "+key)
    for key in ("maintenance_started","cargo_or_tests_started","qualification","remote_ref_updates"):
        check(observed.get(key) is False,"materialization absence of "+key)
    check(observed.get("materialized")=={"head":HEAD,"tree":TREE,"index_equals_tree":True,
          "physical_bytes_equal":True,"detached":True,"maintenance_or_tests_started":False,"qualification":False},
          "complete original materialized physical/index identity")
    check({x["check"]:x["status"] for x in observed["final_audits"]}==
          {"close_owned_helpers":"verified","original_source":"verified",
           "original_source_object_lookup":"verified","new_destination":"verified","original_inputs":"verified"},
          "all actual materialization final audits")
    expected=cfg.get("source_inventory")
    check(all(observed["destination_inventory"].get(k)==expected.get(k)
              for k in ("bytes","sha256","git_blob")) and
          observed["destination_inventory"].get("tracked_entries")==LEAVES and
          observed["destination_inventory"].get("filesystem_entries")==LEAVES,
          "approved exact complete physical source inventory")
    write("MATERIALIZATION_RESULT.original.json",source)
    write("MATERIALIZATION_SUPERVISOR.original.json",terminal_raw)
    return observed

def active_build_processes():
    active=[];unreadable=[]
    for item in pathlib.Path("/proc").iterdir():
        if not item.name.isdecimal():continue
        try:
            name=(item/"comm").read_text().strip()
            if name not in ("cargo","cargo-clippy","clippy-driver","rustc","rustfmt","just","uv","ruff"):
                continue
            status=(item/"status").read_text()
            uid_line=next(x for x in status.splitlines() if x.startswith("Uid:"))
            uid=int(uid_line.split()[1])
            if uid!=os.getuid():continue
            active.append({"pid":int(item.name),"comm":name,"uid":uid})
        except FileNotFoundError:
            continue
        except (OSError,StopIteration,ValueError) as error:
            unreadable.append({"pid":int(item.name),"error":type(error).__name__})
    return {"active_matching_processes":active,"unreadable_matching_processes":unreadable,
            "scope":"Same-UID process names only; no environment/argument values or credentials inspected; no processes killed."}

def installed_file_observation(path,label):
    path=pathlib.Path(path)
    check(path.is_absolute() and path.is_file(),label+" actual existing file required")
    resolved=path.resolve(strict=True)
    before=resolved.stat()
    digest=hashlib.sha256()
    with resolved.open("rb") as f:
        for block in iter(lambda:f.read(1048576),b""):digest.update(block)
    after=resolved.stat()
    check((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
          (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
          label+" changed while reading")
    return {"path":str(path),"resolved":str(resolved),"bytes":before.st_size,
            "sha256":digest.hexdigest(),"mode":stat.S_IMODE(before.st_mode)}

def environment_preflight():
    historical=parse(read_input(ENVIRONMENT_FILE,HISTORICAL_ENV_PIN,100000))
    check(historical["environment"]==ORIGINAL_ENVIRONMENT,"original historical environment bytes/fields")
    desired=dict(ORIGINAL_ENVIRONMENT);desired["CARGO_TARGET_DIR"]=str(TARGET)
    check(cfg.get("environment")==desired,"only approved target differs in the original environment map")
    # Extra formatter environment is inherited, observed and separately approved;
    # no UV/Ruff variable is silently added or changed here.
    observed_uv={name:os.environ.get(name) for name in UV_KEYS}
    jwrite("FORMATTER_ENVIRONMENT.observed.json",observed_uv)
    check(cfg.get("observed_formatter_environment")==observed_uv,
          "Root must freeze the actual formatter environment")
    for key,value in desired.items():os.environ[key]=value
    os.environ["GIT_OPTIONAL_LOCKS"]="0"
    os.environ["PYTHONDONTWRITEBYTECODE"]="1"
    sys.dont_write_bytecode=True
    check(not any(os.environ.get(x) for x in
          ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE","GIT_OBJECT_DIRECTORY",
           "GIT_ALTERNATE_OBJECT_DIRECTORIES","GIT_SHALLOW_FILE","GIT_REPLACE_REF_BASE")),
          "no inherited Git identity/object overrides")
    tools={}
    for name in ("git","just","python3","rustup","cargo","uv"):
        resolved=shutil.which(name)
        check(resolved is not None,"required actual tool missing: "+name)
        tools[name]=installed_file_observation(resolved,"actual tool "+name)
    check(cfg.get("tool_files")==tools,"Root must freeze actual pre-installed tool identities")
    # Read-only version discovery does not run uv sync, uv run or a formatter.
    tool_versions={}
    for name in ("just","uv"):
        tool_versions[name]=run_readonly([tools[name]["path"],"--version"]).decode("utf-8","replace")
    tool_versions["rustup_toolchains"]=run_readonly([tools["rustup"]["path"],"toolchain","list"]).decode("utf-8","replace")
    check(any(line.startswith("1.96.0-") for line in tool_versions["rustup_toolchains"].splitlines()),
          "actual pre-installed original Rust toolchain unavailable")
    target=external_directory(TARGET,"exclusive CARGO_TARGET_DIR",cfg.get("create_target_if_absent") is True)
    minimum=cfg.get("minimum_target_free_bytes")
    check(type(minimum) is int and minimum>0 and target["disk_free"]>=minimum,
          "approved actual target free-space precondition")
    check(cfg.get("create_target_if_absent") in (True,False),"explicit target creation policy")
    v8={}
    for key in ("RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH"):
        v8[key]=installed_file_observation(desired[key],key)
    check(cfg.get("v8_files")==v8,"Root must freeze the actual existing V8 pair identities")
    project=observed_uv["UV_PROJECT_ENVIRONMENT"]
    ruff_cache=observed_uv["RUFF_CACHE_DIR"]
    check(isinstance(project,str) and project and isinstance(ruff_cache,str) and ruff_cache,
          "pre-held external uv environment and Ruff cache require explicit existing environment")
    formatter_dirs={"project":external_directory(project,"original uv project environment"),
                    "ruff_cache":external_directory(ruff_cache,"original Ruff cache")}
    if observed_uv["UV_CACHE_DIR"] is not None:
        formatter_dirs["uv_cache"]=external_directory(observed_uv["UV_CACHE_DIR"],"original uv cache")
    formatter_tools={name:installed_file_observation(pathlib.Path(project)/"bin"/name,"external formatter "+name)
                     for name in ("python","ruff")}
    check(cfg.get("formatter_tool_files")==formatter_tools,"Root must freeze actual external formatter tool identities")
    active=active_build_processes()
    check(not active["active_matching_processes"] and not active["unreadable_matching_processes"],
          "active/unknown same-UID Cargo/formatter process; no competing maintenance")
    record={"historical_environment":HISTORICAL_ENV_PIN,"effective_original_map":desired,
            "only_original_map_override":"CARGO_TARGET_DIR","inherited_formatter_environment":observed_uv,
            "tools":tools,"tool_versions":tool_versions,"v8_files":v8,"target":target,
            "formatter_directories":formatter_dirs,"formatter_tools":formatter_tools,"process_observation":active,
            "tool_or_dependency_installation_commands_executed":False,
            "limitation":"Existing tool/path preflight does not prove frozen uv resolution or future formatting succeeds."}
    jwrite("ENVIRONMENT_PREFLIGHT.json",record)
    return record


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


def actual_leaf_map(data):
    value=parse(data);leaves={}
    for row in value["files"]:
        if row["kind"]=="missing":continue
        check(row.get("stable") is True and row["kind"] in ("file","symlink"),
              "unsupported/unstable physical source leaf: "+row["path"])
        mode="120000" if row["kind"]=="symlink" else ("100755" if row["permissions"] & 0o111 else "100644")
        relative=pathlib.PurePosixPath(row["path"])
        check(not relative.is_absolute() and all(x not in ("",".","..",".git") for x in relative.parts),
              "safe exact physical source path")
        leaves[row["path"]]={"mode":mode,"sha":row["working_blob"],"bytes":row["bytes"],"sha256":row["sha256"]}
    return leaves

def merkle(leaves):
    root={}
    for path,row in leaves.items():
        node=root;parts=path.split("/")
        for part in parts[:-1]:
            check(not isinstance(node.get(part),tuple),"physical file/directory conflict")
            node=node.setdefault(part,{})
        check(parts[-1] not in node,"duplicate physical tree leaf")
        node[parts[-1]]=(row["mode"],row["sha"])
    def build(node):
        entries=[]
        for name,item in node.items():
            if isinstance(item,dict):mode,value="40000",build(item)
            else:mode,value=item
            raw_name=name.encode("utf-8")
            entries.append((raw_name+(b"/" if mode=="40000" else b""),mode.encode()+b" "+raw_name+b"\0"+bytes.fromhex(value)))
        return oid("tree",b"".join(x[1] for x in sorted(entries,key=lambda x:x[0])))
    return build(root)

class OriginalBlobReader:
    def __init__(self,name):
        self.name=name;self.closed=False
        self.stderr_path=OUT/(name+".stderr")
        self.stderr=self.stderr_path.open("xb")
        self.command={"argv":[GIT,"--no-optional-locks","-C",str(REPO),"cat-file","--batch"],"started_at":now()}
        commands.append(self.command)
        self.p=subprocess.Popen(self.command["argv"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr)
    def get(self,value):
        self.p.stdin.write((value+"\n").encode());self.p.stdin.flush()
        header=self.p.stdout.readline(512).rstrip(b"\n").split(b" ")
        check(len(header)==3 and header[0].decode()==value and header[1]==b"blob","available original preimage blob")
        size=int(header[2]);check(0<=size<=1073741824,"bounded original preimage")
        pieces=[];left=size
        while left:
            part=self.p.stdout.read(min(1048576,left))
            check(part,"short original preimage");pieces.append(part);left-=len(part)
        raw=b"".join(pieces)
        check(self.p.stdout.read(1)==b"\n" and oid("blob",raw)==value,"original preimage raw Git identity")
        return raw
    def close(self):
        if self.closed:return
        self.closed=True
        try:
            self.p.stdin.close();rc=self.p.wait(timeout=10)
            self.command.update(returncode=rc,finished_at=now())
            check(rc==0,"original cat-file read helper terminal")
        except BaseException:
            self.p.kill();self.p.wait(timeout=10)
            raise
        finally:
            self.stderr.close()
            raw=regular_read(self.stderr_path,1000000)
            artifacts.append({"name":self.stderr_path.name,"bytes":len(raw),"sha256":sha256(raw),"git_blob":oid("blob",raw)})

def read_actual_leaf(path,row):
    full=REPO/path
    if row["kind"]=="symlink":
        raw=os.fsencode(os.readlink(full))
    else:
        raw=regular_read(full,max(40000000,row["bytes"]))
    check(len(raw)==row["bytes"] and sha256(raw)==row["sha256"] and oid("blob",raw)==row["working_blob"],
          "actual postimage differs from its full inventory: "+path)
    return raw

def archive_transition(name,before,after):
    b={x["path"]:x for x in parse(before)["files"]}
    a={x["path"]:x for x in parse(after)["files"]}
    changes=[];reader=None
    try:
        for path in sorted(set(b)|set(a)):
            previous=b.get(path);current=a.get(path)
            if previous==current:continue
            old=None;new=None
            if previous is not None and previous["kind"]!="missing":
                check(previous["kind"] in ("file","symlink") and previous.get("stable") is True,
                      "supported stable previous source leaf")
                value=previous["working_blob"]
                old=raw_cache.get(value)
                if old is None:
                    check(previous.get("matches_index") is True,"missing exact previous retained postimage: "+path)
                    if reader is None:reader=OriginalBlobReader(name+"-preimages")
                    old=reader.get(value)
                check(len(old)==previous["bytes"] and sha256(old)==previous["sha256"] and oid("blob",old)==value,
                      "exact before bytes for "+path)
            if current is not None and current["kind"]!="missing":
                check(current["kind"] in ("file","symlink") and current.get("stable") is True,
                      "supported stable actual source leaf")
                new=read_actual_leaf(path,current)
                raw_cache[current["working_blob"]]=new
            changes.append({"path":path,"before":previous,"after":current,
                            "before_raw_base64":None if old is None else base64.b64encode(old).decode("ascii"),
                            "after_raw_base64":None if new is None else base64.b64encode(new).decode("ascii")})
    finally:
        if reader is not None:reader.close()
    packet={"format":"hepta-maintenance-actual-source-transition-v1","stage":name,
            "source_commit_unchanged":HEAD,"base_inventory_sha256":sha256(before),
            "after_inventory_sha256":sha256(after),"changes":changes,
            "all_physical_changes_including_untracked_or_ignored_are_recorded":True,
            "qualification":False}
    gzrecord(name+".postimages.json.gz",jbytes(packet))
    patch=git("diff","--binary","--full-index","--no-ext-diff","--no-textconv",
              "--no-renames","HEAD","--")
    write(name+".HEAD-working.patch",patch)
    source_map=actual_leaf_map(after)
    observation={"change_count":len(changes),"paths":[x["path"] for x in changes],
                 "all_actual_physical_leaf_count":len(source_map),"all_actual_physical_tree":merkle(source_map),
                 "tree_scope":"Every supported physical source leaf, including untracked/ignored files; no Git tree/ref was written.",
                 "HEAD_working_patch_bytes":len(patch),"HEAD_working_patch_sha256":sha256(patch),
                 "untracked_are_in_exact_transition_packet":True}
    jwrite(name+".postimages-summary.json",observation)
    return observation

def capture_source(name,before):
    global latest_inventory
    after=inventory_module.inventory(REPO)
    gzrecord(name+".inventory.json.gz",after)
    state=git_state()
    jwrite(name+".git-state.json",state)
    check(state==initial_git_state,"Git HEAD/index/config/refs changed during maintenance")
    summary=archive_transition(name,before,after)
    again=inventory_module.inventory(REPO)
    gzrecord(name+".inventory-after-retention.json.gz",again)
    check(after==again,"source changed while exact postimages were being retained")
    latest_inventory=after
    return {"complete":True,"inventory":{"bytes":len(after),"sha256":sha256(after),"git_blob":oid("blob",after)},
            "postimages":summary}

def check_fmt_base():
    raw=git("cat-file","commit",C0F)
    check(oid("commit",raw)==C0F and raw.split(b"\n",1)[0]==("tree "+C0F_TREE).encode(),"authentic original fmt base commit")
    listing=git("ls-tree","-r","-z","--full-tree","--long",C0F_TREE)
    entries=[]
    for row in listing.split(b"\0"):
        if not row:continue
        fields,path=row.split(b"\t",1)
        mode,kind,value,size=fields.split()
        check(kind==b"blob" and mode in (b"100644",b"100755",b"120000")
              and size.isdigit(),"fmt base complete existing snapshot leaf")
        entries.append({"path":path.decode("utf-8"),"mode":mode.decode(),
                        "sha":value.decode(),"bytes":int(size)})
    check(len(entries)==14851 and len({x["path"] for x in entries})==14851,"original complete c0f snapshot leaf count")
    gzrecord("FMT_BASE.complete-leaves.json.gz",jbytes(entries))
    return {"commit":C0F,"tree":C0F_TREE,"leaf_count":len(entries),
            "scope":"Actual complete tree traversal and blob metadata; prior materialization proof pins original raw objects. No recursive history fsck."}

def set_alarm(seconds):
    check(seconds>0,"positive remaining observation budget")
    signal.alarm(max(1,int(seconds+0.999)))

def alarm_handler(signum,frame):
    raise TimeoutError("separate maintenance preflight/evidence budget exhausted")

record_remaining=RECORD_SECONDS

def bounded_record(action):
    global record_remaining
    check(record_remaining>0,"no remaining record budget")
    started=time.monotonic()
    set_alarm(record_remaining)
    try:return action()
    finally:
        signal.alarm(0)
        record_remaining=max(0.0,record_remaining-(time.monotonic()-started))

def stage(name,argv,seconds):
    item={"name":name,"argv":argv,"timeout_seconds":seconds,"maximum_log_bytes":MAXIMUM_LOG_BYTES,
          "working_directory":str(REPO),"started_at":now(),"status":"attempted",
          "command_returned":False,"execution":None,"retention":None,"test_command":False}
    # Validate the previous full physical observation immediately before a new command.
    def prepare_stage():
        actual=inventory_module.inventory(REPO)
        check(actual==latest_inventory,"physical source drift before "+name)
        verify_original_inputs()
        active=active_build_processes()
        jwrite(name+".process-preflight.json",active)
        check(not active["active_matching_processes"] and not active["unreadable_matching_processes"],
              "conflicting or unobservable active build/formatter process")
    bounded_record(prepare_stage)
    attempted.append(name);result["stages"].append(item)
    jwrite(name+".attempt.json",item)
    event("original_maintenance_command_attempted",name=name,argv=argv,timeout_seconds=seconds)
    log=OUT/(name+".raw.log")
    before=latest_inventory
    try:
        # No wrapper signal is armed around Cargo/format. Only the unchanged
        # original execute_logged owns the exact command deadline/process group.
        signal.alarm(0)
        execution=execute_module.execute_logged(argv,log,maximum_bytes=MAXIMUM_LOG_BYTES,timeout_seconds=seconds)
        item["command_returned"]=True;item["execution"]=execution
        jwrite(name+".execute_logged.original.json",execution)
        raw=regular_read(log,MAXIMUM_LOG_BYTES)
        check(len(raw)==execution["log_bytes"] and sha256(raw)==execution["log_sha256"],"original complete raw maintenance log")
        artifacts.append({"name":log.name,"bytes":len(raw),"sha256":sha256(raw),"git_blob":oid("blob",raw)})
        item["raw_log_retained"]=True
        item["execution_outcome"]=("unknown_deadline_or_output_limit" if
            execution["timed_out"] or execution["output_limit_exceeded"] else
            "completed" if execution["returncode"]==0 else "failed")
    except BaseException as error:
        item.update(status="unknown",error=type(error).__name__+": "+str(error),traceback=traceback.format_exc())
        if log.exists():
            try:
                raw=regular_read(log,MAXIMUM_LOG_BYTES)
                artifacts.append({"name":log.name,"bytes":len(raw),"sha256":sha256(raw),"git_blob":oid("blob",raw)})
                item["raw_log_retained"]=True
                item["raw_log_completeness"]="Unknown because original execution did not return a complete result."
            except BaseException as retention_error:item["raw_log_retention_error"]=repr(retention_error)
    finally:
        try:item["retention"]=bounded_record(lambda:capture_source(name+".after",before))
        except BaseException as error:
            item.update(status="unknown",postimage_retention_error=repr(error),postimage_traceback=traceback.format_exc())
        item["finished_at"]=now()
        if item.get("status")!="unknown":
            item["status"]="completed_review_required" if item.get("execution_outcome")=="completed" else (
                "failed" if item.get("execution_outcome")=="failed" else "unknown")
        jwrite(name+".terminal.json",item)
        event("original_maintenance_command_terminal",name=name,status=item["status"],
              command_returned=item["command_returned"],
              command_returncode=None if item["execution"] is None else item["execution"]["returncode"])
    return item["status"]=="completed_review_required"

def validate_config():
    raw=regular_read(CONFIG,1000000);value=parse(raw)
    if (value.get("format")!="hepta-original-scoped-maintenance-approval-v1" or
        value.get("status")!="ROOT_APPROVED_TO_EXECUTE" or value.get("root_execution_approved") is not True):
        raise PreconditionError("HOLD: exact maintenance approval is absent")
    current=regular_read(__file__,200000)
    check(value.get("driver_sha256")==sha256(current) and value.get("driver_git_blob")==oid("blob",current),"approved exact driver")
    check(value.get("source_repo")==str(REPO) and value.get("source_commit")==HEAD and
          value.get("source_tree")==TREE and value.get("parents")==PARENTS,"approved maintenance source identity")
    check(value.get("fix_argv")==FIX and value.get("fmt_argv")==FMT
          and value.get("fix_seconds")==FIX_SECONDS and value.get("fmt_seconds")==FMT_SECONDS,
          "unchanged original scoped maintenance entry and budgets")
    check(value.get("preflight_seconds")==PREFLIGHT_SECONDS and value.get("record_seconds")==RECORD_SECONDS,
          "separate preparation/evidence overhead")
    check(value.get("test_commands_authorized") is False and value.get("remote_ref_updates_authorized") is False,
          "no test/ref scope expansion")
    input_pins[str(CONFIG)]={"bytes":len(raw),"sha256":sha256(raw),"git_blob":oid("blob",raw)}
    input_pins[str(pathlib.Path(__file__))]={"bytes":len(current),"sha256":sha256(current),"git_blob":oid("blob",current)}
    write("ACTUAL_DRIVER.py",current);write("APPROVED_CONFIG.original.json",raw)
    return value


def initial_preflight():
    global cfg,inventory_module,execute_module,initial_inventory,latest_inventory
    global initial_git_state,initial_git_metadata,initial_environment
    cfg=validate_config()
    observed=validate_materialization()
    result["actual_materialization_job"]=cfg["materialization"]["job_id"]
    result["actual_materialization_result"]=cfg["materialization"]["result"]
    inventory_module=load_module(INVENTORY_FILE,INVENTORY_PIN,"hepta_original_inventory_for_maintenance")
    write("INVENTORY_DRIVER.original.py",regular_read(INVENTORY_FILE))
    for pin in SOURCE_PINS:
        raw=read_input(REPO/pin["path"],pin)
        write("SOURCE_ENTRY."+pin["path"].replace("/","__"),raw)
    execute_pin=next(x for x in SOURCE_PINS if x["path"]=="scripts/hepta_ci_exec.py")
    execute_module=load_module(REPO/"scripts"/"hepta_ci_exec.py",execute_pin,"hepta_original_execute_logged_for_maintenance")
    check(callable(execute_module.execute_logged) and callable(inventory_module.inventory)
          and callable(inventory_module.require_inventory),"exact original interfaces available")
    initial_git_state=git_state()
    jwrite("SOURCE_GIT_STATE.before.json",initial_git_state)
    initial_inventory=inventory_module.inventory(REPO)
    gzrecord("SOURCE.before.inventory.json.gz",initial_inventory)
    pin_bytes(initial_inventory,cfg["source_inventory"],"actual initial complete materialized source")
    inventory_module.require_inventory(initial_inventory,EXPECTED)
    initial_leaves=actual_leaf_map(initial_inventory)
    check(len(initial_leaves)==LEAVES and merkle(initial_leaves)==TREE,
          "all actual initial physical leaves reconstruct exact source tree")
    latest_inventory=initial_inventory
    initial_git_metadata=metadata_inventory(REPO/".git")
    gzrecord("SOURCE_GIT_METADATA.before.json.gz",initial_git_metadata)
    result["fmt_base"]=check_fmt_base()
    initial_environment=environment_preflight()
    verify_original_inputs()
    result["source_preflight_complete"]=True
    result["source_initial_inventory"]=cfg["source_inventory"]
    event("maintenance_preflight_completed",source_commit=HEAD,source_tree=TREE,
          physical_leaves=LEAVES,source_tests_started=False)

def finalize_source():
    if (initial_inventory is None or initial_git_state is None or initial_git_metadata is None
        or inventory_module is None):
        return {"status":"not_run","reason":"initial complete source baseline unavailable; no unchanged-source claim"}
    complete=capture_source("final",initial_inventory)
    after_metadata=metadata_inventory(REPO/".git")
    gzrecord("SOURCE_GIT_METADATA.after.json.gz",after_metadata)
    if after_metadata!=initial_git_metadata:
        raise IntegrityError("complete maintenance Git metadata/object files changed")
    check(complete["complete"],"complete final actual source retention")
    result["actual_final_source"]=complete
    result["git_metadata_unchanged"]=True
    return {"status":"verified","complete_final_source":complete,"git_metadata_unchanged":True}

def finalize_inputs():
    return {"status":"verified",**verify_original_inputs()}

def retain_terminal():
    result["finished_at"]=now()
    result["attempted_commands"]=list(attempted)
    result["not_run_commands"]=[name for name in ("fix","fmt") if name not in attempted]
    result["record_seconds_remaining"]=record_remaining
    result["retry_policy"]="No automatic retry, source reset, cache deletion, ref update, or skipped prerequisite. Preserve every actual command, postimage and failure."
    result["qualification"]=False
    jwrite("READONLY_COMMANDS.json",commands)
    jwrite("INPUT_IDENTITIES.json",input_pins)
    if (OUT/"EVENTS.jsonl").exists():
        raw=regular_read(OUT/"EVENTS.jsonl",10000000)
        artifacts.append({"name":"EVENTS.jsonl","bytes":len(raw),"sha256":sha256(raw),"git_blob":oid("blob",raw)})
    jwrite("ARTIFACTS.json",{"files":list(artifacts),"terminal_report":"RESULT.json",
                           "terminal_report_self_hash_not_included":True})
    jwrite("RESULT.json",result)
    print(json.dumps({"event":"scoped_maintenance_terminal","status":result["status"],
                      "attempted_commands":attempted,"source_commit":HEAD,
                      "test_commands_dispatched":0,"qualification":False,"out":str(OUT)},sort_keys=True),flush=True)

def main():
    result["started_at"]=now()
    real_directory(REPO);real_directory(EVIDENCE)
    check(not os.path.lexists(OUT),"existing maintenance run; reconcile original identity, never overwrite/retry")
    os.mkdir(OUT,0o700)
    os.chdir(REPO)
    os.environ["GIT_OPTIONAL_LOCKS"]="0"
    os.environ["PYTHONDONTWRITEBYTECODE"]="1";sys.dont_write_bytecode=True
    signal.signal(signal.SIGALRM,alarm_handler)
    set_alarm(PREFLIGHT_SECONDS)
    try:
        event("scoped_maintenance_preconditions_started")
        initial_preflight()
        signal.alarm(0)
        if not stage("fix",FIX,FIX_SECONDS):
            result["status"]="FAILED_MAINTENANCE" if result["stages"][-1]["status"]=="failed" else "UNKNOWN"
        elif record_remaining<=60:
            result.update(status="UNKNOWN",error="insufficient separate remaining evidence budget; fmt not started")
        elif not stage("fmt",FMT,FMT_SECONDS):
            result["status"]="FAILED_MAINTENANCE" if result["stages"][-1]["status"]=="failed" else "UNKNOWN"
        else:
            result["status"]="MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED"
    except PreconditionError as error:
        result.update(status="HOLD_PRECONDITION",error=repr(error),traceback=traceback.format_exc())
    except IntegrityError as error:
        result.update(status="FAILED_INTEGRITY",error=repr(error),traceback=traceback.format_exc())
    except ValueError as error:
        result.update(status="FAILED_PRECONDITION" if not attempted else "UNKNOWN",
                      error=repr(error),traceback=traceback.format_exc())
    except BaseException as error:
        result.update(status="UNKNOWN",error=repr(error),traceback=traceback.format_exc())
    finally:
        signal.alarm(0)
        audits=[];issues=[]
        for name,action in (("actual_complete_source_and_git",finalize_source),("original_inputs",finalize_inputs)):
            if record_remaining<=0:
                audits.append({"check":name,"status":"unknown_not_attempted","reason":"record budget exhausted"})
                issues.append("record budget exhausted");continue
            report={"check":name,"started_at":now(),"status":"attempted"}
            try:
                report.update(bounded_record(action))
            except IntegrityError as error:
                report.update(status="failed_integrity",error=repr(error),traceback=traceback.format_exc())
                issues.append(report["error"])
            except BaseException as error:
                report.update(status="unknown",error=repr(error),traceback=traceback.format_exc())
                issues.append(report["error"])
            report["finished_at"]=now();audits.append(report)
        result["final_audits"]=audits
        if issues:
            result["status"]="FAILED_INTEGRITY" if all(x["status"]!="unknown" and x["status"]!="unknown_not_attempted" for x in audits) else "UNKNOWN"
            result["final_retention_issues"]=issues
        if result["status"]=="MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED":
            if not all(x["status"]=="verified" for x in audits):
                result["status"]="UNKNOWN"
        try:retain_terminal()
        except BaseException as error:
            result["status"]="UNKNOWN"
            print(json.dumps({"event":"maintenance_terminal_retention_error","status":"UNKNOWN",
                              "error":repr(error),"attempted_commands":attempted,"out":str(OUT)},sort_keys=True),flush=True)
    return 0 if result["status"]=="MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED" else 1

if __name__=="__main__":
    try:exit_code=main()
    except BaseException as error:
        print(json.dumps({"event":"maintenance_admission_rejected_or_unknown","status":"UNKNOWN",
                          "error":repr(error),"attempted_commands":attempted,"automatic_retry":False},sort_keys=True),flush=True)
        exit_code=1
    sys.exit(exit_code)
