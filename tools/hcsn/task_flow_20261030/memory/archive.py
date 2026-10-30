"""Package retained run evidence, then prove restoration into a new directory."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    start, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu_before = children.ru_utime + children.ru_stime
    result = json.loads((HERE / "results.json").read_text())
    if not result["complete"] or len(result["runs"]) != 30:
        raise RuntimeError("Only package the completed fixed matrix")
    archive = HERE / "raw_evidence.zip"
    manifest_path = HERE / "raw_evidence_manifest.json"
    if archive.exists() or manifest_path.exists():
        raise RuntimeError("Refuse to replace published archive evidence")
    paths = sorted(p for p in (HERE / "runs").rglob("*") if p.is_file())
    if any(p.is_symlink() or p.name.endswith(".pending") for p in paths):
        raise RuntimeError("Unexpected symlink or incomplete evidence")
    files = [dict(path=str(p.relative_to(HERE)), bytes=p.stat().st_size, sha256=sha(p)) for p in paths]
    counts = dict(candidate_checkpoints=sum(p.name.startswith("candidate_") for p in paths),
                  selected_checkpoints=sum(p.name == "selected.npz" for p in paths),
                  prediction_archives=sum(p.name.endswith("_predictions.npz") for p in paths),
                  update_logs=sum(p.name == "updates.csv" for p in paths),
                  run_receipts=sum(p.name == "run.json" for p in paths))
    if counts != dict(candidate_checkpoints=360, selected_checkpoints=30,
                      prediction_archives=135, update_logs=30, run_receipts=30):
        raise RuntimeError("Unexpected retained evidence counts")
    temporary = archive.with_name(archive.name + ".pending")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for record in files:
            info = zipfile.ZipInfo(record["path"], date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, (HERE / record["path"]).read_bytes())
    temporary.replace(archive)
    if archive.stat().st_size >= 20_000_000:
        raise RuntimeError("Retain archive but split before publication: size exceeds20MB")
    manifest = dict(schema="hcsn.memory.raw_evidence.v1", created_utc=datetime.now(timezone.utc).isoformat(),
                    archive=archive.name, archive_sha256=sha(archive), archive_bytes=archive.stat().st_size,
                    results_sha256=sha(HERE / "results.json"), source_freeze_sha256=sha(HERE / "freeze.json"),
                    total_uncompressed_bytes=sum(r["bytes"] for r in files), file_count=len(files),
                    counts=counts, files=files,
                    scope="Lossless runs/ checkpoints, predictions, labels, update logs and run receipts. Original files are retained. Data generators and seeds remain separate frozen source.")
    write_json(manifest_path, manifest)
    with tempfile.TemporaryDirectory(prefix="hcsn_memory_restore_", dir="/tmp") as destination:
        target = Path(destination)
        empty_before = not any(target.iterdir())
        process = subprocess.run([sys.executable, str(HERE / "restore_evidence.py"), "--dest", destination],
                                 check=True, text=True, capture_output=True)
        replay = json.loads(process.stdout)
        if not empty_before or replay["files_restored"] != len(files):
            raise RuntimeError("Restore did not populate a genuinely new directory")
        if any(sha(target / r["path"]) != r["sha256"] for r in files):
            raise RuntimeError("Independent destination file hash mismatch")
    original_unchanged = all(sha(HERE / r["path"]) == r["sha256"] for r in files)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = children.ru_utime + children.ru_stime - child_cpu_before
    output = dict(passed=replay["passed"] and original_unchanged, original_files_retained_unchanged=original_unchanged,
                  new_empty_directory_restore=True, restore=replay, counts=counts,
                  archive_source_sha256=sha(__file__), restore_source_sha256=sha(HERE / "restore_evidence.py"),
                  own_cpu_seconds=time.process_time() - cpu, subprocess_cpu_seconds=child_cpu,
                  measured_cpu_seconds=time.process_time() - cpu + child_cpu,
                  wall_seconds=time.perf_counter() - start)
    write_json(HERE / "archive_validation.json", output)
    if not output["passed"]:
        raise RuntimeError("Preserve failed archive validation")
    # Only the fully archived, verified, retained duplicate directory is ignored.
    (HERE / ".gitignore").write_text("# Restored lossless raw evidence; see raw_evidence_manifest.json.\n/runs/\n")
    print(json.dumps(dict(manifest={k: v for k, v in manifest.items() if k != "files"}, validation=output), indent=2))


if __name__ == "__main__":
    main()
