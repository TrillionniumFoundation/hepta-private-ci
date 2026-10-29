"""Package non-Git raw evidence; verify every member without rewriting results."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import zipfile

ROOT = Path(__file__).resolve().parent

def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()

def candidates(kind):
    files = set()
    if kind == "core":
        for pattern in ("data/*", "results/*/seed_*/**/*",
                        "results/probability_calibration/*.json.gz",
                        "results/numerical_roundoff_operator_diagnostic.npz",
                        "results/figures_history/**/*", "execution_attempts/**/*",
                        "hepta/native_results/**/*", "hepta/bootstrap_repair_results/**/*",
                        "hepta/rr_bridge_results/**/*", "hepta/ci_observation/*.log"):
            files.update(p for p in ROOT.glob(pattern) if p.is_file())
        for name in ("hepta/native_build/target/release/rrsnn-native-owner",
                     "hepta/native_build/target/release/rrsnn-native-bootstrap-repair",
                     "hepta/crate_validation_build/bin/hepta-neuron-unit-tests",
                     "hepta/rr_bridge_build/bin/rrsnn-rr-feature-broker"):
            files.add(ROOT/name)
        files.update(p for p in (ROOT/"execution_logs").glob("*.log")
                     if "policy-benchmark" not in p.name)
    else:
        matrix = json.loads((ROOT/"policy_benchmark_results/matrix.json").read_text())
        if matrix.get("all_completed") is not True or matrix.get("conditions") != 80:
            raise ValueError("Resource archive requires all 80 measured conditions")
        for pattern in ("policy_benchmark_results/**/*", "resource_audit/**/*"):
            files.update(p for p in ROOT.glob(pattern) if p.is_file())
        files.update((ROOT/"execution_logs").glob("*policy-benchmark*.log"))
        for pattern in ("*cleanup*.json", "*preservation_receipt.json",
                        "*publication*.json", "CONTINUATION_STATE.json",
                        "git_publications.json", "workspace_migration*.json",
                        "raw_archive_receipts/*.json"):
            files.update(p for p in ROOT.glob(pattern) if p.is_file())
    return sorted(p for p in files if "__pycache__" not in p.parts
                  and p.suffix not in (".lock", ".pyc")
                  and not ("figures_history" in p.parts and p.suffix == ".py"))

def package(kind, output, source_commit, published_paths):
    published_bytes = Path(published_paths).read_bytes()
    published = json.loads(published_bytes)
    if not isinstance(published, dict) or any(not isinstance(v, str) or len(v) != 40 or any(c not in "0123456789abcdef" for c in v) for v in published.values()):
        raise ValueError("Published paths must map relative paths to verified remote Git blob SHAs")
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("An immutable source commit is required")
    output = Path(output)
    if output.exists():
        raise FileExistsError("Archives are write-once")
    destination=ROOT/"raw_archive_receipts"/(kind+"_prepared.json")
    if destination.exists():
        raise FileExistsError("Prepared receipts are write-once")
    files, excluded = [], []
    for p in candidates(kind):
        if ROOT not in p.resolve().parents or p.is_symlink():
            raise ValueError("Candidate resolves outside the regular evidence tree: "+str(p))
        relative = str(p.relative_to(ROOT))
        if relative in published:
            b = p.read_bytes()
            blob = hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
            if blob != published[relative]:
                raise ValueError("Git-backed exclusion differs from immutable published bytes: "+relative)
            excluded.append({"path":relative,"git_blob_sha":blob,"sha256":sha_bytes(b),"bytes":len(b)})
        else:
            files.append(p)
    entries = []
    for p in files:
        if not p.is_file() or p.is_symlink():
            raise ValueError("Only regular raw files are packaged: "+str(p))
        b = p.read_bytes()
        entries.append({"path":"rrsnn_v4/"+str(p.relative_to(ROOT)),
                        "bytes":len(b),"sha256":sha_bytes(b)})
    manifest = {"schema":"rrsnn-v4-raw-evidence-archive-1",
        "kind":kind,"created_at_utc":datetime.now(timezone.utc).isoformat(),
        "source_repository":"TrillionniumFoundation/hepta-private-ci",
        "source_commit":source_commit,"source_commit_role":"minimum_completed_evidence_snapshot_final_report_head_may_be_later",
        "published_paths_sha256":sha_bytes(published_bytes),
        "package_script_sha256":sha_bytes(Path(__file__).read_bytes()),
        "root_prefix":"rrsnn_v4","raw_files":len(entries),
        "raw_bytes":sum(x["bytes"] for x in entries),"files":entries,
        "git_backed_items_excluded":True,"excluded_published_files":excluded,
        "interpretation":"Core and resource archives are complementary. Restore both beneath research/ in the final source checkout. Core covers completed training, main evaluations, original numerical controls, isolated repair, calibration and native raw proof/timing. Resources covers all 80 conditions and operational provenance. Neither archive changes a result or grants deployment permission."}
    output.parent.mkdir(parents=True,exist_ok=True)
    metadata = {
        "RAW_MANIFEST_"+kind+".json":(json.dumps(manifest,indent=2)+"\n").encode(),
        "RESTORE_"+kind+".txt":(
            "Check out the immutable final source commit delivered with the report. "
            "Extract BOTH complementary raw archives below research/. "
            "For every RAW_MANIFEST_core.json and RAW_MANIFEST_resources.json entry, verify size and SHA-256 before use. "
            "Git-backed sources and generated reports are supplied by the repository. "
            "The core source_commit is a minimum completed-evidence snapshot; final reports may be in a later commit. "
            "Run build_closeout --verify-only only after both parts and all Git-backed reports are present. "
            "Do not overwrite original evidence with independent refits or new measurements.\n").encode()}
    with zipfile.ZipFile(output,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for name, b in metadata.items():
            z.writestr(name,b)
        for p,e in zip(files,entries):
            if sha_bytes(p.read_bytes()) != e["sha256"]:
                raise ValueError("Input changed during packaging")
            z.write(p,e["path"])
    with zipfile.ZipFile(output) as z:
        expected_names = set(metadata) | {e["path"] for e in entries}
        if set(z.namelist()) != expected_names or len(z.namelist()) != len(expected_names):
            raise AssertionError("Archive contains missing, extra or duplicate members")
        for name, b in metadata.items():
            if z.read(name) != b:
                raise AssertionError("Archive metadata changed")
        for e in entries:
            b=z.read(e["path"])
            if len(b)!=e["bytes"] or sha_bytes(b)!=e["sha256"]:
                raise AssertionError("Archived member does not match source")
    receipt={"schema":"rrsnn-v4-raw-archive-prepared-1","kind":kind,
        "source_commit":source_commit,"local_path":str(output.resolve()),
        "archive_bytes":output.stat().st_size,"archive_sha256":sha_bytes(output.read_bytes()),
        "files":len(entries),"raw_bytes":manifest["raw_bytes"],
        "all_archived_members_re_read_and_verified":True,"metadata_sha256":{n:sha_bytes(b) for n,b in metadata.items()},
        "upload_status":"not_yet_uploaded"}
    destination.parent.mkdir(exist_ok=True)
    with destination.open("x") as stream:
        stream.write(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--kind",choices=("core","resources"),required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--source-commit",required=True)
    p.add_argument("--published-paths",required=True)
    a=p.parse_args()
    package(a.kind,a.output,a.source_commit,a.published_paths)
