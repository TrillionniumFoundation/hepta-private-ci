"""Cold-score the fixed retention panel for a completed A training operation before prospective dispatch."""

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import (
    adoption,
    coding_sft,
    data,
    paired_cold,
    paired_freeze,
    paired_source,
    paired_source_fit,
)

require = adoption.require
POLICY = (
    "Require at least one demonstrated old item and retain every passing parent item."
)


def inputs(root, operation):
    completed = adoption.read_json(operation / "COMPLETED.json")
    snapshot = paired_source.read_bound(
        operation / "FROZEN.json", completed["freeze_sha256"]
    )
    require(
        snapshot["schema"] == paired_freeze.FREEZE_SCHEMA
        and data.digest(snapshot["candidate"]) == completed["candidate_sha256"]
        and data.digest(snapshot["parent"]) == completed["parent_sha256"],
        "source completion and frozen pair disagree",
    )
    paired_cold.checked_models(snapshot["parent"], snapshot["candidate"])
    paired_cold.checked_panels(
        {"retention": snapshot["retention"]}, snapshot["parent"]["runtime"]
    )
    a = paired_source.read_bound(root / "failure.json", completed["failure_sha256"])
    return (
        completed,
        snapshot,
        [("known_A", a), *(("retention", r) for r in snapshot["retention"])],
    )


def run_arm(root, operation, arm, out):
    _, snapshot, records = inputs(root, operation)
    model = snapshot[arm]
    loader = paired_cold.loader_for(model)
    p = loader.load_predictor(model, root)
    rows = []
    try:
        for panel, record in records:
            visible = {"task": paired_cold.visible_task(record)}
            raw = p.predict(visible, retain_encoding=True) if loader is coding_sft else p.predict(visible)
            rows.append(
                {
                    "panel": panel,
                    "record_sha256": data.digest(record),
                    "prediction": raw,
                    "outcome": data.verify_answer(record, raw["answer"]),
                }
            )
    finally:
        p.close()
    paired_freeze.publish(
        {"arm": arm, "pid": os.getpid(), "model": data.digest(model), "rows": rows}, out
    )


def read_arm(path, arm, snapshot, records, root):
    result = adoption.read_json(path)
    model = snapshot[arm]
    require(
        result["arm"] == arm
        and result["model"] == paired_cold.verify_materials(model, root)
        and len(result["rows"]) == len(records),
        "cold arm identity or coverage differs",
    )
    loader = paired_cold.loader_for(model)
    if loader is not coding_sft:
        from . import paired_router_source
        for row, (panel, record) in zip(result["rows"], records, strict=True):
            pred = row["prediction"]
            loader.check_prediction(model, pred, paired_cold.visible_task(record))
            for node in pred["circuit_trace"]["nodes"]:
                paired_router_source.inspect_node(model["models"][node["cell_id"]], node, root)
                require(node["output"]["pid"] == result["pid"], "Circuit node belongs to another process")
            require(row["panel"] == panel and row["record_sha256"] == data.digest(record)
                    and pred["loaded_model_digest"] == result["model"]
                    and data.digest(row["outcome"]) == data.digest(data.verify_answer(record, pred["answer"])),
                    "Circuit cold row, model or score differs")
        return result
    tok = paired_cold.frozen_tokenizer(model, root)
    protocol = model["runtime"].get("message_protocol", "legacy_v1")
    for row, (panel, record) in zip(result["rows"], records, strict=True):
        raw = row["prediction"]
        prompt = coding_sft.prompt_text(
            record["task"]["input"], tok, protocol, record["task"].get("messages")
        )
        require(
            row["panel"] == panel
            and row["record_sha256"] == data.digest(record)
            and raw["pid"] == result["pid"]
            and raw["loaded_model_digest"] == result["model"]
            and raw["input_ids"] == tok.encode(prompt, add_special_tokens=False)
            and raw["answer"] == tok.decode(raw["output_ids"], skip_special_tokens=True)
            and raw["input_tokens"] == len(raw["input_ids"])
            and raw["output_tokens"] == len(raw["output_ids"])
            and 0 < raw["input_tokens"] <= model["runtime"]["max_input_tokens"]
            and 0 < raw["output_tokens"] <= model["runtime"]["max_new_tokens"]
            and data.digest(row["outcome"])
            == data.digest(data.verify_answer(record, raw["answer"])),
            "cold output, tokens, or reproducible score differs",
        )
    return result


def gate(root, operation):
    root, operation = Path(root), Path(operation)
    completed, snapshot, records = inputs(root, operation)
    gate_dir = operation / "cold-retention"
    gate_dir.mkdir(mode=0o700, exist_ok=True)
    env = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    with (gate_dir / "lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        arms = {}
        for arm in paired_cold.ARMS:
            path = gate_dir / (arm + ".json")
            if not path.exists():
                with tempfile.TemporaryDirectory(dir=gate_dir) as tmp:
                    staged = Path(tmp) / "arm.json"
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            __spec__.name
                            if __spec__
                            else "cell_experiments.paired_source_gate",
                            "arm",
                            str(root),
                            str(operation),
                            arm,
                            str(staged),
                        ],
                        check=True,
                        timeout=snapshot["timeout_seconds"],
                        env=env,
                    )
                    read_arm(staged, arm, snapshot, records, root)
                    os.link(staged, path)
                    paired_source.sync_directory(gate_dir)
            arms[arm] = read_arm(path, arm, snapshot, records, root)
        comparisons = []
        for i, (panel, record) in enumerate(records):
            p, c = (arms[key]["rows"][i] for key in paired_cold.ARMS)
            require(
                p["prediction"]["input_ids"] == c["prediction"]["input_ids"],
                "parent and child inputs differ",
            )
            comparisons.append(
                {
                    "panel": panel,
                    "record_sha256": data.digest(record),
                    "parent": p["outcome"]["success"],
                    "candidate": c["outcome"]["success"],
                }
            )
        old = [r for r in comparisons if r["panel"] == "retention" and r["parent"]]
        if completed.get("update_scope") and not (
            comparisons[0]["parent"] is False and comparisons[0]["candidate"] is True
        ):
            decision = "no_update_no_cold_source_gain"
        elif not old:
            decision = "insufficient_retention_baseline"
        elif all(r["candidate"] for r in old):
            decision = "eligible_for_prospective_evaluation"
        else:
            decision = "no_update_retention_regressed"
        result = {
            "schema": "hepta.paired-learning.source-retention.v1",
            "scope": completed["scope"],
            "freeze_sha256": completed["freeze_sha256"],
            "candidate_sha256": completed["candidate_sha256"],
            "parent_sha256": completed["parent_sha256"],
            "source_completion_sha256": data.digest(completed),
            "policy": POLICY,
            "gate_source_sha256": coding_sft.file_hash(__file__),
            "decision": decision,
            "cold_receipts": {arm: data.digest(r) for arm, r in arms.items()},
            "comparisons": comparisons,
            "prospective_records_read": 0,
            "promotion_authorized": False,
            "payment_authorized": False,
        }
        paired_source_fit.publish_value(operation / "RETENTION.json", result)
        return result


def main():
    os.umask(0o077)
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        # Native verifier capabilities are transferred only to the original A trainer.
        argv = sys.argv[2:]
        result = subprocess.run(
            [sys.executable, "-m", "cell_experiments.paired_source_train", *argv],
            pass_fds=(3, 4),
            check=True,
            stdout=subprocess.PIPE,
        )
        os.close(3)
        os.close(4)
        from json import loads

        completed = loads(result.stdout)
        root = Path(argv[0])
        key = data.digest(
            [
                completed[k]
                for k in ("study_sha256", "failure_sha256", "correction_sha256")
            ]
        )
        out = gate(root, root / "paired-training" / key)
    else:
        p = argparse.ArgumentParser(
            description=__doc__
            + " Use train with the paired_source_train arguments, or score MATERIALS OPERATION."
        )
        sub = p.add_subparsers(dest="op", required=True)
        for name in ("arm", "score"):
            a = sub.add_parser(name)
            a.add_argument("root", type=Path)
            a.add_argument("operation", type=Path)
            if name == "arm":
                a.add_argument("arm", choices=paired_cold.ARMS)
                a.add_argument("out", type=Path)
        a = p.parse_args()
        if a.op == "arm":
            run_arm(a.root, a.operation, a.arm, a.out)
            return
        out = gate(a.root, a.operation)
    print(data.canonical(out).decode())


if __name__ == "__main__":
    main()
