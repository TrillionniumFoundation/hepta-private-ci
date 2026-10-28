"""Frozen semantic reference router. Only three unlabeled serving fields enter the model."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
import uuid

from transport import SseEvidence, canonical, decode_json, post_once

HERE = Path(__file__).resolve().parent
MODEL = "qwen38-flash-next-uc"
TIMEOUT_SECONDS = 30
OUTPUT_TOKENS = 256
FROZEN_FILES = {"teacher_router.py", "transport.py", "prompt.txt", "PROTOCOL.json", "SOURCE.json", "freeze.py", "test_teacher_router.py"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def durable_bytes(path, data):
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, value):
    durable_bytes(path, canonical(value) + b"\n")


def read_inputs(path, expected_sha256):
    raw = path.read_bytes()
    if sha(raw) != expected_sha256:
        raise ValueError("serving input differs from the external frozen hash")
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("serving corpus byte budget exceeded")
    rows = []
    for line in raw.splitlines():
        request = decode_json(line)
        if not isinstance(request, dict) or set(request) != {"utterance", "series_name", "date"}:
            raise ValueError("input must contain exactly three unlabeled serving fields")
        if any(not isinstance(v, str) or not v.strip() for v in request.values()):
            raise ValueError("serving fields must be nonempty strings")
        if (len(request["utterance"]) > 4096 or len(request["series_name"]) > 256
                or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", request["date"])):
            raise ValueError("serving fields exceed the V5 contract")
        rows.append(request)
    if not 1 <= len(rows) <= 256:
        raise ValueError("one run supports 1..256 requests")
    return rows


def frozen_prompt(expected_sha256):
    raw = (HERE / "FREEZE.json").read_bytes()
    if sha(raw) != expected_sha256:
        raise ValueError("freeze record differs from the externally pinned hash")
    freeze = decode_json(raw)
    if set(freeze["files"]) != FROZEN_FILES:
        raise ValueError("frozen source inventory differs")
    for name, identity in freeze["files"].items():
        data = (HERE / name).read_bytes()
        if {"bytes": len(data), "sha256": sha(data)} != identity:
            raise ValueError("frozen source changed: " + name)
    return (HERE / "prompt.txt").read_text()


def request_body(prompt, request):
    return canonical({"model": MODEL, "instructions": prompt,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": canonical(request).decode()}]}],
        "max_output_tokens": OUTPUT_TOKENS, "stream": True, "store": False})


def identity(run, index, body):
    return "hepta-route-" + sha(canonical({"run_id": run["run_id"], "input_sha256": run["input_sha256"],
        "freeze_sha256": run["freeze_sha256"], "index": index, "body_sha256": sha(body)}))


def execute(index, request, prompt, run, output):
    case = output / f"case-{index:04d}"
    case.mkdir(mode=0o700)
    body = request_body(prompt, request)
    operation_id = identity(run, index, body)
    durable_bytes(case / "request.body.json", body)
    admission = {"operation_id": operation_id, "index": index,
        "request_sha256": sha(canonical(request)), "body_sha256": sha(body),
        "submission_attempted": True, "created_ns": time.time_ns(),
        "endpoint": run["endpoint"], "model": MODEL, "automatic_retry_allowed": False}
    # A committed attempt marker prevents an automatic second POST after a crash.
    write_json(case / "admission.json", admission)
    result = post_once(run["endpoint"], body, operation_id, case / "response.sse", TIMEOUT_SECONDS)
    result.update({"index": index, "request_sha256": admission["request_sha256"]})
    evidence = case / "response.sse"
    if evidence.exists():
        with evidence.open("rb") as stream:
            os.fsync(stream.fileno())
        result["response_sha256"] = sha(evidence.read_bytes())
    write_json(case / "result.json", result)
    print(json.dumps({"index": index, "status": result["status"], "operation_id": operation_id}), flush=True)
    return result


def observe(index, request, prompt, run, output):
    """Reads retained bytes only; no network, new ID, or second admission."""
    case = output / f"case-{index:04d}"
    body = request_body(prompt, request)
    operation_id = identity(run, index, body)
    result = {"index": index, "operation_id": operation_id, "request_sha256": sha(canonical(request)),
              "status": "not_attempted", "raw_label": None, "accepted": False, "accepted_intent": None,
              "observation_only": True, "network_requests": 0}
    if not (case / "admission.json").exists():
        return result
    result["status"] = "unknown_or_invalid"
    try:
        admission = decode_json((case / "admission.json").read_bytes())
        if (admission["operation_id"] != operation_id or admission["body_sha256"] != sha(body)
                or (case / "request.body.json").read_bytes() != body):
            raise ValueError("original model admission binding differs")
        decoder = SseEvidence()
        raw = (case / "response.sse").read_bytes()
        decoder.feed(raw)
        result.update(decoder.result())
        result["response_sha256"] = sha(raw)
    except Exception as error:
        result.update({"error_type": type(error).__name__, "error": str(error)})
    return result


def summarize(results, started, cpu_started, run):
    completed = [row for row in results if row["status"] == "completed"]
    usage_totals = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        known = [row["usage"][key] for row in completed
                 if isinstance(row.get("usage"), dict) and type(row["usage"].get(key)) is int
                 and row["usage"][key] >= 0]
        usage_totals[key] = {"known_sum": sum(known), "known_requests": len(known),
                            "all_requested_calls_accounted": len(known) == len(results)}
    return {"schema": "memory-cell-v7.teacher-run.v1", "run": run, "requested": len(results),
        "completed": len(completed), "unknown_or_not_attempted": len(results) - len(completed),
        "valid_rejections": sum(row.get("raw_label") == "__reject__" for row in completed),
        "accepted": sum(row["accepted"] for row in completed), "usage": usage_totals,
        "wall_seconds": time.monotonic() - started, "local_client_cpu_seconds": time.process_time() - cpu_started,
        "remote_model_cpu_memory_and_weights": "unmeasured", "distillation_performed": False,
        "semantic_accuracy_requires_independent_labels": True,
        "unknown_outcomes_are_not_correct_ood_rejections": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:18081/v1")
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    prompt = frozen_prompt(args.freeze_sha256)
    rows = read_inputs(args.input, args.input_sha256)
    url = urlsplit(args.endpoint)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        parser.error("endpoint must be an explicit HTTP(S) base without credentials or query")
    os.umask(0o077)
    run = {"input_sha256": args.input_sha256, "freeze_sha256": args.freeze_sha256,
           "endpoint": args.endpoint.rstrip("/"), "model": MODEL, "concurrency": args.concurrency,
           "timeout_seconds": TIMEOUT_SECONDS, "max_output_tokens": OUTPUT_TOKENS,
           "prompt_sha256": sha(prompt.encode()), "requests": len(rows)}
    if args.observe_only:
        existing = decode_json((args.output / "RUN.json").read_bytes())
        if {key: existing[key] for key in run} != run:
            raise ValueError("observation parameters differ from the original run")
        run = existing
    else:
        args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        run["run_id"] = str(uuid.uuid4())
        run["created_ns"] = time.time_ns()
        write_json(args.output / "RUN.json", run)
    started, cpu_started = time.monotonic(), time.process_time()
    action = observe if args.observe_only else execute
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(action, index, row, prompt, run, args.output) for index, row in enumerate(rows)]
        results = [future.result() for future in futures]
    prefix = "observed-" if args.observe_only else ""
    durable_bytes(args.output / (prefix + "results.jsonl"), b"".join(canonical(row) + b"\n" for row in results))
    summary = summarize(results, started, cpu_started, run)
    write_json(args.output / (prefix + "SUMMARY.json"), summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["completed"] == len(rows) else 3


if __name__ == "__main__":
    raise SystemExit(main())
