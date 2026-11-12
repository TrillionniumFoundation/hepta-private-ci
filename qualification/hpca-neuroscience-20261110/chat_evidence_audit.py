#!/usr/bin/env python3
"""Portable read-only admission of the frozen 24-task chat diagnostic.

Checks recorded bytes and arithmetic, never executes a model or authenticates
the original producer. Original source/plan, labels and parser remain frozen.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

ORIGIN_HEAD = "4669280bd92804e6b5357ec0d8a27197858a5b6a"
ORIGIN_TREE = "d78b935a2f5abe1273dced958460c7a3e23ddea6"
PLAN_SHA = "acb16047e5942d317262ddb8273a2d62e9131e758d6627dcf1c2f42081d98043"
AUTHORITY = "DENY_ALL_HOLD_NO_GO"
EXPECTED_SOURCES = {
    "BASE_OUTPUT_PLAN.json": "ae4b53e867380d5cd582679612ed0a0970fe89d36eadef19ae7a2b243000b555",
    "CHAT_WRAPPER_PLAN.json": "5ab417097980e4f878d77288d932319bbb6ea31605acd1ca3b801227aeb33f95",
    "HPCA_V2_OOD_PLAN.json": PLAN_SHA,
    "chat_wrapper_probe.py": "ddd53e863301fdbc58600f7f90c12e153f2217d3fa527be933fc4130607e4d28",
    "freegen_contract.py": "daf7e381992bb7fd131f67aaa09eb21433a1804e423deccacd87edf342a2da5b",
    "native_lora_ood_probe.py": "b9f61e8133f67af2d126c3730588c1386efcfb2788259f618e092081c2454af8",
}
MAX_BYTES = 2 * 1024 * 1024


class AuditError(ValueError):
    """Ambiguous or incomplete recorded evidence, with no qualification credit."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    require(isinstance(data, bytes) and len(data) <= MAX_BYTES, "input byte limit")

    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate JSON key")
            out[key] = value
        return out

    def number(text):
        value = float(text)
        require(math.isfinite(value), "non-finite JSON number")
        return value

    def constant(text):
        raise AuditError("non-finite JSON constant: " + text)

    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                            parse_float=number, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AuditError("invalid JSON") from exc
    require(type(result) is dict, "JSON object required")
    return result


def exact(left, right):
    # Python's ordinary equality aliases True with 1 and False with 0.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False)


def semantic_digest(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode())


def audit(result_bytes, pre_bytes, journal_bytes, plan_bytes):
    require(digest(plan_bytes) == PLAN_SHA, "frozen task plan changed")
    result, pre, plan = map(strict_json, (result_bytes, pre_bytes, plan_bytes))
    require(result.get("schema") == "HPCA-CHAT-WRAPPER-PUBLIC-RESULT-1",
            "result schema")
    require(pre.get("schema") == "HPCA-CHAT-WRAPPER-PREEXECUTION-1", "preexecution schema")
    require(result.get("authority") == pre.get("authority") == AUTHORITY, "authority")
    require(result.get("head") == pre.get("head") == ORIGIN_HEAD, "origin head")
    require(result.get("tree") == pre.get("tree") == ORIGIN_TREE, "origin tree")
    require(result.get("preexecution_sha256") == digest(pre_bytes), "preexecution hash")
    require(result.get("journal_sha256") == digest(journal_bytes), "journal hash")
    require(type(pre.get("weight_updates")) is int and pre["weight_updates"] == 0,
            "unexpected training")
    require(type(pre.get("independent_future")) is int and pre["independent_future"] == 0,
            "unsupported future claim")
    require(pre.get("sources") == EXPECTED_SOURCES, "frozen source manifest")
    require(pre["sources"]["HPCA_V2_OOD_PLAN.json"] == PLAN_SHA, "source plan hash")
    config = pre.get("config", {})
    require(semantic_digest(config) ==
            "932c68965af7e412a4b98606cec3d098c2db0afa0965911f8a14c2fd492bf86c",
            "frozen complete generation configuration")
    require(exact(pre.get("runtime"), {"cpu_threads": 4, "python": "3.14.4",
            "torch": "2.9.1+cpu", "transformers": "4.57.3"}), "frozen runtime")
    require(semantic_digest(pre.get("model")) ==
            "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c",
            "frozen model asset witnesses")
    require(semantic_digest(pre.get("prompts")) ==
            "e74d086ed173d3be4bd2acd3c1ac4e75d8a3bb26dfe5507af13e94f0e363b377",
            "frozen prompt token witnesses")
    tasks, rows, prompts = plan["tasks"], result.get("rows"), pre.get("prompts")
    require(type(rows) is list and type(prompts) is list and len(rows) == len(prompts) == 24,
            "complete 24-task denominator required")
    ids = [t["id"] for t in tasks]
    require([r.get("id") for r in rows] == [p.get("id") for p in prompts] == ids,
            "task identity or order")
    for row, task, prompt in zip(rows, tasks, prompts):
        require(row.get("truth") == task["truth"] and row.get("family") == task["family"],
                "frozen truth or family changed")
        tokens, input_ids = row.get("tokens"), prompt.get("input_ids")
        require(type(tokens) is list and 1 <= len(tokens) <= 8 and all(
            type(t) is int and 0 <= t < 2**31 for t in tokens), "generated token identity")
        require(type(input_ids) is list and 1 <= len(input_ids) <= 8192 and all(
            type(t) is int and 0 <= t < 2**31 for t in input_ids), "input token identity")
        require(type(row.get("text")) is str, "generated text type")
        match = re.match(r"^\s*(yes|no)(?!\w)", row["text"], flags=re.IGNORECASE)
        parsed = match.group(1).lower() if match else None
        require(row.get("parsed") == parsed, "parsed answer changed")
        for key, value in {"valid": parsed is not None,
                           "correct": parsed == task["truth"],
                           "first_eos": tokens[0] == 2}.items():
            require(type(row.get(key)) is bool and row[key] is value, "row flag: " + key)
        seconds = row.get("inference_wall_seconds")
        require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
                "invalid inference time")
    require(isinstance(journal_bytes, bytes) and len(journal_bytes) <= MAX_BYTES,
            "journal byte limit")
    journal = [strict_json(line) for line in journal_bytes.splitlines()]
    require(len(journal) == 49, "complete journal required")
    run_id = journal[0].get("run_id")
    require(type(run_id) is str and re.fullmatch(r"[0-9a-f]{32}", run_id), "run id")
    for index, event in enumerate(journal):
        require(event.get("run_id") == run_id, "mixed journal run ids")
        require(type(event.get("sequence")) is int and event["sequence"] == index,
                "journal sequence")
    for index, row in enumerate(rows):
        started, completed = journal[2*index:2*index+2]
        require(set(started) == {"kind", "run_id", "sequence", "task_id"} and
                started["kind"] == "attempt_started" and started["task_id"] == row["id"],
                "adjacent attempt start")
        require(set(completed) == {"kind", "run_id", "sequence", "row"} and
                completed["kind"] == "row_completed" and exact(completed["row"], row),
                "adjacent row completion")
    terminal = journal[-1]
    require(set(terminal) == {"kind", "run_id", "sequence", "n"} and
            terminal["kind"] == "all_rows_complete" and type(terminal["n"]) is int and
            terminal["n"] == 24, "terminal completion")
    summary = {"n": 24, "valid": sum(r["valid"] for r in rows),
               "correct": sum(r["correct"] for r in rows),
               "first_eos": sum(r["first_eos"] for r in rows), "independent_future": 0}
    require(exact(result.get("summary"), summary), "summary arithmetic or types")
    return {"schema": "hpca-chat-recorded-evidence-audit-v1", "authority": AUTHORITY,
            "status": "RECORDED_BYTE_CONSISTENCY_PASS", "summary": summary,
            "run_id": run_id, "journal_events": len(journal),
            "result_sha256": digest(result_bytes), "preexecution_sha256": digest(pre_bytes),
            "journal_sha256": digest(journal_bytes), "plan_sha256": PLAN_SHA,
            "origin_head": ORIGIN_HEAD, "origin_tree": ORIGIN_TREE,
            "new_model_inferences": 0, "independent_future_qualified": 0,
            "calibration": "MISSING", "future_confirmation": "MISSING",
            "old_task_retention": "MISSING", "production_qualified": False}


def read_bounded(path):
    require(path.is_file() and not path.is_symlink(), "missing regular input: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "input byte limit")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence, source = args.evidence_dir, args.source_dir
        result_bytes, pre_bytes, journal_bytes = (read_bounded(evidence / name)
            for name in ("RESULT.json", "PREEXECUTION.json", "ROWS.jsonl"))
        report = audit(result_bytes, pre_bytes, journal_bytes,
                       read_bounded(source / "HPCA_V2_OOD_PLAN.json"))
        pre = strict_json(pre_bytes)
        for name, expected in pre["sources"].items():
            require(digest(read_bounded(source / name)) == expected, "source drift: " + name)
        report["source_files_rechecked"] = len(pre["sources"])
        report["model_bytes_recheck"] = "NOT_RUN"
        report["token_decode_reexecution"] = "NOT_RUN"
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    except (AuditError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, "EVIDENCE_REJECTED: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
