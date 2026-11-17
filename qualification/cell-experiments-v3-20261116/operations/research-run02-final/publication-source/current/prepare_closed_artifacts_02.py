"""Prepare immutable copies of closed Run02 evidence; no final publication plan."""
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
PREP = OUT / "prepared"
BASE = "6b8d8c44a183c48e761aff76e0570ab278b4f7da"
WORK = ROOT / "publication-native-01"
PART = 322560
inputs = {}
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def js(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
def line(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
def read(path, expected=None):
    if not path.is_relative_to(ROOT) or path.is_symlink() or not path.is_file():
        raise ValueError("invalid task-owned regular input")
    raw = path.read_bytes()
    item = {"bytes": len(raw), "sha256": sha(raw)}
    if expected and item["sha256"] != expected:
        raise ValueError("input SHA differs: " + str(path))
    if inputs.setdefault(str(path.relative_to(ROOT)), item) != item:
        raise ValueError("input changed across reads")
    return raw
def write(name, raw):
    p = PREP / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as f:
        f.write(raw)
    return {"path": str(p.relative_to(OUT)), "bytes": len(raw), "sha256": sha(raw)}
def makezip(contents):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, raw in sorted(contents.items()):
            e = zipfile.ZipInfo(name, (2026, 11, 17, 0, 0, 0))
            e.compress_type = zipfile.ZIP_DEFLATED
            e.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(e, raw)
    raw = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() or len(z.namelist()) != len(contents) or set(z.namelist()) != set(contents):
            raise ValueError("prepared ZIP CRC/membership differs")
        if any(z.read(n) != b for n, b in contents.items()):
            raise ValueError("prepared ZIP member bytes differ")
    return raw
def directory_files(names):
    rows = []
    for name in names:
        root = ROOT / name
        if not root.is_dir() or root.is_symlink():
            raise ValueError("required closed directory absent")
        for path in sorted(root.rglob("*")):
            if path.name.startswith("."):
                continue
            if path.is_symlink():
                raise ValueError("unexpected selected symlink")
            if path.is_file():
                rows.append(path)
    return rows
def bundle(name, paths, notes):
    contents = {}
    for path in paths:
        rel = str(path.relative_to(ROOT))
        if rel in contents:
            raise ValueError("duplicate closed evidence member")
        contents[rel] = read(path)
    raw = makezip(contents)
    whole = write(name + "/" + name + ".zip", raw)
    parts = [write(name + "/part-%05d.bin" % i, raw[offset:offset+PART])
             for i, offset in enumerate(range(0, len(raw), PART))]
    index = b"".join(line({"path": n, "bytes": len(b), "sha256": sha(b)})
                     for n, b in sorted(contents.items()))
    index_file = write(name + "/MEMBERS.jsonl", index)
    descriptor = {"schema": "hepta.closed-run02-evidence-zip.v1",
        "archive": whole, "parts": parts, "member_index": index_file,
        "members": len(contents), "source_bytes": sum(map(len, contents.values())),
        "notes": notes, "original_member_bytes_unchanged": True,
        "atomic_filesystem_snapshot_claimed": False,
        "independent_sample_increment": 0, "new_model_test_verifier_C_calls": 0}
    manifest = write(name + "/MANIFEST.json", js(descriptor))
    return {**descriptor, "manifest": manifest}
p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORK, capture_output=True, check=True)
s = subprocess.run(["git", "status", "--porcelain=v1"], cwd=WORK, capture_output=True, check=True)
if p.stdout.decode().strip() != BASE or s.stdout.strip():
    raise ValueError("native base or clean status differs")
PREP.mkdir(exist_ok=False)
export = ROOT / "research-final-export-02"
manifest_raw = read(export / "TRANSFER_MANIFEST.json",
    "4a6f4fae9a04d7afe86476d36fb55767388a15f4a3d98dfa2dcb1795163b3ec9")
manifest = json.loads(manifest_raw)
objects, restored = [], {}
for role in ("archive", "members"):
    raw_parts = []
    for row in manifest[role]["parts"]:
        raw = read(export / row["path"], row["sha256"])
        if len(raw) != row["bytes"] or len(raw) > PART:
            raise ValueError("original part size differs")
        raw_parts.append(raw)
        objects.append({"path": row["path"], "bytes": len(raw), "sha256": sha(raw),
                        "publication_storage": "direct" if role == "archive" else "lossless_index_parts_ZIP"})
    raw = b"".join(raw_parts)
    if len(raw) != manifest[role]["bytes"] or sha(raw) != manifest[role]["sha256"]:
        raise ValueError("original object reconstruction differs")
    if raw != read(export / manifest[role]["transport_path"], manifest[role]["sha256"]):
        raise ValueError("reconstruction does not equal original transport bytes")
    restored[role] = raw
if len(manifest["archive"]["parts"]) != 93 or len(manifest["members"]["parts"]) != 2:
    raise ValueError("original split inventory differs")
member_rows = [json.loads(v) for v in restored["members"].splitlines()]
members = {r["path"]: r for r in member_rows}
if len(members) != 1687 or len(member_rows) != 1687:
    raise ValueError("original archive member inventory differs")
with zipfile.ZipFile(io.BytesIO(restored["archive"])) as z:
    if z.testzip() or set(z.namelist()) != set(members) or len(z.namelist()) != len(members):
        raise ValueError("original archive CRC/membership differs")
    for name, row in members.items():
        raw = z.read(name)
        if len(raw) != row["bytes"] or sha(raw) != row["sha256"]:
            raise ValueError("original archived member identity differs")
for name in ("TRANSFER_MANIFEST.json", "RESTORE.txt"):
    raw = read(export / name)
    objects.append({"path": name, "bytes": len(raw), "sha256": sha(raw), "publication_storage": "direct"})
if len(objects) != 97:
    raise ValueError("original Git-object inventory differs")
index_zip = bundle("export-index-original-parts",
    [export / row["path"] for row in manifest["members"]["parts"]],
    "Two exact original index parts retain their original paths and bytes in this lossless ZIP. Extract them to their original export directory after verifying every SHA; original TRANSFER_MANIFEST and RESTORE remain authoritative.")
object_map = write("ORIGINAL_EXPORT_97_OBJECTS.jsonl", b"".join(line(v) for v in sorted(objects,key=lambda r:r["path"])))
controllers = bundle("closed-controller-evidence",
    directory_files(["research-export-operation-02","research-postrun-preparation-02",
                     "research-terminal-inspection-02"]) + [export / "STARTED.json"],
    "Closed Mac export, postrun preparation and terminal inspection originals. Large files are preserved losslessly; source bytes and original paths are unchanged.")
observation_dirs = ["research02-watch-01"] + [f"research02-live-observation-{n:02d}" for n in list(range(1,35)) + [38]]
observations = bundle("closed-observation-evidence", directory_files(observation_dirs),
    "Original watch and 35 saved intermediate observation directories, including their failed/lost captures where present. These are non-atomic observations, not additional samples, independent executions or a replacement for final owned receipts.")
ops_names = ["RESEARCH02_CONTROLLER_LOSS_OBSERVATION_01.json",
    "RESEARCH02_CONTROLLER_LOSS_READBACK_01.json","RESEARCH_ACTUAL_LAUNCH_02.json",
    "RESEARCH_ACTUAL_OBSERVATION_02_01.json","RESEARCH_ACTUAL_TERMINAL_02.json",
    "RESEARCH_POSTRUN_TERMINAL_02.json","RESEARCH_RESOURCE_RECHECK_02.json",
    "RESEARCH_ROOT_REVIEW_02.json","RESEARCH_DEPLOY_OBSERVATION_02.json",
    "RESEARCH_PREFLIGHT_OBSERVATION_02.json"]
operation_records = bundle("closed-operation-records", [ROOT/"operations"/n for n in ops_names],
    "Selected actual launch, terminal, controller-loss and readback originals. Earlier lost observations and later completed original records coexist; their statuses are not rewritten.")
draft_raw = read(ROOT/"operations/STATIC02_DRAFT_PUBLICATION_01.json",
    "3cd5211fd04ada2ddab181889529eb0d861d06a5b4c2167cbfb9a8530de38a3e")
draft = json.loads(draft_raw)
if len(draft["prs"]) != 8 or draft["head_commit"] != BASE or draft["all_remote_ref_shas_verified"] is not True:
    raise ValueError("closed static publication identity differs")
publication = bundle("closed-static-publication-evidence",
    [ROOT/"publication-final-operation-05/COMPLETE.json",
     ROOT/"operations/STATIC02_DRAFT_PUBLICATION_01.json"] +
    directory_files(["publication-static-root-check-02"]),
    "Closed static publication05 native COMPLETE, root checks and saved Draft PR verification originals. Their earlier and later statuses remain unchanged; no fresh API calls.")
tool_observations = json.loads(sys.argv[1])
observation_file = write("PREPARATION_OBSERVATIONS.json", js(tool_observations))
for rel, expected in inputs.items():
    raw = (ROOT/rel).read_bytes()
    if len(raw) != expected["bytes"] or sha(raw) != expected["sha256"]:
        raise ValueError("closed input changed during preparation")
summary = {"schema":"hepta.run02-publication-preparation.v1",
    "prepared_at_ns":time.time_ns(),"base_commit":BASE,
    "final_publication_plan_frozen":False,"pending_root_final_review_and_diagnostic_disposition":True,
    "export_archive_sha256":manifest["archive"]["sha256"],"export_member_count":len(members),
    "original_git_object_count":len(objects),"original_object_map":object_map,
    "bundles":[index_zip,controllers,observations,operation_records,publication],
    "preparation_observation_file":observation_file,
    "inputs":inputs,"all_input_rechecks_equal":True,
    "model_test_verifier_C_calls":0,"Git_or_PR_mutated":False,
    "raw_diagnostic_not_modified_or_reinterpreted":True}
final = write("PREPARATION_MANIFEST.json", js(summary))
result = {"manifest":final,"original_objects":len(objects),"members":len(members),
    "bundles":[{"name":b["archive"]["path"],"bytes":b["archive"]["bytes"],
                "sha256":b["archive"]["sha256"],"parts":len(b["parts"]),"members":b["members"]}
               for b in summary["bundles"]],
    "original_inputs_rechecked":len(inputs),"final_plan_frozen":False}
print(json.dumps(result),flush=True)
