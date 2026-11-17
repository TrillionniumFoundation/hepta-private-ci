"""Read-only static review of resource operation 02; imports no runtime modules."""
import ast, copy, hashlib, json, stat, zipfile
from pathlib import Path
ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
SRC = ROOT / "research-reschedule-source-02"
OUT = ROOT / "operations/research-reschedule-independent-review-02"
OUT.mkdir(exist_ok=False)
def digest(raw): return hashlib.sha256(raw).hexdigest()
def read(path):
    p = Path(path)
    for q in [p, *p.parents]:
        if q.is_symlink(): raise ValueError("symlink")
    if not stat.S_ISREG(p.lstat().st_mode): raise ValueError("nonregular")
    return p.read_bytes()
def js(path): return json.loads(read(path))
def emit(name, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    with (OUT / name).open("xb") as stream: stream.write(raw)
    return digest(raw)
handoff = js(SRC / "HANDOFF_02.json")
declared = js(SRC / "DECLARED_LITERAL_REPLACEMENTS_02.json")
new_launcher_sha = "205a72dbe8adab915c8f7c9225a3d4effb0f399f80ba167cd5786213aa7eda00"
new_diag_sha = "28d82e170ab0720fb6b453275a80b4bf1eebc1e987ed1ae3bd935bb00a77a071"
specs = {
 "operations/launch_qwen_research_owned_v1_02.py": (
  ROOT / "operations/launch_qwen_research_owned_v1.py",
  "4f647ae7e7cc5f5f0d04b597db10f0a68b946ecff04821651a16633bfe02eab0",
  {"research-sft-01":"research-sft-02", "owned-research-sft-01":"owned-research-sft-02",
   "RESEARCH_LAUNCH_FREEZE_01.json":"RESEARCH_LAUNCH_FREEZE_02.json",
   "research-diagnostic-v1-source/qwen_research_diagnostic_v1.py":"research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py",
   "research-diagnostic-01":"research-diagnostic-02", "owned-research-diagnostic-01":"owned-research-diagnostic-02",
   "RESEARCH_POSTRUN_LAUNCH_FREEZE_01.json":"RESEARCH_POSTRUN_LAUNCH_FREEZE_02.json"}),
 "research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py": (
  ROOT / "operations/research-diagnostic-v1-source/qwen_research_diagnostic_v1.py",
  "c43ff3c5f9bc99c5825a96e0f4b4020d361489d2ffa3ae31bffe49f03ddb6f91",
  {"research-diagnostic-01":"research-diagnostic-02","research-sft-01":"research-sft-02"}),
 "operations/archive_qwen_research_v1_03.py": (
  ROOT / "operations/archive_qwen_research_v1_02.py",
  "658438b68dff7a039a9631beb9e07ded8e7f56de23912672f868a531e063c3b2",
  {"research-sft-01":"research-sft-02","research-diagnostic-01":"research-diagnostic-02",
   "operations/launch_qwen_research_owned_v1.py":"operations/launch_qwen_research_owned_v1_02.py",
   "4f647ae7e7cc5f5f0d04b597db10f0a68b946ecff04821651a16633bfe02eab0":new_launcher_sha,
   "owned-research-sft-01":"owned-research-sft-02","owned-research-diagnostic-01":"owned-research-diagnostic-02",
   "research-diagnostic-v1-source":"research-diagnostic-v1-source-02"})}
results, before = {}, {}
for target, (source, oldsha, replacements) in specs.items():
    oldraw, newraw = read(source), read(SRC / target)
    before[str(source)], before[str(SRC / target)] = digest(oldraw), digest(newraw)
    if digest(oldraw) != oldsha or digest(newraw) != handoff["deployment"][target]["sha256"]:
        raise ValueError("source identity changed")
    if {r["before"]:r["after"] for r in declared[target]} != replacements:
        raise ValueError("undeclared or unexpected replacement")
    mapped = oldraw.decode()
    for old, new in replacements.items():
        if mapped.count(json.dumps(old)) != 1:
            raise ValueError("literal multiplicity differs")
        mapped = mapped.replace(json.dumps(old), json.dumps(new))
    if mapped.encode() != newraw: raise ValueError("nonliteral raw edit")
    class MapConstants(ast.NodeTransformer):
        def visit_Constant(self, node):
            if type(node.value) is str and node.value in replacements:
                node.value = replacements[node.value]
            return node
    left = MapConstants().visit(ast.parse(oldraw))
    right = ast.parse(newraw)
    if ast.dump(left, include_attributes=False) != ast.dump(right, include_attributes=False):
        raise ValueError("AST differs beyond allowed constants")
    results[target] = {"old_sha256":oldsha,"new_sha256":digest(newraw),
                      "literal_changes":len(replacements),"raw_exact_declared_replacements":True,
                      "normalized_AST_equal":True}
oldrule_path = ROOT / "operations/research-diagnostic-v1-source/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json"
newrule_path = SRC / "research-diagnostic-v1-source-02/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json"
oldrule, newrule = js(oldrule_path), js(newrule_path)
if digest(read(oldrule_path)) != "93dff768e527af37551a71b3cf89c47b2b8ad83dae461e11d7a8214cfc0e5ddc":
    raise ValueError("old rule changed")
allowed = {"created_at_ns","diagnostic_source","resource_reschedule"}
if {k for k in oldrule.keys() | newrule.keys() if oldrule.get(k) != newrule.get(k)} != allowed:
    raise ValueError("unexpected rule edit")
normalized = copy.deepcopy(newrule)
normalized.pop("resource_reschedule")
normalized["created_at_ns"] = oldrule["created_at_ns"]
normalized["diagnostic_source"]["sha256"] = oldrule["diagnostic_source"]["sha256"]
if normalized != oldrule or newrule["diagnostic_source"]["sha256"] != new_diag_sha:
    raise ValueError("rule semantics changed")
modules = {
 "research_sft_contract_v1.py":"2ae7c2496ee58ce71cbda7a6d245e65550a76104cbc1359aca06d005f6b16f2c",
 "research_sft_train_v1.py":"a95ccfde26ebb3f32ef1e3fb2df3f1b4d35ab27b4ae42edf8858dc315d2f9972",
 "research_sft_execution_v1.py":"704e7a7e157412d9ce8a7523c31ed635269ead41d40f1720c591dccc4d67f2cd",
 "run_research_sft_v1.py":"0fba8d8800ba3012a55055d7a84c4bfa156d0f96c64e0bd488211f188cbe256c"}
for filename, wanted in modules.items():
    path = ROOT / "research-sft-v1-source-working" / filename
    actual = digest(read(path))
    if actual != wanted: raise ValueError("research module changed")
    before[str(path)] = actual
    if b"research-sft-01" in read(path) or b"research-diagnostic-01" in read(path):
        raise ValueError("old output hard-coded in research module")
bindings = js(SRC / "INPUT_BINDINGS_02.json")
for path, identity in bindings["original_files"].items():
    raw = read(path)
    if len(raw) != identity["bytes"] or digest(raw) != identity["sha256"]:
        raise ValueError("bound prior original changed")
    before[path] = digest(raw)
prior_dir = ROOT / "research-final-evidence-01"
meta = newrule["resource_reschedule"]
for path, wanted in meta["prior_artifact_sha256"].items():
    if digest(read(prior_dir / path)) != wanted: raise ValueError("prior binding differs")
prior_result = js(prior_dir / "research-sft-01/RESULT.json")
prior_freeze = js(prior_dir / "research-sft-01/FREEZE.json")
if meta["prior_operation_id"] != prior_freeze["operation_id"] or meta["prior_status"] != prior_result["status"]:
    raise ValueError("prior identity differs")
if not meta["prior_global_ledger_totals_unknown"] or not prior_result["ledger"]["global_totals_unknown"]:
    raise ValueError("prior unknown tail lost")
if meta["new_independent_sample_increment"] != 0 or meta["prior_outputs_overwritten"] or meta["automatic_retry"]:
    raise ValueError("reschedule boundary differs")
packages = {}
for name, identity in handoff["packages"].items():
    raw = read(SRC / name)
    if len(raw) != identity["bytes"] or digest(raw) != identity["sha256"]:
        raise ValueError("package bytes differ")
    with zipfile.ZipFile(SRC / name) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("package CRC/member duplication")
        if len(archive.namelist()) != identity["members"]:
            raise ValueError("package count differs")
        if name.endswith("RUNTIME_02.zip") and set(archive.namelist()) != set(handoff["deployment"]):
            raise ValueError("unexpected runtime members")
        for member in archive.namelist():
            if archive.read(member) != read(SRC / member):
                raise ValueError("package member differs")
        if any(info.file_size >= 512000 for info in archive.infolist()):
            raise ValueError("oversize member")
    packages[name] = identity
for path, wanted in before.items():
    if digest(read(path)) != wanted: raise ValueError("source changed during review")
review = {"schema":"hepta.research-reschedule-independent-review.v1",
 "status":"NO_BLOCKER_FOUND_IN_STATIC_PATH_AND_BINDING_REVIEW",
 "review_scope":"source bytes, AST, rules semantics, exact prior bindings, packages; not runtime execution or GPU availability",
 "literal_comparisons":results, "rule_changed_top_level_fields":sorted(allowed),
 "rule_semantics_unchanged":True,"four_research_modules_unchanged":modules,
 "prior01_partial_failure_and_costs_preserved":True,"prior_global_unknown_totals_preserved":True,
 "operation02_is_post_failure_resource_reschedule":True,"new_independent_samples":0,
 "tests_executed":0,"model_calls":0,"reference_calls":0,"deployments":0,
 "source_modified":False,"frozen_inputs_before_after_equal":True,
 "packages":packages,"new_rules_sha256":digest(read(newrule_path)),
 "original01_memory_review_zip_sha256":"95277978a7935d46754cfa863fbb88f5071628b07c054e8dc22cd6bf70151ad4",
 "remaining_root_responsibilities":[
 "Fresh GPU resource preflight and unique owned intent; no exclusive GPU reservation is proved by static review.",
 "Freeze actual operation02 argv/source/rule identities before root alone launches.",
 "Report both operation01 and operation02 raw ledgers, measured subtotals and unknown tails; diagnostics remain per operation.",
 "Retain all original operation01 evidence; no new sample or preregistered-first-run claim."],
 "publication_source":"research-reschedule-source-02; input files unchanged"}
review_sha = emit("REVIEW_02.json",review)
print(json.dumps({"review_path":str(OUT/"REVIEW_02.json"),"review_sha256":review_sha,
 "status":review["status"],"literal_counts":[results[x]["literal_changes"] for x in specs],
 "runtime_zip_sha256":packages["RESEARCH_RESCHEDULE_RUNTIME_02.zip"]["sha256"],
 "source_zip_sha256":packages["RESEARCH_RESCHEDULE_SOURCE_02.zip"]["sha256"]},sort_keys=True),flush=True)
