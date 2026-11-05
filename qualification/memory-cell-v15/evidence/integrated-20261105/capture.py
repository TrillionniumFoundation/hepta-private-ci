"""Run scoped current checks without replacing preserved historical receipts."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inventory():
    paths = list(ROOT.glob("*.py"))
    paths += list((ROOT / "native-transfer").glob("*.rs"))
    paths += [ROOT / "device_qualification" / name
              for name in ("history_tests.py", "verify_receipts.py")]
    paths.append(Path(__file__).resolve())
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "run.json").exists():
        raise SystemExit("use a new output directory; retained execution must not be overwritten")
    current = [ROOT / "evidence" / name for name in ("checks.json", "checks.log")]
    historical = {path: path.read_bytes() if path.exists() else None for path in current}
    before = inventory()
    started = datetime.now(timezone.utc).isoformat()
    steps = []
    commands = [
        ("normal", [sys.executable, str(ROOT / "verify.py")]),
        ("history", [sys.executable, str(ROOT / "device_qualification/history_tests.py")]),
        ("optimized", [sys.executable, "-O", str(ROOT / "verify.py")]),
        ("historical-receipts", [sys.executable, str(ROOT / "device_qualification/verify_receipts.py"),
                                  "--output", str(output / "historical-receipts.json")]),
    ]
    try:
        for label, command in commands:
            began = time.perf_counter()
            with (output / (label + ".log")).open("wb") as log:
                process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            row = {"label": label, "command": command, "exit_code": process.returncode,
                   "wall_seconds": time.perf_counter() - began,
                   "log_sha256": sha((output / (label + ".log")).read_bytes())}
            if label in ("normal", "optimized") and current[0].exists():
                checked = json.loads(current[0].read_text())
                row.update(tests_run=checked["tests_run"], passed=checked["passed"])
                for path in current:
                    shutil.copyfile(path, output / (label + "-" + path.name))
            steps.append(row)
            print(json.dumps(row), flush=True)
            if process.returncode or row.get("passed") is False:
                break
    finally:
        after = inventory()
        for path, raw in historical.items():
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(raw)
        restored = all((path.read_bytes() if path.exists() else None) == raw
                       for path, raw in historical.items())
        report = {
            "schema": "hepta.memory.integrated-checks.v1", "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(), "python": sys.version,
            "platform": platform.platform(), "pythonpath": os.getenv("PYTHONPATH"),
            "steps": steps, "source_sha256": before, "source_unchanged": before == after,
            "historical_checks_restored": restored,
            "passed": (len(steps) == len(commands) and before == after and restored
                       and all(step["exit_code"] == 0 and step.get("passed", True) for step in steps)),
            "scope": "Current reference checks and offline verification of historical signed host receipts; no new model runs, independent samples, remote host operations or full lifecycle costs.",
            "new_model_runs": 0, "new_independent_language_samples": 0,
            "production_activation_allowed": False,
        }
        (output / "run.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: report[key] for key in
                         ("passed", "source_unchanged", "historical_checks_restored")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
