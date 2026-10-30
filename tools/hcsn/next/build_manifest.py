"""Build an explicit source/evidence manifest and a complete reproducible export."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "next"
SUFFIXES = {".py", ".md", ".json", ".npz", ".png", ".svg", ".txt"}
DERIVED = {"delivery_manifest.json", "evidence_checks.json"}


def describe(path):
    data = path.read_bytes()
    return dict(path=str(path.relative_to(ROOT)), bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        git_blob_sha=hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest())


def main(archive):
    failure_trace = FOLDER / "ridge/development_failures/aot_lazy_table/failure.log"
    files = [p for p in sorted(FOLDER.rglob("*")) if p.is_file()
             and (p.suffix in SUFFIXES or p == failure_trace) and "__pycache__" not in p.parts
             and not (p.parent == FOLDER and p.name in DERIVED)]
    manifest = dict(schema="hepta.hcsn.followup.delivery.v1",
        repository="TrillionniumFoundation/hepta-private-ci",
        branch="dot/hcsn-free-boundary-research-20261029",
        parent_before_followup="453a1ffbdfc97217c77ace1f8c927e568a06e073",
        created_utc=datetime.now(timezone.utc).isoformat(),
        path_base="tools/hcsn in the Git repository; hcsn_research in the export",
        environment="CPU-only Linux, eight CPU quota, eight GiB RAM; no GPU",
        files=[describe(p) for p in files],
        exclusions=["Downloaded pretrained weights and raw datasets", "Frozen feature caches",
                    "Paper PDF/screenshots", "Runtime logs except the archived initial development failure trace; interpreter caches",
                    "This manifest and derived evidence_checks.json to avoid circular digests"],
        counts=dict(fixed_protocol_neural_training_runs=335, separate_development_training_runs=4,
                    separate_linear_reference_fits=2, saved_neural_and_linear_checkpoints=337,
                    historical_neural_training_runs_preserved=160),
        acceptance="Engineering/evidence integrity is distinct from scientific quality criteria; see blocker_ledger.json",
        history="The separate parent manifest constrains 123 unchanged original files.")
    (FOLDER / "delivery_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    subprocess.run([sys.executable, "-B", str(FOLDER / "verify_delivery.py"), "--require-manifest"], check=True)
    if archive:
        previous = json.loads((ROOT / "delivery_manifest.json").read_text())
        paths = {ROOT / row["path"] for row in previous["files"] + manifest["files"]}
        paths.update((ROOT / "delivery_manifest.json", FOLDER / "delivery_manifest.json",
                      FOLDER / "evidence_checks.json"))
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
            for path in sorted(paths):
                out.write(path, str(Path("hcsn_research") / path.relative_to(ROOT)))
        with zipfile.ZipFile(archive) as check:
            assert check.testzip() is None
            assert len(check.namelist()) == len(paths)
        print(json.dumps(dict(archive=str(archive.resolve()), files=len(paths),
            bytes=archive.stat().st_size, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    main(parser.parse_args().archive)
