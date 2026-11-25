"""Supervise one immutable, single-threaded shard; no test capability is invoked."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

EXPECTED_PROTOCOL = "aad9b709d3ee6a32597487f5ae1eb2c1fc490f74d05320c4d32349fe7f09e7b8"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    root = Path(args.root).resolve()
    receipt_path = root / f"WORKER_{args.index}_EXECUTION.json"
    if receipt_path.exists():
        raise FileExistsError("Worker execution is already terminal")
    protocol = root / "FORMAL_PROTOCOL_v2.json"
    if sha(protocol) != EXPECTED_PROTOCOL:
        raise ValueError("Unrecognized frozen protocol")
    bound = json.loads(protocol.read_text())
    for name, expected in bound["source_hashes"].items():
        if sha(root / name) != expected:
            raise ValueError("Worker source changed")
    env = dict(os.environ, PFT_HCSN_CAPSULE=str(root / "capsule"),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    command = [sys.executable, str(root / "runner.py"), "--protocol", str(protocol),
               "--out", str(root / "formal_v2_training"), "--shard-index", str(args.index), "--shard-count", "4"]
    start_utc = datetime.now(timezone.utc).isoformat()
    start, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    error, exit_code = None, None
    stdout, stderr = root / f"worker_{args.index}.stdout.log", root / f"worker_{args.index}.stderr.log"
    try:
        with stdout.open("x") as out, stderr.open("x") as err:
            child = subprocess.run(command, cwd=root, env=env, stdout=out, stderr=err, timeout=5400)
            exit_code = child.returncode
    except Exception as exc:
        error = repr(exc)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"status": "COMPLETED" if exit_code == 0 and error is None else "FAILED",
               "exit_code": exit_code, "error": error, "shard_index": args.index, "shard_count": 4,
               "protocol_sha256": EXPECTED_PROTOCOL, "source_git_anchor": args.git_anchor,
               "launcher_sha256": sha(__file__), "command": command, "host": platform.node(),
               "started_utc": start_utc, "completed_utc": datetime.now(timezone.utc).isoformat(),
               "wall_s": time.perf_counter() - start,
               "child_cpu_s": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
               "child_peak_rss_kib": after.ru_maxrss,
               "requested_cpu_quota_percent": 100, "requested_memory_limit_bytes": 2147483648,
               "maximum_campaign_concurrent_workers": 4, "shared_host_contention_possible": True,
               "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr), "test_created": False}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--index", type=int, choices=range(4), required=True)
    p.add_argument("--git-anchor", required=True)
    raise SystemExit(main(p.parse_args()))
