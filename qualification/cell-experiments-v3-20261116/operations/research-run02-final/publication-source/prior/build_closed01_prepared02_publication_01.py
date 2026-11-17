"""Package closed Run01 and frozen Run02 preparation, without reading live outputs."""
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
OUT = ROOT / "research-closed01-prepared02-publication-01"
WORK = ROOT / "publication-native-01"
BASE = "36ec275d56bb7e40d671443e2ed6e0b154c0a489"
PREFIX = "qualification/cell-experiments-v3-20261116/operations/research-run01-and-run02-preparation/"
EX, RR, MR, RS, IR, DR, PF = [ROOT / p for p in [
    "research-final-export-01", "research-results-review-01",
    "operations/research-run01-memory-review-01", "research-reschedule-source-02",
    "operations/research-reschedule-independent-review-02", "research-deployment-02",
    "research-preflight-02"]]
OPS = ROOT / "operations"
ops_observation = json.loads(sys.argv[1])
pending02 = {"export_research_results_02.py", "inspect_research_terminal_02.py",
             "launch_research_postrun_02.py", "observe_research_run_02.py",
             "prepare_research_postrun_02.py"}
selected_ops = {r["name"]: r for r in ops_observation["operations"]
                if not r["direct_git_paths"] and not r["in_original_run01_zip"]
                and r["name"] not in pending02}
payload, origins, inputs, groups, skipped = {}, {}, {}, [], []


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def js(v):
    return (json.dumps(v, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def line(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def read(p, expected=None):
    allow = any(p.is_relative_to(d) for d in [EX, RR, MR, RS, IR, DR, PF])
    allow = allow or p in [ROOT / "FORMAT_06.json",
        ROOT / "research-publication-source-01/NATIVE_FINAL_PLAN_01.json"]
    allow = allow or (p.parent == OPS and p.name in selected_ops)
    if not allow or p.is_symlink() or not p.is_file():
        raise ValueError("input outside closed/prepared allowlist: " + str(p))
    raw = p.read_bytes()
    ident = {"bytes": len(raw), "sha256": sha(raw)}
    if expected and ident["sha256"] != expected:
        raise ValueError("input SHA differs: " + str(p))
    if str(p) in inputs and inputs[str(p)] != ident:
        raise ValueError("input changed during read")
    inputs[str(p)] = ident
    return raw


def put(n, raw, origin):
    n = PREFIX + n
    if n in payload or len(raw) >= 512000:
        raise ValueError("duplicate or oversized payload")
    if any(p.startswith(".hepta-") for p in Path(n).parts):
        raise ValueError("standalone transport temporary file rejected")
    if n.endswith((".zip", ".bin")) and len(raw) > 322560:
        raise ValueError("binary part exceeds bound")
    payload[n], origins[n] = raw, origin
    return n


def cp(p, n, expected=None):
    return put(n, read(p, expected), str(p))


def group(title, names, note=""):
    groups.append({"title": title, "files": names, "note": note})


def git(*argv):
    p = subprocess.run(["git", *argv], cwd=WORK, capture_output=True, timeout=60)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout


def fileset(root):
    result = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("symlink in selected closed source")
        if not p.is_file():
            continue
        name = p.relative_to(root).as_posix()
        if any(x.startswith(".hepta-") for x in Path(name).parts):
            skipped.append({"root": str(root), "path": name, "reason": "temporary transport metadata"})
        else:
            result.append(p)
    return result


def zipread(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    if z.testzip() or len(z.namelist()) != len(set(z.namelist())):
        raise ValueError("ZIP CRC or membership differs")
    for x in z.infolist():
        n = Path(x.filename)
        if n.is_absolute() or ".." in n.parts or stat.S_ISLNK(x.external_attr >> 16):
            raise ValueError("unsafe ZIP member")
    return z


def zipbytes(contents):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n, raw in sorted(contents.items()):
            info = zipfile.ZipInfo(n, (2026, 11, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, raw)
    raw = stream.getvalue()
    with zipread(raw) as z:
        if set(z.namelist()) != set(contents) or any(z.read(n) != b for n, b in contents.items()):
            raise ValueError("snapshot original bytes differ")
    return raw


def snapshot(root, selected, dest, filename):
    contents = {p.relative_to(root).as_posix(): read(p) for p in selected}
    raw = zipbytes(contents)
    paths, parts = [], []
    for i, offset in enumerate(range(0, len(raw), 322560)):
        data = raw[offset:offset+322560]
        n = filename if len(raw) <= 322560 else filename + ".part%03d.bin" % i
        paths.append(put(dest + "/" + n, data, "new lossless ZIP of exact original files"))
        parts.append({"path": n, "bytes": len(data), "sha256": sha(data)})
    if b"".join(payload[n] for n in paths) != raw:
        raise ValueError("snapshot part reconstruction differs")
    m = {"schema": "hepta.closed-prepared-source-snapshot.v1", "source_root": str(root),
        "archive_filename": filename, "archive_bytes": len(raw), "archive_sha256": sha(raw),
        "parts": parts, "members": {n: {"bytes": len(b), "sha256": sha(b)} for n, b in contents.items()},
        "source_modified": False, "new_model_or_test_execution": False,
        "atomic_snapshot_claimed": False}
    paths.append(put(dest + "/MANIFEST.json", js(m), "generated exact member and part identities"))
    paths.append(put(dest + "/RESTORE.md", b"""# Restore exact original records

Concatenate manifest parts in order. Verify each part and the whole ZIP by
byte count and SHA256, then check ZIP CRC and every member's path, size and
SHA256 before extraction to a new directory. Preserve original receipt bytes
and recorded absolute paths. No new execution is implied by restoration.

This snapshot packages closed records or frozen preparation files. Readable
copies elsewhere duplicate evidence for review, never calls, cost or samples.
""", "generated lossless restoration instructions"))
    return paths


if git("rev-parse", "HEAD").decode().strip() != BASE or git("status", "--porcelain=v1").strip():
    raise ValueError("native publication base or clean state differs")
prior = json.loads(read(ROOT / "research-publication-source-01/NATIVE_FINAL_PLAN_01.json",
    "341eba883c2bb4cc205d6133fd47e7223138dff796287ef5bd0c951a8e357d85"))
core = {x.split("\t", 1)[1]: x.split("\t", 1)[0].split()[2]
        for x in git("ls-tree", "-r", "HEAD", "--", "scripts/cell_experiments").decode().splitlines()
        if x.endswith(".py")}
if len(core) != 64 or core != prior["expected_complete_core_git_blobs"]:
    raise ValueError("64 frozen core Git blobs differ")

traw = read(EX / "TRANSFER_MANIFEST.json",
    "785f5f4c4bfbb9f5c68131cfe1116c870274dd0cb7ec9473c671ebe38af039cf")
tm = json.loads(traw)
if tm["member_count"] != 694:
    raise ValueError("closed original member count differs")
for k in ["archive", "members"]:
    item = tm[k]
    whole = read(EX / item["transport_path"], item["sha256"])
    parts = [read(EX / p["path"], p["sha256"]) for p in item["parts"]]
    if len(whole) != item["bytes"] or b"".join(parts) != whole:
        raise ValueError("closed export part bytes differ")
araw = read(EX / "qwen-research-sft.zip",
    "3b6b10a9bfdcb2cf3c7df965dd45e5cac3143463b3b8a615ff544aeb417b437a")
mraw = read(EX / "MEMBERS.jsonl",
    "336e7308d967918413b0c0fc6b8e5e2acefc16476e70b419f100b3752731afa5")
mrows = [json.loads(x) for x in mraw.splitlines()]
az = zipread(araw)
if az.namelist() != [m["path"] for m in mrows]:
    raise ValueError("closed ZIP exact member order differs")
for m in mrows:
    data = az.read(m["path"])
    if len(data) != m["bytes"] or sha(data) != m["sha256"]:
        raise ValueError("closed ZIP member SHA differs")
group("Preserve complete closed research01 archive and original export receipt",
    [cp(EX / "TRANSFER_MANIFEST.json", "run01/export/TRANSFER_MANIFEST.json"),
     cp(EX / "RESTORE.txt", "run01/export/RESTORE.txt"),
     *[cp(EX / p["path"], "run01/export/" + p["path"]) for p in tm["archive"]["parts"]],
     cp(EX / "STARTED.json", "run01/export-operation/STARTED.json")])
group("Preserve the exact closed research01 member identity index",
    [cp(EX / p["path"], "run01/export/" + p["path"]) for p in tm["members"]["parts"]],
    "The original 694-row member index stays intact under the 800-line ceiling.")

group("Preserve the exact independent closed-result review program",
    [cp(RR / "review_closed_research01.py", "run01/result-review/review_closed_research01.py",
        "265f77d60233e641bbe84b14ea7d01965bb28a4a7edd0884c20db5e233c39204")])
rlist = fileset(RR)
if {p.name for p in rlist} != {"RESULT_REVIEW_01.md", "CLOSED_RESULT_REVIEW_01.json",
    "REVIEW_EXECUTION_RECEIPT_01.json", "review_closed_research01.py", "REVIEW_PLAN.md"}:
    raise ValueError("closed review file set changed")
read(RR / "CLOSED_RESULT_REVIEW_01.json",
     "f5ed93d4013baa560ef781ae2c36b0bd502841cb1d5be13a83f1f9c8a8f159a3")
group("Preserve closed-result conclusions and complete original review evidence",
    [cp(RR / "RESULT_REVIEW_01.md", "run01/result-review/RESULT_REVIEW_01.md",
        "c4e404ab6b791292b479cfc4b09ac0932af27e605bf7bc3a5e432e4ce9d12685"),
     cp(RR / "REVIEW_EXECUTION_RECEIPT_01.json", "run01/result-review/REVIEW_EXECUTION_RECEIPT_01.json",
        "e2386d009d77f8da614b2f3e43c2861e75ffae1caac25caa565ffe0f7f5f9b99"),
     *snapshot(RR, rlist, "run01/result-review/originals-archive", "CLOSED_RESULT_REVIEW_ORIGINALS_01.zip")])
group("Preserve the post-launch result-review checklist and its stated limits",
    [cp(RR / "REVIEW_PLAN.md", "run01/result-review/REVIEW_PLAN.md",
        "157a739df8d8ba8c8926a1d7151e1caede5c23eee125e1912d509e89a665ee9c")])

memraw = read(MR / "research-run01-memory-review-01.zip",
    "95277978a7935d46754cfa863fbb88f5071628b07c054e8dc22cd6bf70151ad4")
with zipread(memraw) as z:
    memnames = set(z.namelist())
    if len(memnames) != 43:
        raise ValueError("memory review original ZIP members differ")
    for n in memnames:
        if z.read(n) != read(MR / n):
            raise ValueError("memory review retained original differs")
group("Preserve memory admission findings and exact read-only review sources",
    [cp(MR / n, "run01/memory-review/" + n) for n in [
        "REVIEW.json", "README.md", "build_readonly_review.py", "source_recheck.py"]])
if inputs[str(MR / "REVIEW.json")]["sha256"] != "14b2d870b74008fc30d9b81e43772d0d2e3065db5e4a775a2059ad277ada768a":
    raise ValueError("memory review conclusion differs")
extra = [p for p in fileset(MR) if p.relative_to(MR).as_posix() not in memnames
         and p.name != "research-run01-memory-review-01.zip"]
group("Preserve complete memory-review originals and actual transfer terminals",
    [put("run01/memory-review/research-run01-memory-review-01.zip", memraw, "exact original 43-member ZIP"),
     *snapshot(MR, extra, "run01/memory-review/transfer-and-terminal-originals", "MEMORY_REVIEW_EXTRA_ORIGINALS_01.zip"),
     cp(MR / "process_identity.py", "run01/memory-review/process_identity.py")])

sr = read(RS / "RESEARCH_RESCHEDULE_SOURCE_02.zip",
    "f142b91ebed199e1142c0b59e0e12f920d4bf9ea51fd4899d8cd4f85c7928d60")
rt = read(RS / "RESEARCH_RESCHEDULE_RUNTIME_02.zip",
    "2fed6d1998e9a3737cae70af876e3d53bfc410dc0af2fd1ed7cbbd4912fc15a7")
for raw, count in [(sr, 20), (rt, 4)]:
    with zipread(raw) as z:
        if len(z.namelist()) != count:
            raise ValueError("reschedule original ZIP membership differs")
        for n in z.namelist():
            if z.read(n) != read(RS / n):
                raise ValueError("reschedule original source bytes differ")
        if count == 20:
            source_names = set(z.namelist())
respaths = {}
def res(n):
    if n not in respaths:
        respaths[n] = cp(RS / n, "run02/source/" + n)
    return respaths[n]
group("Preserve operation02 owned launcher and declared minimal source changes",
    [res(n) for n in ["operations/launch_qwen_research_owned_v1_02.py",
        "diffs/launch_qwen_research_owned_v1_02.py.diff",
        "DECLARED_LITERAL_REPLACEMENTS_02.json", "NORMALIZED_AST_COMPARISON_02.json",
        "DIAGNOSTIC_RULE_METADATA_CHANGES_02.json"]])
group("Preserve the frozen operation02 read-only diagnostic",
    [res("research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py")],
    "The frozen 741-line diagnostic remains a complete file with its exact source identity.")
group("Preserve operation02 archive binding and unchanged diagnostic rule semantics",
    [res(n) for n in ["operations/archive_qwen_research_v1_03.py",
        "diffs/archive_qwen_research_v1_03.py.diff", "diffs/qwen_research_diagnostic_v1.py.diff",
        "diffs/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json.diff",
        "research-diagnostic-v1-source-02/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json"]])
group("Freeze the explicit reschedule protocol and cumulative accounting requirement",
    [res(n) for n in ["PROTOCOL_ADDENDUM_02.md", "UNCHANGED_RESEARCH_AND_BUDGET_02.json",
        "DEPLOYMENT_MAP_02.json", "INPUT_BINDINGS_02.json", "MANIFEST_02.json", "HANDOFF_02.json"]]
    + [put("run02/source/RESEARCH_RESCHEDULE_SOURCE_02.zip", sr, "exact original 20-member source ZIP"),
       put("run02/source/RESEARCH_RESCHEDULE_RUNTIME_02.zip", rt, "exact original four-member runtime ZIP")])
group("Preserve the path-version preparation program and its actual terminal",
    [res(n) for n in ["prepare_reschedule_source_02.py", "PREPARATION_OBSERVATION_02.json"]])
if {p.relative_to(RS).as_posix() for p in fileset(RS)} - source_names - {
    "RESEARCH_RESCHEDULE_SOURCE_02.zip", "RESEARCH_RESCHEDULE_RUNTIME_02.zip",
    "HANDOFF_02.json", "PREPARATION_OBSERVATION_02.json", "prepare_reschedule_source_02.py"}:
    raise ValueError("unaccounted frozen reschedule files")
group("Preserve the independent static review of operation02 source equivalence",
    [cp(IR / n, "run02/independent-review/" + n) for n in [
        "README.md", "REVIEW_02.json", "STATIC_REVIEW_TERMINAL.json", "static_review.py"]])
if inputs[str(IR / "REVIEW_02.json")]["sha256"] != "1e485a82c915e1a273cf9a48ca00c267cdc3c6a701c51ab9acd728a9cc97e5dd":
    raise ValueError("independent operation02 review differs")
df = fileset(DR)
if {p.name for p in df} != {"EXIT.json", "STARTED.json", "stdout.log", "stderr.log"}:
    raise ValueError("closed deployment files changed")
fr = read(ROOT / "FORMAT_06.json",
    "b87296a2439627c04593c338926e74d52934cf3df61f9fc7fb52e913c90a4fc7")
fmt = json.loads(fr)
if fmt["exit_code"] != 0 or fmt["frozen_core_unchanged"] is not True:
    raise ValueError("format receipt differs")
group("Preserve completed operation02 deployment and actual formatting receipt",
    [cp(p, "run02/deployment/" + p.name) for p in df]
    + [put("run02/format/FORMAT_06.json", fr, str(ROOT / "FORMAT_06.json"))])
pf = fileset(PF)
if {p.name for p in pf} != {"EXIT.json", "RESEARCH_LAUNCH_FREEZE_02.json",
    "RESEARCH_PREFLIGHT_02.json", "STARTED.json", "stdout.log", "stderr.log"}:
    raise ValueError("closed preflight files changed")
group("Preserve the frozen operation02 preflight and exact launch intent",
    [cp(p, "run02/preflight/" + p.name) for p in pf])

oprows = []
op_payload = []
for item in ops_observation["operations"]:
    row = dict(item)
    if item["name"] in pending02:
        row["coverage"] = "next_package_pending_run02_final_operations"
        row["identity_scope"] = "as observed by bounded source inventory; not a runtime observation"
    elif item["direct_git_paths"]:
        for n in item["direct_git_paths"]:
            if sha(git("show", "HEAD:" + n)) != item["sha256"]:
                raise ValueError("prior direct Git source coverage differs")
        row["coverage"] = "already_in_s01_to_s68_exact_Git_bytes"
    elif item["in_original_run01_zip"]:
        if sha(az.read("operations/" + item["name"])) != item["sha256"]:
            raise ValueError("original run01 archive source coverage differs")
        row["coverage"] = "exact_original_run01_archive"
    else:
        path = cp(OPS / item["name"], "mac-operations/" + item["name"], item["sha256"])
        op_payload.append(path)
        row["coverage"] = "included_in_this_package"
        row["publication_path"] = path
    oprows.append(row)
group("Preserve previously unbound task-owned Mac preparation and publication programs", op_payload)
pending_inline = [
    {"role": "Run01 terminal inspection Mac controller",
     "status": "next_package_pending_original_inline_source_binding"},
    {"role": "Run01 postrun prepare and launch Mac controller",
     "status": "next_package_pending_original_inline_source_binding"},
    {"role": "Run01 final export Mac controller",
     "status": "next_package_pending_original_inline_source_binding"}]
op_header = {"schema": "hepta.task-owned-mac-source-coverage.v1",
    "native_head": BASE, "inventory_PTY": ops_observation["inventory_PTY"],
    "inventory_created_unix_ms": ops_observation["inventory_created_unix_ms"],
    "scope": "explicit task-owned top-level operations Python files; no unrelated directories or keys",
    "future_files_or_hidden_archive_coverage_not_inferred": True}
op_index = put("MAC_OPERATIONS_SOURCE_COVERAGE.jsonl",
    b"".join(line(v) for v in [op_header, *oprows, *pending_inline]),
    "generated exact source coverage and explicit pending map")
pending_text = """# Explicit next-package source bindings

The following operation02 runtime-control scripts are left for the final
operation02 package, as root requested. Only their source identity at the
bounded inventory time is recorded here; no live outputs were read.

- export_research_results_02.py
- inspect_research_terminal_02.py
- launch_research_postrun_02.py
- observe_research_run_02.py
- prepare_research_postrun_02.py

The bounded top-level operations inventory did not contain a stand-alone
operation01 Python file for each of these controller roles:

- original Mac terminal inspection controller;
- original Mac postrun preparation and launch controller;
- original Mac final export controller.

Root must bind their original inline command source or retained controller
receipts in the next package before claiming controller-source coverage is
complete. This is an explicit pending source binding, not proof that bytes
are absent from every older archive or that a controller did not execute.

MAC_OPERATIONS_SOURCE_COVERAGE.jsonl identifies all 23 observed top-level
Python files, exact SHA values, direct prior Git paths, original archive
coverage, newly preserved files and the five operation02 deferrals.
"""
pending_path = put("NEXT_PACKAGE_PENDING.md", pending_text.encode(), "explicit non-silent source deferrals")
group("Record task-owned Mac source coverage and explicit final-package deferrals", [op_index, pending_path])

coverage = {
    "schema": "hepta.closed01-prepared02-publication-coverage.v1",
    "prepared_at_ns": time.time_ns(), "base_commit": BASE,
    "Run01": {"closed": True, "archive_members": 694, "original_export_Git_objects": 8,
        "archive_sha256": tm["archive"]["sha256"], "status": "RESEARCH_PARTIAL_UNQUALIFIED",
        "retained_shadow_output_receipts": 6, "retained_reference_receipts": 36,
        "fit_entries": 4, "completed_fits": 0, "completed_optimizer_step_receipts": 0,
        "global_totals_unknown": True, "all_six_primaries_first_memory_gate_failed": True,
        "new_primary_task_success_rate": None, "new_cold_results": None,
        "external_GPU_process_owner_and_exact_causal_contribution": "unknown",
        "failed_attempts_and_unknown_cost_tails_preserved": True},
    "Run02": {"root_reported_running_at_assignment": True,
        "reported_PTY": "dpty-245ab3897004ac7e6e8e405d65d7c78e36efa62a7b97edfdfa272e0c745f3770",
        "reported_Desktop_PID": 2451059, "live_execution_observed_by_packager": False,
        "scope": "frozen source and closed preparation only",
        "runtime_outputs_or_eventual_outcome_read": False,
        "automatic_retry": False, "training_modules_parameters_budgets_or_thresholds_changed": False,
        "cumulative_01_and_02_reporting_required": True},
    "Mac_operations_coverage": {"observed_top_level_python_files": len(oprows),
        "newly_preserved_files": len(op_payload), "deferred_run02_final_files": sorted(pending02),
        "deferred_run01_inline_controller_roles": pending_inline},
    "original_64_core_git_blobs_unchanged": True,
    "new_model_test_verifier_training_or_C_execution": False,
    "Git_or_PR_mutation_by_packager": False, "new_independent_samples": 0,
    "new_users": 0, "new_teachers": 0, "new_C": False,
    "scientific_confirmation_qualified": False, "native_cell_adoption": False,
    "proof_of_useful_work_eligible": False, "circuit_qualified": False, "candidate_selected": None,
    "excluded": ["active Run02 outputs and owned logs", "Run02 candidates, adapters and task results",
        "base weights", "venv", "caches", "C", "unrelated work", "architecture final draft"],
    "new_snapshot_temporary_metadata_exclusions": skipped,
    "original_inputs_modified": False, "atomic_snapshot_claimed": False}
readme = """# Closed research01 and frozen operation02 preparation

This package preserves the complete closed operation01 archive, its independent
result review and its memory-admission review. For operation02 it preserves
only frozen source versions, independent static review and completed deployment,
preflight and formatting records. Root reported operation02 running when this
task was assigned. Its active outputs and eventual results were not inspected.

## Closed operation01

The original export has 694 members and eight proposed Git objects. All original
parts, TRANSFER_MANIFEST and RESTORE instructions remain byte-identical. The
export STARTED receipt is also retained separately. The complete failed attempts,
plans, reference receipts and unknown cost tails remain inside the original ZIP.

Independent review records six retained shadow generation outputs, 36 reference
receipts, four fit entries, zero completed fits and zero recorded optimizer steps.
All six primary workers failed initial memory admission before their model and
optimizer initialization. No new primary A/B or cold result was obtained. Missing
outcomes are unavailable, not zero percent success. The original global ledger
totals remain unknown; retained receipt counts do not replace them.

The final result-review JSON is preserved in a lossless original-file ZIP with
member SHA values. Its report, actual review script, checklist and execution
receipt are also readable. The memory review retains its original 43-member
ZIP plus a lossless archive of transfer/terminal originals outside that ZIP.
Duplicated readable evidence never adds calls, cost or independent samples.

## Operation02 preparation

The original source/runtime ZIPs, path-only variants, full diffs, rule metadata,
protocol addendum, source generation script and actual preparation terminal are
preserved. Independent static review and completed deployment/preflight/format
records remain unchanged. The four research modules and 64 core Git blobs do
not change. No active operation02 output, owned log, candidate, adapter, task
result or live resource measurement was read.

Operation02 is an explicitly numbered post-failure resource reschedule. Its
parameters, per-operation budgets and admission thresholds are unchanged. Costs
from both operations must be retained without adding overlapping scopes or
turning unknown tails into zero. Repeated tasks, fresh shadow outputs, reference
rechecks and cold observations add cost, not independent sources or samples.

Preflight is a past observation, not a resource reservation or a success claim.
Source equivalence, deployment and formatting cannot establish learned capability.

## Coverage and explicit deferrals

MAC_OPERATIONS_SOURCE_COVERAGE.jsonl maps task-owned top-level Mac scripts to
exact prior Git coverage, original archive coverage, this package, or the final
operation02 package. NEXT_PACKAGE_PENDING.md explicitly lists five new run02
controller files and three run01 inline-controller source bindings still to be
resolved. This publication does not silently assert complete controller coverage.

All originals remain unchanged. New snapshot indexes preserve member bytes and
restoration steps without claiming atomic snapshots. Temporary transport locks
are excluded from new standalone payloads and snapshots; any such bytes inside
an already frozen original ZIP remain part of that original identity.

No model, training loop, verifier, engineering test, C task, Git mutation or PR
action is performed by this packager. Original consistency-check counts are not
new experiments. New independent users, teachers, samples and C remain zero;
scientific confirmation, native adoption, Circuit and PoUW remain unqualified.
"""
coverage_path = put("COVERAGE.json", js(coverage), "generated closed/prepared scope boundary")
readme_path = put("README.md", readme.encode(), "generated independent evidence and preparation explanation")
input_path = put("INPUT_BINDINGS.jsonl",
    b"".join(line({"source_path": n, **v}) for n, v in sorted(inputs.items())),
    "generated exact closed/frozen input identities")
group("Document closed-result coverage and exclude active operation02 outcomes",
      [coverage_path, readme_path, input_path])

names = [n for g in groups for n in g["files"]]
if len(names) != len(set(names)) or set(names) != set(payload):
    raise ValueError("publication groups do not partition exact payload")
tree = OUT / "payload"
tree.mkdir(exist_ok=False)
identities = {}
for n, raw in sorted(payload.items()):
    p = tree / n
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as f:
        f.write(raw)
    r = subprocess.run(["git", "diff", "--no-index", "--numstat", "--", "/dev/null", str(p)],
                       cwd=OUT, capture_output=True, timeout=60)
    if r.returncode not in (0, 1):
        raise RuntimeError(r.stderr.decode(errors="replace"))
    first = r.stdout.decode().split("\t", 1)[0] if r.stdout else "0"
    identities[n] = {"bytes": len(raw), "sha256": sha(raw),
        "git_added_text_lines": 0 if first == "-" else int(first), "origin": origins[n]}
stages = []
for g in groups:
    chunks, pending, count = [], [], 0
    for n in g["files"]:
        lines = identities[n]["git_added_text_lines"]
        if lines > 800:
            raise ValueError("unexceptioned file exceeds 800 lines")
        if pending and count + lines > 499:
            chunks.append(pending)
            pending, count = [], 0
        pending.append(n)
        count += lines
        if count > 499:
            chunks.append(pending)
            pending, count = [], 0
    if pending:
        chunks.append(pending)
    for i, chunk in enumerate(chunks):
        num = 69 + len(stages)
        title = g["title"] + ((" (part %d)" % (i+1)) if len(chunks) > 1 else "")
        lines = sum(identities[n]["git_added_text_lines"] for n in chunk)
        branch = "codex/cell-experiments-v3-20261116-0c078a-s"
        stages.append({"id": "s%d-closed01-prepared02" % num, "number": num,
            "commit_subject": title, "draft_pr_title": "[draft] " + title,
            "draft_pr_head": branch + str(num), "draft_pr_base": branch + str(num-1),
            "draft_pr_body": (
                "Operation01 produced no trained candidate or new primary result. Preserve its "
                "closed failure evidence, or the separate operation02 preparation, so source "
                "identity, costs and qualification limits remain reviewable. Root reported "
                "operation02 running at assignment; no active output or eventual outcome is "
                "included. No new independent samples, user/teacher growth, C, Circuit, PoUW "
                "or adoption is claimed. " + g["note"]),
            "files": chunk, "added_text_lines": lines,
            "kind": "bounded_evidence_and_reviewable_source",
            "mechanical_evidence_exception": None, "prefer_under_500_met": lines < 500,
            "mechanical_json_evidence": [n for n in chunk if n.endswith((".json", ".jsonl"))]})
attrs = git("check-attr", "-z", "diff", "--", *sorted(payload)).split(b"\0")
if any(attrs[i] != b"unspecified" for i in range(2, len(attrs)-1, 3)):
    raise ValueError("destination diff attributes require review")
for n, v in inputs.items():
    b = Path(n).read_bytes()
    if len(b) != v["bytes"] or sha(b) != v["sha256"]:
        raise ValueError("closed/frozen input changed during packaging")
if git("rev-parse", "HEAD").decode().strip() != BASE or git("status", "--porcelain=v1").strip():
    raise ValueError("native worktree changed during preparation")
plan = {"schema": "hepta.native-final-publication-plan.v3", "base_commit": BASE,
    "frozen_at_ns": time.time_ns(), "binary_part_limit": 322560,
    "git_object_limit_exclusive": 512000, "expected_complete_core_git_blobs": core,
    "new_model_execution": False, "source_scope": "closed Run01 and frozen/closed Run02 preparation only",
    "files": identities, "stages": stages}
plan_raw = js(plan)
with (OUT / "NATIVE_FINAL_PLAN_01.json").open("xb") as f:
    f.write(plan_raw)
straw = js({"schema": "hepta.full-stage-manifest.v1", "base_commit": BASE,
            "files": identities, "stages": stages})
with (OUT / "STAGE_MANIFEST_01.json").open("xb") as f:
    f.write(straw)
final = zipbytes({"NATIVE_FINAL_PLAN_01.json": plan_raw, **payload})
ap = OUT / "publication-closed01-prepared02-input-01.zip"
with ap.open("xb") as f:
    f.write(final)
manifest = {"schema": "hepta.closed01-prepared02-publication-ready.v1",
    "status": "FROZEN_READY_FOR_ROOT_REVIEW_NOT_PUBLISHED",
    "base_commit": BASE, "intended_native_operation": "publication-final-operation-04",
    "archive_path": str(ap), "archive_bytes": len(final), "archive_sha256": sha(final),
    "plan_path": str(OUT / "NATIVE_FINAL_PLAN_01.json"), "plan_bytes": len(plan_raw),
    "plan_sha256": sha(plan_raw), "stage_manifest_path": str(OUT / "STAGE_MANIFEST_01.json"),
    "stage_manifest_bytes": len(straw), "stage_manifest_sha256": sha(straw),
    "first_stage": 69, "last_stage": stages[-1]["number"], "stage_count": len(stages),
    "payload_files": len(payload), "payload_bytes": sum(map(len, payload.values())),
    "maximum_object_bytes": max(map(len, payload.values())),
    "maximum_text_stage_lines": max(s["added_text_lines"] for s in stages),
    "mechanical_exceptions": 0, "active_run02_read": False,
    "models_tests_verifiers_or_C_executed": False, "native_worktree_modified": False,
    "original_inputs_rehashed_equal": len(inputs), "Mac_ops_newly_preserved": len(op_payload),
    "root_must_copy_archive_to_direct_MacROOT_child": True,
    "stages": [{"number": s["number"], "files": len(s["files"]), "lines": s["added_text_lines"],
                "title": s["commit_subject"], "prefer_under_500_met": s["prefer_under_500_met"]}
               for s in stages]}
with (OUT / "MANIFEST.json").open("xb") as f:
    f.write(js(manifest))
print(json.dumps(manifest, sort_keys=True), flush=True)
