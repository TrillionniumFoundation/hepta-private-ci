"""Freeze closed Run02 evidence and reviewable source for root-only publication."""
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import time
import zipfile
ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
OUT = ROOT / "research-final-publication-02"
WORK = ROOT / "publication-native-01"
BASE = "6b8d8c44a183c48e761aff76e0570ab278b4f7da"
PREFIX = "qualification/cell-experiments-v3-20261116/operations/research-run02-final/"
PART = 322560
payload, origins, inputs, groups, bundles = {}, {}, {}, [], []
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def js(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+"\n").encode()
def jl(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()+b"\n"
def read(path, expected=None):
    if not path.is_relative_to(ROOT) or path.is_symlink() or not path.is_file():
        raise ValueError("input is not a regular task-owned file")
    raw=path.read_bytes()
    identity={"bytes":len(raw),"sha256":sha(raw)}
    if expected and identity["sha256"] != expected:
        raise ValueError("frozen source digest differs: "+str(path))
    key=str(path.relative_to(ROOT))
    if inputs.setdefault(key,identity) != identity:
        raise ValueError("input changed across reads")
    return raw
def put(name, raw, origin):
    if Path(name).is_absolute() or ".." in Path(name).parts or ".git" in Path(name).parts:
        raise ValueError("unsafe publication path")
    key=PREFIX+name
    if key in payload or len(raw)>=512000:
        raise ValueError("duplicate or oversized Git object")
    if name.endswith((".zip",".bin")) and len(raw)>PART:
        raise ValueError("binary publication part exceeds bound")
    payload[key],origins[key]=raw,origin
    return key
def group(title, names, note=""):
    groups.append({"title":title,"files":names,"note":note})
def cp(path,name,expected=None):
    return put(name,read(path,expected),str(path.relative_to(ROOT)))
def git(*args):
    p=subprocess.run(["git",*args],cwd=WORK,capture_output=True,timeout=90)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout
def makezip(contents):
    s=io.BytesIO()
    with zipfile.ZipFile(s,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,raw in sorted(contents.items()):
            e=zipfile.ZipInfo(name,(2026,11,17,0,0,0))
            e.compress_type=zipfile.ZIP_DEFLATED
            e.external_attr=(stat.S_IFREG|0o644)<<16
            z.writestr(e,raw)
    raw=s.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() or set(z.namelist())!=set(contents) or len(z.namelist())!=len(contents):
            raise ValueError("ZIP CRC or exact membership differs")
        if any(z.read(n)!=b for n,b in contents.items()):
            raise ValueError("ZIP member bytes differ")
    return raw
def archive_bundle(name, contents, note):
    raw=makezip(contents)
    rows,names=[],[]
    for i,offset in enumerate(range(0,len(raw),PART)):
        data=raw[offset:offset+PART]
        part=name+"/part-%05d.bin"%i
        names.append(put(part,data,"lossless closed-evidence archive part"))
        rows.append({"path":part,"bytes":len(data),"sha256":sha(data)})
    index=b"".join(jl({"path":n,"bytes":len(b),"sha256":sha(b)}) for n,b in sorted(contents.items()))
    index_name=name+"/MEMBERS.jsonl"
    names.append(put(index_name,index,"exact original archive member identities"))
    descriptor={"schema":"hepta.final-evidence-lossless-archive.v1",
        "archive_bytes":len(raw),"archive_sha256":sha(raw),"parts":rows,
        "members":len(contents),"member_index":index_name,"member_index_sha256":sha(index),
        "notes":note,"original_bytes_unchanged":True,"new_independent_samples":0}
    names.append(put(name+"/MANIFEST.json",js(descriptor),"lossless reconstruction manifest"))
    bundles.append(descriptor)
    return names
def regular_files(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("selected input directory absent")
    rows=[]
    for p in sorted(directory.rglob("*")):
        if p.name.startswith("."):
            continue
        if p.is_symlink():
            raise ValueError("selected input has an unexpected symlink")
        if p.is_file():
            rows.append(p)
    return rows
if git("rev-parse","HEAD").decode().strip()!=BASE or git("status","--porcelain=v1").strip():
    raise ValueError("native base or clean status differs")
config=json.loads(read(OUT/"FINAL_INPUTS_02.json"))
if config["root_final_freeze_authorized"] is not True or config["base_commit"]!=BASE:
    raise ValueError("final root disposition has not been supplied")
prior=json.loads(read(ROOT/"research-static-publication-02/NATIVE_FINAL_PLAN_01.json",
    "e8710053841ddad7c709a593bf1ae09cc74071c26cc8a6384012e66c2ff90f34"))
core={r.split("\t",1)[1]:r.split("\t",1)[0].split()[2]
      for r in git("ls-tree","-r","HEAD","--","scripts/cell_experiments").decode().splitlines()
      if r.endswith(".py")}
if len(core)!=64 or core!=prior["expected_complete_core_git_blobs"]:
    raise ValueError("64 frozen core blobs differ")
prep=json.loads(read(OUT/"prepared-v2/PREPARATION_MANIFEST.json",
    "93e3a3ca49a082dc7c238cca62180301b531b8fd1cc3dc61a9ea0e8dcc13d5c0"))
for name,identity in prep["inputs"].items():
    raw=read(ROOT/name,identity["sha256"])
    if len(raw)!=identity["bytes"]:
        raise ValueError("prepared closed input size differs")
export=ROOT/"research-final-export-02"
transfer_raw=read(export/"TRANSFER_MANIFEST.json",
    "4a6f4fae9a04d7afe86476d36fb55767388a15f4a3d98dfa2dcb1795163b3ec9")
transfer=json.loads(transfer_raw)
if transfer["member_count"]!=1687 or transfer["archive"]["sha256"]!="a852fa6d9ce8317edd15bd7e6edeb3ee12e97e3d27c4ba179e5fe2c34846ad61":
    raise ValueError("Run02 frozen export identity differs")
archive_files,restore_map=[],[]
for row in transfer["archive"]["parts"]:
    name="export/"+row["path"]
    archive_files.append(cp(export/row["path"],name,row["sha256"]))
    restore_map.append({**row,"source_path":"research-final-export-02/"+row["path"],"published_path":PREFIX+name})
for i in range(0,len(archive_files),8):
    group("Preserve Run02 original archive parts %02d through %02d"%(i,min(i+7,len(archive_files)-1)),
        archive_files[i:i+8],"Exact bytes of the closed original export; no execution or adoption is implied.")
for row in transfer["members"]["parts"]:
    restore_map.append({**row,"source_path":"research-final-export-02/"+row["path"],
        "published_container_manifest":PREFIX+"prepared-v2/export-index-original-parts/MANIFEST.json",
        "container_member":"research-final-export-02/"+row["path"]})
for name in ("TRANSFER_MANIFEST.json","RESTORE.txt"):
    raw=read(export/name)
    restore_map.append({"path":name,"bytes":len(raw),"sha256":sha(raw),
        "source_path":"research-final-export-02/"+name,"published_path":PREFIX+"export/"+name})
if len(restore_map)!=97:
    raise ValueError("97-object restoration map differs")
group("Bind all 97 original Run02 export objects to exact restoration paths",[
    put("export/TRANSFER_MANIFEST.json",transfer_raw,"original unchanged transfer manifest"),
    cp(export/"RESTORE.txt","export/RESTORE.txt"),
    put("export/ORIGINAL_97_OBJECT_RESTORE_MAP.jsonl",b"".join(jl(v) for v in restore_map),"exact original object restoration mapping")])
for bundle in prep["bundles"]:
    names=[]
    for row in bundle["parts"]+[bundle["member_index"],bundle["manifest"]]:
        names.append(cp(OUT/row["path"],row["path"],row["sha256"]))
    group("Preserve "+Path(bundle["archive"]["path"]).parent.name+" originals",names,bundle["notes"])
source_rows=[]
control=[]
statuses={
    "reconcile_research02_controller_loss_01.py":"executed per root; original loss/readback records retained",
    "prepare_research_postrun_reconciled_02.py":"prepared but not executed per root",
    "prepare_research_postrun_reconciled_v2_02.py":"executed per root; original preparation/closure evidence retained",
    "prepare_static_publication_02.py":"executed for the already closed static publication per root",
    "verify_final_publication_02.py":"prepared but not executed at this package cutoff; future validation receipt is outside its own input archive"}
for name,status in statuses.items():
    path=ROOT/"operations"/name
    raw=read(path,config["new_control_sources"][name])
    control.append(put("control-source/"+name,raw,str(path.relative_to(ROOT))))
    source_rows.append({"path":str(path.relative_to(ROOT)),"sha256":sha(raw),"bytes":len(raw),"execution_status":status})
for path in regular_files(ROOT/"operations/research02-controller-reconciliation-review-01"):
    control.append(cp(path,"controller-review/"+path.name))
control.append(put("control-source/SOURCE_STATUS.jsonl",b"".join(jl(v) for v in source_rows),
    "execution distinctions reported by root, with unchanged original evidence"))
group("Preserve reconciled controller source and both original static reviews",control,
    "The first reconciled preparer was not executed; v2 and its actual closed receipts are distinct.")
old_sources=[
    ROOT/"research-publication-source-01/build_publication_source_01.py",
    ROOT/"research-closed01-prepared02-publication-01/build_closed01_prepared02_publication_01.py",
    ROOT/"research-static-publication-02/build_static_publication_02.py"]
for path in old_sources:
    group("Preserve previously unpublished "+path.name,[cp(path,"publication-source/prior/"+path.name)])
current_sources=[OUT/n for n in ["inventory_final_publication_02.py",
    "inventory_final_publication_v2_02.py","inventory_final_publication_v3_02.py",
    "prepare_closed_artifacts_02.py","prepare_closed_artifacts_v2_02.py",
    "build_final_publication_02.py"]]+[Path(__file__).resolve()]
group("Preserve every final-package program including failed historical versions",
    [cp(p,"publication-source/current/"+p.name) for p in current_sources],
    "Failed inventory/preparation versions remain historical source; their actual terminals are retained. The final builder includes its own stable source, never its future outputs.")
tracked={}
for row in git("ls-tree","-r","HEAD").decode().splitlines():
    left,name=row.split("\t",1)
    tracked.setdefault(left.split()[2],[]).append(name)
coverage_rows=[]
for name in config["operations_source_names"]:
    path=ROOT/"operations"/name
    raw=read(path)
    blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    previous=tracked.get(blob,[])
    target=PREFIX+"control-source/"+name
    if not previous and target not in payload:
        document=next((v for v in config["documents"] if v["source_path"]==str(path.relative_to(ROOT))),None)
        if document is None or document["sha256"]!=sha(raw):
            raise ValueError("task-owned operations source has no exact published/new source: "+name)
        target=PREFIX+document["target"]
    coverage_rows.append({"source_path":str(path.relative_to(ROOT)),"sha256":sha(raw),
        "git_blob":blob,"prior_exact_blob_paths":previous,
        "new_published_path":None if previous else target})
for path in old_sources+current_sources:
    raw=read(path)
    coverage_rows.append({"source_path":str(path.relative_to(ROOT)),"sha256":sha(raw),
        "new_published_path":PREFIX+"publication-source/"+("prior/" if path in old_sources else "current/")+path.name})
group("Bind all selected controller and publication source bytes",[
    put("publication-source/COMPLETE_SOURCE_COVERAGE.jsonl",b"".join(jl(v) for v in coverage_rows),
        "exact base Git blobs or new reviewable source paths, including failed source versions")])
documents=[]
document_groups={}
for item in config["documents"]:
    path=ROOT/item["source_path"]
    raw=read(path,item["sha256"])
    target=item["target"]
    role=item["role"]
    record={"source_path":item["source_path"],"target":target,"bytes":len(raw),"sha256":sha(raw),"role":role}
    text_file=path.suffix in (".py",".md",".diff")
    binary=target.endswith((".zip",".bin"))
    direct=(len(raw)<512000 and ((binary and len(raw)<=PART) or
            (not binary and len(raw.splitlines())<=800)))
    if text_file and not direct:
        raise ValueError("reviewable source or narrative requires an explicit bounded arrangement")
    if direct:
        names=[put(target,raw,item["source_path"])]
        record["storage"]="direct exact bytes"
    else:
        archive_name=target+".original"
        names=archive_bundle(archive_name,{item["source_path"]:raw},
            "Exact closed original companion file; no content rewriting. Restore using this original-byte manifest.")
        record["storage"]="lossless archive"
        record["container_manifest"]=archive_name+"/MANIFEST.json"
    document_groups.setdefault(role,[]).extend(names)
    documents.append(record)
for role,names in document_groups.items():
    group("Preserve "+role+" originals and their stated interpretation limits",names)
group("Bind final result, interface and posthoc document identities",[
    put("FINAL_DOCUMENT_BINDINGS.jsonl",b"".join(jl(v) for v in documents),"closed original document identities and restoration paths")])
preparation_files=regular_files(OUT/"prepared")+[
    OUT/"READONLY_DISCOVERY_01.json",OUT/"prepared-v2/PREPARATION_MANIFEST.json",
    OUT/"prepared-v2/PREPARATION_OBSERVATIONS.json",OUT/"FINAL_PREPARATION_OBSERVATIONS_02.json"]
group("Retain all packaging failures, partial originals and successful preparation observations",
    archive_bundle("publication-preparation-evidence",
        {str(p.relative_to(ROOT)):read(p) for p in preparation_files},
        "Historical packaging-only failures and partial files remain intact. Original source versions are separately reviewable. This evidence does not add scientific samples or executions."))
for required in ("summary/RESULTS_AND_DECISIONS.md","result-review/","interface-review/","posthoc/"):
    if not any(item["target"]==required or item["target"].startswith(required) for item in config["documents"]):
        raise ValueError("required final disposition document missing: "+required)
readme="""# Closed Run02 research evidence and final interpretation

Read [the final Chinese results and decisions](summary/RESULTS_AND_DECISIONS.md)
together with the original [result review](result-review/), [diagnostic-interface
review](interface-review/) and [posthoc material](posthoc/). Their individual
source SHA values and storage locations are in FINAL_DOCUMENT_BINDINGS.jsonl.

## Exact original export

The original Run02 ZIP contains 1,687 members. Its 29,880,237 bytes have SHA256
a852fa6d9ce8317edd15bd7e6edeb3ee12e97e3d27c4ba179e5fe2c34846ad61.
All 97 original Git export objects remain exactly recoverable. The 93 original
archive parts, original TRANSFER_MANIFEST.json and RESTORE.txt retain their
original bytes in export/. The two original JSONL index parts retain their
original names and bytes inside the lossless export-index-original-parts bundle.
ORIGINAL_97_OBJECT_RESTORE_MAP.jsonl maps every original object.

The index .bin names do not make JSONL binary to Git. A lossless ZIP preserves
their exact bytes while meeting the text-stage limit; no diff attributes or
publisher limits were changed. No original diagnostic, result, failed receipt
or reported unknown value has been rewritten by publication.

To restore, first verify and concatenate the ordered parts described by
prepared-v2/export-index-original-parts/MANIFEST.json into a NEW ZIP. Verify its
CRC and the two member identities in MEMBERS.jsonl. Extract to a NEW directory;
the members have research-final-export-02/ paths. Place those two index parts
alongside the 95 directly retained export objects in a new export directory,
using the 97-object map. Follow the unchanged original TRANSFER_MANIFEST and
RESTORE: verify every part, reconstructed ZIP/index, CRC, member path/size/SHA,
then extract to a new target. Reject traversal, symlinks and existing targets.

The research-sft-02/RESULT.json and research-diagnostic-02/DIAGNOSTIC.json are
members inside the original ZIP, not directly published standalone JSONs.
Their original interpretations and any later offline analysis are distinct.

## Controllers, snapshots and posthoc boundaries

The closed controller, observation, operation and prior-publication bundles
preserve original bytes. Their parts, archive hash and member index are in each
prepared-v2 bundle manifest. Reconstruct the archive at a new destination before
extraction; its whole transport ZIP is not separately duplicated in Git.

Watch and intermediate observations are non-atomic snapshots. Earlier lost or
incomplete controller captures remain visible beside later original readbacks.
They are not additional independent samples or substitutes for final owned
receipts. Source presence is not proof every program executed: the first
reconciled preparer is explicitly unexecuted; v2 has its own execution evidence.

The original frozen diagnostic remains unchanged. The interface review and
posthoc analysis retain their stated timing, assumptions and limits.
Posthoc analysis is not a retroactive pre-registration, a new training run,
a new independent task, or a reason to erase the original diagnostic output.

## Source and publication provenance

The selected operations source inventory is checked against exact base Git
blobs or newly published source. All three earlier publication builders and
every current package program are readable, including failed historical versions.
Packaging failures, partial outputs and successful observations are preserved.
The builder includes its stable source bytes, never its own future results.

The earlier Run01 resource failure remains in the previously published
research-run01-and-run02-preparation/run01/export/ archive. Run02 does not
replace it or erase its cost. Source, cost and global-total uncertainty must be
read with the final review, not inferred from exit codes or archive success.

This archive has an explicit cutoff before root validates or publishes this
operation06 input. Its prepared validation source is included; future validation,
native publication and Draft PR receipts are outside the input they describe.
No recursive trailing package is implied.

This publication performs no model, training, test, business verifier or C call.
It adds no independent samples and does not establish scientific confirmation,
Circuit, PoUW eligibility or production adoption. All 64 core Git blobs remain
unchanged. Root alone performs native Git publication and Draft PR operations.
"""
group("Explain exact restoration and original versus posthoc evidence boundaries",[
    put("README.md",readme.encode(),"closed original restoration and interpretation limits"),
    cp(OUT/"FINAL_INPUTS_02.json","publication-source/FINAL_INPUTS_02.json")])
member_raw=read(export/"MEMBERS.jsonl",transfer["members"]["sha256"])
member_map={row["path"]:row for row in (json.loads(v) for v in member_raw.splitlines())}
coverage={"schema":"hepta.closed-run02-publication-coverage.v1",
    "prepared_at_ns":time.time_ns(),"base_commit":BASE,"original_export_objects":97,
    "archive_members":1687,"archive_sha256":transfer["archive"]["sha256"],
    "raw_result_member":member_map["research-sft-02/RESULT.json"],
    "raw_diagnostic_member":member_map["research-diagnostic-02/DIAGNOSTIC.json"],
    "original_diagnostic_unchanged":True,"posthoc_disposition":config["posthoc_disposition"],
    "closed_watch_and_intermediate_observation_directories":36,
    "non_atomic_snapshots_are_not_independent_samples":True,
    "selected_operations_sources":len(config["operations_source_names"]),
    "previous_publication_builders_preserved":3,
    "current_packaging_sources_preserved":len(current_sources),
    "all_packaging_failures_retained":True,"all_64_core_git_blobs_unchanged":True,
    "cutoff":"before root's validation/publication/Draft PR operations on this operation06 input",
    "future_operation06_receipts_excluded_from_their_own_input":True,
    "new_model_test_verifier_C_calls":0,"Git_or_PR_mutated":False,"independent_sample_increment":0,
    "scientific_confirmation_qualified":False,"Circuit_qualified":False,
    "PoUW_eligible":False,"native_adoption":False,
    "excluded":["internal COORDINATOR_CHECKPOINT files","base weights","venv",
        "unrelated work","standalone temporary lock files"]}
names=[put("COVERAGE.json",js(coverage),"final package scope, unchanged originals and explicit qualification limits")]
input_rows=[jl({"source_path":n,**v}) for n,v in sorted(inputs.items())]
for i in range(0,len(input_rows),200):
    names.append(put("input-bindings/part-%03d.jsonl"%(i//200),b"".join(input_rows[i:i+200]),
        "exact original input identities; bounded parts form one complete inventory"))
group("Bind complete source inputs and preserve qualification limits",names)
names=[n for g in groups for n in g["files"]]
if len(names)!=len(set(names)) or set(names)!=set(payload):
    raise ValueError("stage groups do not partition payload")
tree=OUT/"payload"
tree.mkdir(exist_ok=False)
identities={}
for name,raw in sorted(payload.items()):
    p=tree/name
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("xb") as f:
        f.write(raw)
    result=subprocess.run(["git","diff","--no-index","--numstat","--","/dev/null",str(p)],
        cwd=OUT,capture_output=True,timeout=60)
    if result.returncode not in (0,1):
        raise RuntimeError(result.stderr.decode(errors="replace"))
    first=result.stdout.decode().split("\t",1)[0] if result.stdout else "0"
    identities[name]={"bytes":len(raw),"sha256":sha(raw),
        "git_added_text_lines":0 if first=="-" else int(first),"origin":origins[name]}
stages=[]
for g in groups:
    chunks,pending,count=[],[],0
    for name in g["files"]:
        n=identities[name]["git_added_text_lines"]
        if n>800:
            raise ValueError("source/evidence exceeds text bound; no exception authorized: "+name)
        if pending and count+n>499:
            chunks.append(pending)
            pending,count=[],0
        pending.append(name)
        count+=n
        if count>499:
            chunks.append(pending)
            pending,count=[],0
    if pending:
        chunks.append(pending)
    for i,chunk in enumerate(chunks):
        number=97+len(stages)
        title=g["title"]+(" (part %d)"%(i+1) if len(chunks)>1 else "")
        branch="codex/cell-experiments-v3-20261116-0c078a-s"
        lines=sum(identities[n]["git_added_text_lines"] for n in chunk)
        stages.append({"id":"s%d-run02-final"%number,"number":number,
            "commit_subject":title,"draft_pr_title":"[draft] "+title,
            "draft_pr_head":branch+str(number),"draft_pr_base":branch+str(number-1),
            "draft_pr_body":"Make the closed Run02 results, original diagnostic, interface review and explicitly posthoc interpretation reviewable. Preserve original failures, source, costs and unknowns. This stage does not execute models or tests, add independent samples, select a production candidate or establish scientific, Circuit or PoUW qualification. "+g["note"],
            "files":chunk,"added_text_lines":lines,"kind":"bounded_evidence_and_reviewable_source",
            "mechanical_evidence_exception":None,"prefer_under_500_met":lines<500})
attrs=git("check-attr","-z","diff","--",*sorted(payload)).split(b"\0")
if any(attrs[i]!=b"unspecified" for i in range(2,len(attrs)-1,3)):
    raise ValueError("destination diff attributes require review")
for name,expected in inputs.items():
    raw=(ROOT/name).read_bytes()
    if len(raw)!=expected["bytes"] or sha(raw)!=expected["sha256"]:
        raise ValueError("original input changed during final preparation")
if git("rev-parse","HEAD").decode().strip()!=BASE or git("status","--porcelain=v1").strip():
    raise ValueError("native tree changed during final preparation")
plan={"schema":"hepta.native-final-publication-plan.v3","base_commit":BASE,
    "frozen_at_ns":time.time_ns(),"binary_part_limit":PART,"git_object_limit_exclusive":512000,
    "expected_complete_core_git_blobs":core,"new_model_execution":False,
    "source_scope":"closed Run02 original evidence, final reviews, explicit posthoc results and all selected control/publication source",
    "files":identities,"stages":stages}
plan_raw=js(plan)
stage_raw=js({"schema":"hepta.full-stage-manifest.v1","base_commit":BASE,"files":identities,"stages":stages})
for name,raw in [("NATIVE_FINAL_PLAN_01.json",plan_raw),("STAGE_MANIFEST_01.json",stage_raw)]:
    with (OUT/name).open("xb") as f:
        f.write(raw)
archive=makezip({"NATIVE_FINAL_PLAN_01.json":plan_raw,**payload})
archive_name="publication-run02-final-input-02.zip"
with (OUT/archive_name).open("xb") as f:
    f.write(archive)
if (OUT/archive_name).read_bytes()!=archive:
    raise ValueError("saved input archive differs")
with zipfile.ZipFile(OUT/archive_name) as z:
    if z.testzip() or set(z.namelist())!=set(payload)|{"NATIVE_FINAL_PLAN_01.json"}:
        raise ValueError("saved final archive CRC/membership differs")
    for name,identity in identities.items():
        raw=z.read(name)
        if len(raw)!=identity["bytes"] or sha(raw)!=identity["sha256"]:
            raise ValueError("saved final payload identity differs")
destination=ROOT/archive_name
with destination.open("xb") as f:
    f.write(archive)
if destination.read_bytes()!=archive:
    raise ValueError("authorized create-only direct-root copy differs")
manifest={"schema":"hepta.closed-run02-publication-ready.v1",
    "status":"FROZEN_VALIDATED_AND_COPIED_FOR_ROOT_REVIEW_NOT_PUBLISHED",
    "base_commit":BASE,"intended_native_operation":"publication-final-operation-06",
    "archive_path":str(OUT/archive_name),"direct_root_archive_path":str(destination),
    "archive_bytes":len(archive),"archive_sha256":sha(archive),
    "plan_path":str(OUT/"NATIVE_FINAL_PLAN_01.json"),"plan_bytes":len(plan_raw),"plan_sha256":sha(plan_raw),
    "stage_manifest_path":str(OUT/"STAGE_MANIFEST_01.json"),
    "stage_manifest_bytes":len(stage_raw),"stage_manifest_sha256":sha(stage_raw),
    "first_stage":97,"last_stage":stages[-1]["number"],"stage_count":len(stages),
    "payload_files":len(payload),"payload_bytes":sum(map(len,payload.values())),
    "maximum_object_bytes":max(map(len,payload.values())),
    "maximum_text_stage_lines":max(s["added_text_lines"] for s in stages),
    "mechanical_exceptions":0,"original_inputs_rehashed_equal":len(inputs),
    "all_97_export_objects_exactly_recoverable":True,"original_archive_members":1687,
    "original_results_and_diagnostic_unchanged":True,"no_model_test_verifier_C_or_Git_mutation":True,
    "stages":[{"number":s["number"],"files":len(s["files"]),"lines":s["added_text_lines"],
               "title":s["commit_subject"]} for s in stages]}
with (OUT/"MANIFEST.json").open("xb") as f:
    f.write(js(manifest))
print(json.dumps(manifest,sort_keys=True),flush=True)
