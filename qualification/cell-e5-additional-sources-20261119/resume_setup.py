"""Resume setup from verified original snapshots; do not fetch sources again."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

from acquire_sources import digest, setup, write
from replay_sources import checked_snapshot


def main(root):
    began = time.perf_counter()
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    plan = json.loads((root / "ACQUISITION_PLAN.json").read_bytes())
    recovery = json.loads((root / "SETUP_RECOVERY.json").read_bytes())
    assert digest((root / "ACQUISITION_PLAN.json").read_bytes()) == recovery["plan_sha256"]
    write(root / "ACQUISITION_STARTED.json", {"started_at_ns": time.time_ns(), "runner_sha256": digest(Path(__file__).read_bytes()), "recovery": recovery, "new_model_calls": 0, "new_training_updates": 0})
    outcomes, stages = [], []
    try:
        for blob in json.loads((root / "BLOBS.json").read_bytes()):
            data = (root / "git-blobs" / blob["git_blob_sha1"]).read_bytes()
            assert len(data) == blob["bytes"] and digest(data) == blob["sha256"]
            assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == blob["git_blob_sha1"]
        assert json.loads((root / "RAW_DOWNLOAD_FAILURES.json").read_bytes()) == []
        for entry in plan["projects"]:
            for variant in ("before", "after"):
                _, manifest = checked_snapshot(root, entry["index"], variant)
                assert manifest["revision"] == entry[variant + "_commit"]
                outcomes.append({"identity": [entry["index"], variant], "status": "ACQUIRED", "files": len(manifest["files"]), "manifest_sha256": digest((root / "snapshots" / f"{entry['index']}-{variant}.json").read_bytes())})
        write(root / "SNAPSHOT_ACQUISITION.json", outcomes)
        stages = setup(root)
        status, error = "ACQUIRED", None
    except Exception as failure:
        status, error = "FAILED", repr(failure)
    final_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"status": status, "error": error, "snapshots": outcomes, "setup_stages": stages, "new_model_calls": 0, "new_training_updates": 0, "new_native_children": 0, "new_authenticated_users": 0, "source_growth_qualified": False, "wall_seconds": time.perf_counter() - began, "completed_child_cpu_seconds": final_cpu.ru_utime + final_cpu.ru_stime - cpu.ru_utime - cpu.ru_stime, "full_system_cost_known": False}
    write(root / "ACQUISITION.json", result)
    print(json.dumps(result), flush=True)
    return 0 if status == "ACQUIRED" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    raise SystemExit(main(parser.parse_args().root.resolve(strict=True)))
