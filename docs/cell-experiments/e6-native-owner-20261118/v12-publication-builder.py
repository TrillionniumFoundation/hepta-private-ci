"""Make an evidence-only native descendant of the exact v12 tested source; do not touch its checkout."""
import datetime,hashlib,json,shutil,subprocess,tarfile,time
from pathlib import Path
W=Path("/home/qq/e6-owner-current-20261118-556e5fc18a5b");S=W/"source"
D="30b4e260accbc0d81f6a17e106854c41c61c3346";E="b01b277b7c887a65a2159b37074eb7e0564e09e0"
R=W/"evidence-publisher-v12";P="docs/cell-experiments/e6-native-owner-20261118"
def git(cwd,*a):return subprocess.check_output(["git","-C",str(cwd),*a],text=True).strip()
assert git(S,"rev-parse","HEAD")==D and not git(S,"status","--porcelain")
info=json.loads((W/"public-evidence-v12-build-result.json").read_text());assert info["source_head"]==D and info["source_unchanged"]
arc=Path(info["archive"]);assert hashlib.sha256(arc.read_bytes()).hexdigest()==info["sha256"]
with tarfile.open(arc,"r:xz") as t:
    members=t.getmembers();assert len(members)==info["regular_files"] and len({x.name for x in members})==len(members)
    assert all(x.isfile() and x.name.startswith("native-owner-v12/") and ".." not in Path(x.name).parts for x in members)
    manifest_bytes=t.extractfile("native-owner-v12/manifest.json").read();manifest=json.loads(manifest_bytes)
    expected={x["path"]:x for x in manifest["files"]}
    assert set(expected)=={x.name[len("native-owner-v12/"):] for x in members if x.name!="native-owner-v12/manifest.json"}
    for rel,row in expected.items():
        data=t.extractfile("native-owner-v12/"+rel).read()
        assert len(data)==row["bytes"] and hashlib.sha256(data).hexdigest()==row["sha256"],rel
summary=json.loads((W/"public-evidence-v12/summary.json").read_text())
assert summary["source_head"]==D and summary["source_unchanged"]
subprocess.run(["git","-C",str(S),"worktree","add","--detach",str(R),D],check=True)
dest=R/P;assert dest.is_dir()
names={}
for src,name in [
    (arc,arc.name),
    (W/"public-evidence-v12/manifest.json","v12-MANIFEST.json"),
    (W/"public-evidence-v12/summary.json","v12-SUMMARY.json"),
    (W/"owner-client-refusal-stages-candidate.json","v12-source-candidate.json"),
    (W/"native-v12/product-manifest.json","v12-compiler-products.json"),
]:
    path=dest/name;assert not path.exists()
    if name=="v12-compiler-products.json" and not src.exists():
        assert summary["status"]=="failed" and summary["checks"]["helper-build"]["passed"] is False
        assert "product-build-and-pin" not in summary["checks"]
        path.write_text(json.dumps(dict(status="not-produced",source_head=D,source_tree=summary["source_tree"],failed_stage="helper-build",product_build_attempted=False,business_tests_attempted=False,reason="Rust E0034 diagnostic Write import collided with original inputs Read::by_ref through super glob. No original reader or predicate was changed."),indent=2)+"\n")
    else:
        shutil.copyfile(src,path)
    names[name]=hashlib.sha256(path.read_bytes()).hexdigest()
builder=Path(__file__).read_bytes()
(dest/"v12-publication-builder.py").write_bytes(builder)
names["v12-publication-builder.py"]=hashlib.sha256(builder).hexdigest()
archive_record=dict(**info,verified_regular_members=len(members),manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
  tested_source=D,tested_tree=summary["source_tree"],publication_scope="Evidence-only descendant; no tests are attributed to its metadata commit.")
(dest/"v12-ARCHIVE.json").write_text(json.dumps(archive_record,indent=2)+"\n")
names["v12-ARCHIVE.json"]=hashlib.sha256((dest/"v12-ARCHIVE.json").read_bytes()).hexdigest()
case_rows=[]
for name in ("ordinary-whole-cold-no-update","ordinary-whole-cold-adopt"):
    case=summary["checks"].get(name)
    outcome="not attempted" if case is None else ("passed" if case.get("passed") else "retained failure")
    case_rows.append(f"| {name} | {outcome} |")
labels=", ".join(summary["observed_static_stages"]) or "none recorded"
extra=f"""
## v12: diagnostic candidate preparation failure

The exact tested source is {D}, tree {summary["source_tree"]}, direct child of evidence-only {E}. v11 passed its nine related codec/frame regressions and recorded a real 19,114-byte Task reply under its 28,933-byte bound, but the original NoUpdate still failed later with a generic historical Dataset/client refusal. Those v11 byte counts and tests remain attached to source e21ca2d9; they are not inherited as v12 passes.

The actual attempt stopped during helper compilation after 14.718 seconds: Rust E0034 reported ambiguous Read/Write `by_ref` in the original historical bootstrap inputs module. The newly imported Write trait had propagated through its existing super glob. This source produced no per-run product manifest and executed no NoUpdate or Adopt case. The original reader and all gates remain unchanged; the failure is retained. v12-compiler-products.json explicitly records the missing product stage instead of reusing older binaries.\n\nThis candidate adds only diagnostic observations at existing client rejection branches, transport/decoder boundaries, receipt comparisons, operation callbacks before error fencing, original activation checks, Dataset callbacks and original source callers. Original callback Results are still stored without a new early return; original postcheck priority, question marks, error conversions, Drop/fence, identity predicates, deadlines, MAX_READS and all frame/component bounds remain unchanged. Only the existing read-limit rejection may print the local sequence and fixed maximum; other new labels contain no values, payload, configuration or key. Mechanical stripping restores all original tokens and strings, with two explicitly reviewed rustfmt match-arm style normalizations.

| Exact selected stage | Actual outcome |
|---|---|
{chr(10).join(case_rows)}

Observed original Root error stages: {labels}. Observed daemon stages: {", ".join(summary["observed_daemon_stages"]) or "none recorded"}. Numeric Task response observations: {json.dumps(summary["task_reply_measurements"],sort_keys=True)}. Read-limit observations: {json.dumps(summary["client_limit_observations"],sort_keys=True)}. The complete short original diagnostic stderr files are projected into v12-SUMMARY.json from the whitelist and remain byte-preserved in the raw archive. Per-process line order is retained; separate process outputs do not establish a total ordering. Missing labels do not prove that every uncovered condition passed.

The adapter would require a new actual daemon containing all eight selected labels before business execution, and would record both products plus the actual Source/Observer libtest. Those preparation stages were not reached in this attempt. Compiler stdout/stderr and the execution record preserve the actual failure and elapsed time.

The adapter permits one original NoUpdate case with retries zero; the original Adopt cold case is attempted once only if NoUpdate passes. No v11 codec/frame tests were repeated on this diagnostic-only candidate. All earlier tests remain attached to their actually tested sources.

The safe v12 archive is {arc.name} ({info["bytes"]:,} bytes, SHA-256 {info["sha256"]}). Each of its {len(members)} regular members was checked against its manifest before publication. v12-SUMMARY.json and v12-ARCHIVE.json distinguish tested source, execution and this evidence-only child.

All command timings and cost gaps are retained. Unmeasured CPU/GPU/energy/API/monetary costs remain unknown. Existing cold profiles inspect retained C; they do not execute a fresh D. Independent-controller certification, FinalUse, settlement and complete E6 qualification remain unestablished.
"""
readme=dest/"README.md";readme.write_text(readme.read_text()+extra)
names["README.md"]=hashlib.sha256(readme.read_bytes()).hexdigest()
subprocess.run(["git","-C",str(R),"add","--",P],check=True)
changed=git(R,"diff","--cached","--name-only").splitlines()
assert set(changed)=={P+"/"+n for n in names},changed
assert git(R,"diff","--name-only")=="" and git(R,"rev-parse","HEAD")==D
subprocess.run(["git","-C",str(R),"-c","user.name=Codex","-c","user.email=codex@openai.com","commit","-m","Archive actual historical client and Dataset diagnostic results"],check=True)
head=git(R,"rev-parse","HEAD");tree=git(R,"rev-parse","HEAD^{tree}")
assert git(R,"rev-parse","HEAD^")==D and not git(R,"status","--porcelain")
for name,sha in names.items():
    data=subprocess.check_output(["git","-C",str(R),"show",head+":"+P+"/"+name]);assert hashlib.sha256(data).hexdigest()==sha
bundle=W/"native-owner-v12-from-evidence.bundle"
subprocess.run(["git","-C",str(R),"-c","pack.threads=1","bundle","create",str(bundle),"HEAD","^"+E],check=True)
assert git(S,"rev-parse","HEAD")==D and not git(S,"status","--porcelain")
result=dict(status="created",head=head,tree=tree,parent=D,base=E,repo=str(R),tested_source=D,tested_tree=summary["source_tree"],
  files=changed,archive=archive_record,bundle=str(bundle),bundle_bytes=bundle.stat().st_size,bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
  observed_static_stages=summary["observed_static_stages"],source_unchanged=True,finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
(W/"native-owner-v12-publication.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result),flush=True)

