"""Summarize retained outcomes and tokenize authored references after run termination.

This posthoc diagnostic never calls a model or semantic verifier. Reference
lengths describe the supplied authored answers, not a minimum valid answer.
"""

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
EXPECTED_SOURCE = "fdcd9466664b6847bab4d4f547c5e8452a0eb5fe831452c9b4aa4607408aeae1"
THRESHOLD = 256


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def identity(blob):
    return {
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(blob)).encode() + b"\0" + blob
        ).hexdigest(),
    }


class Reads:
    """Bind every consumed original and check it again before producing a result."""

    def __init__(self):
        self.files = {}

    def raw(self, path):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("ordinary original file required: " + str(path))
        blob = path.read_bytes()
        item = identity(blob)
        if str(path) in self.files and self.files[str(path)] != item:
            raise ValueError("original changed while diagnosing")
        self.files[str(path)] = item
        return blob

    def json(self, path):
        return json.loads(self.raw(path))

    def confirm_unchanged(self):
        for path in list(self.files):
            self.raw(path)


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def summarize(rows, maximum):
    reasons = Counter(
        {
            reason: 0
            for reason in (
                "invalid_test_patch",
                "business_tests_failed",
                "business_tests_passed",
            )
        }
    )
    termination = Counter(
        {reason: 0 for reason in ("eos_token", "max_new_tokens", "other", "unknown")}
    )
    executed = first = within = 0
    tokens, attempt_details = [], []
    for row in rows:
        steps = row["steps"]
        if not steps or len(steps) > maximum or maximum > 2:
            raise ValueError("retained attempt count differs")
        outcomes = []
        for step in steps:
            verification = step["verification"]
            result = verification["result"] if verification else {}
            success = bool(verification and verification["success"])
            performed = bool(result.get("executed", False))
            if performed != step["executed"]:
                raise ValueError("retained execution flags disagree")
            outcomes.append(success)
            executed += performed
            reasons[result.get("reason", "not_verified")] += 1
            output = step["output"]
            finish = output.get("finish_reason", "unknown")
            termination[finish] += 1
            if output.get("hit_output_limit", False) != (finish == "max_new_tokens"):
                raise ValueError("retained cap and termination flags disagree")
            if output.get("eos_seen", False) != (finish == "eos_token"):
                raise ValueError("retained EOS and termination flags disagree")
            tokens.append(output["output_tokens"])
        if row["first_attempt_success"] != outcomes[0] or row["success"] != any(
            outcomes
        ):
            raise ValueError(
                "retained task success disagrees with semantic observations"
            )
        first += outcomes[0]
        within += any(outcomes[:2])
        attempt_details.append(
            {
                "task_id": row["task_id"],
                "source_id": row["source_id"],
                "first_success": outcomes[0],
                "within_observed_two_success": any(outcomes[:2]),
                "attempts": len(steps),
                "executed_attempts": sum(s["executed"] for s in steps),
            }
        )
    return {
        "tasks": len(rows),
        "maximum_attempts": maximum,
        "model_calls_previously_recorded": len(tokens),
        "first_attempt_successes": first,
        "within_observed_two_successes": within,
        "first_attempt_success_rate": first / len(rows) if rows else None,
        "within_observed_two_success_rate": within / len(rows) if rows else None,
        "second_attempt_available": maximum == 2,
        "executed_attempts": executed,
        "reason_counts": dict(reasons),
        "termination_counts": dict(termination),
        "output_tokens": {
            "total": sum(tokens),
            "minimum": min(tokens) if tokens else None,
            "maximum": max(tokens) if tokens else None,
        },
        "task_rows": attempt_details,
    }


def evaluation_summaries(reads, root):
    panels = {}
    for panel in ("A", "B", "C"):
        arms = {}
        for path in sorted((root / "evaluation" / panel).glob("*/EVALUATION.json")):
            report = reads.json(path)
            if (
                report["schema"] != "hepta.repository-evaluation.v2"
                or report["status"] != "COMPLETE"
            ):
                raise ValueError("unsupported evaluation receipt")
            summary = summarize(report["rows"], report["maximum_attempts"])
            if (
                summary["tasks"] != report["tasks"]
                or summary["first_attempt_successes"]
                != report["first_attempt_successes"]
                or summary["within_observed_two_successes"] != report["successes"]
            ):
                raise ValueError("evaluation aggregate differs from retained rows")
            summary["model_digest"] = report["model_digest"]
            arms[path.parent.name] = summary
        panels[panel] = arms
    return panels


def collection_summary(reads, root):
    directory = root / "E2_COLLECTION"
    if not (directory / "COLLECTION.json").exists():
        return {"status": "MISSING", "cohorts": {}}
    collection = reads.json(directory / "COLLECTION.json")
    cohorts = {}
    for name, maximum in (("shadow", 1), ("controlled", 2)):
        paths = sorted((directory / name).glob("*/RESULT.json"))
        summary = summarize([reads.json(p) for p in paths], maximum)
        declared = collection["cohorts"][name]
        if (
            summary["tasks"] != declared["records"]
            or summary["model_calls_previously_recorded"] != declared["model_calls"]
            or summary["executed_attempts"] != declared["executed_attempts"]
            or summary["within_observed_two_successes"] != declared["successful_tasks"]
        ):
            raise ValueError("E2 collection aggregate differs from retained attempts")
        cohorts[name] = summary
    return {
        "status": "COMPLETE",
        "cohorts": cohorts,
        "independent_sample_increment": 0,
        "student_policy": collection["student_policy"],
    }


def reference_lengths(reads, root, source, frozen):
    parent = reads.json(root / "parent.json")
    runtime = parent["runtime"]
    if runtime["message_protocol"] != "native_chat_v2":
        raise ValueError("actual native message protocol required")
    base = Path(runtime["base_directory"])
    if base.is_absolute() or ".." in base.parts:
        raise ValueError("base must stay in original run")
    bound = {}
    for item in parent["files"]:
        relative = Path(item["path"])
        if relative.parent == base and relative.suffix != ".safetensors":
            blob = reads.raw(root / relative)
            if (
                len(blob) != item["bytes"]
                or hashlib.sha256(blob).hexdigest() != item["sha256"]
            ):
                raise ValueError(
                    "native tokenizer material differs from model manifest"
                )
            bound[str(relative)] = reads.files[str(root / relative)]
    if not {
        str(base / name)
        for name in ("tokenizer.json", "tokenizer_config.json", "config.json")
    } <= set(bound):
        raise ValueError("required native tokenizer files are not bound")
    sys.path.insert(0, str(source / "scripts"))
    protocol = importlib.import_module("cell_experiments.chat_protocol")
    if not Path(protocol.__file__).resolve().is_relative_to(source.resolve()):
        raise ValueError("chat serializer imported from outside frozen source")
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        root / base, local_files_only=True, trust_remote_code=False
    )
    if (
        protocol.template_digest(tokenizer.chat_template)
        != runtime["chat_template_sha256"]
    ):
        raise ValueError("native template differs from frozen inference")
    panels = {"A": [], "B": [], "C": []}
    for name in ("open", "confirmation"):
        relative = "inputs/" + name + "/records.jsonl"
        blob = reads.raw(root / relative)
        if hashlib.sha256(blob).hexdigest() != frozen["input_files"][relative]:
            raise ValueError("authored reference input differs from frozen original")
        for line in blob.splitlines():
            record = json.loads(line)
            panel = {"train": "A", "selection": "B", "confirmation": "C"}[
                record["split"]
            ]
            # Tokenize text only: do not enter an SFT builder or change split or
            # training authorization for held-out B/C reference records.
            messages = protocol.inference_messages(
                record["task"]["input"], record["task"].get("messages")
            )
            prefix = protocol.render_prompt(
                tokenizer, record["task"]["input"], messages
            )
            wire = protocol._wire(messages)
            complete = tokenizer.apply_chat_template(
                [*wire, {"role": "assistant", "content": record["final_answer"]}],
                tokenize=False,
                add_generation_prompt=False,
            )
            if not complete.startswith(prefix):
                raise ValueError("native reference boundary is not prefix stable")
            continuation = tokenizer.encode(
                complete[len(prefix) :], add_special_tokens=False
            )
            panels[panel].append(
                {
                    "task_id": record["task_id"],
                    "source_id": record["source_id"],
                    "answer_sha256": hashlib.sha256(
                        record["final_answer"].encode()
                    ).hexdigest(),
                    "answer_text_tokens": len(
                        tokenizer.encode(
                            record["final_answer"], add_special_tokens=False
                        )
                    ),
                    "native_target_tokens": len(continuation),
                    "prefix_tokens": len(
                        tokenizer.encode(prefix, add_special_tokens=False)
                    ),
                }
            )
    result = {}
    for panel, rows in panels.items():
        aggregate = {}
        for field in ("answer_text_tokens", "native_target_tokens"):
            values = [row[field] for row in rows]
            aggregate[field] = {
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
                "over_256": sum(value > THRESHOLD for value in values),
            }
        result[panel] = {"tasks": len(rows), "summary": aggregate, "rows": rows}
    return {
        "panels": result,
        "threshold": THRESHOLD,
        "actual_max_new_tokens": runtime["max_new_tokens"],
        "tokenizer_files": bound,
        "chat_template_sha256": runtime["chat_template_sha256"],
        "native_target_includes_template_continuation": True,
        "target_truncation": False,
        "minimal_valid_answer_length_bound": False,
        "interpretation": "Posthoc lengths of the supplied authored references only; other valid tests can be shorter or longer.",
    }


def diagnose(options):
    root, logs, source, output = [
        Path(p).absolute()
        for p in (options.root, options.logs, options.source, options.output)
    ]
    if any(
        output == parent or output.is_relative_to(parent)
        for parent in (root, logs, source)
    ):
        raise ValueError("diagnostics must be outside all original trees")
    reads = Reads()
    terminal = reads.json(logs / "RESULT.json")
    if (
        terminal.get("status") not in ("COMPLETE_DEVELOPMENT", "INCOMPLETE")
        or terminal.get("source_digest") != EXPECTED_SOURCE
    ):
        raise ValueError("bound supervisor terminal receipt required")
    frozen = reads.json(root / "FREEZE.json")
    package = {
        p.name: hashlib.sha256(reads.raw(p)).hexdigest()
        for p in sorted((source / "scripts/cell_experiments").glob("*.py"))
    }
    if (
        len(package) != 44
        or package != frozen["source_inventory"]
        or hashlib.sha256(canonical(package)).hexdigest() != EXPECTED_SOURCE
    ):
        raise ValueError("frozen source changed")
    output.mkdir(parents=True, exist_ok=False)
    started, wall, cpu = time.time_ns(), time.perf_counter(), time.process_time()
    script = identity(Path(__file__).read_bytes())
    write_new(
        output / "COMMAND.json",
        {
            "python": sys.executable,
            "argv": sys.argv,
            "script": script,
            "created_at_ns": started,
            "operator_must_observe_actual_job_terminal": True,
        },
    )
    try:
        evaluations = evaluation_summaries(reads, root)
        collection = collection_summary(reads, root)
        lengths = reference_lengths(reads, root, source, frozen)
        reads.confirm_unchanged()
        result = {
            "schema": "hepta.repository-study.posthoc-diagnostics.v2",
            "status": "COMPLETE",
            "started_at_ns": started,
            "completed_at_ns": time.time_ns(),
            "source_digest": EXPECTED_SOURCE,
            "terminal_status": terminal["status"],
            "evaluations": evaluations,
            "E2_COLLECTION": collection,
            "authored_reference_lengths": lengths,
            "consumed_originals": reads.files,
            "consumed_originals_unchanged": True,
            "posthoc": True,
            "new_model_calls": 0,
            "new_semantic_verifier_calls": 0,
            "new_training_updates": 0,
            "new_independent_samples": 0,
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu,
        }
        write_new(output / "DIAGNOSTICS.json", result)
        return {
            "status": "COMPLETE",
            "path": str(output / "DIAGNOSTICS.json"),
            "sha256": hashlib.sha256(
                (output / "DIAGNOSTICS.json").read_bytes()
            ).hexdigest(),
            "evaluation_arms": {
                panel: len(arms) for panel, arms in evaluations.items()
            },
            "new_model_calls": 0,
            "new_semantic_verifier_calls": 0,
        }
    except Exception as failure:
        write_new(
            output / "FAILED.json",
            {"error": repr(failure), "partial_artifacts_retained": True},
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "logs", "source", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(diagnose(parser.parse_args()), sort_keys=True))
