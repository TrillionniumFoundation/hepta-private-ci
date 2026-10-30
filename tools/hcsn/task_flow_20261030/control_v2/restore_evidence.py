"""Restore exact evidence members with archive/member identity verification."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import zipfile

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore(destination):
    start = time.perf_counter()
    destination = Path(destination).resolve()
    record = json.loads((HERE / "evidence_archives.json").read_text())
    for relative, expected in record["bound_files_sha256"].items():
        assert digest(HERE / relative) == expected, relative
    groups = {"raw_development.zip": json.loads((HERE / "development_manifest.json").read_text())["files"],
        "raw_heldout.zip": json.loads((HERE / "heldout_manifest.json").read_text())["files"],
        "raw_training.zip": json.loads((HERE / "training_manifest.json").read_text())["files"],
        "raw_traces.zip": {r["trace"]: r["trace_sha256"] for r in json.loads((HERE / "confirmation.json").read_text())["rows"]}}
    verified, restored = 0, 0
    for item in record["archives"]:
        archive_path = HERE / item["path"]
        assert digest(archive_path) == item["sha256"]
        files = groups[item["path"]]
        with zipfile.ZipFile(archive_path) as archive:
            assert len(archive.namelist()) == len(set(archive.namelist())) == len(files)
            assert set(archive.namelist()) == set(files)
            assert sum(info.file_size for info in archive.infolist()) == item["uncompressed_bytes"]
            for relative, expected in files.items():
                target = (destination / relative).resolve()
                assert target.is_relative_to(destination), relative
                if target.exists():
                    assert target.is_file() and digest(target) == expected, relative
                else:
                    payload = archive.read(relative)
                    assert hashlib.sha256(payload).hexdigest() == expected, relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(target.suffix+".partial")
                    temporary.write_bytes(payload)
                    temporary.replace(target)
                    restored += 1
                verified += 1
    return dict(passed=True, verified_files=verified, restored_files=restored,
        destination=str(destination), wall_seconds=time.perf_counter()-start,
        archive_manifest_sha256=digest(HERE / "evidence_archives.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", default=str(HERE))
    print(json.dumps(restore(parser.parse_args().destination), indent=2))
