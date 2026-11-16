"""Strict joins for retained repository executions, models and B-only choices."""

import copy
import hashlib
from pathlib import Path

from . import coding_sft, data, repo_execution
from .circuit_task_bindings_v2 import _bound_features, _bound_panel
from .composition_core import require
from . import study_v2 as study


def material(root):
    models, evidence = {}, {}
    parent = study.manifest(root, "parent")
    parent_digest = coding_sft.verify_model(parent, root)
    for name in study.EVALUATED:
        manifest = study.manifest(root, name)
        identity = coding_sft.verify_model(manifest, root)
        models[name] = manifest
        if name in study.TRAINED:
            plan = study.read(Path(root) / "plans" / (name + ".json"))
            training = study.read(Path(root) / "models" / name / "training.json")
            chosen = study.read(Path(root) / "plans" / (name + ".records.json"))
            require(
                training["status"] == "COMPLETE"
                and training["candidate_model_digest"] == identity
                and training["parent_model_digest"]
                == parent_digest
                == manifest["parent"]
                and training["plan_digest"] == data.digest(plan)
                and training["records_digest"]
                == data.digest(chosen)
                == plan["training_records_digest"]
                and training["training_source_ids"] == plan["train_sources"]
                and training["steps"] == plan["training"]["steps"]
                and training["owner"] == plan["training_owner"],
                "training/model/plan binding differs: " + name,
            )
            evidence[name] = {"plan": plan, "training": training}
    mixture = study.read(Path(root) / "models/integrated/mixture.json")
    require(
        mixture["status"] == "COMPLETE"
        and mixture["output"] == data.digest(models["integrated"])
        and mixture["inputs"] == [data.digest(models[n]) for n in study.ROUTED[:2]]
        and mixture["weights"] == [0.5, 0.5]
        and mixture["rank"] == 8,
        "integrated adapter binding differs",
    )
    return models, evidence


def checked_evaluation(root, name, panel_name, records, models, *, prompts=None):
    """Check raw saved outputs, request histories and every semantic attempt."""
    split = {"A": "train", "B": "selection", "C": "confirmation"}.get(panel_name)
    require(
        split is not None and all(r["split"] == split for r in records),
        "evaluation split differs",
    )
    directory = Path(root) / "evaluation" / panel_name / name
    report = study.read(directory / "EVALUATION.json")
    identity = data.digest(models[name])
    require(
        report["schema"] == "hepta.repository-evaluation.v2"
        and report["status"] == "COMPLETE"
        and report["model_digest"] == identity
        and report["tasks"] == len(records) == len(report["rows"]),
        "evaluation panel/model differs",
    )
    calls = input_tokens = output_tokens = 0
    for index, (record, row) in enumerate(zip(records, report["rows"])):
        require(
            all(
                row[k] == record[k]
                for k in ("record_id", "task_id", "source_id", "lineage_id")
            )
            and row["task_digest"] == data.digest(record)
            and row["original_input_sha256"] == data.digest(record["task"]["input"]),
            "evaluated task differs",
        )
        shown = record if prompts is None else prompts[index]
        messages = copy.deepcopy(
            shown["task"].get(
                "messages", [{"role": "user", "content": shown["task"]["input"]}]
            )
        )
        input_sha = hashlib.sha256(shown["task"]["input"].encode()).hexdigest()
        require(
            1 <= len(row["steps"]) <= report["maximum_attempts"],
            "invalid attempt count",
        )
        successes = []
        for number, step in enumerate(row["steps"]):
            require(
                step["number"] == number
                and step["receipt_sha256"]
                == data.digest(
                    {k: v for k, v in step.items() if k != "receipt_sha256"}
                ),
                "step hash differs",
            )
            request = study.read(directory / str(index) / f"request-{number}.json")
            expected = {
                "record_id": record["record_id"],
                "task": {"input": shown["task"]["input"], "messages": messages},
            }
            require(
                request == expected
                and study.read(directory / str(index) / f"step-{number}.json") == step,
                "saved request or step differs",
            )
            output, verification = step["output"], step["verification"]
            require(
                study.read(directory / str(index) / f"output-{number}.json") == output
                and output["loaded_model_digest"] == identity
                and output["input_sha256"] == input_sha,
                "actual output or input binding differs",
            )
            payload = {
                k: v
                for k, v in verification.items()
                if k not in ("success", "receipt_sha256")
            }
            require(
                data.digest(payload) == verification["receipt_sha256"]
                and verification["record_id"] == record["record_id"]
                and verification["answer_sha256"]
                == hashlib.sha256(output["answer"].encode()).hexdigest()
                and verification["input_sha256"] == input_sha
                and verification["parameters_sha256"]
                == data.digest(record["task"]["verifier"]["parameters"])
                and list(verification["verifier"]) == ["repo_patch", "1"]
                and verification["verifier_source_sha256"]
                == coding_sft.file_hash(repo_execution.__file__),
                "semantic receipt differs",
            )
            result, actual = (
                verification["result"],
                verification["result"].get("result") or {},
            )
            count = actual.get("control_count")
            success = bool(
                result.get("executed") is True
                and result.get("exit_code") == 0
                and actual.get("original_passed") is True
                and type(count) is int
                and count > 0
                and actual.get("controls_rejected") == count
            )
            require(
                type(verification["success"]) is bool
                and verification["success"] == result["success"] == success
                and step["executed"] == bool(result.get("executed")),
                "business outcome differs",
            )
            if successes:
                require(not successes[-1], "attempt continued after task success")
            successes.append(success)
            messages.extend(
                [
                    {"role": "assistant", "content": output["answer"]},
                    {"role": "tool", "content": step["feedback"]},
                ]
            )
            calls += 1
            input_tokens += output["input_tokens"]
            output_tokens += output["output_tokens"]
        require(
            row["first_attempt_success"] == successes[0]
            and row["success"] == successes[-1],
            "task outcome summary differs",
        )
    require(
        (
            report["cost"]["model_calls"],
            report["cost"]["input_tokens"],
            report["cost"]["output_tokens"],
        )
        == (calls, input_tokens, output_tokens),
        "evaluation cost differs",
    )
    require(
        report["successes"] == sum(r["success"] for r in report["rows"])
        and report["first_attempt_successes"]
        == sum(r["first_attempt_success"] for r in report["rows"]),
        "evaluation totals differ",
    )
    return report


def heldout_targets(records, evaluations, model_digests, feature_rows):
    """Diagnostic B/C labels are observed success classes, never training examples."""
    require(
        all(r["split"] in ("selection", "confirmation") for r in records),
        "held-out panel required",
    )
    bound, _ = _bound_panel(records, evaluations, model_digests, data.digest(records))
    features = _bound_features(records, feature_rows)
    rows = []
    for record in records:
        task = record["task_id"]
        successful = [slot for slot in (0, 1, 2) if bound[slot][task]["success"]]
        rows.append({**features[task], "target": successful[0] if successful else 2})
    return rows


def source_macro(rows, success_field="first_attempt_success"):
    groups = {}
    for row in rows:
        groups.setdefault(row["source_id"], []).append(bool(row[success_field]))
    require(bool(groups), "source macro needs observations")
    return sum(sum(values) / len(values) for values in groups.values()) / len(groups)


def e6_evaluation(plan, evaluations, candidate):
    rows, reports = [], [evaluations[n] for n in ("parent", "retrieval", candidate)]
    for arm, name in (
        ("parent", "parent"),
        ("retrieval", "retrieval"),
        ("candidate", candidate),
    ):
        for task in evaluations[name]["rows"]:
            first = task["steps"][0]
            rows.append(
                {
                    **{k: task[k] for k in ("task_id", "source_id", "task_digest")},
                    "arm": arm,
                    "loaded_model_digest": first["output"]["loaded_model_digest"],
                    "success": task["first_attempt_success"],
                    "output_digest": data.digest(first["output"]),
                    "first_step_receipt_sha256": first["receipt_sha256"],
                    "semantic_receipt_sha256": first["verification"]["receipt_sha256"],
                }
            )
    return {
        "status": "COMPLETE",
        "owner": plan["evaluation_owner"],
        "plan_digest": data.digest(plan),
        "started_at_ns": min(r["started_at_ns"] for r in reports),
        "completed_at_ns": max(r["completed_at_ns"] for r in reports),
        "rows": rows,
        "raw_evaluations": {
            n: data.digest(evaluations[n]) for n in ("parent", "retrieval", candidate)
        },
        "profile": "first attempt source-macro business success; retrieval uses its pinned A-only augmented prompt",
    }


def choose_e6(evaluation, parameter_change, minimum_gain=0):
    scores = {
        arm: source_macro([r for r in evaluation["rows"] if r["arm"] == arm], "success")
        for arm in ("parent", "retrieval", "candidate")
    }
    decision = (
        "ADOPTED"
        if parameter_change
        and scores["candidate"]
        > max(scores["parent"], scores["retrieval"]) + minimum_gain
        else "NO_UPDATE"
    )
    return {
        "decision": decision,
        "scores": scores,
        "parameter_change": parameter_change,
        "rule": "candidate source-macro first-attempt success strictly exceeds both frozen baselines",
    }


def binding_inventory(root):
    """Bind immutable pre-C originals; ongoing supervisor logs are outside scope."""
    root = Path(root)
    names = (
        "FREEZE.json",
        "parent.json",
        "inputs",
        "plans",
        "models",
        "base",
        "E2_COLLECTION",
        "evaluation/A",
        "evaluation/B",
        "features",
        "circuit",
        "growth",
        "cold_checks",
        "E6_BINDINGS",
        "SELECTION_STARTED.json",
    )
    files = {}
    for name in names:
        path = root / name
        if not path.exists():
            continue
        for item in [path] if path.is_file() else sorted(path.rglob("*")):
            if item.is_file():
                relative = str(item.relative_to(root))
                coding_sft.bound_file(root, relative)
                files[relative] = coding_sft.file_hash(item)
    return files


def verify_bindings(root, bindings):
    for name, expected in bindings.items():
        require(
            coding_sft.file_hash(coding_sft.bound_file(root, name)) == expected,
            "pre-confirmation bound file changed: " + name,
        )
