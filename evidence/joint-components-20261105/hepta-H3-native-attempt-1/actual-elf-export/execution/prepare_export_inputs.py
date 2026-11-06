"""Cloud-only construction of the exact H3 archival request; never launches it."""
import ast
import base64
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(name, raw):
    path = ROOT / name
    if path.exists():
        raise ValueError("fresh cloud preparation path required: " + str(path))
    path.write_bytes(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


base_path = WORK / "w1/h1-elf-export/export_retained_elfs.py"
base = base_path.read_bytes()
assert sha(base) == "8ba375f315433a4eea9a05b9f1a0fbcffced353eb668cca6cd799b433fa4402b"
code = base.replace(
    b'"""Losslessly package only explicitly pinned, already retained executable bytes.',
    b'"""Losslessly package explicitly pinned, already retained H3 executable bytes.',
).replace(
    b'require(plan["phase"] in ("H1", "H2"), "explicit source phase required")',
    b'require(plan["phase"] == "H3", "the explicit H3 source phase is required")',
)
assert code != base
before_tree, after_tree = ast.parse(base), ast.parse(code)
for left, right in zip(before_tree.body[1:], after_tree.body[1:], strict=True):
    if isinstance(left, ast.FunctionDef) and left.name == "validate_plan":
        left.body[2] = right.body[2]
    assert ast.dump(left) == ast.dump(right)
code_rec = write("export_h3_retained_images.py", code)
patch = "".join(difflib.unified_diff(base.decode().splitlines(True), code.decode().splitlines(True),
    fromfile="approved-H1/export_retained_elfs.py", tofile="H3/export_h3_retained_images.py"))
patch_rec = write("H3-exporter-vs-approved-H1.patch", patch.encode())

map_path = WORK / "model_storage/h3-preparation/native/joint-h3-native-attempt-1/h3-actual-image-inventory.json"
map_raw = map_path.read_bytes()
assert len(map_raw) == 278536 and sha(map_raw) == "6a8ecb8b9160284baf91d13b61973e4ee3b64b5a740cde0908ccd7b4c03361b7"
mapping = json.loads(map_raw)
commit, tree = "6db78eca53a5acdda0d96873d3f4cd65863426f0", "e91f5994017fc5d2cfe58d405a20ee6ad9376772"
assert (mapping["source_commit"], mapping["source_tree"], mapping["status"]) == (commit, tree, "FAILED")
assert mapping["partial_artifacts"] == []
assert len(mapping["images"]) == 11
assert sum(row["bytes"] for row in mapping["images"]) == mapping["complete_image_unique_bytes"] == 1674575368
assert sum(len(row["retained_aliases"]) for row in mapping["images"]) == mapping["complete_retained_alias_count"] == 30
assert len({row["sha256"] for row in mapping["images"]}) == 11
assert len(mapping["unmatched_live_observations"]) == 1
unmatched = mapping["unmatched_live_observations"][0]
assert unmatched["record"]["pid"] == 1038111 and unmatched["matching_fd"] is None
source_root = "/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf/evidence/joint-h3-native-attempt-1"
files = []
for row in mapping["images"]:
    aliases = row["retained_aliases"]
    assert len(aliases) == len(set(aliases))
    assert all(Path(alias).is_relative_to(source_root) and "target" not in Path(alias).parts for alias in aliases)
    assert all(observation["retained_copy"] in aliases and observation["source_commit"] == commit and
               observation["source_tree"] == tree for observation in row["observations"])
    files.append(dict(name="H3/elf/" + row["sha256"] + ".elf", bytes=row["bytes"], sha256=row["sha256"],
        source_path=aliases[0], aliases=aliases, original_actual_paths=row["actual_paths"],
        original_observations=row["observations"],
        role="complete-live-daemon-image" if row["kind"] == "ordinary-daemon" else "complete-recorded-test-image",
        selection_rule="First explicitly recorded retained alias in the frozen H3 inventory; other aliases remain provenance only and are not reopened by this export."))
daemon = [row for row in mapping["images"] if row["kind"] == "ordinary-daemon"]
assert len(daemon) == 1 and len(daemon[0]["retained_aliases"]) == 1
assert daemon[0]["bytes"] == 488112384 and daemon[0]["sha256"] == "00a637f55c720b06a655b569930bddaef19fd791467bc4784fe0bfb9e0002a26"
assert [row["full_hash_and_copy_this_capture"] for row in daemon[0]["observations"]] == [True, False]
assert [row["same_held_file_object_verified"] for row in daemon[0]["observations"]] == [False, True]
final_use = [row for row in files if row["sha256"] == "1383f1adbe7721e1ff362142f0ce35ef755bece0ae2a188cb28e375a2332b923"][0]
assert all(row["external_binding_gate_passed"] is False for row in final_use["original_observations"])
assert any(row["pid"] == 1038111 for row in final_use["original_observations"])

release_path = WORK / "w1/H3-owned-release-probe/proof.json"
release_raw = release_path.read_bytes()
assert sha(release_raw) == "06661599f4cd936baa7493ac4f9a1df95def4a0dd391f638145b46f1c032458e"
release = json.loads(release_raw)
assert release["job_id"] == "1a1ada80dcc-fc05-5a8b" and release["owned_processes_clear"] is True
assert release["original_authoritative_terminal"] == dict(at_unix_ms=1793916036769,exit_code=1,state="failed",timed_out=False)
outcome = {key: value for key, value in mapping.items() if key not in ("images", "source_commit", "source_tree")}
outcome["result"] = "FAILED"
outcome["native_job_id"] = release["job_id"]
total = sum(row["bytes"] for row in files)
plan = dict(schema="hepta-actual-retained-elf-export-plan-v1", phase="H3", source_commit=commit,
    source_tree=tree, source_root=source_root, files=files, total_elf_bytes=total,
    max_archive_bytes=total + 64 * 1024 * 1024, part_bytes=4 * 1024 * 1024,
    archive_name="H3-actual-retained-elfs.tar.xz",
    output_directory="/home/qian-qi/work/hepta-h3-actual-elf-export-20261105-93bfc-01",
    source_map=dict(local_original_path=str(map_path), bytes=len(map_raw), sha256=sha(map_raw),
                    data_base64=base64.b64encode(map_raw).decode()),
    release_prerequisite=dict(job_id=release["job_id"],
        path="/home/qian-qi/work/hepta-joint-h3-owned-release-20261105-93bfc-01.json",
        sha256=sha(release_raw),
        scope="Exact H3 owned unit/cgroup/process release only; root must reserve this archive component window."),
    original_run_outcome=outcome, native_reexecution=False,
    capture_limits="H3 remains FAILED at the external FinalUse live-to-FD correlation. Its 50 passing raw cases and 50 bijective FD records do not retrospectively identify the unmatched live PID 1038111. The ordinary daemon has one complete retained image: first-process full hash/copy and second-process verification of the same held file object, not a second full read/copy. All original aliases and observations remain verbatim in the embedded source inventory. No inferred target images, missing-case attribution, privileged-writer protection, or full runtime/dependency closure is claimed.",
    selected_source_paths=len(files), alias_paths_total=30, unselected_alias_paths=19,
    partial_artifacts=[], partial_artifact_scope=mapping["partial_artifact_scope"],
    proposed_transport_budget_seconds=900,
    transport_budget_scope="New bounded post-terminal archive component only; no native test or benchmark reexecution and no automatic retry.",
    publication_contract="Require an authoritative successful archive job plus completion.json with status COMPLETE and all pinned archive/part/index hashes; file existence alone is insufficient.")
plan_raw = encoded(plan)
plan_rec = write("H3-export-plan.json", plan_raw)
spec = importlib.util.spec_from_file_location("h3_export", ROOT / "export_h3_retained_images.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
validated, original = module.validate_plan(plan_raw)
assert validated == plan and original == map_raw
assert len(plan_raw) < 2 * 1024 * 1024

test = (WORK / "w1/h1-elf-export/test_export_utility.py").read_text()
test = test.replace("export_retained_elfs.py", "export_h3_retained_images.py").replace('"H1', '"H3')
test_rec = write("test_export_utility.py", test.encode())

old_bootstrap = (WORK / "w1/h2-elf-export/H2-export-bootstrap.py").read_text()
suffix = old_bootstrap[old_bootstrap.index("STAGE = Path("):]
suffix = suffix.replace("hepta-h2-actual-elf-export-inputs-", "hepta-h3-actual-elf-export-inputs-")
suffix = suffix.replace("export_h2_retained_images.py", "export_h3_retained_images.py").replace("H2-export-plan.json", "H3-export-plan.json")
suffix = suffix.replace("2a18729275fe2051b3f691fce56542e2d1291193e983330fe82601caf22349b3", sha(plan_raw))
suffix = suffix.replace("37538f62fd81398262ccde1b9cfa0d1cb0163b115e108b80220ab7af8f929365", sha(code))
inputs = [dict(name=name, bytes=len(raw), sha256=sha(raw), base64=base64.b64encode(raw).decode())
          for name, raw in [("export_h3_retained_images.py", code), ("H3-export-plan.json", plan_raw)]]
bootstrap = ("import base64,hashlib,json,os,stat\nfrom pathlib import Path\nINPUTS = json.loads(" +
             repr(json.dumps(inputs, separators=(",", ":"))) + ")\n" + suffix).encode()
ast.parse(bootstrap)
bootstrap_rec = write("H3-export-bootstrap.py", bootstrap)
request = dict(host="desktop", executable="/usr/bin/python3", args=["-B", "-"], cwd="/home/qian-qi/work",
    env={"PYTHONDONTWRITEBYTECODE":"1"}, stdin=bootstrap.decode(), timeout_seconds=900,
    idempotency_key="93bfc-hepta-h3-actual-retained-images-export-01")
request_rec = write("H3-export-frozen-launch-request.json", encoded(request))
manifest = dict(schema="H3-cloud-only-archive-preparation-v1", remote_started=False,
    root_review_and_window_reservation_required=True,
    approved_complete_only_exporter=dict(path=str(base_path),bytes=len(base),sha256=sha(base)),
    exporter_semantic_delta="Only docstring and exact phase H3 validation; all I/O, limits, two-read, no-overwrite, archive/member/part verification, and fsync function bodies remain identical to approved H1.",
    source_map=dict(path=str(map_path),bytes=len(map_raw),sha256=sha(map_raw)),
    release_proof=dict(path=str(release_path),bytes=len(release_raw),sha256=sha(release_raw)),
    files=[code_rec,patch_rec,plan_rec,test_rec,bootstrap_rec,request_rec],
    original_outcome="FAILED", unique_complete_images=11, complete_aliases=30, selected_paths=11,
    other_aliases_metadata_only=19, total_actual_input_bytes=total,
    container_max_bytes=total+64*1024*1024, archive_plus_parts_max_bytes=2*(total+64*1024*1024),
    compression_preset=3, compression_processes=1, transport_budget_seconds=900,
    actual_compressed_size="unknown until successful measured export",
    utility_scope="Pending local byte-fixture controls only; no native/learning/process execution credit.")
manifest_rec = write("cloud-preparation-manifest.json", encoded(manifest))
print(json.dumps(dict(exporter=code_rec,plan=plan_rec,request=request_rec,manifest=manifest_rec,
    source_unique_bytes=total,source_aliases=30,bootstrap_bytes=len(bootstrap)),sort_keys=True))
