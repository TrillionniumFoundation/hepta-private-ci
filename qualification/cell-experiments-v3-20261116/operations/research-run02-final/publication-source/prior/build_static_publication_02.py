"""Freeze static architecture and retained control source, never live Run02 outputs."""
import difflib
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
OUT = ROOT / "research-static-publication-02"
WORK = ROOT / "publication-native-01"
BASE = "296eed0d85795d102d1bb27a84b86f8f4ed26e4b"
PREFIX = "qualification/cell-experiments-v3-20261116/operations/research-static-architecture-and-control/"
PRIOR_PREFIX = "qualification/cell-experiments-v3-20261116/operations/research-run01-and-run02-preparation/"
OPS = ROOT / "operations"
inventory = json.loads(sys.argv[1])
sources = ["export_research_results_02.py", "inspect_research_terminal_02.py",
    "launch_research_postrun_02.py", "observe_research_run_02.py",
    "prepare_research_postrun_02.py", "watch_research_run_02.py",
    "prepare_closed01_publication_01.py"]
inline_names = [Path(row["path"]).name for row in inventory["bindings"]["source_rows"]]
allowed = {ROOT / "architecture-synthesis-01/ARCHITECTURE_RESEARCH.md",
    ROOT / "research-interpretation-review-01/REVIEW.md", ROOT / "FORMAT_07.json",
    ROOT / "publication-final-operation-04/COMPLETE.json",
    ROOT / "publication-closed01-root-check-01/RESULT.json",
    ROOT / "publication-closed01-root-check-01/REVIEW_TEXT.json",
    ROOT / "research-closed01-prepared02-publication-01/NATIVE_FINAL_PLAN_01.json",
    OPS / "RETAINED_INLINE_SOURCE_BINDINGS_01.json",
    OPS / "CLOSED01_PREPARED02_DRAFT_PUBLICATION_01.json"}
allowed.update(OPS / name for name in sources + inline_names)
payload, origins, inputs, groups = {}, {}, {}, []


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def js(v):
    return (json.dumps(v, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def line(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode() + b"\n"


def read(p, expected=None):
    if p not in allowed or p.is_symlink() or not p.is_file():
        raise ValueError("source outside static closed allowlist: " + str(p))
    raw = p.read_bytes()
    identity = {"bytes": len(raw), "sha256": sha(raw)}
    if expected and identity["sha256"] != expected:
        raise ValueError("source identity differs: " + str(p))
    if str(p) in inputs and inputs[str(p)] != identity:
        raise ValueError("source changed across reads")
    inputs[str(p)] = identity
    return raw


def put(name, raw, origin):
    name = PREFIX + name
    if name in payload or len(raw) >= 512000:
        raise ValueError("duplicate or oversized payload")
    if name.endswith((".zip", ".bin")) and len(raw) > 322560:
        raise ValueError("binary part exceeds bound")
    payload[name], origins[name] = raw, origin
    return name


def cp(p, name, expected=None):
    return put(name, read(p, expected), str(p))


def group(title, names, note=""):
    groups.append({"title": title, "files": names, "note": note})


def git(*args):
    p = subprocess.run(["git", *args], cwd=WORK, capture_output=True, timeout=60)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout


def makezip(contents):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, raw in sorted(contents.items()):
            entry = zipfile.ZipInfo(name, (2026, 11, 17, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(entry, raw)
    raw = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() or set(z.namelist()) != set(contents):
            raise ValueError("ZIP CRC or member set differs")
        if any(z.read(n) != b for n, b in contents.items()):
            raise ValueError("ZIP original bytes differ")
    return raw


if git("rev-parse", "HEAD").decode().strip() != BASE or git("status", "--porcelain=v1").strip():
    raise ValueError("publication base or clean status differs")
prior = json.loads(read(ROOT / "research-closed01-prepared02-publication-01/NATIVE_FINAL_PLAN_01.json",
    "498b93ec7ea0c6ced1de2850cb3806ab6a5b9b7fb745f19db7b8d702288219bc"))
core = {s.split("\t", 1)[1]: s.split("\t", 1)[0].split()[2]
        for s in git("ls-tree", "-r", "HEAD", "--", "scripts/cell_experiments").decode().splitlines()
        if s.endswith(".py")}
if len(core) != 64 or core != prior["expected_complete_core_git_blobs"]:
    raise ValueError("64 frozen core Git blobs differ")

archive_git_path = PRIOR_PREFIX + "run01/export"
if git("cat-file", "-t", BASE + ":" + archive_git_path).decode().strip() != "tree":
    raise ValueError("published run01 export directory missing")
index_raw = git("show", BASE + ":" + archive_git_path + "/members-part-00000.bin")
if sha(index_raw) != "336e7308d967918413b0c0fc6b8e5e2acefc16476e70b419f100b3752731afa5":
    raise ValueError("published run01 member index differs")
members = {v["path"]: v for v in (json.loads(x) for x in index_raw.splitlines())}
result_sha = "bbb77cb25b2f7e28caa3a71f7112d549734b3ff8bbdd32b562fc2bbbf5bc0e33"
diagnostic_sha = "b623702d5611bd24bd3f9736300938c6e02f2ec75bed838962d33b05e6b7af37"
for name, expected in [("research-sft-01/RESULT.json", result_sha),
                       ("research-diagnostic-01/DIAGNOSTIC.json", diagnostic_sha)]:
    if members[name]["sha256"] != expected:
        raise ValueError("published archive member reference differs")
protocol_git_path = PRIOR_PREFIX + "run02/source/PROTOCOL_ADDENDUM_02.md"
if sha(git("show", BASE + ":" + protocol_git_path)) != "8f9ae4acd63ae3eebce183cf68b0791fb0bbeec1cee9d9b337ac85fbb76335b9":
    raise ValueError("published run02 protocol link differs")
archive_url = "https://github.com/TrillionniumFoundation/hepta-private-ci/tree/" + BASE + "/" + archive_git_path + "/"
protocol_url = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/" + BASE + "/" + protocol_git_path
original = read(ROOT / "architecture-synthesis-01/ARCHITECTURE_RESEARCH.md",
    "4bd2e5b6392e09e65ad7549cb4dcad9de231cc2c0f5ed71369762144318e5f06")
text = original.decode()
edits = []
def change(old, new, reason):
    global text
    if text.count(old) != 1:
        raise ValueError("architecture edit target is not unique")
    text = text.replace(old, new)
    edits.append({"before": old, "after": new, "reason": reason})
change("> 研究架构稿；状态截点：2026-11-17 的已保留原件与本轮交接。",
       "> 研究架构发布版；原稿状态截点：2026-11-17 UTC（美国东部标准时间 EST 为 2026-11-16）的已保留原件与本轮交接。",
       "label the original UTC cutoff and its requested Eastern-time date; not a new runtime cutoff")
change("L1–L3 相对本工作区父目录，尚未在本稿中赋予远端发布提交：",
       "L1–L3 固定到发布提交 " + BASE + "；L1、L2 指向完整封存归档目录，RESULT 与 DIAGNOSTIC 是归档内成员，需按 manifest 恢复；L3 指向该提交下的补充协议：",
       "replace local-only references with frozen publication links and state archive-member scope")
tick = chr(96)
for label, member, expected in [
    ("L1", "research-sft-01/RESULT.json", result_sha),
    ("L2", "research-diagnostic-01/DIAGNOSTIC.json", diagnostic_sha)]:
    old_line = next(s for s in text.splitlines() if s.startswith("- [" + label + ":"))
    new_line = ("- [" + label + ": 研究01封存归档](" + archive_url + ")，归档内成员 "
                + tick + member + tick + "，成员 SHA256 " + tick + expected + tick + "。")
    change(old_line, new_line, "link to the archive, not a nonexistent directly published JSON")
    old_ref = next(s for s in text.splitlines() if s.startswith("[" + label + "]:"))
    change(old_ref, "[" + label + "]: " + archive_url, "freeze the reference-definition archive URL")
old_line = next(s for s in text.splitlines() if s.startswith("- [L3:"))
change(old_line, old_line.replace("../research-reschedule-source-02/PROTOCOL_ADDENDUM_02.md", protocol_url),
       "freeze the direct protocol document URL")
change("[L3]: ../research-reschedule-source-02/PROTOCOL_ADDENDUM_02.md",
       "[L3]: " + protocol_url, "freeze the reference-definition protocol URL")
if len(edits) != 8 or len(text.splitlines()) != len(original.decode().splitlines()):
    raise ValueError("unexpected architecture edit scope")
published = text.encode()
restored = text
for edit in reversed(edits):
    if restored.count(edit["after"]) != 1:
        raise ValueError("publication edit is not reversibly unique")
    restored = restored.replace(edit["after"], edit["before"])
if restored.encode() != original:
    raise ValueError("architecture changed beyond declared edits")
original_path = put("architecture/originals/ARCHITECTURE_RESEARCH.md", original,
                    "exact unmodified original architecture draft")
published_path = put("architecture/ARCHITECTURE_RESEARCH.md", published,
                     "publication copy with only declared link/date presentation edits")
group("Preserve the original architecture research draft unchanged", [original_path])
group("Publish architecture research with fixed archive links and explicit dates", [published_path],
      "The original is retained; the publication copy only changes declared L1-L3 links and date presentation.")
diff = "".join(difflib.unified_diff(original.decode().splitlines(True), text.splitlines(True),
    fromfile="originals/ARCHITECTURE_RESEARCH.md", tofile="ARCHITECTURE_RESEARCH.md")).encode()
edit_record = {"schema": "hepta.architecture-publication-edit.v1",
    "original_sha256": sha(original), "published_sha256": sha(published),
    "original_bytes": len(original), "published_bytes": len(published),
    "original_source_unmodified": True, "original_cutoff_timezone": "UTC",
    "displayed_original_cutoff_Eastern_date": "2026-11-16 EST",
    "publication_link_commit": BASE, "exact_reversible_edits": edits,
    "all_other_bytes_unchanged": True,
    "L1_L2_are_archive_links_not_direct_JSON_links": True,
    "published_archive_member_index_sha256": sha(index_raw),
    "L1_member": members["research-sft-01/RESULT.json"],
    "L2_member": members["research-diagnostic-01/DIAGNOSTIC.json"]}
edit_files = [
    put("architecture/DECLARED_LINK_AND_DATE_CHANGES.json", js(edit_record), "exact approved publication edits"),
    put("architecture/ARCHITECTURE_PUBLICATION.diff", diff, "exact original/publication diff"),
    cp(ROOT / "research-interpretation-review-01/REVIEW.md", "interpretation/REVIEW.md",
       "1857e9037e1e1222f64934e6b3b5e6cbf3807580980b0683f911766dca893a2e")]
group("Record precise architecture edits and the independent interpretation limits", edit_files)

source_rows = []
source_files = []
for name in sources:
    expected = inventory["operations/" + name]["sha256"]
    raw = read(OPS / name, expected)
    source_files.append(put("control-source/" + name, raw, str(OPS / name)))
    status = "prepared_not_executed_per_root" if name == "prepare_research_postrun_02.py" else "execution_not_asserted_by_this_static_package"
    source_rows.append({"path": name, "bytes": len(raw), "sha256": sha(raw),
                       "scope": "source text only", "execution_status": status})
group("Preserve the selected control programs without claiming runtime execution", source_files,
      "prepare_research_postrun_02.py was prepared but not executed; actual reconciled control execution is deferred to the final run02 evidence package.")
binding_raw = read(OPS / "RETAINED_INLINE_SOURCE_BINDINGS_01.json",
    "cad03659b42ebc146f0337e6d533db5a3d1dee9577119b34bc62e0c1d5847aef")
bindings = json.loads(binding_raw)
if len(bindings["source_rows"]) != 7 or bindings["reexecuted"] is not False:
    raise ValueError("retained inline materialization scope differs")
inline_files = []
for item in bindings["source_rows"]:
    raw = read(ROOT / item["path"], item["sha256"])
    if len(raw) != item["bytes"]:
        raise ValueError("retained inline byte count differs")
    inline_files.append(put("retained-inline/" + Path(item["path"]).name, raw,
        "new materialization of retained original inline command text; not its original execution path"))
inline_files.append(put("retained-inline/RETAINED_INLINE_SOURCE_BINDINGS_01.json",
                        binding_raw, str(OPS / "RETAINED_INLINE_SOURCE_BINDINGS_01.json")))
receipt_names = ["operations/RESEARCH_ACTUAL_TERMINAL_01.json",
    "operations/RESEARCH_POSTRUN_TERMINAL_01.json", "operations/RESEARCH_POSTRUN_LAUNCH_FREEZE_01.json",
    "operations/RESEARCH_TERMINAL_INDEX_01.json", "owned-research-sft-01/STARTED.json",
    "owned-research-sft-01/EXIT.json", "owned-research-diagnostic-01/STARTED.json",
    "owned-research-diagnostic-01/EXIT.json"]
receipt_bindings = {name: members[name] for name in receipt_names}
closure = {"schema": "hepta.retained-inline-role-coverage.v1",
    "materialization_binding_sha256": sha(binding_raw),
    "source_text_origin": "root retained original inline command strings, materialized under new paths",
    "original_on_disk_execution_paths_claimed": False,
    "reexecuted_or_new_execution_results": False,
    "closed_scope": "reviewable retained source-text availability for three previously pending Run01 controller roles",
    "roles": [
        {"role": "Run01 terminal inspection", "retained_source": "retained_inline_research01_inspection.py"},
        {"role": "Run01 postrun preparation and launch",
         "retained_sources": ["retained_inline_research01_postrun_prepare.py", "retained_inline_research01_postrun_launch.py"]},
        {"role": "Run01 final export", "retained_source": "retained_inline_research01_export.py"}],
    "original_execution_archive_url": archive_url,
    "original_receipt_members": receipt_bindings,
    "execution_provenance_limit": "original launch/terminal/owned receipts remain authoritative; text materialization does not retroactively make these paths original launch paths or independently prove every retained line executed",
    "independent_source_custody_claimed": False}
inline_files.append(put("retained-inline/ROLE_COVERAGE_AND_EXECUTION_BOUNDARY.json",
                        js(closure), "retained source availability mapped to existing original receipt identities"))
inline_files.append(put("retained-inline/README.md", b"""# Retained original inline source

These seven files were newly materialized from retained original inline Python
command strings. Their names were not original on-disk execution paths. The
materialization binding preserves text identity and origin store keys. Neither
this materialization nor this publication executes those commands again.

The three previously pending Run01 controller roles now have reviewable retained
source text: terminal inspection, postrun preparation/launch and final export.
Original execution identity remains in the earlier launch, terminal and owned
receipts referenced by the coverage map. This closes source-text availability,
not an independent custody attestation or a new reproduction of those executions.

No operation02 outcome follows from retaining a launch or monitoring script.
No live output, owned record, adapter or result was read by this packager.
""", "explicit materialization and execution provenance boundary"))
group("Preserve original inline command text with exact materialization limits", inline_files)

complete_path = ROOT / "publication-final-operation-04/COMPLETE.json"
complete_raw = read(complete_path,
    "05413a2009d21f5840cd5df56d980a7b7490123e6f816ba4dcac1f2975c12ce2")
complete = json.loads(complete_raw)
draft_path = OPS / "CLOSED01_PREPARED02_DRAFT_PUBLICATION_01.json"
draft_raw = read(draft_path,
    "c5de84e099368f568bf3c7e02c8e299d054b759bed2a86564a040343adc047c3")
draft = json.loads(draft_raw)
if len(complete["commits"]) != 20 or complete["commits"][-1]["commit"] != BASE:
    raise ValueError("closed native publication chain differs")
if len(draft["prs"]) != 20 or draft["head_commit"] != BASE or draft["all_remote_ref_shas_verified"] is not True:
    raise ValueError("closed draft publication record differs")
pairs = []
for i, (commit, pr) in enumerate(zip(complete["commits"], draft["prs"])):
    if pr["number"] != 6510 + i or pr["draft"] is not True or pr["merged"] is not False:
        raise ValueError("closed PR identity/state differs")
    if pr["head_sha"] != commit["commit"] or pr["base_sha"] != commit["base_commit"]:
        raise ValueError("saved PR head/base differs from native commits")
    pairs.append({"stage": 69+i, "PR": pr["number"], "url": pr["url"],
        "head_sha": pr["head_sha"], "base_sha": pr["base_sha"], "draft": True, "merged": False})
closed_contents = {
    "publication-final-operation-04/COMPLETE.json": complete_raw,
    "operations/CLOSED01_PREPARED02_DRAFT_PUBLICATION_01.json": draft_raw}
for name in ["RESULT.json", "REVIEW_TEXT.json"]:
    path = ROOT / "publication-closed01-root-check-01" / name
    closed_contents["publication-closed01-root-check-01/" + name] = read(path)
closed_zip = makezip(closed_contents)
closed_manifest = {"schema": "hepta.closed-publication-evidence.v1",
    "archive": "CLOSED_PUBLICATION_04_ORIGINALS.zip", "bytes": len(closed_zip),
    "sha256": sha(closed_zip), "members": {n: {"bytes": len(raw), "sha256": sha(raw)}
        for n, raw in closed_contents.items()},
    "source_records_unchanged": True, "new_API_verification_performed": False,
    "closed_saved_API_receipts_match_native_commits": True}
closed_summary = {"schema": "hepta.closed-publication-static-summary.v1",
    "native_operation": "publication-final-operation-04", "first_stage": 69, "last_stage": 88,
    "head_commit": BASE, "saved_native_status": complete["status"],
    "saved_followup_API_all_refs_verified": draft["all_remote_ref_shas_verified"],
    "saved_API_records_rechecked_against_saved_native_commits": True,
    "fresh_API_calls": 0, "merge_performed": False, "production_adoption": False, "rows": pairs}
group("Preserve closed native publication and Draft PR verification originals", [
    put("closed-publication/CLOSED_PUBLICATION_04_ORIGINALS.zip", closed_zip, "lossless ZIP of four exact closed original files"),
    put("closed-publication/MANIFEST.json", js(closed_manifest), "original closed publication member identities"),
    put("closed-publication/RECORDED_PUBLICATION_SUMMARY.json", js(closed_summary), "saved API/native consistency summary, not fresh API verification"),
    put("closed-publication/RESTORE.md", b"""# Restore original closed publication records

Verify the ZIP size/SHA and CRC, then every member path, byte count and SHA from
MANIFEST.json before extracting to a new directory. Original COMPLETE.json
retains its earlier PUSHED_PENDING_API_VERIFICATION status. The later saved
Draft-publication record contains the completed API checks. Neither is rewritten.

The static summary compares those saved records. It does not perform new API
calls, Git mutations, PR operations, merges or deployment.
""", "lossless restoration and sequential-record status explanation")])
format_raw = read(ROOT / "FORMAT_07.json",
    "d82ba14c879f4acca492849388f97b16a9790806d3d67b10625d15f987034c9a")
fmt = json.loads(format_raw)
if fmt["exit_code"] != 0 or fmt["frozen_core_unchanged"] is not True or fmt["tests_rerun_after_format"] is not False:
    raise ValueError("FORMAT07 record differs")
group("Preserve the actual formatting receipt and control-source execution statuses", [
    put("format/FORMAT_07.json", format_raw, str(ROOT / "FORMAT_07.json")),
    put("control-source/SOURCE_STATUS.jsonl", b"".join(line(x) for x in source_rows),
        "source-only statuses with explicit prepared-not-executed exception")])

coverage = {"schema": "hepta.static-architecture-control-publication.v1",
    "prepared_at_ns": time.time_ns(), "base_commit": BASE,
    "architecture_original_sha256": sha(original), "architecture_publication_sha256": sha(published),
    "architecture_changes": "eight exact reversible link/date presentation line edits only",
    "original_architecture_modified": False, "interpretation_review_original_preserved": True,
    "retained_inline_files": 7, "retained_inline_text_reexecuted": False,
    "original_disk_execution_paths_for_materialized_files_claimed": False,
    "three_Run01_pending_roles_source_text_available": True,
    "execution_identity_remains_in_original_receipts": True,
    "selected_control_source_files": len(sources),
    "prepare_research_postrun_02_execution": "prepared_not_executed_per_root",
    "other_selected_source_execution": "not asserted by source presence",
    "closed_publication_stages": [69, 88], "closed_saved_PR_numbers": [6510, 6529],
    "closed_saved_PR_count": 20, "new_API_calls": 0,
    "excluded": ["all activity/result/observation outputs for Run02", "COORDINATOR_CHECKPOINT09",
        "Run02 owned logs, adapters, candidates and results",
        "reconcile_research02_controller_loss_01.py",
        "prepare_research_postrun_reconciled_02.py", "their associated observations",
        "base weights", "venv", "caches", "C tasks", "unrelated work"],
    "final_Run02_execution_bindings_deferred": True,
    "64_core_Git_blobs_unchanged": True, "no_model_training_test_verifier_or_C_execution": True,
    "Git_or_PR_mutated": False, "new_independent_samples": 0,
    "scientific_confirmation_qualified": False, "native_adoption": False,
    "Circuit_qualification": False, "PoUW_eligibility": False,
    "atomic_filesystem_snapshot_claimed": False}
readme = """# Static architecture and retained control source

This package publishes the architecture analysis and static interpretation
review, selected control source text, newly materialized original inline
commands, and already closed publication evidence. It contains no Run02 runtime
outcome, live observation, owned log, candidate or adapter.

## Architecture publication copy

The original architecture draft remains byte-identical. The publication copy
makes only eight declared, reversible line edits: date presentation, the L1-L3
introduction, three visible source links and their reference definitions.
The original cutoff is explicitly UTC; its displayed Eastern date is
2026-11-16 EST. This is the original cutoff, not a new execution-state claim.

L1 and L2 point to the fixed published Run01 export directory. RESULT and
DIAGNOSTIC are members inside its archived bytes, not separately published JSON
files. Their original member SHA values are unchanged and were checked against
the Git-pinned member index. L3 points directly to the fixed published protocol.
All scientific conclusions, designs and remaining references stay unchanged.

## Control-source provenance

Source presence is not proof of execution. prepare_research_postrun_02.py is
explicitly marked prepared but not executed, as root reported. Actual reconciled
operation02 controllers and final execution bindings belong to the later Run02
evidence package. No outcome is inferred from monitoring or launch source text.

Seven retained-inline files newly materialize the original command strings.
They were not original on-disk launch paths and were not reexecuted. The three
Run01 source-text gaps are resolved within that retained-text scope; original
execution identity still comes from the original launch/terminal/owned receipts.

## Closed publication evidence

The native operation04 COMPLETE record, the later saved Draft verification
record, and the two closed root-check files are retained losslessly. The summary
compares their saved head/base identities without fresh API calls. The native
record's earlier status is preserved, while the later API record records the
completed checks. No merge or production adoption is implied.

FORMAT07 is an existing completed just-fmt receipt: exit0, unchanged 64 core
files, no tests rerun. This packager does not execute formatting or tests again.

No live Run02 output, controller-loss observation or checkpoint09 was read.
No model, training, verifier, C, Git/PR mutation or new independent sample is
created by this publication. Actual Run02 outcomes remain a separate package.
"""
group("Document static publication scope and precise provenance limits", [
    put("COVERAGE.json", js(coverage), "generated selected static/closed coverage"),
    put("README.md", readme.encode(), "generated static interpretation and provenance scope"),
    put("INPUT_BINDINGS.jsonl", b"".join(line({"source_path": n, **v}) for n, v in sorted(inputs.items())),
        "exact selected original input identities")])

names = [n for g in groups for n in g["files"]]
if len(names) != len(set(names)) or set(names) != set(payload):
    raise ValueError("group payload partition differs")
tree = OUT / "payload"
tree.mkdir(exist_ok=False)
identities = {}
for name, raw in sorted(payload.items()):
    p = tree / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as f:
        f.write(raw)
    x = subprocess.run(["git", "diff", "--no-index", "--numstat", "--", "/dev/null", str(p)],
        cwd=OUT, capture_output=True, timeout=60)
    if x.returncode not in (0, 1):
        raise RuntimeError(x.stderr.decode(errors="replace"))
    first = x.stdout.decode().split("\t", 1)[0] if x.stdout else "0"
    identities[name] = {"bytes": len(raw), "sha256": sha(raw),
        "git_added_text_lines": 0 if first == "-" else int(first), "origin": origins[name]}
stages = []
for g in groups:
    chunks, pending, count = [], [], 0
    for name in g["files"]:
        lines = identities[name]["git_added_text_lines"]
        if lines > 800:
            raise ValueError("unexceptioned object exceeds 800 text lines")
        if pending and count + lines > 499:
            chunks.append(pending)
            pending, count = [], 0
        pending.append(name)
        count += lines
        if count > 499:
            chunks.append(pending)
            pending, count = [], 0
    if pending:
        chunks.append(pending)
    for i, chunk in enumerate(chunks):
        number = 89 + len(stages)
        title = g["title"] + ((" (part %d)" % (i+1)) if len(chunks) > 1 else "")
        lines = sum(identities[n]["git_added_text_lines"] for n in chunk)
        branch = "codex/cell-experiments-v3-20261116-0c078a-s"
        stages.append({"id": "s%d-static-architecture-control" % number, "number": number,
            "commit_subject": title, "draft_pr_title": "[draft] " + title,
            "draft_pr_head": branch + str(number), "draft_pr_base": branch + str(number-1),
            "draft_pr_body": (
                "Make the architecture analysis, interpretation limits and retained control "
                "source reviewable with fixed published evidence links. Preserve original "
                "draft bytes, explicit source materialization provenance and closed publication "
                "receipts. This static package contains no Run02 outcome or live observation, "
                "does not claim every retained script executed, and does not establish "
                "scientific benefit, Circuit, PoUW or native adoption. " + g["note"]),
            "files": chunk, "added_text_lines": lines,
            "kind": "bounded_evidence_and_reviewable_source",
            "mechanical_evidence_exception": None, "prefer_under_500_met": lines < 500,
            "mechanical_json_evidence": [n for n in chunk if n.endswith((".json", ".jsonl"))]})
attrs = git("check-attr", "-z", "diff", "--", *sorted(payload)).split(b"\0")
if any(attrs[i] != b"unspecified" for i in range(2, len(attrs)-1, 3)):
    raise ValueError("destination attributes require review")
for name, identity in inputs.items():
    raw = Path(name).read_bytes()
    if len(raw) != identity["bytes"] or sha(raw) != identity["sha256"]:
        raise ValueError("static original input changed during preparation")
if git("rev-parse", "HEAD").decode().strip() != BASE or git("status", "--porcelain=v1").strip():
    raise ValueError("native tree changed during preparation")
plan = {"schema": "hepta.native-final-publication-plan.v3", "base_commit": BASE,
    "frozen_at_ns": time.time_ns(), "binary_part_limit": 322560,
    "git_object_limit_exclusive": 512000, "expected_complete_core_git_blobs": core,
    "new_model_execution": False, "source_scope": "static architecture, retained control source and closed publication evidence only",
    "files": identities, "stages": stages}
plan_raw = js(plan)
with (OUT / "NATIVE_FINAL_PLAN_01.json").open("xb") as f:
    f.write(plan_raw)
straw = js({"schema": "hepta.full-stage-manifest.v1", "base_commit": BASE,
           "files": identities, "stages": stages})
with (OUT / "STAGE_MANIFEST_01.json").open("xb") as f:
    f.write(straw)
ar = makezip({"NATIVE_FINAL_PLAN_01.json": plan_raw, **payload})
ap = OUT / "publication-static-architecture-control-input-02.zip"
with ap.open("xb") as f:
    f.write(ar)
manifest = {"schema": "hepta.static-publication-ready.v1",
    "status": "FROZEN_READY_FOR_ROOT_REVIEW_NOT_PUBLISHED", "base_commit": BASE,
    "intended_native_operation": "publication-final-operation-05",
    "archive_path": str(ap), "archive_bytes": len(ar), "archive_sha256": sha(ar),
    "plan_path": str(OUT / "NATIVE_FINAL_PLAN_01.json"), "plan_bytes": len(plan_raw), "plan_sha256": sha(plan_raw),
    "stage_manifest_path": str(OUT / "STAGE_MANIFEST_01.json"),
    "stage_manifest_bytes": len(straw), "stage_manifest_sha256": sha(straw),
    "first_stage": 89, "last_stage": stages[-1]["number"], "stage_count": len(stages),
    "payload_files": len(payload), "payload_bytes": sum(map(len, payload.values())),
    "maximum_object_bytes": max(map(len, payload.values())),
    "maximum_text_stage_lines": max(s["added_text_lines"] for s in stages),
    "all_stages_under_500_lines": all(s["added_text_lines"] < 500 for s in stages),
    "mechanical_exceptions": 0, "original_inputs_rehashed_equal": len(inputs),
    "architecture_original_sha256": sha(original), "architecture_publication_sha256": sha(published),
    "architecture_edits": len(edits), "active_Run02_output_read": False,
    "no_model_test_verifier_C_or_Git_mutation": True,
    "root_must_copy_archive_to_direct_MacROOT_child": True,
    "stages": [{"number": s["number"], "files": len(s["files"]), "lines": s["added_text_lines"],
                "title": s["commit_subject"]} for s in stages]}
with (OUT / "MANIFEST.json").open("xb") as f:
    f.write(js(manifest))
print(json.dumps(manifest, sort_keys=True), flush=True)
