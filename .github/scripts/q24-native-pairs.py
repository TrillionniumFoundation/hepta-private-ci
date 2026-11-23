"""Run unmodified libtest cases on source-pinned binaries built on one machine."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time

ROOT = Path(os.environ["GITHUB_WORKSPACE"])
OUT = Path(os.environ["RUNNER_TEMP"]) / "q24-evidence"
BINS = {arm: Path(os.environ["RUNNER_TEMP"]) / ("q24-" + arm) for arm in ("base", "candidate")}
DIAGNOSTIC = "original_next_use_evidence_timing_diagnostic"
CASES = {
    "q24_remote_selection_reads_original_publication_before_c_and_recovers_signature",
    "q24_remote_c_requires_actual_completion_and_original_selector_signature",
    "q24_remote_current_refuses_withdrawal_after_a_successful_read",
    "q24_remote_context_pins_full_signatures_and_refuses_uploaded_observations",
    "q24_remote_read_consumes_late_and_wrong_nonce_responses_without_effects",
    "q24_remote_read_refuses_expired_original_window_and_same_process_bootstrap",
    "q24_next_use_command_attests_actual_different_c_and_shares_dispatch",
    "q24_next_use_command_lost_ack_recovers_exact_original_signature_readonly",
    "q24_next_use_command_early_dispatch_never_runs_c_or_resets_admission",
    "q24_next_use_command_pins_both_original_signatures_before_dispatch",
    "q24_next_use_command_readback_refuses_actual_publication_withdrawal",
    "q24_next_use_command_preserves_original_expiry_and_external_custody",
    "q24_next_use_command_healthy_evidence_readback_then_publication_withdrawal",
}
rosters = {}
for arm, binary in BINS.items():
    raw = subprocess.check_output([binary, "--list"], cwd=ROOT, text=True)
    (OUT / ("list-" + arm + ".txt")).write_text(raw)
    roster = {}
    for name in re.findall(r"^(.*): test$", raw, re.MULTILINE):
        short = name.split("::")[-1]
        if short not in CASES | {DIAGNOSTIC}:
            continue
        assert short not in roster, (arm, short)
        roster[short] = name
    assert roster.keys() == CASES | {DIAGNOSTIC}, (arm, roster.keys())
    rosters[arm] = roster
assert rosters["base"] == rosters["candidate"]

rows = []
def run(arm, label, owner=False):
    roster = rosters[arm]
    if owner:
        args = ["--test-threads=1"] + [roster[case] for case in sorted(CASES)]
    else:
        args = ["--exact", roster[DIAGNOSTIC], "--nocapture", "--test-threads=1"]
    file = OUT / f"{label}-{arm}.log"
    start = time.monotonic_ns()
    with file.open("wb") as log:
        result = subprocess.run([BINS[arm], *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    elapsed = (time.monotonic_ns() - start) / 1e6
    text = file.read_text(errors="replace")
    timing = re.findall(r"LEARN_FDE_C_TIMING evidence_readback_elapsed_us=(\d+) result=([^\n]*)", text)
    summary = re.findall(r"^test result: .*", text, re.MULTILINE)
    row = {"arm": arm, "label": label, "returncode": result.returncode,
           "wall_ms": round(elapsed, 3), "summary": summary,
           "log_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
           "evidence_us": int(timing[0][0]) if len(timing)==1 else None,
           "evidence_status": timing[0][1] if len(timing)==1 else None}
    if owner:
        row["cases"] = {key: bool(re.search(re.escape(name) + r" \.\.\. ok$", text, re.MULTILINE))
                        for key, name in roster.items() if key in CASES}
    print(json.dumps(row, sort_keys=True), flush=True)
    return row

for pair in range(6):
    order = ("base", "candidate") if pair % 2 == 0 else ("candidate", "base")
    for arm in order:
        rows.append(run(arm, f"solo-pair-{pair+1:02}"))
for arm in ("candidate", "base"):
    rows.append(run(arm, "owners", owner=True))
for pair in range(2):
    order = ("base", "candidate") if pair == 0 else ("candidate", "base")
    for arm in order:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(run, arm, f"two-way-pair-{pair+1}-{i+1}") for i in range(2)]
            rows.extend(attempt.result() for attempt in attempts)
(OUT / "results.json").write_text(json.dumps({
    "source": {"base": os.environ["BASE"], "candidate": os.environ["CANDIDATE"]},
    "machine": platform.uname()._asdict(), "fixture_timeout_ms": 500,
    "solo_pairs": 6, "two_way_pairs": 2, "attempts": rows}, indent=2) + "\n")
for row in rows:
    expected = 13 if row["label"]=="owners" else 1
    if (row["returncode"] or not any(f"ok. {expected} passed; 0 failed" in s for s in row["summary"])
        or ("cases" in row and not all(row["cases"].values()))
        or (expected == 1 and row["evidence_status"] != "Ok(())")):
        raise SystemExit("Results include a failed or missing original test; see all raw attempts")
