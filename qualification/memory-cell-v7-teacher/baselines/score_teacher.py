#!/usr/bin/env python3
"""Score frozen teacher results without importing teacher code or prompt."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


INTENTS = {"at", "previous", "change", "mean3", "range3", "peak3"}
REJECT = "__reject__"
REQUEST_SHA = "622fb6942a308a3e3930c960474f88b19e92cc31f5709309a56ad5c93c83d700"
LABEL_SHA = "1979ff69c07f7a2c4883699225b33d32ea368bb89f9892fe0890e8cbdf4c2677"


def held_canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def teacher_canonical(value):
    # Exact specification supplied by the parent; no teacher file was opened.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_held(root):
    request_raw = (root / "requests.jsonl").read_bytes()
    label_raw = (root / "labels.jsonl").read_bytes()
    assert digest(request_raw) == REQUEST_SHA and digest(label_raw) == LABEL_SHA
    requests = [json.loads(line) for line in request_raw.splitlines()]
    labels = [json.loads(line) for line in label_raw.splitlines()]
    assert len(requests) == len(labels) == 180
    for index, (request, label) in enumerate(zip(requests, labels, strict=True)):
        assert set(request) == {"utterance", "series_name", "date"}
        assert label["index"] == index
        assert digest(held_canonical(request)) == label["request_sha256"]
    assert Counter(row["expected_intent"] for row in labels) == Counter({
        **{intent: 20 for intent in INTENTS}, REJECT: 60})
    return requests, labels


def score(requests, labels, records):
    by_index = defaultdict(list)
    operations = defaultdict(list)
    global_errors = []
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            global_errors.append({"position": position, "error": "record is not an object"})
            continue
        index = record.get("index")
        if type(index) is not int or not 0 <= index < 180:
            global_errors.append({"position": position, "error": "invalid request index"})
            continue
        by_index[index].append(record)
        operation = record.get("operation_id")
        if isinstance(operation, str) and operation:
            operations[operation].append(index)
    if len(records) != 180:
        global_errors.append({"error": "result count differs", "received": len(records), "expected": 180})
    reused = {index for indices in operations.values() if len(indices) > 1 for index in indices}
    rows, counts, confusion = [], Counter(), Counter()
    for index, (request, gold) in enumerate(zip(requests, labels, strict=True)):
        matches = by_index[index]
        record = matches[0] if len(matches) == 1 else None
        errors = []
        intent = None
        if record is None:
            errors.append("missing or duplicate result for original input")
        else:
            if record.get("request_sha256") != digest(teacher_canonical(request)):
                errors.append("teacher request canonical fingerprint differs")
            if record.get("status") != "completed":
                errors.append("original request did not reach declared terminal completion")
            if not isinstance(record.get("operation_id"), str) or not record["operation_id"].strip():
                errors.append("original operation identity missing")
            if index in reused:
                errors.append("operation identity reused across result rows")
            raw = record.get("raw_label")
            accepted = record.get("accepted")
            intent = record.get("accepted_intent")
            if not isinstance(raw, str) or raw not in INTENTS | {REJECT}:
                errors.append("raw label outside frozen finite contract")
            elif type(accepted) is not bool:
                errors.append("accepted flag is not a boolean")
            elif raw == REJECT:
                if accepted or intent is not None:
                    errors.append("rejection label and acceptance fields disagree")
            elif not accepted or intent != raw:
                errors.append("supported label and acceptance fields disagree")
        supported = gold["expected_intent"] != REJECT
        if errors:
            outcome, observed = ("known_unknown" if supported else "ood_unknown"), "__unknown__"
        elif supported and intent == gold["expected_intent"]:
            outcome, observed = "known_correct", intent
        elif supported and intent is None:
            outcome, observed = "known_rejected", REJECT
        elif supported:
            outcome, observed = "known_wrong", intent
        elif intent is None:
            outcome, observed = "ood_rejected", REJECT
        else:
            outcome, observed = "ood_false_accept", intent
        counts[outcome] += 1
        confusion[(gold["expected_intent"], observed)] += 1
        rows.append({"index": index, "held_request_sha256": gold["request_sha256"],
                     "teacher_request_sha256": digest(teacher_canonical(request)),
                     "expected_intent": gold["expected_intent"], "family": gold["family"],
                     "outcome": outcome, "errors": errors, "records": matches})
    for key in ("known_correct", "known_wrong", "known_rejected", "known_unknown",
                "ood_rejected", "ood_false_accept", "ood_unknown"):
        counts.setdefault(key, 0)
    assert sum(counts[k] for k in counts if k.startswith("known_")) == 120
    assert sum(counts[k] for k in counts if k.startswith("ood_")) == 60
    unknown = counts["known_unknown"] + counts["ood_unknown"]
    # Failed/invalid attempts still incur costs. Sum all recorded provider usage,
    # rather than only correctly classified inputs, and disclose attribution gaps.
    usage_totals = Counter()
    usage_rows_missing = 0
    for record in records:
        usage = record.get("usage") if isinstance(record, dict) else None
        if not isinstance(usage, dict) or any(type(usage.get(key)) is not int or usage[key] < 0
                                              for key in ("input_tokens", "output_tokens")):
            usage_rows_missing += 1
            continue
        usage_totals["input_tokens"] += usage["input_tokens"]
        usage_totals["output_tokens"] += usage["output_tokens"]
        cached = usage.get("input_tokens_details", {}).get("cached_tokens") if isinstance(usage.get("input_tokens_details"), dict) else None
        if type(cached) is int and cached >= 0:
            usage_totals["cached_input_tokens"] += cached
    terminal_complete = not global_errors and unknown == 0 and len(records) == 180
    summary = {"schema": "hepta.cell-v7.teacher-evaluation.v1", **dict(counts),
               "supported_total": 120, "ood_total": 60, "unknown": unknown,
               "correct_coverage": counts["known_correct"] / 120,
               "ood_false_accept_rate": counts["ood_false_accept"] / 60,
               "all_original_requests_terminal_and_bound": terminal_complete,
               "global_protocol_errors": global_errors,
               "gate": {"minimum_supported_correct": 96, "maximum_ood_false_accept": 3,
                        "maximum_unknown": 0, "required_bound_terminal_results": 180},
               "gate_pass": terminal_complete and counts["known_correct"] >= 96 and counts["ood_false_accept"] <= 3,
               "confusion": [{"expected": expected, "observed": observed, "count": count}
                             for (expected, observed), count in sorted(confusion.items())],
               "recorded_provider_usage": dict(usage_totals),
               "usage_rows_missing_or_invalid": usage_rows_missing,
               "usage_sum_is_fully_attributable": not global_errors and not reused and usage_rows_missing == 0,
               "usage_includes_failed_or_invalid_attempts_when_present": True,
               "request_sha256": REQUEST_SHA, "label_sha256": LABEL_SHA,
               "limits": ["Synthetic English routing task; no production-agent or numeric-execution result.",
                          "Unknown requests are not credited as OOD rejection.",
                          "Provider usage is reported as observed; absent usage is not zero cost."]}
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    held, output = args.held.resolve(), args.output.resolve()
    if output == held or held in output.parents:
        raise ValueError("evaluation output cannot modify the frozen held directory")
    requests, labels = read_held(held)
    if args.results.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("results exceed the declared read budget")
    raw = args.results.read_bytes()
    records = []
    for position, line in enumerate(raw.splitlines()):
        try:
            records.append(json.loads(line))
        except (ValueError, UnicodeError) as error:
            # Result order may be concurrent: do not guess an input index for a
            # damaged line. Its unknown input stays missing and blocks the gate.
            records.append({"malformed_result_position": position,
                            "raw_line_sha256": digest(line), "parse_error": str(error)})
    rows, summary = score(requests, labels, records)
    summary["results_sha256"] = digest(raw)
    summary["evaluator_sha256"] = digest(Path(__file__).read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    with (output / "evaluated.jsonl").open("xb") as stream:
        for row in rows:
            stream.write(held_canonical(row) + b"\n")
    with (output / "SUMMARY.json").open("xb") as stream:
        stream.write(held_canonical(summary) + b"\n")
    read_held(held)
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0 if summary["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
