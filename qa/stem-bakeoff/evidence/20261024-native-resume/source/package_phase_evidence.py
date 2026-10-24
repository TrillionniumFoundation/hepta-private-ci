"""Package this phase's recorded data using the existing lossless archive format."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

QA = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(QA))
from package_cell_evidence import collect_files, sha_file
from package_cell_local_evidence import build, code_pin


def roots_for(root, bundle):
    roots = {"bundle": str(bundle)}
    for name in ("native-export", "native-runtime", "native-parity-1", "resume-attempt-1",
                 "data-audit", "resume-audit", "native-audit", "local-actions"):
        roots[name] = str(root/name)
    for name in ("source-freeze.json", "native-freeze.json"):
        roots[name] = str(root/name)
    for path in sorted((root/"publication").glob("*.json")):
        if path.name.startswith(("commit-", "published-")):
            roots["publication/"+path.name] = str(path)
    pilot = root/"pandas-pilot"
    for path in sorted(pilot.iterdir()):
        if path.is_file() and path.suffix in (".json", ".txt"):
            roots["pandas-pilot/"+path.name] = str(path)
    for name in ("commands", "prepared-actions", "execution-attempt-1"):
        roots["pandas-pilot/"+name] = str(pilot/name)
    # Retain Git objects and portable bare-repository metadata, not worktree
    # pointers, installed environments, compiler caches or Hepta source copies.
    source = pilot/"sources/pandas.git"
    for name in ("objects", "refs", "HEAD", "config", "shallow", "packed-refs"):
        if (source/name).exists():
            roots["pandas-source.git/"+name] = str(source/name)
    for role in ("base", "candidate"):
        complete = json.loads((pilot/f"build-complete-{role}.json").read_bytes())
        for row in complete["extension_files"]:
            path = pilot/"checkouts"/role/row["path"]
            if sha_file(path) != row["sha256"]:
                raise ValueError("qualified native extension changed")
            roots[f"pandas-native/{role}/"+row["path"]] = str(path)
    metadata = Path("/workspace/scratch/f1f83ab8f2f0/upstream-bugsinpy/projects/pandas/bugs/5")
    for path in sorted(metadata.iterdir()):
        if path.is_file():
            roots["pandas-original-metadata/"+path.name] = str(path)
    closing = root/"closing/phase-cost-ledger.json"
    if closing.exists(): roots["closing/phase-cost-ledger.json"] = str(closing)
    return roots


def package(root, bundle, output):
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    root, bundle, output = Path(root), Path(bundle), Path(output)
    repo = QA.parents[1]
    measured = json.loads((root/"source-freeze.json").read_bytes())["source_commit"]
    reporting = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    snapshots = {}
    for name in ("package_phase_evidence.py", "pandas_pilot_build_measured_snapshot.py",
                 "pandas_source_pilot_measured_snapshot.py"):
        path = Path(__file__).with_name(name)
        relative = path.relative_to(repo).as_posix()
        saved = subprocess.check_output(["git", "-C", str(repo), "show", reporting+":"+relative])
        if hashlib.sha256(saved).hexdigest() != sha_file(path):
            raise ValueError("reporting source not saved in exact Git version")
        snapshots[relative] = sha_file(path)
    roots = roots_for(root, bundle)
    provenance = {"git": code_pin(repo, measured), "roots": roots,
        "reporting_source_commit": reporting, "historical_and_packaging_source_sha256": snapshots,
        "native_binary_scope": "one measured Linux x86_64 replay executable, restored non-executable until explicitly enabled",
        "pandas_binary_scope": "qualified source-built extensions; historical Python/dependency environment is reacquired from hash lock",
        "quality_scope": "systems regression plus one TRAIN source pilot; no new holdout or quality promotion"}
    result = build(collect_files(repo, roots), output, provenance)
    receipt = {"archive": str(output), "archive_sha256": result["archive_sha256"],
        "file_count": result["file_count"], "object_count": result["object_count"],
        "wall_ns": time.perf_counter_ns()-start, "parent_cpu_ns": time.process_time_ns()-cpu,
        "child_git_cpu_in_outer_receipt": True, "source_commit": measured, "reporting_commit": reporting}
    (root/"closing/archive-build.json").write_text(json.dumps(receipt, indent=2)+"\n")
    (root/"closing/archive-roots.json").write_text(json.dumps(roots, indent=2)+"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "bundle", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.root, args.bundle, args.output)))
