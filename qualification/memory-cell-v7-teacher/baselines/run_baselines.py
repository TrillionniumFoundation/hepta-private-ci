#!/usr/bin/env python3
"""Run the original frozen V6, V5 and deterministic routers on V7 held input.

No candidate is trained or modified. Only requests.jsonl is sent to children;
the evaluator alone reads labels.jsonl. No teacher source or old held text is
opened. Missing dependencies and invalid/missing output remain unknown.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


INTENTS = {"at", "previous", "change", "mean3", "range3", "peak3"}
REJECT = "__reject__"
REQUEST_SHA = "622fb6942a308a3e3930c960474f88b19e92cc31f5709309a56ad5c93c83d700"
LABEL_SHA = "1979ff69c07f7a2c4883699225b33d32ea368bb89f9892fe0890e8cbdf4c2677"
FREEZE_SHA = "01c4327b3f950b821861bb5ed54c592aa385e277260b9ab203059e765b0c8244"
V6_MODEL = "evidence/development-v6c/combined-lr-c1.0/model.json"
V6_SHA = "9107b8e9cc4f823cd227a43be04fe50c7ac07663c33623cbb5b71272eb69ac94"
V5_MODEL = "evidence/baseline-v5/seed-8011/selected"
V5_MANIFEST_SHA = "dbeb0963bb2ccd49ebe6078bea44a7ce5d51cd7add5e29c87e9499e959989965"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def verify_held(held):
    request_raw = (held / "requests.jsonl").read_bytes()
    label_raw = (held / "labels.jsonl").read_bytes()
    assert hashlib.sha256(request_raw).hexdigest() == REQUEST_SHA
    assert hashlib.sha256(label_raw).hexdigest() == LABEL_SHA
    requests = [json.loads(line) for line in request_raw.splitlines()]
    labels = [json.loads(line) for line in label_raw.splitlines()]
    assert len(requests) == len(labels) == 180
    for index, (request, label) in enumerate(zip(requests, labels, strict=True)):
        assert set(request) == {"utterance", "series_name", "date"}
        assert label["index"] == index
        assert hashlib.sha256(canonical(request)).hexdigest() == label["request_sha256"]
    assert Counter(row["expected_intent"] for row in labels) == Counter({
        **{intent: 20 for intent in INTENTS}, REJECT: 60})
    return request_raw, labels


def verify_frozen(v6):
    freeze_path = v6 / "FREEZE.json"
    assert identity(freeze_path)["sha256"] == FREEZE_SHA
    freeze = json.loads(freeze_path.read_text())
    observed = {"memory-cell-v6/FREEZE.json": identity(freeze_path)}
    # These inventories contain public source/development artifacts, not held input.
    for relative, expected in freeze["files"].items():
        assert "independent-held" not in relative
        actual = identity(v6 / relative)
        assert actual == {key: expected[key] for key in ("bytes", "sha256")}, relative
        observed["memory-cell-v6/" + relative] = actual
    for relative, expected in freeze["source_inventory"].items():
        assert "independent-held" not in relative
        actual = identity(v6.parent / relative)
        assert actual == {key: expected[key] for key in ("bytes", "sha256")}, relative
        observed[relative] = actual
    manifest_path = v6 / V5_MODEL / "manifest.json"
    assert identity(manifest_path)["sha256"] == V5_MANIFEST_SHA
    manifest = json.loads(manifest_path.read_text())
    observed["memory-cell-v6/" + V5_MODEL + "/manifest.json"] = identity(manifest_path)
    for relative, expected in manifest["files"].items():
        assert "/" not in relative and ".." not in relative
        actual = identity(manifest_path.parent / relative)
        assert actual == expected, relative
        observed["memory-cell-v6/" + V5_MODEL + "/" + relative] = actual
    assert identity(v6 / V6_MODEL)["sha256"] == V6_SHA
    return observed


def score(labels, stdout, returncode, timed_out):
    protocol_errors, decisions = [], []
    try:
        decisions = [json.loads(line) for line in stdout.splitlines()]
    except (ValueError, UnicodeError) as error:
        protocol_errors.append("non-JSON output: " + str(error))
    if len(decisions) != len(labels):
        protocol_errors.append(f"expected {len(labels)} replies, received {len(decisions)}")
    if returncode != 0 or timed_out:
        protocol_errors.append("child did not exit successfully")
    rows, counts = [], Counter()
    for index, gold in enumerate(labels):
        decision = decisions[index] if index < len(decisions) else None
        unknown = bool(protocol_errors)
        error = None
        accepted_intent = None
        if not unknown:
            if not isinstance(decision, dict) or "error" in decision:
                unknown, error = True, "missing decision or explicit child error"
            elif type(decision.get("accepted")) is not bool:
                unknown, error = True, "accepted is not a boolean"
            elif decision["accepted"]:
                accepted_intent = decision.get("accepted_intent")
                if not isinstance(accepted_intent, str) or accepted_intent not in INTENTS:
                    unknown, error = True, "accepted intent is outside original contract"
            elif decision.get("accepted_intent") is not None:
                unknown, error = True, "rejection carries an accepted intent"
        supported = gold["expected_intent"] != REJECT
        if unknown:
            outcome = "known_unknown" if supported else "ood_unknown"
        elif supported and accepted_intent == gold["expected_intent"]:
            outcome = "known_correct"
        elif supported and accepted_intent is None:
            outcome = "known_rejected"
        elif supported:
            outcome = "known_wrong"
        elif accepted_intent is None:
            outcome = "ood_rejected"
        else:
            outcome = "ood_false_accept"
        counts[outcome] += 1
        rows.append({"index": index, "request_sha256": gold["request_sha256"],
                     "expected_intent": gold["expected_intent"], "family": gold["family"],
                     "outcome": outcome, "decision": decision, "error": error})
    for key in ("known_correct", "known_wrong", "known_rejected", "known_unknown",
                "ood_rejected", "ood_false_accept", "ood_unknown"):
        counts.setdefault(key, 0)
    assert sum(counts[key] for key in counts if key.startswith("known_")) == 120
    assert sum(counts[key] for key in counts if key.startswith("ood_")) == 60
    unknown = counts["known_unknown"] + counts["ood_unknown"]
    summary = {**dict(counts), "supported_total": 120, "ood_total": 60,
               "correct_coverage": counts["known_correct"] / 120,
               "supported_acceptance": (counts["known_correct"] + counts["known_wrong"]) / 120,
               "ood_false_accept_rate": counts["ood_false_accept"] / 60,
               "protocol_complete": not protocol_errors, "protocol_errors": protocol_errors,
               "unknown": unknown,
               "gate": {"minimum_supported_correct": 96, "maximum_ood_false_accept": 3,
                        "maximum_unknown": 0},
               "gate_pass": not protocol_errors and unknown == 0
                   and counts["known_correct"] >= 96 and counts["ood_false_accept"] <= 3}
    return rows, summary


def run(args):
    v6 = args.v6_root.resolve()
    held = args.held.resolve()
    out = args.output.resolve()
    if out == v6 or v6 in out.parents or out == held or held in out.parents:
        raise ValueError("results must be outside both frozen directories")
    request_raw, labels = verify_held(held)
    before = verify_frozen(v6)
    out.mkdir(parents=True, exist_ok=False)
    save(out / "FROZEN_BEFORE.json", before)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(v6.parent / "memory-cell-v5")
    commands = {
        "v6_selected": [args.python, str(v6 / "native_router.py"), "--model", str(v6 / V6_MODEL), "--sha256", V6_SHA],
        "v5_selected": [args.python, str(v6 / "serve.py"), "--v5-model", str(v6 / V5_MODEL), "--sha256", V5_MANIFEST_SHA],
        "deterministic": [args.python, str(v6 / "native_router.py"), "--deterministic"],
    }
    result = {"schema": "hepta.cell-v7.frozen-baseline-evaluation.v1",
              "candidate_sources_or_calibration_modified": False, "trained": False,
              "previous_held_read": False, "teacher_source_or_output_read": False,
              "request_sha256": REQUEST_SHA, "label_sha256": LABEL_SHA,
              "results": {}, "limits": ["Finite synthetic routing evaluation only.",
                  "No agent, model service or system-wide memory claim is made.",
                  "Unknown rows are not counted as successful OOD rejection.",
                  "The original scripts do not echo request IDs; scoring requires a complete one-row-per-input stream."]}
    for name, command in commands.items():
        cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        stdout, stderr, code, timed_out = b"", b"", None, False
        try:
            child = subprocess.run(command, input=request_raw, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=v6, env=env, timeout=args.timeout)
            stdout, stderr, code = child.stdout, child.stderr, child.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, timed_out = error.stdout or b"", error.stderr or b"", True
        except OSError as error:
            stderr = str(error).encode()
        wall = time.perf_counter() - started
        cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        (out / (name + ".stdout.jsonl")).write_bytes(stdout)
        (out / (name + ".stderr.txt")).write_bytes(stderr)
        rows, summary = score(labels, stdout, code, timed_out)
        with (out / (name + ".evaluated.jsonl")).open("xb") as stream:
            for row in rows:
                stream.write(canonical(row) + b"\n")
        record = {"command": command, "returncode": code, "timed_out": timed_out,
                  "wall_seconds": wall,
                  "child_cpu_seconds": (cpu_after.ru_utime + cpu_after.ru_stime) - (cpu_before.ru_utime + cpu_before.ru_stime),
                  "stdout": identity(out / (name + ".stdout.jsonl")),
                  "stderr": identity(out / (name + ".stderr.txt")), **summary}
        result["results"][name] = record
        save(out / (name + ".REPORT.json"), record)
        print(json.dumps({"baseline": name, **summary}, sort_keys=True), flush=True)
    after = verify_frozen(v6)
    verify_held(held)
    assert after == before
    save(out / "FROZEN_AFTER.json", after)
    result["frozen_sources_models_and_held_unchanged"] = True
    result["all_lanes_valid"] = all(row["protocol_complete"] and row["unknown"] == 0 for row in result["results"].values())
    result["all_gates_pass"] = all(row["gate_pass"] for row in result["results"].values())
    save(out / "SUMMARY.json", result)
    return 0 if result["all_lanes_valid"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v6-root", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    raise SystemExit(run(args))
