"""Publish only whitelisted evidence for the exact v13 source; never inherit a test result."""
import datetime,hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
W=Path("/home/qq/e6-owner-current-20261118-556e5fc18a5b");S=W/"source"
D="978719e6137cc1fe9a64bcde7795cd478b2f293e";E="5a5d9c5256cd3ce390b2442474224ab98ea2efcc"
R=W/"evidence-publisher-v13";P="docs/cell-experiments/e6-native-owner-20261118"
def git(cwd,*a):return subprocess.check_output(["git","-C",str(cwd),*a],text=True).strip()
assert git(S,"rev-parse","HEAD")==D and not git(S,"status","--porcelain")
assert git(S,"rev-parse","HEAD^")==E
info=json.loads((W/"public-evidence-v13-build-result.json").read_text());assert info["source_head"]==D and info["source_unchanged"]
arc=Path(info["archive"]);assert hashlib.sha256(arc.read_bytes()).hexdigest()==info["sha256"]
with tarfile.open(arc,"r:xz") as t:
 members=t.getmembers();assert len(members)==info["regular_files"] and len({x.name for x in members})==len(members)
 assert all(x.isfile() and x.name.startswith("native-owner-v13/") and ".." not in Path(x.name).parts for x in members)
 manifest_bytes=t.extractfile("native-owner-v13/manifest.json").read();manifest=json.loads(manifest_bytes)
 expected={x["path"]:x for x in manifest["files"]}
 assert set(expected)=={x.name[len("native-owner-v13/"):] for x in members if x.name!="native-owner-v13/manifest.json"}
 for rel,row in expected.items():
  data=t.extractfile("native-owner-v13/"+rel).read()
  assert len(data)==row["bytes"] and hashlib.sha256(data).hexdigest()==row["sha256"],rel
review_path=W/"client-log-scope-v13-review/INDEPENDENT_REVIEW.json"
assert hashlib.sha256(review_path.read_bytes()).hexdigest()=="56af8a97d7965c9efd1d79a99ca44862bd26c0260f15fab3ecea9c9fbc674a53"
review=json.loads(review_path.read_text());assert review["frozen_head"]==D and review["status"]=="reviewed-no-blocker"
summary=json.loads((W/"public-evidence-v13/summary.json").read_text())
assert summary["source_head"]==D and summary["source_unchanged"]
subprocess.run(["git","-C",str(S),"worktree","add","--detach",str(R),D],check=True)
dest=R/P;assert dest.is_dir();names={}
for src,name in [
 (arc,arc.name),(W/"public-evidence-v13/manifest.json","v13-MANIFEST.json"),
 (W/"public-evidence-v13/summary.json","v13-SUMMARY.json"),
 (W/"owner-client-log-scope-v13-candidate.json","v13-source-candidate.json"),
 (Path(__file__),"v13-publication-builder.py"),
 (review_path,"v13-INDEPENDENT-REVIEW.json"),
]:
 path=dest/name;assert not path.exists();shutil.copyfile(src,path);names[name]=hashlib.sha256(path.read_bytes()).hexdigest()
product_path=W/"native-v13/product-manifest.json"
if product_path.exists():
 product=json.loads(product_path.read_text());assert product["head"]==D and product["tree"]==summary["source_tree"]
 shutil.copyfile(product_path,dest/"v13-compiler-products.json")
 product_note="Both products were prepared and pinned by the original compiler-artifact route on this exact candidate. See v13-compiler-products.json for actual SHA-256 values. Where component-executable-bindings.json exists, it also checks all eight selected daemon labels and the actual Source/Observer libtest. A changed Root hash is not assumed for client-side edits."
else:
 (dest/"v13-compiler-products.json").write_text(json.dumps(dict(status="not-produced",source_head=D,source_tree=summary["source_tree"],qualification="Preparation did not produce the product manifest. No old ELF is substituted and no business execution is inferred."),indent=2)+"\n")
 product_note="Preparation did not produce the product manifest. No old ELF was substituted. Product and business results must not be inferred from this candidate."
names["v13-compiler-products.json"]=hashlib.sha256((dest/"v13-compiler-products.json").read_bytes()).hexdigest()
archive_record=dict(**info,verified_regular_members=len(members),manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),tested_source=D,tested_tree=summary["source_tree"],publication_scope="Evidence-only descendant; no tests are attributed to this metadata commit.")
(dest/"v13-ARCHIVE.json").write_text(json.dumps(archive_record,indent=2)+"\n");names["v13-ARCHIVE.json"]=hashlib.sha256((dest/"v13-ARCHIVE.json").read_bytes()).hexdigest()
rows=[]
for name in ("ordinary-whole-cold-no-update","ordinary-whole-cold-adopt"):
 case=summary["checks"].get(name);outcome="not attempted" if case is None else ("passed" if case.get("passed") else "retained failure")
 rows.append(f"| {name} | {outcome} |")
labels=", ".join(summary["observed_static_stages"]) or "none recorded"
extra=f"""
## v13: repair diagnostic trait scope without changing the original reader

The exact source is {D}, tree {summary["source_tree"]}, direct child of evidence-only {E}. The previous source 30b4e260 failed during helper compilation with E0034: a newly imported diagnostic Write trait reached an original child module through its existing super glob and made the original Read::by_ref call ambiguous. That actual failed preparation took 14.717660 seconds and produced no product manifest or business result; all of it remains in the v12 archive.

This successor removes the diagnostic Write trait import from the main historical client and from the historical source parent that also has a child super glob. Its 29 fixed write_all calls and one numeric write_fmt call use fully qualified std::io::Write instead. The two leaf diagnostic modules remain unchanged. The original inputs module, its Read::by_ref call and every reader predicate remain byte-identical; the diagnostic bytes, including the numeric line's final newline, are preserved. The original parent review and post-format mechanical audit are archived. The additional independent frozen-source audit is retained byte-for-byte as v13-INDEPENDENT-REVIEW.json (SHA-256 56af8a97d7965c9efd1d79a99ca44862bd26c0260f15fab3ecea9c9fbc674a53). The publication-only builder adds that completed review to the planned evidence files; it does not modify the frozen run adapter or source.

The underlying v12 diagnostic observations remain at the original client, operation, Dataset and source-caller error boundaries. Original Results, postcheck priority, fence/drop, identity/authentication, deadlines, MAX_READS=64 and all frame/component bounds remain unchanged. No extra wire exchange or trial business execution was added. v11's 9/9 related codec/frame results and its measured 19,114-byte first Task reply remain attached to e21ca2d9 and are not inherited as passes or byte measurements on this candidate.

| Exact selected original case | Actual outcome |
|---|---|
{chr(10).join(rows)}

Observed Root error stages: {labels}. Observed daemon stages: {", ".join(summary["observed_daemon_stages"]) or "none recorded"}. First Task numeric observations from this candidate: {json.dumps(summary["task_reply_measurements"],sort_keys=True)}. Read-limit observations: {json.dumps(summary["client_limit_observations"],sort_keys=True)}. The complete selected stderr originals remain in the explicit archive and bounded safe projections in v13-SUMMARY.json. Per-process order is preserved; separate process files do not establish global temporal order. Missing tags cannot prove every unlabelled condition passed.

{product_note}

The adapter permits one original evaluated-NoUpdate whole-cold profile with retries zero; it permits the original Adopt cold profile once only after NoUpdate passes. The unchanged v11 codec/frame regressions were not rerun here. Earlier source-specific qualifications stay with their original source and actual binary records.

The safe v13 archive is {arc.name}, {info["bytes"]:,} bytes, SHA-256 {info["sha256"]}; all {len(members)} regular members were checked against the original manifest before publication. This evidence-only child is separately identified from the actually attempted source.

All real command timings and failed preparation or business costs are retained. Unknown CPU/GPU/energy/API/monetary costs remain null, not zero. Existing cold profiles inspect retained C; they do not execute a fresh D. Independent-controller certification, FinalUse, settlement and complete E6 qualification remain unestablished.
"""
readme=dest/"README.md";readme.write_text(readme.read_text()+extra);names["README.md"]=hashlib.sha256(readme.read_bytes()).hexdigest()
subprocess.run(["git","-C",str(R),"add","--",P],check=True)
changed=git(R,"diff","--cached","--name-only").splitlines();assert set(changed)=={P+"/"+n for n in names}
assert git(R,"diff","--name-only")=="" and git(R,"rev-parse","HEAD")==D
subprocess.run(["git","-C",str(R),"-c","user.name=Codex","-c","user.email=codex@openai.com","commit","-m","Archive exact historical diagnostic scope repair and owner result"],check=True)
head=git(R,"rev-parse","HEAD");tree=git(R,"rev-parse","HEAD^{tree}")
assert git(R,"rev-parse","HEAD^")==D and not git(R,"status","--porcelain")
for name,sha in names.items():
 data=subprocess.check_output(["git","-C",str(R),"show",head+":"+P+"/"+name]);assert hashlib.sha256(data).hexdigest()==sha
bundle=W/"native-owner-v13-from-evidence.bundle"
subprocess.run(["git","-C",str(R),"-c","pack.threads=1","bundle","create",str(bundle),"HEAD","^"+E],check=True)
assert git(S,"rev-parse","HEAD")==D and not git(S,"status","--porcelain")
result=dict(status="created",head=head,tree=tree,parent=D,base=E,repo=str(R),tested_source=D,tested_tree=summary["source_tree"],files=changed,archive=archive_record,bundle=str(bundle),bundle_bytes=bundle.stat().st_size,bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),observed_static_stages=summary["observed_static_stages"],observed_daemon_stages=summary["observed_daemon_stages"],source_unchanged=True,finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
(W/"native-owner-v13-publication.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result),flush=True)
