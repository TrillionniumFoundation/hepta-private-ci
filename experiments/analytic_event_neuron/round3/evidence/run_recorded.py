"""Record an operational invocation of the unchanged frozen main CLI."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from .. import freeze


def execute(run_dir, log, receipt):
    root, log, receipt = Path(run_dir), Path(log), Path(receipt)
    frozen = freeze.verify(root)
    if log.exists() or receipt.exists():
        raise FileExistsError("Operational invocation logs are never overwritten")
    command = [sys.executable, "-u", "-m", "experiments.analytic_event_neuron.round3.run",
               "--run-dir", str(root)]
    document = {"schema": "hepta.analytic-event.round3.recorded-invocation.v1", "status": "starting",
        "command": command, "source_commit": frozen["source_commit"],
        "freeze_sha256": hashlib.sha256((root / "FREEZE.json").read_bytes()).hexdigest(),
        "created_utc": datetime.now(timezone.utc).isoformat(), "scientific_source_modified": False,
        "measurement_scope": "One CLI process tree, including resumption verification and all remaining scopes; overlaps per-scope successful execution timing",
        "child_cpu_scope": "Linux RUSAGE_CHILDREN delta after the CLI exits and reaps its native child; not a separate per-native CPU measurement",
        "initial_failed_attempt_cost_included": False}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x+b") as store:
        # Reserve small receipt storage before launch; no absolute guarantee is
        # made about filesystem availability during a later full-disk failure.
        store.write(b" " * 16384)
        store.flush()
        os.fsync(store.fileno())

        def persist():
            body = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
            if len(body) > 16384:
                raise ValueError("Operational receipt exceeded its reserved allocation")
            store.seek(0)
            store.write(body.ljust(16384, b" "))
            store.flush()
            os.fsync(store.fileno())

        persist()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        began = time.perf_counter_ns()
        with log.open("xb", buffering=0) as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
            document.update(status="running", process_id=process.pid)
            persist()
            code = process.wait()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        document.update(status="exited", returncode=code, wall_ns=time.perf_counter_ns() - began,
            child_user_cpu_seconds=after.ru_utime - before.ru_utime,
            child_system_cpu_seconds=after.ru_stime - before.ru_stime,
            reported_child_maxrss_kib=after.ru_maxrss,
            child_block_inputs=after.ru_inblock - before.ru_inblock,
            child_block_outputs=after.ru_oublock - before.ru_oublock,
            completed_utc=datetime.now(timezone.utc).isoformat(),
            output_log_bytes=log.stat().st_size,
            output_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
        persist()
    freeze.verify(root)
    print(json.dumps({"returncode": code, "wall_ns": document["wall_ns"], "receipt": str(receipt)}))
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-dir", "log", "receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    arguments = parser.parse_args()
    raise SystemExit(execute(arguments.run_dir, arguments.log, arguments.receipt))
