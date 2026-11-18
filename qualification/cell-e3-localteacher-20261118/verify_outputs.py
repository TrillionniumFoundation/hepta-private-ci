"""Verify exact second-teacher outputs and bind feedback for the next stage."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from cell_experiments import data, protocol_v3, repo_execution


def read(path):
    return data._parse(path.read_bytes())


def write(path, value):
    with path.open("xb") as stream:
        stream.write(data.canonical(value) + b"\n")


def main(run, output, stage):
    protocol = read(HERE / "PROTOCOL.json")
    if (hashlib.sha256(Path(__file__).read_bytes()).hexdigest() !=
            protocol["local_verifier_helper_sha256"]):
        raise ValueError("published output-verification helper changed")
    for path, key in ((Path(repo_execution.__file__), "verifier_source_sha256"),
                      (Path(protocol_v3.__file__), "feedback_source_sha256")):
        if hashlib.sha256(path.read_bytes()).hexdigest() != protocol[key]:
            raise ValueError("original source differs: " + key)
    records = read(HERE / "A_RECORDS.json")
    repo_execution.load_catalog("open")
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    receipts, feedbacks, costs = [], [], []
    if stage == "reference":
        answers = [record["final_answer"] for record in records]
    else:
        freeze = read(run / "FREEZE.json")
        if freeze["records_digest"] != data.digest(records) or freeze["protocol"] != protocol:
            raise ValueError("actual teacher freeze differs")
        answers = []
        for index, record in enumerate(records):
            request = read(run / stage / f"REQUEST-{index}.json")
            original = read(run / stage / f"OUTPUT-{index}.json")
            if (original["record_id"] != record["record_id"] or
                    original["freeze_digest"] != data.digest(freeze) or
                    original["request_digest"] != data.digest(request["payload"]) or
                    original["logical_messages_digest"] != data.digest(request["logical_messages"])):
                raise ValueError("raw teacher request or output binding differs")
            raw = original["raw_response"]
            answer = raw["choices"][0]["message"].get("content") or ""
            if answer != original["answer"]:
                raise ValueError("teacher answer was modified")
            answers.append(answer)
            usage = original.get("usage") or {}
            costs.append({"record_id": record["record_id"], "wall_seconds": original["wall_seconds"],
                          "usage": usage, "finish_reason": raw["choices"][0].get("finish_reason"),
                          "input_budget_observed": isinstance(usage.get("prompt_tokens"), int) and
                          usage["prompt_tokens"] <= protocol["maximum_observed_input_tokens"],
                          "output_budget_observed": isinstance(usage.get("completion_tokens"), int) and
                          usage["completion_tokens"] <= protocol["request_parameters"]["max_tokens"]})
    for record, answer in zip(records, answers):
        protocol_v3.require_prepared(record)
        receipt = data.verify_answer(record, answer)
        receipts.append(receipt)
        feedbacks.append({"record_id": record["record_id"],
                          "verification_digest": data.digest(receipt),
                          "content": protocol_v3.feedback(receipt)})
    if stage == "reference" and not all(row["success"] for row in receipts):
        raise ValueError("original reference fails the local verification environment")
    import numpy
    write(output / "VERIFICATIONS.json", receipts)
    write(output / "FEEDBACK.json", feedbacks)
    summary = {"stage": stage, "verified_calls": len(receipts),
               "successful_calls": sum(row["success"] for row in receipts),
               "verification_wall_seconds": time.perf_counter() - started,
               "python": sys.version, "numpy": numpy.__version__,
               "verifier_source_sha256": protocol["verifier_source_sha256"],
               "teacher_costs": costs, "full_system_cost_known": False,
               "scoring_modified": False, "teacher_outputs_trained_on": False}
    write(output / "SUMMARY.json", summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("reference", "first", "second"))
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.run, args.output, args.stage)
