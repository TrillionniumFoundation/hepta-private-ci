"""Package immutable research code and engineering evidence; never run a model."""
import difflib
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import time
import zipfile

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
OUT = ROOT / "research-publication-source-01"
WORK = ROOT / "publication-native-01"
BASE = "6b63615afc272cec57d8b3d26bd0135f02e440d9"
PREFIX = "qualification/cell-experiments-v3-20261116/operations/research-source-v1/"
SRC = ROOT / "research-sft-v1-source-working"
DIAG = ROOT / "operations/research-diagnostic-v1-source"
OPS = ROOT / "operations"
files, stages, origins, checks = {}, [], {}, []


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def js(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def read(path, expected=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular source required: " + str(path))
    raw = path.read_bytes()
    if expected and sha(raw) != expected:
        raise ValueError("source SHA differs: " + str(path))
    return raw


def put(name, raw, origin):
    full = PREFIX + name
    if full in files or len(raw) >= 512000:
        raise ValueError("duplicate or oversized payload")
    if any(p.startswith(".hepta-") for p in Path(name).parts):
        raise ValueError("no standalone transport temporary file")
    files[full], origins[full] = raw, origin
    return full


def copy(path, name, expected=None):
    return put(name, read(path, expected), str(path))


def git(*args):
    p = subprocess.run(["git", *args], cwd=WORK, capture_output=True, timeout=60)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout


def bundle(path, expected, index):
    raw = read(path, expected)
    z = zipfile.ZipFile(io.BytesIO(raw))
    if z.testzip() or len(z.namelist()) != len(set(z.namelist())):
        raise ValueError("invalid archive CRC or duplicate member")
    for item in z.infolist():
        name = Path(item.filename)
        if name.is_absolute() or ".." in name.parts or stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError("unsafe archive member")
    m = json.loads(z.read(index))
    if set(z.namelist()) != set(m["files"]) | {index}:
        raise ValueError("archive membership differs")
    for name, identity in m["files"].items():
        data = z.read(name)
        if len(data) != identity["bytes"] or sha(data) != identity["sha256"]:
            raise ValueError("archive member SHA differs")
    checks.append({"path": str(path), "sha256": sha(raw), "bytes": len(raw),
                   "members": len(z.namelist()), "verified_member_hashes": len(m["files"])})
    return raw, z, m


def stage(title, names, note=""):
    n = 52 + len(stages)
    branch = "codex/cell-experiments-v3-20261116-0c078a-s"
    stages.append({
        "id": "s%d-research-source" % n, "number": n,
        "commit_subject": title, "draft_pr_title": "[draft] " + title,
        "draft_pr_head": branch + str(n), "draft_pr_base": branch + str(n - 1),
        "draft_pr_body": (
            "Preserve the separate research-only SFT protocol, reviewable implementation, "
            "or exact original engineering evidence. The unchanged native positive-A "
            "qualification gate remains intact. This source package contains no actual "
            "pretrained-model research fit, independent users/teachers/sources, new C, "
            "learned Circuit benefit, PoUW qualification or native adoption. Actual "
            "operation results belong to a separate evidence publication. " + note),
        "files": names, "kind": "bounded_evidence_and_reviewable_source",
        "mechanical_evidence_exception": None})


if git("rev-parse", "HEAD").decode().strip() != BASE or git("status", "--porcelain=v1").strip():
    raise ValueError("publication base or worktree differs")
prior = json.loads(read(ROOT / "parent-readiness-frozen-02/NATIVE_FINAL_PLAN_01.json",
    "d11863862716f1a9032f038c1f76705268c1c36af06da7dc6116d6d6a9e69b66"))
core = {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2]
        for line in git("ls-tree", "-r", "HEAD", "--", "scripts/cell_experiments").decode().splitlines()
        if line.endswith(".py")}
if core != prior["expected_complete_core_git_blobs"] or len(core) != 64:
    raise ValueError("frozen 64 core Git blobs differ")
sr, sz, sm = bundle(SRC / "RESEARCH_SOURCE_V1.zip",
    "a3e2228377c20dab52a8cdfa20ce3cef62f92b75c5eacb1a5cea426b43e922bc",
    "FINAL_SOURCE_MANIFEST_V1.json")
cr, cz, cm = bundle(SRC / "CPU_ENGINEERING_01.zip",
    "78629fbaf830a733e09a77b733e33ec38546c57daa2f8899f5a8f28902794381",
    "EXPORT_INDEX_01.json")
dr, dz, dm = bundle(DIAG / "qwen-research-diagnostic-helper-01.zip",
    "c395702327f6cf3356b611c4533a0a9c82759f8141b5165703051fa0107ec2a3", "MANIFEST.json")
s = {n: put("research/" + n, sz.read(n), str(SRC / "RESEARCH_SOURCE_V1.zip") + "::" + n)
     for n in sz.namelist()}
stage("Freeze authored-target SFT research protocol", [
    s["RESEARCH_PROTOCOL_V1.md"], s["README_RESEARCH_SFT_V1.md"], s["LAUNCH_INPUTS_V1.json"]])
for name, title in [
    ("research_sft_contract_v1.py", "Add separate research SFT admission contract"),
    ("research_sft_train_v1.py", "Add research SFT numerical training entry"),
    ("research_sft_execution_v1.py", "Add research collection and evaluation workers"),
    ("run_research_sft_v1.py", "Add bounded research study coordinator")]:
    stage(title, [s[name]])
stage("Record research training differences and source identity", [
    s["RESEARCH_VS_ORIGINAL_TRAIN.diff"], s["NUMERICAL_KERNEL_DIFF.json"],
    s["FINAL_SOURCE_MANIFEST_V1.json"]])
def cpu_source(names):
    return [put("engineering/source/" + n, cz.read(n), str(SRC / "CPU_ENGINEERING_01.zip") + "::" + n)
            for n in names]
stage("Add actual research contract and tensor engineering cases",
      cpu_source(["test_research_sft_v1.py", "test_research_sft_tensor_v1.py"]))
stage("Preserve CPU engineering harness and shared test fixtures",
      cpu_source(["engineering_controller_v1.py", "engineering_entry_v1.py", "test_qwen_development_v3.py"]))
parts, part_paths = [], []
for number, offset in enumerate(range(0, len(cr), 300000)):
    name = "CPU_ENGINEERING_01.part%03d.bin" % number
    raw = cr[offset:offset + 300000]
    part_paths.append(put("engineering/archive/" + name, raw, "exact original CPU archive byte slice"))
    parts.append({"path": name, "offset": offset, "bytes": len(raw), "sha256": sha(raw)})
if b"".join(files[n] for n in part_paths) != cr:
    raise ValueError("CPU archive part reconstruction differs")
pm = put("engineering/archive/MANIFEST.json", js({
    "schema": "hepta.research-cpu-evidence-parts.v1",
    "filename": "CPU_ENGINEERING_01.zip", "bytes": len(cr), "sha256": sha(cr),
    "members": len(cz.namelist()), "member_index": "EXPORT_INDEX_01.json",
    "original_zip_preserved_byte_for_byte": True, "parts": parts,
    "real_Qwen_generations": 0, "real_research_fits": 0}), "generated exact part manifest")
restore = put("engineering/archive/RESTORE.md", b"""# Restore original CPU evidence

Concatenate the two parts in manifest order to recover CPU_ENGINEERING_01.zip.
Verify its byte count and full SHA256, then verify ZIP CRC and every one of
the 372 file records in EXPORT_INDEX_01.json. That index is the 373rd member.

Ten zero-byte transport lock members remain inside the opaque original ZIP.
They are historical metadata with no evidence or sample meaning; no standalone
lock is added to this repository. Symlink fixtures are explicit metadata,
not links to be followed during restoration.

The archive contains twelve actual behavioral tests and one actual tiny random
Qwen2/PEFT CPU test, including real optimizer and adapter bytes. It contains
zero pretrained Qwen generations, zero real research fits, and zero actual
authored business-verifier executions.
""", "generated byte restoration instructions")
original_source = put("transport/RESEARCH_SOURCE_V1.zip", sr, "exact original source ZIP")
handoff = copy(SRC / "HANDOFF_V1.json", "research/HANDOFF_V1.json",
    "1c8959e5377fdac8f51a61b70cf162b8c2d9e13577700fcfa8c072ead6c97a92")
stage("Preserve actual CPU engineering results and complete raw evidence", [
    s["RESEARCH_ENGINEERING_SUMMARY_V1.json"], s["ENGINEERING_SOURCE_MANIFEST.json"],
    s["CPU_ENGINEERING_01_RECEIPT.json"], s["CPU_ENGINEERING_TERMINAL_01.json"],
    handoff, original_source, pm, restore, *part_paths])
history = [copy(SRC / n, "history/" + n) for n in [
    "MIGRATION_STARTED.json", "MAC_CHECKPOINT_01.json", "MAC_PATCH_01.json", "MAC_INTERFACE_02.json"]]
old_util = copy(OPS / "archive_qwen_final_v3.py", "archive/previous/archive_qwen_final_v3.py",
    "7bcd81d5bc8cae58c03a80c62e5c39f858a5996c1df1768ac4252a2d58fb80d1")
stage("Preserve source recovery boundary and original archive utility", [*history, old_util])

d = {n: put("diagnostic/" + n, dz.read(n), str(DIAG / "qwen-research-diagnostic-helper-01.zip") + "::" + n)
     for n in dz.namelist()}
stage("Add frozen read-only research diagnostic", [d["qwen_research_diagnostic_v1.py"]],
      "The complete frozen diagnostic is one file under the mandatory 800-line ceiling; "
      "splitting its contents would alter its frozen source identity.")
stage("Freeze diagnostic rules and actual behavioral test source", [
    d["test_qwen_research_diagnostic_v1.py"], d["QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json"],
    d["QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.template.json"], d["README.md"]])
used = {n for group in stages for n in group["files"]}
d_rest = [n for n in d.values() if n not in used]
d_original = put("transport/qwen-research-diagnostic-helper-01.zip", dr, "exact original diagnostic ZIP")
d_verified = copy(DIAG / "PACKAGE_VERIFIED_01.json", "diagnostic/PACKAGE_VERIFIED_01.json",
    "72c312c6db4a0c2da58b8c5d57849faa50954a29a0527d63898ad2e32c68082b")
d_history = [copy(DIAG / n, "diagnostic/history/" + n)
             for n in ["TESTS_01.json", "TESTS_01.stdout.log", "TESTS_01.stderr.log"]]
stage("Preserve independent diagnostic review and actual test receipts",
      [*d_rest, d_original, d_verified, *d_history])

owned = [copy(OPS / name, "owned/" + name, identity) for name, identity in [
    ("launch_qwen_research_owned_v1.py", "4f647ae7e7cc5f5f0d04b597db10f0a68b946ecff04821651a16633bfe02eab0"),
    ("check_research_owned_launcher_01.py", "107991b3ef63faba10df83f02317748165f560e4461a36775687d051702e8644"),
    ("RESEARCH_OWNED_LAUNCHER_ENGINEERING_01.json", "2ffbaa5063ace86b14e9f11a42dbd403df4952a136b50b0962c555fe1f401f6c")]]
for p in sorted((ROOT / "owned-launcher-engineering-01").iterdir()):
    if p.is_file() and not p.name.startswith("."):
        owned.append(copy(p, "owned/engineering/" + p.name))
stage("Preserve owned process launcher and closed-pipe engineering evidence", owned)
a1 = read(OPS / "archive_qwen_research_v1.py",
    "1b88e687a6c92148f6efff6bfd77bf0e20ae42eb613181e6d1ef523dd2d0e903")
a2 = read(OPS / "archive_qwen_research_v1_02.py",
    "658438b68dff7a039a9631beb9e07ded8e7f56de23912672f868a531e063c3b2")
old, new = b'root / DIAG / "RESULT.json"', b'root / DIAG / "DIAGNOSTIC.json"'
if a1.count(old) != 1 or a1.replace(old, new) != a2:
    raise ValueError("archive02 differs from the reviewed one-literal change")
old_archive = [put("archive/archive_qwen_research_v1.py", a1, str(OPS / "archive_qwen_research_v1.py"))]
old_archive += [copy(OPS / name, "archive/" + name, identity) for name, identity in [
    ("check_research_archive_01.py", "90ab35644fddf2fbe6b4d52db6c6920910829dd2a8da376432f3e2e28f18fc6f"),
    ("RESEARCH_ARCHIVE_ENGINEERING_01.json", "de2e39ae1cecdfc5f38e65073386d5ed1917a863a16602f3798831ed404de790")]]
for p in sorted((ROOT / "research-archive-engineering-01").iterdir()):
    if p.is_file() and not p.name.startswith("."):
        old_archive.append(copy(p, "archive/engineering/" + p.name))
stage("Preserve original archive helper and actual terminal-binding checks", old_archive)
new_archive = put("archive/archive_qwen_research_v1_02.py", a2, str(OPS / "archive_qwen_research_v1_02.py"))
patch = "".join(difflib.unified_diff(a1.decode().splitlines(True), a2.decode().splitlines(True),
    fromfile="archive_qwen_research_v1.py", tofile="archive_qwen_research_v1_02.py")).encode()
diff_path = put("archive/ARCHIVE_DIAGNOSTIC_PATH_02.diff", patch, "generated exact one-literal difference")
archive_note = put("archive/README.md", b"""# Archive helper revision 02

The final export entry is archive_qwen_research_v1_02.py. It changes only the
diagnostic filename from RESULT.json to DIAGNOSTIC.json, matching the frozen
reader's output. Revision 01 and the exact minimal diff remain unchanged here.

The three engineering checks actually executed revision 01. Revision 02 has
a verified one-literal source difference. No extra engineering run or actual
research export is claimed by this source package. Root owns the actual export.

The helper binds owned waits, stopped writers, exact launch/freezes and raw
logs. It does not claim atomic snapshots, turn missing costs into zero,
or authorize adoption.
""", "generated archive version boundary note")
stage("Bind final archive helper to the frozen diagnostic output",
      [new_archive, diff_path, archive_note])

locks = [{"path": n, **v} for n, v in cm["files"].items()
         if any(p.startswith(".hepta-") for p in Path(n).parts)]
if len(locks) != 10 or any(v["bytes"] != 0 for v in locks):
    raise ValueError("original lock metadata count differs")
coverage = {
    "schema": "hepta.research-source-publication-coverage.v1",
    "prepared_at_ns": time.time_ns(), "publication_base": BASE,
    "source_scope": "prefit implementation, frozen diagnostic and engineering only",
    "input_archives": checks, "original_core_python_files": 64,
    "original_core_git_blobs_unchanged": True,
    "runtime_modules": sm["runtime_modules"],
    "diagnostic_source": dm["files"]["qwen_research_diagnostic_v1.py"],
    "diagnostic_rules": dm["files"]["QWEN_RESEARCH_DIAGNOSTIC_FREEZE_01.json"],
    "original_cpu_zip_preserved_byte_for_byte": True,
    "opaque_original_archive_empty_non_evidence_lock_members": locks,
    "standalone_lock_files": 0,
    "excluded": ["base pretrained weights", "venv", "runtime caches", "future results",
                 "unverified draft diagnostic fragments"],
    "recovery": {
        "old_local_RAM_original_lost": True, "old_design_original_bytes_recovered": False,
        "historical_design_sha256": "d4aa19925cd347602e853570c2ff62c1b7744597aaa70c9f2cc18a883162738f",
        "new_protocol_sha256": "1f3171699624a18f705728f495d81c51c4909d2e7c3a6950df14335b31cdc0ee",
        "original_migration_and_checkpoint_receipts_preserved": True},
    "engineering": {
        "actual_behavior_tests": 12, "actual_tiny_tensor_tests": 1, "actual_tiny_tensor_steps": 64,
        "actual_final_diagnostic_tests": 10, "prior_diagnostic_receipt_separate": True,
        "owned_fixture_expected_exit": 7, "archive01_actual_checks": 3,
        "archive02_one_literal_difference_verified": True, "archive02_extra_tests_claimed": 0,
        "real_pretrained_Qwen_generations": 0, "real_research_fits": 0,
        "actual_authored_business_verifier_calls": 0},
    "qualification": {
        "research_only": True, "scientific_confirmation_qualified": False,
        "native_cell_adoption": False, "proof_of_useful_work_eligible": False,
        "circuit_qualified": False, "new_C": False, "candidate_selected": None,
        "independent_sample_increment": 0, "new_users": 0, "new_teachers": 0},
    "actual_operation_results": "not included; require separate real-operation evidence",
    "Git_mutations_by_packager": False, "atomic_filesystem_snapshot_claimed": False}
c_path = put("COVERAGE.json", js(coverage), "generated verified coverage index")
r_path = put("README.md", b"""# Separate authored-target SFT research source

This package preserves code, protocol, fixed diagnostic rules and actual
engineering evidence prepared for a new exploratory study after complete
parent03 A=0/6. It contains no later pretrained-model operation results.
Historical fields such as actual_run_started describe their original file's
freeze time, not the current live operation state.

## Scientific boundary

The original 64 core files and positive-A native qualification gate remain
unchanged. The separate research.authored-sft.v1 schema admits authorized,
business-checked authored A labels for this explicitly post-failure study.
It neither invents baseline success nor creates a native qualified candidate.

The six arms reuse exposed development tasks. Replays, seeds, cold processes,
synthetic fixtures and source partitions add no independent samples, users,
teachers or new C. Four plans must be frozen before the first actual fit.
The fixed diagnostic slots are final answer, trajectory and controlled
correction, with shadow correction separate. An oracle union is not learned
routing or per-edge ablation. Cold loading and changed weights alone do not
establish useful learning, adoption or Proof of Useful Work.

## Package contents

- research/: exact runtime modules, protocol restatement, launch inputs,
  manifests, numerical diff and actual CPU engineering summary.
- engineering/source/: tested behavioral and tensor cases plus real harness.
- engineering/archive/: two exact parts of the original complete CPU ZIP.
- diagnostic/: frozen reader, rules, independent review, final ten-test
  evidence and earlier nine-test receipts preserved separately.
- owned/: owned launcher and actual closed-control-pipe fixture evidence.
- archive/: original utility, tested revision 01, final revision 02 and the
  exact one-literal diagnostic output filename correction.
- history/: retained RAM-loss, migration, patch and checkpoint receipts.
- transport/: exact original source and diagnostic ZIP packages.

The original CPU ZIP contains ten zero-byte transport locks. They remain
only inside the opaque original bytes and have no sample or evidence meaning.
No standalone lock/upload temporary file is added. Pretrained base weights,
venv, caches, future model outputs and unverified drafts are excluded.

## Evidence and use

Twelve behavioral cases and one tiny random Qwen2/PEFT CPU case actually
completed with zero skips or timeouts. The tiny case used the real 64-step
loss, gradients, AdamW and adapter save/reload. It did not load pretrained
Qwen, perform a real research fit or execute authored business verifiers.
The diagnostic's final ten cases checked read-only accounting and failure
behavior. These engineering checks do not enter task success or fit budgets.

Deploy the exact source packages and their manifests. The original pinned
HOME venv remains the runtime; RAM holds inputs, outputs, source and caches.
Helpers04 and complete parent03 evidence are already in the previous stack.
Actual launch, worker exits, model results, full costs and cold outcomes
require the separate later operation archive.

The old local design original was lost with RAM. RESEARCH_PROTOCOL_V1.md is
a new explicit restatement with its own SHA. Its historical design SHA is
an identity reference, never a claim that original bytes were recovered.
Failures, missing cost tails and qualification exclusions remain explicit.
""", "generated source scope and qualification boundary")
stage("Document research package coverage and explicit qualification limits", [c_path, r_path])

all_names = [n for group in stages for n in group["files"]]
if len(all_names) != len(set(all_names)) or set(all_names) != set(files):
    raise ValueError("stage partition differs")
tree = OUT / "payload"
tree.mkdir(exist_ok=False)
identities = {}
for name, raw in sorted(files.items()):
    path = tree / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw)
    p = subprocess.run(["git", "diff", "--no-index", "--numstat", "--", "/dev/null", str(path)],
                       cwd=OUT, capture_output=True, timeout=60)
    if p.returncode not in (0, 1):
        raise RuntimeError(p.stderr.decode(errors="replace"))
    first = p.stdout.decode().split("\t", 1)[0] if p.stdout else "0"
    lines = 0 if first == "-" else int(first)
    identities[name] = {"bytes": len(raw), "sha256": sha(raw),
                        "git_added_text_lines": lines, "origin": origins[name]}
for group in stages:
    group["added_text_lines"] = sum(identities[n]["git_added_text_lines"] for n in group["files"])
    group["prefer_under_500_met"] = group["added_text_lines"] < 500
    group["mechanical_json_evidence"] = [n for n in group["files"] if n.endswith((".json", ".jsonl"))]
    if group["added_text_lines"] > 800:
        raise ValueError("stage exceeds 800 lines: " + group["id"])
attrs = git("check-attr", "-z", "diff", "--", *sorted(files)).split(b"\0")
if any(attrs[i] != b"unspecified" for i in range(2, len(attrs) - 1, 3)):
    raise ValueError("destination diff attributes require review")
plan = {
    "schema": "hepta.native-final-publication-plan.v3", "base_commit": BASE,
    "frozen_at_ns": time.time_ns(), "binary_part_limit": 322560,
    "git_object_limit_exclusive": 512000, "expected_complete_core_git_blobs": core,
    "source_scope": "separate research sources, fixed diagnostic and engineering only",
    "new_model_execution": False, "files": identities, "stages": stages}
plan_raw = js(plan)
with (OUT / "NATIVE_FINAL_PLAN_01.json").open("xb") as f:
    f.write(plan_raw)
archive = OUT / "publication-research-source-input-01.zip"
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for name, raw in [("NATIVE_FINAL_PLAN_01.json", plan_raw), *sorted(files.items())]:
        info = zipfile.ZipInfo(name, date_time=(2026, 11, 17, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        z.writestr(info, raw)
with zipfile.ZipFile(archive) as z:
    if z.testzip() or set(z.namelist()) != set(files) | {"NATIVE_FINAL_PLAN_01.json"}:
        raise ValueError("final archive CRC or membership differs")
    if z.read("NATIVE_FINAL_PLAN_01.json") != plan_raw:
        raise ValueError("final plan bytes differ")
    for name, raw in files.items():
        if z.read(name) != raw:
            raise ValueError("final payload bytes differ")
if git("rev-parse", "HEAD").decode().strip() != BASE or git("status", "--porcelain=v1").strip():
    raise ValueError("publication tree changed during preparation")
manifest = {
    "schema": "hepta.research-source-publication-ready.v1",
    "status": "FROZEN_READY_FOR_ROOT_REVIEW_NOT_PUBLISHED",
    "archive_path": str(archive), "archive_bytes": archive.stat().st_size,
    "archive_sha256": sha(archive.read_bytes()),
    "plan_path": str(OUT / "NATIVE_FINAL_PLAN_01.json"),
    "plan_bytes": len(plan_raw), "plan_sha256": sha(plan_raw),
    "base_commit": BASE, "first_stage": 52, "last_stage": stages[-1]["number"],
    "stage_count": len(stages), "payload_files": len(files),
    "payload_bytes": sum(len(x) for x in files.values()),
    "maximum_object_bytes": max(len(x) for x in files.values()),
    "maximum_text_stage_lines": max(x["added_text_lines"] for x in stages),
    "mechanical_exceptions": 0, "standalone_lock_files": 0,
    "root_must_copy_archive_to_direct_MacROOT_child": True,
    "original_sources_unmodified": True, "native_worktree_unmodified": True,
    "new_models_or_tests_executed": False,
    "stages": [{"number": x["number"], "files": len(x["files"]),
                "lines": x["added_text_lines"], "prefer_under_500_met": x["prefer_under_500_met"],
                "title": x["commit_subject"]} for x in stages]}
with (OUT / "MANIFEST.json").open("xb") as f:
    f.write(js(manifest))
print(json.dumps(manifest, sort_keys=True), flush=True)
