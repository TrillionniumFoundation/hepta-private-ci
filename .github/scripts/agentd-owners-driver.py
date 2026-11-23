from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


TMP = Path(os.environ["RUNNER_TEMP"])
OUT = TMP / "owners-lint-evidence"
CASES = json.loads((TMP / "owners-cases.json").read_bytes())
assert len(CASES) == len(set(CASES)) == 33


def native(arm):
    binary = TMP / ("agentd-owners-" + arm)
    names = {v.removesuffix(": test") for v in subprocess.check_output([binary, "--list"], text=True).splitlines() if v.endswith(": test")}
    assert set(CASES) <= names
    assert os.geteuid() != 0
    result = []
    with (OUT / f"native-{arm}.log").open("wb") as raw:
        for name in CASES:
            start = time.monotonic()
            proc = subprocess.run([binary, "--exact", name, "--test-threads=1"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            raw.write(proc.stdout)
            status = (proc.returncode == 0 and f"test {name} ... ok".encode() in proc.stdout and b"1 passed; 0 failed; 0 ignored;" in proc.stdout)
            result.append({"name": name, "code": proc.returncode, "one_pass": status, "seconds": time.monotonic() - start, "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest()})
    (OUT / f"native-{arm}.json").write_text(json.dumps(result, indent=2) + "\n")
    assert all(r["one_pass"] for r in result)


def diagnoses(arm):
    report = (OUT / f"strict-{arm}.log").read_text()
    rows = []
    for segment in re.split(r"(?m)^error: ", report)[1:]:
        message = segment.splitlines()[0]
        if message.startswith("could not compile"):
            continue
        location = re.search(r"(?m)^\s*--> ([^:\n]+):(\d+):(\d+)\s*$", segment)
        assert location, (arm, message)
        rows.append((location[1], message))
    assert rows and "error: could not compile" in report
    return Counter(rows)


if sys.argv[1] == "native":
    native(sys.argv[2])
else:
    before = diagnoses("base")
    after = diagnoses("candidate")
    codes = [int((OUT / f"strict-{arm}.exit").read_text()) for arm in ("base", "candidate")]
    added = sorted((after - before).elements())
    removed = sorted((before - after).elements())
    summary = {"before": before.total(), "after": after.total(), "added": added, "removed": removed, "codes": codes}
    (OUT / "strict-pair.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(summary)
    assert codes == [101, 101] and before.total() == 115 and after.total() == 114
    assert not added and removed == [("hepta-agentd/src/circuit_original_evaluation_provider_records.rs", "this function has too many arguments (8/7)")]
