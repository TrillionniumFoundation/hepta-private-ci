"""Preserve Unix artifact names and all partial model/log evidence without following links."""

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import identity, save


def pack(source, output):
    output.mkdir(parents=True, exist_ok=False)
    if not source.exists():
        source.mkdir(parents=True)
    receipt = source / "receipt.json"
    if not receipt.is_file():
        save(receipt, {"schema": "hepta.memory.v10.ci-receipt.v1", "passed": False,
             "error": "CI stopped before the driver created its receipt", "tests_executed": False,
             "source_commit": os.environ.get("GITHUB_SHA"), "github_run_id": os.environ.get("GITHUB_RUN_ID")})
    archive = output / "memory-v10-evidence.tar.xz"
    files, special, started, cpu = {}, {}, time.monotonic_ns(), time.process_time_ns()
    with tarfile.open(archive, "w:xz", format=tarfile.PAX_FORMAT) as tar:
        for directory, dirs, names in os.walk(source, followlinks=False):
            for name in sorted(dirs + names):
                path = Path(directory) / name
                relative = "memory-v10-ci-output/" + path.relative_to(source).as_posix()
                mode = path.lstat().st_mode
                if stat.S_ISDIR(mode):
                    continue
                if not stat.S_ISREG(mode):
                    special[relative] = {"mode": mode, "contents_followed": False,
                                         "symlink_target": os.readlink(path) if stat.S_ISLNK(mode) else None}
                    continue
                before = identity(path)
                tar.add(path, arcname=relative, recursive=False)
                if before != identity(path):
                    raise ValueError("evidence changed while packaging: " + relative)
                files[relative] = before
    result = {"schema": "hepta.memory.v10.ci-transport.v1", "files": files, "nonregular_entries": special,
              "archive": {"path": archive.name, **identity(archive)},
              "original_file_names_preserved": True, "symlinks_followed": False,
              "pack_wall_ns": time.monotonic_ns() - started, "pack_cpu_ns": time.process_time_ns() - cpu,
              "upload_cost": "retained separately by Actions; not included in wrapper measurements"}
    save(output / "INDEX.json", result)
    (output / "receipt.json").write_bytes(receipt.read_bytes())
    print(json.dumps({"archive": result["archive"], "files": len(files), "special_entries": len(special)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pack(args.source.absolute(), args.output.absolute())
