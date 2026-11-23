"""Read the native and strict evidence emitted from immutable source worktrees."""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

OUT = Path(os.environ["RUNNER_TEMP"]) / "private16-evidence"
ARMS = ("base", "candidate")
CASES = {
    "deferred_training_uses_actual_material_cut_and_original_source_without_precreation",
    "deferred_training_lost_ack_recovers_same_job_and_original_signature",
    "deferred_training_missing_dataset_or_partial_owners_never_bootstrap_replacements",
    "deferred_training_wrong_context_does_not_consume_original_custody",
    "deferred_training_failed_source_or_pending_claim_never_rearms",
    "deferred_training_attenuation_and_prebound_transport_preserve_original_custody",
    "deferred_training_connection_rejects_experience_and_valid_other_freeze_context",
    "deferred_training_connection_preserves_expiry_and_readonly_cold_original_signature",
}

def record(name, data):
    value = json.dumps(data, indent=2, sort_keys=True)
    (OUT / (name + ".json")).write_text(value + "\n")
    print(value, flush=True)

def native():
    tools = {}
    lists = {}
    for arm in ARMS:
        binary = Path(os.environ["RUNNER_TEMP"]) / ("agentd-private-" + arm)
        work = Path(os.environ["RUNNER_TEMP"]) / ("source-private-" + arm)
        with binary.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        roster = subprocess.check_output([binary, "--list"], text=True, cwd=work)
        (OUT / ("list-" + arm + ".txt")).write_text(roster)
        full = sorted(n for n in re.findall(r"^(.+): test$", roster, re.M) if "deferred_training_" in n)
        lists[arm] = full
        assert len(full) == len(CASES) and {n.split("::")[-1] for n in full} == CASES, full
        tools[arm] = (digest, binary, work)
    assert lists["base"] == lists["candidate"], lists
    assert tools["base"][0] != tools["candidate"][0], "the two ELFs are identical"
    rows = {}
    for arm in ARMS:
        digest, binary, work = tools[arm]
        log = OUT / ("tests-" + arm + ".log")
        start = time.monotonic()
        with log.open("w") as stream:
            p = subprocess.run([binary, "deferred_training_", "--test-threads=1"], cwd=work,
                               stdout=stream, stderr=subprocess.STDOUT)
        report = log.read_text()
        passed = sorted(re.findall(r"^test (.+?) \.\.\. ok$", report, re.M))
        rows[arm] = {"source": os.environ[arm.upper()], "elf_sha256": digest,
                     "elapsed": time.monotonic() - start, "exit": p.returncode,
                     "test_ids": passed, "complete": passed == lists[arm]}
        print(report, flush=True)
    record("native", rows)
    assert all(row["exit"] == 0 and row["complete"] for row in rows.values()), rows

def strict():
    counters = {}
    for arm in ARMS:
        value = (OUT / ("strict-" + arm + ".log")).read_text()
        errors = collections.Counter()
        for block in re.split(r"(?m)^error(?:\[E\d+\])?: ", value)[1:]:
            location = re.search(r"(?m)^\s*-->\s+(hepta-agentd/[^:\s]+):\d+:\d+", block)
            if location:
                errors[(location[1], block.splitlines()[0])] += 1
        counters[arm] = errors
        assert re.search(r"could not compile .codex-hepta-agentd.* due to \d+ previous errors", value), value[-1800:]
    a, b = (counters[k] for k in ARMS)
    fixed = sorted((a-b).elements())
    added = sorted((b-a).elements())
    rows = {"before": a.total(), "after": b.total(), "resolved": fixed, "new": added}
    record("strict", rows)
    assert (a.total(), b.total()) == (138, 128) and len(fixed) == 10 and not added, rows

if __name__ == "__main__":
    {"native": native, "strict": strict}[sys.argv[1]]()
