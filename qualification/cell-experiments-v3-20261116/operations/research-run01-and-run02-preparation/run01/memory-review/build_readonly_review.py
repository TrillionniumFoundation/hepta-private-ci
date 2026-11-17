"""Package a selected, already-terminal memory-failure review; no model imports."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).parent
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
def emit(relative, raw):
    p = ROOT / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as stream:
        stream.write(raw)
    return relative
def emit_json(relative, value):
    return emit(relative, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode() + b"\n")
def read(relative):
    return json.loads((ROOT / "originals" / relative).read_bytes())

transfer = json.loads((ROOT / "TRANSFER.json").read_bytes())
recheck = json.loads((ROOT / "RECHECK_TRANSFER.json").read_bytes())
original_index, members, seal_checks = [], [], []
for row in transfer["files"]:
    p = PurePosixPath(row["path"])
    if p.is_absolute() or ".." in p.parts or str(p) != row["path"]:
        raise ValueError("unsafe member")
    raw = base64.b64decode(row["data_base64"], validate=True)
    if len(raw) != row["bytes"] or sha(raw) != row["sha256"] or row["eof"] is not True:
        raise ValueError("original byte identity differs")
    members.append(emit("originals/" + str(p), raw))
    original_index.append({k: row[k] for k in ("path", "bytes", "sha256", "version")})
    if p.suffix == ".json":
        value = json.loads(raw)
        if isinstance(value, dict) and "receipt_sha256" in value:
            unsealed = {k: v for k, v in value.items() if k != "receipt_sha256"}
            if sha(canonical(unsealed)) != value["receipt_sha256"]:
                raise ValueError("receipt seal differs: " + str(p))
            seal_checks.append(str(p))

for stem, tool, script in (
    ("PROCESS_IDENTITY", transfer["process_identity_observation_tool"], transfer["process_identity_observation_script"]),
    ("SOURCE_RECHECK", recheck["source_recheck_tool"], recheck["source_recheck_script"]),
):
    if tool["status"]["exit_code"] != 0 or tool["output_complete"] is not True:
        raise ValueError("review observation did not finish")
    if sha(tool["text"].encode()) != tool["chunk_sha256"]:
        raise ValueError("observation raw output differs")
    members.append(emit_json(stem + "_TERMINAL.json", tool))
    members.append(emit(stem + ".log", tool["text"].encode()))
    members.append(emit(stem.lower() + ".py", script.encode()))
observation = json.loads(transfer["process_identity_observation_tool"]["text"])
source_recheck = json.loads(recheck["source_recheck_tool"]["text"])
if {(r["path"], r["sha256"], r["bytes"]) for r in source_recheck["files"]} != {
    (r["path"], r["sha256"], r["bytes"]) for r in original_index
} or source_recheck["all_unchanged"] is not True:
    raise ValueError("Desktop recheck differs")
members.append(emit_json("ORIGINAL_INDEX.json", original_index))
members.append(emit_json("ROOT_INSPECTION_REFERENCE.json", transfer["root_inspection_reference"]))

names = ["corrections-collect", "parent-primary", "retrieval-primary", "final_answer-primary",
         "trajectory-primary", "shadow_correction-primary", "controlled_correction-primary"]
result = read("research-sft-01/RESULT.json")
owned = read("owned-research-sft-01/EXIT.json")
if result["status"] != "RESEARCH_PARTIAL_UNQUALIFIED" or owned["wait_returncode"] != 0:
    raise ValueError("unexpected terminal outcome")
timeline, gates, previous_end = [], [], None
for index, name in enumerate(names):
    launch = read("research-sft-01/processes/" + name + "/LAUNCH.json")
    exited = read("research-sft-01/processes/" + name + "/EXIT.json")
    if exited != result["children"][index]["exit"]:
        raise ValueError("coordinator child exit differs")
    started, ended = launch["started_at_ns"], exited["completed_at_ns"]
    if type(started) is not int or type(ended) is not int or started >= ended:
        raise ValueError("invalid exact timestamp")
    gap = None if previous_end is None else started - previous_end
    if gap is not None and gap <= 0:
        raise ValueError("overlapping worker lifetimes")
    if exited["timed_out"] or exited["exit_code"] != (0 if index == 0 else 1):
        raise ValueError("unexpected worker outcome")
    timeline.append({"name": name, "pid": exited["pid"], "started_at_ns": started,
                     "completed_at_ns": ended, "gap_after_previous_exit_ns": gap,
                     "exit_code": exited["exit_code"], "timed_out": exited["timed_out"]})
    previous_end = ended
    if index:
        failed = read("research-sft-01/workers/" + name + "/FAILED.json")
        expected = "line 129, in evaluate" if index < 3 else "line 135, in train"
        if expected not in failed["traceback"] or "line 311, in check_device" not in failed["traceback"]:
            raise ValueError("unexpected failure callsite")
        if failed["error"] != "ValueError('selected CUDA device has insufficient free memory')":
            raise ValueError("unexpected failure")
        gates.append({"name": name, "callsite": expected, "gate": "first explicit pre-model-load check",
                      "error": failed["error"], "actual_free_bytes_at_gate": None,
                      "predictor_constructor_reached": False, "optimizer_constructed": False})
if owned["completed_at_ns"] <= previous_end:
    raise ValueError("coordinator exit precedes child completion")

parent = read("probe-qwen-parent-03/parent.json")
first = read("research-sft-01/workers/corrections-collect/shadow/0/output-0.json")
collection = read("research-sft-01/workers/corrections-collect/RESULT.json")
threshold = parent["runtime"]["min_cuda_free_bytes"]
if threshold != 4294967296 or first["pid"] != timeline[0]["pid"]:
    raise ValueError("runtime or first prediction differs")
report = {
    "schema": "hepta.research-run01-memory-failure-review.v1",
    "scope": "selected frozen source and terminal original receipts; not a complete execution archive",
    "operation": "research-sft-01", "observed_result": result["status"],
    "owned_wait_returncode": owned["wait_returncode"],
    "review_model_calls": 0, "review_reference_calls": 0, "review_signals_sent": 0,
    "frozen_sources_modified": False, "environment_read": False, "new_C_read": False,
    "independent_sample_increment": 0,
    "conclusion": "All six primaries failed the first explicit available-memory gate before loading Qwen; exact worker receipts are strictly sequential.",
    "not_supported": [
        "A worker loaded this Qwen and then failed a duplicate memory gate.",
        "One of the seven owned worker processes remained alive while the next was launched.",
        "The later non-owned GPU PID is definitively responsible for every earlier failure.",
        "Later GPU observations recover exact free bytes at each failed gate.",
        "CUDA context initialization and driver reclamation latency were measured or ruled out.",
        "This partial operation completed four fits or produced capability, Circuit, PoUW, adoption, or new-sample evidence."
    ],
    "timeline": timeline, "failed_gates": gates,
    "threshold_bytes": threshold,
    "collection_preload_free_bytes": first["device"]["free_bytes_before_load"],
    "collection_preload_scope": "one pre-load Predictor device report; reused in prediction outputs, not live per-call memory",
    "device": first["device"],
    "external_pid_observation": observation,
    "external_pid_ownership": "unknown; process absent when this review attempted bounded identification",
    "root_gpu_observation_reference": transfer["root_inspection_reference"],
    "root_gpu_values_are_separate_observations_not_per_gate_measurements": True,
    "fit_attempts_started": result["fit_attempts_started"],
    "fits_completed": result["fits_completed"],
    "completed_training_step_receipts": result["ledger"]["completed_training_step_receipts"],
    "ledger_training_steps_total": result["ledger"]["training_steps"],
    "ledger_global_totals_unknown": result["ledger"]["global_totals_unknown"],
    "completed_shadow_output_receipts": collection["new_model_calls"],
    "shadow_input_tokens_measured": collection["input_tokens"],
    "shadow_output_tokens_measured": collection["output_tokens"],
    "authored_reference_receipts": result["ledger"]["authored_reference_receipts"],
    "cost_policy": "Preserve partial unknown totals and nonadditive nested scopes; no new cost extrapolation.",
    "source_recheck_observed_at_ns": source_recheck["observed_at_ns"],
    "selected_original_count": len(original_index),
    "sealed_receipts_verified": seal_checks,
    "method": "stdlib-only byte copying, SHA verification, JSON parsing with exact Python integers, and source inspection; no frozen module imported."
}
members.append(emit_json("REVIEW.json", report))
table = "\n".join("| {name} | {pid} | {exit_code} | {gap} |".format(
    **row, gap="n/a" if row["gap_after_previous_exit_ns"] is None else str(row["gap_after_previous_exit_ns"]))
    for row in timeline)
readme = f"""# Research 01: memory-gate failure review

All six primary workers failed their first explicit available-memory check before Qwen was loaded in that worker. The seven real worker LAUNCH/EXIT pairs are strictly sequential. Collection exited 0; all six primaries exited 1, without timeout. The coordinator's owned wait returned 0 because it preserved and reported a partial study.

## Actual execution order

| Worker | PID | Exit | Gap after previous EXIT (ns) |
| --- | ---: | ---: | ---: |
{table}

Exact integer timestamps, original file hashes, worker traces, and receipt seals are retained in REVIEW.json and ORIGINAL_INDEX.json. Original byte copies are under originals/. All 31 selected Desktop files were reread and verified unchanged after collection.

## Gate and allocation order

- parent/retrieval: research_sft_execution_v1.py line 129 calls check_device after gc.collect/empty_cache, before load_predictor at line 132.
- Four fits: research_sft_train_v1.py line 135 calls check_device after six authored-reference rechecks, before memory-fraction setup, Predictor at line 142, LoRA, optimizer, and fit_steps.
- causal_probe_v3.py lines 309-311 read mem_get_info and reject free bytes below {threshold}. The failing branch does not save the actual free-byte value.
- Predictor has its own pre-load check at line 331, before model .to(device). None of these six traces reaches its constructor.
- The collection Predictor close drops model/tokenizer references and collects Python garbage, without explicit empty_cache. Its process actually exited before parent-primary was launched. No live owned-worker overlap appears in the retained receipts. CUDA-context overhead and driver-reclamation timing were not instrumented.

This establishes failure before this worker's Qwen/LoRA/optimizer allocation. It does not establish zero CUDA overhead in the process or exclusive attribution to another process.

## Memory observations and limits

The first actual shadow output records {first["device"]["free_bytes_before_load"]} B (5530.625 MiB) available before collection model load. The unchanged threshold is 4 GiB. Root separately observed 6531 MiB before the operation and 3963 MiB later, including a different PID 2228309 using 2570 MiB; that source is linked by SHA in ROOT_INSPECTION_REFERENCE.json and is not a measurement at each failed check.

In this review's one bounded read-only identity observation, PID 2228309 was already absent. No PPID or script ownership was established, no environment or inline -c code was retained, and no signal was sent. Its ownership and exact causal contribution remain unknown.

## Scientific and accounting boundary

The actual retained collection has 6 shadow outputs, 1727 input tokens and 1764 output tokens. The coordinator ledger retains 36 authored-reference receipts. There are 4 training-entry STARTED records, 0 completed fits and 0 completed step receipts. The raw partial ledger's overall training-step total remains null, not rewritten to zero; the failure callsites independently show these four fits did not reach an optimizer update. Unknown total costs remain unknown; nested process costs are not added again.

These are failed execution and descriptive engineering records. They add no independent sample, teacher, user, new C, Cell adoption, Circuit, PoUW or capability evidence. A separately numbered resource reschedule must preserve this operation and its costs and cannot be described as a preregistered first run or new sample.

## Package

The ZIP is a selected review bundle, not the full study archive. MANIFEST.json lists every bundled member and SHA. REVIEW_VERIFIED.json binds ZIP SHA, CRC/member hashes, and unchanged copied source bytes. TRANSFER.json and RECHECK_TRANSFER.json are local transfer containers and are excluded from the ZIP to avoid duplicate evidence bytes. No model or reference was executed and no frozen source was changed by this review.
"""
members.append(emit("README.md", readme.encode()))
members.append("build_readonly_review.py")
inventory = [{"path": p, "bytes": (ROOT / p).stat().st_size, "sha256": sha((ROOT / p).read_bytes())}
             for p in sorted(members)]
if any(x["bytes"] >= 512000 for x in inventory):
    raise ValueError("member too large")
manifest = {"schema": "hepta.selected-review-bundle.v1", "members": inventory,
            "original_count": len(original_index), "selected_scope_only": True}
members.append(emit_json("MANIFEST.json", manifest))
zip_path = ROOT / "research-run01-memory-review-01.zip"
with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for p in sorted(members):
        archive.write(ROOT / p, p)
with zipfile.ZipFile(zip_path) as archive:
    if archive.testzip() is not None or set(archive.namelist()) != set(members):
        raise ValueError("ZIP verification failed")
    for p in members:
        if archive.read(p) != (ROOT / p).read_bytes():
            raise ValueError("member bytes changed")
for row in original_index:
    raw = (ROOT / "originals" / row["path"]).read_bytes()
    if len(raw) != row["bytes"] or sha(raw) != row["sha256"]:
        raise ValueError("copied original changed")
for row in inventory:
    raw = (ROOT / row["path"]).read_bytes()
    if len(raw) != row["bytes"] or sha(raw) != row["sha256"]:
        raise ValueError("bundle source changed")
verified = {"schema": "hepta.selected-review-verification.v1", "zip": zip_path.name,
            "bytes": zip_path.stat().st_size, "sha256": sha(zip_path.read_bytes()),
            "members": len(members), "originals": len(original_index),
            "crc_and_every_member_verified": True, "copied_originals_before_after_equal": True,
            "manifest_sha256": sha((ROOT / "MANIFEST.json").read_bytes()),
            "review_sha256": sha((ROOT / "REVIEW.json").read_bytes())}
emit_json("REVIEW_VERIFIED.json", verified)
print(json.dumps(verified, sort_keys=True), flush=True)
