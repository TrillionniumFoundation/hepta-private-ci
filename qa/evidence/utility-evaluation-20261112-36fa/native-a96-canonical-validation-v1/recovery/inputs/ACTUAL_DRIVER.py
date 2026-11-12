#!/usr/bin/env python3
"""Evidence-only canonical object validation. No Git writes, checkout or Cargo."""
import base64, datetime, gzip, hashlib, io, json, os, pathlib, re, signal, stat, subprocess, sys, traceback

REPO = pathlib.Path("/home/qian-qi/hepta-utility-36fa-source-gates-c0f78493-v1")
ROOT = pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/a96-canonical-independent-validation-v1")
OUT = ROOT / "validation"
C0F = "c0f78493f815780f68b9bf5e390a21314d79311f"
C0FTREE = "313ee34febc8ccc54c611ab56286e289518c63cb"
B298 = "b29869e856d08db1bfb066116a9c443376ccc57d"
B298TREE = "906546a"  # Full identity is obtained from the pinned original commit and packet base_tree.
TIP = "a96d1b821d10ed3d9e99dd06c5141f9f242ae318"
TIPTREE = "f96bebefbc1e7d8187efadb62f88d524cdd18451"
MANIFEST = {"bytes":286428,"sha256":"33137b5f1d860e8268e73ec9fc1751c70aed0734f502af41a19c6fcb37c502eb","sha":"7781160ffff79c238c5955bd8ca2e320e7ef7c99"}
RAW = {"bytes":12080171,"sha256":"bcecb58bbaf97b6fbd83bb9f9bee9829c902d8c721b52f19aac2160a0a2b8af0","sha":"0d41eafb234db8442e8a4c2514456e33499453d6"}
HEX = re.compile(r"^[0-9a-f]{40}$")
START = datetime.datetime.now(datetime.timezone.utc).isoformat()
result = {"kind":"evidence_only_canonical_validation","started_at":START,"qualification":False,
          "git_object_imported":False,"source_or_ref_write_requested":False,"cargo_or_tests_started":False,
          "historical_fsck_scope":"Not run. The previously observed whole-history fsck exit 3 remains a separate limitation.",
          "scope_correction":"The manifest phrase complete ancestry is not enforced as recursive history completeness. Root authorizes snapshot closure: each prerequisite belongs to pinned b298/c0f snapshots or the two anchors, and the exact 16082 set equals objects needed by seven new snapshots minus provided objects, plus those anchors."}
artifacts = []
commands = []
batch = None
before = None
objects = {}
existing = {}
retained_raw = {}
needed = {}
phase = "starting"
created_out = False

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

def write(name, b):
    p = OUT/name
    check(p.parent == OUT, "output must be one level")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(b)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        raise
    check(regular_read(p, max(40000000,len(b))) == b, "output readback mismatch")
    m = {"name":name,"bytes":len(b),"sha256":sha256(b),"git_blob":oid("blob",b)}
    artifacts.append(m)
    return m

def jbytes(x):
    return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")

def jwrite(name,x):
    return write(name,jbytes(x))

def jgz(name,x):
    raw = jbytes(x)
    gz = gzip.compress(raw,mtime=0)
    check(gzip.decompress(gz) == raw,"gzip roundtrip")
    m = write(name,gz)
    m["raw_bytes"] = len(raw)
    m["raw_sha256"] = sha256(raw)
    m["raw_git_blob"] = oid("blob",raw)
    # Bounded independent chunks make later transport lossless; they are exact gzip slices.
    m["parts"] = []
    for i,off in enumerate(range(0,len(gz),262144)):
        c = gz[off:off+262144]
        cm = write(name+".part-%03d.b64"%(i+1),base64.b64encode(c)+b"\n")
        cm.update({"decoded_offset":off,"decoded_bytes":len(c),"decoded_sha256":sha256(c)})
        m["parts"].append(cm)
    return m

git_env = os.environ.copy()
git_overrides = [name for name in ("GIT_DIR","GIT_WORK_TREE","GIT_INDEX_FILE","GIT_OBJECT_DIRECTORY","GIT_ALTERNATE_OBJECT_DIRECTORIES") if git_env.get(name)]
git_env["GIT_OPTIONAL_LOCKS"] = "0"
GIT = "/usr/bin/git"

def git(args):
    argv = [GIT,"--no-optional-locks","-C",str(REPO),*args]
    commands.append({"argv":argv,"started_at":now(),"read_only":True})
    p = subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=git_env,timeout=60,check=False)
    commands[-1].update({"returncode":p.returncode,"stdout_sha256":sha256(p.stdout),"stderr_sha256":sha256(p.stderr)})
    check(p.returncode == 0, "read-only git command failed: "+repr(args)+" stderr="+p.stderr.decode("utf-8","replace")[:4000])
    return p.stdout

def git_state():
    head = git(["rev-parse","--verify","HEAD"]).decode("ascii").strip()
    tree = git(["rev-parse","--verify","HEAD^{tree}"]).decode("ascii").strip()
    gitdir = pathlib.Path(git(["rev-parse","--absolute-git-dir"]).decode("utf-8").strip())
    index = regular_read(gitdir/"index",40000000)
    refs = git(["for-each-ref","--format=%(refname) %(objectname)"])
    return {"head":head,"tree":tree,"index_bytes":len(index),"index_sha256":sha256(index),
            "refs_bytes":len(refs),"refs_sha256":sha256(refs),"worktree_file_bytes_examined":False}

def exact_read(f,n):
    a = []
    while n:
        c = f.read(min(n,1048576))
        check(bool(c),"unexpected EOF in git cat-file")
        a.append(c)
        n -= len(c)
    return b"".join(a)

def get_existing(s,typ):
    global batch
    check(HEX.fullmatch(s) is not None,"invalid Git object SHA")
    if s in existing:
        check(existing[s]["type"] == typ,"existing object type mismatch")
        return retained_raw.get(s)
    batch.stdin.write((s+"\n").encode("ascii"))
    batch.stdin.flush()
    h = batch.stdout.readline(512)
    z = h.rstrip(b"\n").split(b" ")
    check(len(z) == 3 and z[0].decode("ascii") == s,"missing or invalid existing object "+s+": "+repr(h))
    actual_type = z[1].decode("ascii")
    n = int(z[2])
    check(actual_type == typ and 0 <= n <= 1073741824,"object type or size rejected "+s)
    b = exact_read(batch.stdout,n)
    check(exact_read(batch.stdout,1) == b"\n","invalid git batch terminator")
    check(oid(typ,b) == s,"existing raw Git SHA mismatch "+s)
    existing[s] = {"sha":s,"type":typ,"bytes":n,"sha256":sha256(b),"raw_git_sha_verified":True}
    if typ in ("tree","commit"):
        retained_raw[s] = b
    return b if typ in ("tree","commit") else None

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

def get_packet(s,typ):
    obj = objects[s]
    check(obj["type"] == typ,"packet ref type mismatch")
    return obj["raw"]

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

def add_file_meta(rows):
    out = []
    for path in sorted(rows):
        row = dict(rows[path])
        m = objects.get(row["sha"],existing.get(row["sha"]))
        check(m is not None,"no blob metadata")
        row.update({"bytes":m["bytes"],"sha256":m["sha256"]})
        out.append(row)
    return out

def on_alarm(signum,frame):
    raise TimeoutError("evidence-only canonical validation 600-second budget")

try:
    check(ROOT.is_dir() and not ROOT.is_symlink(),"missing or unsafe evidence input directory")
    OUT.mkdir(mode=0o700)
    created_out = True
    check(not git_overrides,"inherited Git location overrides: "+repr(git_overrides))
    write("ACTUAL_DRIVER.py",regular_read(__file__,100000))
    signal.signal(signal.SIGALRM,on_alarm)
    signal.alarm(600)
    phase = "input_validation"
    mb = regular_read(ROOT/"CANONICAL_MANIFEST.json",1000000)
    check(len(mb)==MANIFEST["bytes"] and sha256(mb)==MANIFEST["sha256"] and oid("blob",mb)==MANIFEST["sha"],"manifest identity")
    manifest = parse(mb)
    check(manifest["repository"]=="TrillionniumFoundation/hepta-private-ci" and manifest["fixed_tip"]==TIP and manifest["fixed_tip_tree"]==TIPTREE,"manifest pin")
    write("CANONICAL_MANIFEST.original.json",mb)
    joined = []
    offset = 0
    for ordinal,p in enumerate(manifest["parts"],1):
        check(p["ordinal"]==ordinal and p["base64_offset"]==offset,"part ordering")
        b = regular_read(ROOT/p["name"],1000000)
        check(len(b)==p["bytes"] and sha256(b)==p["sha256"] and oid("blob",b)==p["git_blob"],"part identity")
        check(b.endswith(b"\n") and b.count(b"\n")==1 and len(b)-1==p["base64_characters"],"part LF/size")
        joined.append(b[:-1])
        offset += len(b)-1
    enc = b"".join(joined)
    b64_record = enc+b"\n"
    check(len(b64_record)==manifest["base64_stream"]["bytes"] and sha256(b64_record)==manifest["base64_stream"]["sha256"] and oid("blob",b64_record)==manifest["base64_stream"]["git_blob"],"base64 stream identity")
    gz = base64.b64decode(enc,validate=True)
    check(base64.b64encode(gz)==enc,"noncanonical base64")
    check(len(gz)==manifest["gzip"]["bytes"] and sha256(gz)==manifest["gzip"]["sha256"] and oid("blob",gz)==manifest["gzip"]["git_blob"],"gzip identity")
    with gzip.GzipFile(fileobj=io.BytesIO(gz),mode="rb") as f:
        raw = f.read(RAW["bytes"]+1)
        check(len(raw)==RAW["bytes"] and not f.read(1),"raw gzip bound")
    check(sha256(raw)==RAW["sha256"] and oid("blob",raw)==RAW["sha"],"raw packet identity")
    packet = parse(raw)
    check(packet["format"]=="hepta-canonical-git-object-transport-v1" and packet["repository"]==manifest["repository"],"packet format/repo")
    check(packet["fixed_base"]==B298 and packet["reuse_commit"]==C0F and packet["reuse_tree"]==C0FTREE and packet["fixed_tip"]==TIP and packet["fixed_tip_tree"]==TIPTREE,"packet anchors")
    check(packet["native_import_performed"] is False and packet["source_and_ref_writes_performed"] is False and packet["test_execution"] is False,"packet evidence scope")
    expected_index = {x["sha"]:x for x in manifest["object_index"]}
    check(len(expected_index)==395 and len(packet["objects"])==395,"object count")
    for x in packet["objects"]:
        s,t = x["sha"],x["type"]
        check(HEX.fullmatch(s) is not None and s not in objects and t in ("tree","blob","commit"),"object shape/duplicate")
        b = base64.b64decode(x["raw_base64"],validate=True)
        check(base64.b64encode(b).decode("ascii")==x["raw_base64"],"object base64 canonical")
        check(len(b)==x["bytes"] and sha256(b)==x["sha256"] and oid(t,b)==s,"packet object raw identity "+s)
        m = expected_index[s]
        check((t,len(b),sha256(b))==(m["type"],m["bytes"],m["sha256"]),"manifest object index mismatch")
        objects[s] = {"sha":s,"type":t,"bytes":len(b),"sha256":sha256(b),"raw":b}
    check(set(objects)==set(expected_index),"packet object index exact set")
    result["packet"] = {"parts":5,"gzip_bytes":len(gz),"gzip_sha256":sha256(gz),"raw_bytes":len(raw),"raw_sha256":sha256(raw),
                        "objects":395,"counts":{t:sum(x["type"]==t for x in objects.values()) for t in ("commit","tree","blob")}}
    check(result["packet"]["counts"]=={"commit":7,"tree":80,"blob":308},"object counts by type")
    phase = "pinned_existing_snapshots"
    before = git_state()
    jwrite("SOURCE_GIT_STATE.before.json",before)
    check(before["head"]==C0F and before["tree"]==C0FTREE,"source-gates repo identity")
    stderr = open(OUT/"cat-file.stderr.log","xb")
    batch_argv = [GIT,"--no-optional-locks","-C",str(REPO),"cat-file","--batch"]
    commands.append({"argv":batch_argv,"started_at":now(),"read_only":True})
    batch = subprocess.Popen(batch_argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,env=git_env)
    braw = get_existing(B298,"commit")
    craw = get_existing(C0F,"commit")
    bfields = commit_fields(braw)
    cfields = commit_fields(craw)
    check(bfields["tree"]==packet["base_tree"] and bfields["tree"].startswith(B298TREE),"original b298 root")
    check(cfields["tree"]==C0FTREE and cfields["parents"]==["e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd",B298],"original c0f root/parent order")
    bmap,btrees = snapshot(bfields["tree"],get_existing)
    cmap,ctrees = snapshot(C0FTREE,get_existing)
    check(len(bmap)==14842 and len(cmap)==14851,"existing snapshot leaf counts")
    trusted = {s:m["type"] for s,m in existing.items()}
    check(trusted[B298]=="commit" and trusted[C0F]=="commit","anchor types")
    required = {}
    for x in packet["required_existing_objects"]:
        check(set(x)=={"sha","type"} and HEX.fullmatch(x["sha"]) and x["type"] in ("tree","blob","commit"),"prerequisite shape")
        check(x["sha"] not in required,"duplicate prerequisite")
        check(trusted.get(x["sha"])==x["type"],"prerequisite outside trusted pinned snapshots "+x["sha"])
        required[x["sha"]]=x["type"]
    check(len(required)==16082 and manifest["required_existing_object_count"]==16082,"prerequisite count")
    result["pinned_snapshots"] = {"b298_tree":bfields["tree"],"b298_leaves":len(bmap),"b298_unique_trees":len(btrees),
                                 "c0f_tree":C0FTREE,"c0f_leaves":len(cmap),"c0f_unique_trees":len(ctrees),
                                 "trusted_object_union_count":len(trusted)}
    def resolve_new(s,typ):
        if s in objects:
            return get_packet(s,typ)
        check(trusted.get(s)==typ,"new snapshot references untrusted existing object "+s)
        check(required.get(s)==typ,"new snapshot prerequisite absent from declared set "+s)
        needed[s]=typ
        return get_existing(s,typ)
    phase = "seven_canonical_snapshots"
    order = packet["canonical_commit_order"]
    check(order==manifest["canonical_commits"] and len(order)==7,"canonical ordered metadata")
    changed = packet["per_commit_changed_paths"]
    check(len(changed)==7,"changed path records")
    canonical_audit = []
    all_maps = {"base_b298":add_file_meta(bmap),"reuse_c0f":add_file_meta(cmap)}
    parent = B298
    parent_map = bmap
    provided_used = set()
    for i,c in enumerate(order):
        check(c["parents"]==[parent],"canonical ordered parent chain")
        rawcommit = get_packet(c["sha"],"commit")
        fields = commit_fields(rawcommit)
        check(fields["tree"]==c["tree"] and fields["parents"]==c["parents"],"raw original commit headers")
        check(not fields["message_ends_with_lf"],"unexpected added message LF")
        check(len(fields["author_lines"])==1 and len(fields["committer_lines"])==1 and fields["author_lines"][0].endswith(" -0500") and fields["committer_lines"][0].endswith(" -0500"),"original timezones")
        rows,trees = snapshot(c["tree"],resolve_new)
        changes = [{"path":p.decode("utf-8"),"before":parent_map.get(p),"after":rows.get(p)}
                   for p in sorted(set(parent_map)|set(rows)) if parent_map.get(p)!=rows.get(p)]
        exp = changed[i]
        check(exp["sha"]==c["sha"] and exp["tree"]==c["tree"] and exp["parent"]==parent,"changed record commit")
        check(exp["leaf_count"]==len(rows) and exp["unique_tree_objects"]==len(trees),"changed record counts")
        check(sorted(exp["changes"],key=lambda x:x["path"].encode("utf-8"))==changes,"actual complete leaf diff mismatch")
        summary = manifest["per_commit_summary"][i]
        check(summary["sha"]==c["sha"] and summary["leaf_count"]==len(rows) and summary["changed_paths"]==len(changes),"manifest per-commit summary")
        canonical_audit.append({"sha":c["sha"],"tree":c["tree"],"parents":c["parents"],"leaf_count":len(rows),
                                "unique_tree_objects":len(trees),"changed_paths":changes,"raw_commit_fields":fields})
        all_maps[c["sha"]] = add_file_meta(rows)
        provided_used.add(c["sha"])
        provided_used.update(trees & set(objects))
        provided_used.update(x["sha"] for x in rows.values() if x["sha"] in objects)
        parent,parent_map = c["sha"],rows
    needed.update({B298:"commit",C0F:"commit"})
    check(needed==required,"exact needed-existing set mismatch")
    check(provided_used==set(objects),"provided objects are not exactly referenced by seven snapshots/commits")
    check(parent==TIP and order[-1]["tree"]==TIPTREE and len(parent_map)==15161,"exact final snapshot")
    result["required_existing"] = {"count":len(required),"counts":{t:sum(x==t for x in required.values()) for t in ("commit","tree","blob")},
                                   "trusted_snapshot_membership":True,"exact_needed_existing_set":True}
    check(result["required_existing"]["counts"]=={"commit":2,"tree":1774,"blob":14306},"prerequisite type counts")
    phase = "retaining_audit"
    jgz("OBJECT_AUDIT.json.gz",{
        "provided":[{k:v for k,v in objects[s].items() if k!="raw"} for s in sorted(objects)],
        "existing":[existing[s] for s in sorted(existing)],
        "required_existing":[{"sha":s,"type":required[s]} for s in sorted(required)],
        "needed_existing":[{"sha":s,"type":needed[s]} for s in sorted(needed)]})
    jgz("SNAPSHOT_LEAVES.json.gz",all_maps)
    jgz("TREE_AND_ANCHOR_RAW.json.gz",{
        "existing":[{**existing[s],"raw_base64":base64.b64encode(retained_raw[s]).decode("ascii")} for s in sorted(retained_raw)],
        "provided_tree_and_commit":[{k:v for k,v in objects[s].items() if k!="raw"}|{"raw_base64":base64.b64encode(objects[s]["raw"]).decode("ascii")}
                                    for s in sorted(objects) if objects[s]["type"] in ("tree","commit")]})
    jwrite("CANONICAL_COMMITS_AND_DIFFS.json",canonical_audit)
    result.update({"status":"canonical_snapshot_closure_verified","canonical_commit_count":7,"canonical_tip":TIP,
                   "canonical_tip_tree":TIPTREE,"canonical_tip_leaf_count":15161,
                   "provided_raw_objects_verified":395,"provided_exact_reachable_set":True})
except BaseException as e:
    result.update({"status":"failed","failure_phase":phase,"error":type(e).__name__+": "+str(e),"traceback":traceback.format_exc()})
finally:
    signal.alarm(0)
    if batch is not None:
        try:
            batch.stdin.close()
            rc = batch.wait(timeout=5)
            result["cat_file_returncode"] = rc
            if rc != 0:
                result["status"] = "failed"
                result["cat_file_error"] = "read-only batch returned nonzero"
        except BaseException as e:
            result["cat_file_close_error"] = repr(e)
            batch.terminate()  # This exact owned read-only helper only; never a Cargo/native process.
            try:
                batch.wait(timeout=5)
            except BaseException:
                pass
            result["status"] = "failed"
        stderr.close()
        try:
            errraw = regular_read(OUT/"cat-file.stderr.log",1000000)
            artifacts.append({"name":"cat-file.stderr.log","bytes":len(errraw),"sha256":sha256(errraw),"git_blob":oid("blob",errraw)})
        except BaseException as e:
            result["cat_file_stderr_read_error"] = repr(e)
            result["status"] = "failed"
    try:
        after = git_state()
        result["source_git_state_before"] = before
        result["source_git_state_after"] = after
        result["source_git_state_equal"] = (before==after) if before is not None else None
        if before is not None and before != after:
            result["status"] = "failed"
            result["source_git_state_changed"] = True
        elif before is None:
            result["source_git_state_comparison"] = "unknown_missing_before"
        if created_out:
            jwrite("SOURCE_GIT_STATE.after.json",after)
    except BaseException as e:
        result["source_git_state_equal"] = None
        result["final_git_state_error"] = repr(e)
        result["status"] = "failed"
    result["finished_at"] = now()
    if created_out:
        jwrite("COMMANDS.json",commands)
        result["artifacts"] = artifacts.copy()
        jwrite("ROOT_REVIEW.json",result)
        jwrite("ARTIFACTS.json",artifacts.copy())
    print(json.dumps(result,sort_keys=True,ensure_ascii=False),flush=True)
sys.exit(0 if result.get("status")=="canonical_snapshot_closure_verified" and result.get("source_git_state_equal") is True else 1)
