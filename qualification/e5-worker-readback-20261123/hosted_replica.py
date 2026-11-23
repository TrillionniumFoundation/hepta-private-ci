"""Run the registered historical harness once in its dedicated network namespace."""

import json
from pathlib import Path
import socket
import sys

from cell_experiments import e5_worker_control as control


def main(plain, circuit, out):
    interfaces = [name for _, name in socket.if_nameindex()]
    if interfaces != ["lo"]:
        raise RuntimeError(f"Unexpected active network interfaces: {interfaces}")
    (out / "network-before.txt").write_text(Path("/proc/net/dev").read_text())
    try:
        verified = control.run(plain, circuit, out / "run", train=True, release_trainer=True)
    finally:
        (out / "network-after.txt").write_text(Path("/proc/net/dev").read_text())
    result = json.loads((out / "run/SUMMARY.json").read_bytes())
    print("E5_BATCHES", json.dumps([
        dict(workers=row["workers"], seconds=row["seconds"], overlap=row["job_concurrency_nanoseconds"],
             verdicts=[job["returncode"] for job in row["jobs"]], accepted=row["completed_unique_pairs"])
        for row in result["runs"]
    ]), flush=True)
    print("E5_RATES", result["median_pairs_per_hour"], flush=True)
    if not verified:
        raise RuntimeError("Registered identities, equivalent work or overlaps did not match.")


if __name__ == "__main__":
    main(*(Path(s) for s in sys.argv[1:]))
