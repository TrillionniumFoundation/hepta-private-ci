"""Execute real kernel admission, descendant and timeout qualification on a delegated runner.

No successful cgroup campaign is simulated. Run with an explicitly delegated,
already-enabled memory/CPU parent; the program does not change its controllers.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from experiments.hcsn_v10_followup_20261101.economics.cgroup_meter import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delegated-parent", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    directory = Path(__file__).resolve().parent
    fixture = directory.parents[1] / "hcsn_v9_followup_20261101/economics/short_tree_probe.py"
    sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in (*directory.glob("*.py"), fixture)}
    (args.out / "SOURCE_FREEZE.json").write_text(json.dumps(sources, indent=2) + "\n")
    results = []
    for mode in ("waited", "adopted", "nonzero", "timeout"):
        if mode in ("waited", "adopted"):
            nodes = args.out / (mode + "_nodes")
            command = [sys.executable, "-m", "experiments.hcsn_v9_followup_20261101.economics.short_tree_probe",
                       "--out", str(nodes), "--mode", mode]
            timeout = 10
        elif mode == "nonzero":
            command, timeout = [sys.executable, "-c", "raise SystemExit(3)"], 10
        else:
            script = ("import subprocess,sys,time; "
                      "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                      "print('spawned-child',p.pid,flush=True); time.sleep(30)")
            command, timeout = [sys.executable, "-c", script], 0.5
        receipt = run(command, args.out / mode, args.delegated_parent, timeout)
        accepted = receipt["measurement_valid"] and receipt["cleanup_verified"] and receipt["all_group_tasks_exited"]
        if mode in ("waited", "adopted"):
            accepted = accepted and receipt["task_success"] and len(list(nodes.glob("*.json"))) == 4
        elif mode == "nonzero":
            accepted = accepted and receipt.get("root_exit_code") == 3 and not receipt["task_success"]
        else:
            accepted = (accepted and receipt.get("timed_out") is True and receipt.get("root_exit_code") == -9
                        and "spawned-child" in (args.out / mode / "stdout.log").read_text())
        results.append({"mode": mode, "accepted": bool(accepted), "status": receipt["status"],
                        "measurement_valid": receipt["measurement_valid"], "cleanup_verified": receipt["cleanup_verified"]})
        if receipt["status"] == "UNAVAILABLE":
            break
    unchanged = all(Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                    for path, digest in sources.items())
    passed = len(results) == 4 and all(r["accepted"] for r in results) and unchanged
    summary = {"schema": "hcsn-v10-delegated-cgroup-qualification.v1", "status": "PASS" if passed else "HOLD",
               "results": results, "source_unchanged": unchanged,
               "complete_family_rss_peak_qualified": False, "device_energy_qualified": False,
               "metric": "Hierarchical cgroup charge highwater and CPU; no unique-page/RSS/energy equivalence."}
    (args.out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
