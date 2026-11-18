"""Publish exact failed and repaired source-gate evidence as one metadata-only child."""
import datetime,hashlib,json,pathlib,shutil,subprocess,tarfile
W=pathlib.Path("/home/qq/e6-owner-current-20261118-556e5fc18a5b");S=W/"source";Q=W/"source-closure-v14"
D="a6f9e8064f83680134af168e0500048b6942ddfd";TREE="894a8e5ff061980adec9825f0e519b3aba8c454e"
FAILED="570b46e1cd0d9093f37dbb31bd157825971e899d";BASE="3299c1d3318ff157f4948dee89b7939ef67b515c"
R=W/"evidence-publisher-v15";P="docs/cell-experiments/e6-native-owner-20261118"
def git(root,*args):return subprocess.check_output(["git","-C",str(root),*args],text=True).strip()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
assert git(S,"rev-parse","HEAD")==D and git(S,"rev-parse","HEAD^{tree}")==TREE and not git(S,"status","--porcelain")
assert git(S,"rev-list","--reverse",BASE+".."+D).splitlines()==[FAILED,D]
info=json.loads((W/"public-evidence-v15-build-result.json").read_text())
assert info["source_head"]==D and info["source_tree"]==TREE and info["source_unchanged"]
arc=pathlib.Path(info["archive"]);assert sha(arc)==info["archive_sha256"]
manifest_path=pathlib.Path(info["manifest"]);manifest=json.loads(manifest_path.read_text());assert sha(manifest_path)==info["manifest_sha256"]
with tarfile.open(arc,"r:xz") as tar:
 members=tar.getmembers();expected={row["path"]:row for row in manifest["files"]}
 assert len(members)==info["regular_files"]==len(expected)+1
 assert len({x.name for x in members})==len(members) and all(x.isfile() and x.name.startswith("native-owner-v14-v15/") and ".." not in pathlib.Path(x.name).parts for x in members)
 assert {x.name[len("native-owner-v14-v15/"):] for x in members}==set(expected)|{"manifest.json"}
 assert tar.extractfile("native-owner-v14-v15/manifest.json").read()==manifest_path.read_bytes()
 for name,row in expected.items():
  data=tar.extractfile("native-owner-v14-v15/"+name).read()
  assert len(data)==row["bytes"] and hashlib.sha256(data).hexdigest()==row["sha256"],name
s14=json.loads((W/"public-evidence-v14-v15/v14-SUMMARY.json").read_text())
s15=json.loads((W/"public-evidence-v14-v15/v15-SUMMARY.json").read_text())
assert s15["successful"] and s15["product_preparation"]["passed"]
subprocess.run(["git","-C",str(S),"worktree","add","--detach",str(R),D],check=True)
dest=R/P;assert dest.is_dir();names={}
copies=[
(arc,arc.name),(manifest_path,"v14-v15-MANIFEST.json"),
(W/"public-evidence-v14-v15/v14-SUMMARY.json","v14-SUMMARY.json"),
(W/"public-evidence-v14-v15/v15-SUMMARY.json","v15-SUMMARY.json"),
(W/"source-closure-v14-evidence/freeze.json","v14-source-candidate.json"),
(W/"source-closure-v15-evidence/freeze.json","v15-source-candidate.json"),
(W/"source-closure-v15-evidence/products/product-manifest.json","v15-compiler-products.json"),
(W/"source-closure-v15-evidence/products/root-elf-fixed-diagnostic-tags.json","v15-ROOT-ELF-STAGES.json"),
(W/"historical-read-budget-v13-e1-20261118-556e/SUCCESSFUL_FRESH_PATH_READ_ACCOUNTING.json","v13-READ-BUDGET-ACCOUNTING.json"),
(pathlib.Path(__file__),"v15-publication-builder.py"),
(W/"historical-task-diagnostic-qa-v15-e1-v2/FROZEN_REVIEW.json","v15-FROZEN-HELPER-REVIEW.json")]
for src,name in copies:
 assert not (dest/name).exists()
 shutil.copyfile(src,dest/name);names[name]=sha(dest/name)
record=dict(info,verified_regular_members=len(members),archive_manifest_sha256=sha(manifest_path),source_tested=D,source_tree_tested=TREE,failed_source_retained=FAILED,evidence_scope="Metadata-only child; no source tests or product builds are attributed to this documentation commit.")
(dest/"v15-ARCHIVE.json").write_text(json.dumps(record,indent=2)+"\n");names["v15-ARCHIVE.json"]=sha(dest/"v15-ARCHIVE.json")
products=s15["compiler_products"]["artifacts"];qa=s15["unittest"];sweep=s15["protected_file_sweep"];prep=s15["product_preparation"]
extra=f"""
## v14–v15: executable source gates and exact product identity

The latest native business observation remains **BLOCKED** on source 978719e6137cc1fe9a64bcde7795cd478b2f293e: the historical client attempted request 65 against the original maximum 64. These successors repair source gates and diagnostics. No new NoUpdate, Adopt, libtest, model, or fresh D executes here.

The exact linear history is {BASE} → {FAILED} → {D}, tree {TREE}. The first successor changed only CALLERS and source-QA files and retained the same Rust tree as 978719e. Its failed result remains v14. The final successor changes three Rust files, CALLERS and three related QA files. This following documentation child has no inherited test identity.

| Exact source and scope | Actual result | Measured wall scope |
|---|---|---:|
| Unmodified original two QA modules on {BASE[:8]} | 20 cases, 69 error events including subtests | 1.071733924 s |
| Scoped v14 QA on {FAILED[:8]} | 143 cases, 24 error events across 16 cases, 0 assertion failures/skips; protected sweep stopped early | {s14["whole_qa_execution_seconds"]:.9f} s |
| Scoped v15 QA on {D[:8]} | {qa["tests_run"]}/{qa["tests_run"]} passed, 0 errors/failures/skips | {s15["whole_qa_execution_seconds"]:.9f} s |
| Original protected-file sweep on {D[:8]} | All {sweep["protected_rows"]} rows checked and passed | {sweep["duration_seconds"]:.9f} s, included above |
| Real two-product preparation on {D[:8]} | Compiled, pinned from actual compiler-artifact records and independently hashed | {prep["whole_product_preparation_seconds"]:.9f} s |

### What the repair preserves

The v14 failures exposed three concrete issues. The original function-order verifier requires at least two markers but the default wrapper row supplied one. The strict typed resolver cannot infer the historical Lane through its take/ok_or_else/inspect_err chain. Fourteen inline diagnostics also conflicted with the complete historical reader's original whole-file write prohibition.

The original verifier and typed resolver remain unchanged. The default wrapper is pinned as the complete original call, including requested_end and 16_384, with two real body markers and a top-level requirement. Only the historical local variable receives an explicit Lane annotation; the initializer, type and error propagation remain unchanged. Its removal must still fail the original typed verifier. The unrelated CURRENT reader and row270 remain byte-identical.

All 13 original reader forbidden patterns, including write_all, remain. The existing 14 inspect_err sites now call one private child module through a fieldless closed enum. The helper accepts no task or error data, selects only the original fixed byte strings and ignores the result of its sole stderr UFCS write. Seven new QA cases protect its exact executable shape, actual literal positions, private module/imports, original 5+9 call distribution, each observer removal, extra calls/aliases/function pointers, dynamic payloads, comment/string spoofing, write prohibition, caller boundary and inventory. The optional trailing comma covers the actual one-argument Rust formatting; extra-argument and tuple controls remain rejected.

The helper is inside the original codex-rs source inventory. All 1,123 existing boundary records remain unchanged relative to v14; one unique helper boundary, one inventory entry and two protected rows were added. Existing complete-task test/mutation topology remains. One rustfmt receiver line break is pinned exactly in CALLERS because the original verifier uses code.find; the original QA token matcher already accepts the whitespace and was unchanged.

The failed EOF check (exit 2), rejected wrong-file row270 proposal, initially narrow observer regex, formatter PATH preparation failure, and two rejected marker-locator assumptions are retained with their exact scopes. Static proposal defects are not relabelled as executed QA failures. The complete failed 570b run is retained alongside the passing a6f9 run.

### Actual product provenance

Both products were built on {D} through the original build-and-pin routine with two Cargo jobs, locked offline dependencies and identical source snapshots before/after. No earlier executable substitutes for a fresh compiler record.

| Product | Bytes | SHA-256 |
|---|---:|---|
| hepta-authority-host | {products["hepta-authority-host"]["bytes"]} | {products["hepta-authority-host"]["sha256"]} |
| codex-hepta-agentd | {products["codex-hepta-agentd"]["bytes"]} | {products["codex-hepta-agentd"]["sha256"]} |

All 14 original diagnostic byte strings were found in the pinned Root ELF during a stable full hash read. The exact receipts are v15-compiler-products.json and v15-ROOT-ELF-STAGES.json. This proves compilation and executable identity; no business execution follows from it.

### Budget and qualification remain explicit

v13-READ-BUDGET-ACCOUNTING.json contains the independently reviewed static audit bound to 978719e. It accounts for 64 successful startup requests (62 Task, one Trust and one PostA), then identifies attach_sources as the next static call requiring requests 65–66. This agrees with the observed refusal at 65; it is not a runtime stack. A closed whole-session bound covering fresh NoUpdate, Adopt, cold recovery and all permitted consumers is not established. MAX_READS remains 64; no arbitrary 128/256 replacement was made.

Authentication, deadlines, identity/freshness, refusal state, original Results/postchecks and request/response limits remain unchanged by v15. The v11 Task capacity revision and its 9/9 tests, the old 843 949-case result and all native attempts retain their original sources. The 150 scoped cases and 892-row protected sweep are not a new full caller sweep.

The recorded native attempt wall scopes v1–v13 total 3283.672103214776 seconds. Separate QA, research, publication and unmeasured preparation are excluded. Nested stages are not added again; the QA and product preparation scopes above are separate and ran concurrently. Unknown CPU, energy, API and monetary costs remain null.

The explicit archive {arc.name} contains {info["regular_files"]} regular members, {info["archive_bytes"]:,} bytes, SHA-256 {info["archive_sha256"]}. Every member was checked against v14-v15-MANIFEST.json. Only source, patches, stdout/stderr, JUnit, metadata, costs and static reviews are included; private keys, SourceInputs and authority-input directories are excluded.

Complete original-owner NoUpdate/adoption, independent-controller authorization, fresh D, FinalUse and settlement qualification remain unestablished.
"""
readme=dest/"README.md";readme.write_text(readme.read_text()+extra);names["README.md"]=sha(readme)
subprocess.run(["git","-C",str(R),"add","--",P],check=True)
changed=git(R,"diff","--cached","--name-only").splitlines()
assert set(changed)=={P+"/"+name for name in names} and not git(R,"diff","--name-only")
subprocess.run(["git","-C",str(R),"-c","user.name=Codex","-c","user.email=codex@openai.com","commit","-m","Archive failed source gates and verified closed diagnostic successor"],check=True)
head=git(R,"rev-parse","HEAD");tree=git(R,"rev-parse","HEAD^{tree}")
assert git(R,"rev-parse","HEAD^")==D and not git(R,"status","--porcelain")
linear=git(R,"rev-list","--reverse",BASE+".."+head).splitlines();assert linear==[FAILED,D,head]
for name,digest in names.items():
 assert hashlib.sha256(subprocess.check_output(["git","-C",str(R),"show",head+":"+P+"/"+name])).hexdigest()==digest
bundle=W/"native-owner-v15-from-evidence.bundle"
subprocess.run(["git","-C",str(R),"-c","pack.threads=1","bundle","create",str(bundle),"HEAD","^"+BASE],check=True)
assert git(S,"rev-parse","HEAD")==D and not git(S,"status","--porcelain")
result={"status":"created","source_head":D,"source_tree":TREE,"failed_source":FAILED,"evidence_head":head,"evidence_tree":tree,"base":BASE,"expectedlinear":linear,"bundle":str(bundle),"bundle_ref":"HEAD","bundle_bytes":bundle.stat().st_size,"bundle_sha256":sha(bundle),"archive":record,"archive_manifest":str(manifest_path),"archive_manifest_sha256":sha(manifest_path),"repo":str(R),"files":changed,"file_sha256":names,"source_unchanged":True,"native_business_executed":False,"finished":datetime.datetime.now(datetime.timezone.utc).isoformat()}
(W/"native-owner-v15-publication.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2))
