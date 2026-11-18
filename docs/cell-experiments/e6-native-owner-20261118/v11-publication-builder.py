"""Make an evidence-only native descendant of the exact v11 tested source; do not touch its checkout."""
import datetime,hashlib,json,shutil,subprocess,tarfile,time
from pathlib import Path
W=Path("/home/qq/e6-owner-current-20261118-556e5fc18a5b");S=W/"source"
D="e21ca2d9718c9c3506f6301449b29e6471a5cc22";E="1f4bdb211f0fb80fef89f25aef0f969053998b84"
R=W/"evidence-publisher-v11";P="docs/cell-experiments/e6-native-owner-20261118"
def git(cwd,*a):return subprocess.check_output(["git","-C",str(cwd),*a],text=True).strip()
assert git(S,"rev-parse","HEAD")==D and not git(S,"status","--porcelain")
info=json.loads((W/"public-evidence-v11-build-result.json").read_text());assert info["source_head"]==D and info["source_unchanged"]
arc=Path(info["archive"]);assert hashlib.sha256(arc.read_bytes()).hexdigest()==info["sha256"]
with tarfile.open(arc,"r:xz") as t:
    members=t.getmembers();assert len(members)==info["regular_files"] and len({x.name for x in members})==len(members)
    assert all(x.isfile() and x.name.startswith("native-owner-v11/") and ".." not in Path(x.name).parts for x in members)
    manifest_bytes=t.extractfile("native-owner-v11/manifest.json").read();manifest=json.loads(manifest_bytes)
    expected={x["path"]:x for x in manifest["files"]}
    assert set(expected)=={x.name[len("native-owner-v11/"):] for x in members if x.name!="native-owner-v11/manifest.json"}
    for rel,row in expected.items():
        data=t.extractfile("native-owner-v11/"+rel).read()
        assert len(data)==row["bytes"] and hashlib.sha256(data).hexdigest()==row["sha256"],rel
summary_bytes=(W/"public-evidence-v11/summary.json").read_bytes()
summary=json.loads(summary_bytes)
assert summary["source_head"]==D and summary["source_unchanged"]
failure_rows=[]
for role,relative,expected_sha in [
    ("post-A daemon", "child-logs/ordinary-q24-original-process-t0eB9Z/stderr.log", "4ff567607d654da8ce2323277b0c35a20dc4514b082f9e4d69a48766e989f1b0"),
    ("post-A Root", "child-logs/ordinary-q24-original-process-oiFFyt/stderr.log", "a0d765b6558b0792587fa8613dc5166108c85802c6dde40e29c37acf7f63d2db"),
    ("original B source", "child-logs/ordinary-q24-original-process-JZKV0W/stderr.log", "b95844c93c2b6023295c70ee9876aada3c81337c19dd769dd314f806b8cf41b8"),
]:
    raw=(W/"public-evidence-v11"/relative).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected_sha
    assert len(raw)<1024 and all(marker not in raw for marker in (b"PRIVATE KEY", b"generator_key", b"observer_key"))
    failure_rows.append(dict(role=role,archive_member="native-owner-v11/"+relative,sha256=expected_sha,stderr=raw.decode()))
summary["native_failure_projection"]=dict(
    records=failure_rows,
    earliest_visible_daemon_boundary="original historical learning source -> original training material -> original Dataset projection -> original Root historical Dataset -> original complete historical task read unavailable",
    client_request_sequence_observed=None,
    interpretation="The original historical client refusal remains unresolved. Root owner-process exit and B notification closure are retained as subsequent observations, not asserted as the daemon's initial cause. These separate stderr files do not supply a total timestamp order.",
    measurement_scope="19114/28933 is v11 actual Task data; v10 exact response length was not measured.",
)
summary["metadata_projection_source"]=dict(archive_summary_sha256=hashlib.sha256(summary_bytes).hexdigest(),addition="Only the error projection above was added from byte-verified whitelisted archived stderr; the archived summary and all tested-source materials remain immutable.")

subprocess.run(["git","-C",str(S),"worktree","add","--detach",str(R),D],check=True)
dest=R/P;assert dest.is_dir()
names={}
for src,name in [
    (arc,arc.name),
    (W/"public-evidence-v11/manifest.json","v11-MANIFEST.json"),
    (W/"public-evidence-v11/summary.json","v11-SUMMARY.json"),
    (W/"owner-task-response-capacity-candidate.json","v11-source-candidate.json"),
    (W/"native-v11/product-manifest.json","v11-compiler-products.json"),
]:
    path=dest/name;assert not path.exists();shutil.copyfile(src,path);names[name]=hashlib.sha256(path.read_bytes()).hexdigest()
(dest/"v11-SUMMARY.json").write_text(json.dumps(summary,indent=2)+"\n")
names["v11-SUMMARY.json"]=hashlib.sha256((dest/"v11-SUMMARY.json").read_bytes()).hexdigest()
builder=Path(__file__).read_bytes()
(dest/"v11-publication-builder.py").write_bytes(builder)
names["v11-publication-builder.py"]=hashlib.sha256(builder).hexdigest()
archive_record=dict(**info,verified_regular_members=len(members),manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
  tested_source=D,tested_tree=summary["source_tree"],publication_scope="Evidence-only descendant; no tests are attributed to its metadata commit.")
(dest/"v11-ARCHIVE.json").write_text(json.dumps(archive_record,indent=2)+"\n")
names["v11-ARCHIVE.json"]=hashlib.sha256((dest/"v11-ARCHIVE.json").read_bytes()).hexdigest()
case_rows=[]
for name in ("task-capacity-regressions","ordinary-whole-cold-no-update","ordinary-whole-cold-adopt"):
    case=summary["checks"].get(name)
    outcome="not attempted" if case is None else ("passed" if case.get("passed") else "retained failure")
    case_rows.append(f"| {name} | {outcome} |")
labels=", ".join(summary["observed_static_stages"]) or "none recorded"
extra=f"""
## v11: compose the complete Task response capacity

The exact tested source is {D}, tree {summary["source_tree"]}, direct child of evidence-only {E}. The v10 original Task operation reached reply serialization and then rejected its nonempty complete response at the 16,384-byte outer bound. Its actual byte count was not measured. Both original component validators had run before that branch: the complete Ledger DTO remains capped at 12,288 bytes, and the complete Publication DTO remains capped at 16,384 bytes. The finite canonical seven-field envelope is at most 261 bytes, derived from its fixed JSON keys, purpose, two canonical digest strings and the decimal width of MAX_READS. The Task-only response bound is therefore 28,933 bytes.

The repair applies that derived bound to the Task producer, complete Task decoder, historical server response policy and the actual client frame reader. The client chooses its capacity from the already known operation before reading the peer-controlled length. Requests, bootstrap data, default CURRENT exchanges and all five other historical operations retain their original bounds. Both inner DTO caps, original authentication, pidfd checks, absolute deadlines, MAX_READS, refusal state and fencing remain in force. The existing transport ceiling remains 65,536 bytes.

This is a paired Root/daemon capacity revision with the same v1 JSON shape, purpose and digest domains. Old v1 readers still reject replies above 16 KiB before allocating the body; mixed-version compatibility is not claimed. No canonical task field is removed, and the original ordinary A/business fixture is unchanged.

| Exact selected stage | Actual outcome |
|---|---|
{chr(10).join(case_rows)}

Related codec regressions generate their larger publication through the existing controlled Source/Cell execution, then retain the complete original Ledger/Publication validation. They are data/transport tests, not independent Root authentication or business adoption. Actual socket/pidfd regressions check the larger selected response, the unchanged default response/request limits, oversized-prefix refusal before body allocation, and the original deadlines.

The original daemon stderr is preserved verbatim in the metadata summary alongside the Root and B source stderr: `original historical learning source -> original training material -> original Dataset projection -> original Root historical Dataset -> original complete historical task read unavailable`. Root's later `owner process exited` is not asserted as the initial cause. No historical-client request count or sequence was recorded, and no count is inferred from the separate A control request IDs. The archive's original summary remains immutable; v11-SUMMARY.json adds only this explicit projection from its hash-verified raw stderr. v11-publication-builder.py records the metadata-only transformation.

Observed numeric Task measurements: {json.dumps(summary.get("task_reply_measurements", []),sort_keys=True)}. These record only the original serialized Vec length and selected bound, without reserializing components in the production success path. Observed original Root error stages: {labels}. Original errors and failed outputs remain in the archive; absent narrow labels do not establish that uncovered comparisons passed.

Both production binaries were rebuilt and pinned at this exact source. Each actual ELF was required to differ from v10, and the new numeric Task observation label was verified in the authority ELF before execution. Compiler records, product-manifest.json and component-executable-bindings.json retain their exact provenance. The adapter permits one original NoUpdate case with retries zero; the original Adopt cold case is attempted once only if NoUpdate passes. Earlier-source tests remain attached to their original commits.

The safe v11 archive is {arc.name} ({info["bytes"]:,} bytes, SHA-256 {info["sha256"]}). Every one of its {len(members)} regular members was checked against its manifest before publication. v11-SUMMARY.json and v11-ARCHIVE.json distinguish source, execution and metadata identities. This evidence-only commit is a direct child of the actually tested source.

All command timings and cost gaps are retained. Unmeasured CPU/GPU/energy/API/monetary costs remain unknown. Existing cold profiles inspect retained C and do not execute a fresh D. Independent-controller certification, FinalUse, settlement and complete E6 qualification remain unestablished.
"""
readme=dest/"README.md";readme.write_text(readme.read_text()+extra)
names["README.md"]=hashlib.sha256(readme.read_bytes()).hexdigest()
subprocess.run(["git","-C",str(R),"add","--",P],check=True)
changed=git(R,"diff","--cached","--name-only").splitlines()
assert set(changed)=={P+"/"+n for n in names},changed
assert git(R,"diff","--name-only")=="" and git(R,"rev-parse","HEAD")==D
subprocess.run(["git","-C",str(R),"-c","user.name=Codex","-c","user.email=codex@openai.com","commit","-m","Archive paired Task capacity revision and exact native owner results"],check=True)
head=git(R,"rev-parse","HEAD");tree=git(R,"rev-parse","HEAD^{tree}")
assert git(R,"rev-parse","HEAD^")==D and not git(R,"status","--porcelain")
for name,sha in names.items():
    data=subprocess.check_output(["git","-C",str(R),"show",head+":"+P+"/"+name]);assert hashlib.sha256(data).hexdigest()==sha
bundle=W/"native-owner-v11-from-evidence.bundle"
subprocess.run(["git","-C",str(R),"-c","pack.threads=1","bundle","create",str(bundle),"HEAD","^"+E],check=True)
assert git(S,"rev-parse","HEAD")==D and not git(S,"status","--porcelain")
result=dict(status="created",head=head,tree=tree,parent=D,base=E,repo=str(R),tested_source=D,tested_tree=summary["source_tree"],
  files=changed,archive=archive_record,bundle=str(bundle),bundle_bytes=bundle.stat().st_size,bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
  observed_static_stages=summary["observed_static_stages"],source_unchanged=True,finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
(W/"native-owner-v11-publication.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result),flush=True)

