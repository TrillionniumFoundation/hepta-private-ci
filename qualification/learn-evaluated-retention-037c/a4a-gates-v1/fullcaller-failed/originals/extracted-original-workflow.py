import json
import os
from pathlib import Path
import subprocess
import sys

repo = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
records = Path(os.environ["RUNNER_TEMP"]) / "daemon-learning-caller-proof"
records.mkdir(parents=True, exist_ok=True)
os.chdir(repo)
sys.path.insert(0, str(repo / "scripts"))
from hepta_ci_exec import execute_logged

def identity():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo).decode().strip()
    return {"head": git("rev-parse", "HEAD"),
            "tree": git("rev-parse", "HEAD^{tree}"),
            "status": git("status", "--porcelain=v1", "--untracked-files=all")}

def save(name, value):
    (records / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

before = identity()
save("source-before.json", before)
if before["head"] != os.environ["SOURCE_SHA"] or before["status"]:
    raise RuntimeError("caller proof requires the exact clean source")
try:
    for phase, timeout in (("self-test", 300), ("verify", 4800)):
        command = ["python3", "scripts/verify_hepta_callers.py", phase]
        result = execute_logged(command, records / (phase + ".log"),
                                timeout_seconds=timeout)
        save(phase + ".json", {"source_sha": before["head"],
                              "command": command, **result})
        if result["returncode"] or result["timed_out"] or result["output_limit_exceeded"]:
            raise RuntimeError(phase + " failed; original log and exit status retained")
finally:
    after = identity()
    save("source-after.json", after)
    if after != before:
        raise RuntimeError("caller proof changed the fixed source")
