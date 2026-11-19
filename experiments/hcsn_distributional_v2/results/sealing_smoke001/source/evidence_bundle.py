"""Preserve selected sealed v2 evidence using the frozen streaming archive code."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from experiments.hcsn_free_boundary_v1.archive import pack, restore, sha256


def run(name, include, part_bytes=1572864):
    package = Path(__file__).resolve().parent
    destination = package / "artifacts"
    selected = {}
    for relative in include:
        target = (package / relative).resolve()
        if not target.is_relative_to(package) or not target.exists():
            raise ValueError("Expected an existing v2 package member: " + relative)
        files = [target] if target.is_file() else target.rglob("*")
        for path in files:
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                if path.is_symlink():
                    raise ValueError("Evidence may not contain symlinks")
                selected[path.relative_to(package)] = path
    if not selected:
        raise ValueError("No evidence selected")
    started = time.process_time()
    with tempfile.TemporaryDirectory(prefix="hcsn-v2-evidence-") as temporary:
        staging = Path(temporary) / "stage"
        staging.mkdir()
        for relative, source in sorted(selected.items()):
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, target)
            except OSError:
                shutil.copyfile(source, target)
        packing = time.process_time()
        manifest = pack(staging, destination, name, part_bytes=part_bytes)
        packing_cpu = time.process_time() - packing
        restoring = time.process_time()
        check = restore(destination / (name + ".json"), Path(temporary) / "restore")
        restoring_cpu = time.process_time() - restoring
        for member in manifest["members"]:
            if sha256(package / member["path"]) != member["sha256"]:
                raise RuntimeError("Source changed while sealing evidence")
    result = dict(schema="hcsn-v2-evidence-seal.v1", name=name, includes=include,
                  members=len(manifest["members"]), compressed_bytes=manifest["compressed_bytes"],
                  uncompressed_file_bytes=manifest["uncompressed_file_bytes"], parts=len(manifest["parts"]),
                  archive_sha256=manifest["archive_sha256"], verified_restore=check,
                  pack_cpu_seconds=packing_cpu, restore_cpu_seconds=restoring_cpu,
                  body_cpu_seconds=time.process_time() - started,
                  whole_process_self_cpu_seconds_through_seal=time.process_time(),
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  pack_restore_source_sha256=sha256(package.parent / "hcsn_free_boundary_v1/archive.py"),
                  scope="This complete archive process only; pack and restore timers are nested, not additive to whole-process CPU")
    with (destination / (name + "_EXECUTION.json")).open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--include", action="append", required=True)
    parser.add_argument("--part-bytes", type=int, default=1572864)
    args = parser.parse_args()
    run(args.name, args.include, args.part_bytes)
