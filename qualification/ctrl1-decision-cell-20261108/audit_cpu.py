"""Independently reconcile archived CTRL-1 CPU allowance evidence.

Run with the frozen experiment sources checked out:
  python3 qualification/ctrl1-decision-cell-20261108/audit_cpu.py RUN_DIRECTORY
Add --recompute-results to replay every available policy's exact evaluation.
Embedded execution paths are provenance only; reads stay inside the archive.
Hashes prove retained-file consistency, not independent execution attestation.
This helper does not train, select checkpoints, or grant promotion authority.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from fractions import Fraction
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import signal
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

# Standalone imports require the repository path bootstrap above.
from ndu_ctrl1.evaluation import METRICS, evaluate  # noqa: E402
from ndu_ctrl1.learning import FEATURES, Learner, _sha  # noqa: E402
from ndu_ctrl1.model import ACTIONS, Scenario, State, legal_actions  # noqa: E402
from ndu_ctrl1.policies import Controller  # noqa: E402
from ndu_ctrl1.run import (  # noqa: E402
    digest,
    examples_for_training,
    profiles,
    scenarios,
    source_manifest,
)

MAX_BYTES, MAX_FILES = 2_000_000, 1024
METHODS = {"actor_critic": "fitted_actor_critic", "distillation": "distilled"}
COUNTS = set(
    "actor_updates critic_updates model_calls outcome_branches critic_predictions legal_mask_calls known_boundary_values future_base_charges".split()
)
RECEIPT_FIELDS = set(
    "schema plan_sha256 method seed profile_sha256 examples_sha256 sources_sha256 hard_worker_cpu_seconds worker worker_exit_code termination worker_user_cpu_seconds worker_system_cpu_seconds worker_inclusive_cpu_seconds parent_cpu_seconds wall_seconds source_drift parent_error checkpoint_validation limits_validated candidate_status checkpoint_path retained_record_path initial_parameters_sha256 parameters_sha256 actual_actor_updates retained_actor_updates completed_epochs unobserved_tail".split()
)
ROW_FIELDS = set(
    "attempt_id profile_id training_seed cpu_cap_seconds method scenario_id candidate_status worker_cpu_seconds retained_epochs parameters_sha256".split()
)
RESULT_FIELDS = {
    *METRICS,
    "value",
    "actions",
    "policy_gap",
    "oracle_value",
    "net_terminal_utility",
    "policy_states",
    "offline_oracle",
    "offline_policy_evaluation",
    "evaluation",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, expected, label):
    require(
        isinstance(value, dict) and set(value) == set(expected),
        f"{label}: unknown or missing fields",
    )


def number(value, lower=0, upper=math.inf, integer=False):
    require(
        type(value) in ((int,) if integer else (int, float))
        and math.isfinite(value)
        and lower <= value <= upper,
        "Invalid bounded evidence number",
    )
    return value


def same(actual, expected, label):
    require(
        digest(actual) == digest(expected), f"{label}: original-file binding mismatch"
    )


def close(actual, expected, label):
    require(
        math.isclose(
            number(actual, -math.inf),
            number(expected, -math.inf),
            rel_tol=1e-10,
            abs_tol=1e-10,
        ),
        f"{label}: numerical reconciliation failed",
    )


def decode(raw):
    def reject(value):
        raise ValueError(f"Nonfinite or overlong JSON number: {value[:32]}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=reject,
        parse_int=lambda value: int(value) if len(value) <= 24 else reject(value),
        parse_float=lambda value: number(float(value), -math.inf),
    )


def read(path):
    require(
        not path.is_symlink() and path.stat().st_size <= MAX_BYTES,
        "Invalid JSON artifact size or symlink",
    )
    with path.open("rb") as handle:
        content = handle.read(MAX_BYTES + 1)
    require(len(content) <= MAX_BYTES, "JSON artifact exceeds size bound")
    return decode(content)


def lines(path, count):
    result = []
    with path.open("rb") as handle:
        for _ in range(count + 1):
            raw = handle.readline(64_001)
            if not raw:
                break
            require(
                len(raw) <= 64_000 and raw.endswith(b"\n"),
                "Invalid bounded JSONL record",
            )
            result.append(decode(raw))
    require(len(result) == count, "JSONL denominator differs from the frozen plan")
    return result


def inventory(directory):
    manifest = read(directory / "ARTIFACTS.json")
    fields(manifest, {"plan_sha256", "status", "files"}, "Artifact manifest")
    require(
        isinstance(manifest["files"], dict) and len(manifest["files"]) < MAX_FILES,
        "Unbounded inventory",
    )
    actual, pending, seen = set(), [directory], 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                seen += 1
                require(
                    seen <= MAX_FILES and not entry.is_symlink(),
                    "Unbounded inventory or artifact symlink",
                )
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    require(
                        len(path.relative_to(directory).parts) <= 3,
                        "Unexpected artifact directory depth",
                    )
                    pending.append(path)
                else:
                    require(
                        entry.is_file(follow_symlinks=False),
                        "Unsupported artifact file type",
                    )
                    actual.add(str(path.relative_to(directory)))
    require(
        actual == set(manifest["files"]) | {"ARTIFACTS.json"},
        "Missing or undeclared artifacts",
    )
    total = 0
    for relative, declared in manifest["files"].items():
        part = Path(relative)
        require(
            not part.is_absolute() and ".." not in part.parts and str(part) == relative,
            "Unsafe inventory path",
        )
        fields(declared, {"bytes", "sha256"}, "Artifact identity")
        total += number(declared["bytes"], upper=MAX_BYTES, integer=True)
        require(total <= 32_000_000, "Artifact archive exceeds total size bound")
        with (directory / relative).open("rb") as handle:
            content = handle.read(MAX_BYTES + 1)
        require(
            len(content) == declared["bytes"]
            and hashlib.sha256(content).hexdigest() == declared["sha256"],
            f"Artifact content differs from inventory: {relative}",
        )
    return manifest, actual


def rational(value):
    require(isinstance(value, str) and len(value) <= 64, "Invalid rational encoding")
    result = Fraction(value)
    require(str(result) == value, "Noncanonical rational encoding")
    return result


def public_examples(roster, profile):
    fields(roster, {"costs", "examples"}, "Shared roster")
    require(
        isinstance(roster["examples"], list) and len(roster["examples"]) == 128,
        "Unexpected training denominator",
    )
    examples = []
    for row in roster["examples"]:
        fields(row, {"scenario", "public_post_base_state"}, "Training example")
        scenario, state = dict(row["scenario"]), dict(row["public_post_base_state"])
        for key in ("prior", "signal_accuracy", "repair_success"):
            scenario[key] = rational(scenario[key])
        state["belief"] = rational(state["belief"])
        examples.append((Scenario(**scenario), State(**state)))
    expected, costs = examples_for_training(profile)
    same(_sha(examples), _sha(expected), "Frozen train-only public roster")
    require(len(roster["costs"]) == len(costs), "Missing shared roster cost receipts")
    for retained, generated in zip(roster["costs"], costs):
        fields(retained, set(generated), "Shared roster costs")
        for key in ("wall_seconds", "cpu_seconds"):
            number(retained[key])
        same(
            {
                k: v
                for k, v in retained.items()
                if k not in ("wall_seconds", "cpu_seconds")
            },
            {
                k: v
                for k, v in generated.items()
                if k not in ("wall_seconds", "cpu_seconds")
            },
            "Shared roster work",
        )
    return examples


def termination(exit_code, worker):
    """Reconstruct classification independently; SIGKILL never proves CPU expiry."""
    number(exit_code, -127, 255, integer=True)
    status, name, allowed = worker["status"], None, False
    if exit_code < 0:
        value = -exit_code
        try:
            name = signal.Signals(value).name
        except ValueError:
            name = f"signal_{value}"
        kind = {
            signal.SIGXCPU: "CpuBudgetSignal",
            signal.SIGKILL: "AmbiguousSigkill",
            signal.SIGALRM: "WallAlarmSignal",
        }.get(value, "UnexpectedSignal")
        allowed = value == signal.SIGXCPU and status != "Failed"
    elif exit_code == 0 and status in ("Completed", "CpuBudgetStop"):
        kind, allowed = (
            ("Completed" if status == "Completed" else "CooperativeCpuBudgetStop"),
            True,
        )
    else:
        kind = "ProcessFailure" if exit_code else "MissingOrInvalidCompletionReceipt"
    if status == "Failed":
        kind, allowed = "WorkerReportedFailure", False
    return {
        "kind": kind,
        "exit_code": exit_code,
        "signal": name,
        "allows_retained_checkpoint": allowed,
    }


def checkpoint(record, plan, examples):
    learner = Learner.from_record(record)
    training = learner.training
    for key in ("seed", "examples", "examples_sha256", "profile_sha256"):
        same(training[key], plan[key], f"Checkpoint {key}")
    same(training["epochs"], plan["max_epochs"], "Checkpoint epoch ceiling")
    same(
        training["cpu_budget_seconds"],
        plan["soft_training_cpu_seconds"],
        "Checkpoint CPU allowance",
    )
    same(asdict(learner.profile), plan["profile"], "Checkpoint utility profile")
    same(learner.method, METHODS[plan["method"]], "Checkpoint training method")
    epochs = number(
        training["completed_epochs"], upper=plan["max_epochs"], integer=True
    )
    retained = number(training["retained_actor_updates"], upper=262144, integer=True)
    require(retained == epochs * len(examples), "Retained epoch is partial")
    fields(training["counts"], COUNTS, "Training counters")
    for value in training["counts"].values():
        number(value, upper=10**10, integer=True)
    require(
        retained
        <= training["counts"]["actor_updates"]
        <= plan["max_epochs"] * len(examples),
        "Actual update count loses retained work",
    )
    rng = random.Random(plan["seed"])
    initial = {
        "actor": [[rng.uniform(-0.02, 0.02) for _ in FEATURES] for _ in ACTIONS],
        "critic": [0.0] * len(FEATURES),
    }
    same(training["initial_parameters_sha256"], _sha(initial), "Shared initialization")
    labels = training["teacher_labels"]
    require(
        isinstance(labels, list) and len(labels) <= len(examples),
        "Unbounded teacher labels",
    )
    for index, label in enumerate(labels):
        fields(
            label,
            {"example", "action", "model_calls", "expanded_nodes"},
            "Teacher label",
        )
        require(
            type(label["example"]) is int
            and label["example"] == index
            and label["action"] in legal_actions(*examples[index]),
            "Teacher label is not a legal training example",
        )
        for key in ("model_calls", "expanded_nodes"):
            number(label[key], upper=96, integer=True)
    complete = plan["method"] == "actor_critic" or len(labels) == len(examples)
    require(
        training["teacher_complete"] is complete and (not retained or complete),
        "Incomplete teacher retained as a candidate",
    )
    require(
        plan["method"] != "actor_critic" or not labels,
        "Actor-critic has undeclared teacher labels",
    )
    if "actual_actor_updates" in training:
        same(
            training["actual_actor_updates"],
            training["counts"]["actor_updates"],
            "Final training work",
        )
        require(
            training["candidate_available"] is (retained > 0),
            "Checkpoint candidate status disagrees with complete epochs",
        )
        for field in ("model_calls", "expanded_nodes"):
            same(
                training[f"teacher_{field}"],
                sum(row[field] for row in labels),
                "Teacher work total",
            )
        for field in ("elapsed_cpu_seconds", "elapsed_wall_seconds"):
            number(training[field])
    return learner


def audit_worker(directory, key, joined, profile_id, profile, examples, sources):
    base = directory / "workers" / key
    receipt, plan = read(base / "RECEIPT.json"), read(base / "PLAN.json")
    fields(receipt, RECEIPT_FIELDS, "Worker receipt")
    fields(joined, RECEIPT_FIELDS | {"id", "profile_id"}, "Joined worker receipt")
    same(
        {k: v for k, v in joined.items() if k not in ("id", "profile_id")},
        receipt,
        "Original worker receipt",
    )
    same(joined["id"], key, "Attempt ID")
    same(joined["profile_id"], profile_id, "Attempt profile ID")
    method, seed, cap = (
        receipt["method"],
        receipt["seed"],
        receipt["hard_worker_cpu_seconds"],
    )
    expected_plan = {
        "schema": "hepta.ctrl1.cpu-allowance.v1",
        "method": method,
        "seed": seed,
        "hard_worker_cpu_seconds": cap,
        "soft_training_cpu_seconds": 0.9 * cap,
        "wall_fuse_seconds": max(5, 4 * cap),
        "max_epochs": 512,
        "profile": asdict(profile),
        "profile_sha256": profile_id,
        "examples": len(examples),
        "examples_sha256": _sha(examples),
        "sources": sources,
        "sources_sha256": digest(sources),
        "selection": "last complete epoch; no development/test access",
        "cache": "transition and legal-action LRUs cleared inside each worker",
    }
    same(plan, expected_plan, "Original worker plan")
    require(
        receipt["schema"] == "hepta.ctrl1.cpu-attempt.v1",
        "Unknown worker receipt schema",
    )
    same(receipt["plan_sha256"], digest(plan), "Worker plan hash")
    for field in ("profile_sha256", "examples_sha256", "sources_sha256"):
        same(receipt[field], plan[field], f"Worker {field}")
    worker = (
        read(base / "WORKER.json")
        if (base / "WORKER.json").exists()
        else {"status": "MissingReceipt"}
    )
    same(receipt["worker"], worker, "Original worker completion")
    if worker["status"] in ("Completed", "CpuBudgetStop"):
        fields(
            worker,
            {
                "status",
                "budget_stop_stage",
                "actual_actor_updates",
                "actual_counts",
                "teacher_complete",
                "teacher_model_calls",
                "teacher_expanded_nodes",
            },
            "Worker completion",
        )
    elif worker["status"] == "Failed":
        fields(worker, {"status", "error_type", "error"}, "Worker failure")
    else:
        same(worker, {"status": "MissingReceipt"}, "Absent worker completion")
        require(
            not (base / "WORKER.json").exists(), "Fabricated missing completion receipt"
        )
    observed = termination(receipt["worker_exit_code"], worker)
    same(receipt["termination"], observed, "Actual termination classification")
    for field in (
        "worker_user_cpu_seconds",
        "worker_system_cpu_seconds",
        "worker_inclusive_cpu_seconds",
        "parent_cpu_seconds",
        "wall_seconds",
    ):
        number(receipt[field])
    close(
        receipt["worker_inclusive_cpu_seconds"],
        receipt["worker_user_cpu_seconds"] + receipt["worker_system_cpu_seconds"],
        "wait4 inclusive CPU",
    )
    limits = read(base / "LIMITS.json") if (base / "LIMITS.json").exists() else None
    limits_valid = digest(limits) == digest(
        {"cpu": [cap, cap], "wall_alarm_seconds": plan["wall_fuse_seconds"]}
    )
    require(
        receipt["limits_validated"] is limits_valid,
        "CPU limit validation does not match original limits",
    )
    require(
        type(receipt["source_drift"]) is bool
        and type(receipt["unobserved_tail"]) is bool,
        "Invalid worker observation flags",
    )
    require(
        receipt["unobserved_tail"] is (receipt["actual_actor_updates"] is None),
        "Unknown work tail is concealed",
    )
    if receipt["parent_error"] is not None:
        fields(receipt["parent_error"], {"error_type", "message"}, "Parent error")
    learner, record = None, None
    if (base / "CHECKPOINT.json").exists():
        record = read(base / "CHECKPOINT.json")
        if receipt["checkpoint_validation"] == "valid":
            learner = checkpoint(record, plan, examples)
        else:
            require(
                receipt["checkpoint_validation"] == "invalid"
                and receipt["parent_error"] is not None,
                "Unexplained rejected checkpoint",
            )
            record = None
    else:
        require(
            receipt["checkpoint_validation"] in ("missing", "invalid"),
            "Missing checkpoint called valid",
        )
    training = learner.training if learner else {}
    for field, value in (
        ("initial_parameters_sha256", training.get("initial_parameters_sha256")),
        ("parameters_sha256", record.get("parameters_sha256") if record else None),
        ("retained_actor_updates", training.get("retained_actor_updates", 0)),
        ("completed_epochs", training.get("completed_epochs", 0)),
        ("actual_actor_updates", worker.get("actual_actor_updates")),
    ):
        same(receipt[field], value, f"Worker retained {field}")
    if worker["status"] in ("Completed", "CpuBudgetStop"):
        require(
            learner is not None and "budget_stop_stage" in training,
            "Completion lacks its final checkpoint",
        )
        for field, source in (
            ("actual_actor_updates", "actual_actor_updates"),
            ("actual_counts", "counts"),
            ("teacher_complete", "teacher_complete"),
            ("teacher_model_calls", "teacher_model_calls"),
            ("teacher_expanded_nodes", "teacher_expanded_nodes"),
            ("budget_stop_stage", "budget_stop_stage"),
        ):
            same(worker[field], training[source], "Completion work/checkpoint join")
        if worker["status"] == "Completed":
            require(
                training["completed_epochs"] == 512
                and training["budget_stop_stage"] is None,
                "Unfinished training called Completed",
            )
        else:
            require(
                training["budget_stop_stage"]
                in (
                    "teacher",
                    "epoch_boundary",
                    "partial_epoch",
                    "epoch_over_allowance",
                ),
                "Unexplained cooperative stop",
            )
    available = bool(
        learner
        and training["retained_actor_updates"] > 0
        and not receipt["source_drift"]
        and receipt["parent_error"] is None
        and limits_valid
        and observed["allows_retained_checkpoint"]
    )
    same(
        receipt["candidate_status"],
        "Available" if available else "NoCandidate",
        "Candidate eligibility",
    )
    original_root = None
    for field, exists in (
        ("checkpoint_path", available),
        ("retained_record_path", (base / "CHECKPOINT.json").exists()),
    ):
        value = receipt[field]
        require(
            (value is not None) is bool(exists),
            "Checkpoint path presence disagrees with original",
        )
        if exists:
            path = Path(value)
            require(
                path.is_absolute()
                and ".." not in path.parts
                and str(path) == value
                and path.parts[-3:] == ("workers", key, "CHECKPOINT.json"),
                "Checkpoint provenance path is unsafe or belongs to another attempt",
            )
            if original_root is not None:
                same(str(path.parents[2]), original_root, "Original execution root")
            original_root = str(path.parents[2])
    return receipt, learner if available else None, original_root


def audit(directory, recompute_results=False):
    require(not directory.is_symlink(), "Archive root is a symlink")
    directory = directory.resolve(strict=True)
    manifest, retained_files = inventory(directory)
    plan, report = read(directory / "PLAN.json"), read(directory / "REPORT.json")
    fields(
        plan,
        {
            "schema",
            "sources",
            "profiles",
            "training_seeds",
            "cpu_caps_seconds",
            "max_epochs",
            "methods",
            "confirmation",
            "expected_workers",
            "expected_comparison_rows",
            "selection",
            "scope",
        },
        "Campaign plan",
    )
    require(plan["schema"] == "hepta.ctrl1.cpu-campaign.v1", "Unknown campaign schema")
    same(plan["sources"], source_manifest(), "Current frozen sources")
    same(manifest["plan_sha256"], digest(plan), "Inventory plan")
    same(report["plan_sha256"], digest(plan), "Report plan")
    same(manifest["status"], report["status"], "Manifest completion status")
    expected_profiles = {digest(asdict(profile)): profile for profile in profiles()}
    expected_scenarios = dict(scenarios("confirmation"))
    same(
        plan["profiles"],
        [
            {"digest": key, **asdict(profile)}
            for key, profile in expected_profiles.items()
        ],
        "Four-profile roster",
    )
    same(
        plan["confirmation"],
        [
            {"id": key, **asdict(scenario)}
            for key, scenario in expected_scenarios.items()
        ],
        "Eight-scenario roster",
    )
    for field, value in (
        ("training_seeds", [17, 23, 41]),
        ("cpu_caps_seconds", [1, 2, 4]),
        ("methods", list(METHODS)),
        ("max_epochs", 512),
        ("expected_workers", 72),
        ("expected_comparison_rows", 576),
    ):
        same(plan[field], value, f"Frozen {field}")
    same(
        plan["selection"],
        "last complete epoch; no development/test checkpoint selection",
        "Checkpoint selection rule",
    )
    same(
        plan["scope"],
        "matched worker CPU allowance; complete physical pipeline cost is not equated",
        "CPU comparison scope",
    )
    expected_attempts = {
        f"{pid[:12]}-{seed}-{cap}-{method}": (pid, seed, cap, method)
        for pid, seed, cap, method in itertools.product(
            expected_profiles, (17, 23, 41), (1, 2, 4), METHODS
        )
    }
    receipts = read(directory / "RECEIPTS.json")
    require(
        isinstance(receipts, list) and len(receipts) == 72,
        "Incomplete CPU attempt denominator",
    )
    joined = {receipt["id"]: receipt for receipt in receipts}
    require(
        len(joined) == 72 and set(joined) == set(expected_attempts),
        "Duplicate, missing, or unknown CPU attempts",
    )
    examples = {
        pid: public_examples(
            read(directory / f"shared-roster-{pid[:12]}.json"), profile
        )
        for pid, profile in expected_profiles.items()
    }
    checked, learners, execution_roots = {}, {}, set()
    allowed_files = {
        "ARTIFACTS.json",
        "PLAN.json",
        "REPORT.json",
        "RECEIPTS.json",
        "attempts.jsonl",
    }
    for pid in expected_profiles:
        allowed_files.update(
            (f"shared-roster-{pid[:12]}.json", f"results-{pid[:12]}.jsonl")
        )
    for key, (pid, seed, cap, method) in expected_attempts.items():
        for field, value in (
            ("profile_id", pid),
            ("seed", seed),
            ("hard_worker_cpu_seconds", cap),
            ("method", method),
        ):
            same(joined[key][field], value, f"Cartesian attempt {field}")
        receipt, learner, original_root = audit_worker(
            directory,
            key,
            joined[key],
            pid,
            expected_profiles[pid],
            examples[pid],
            plan["sources"],
        )
        require(
            receipt["source_drift"] is False and receipt["parent_error"] is None,
            "Completed campaign contains parent/source validation failure",
        )
        checked[key], learners[key] = receipt, learner
        if original_root is not None:
            execution_roots.add(original_root)
        allowed_files.update(
            f"workers/{key}/{name}.{suffix}"
            for name in ("PLAN", "LIMITS", "CHECKPOINT", "WORKER", "RECEIPT")
            for suffix in ("json", "tmp")
        )
    require(
        len(execution_roots) <= 1 and retained_files <= allowed_files,
        "Unexpected evidence files or mixed execution roots",
    )
    events = lines(directory / "attempts.jsonl", 144)
    for index, key in enumerate(expected_attempts):
        same(events[2 * index], {"id": key, "status": "Started"}, "Worker start event")
        same(
            events[2 * index + 1],
            {
                "id": key,
                "status": checked[key]["candidate_status"],
                "worker_status": checked[key]["worker"]["status"],
                "termination": checked[key]["termination"]["kind"],
            },
            "Worker terminal event",
        )
    rows, row_keys, replayed = [], set(), 0
    for pid, profile in expected_profiles.items():
        for row in lines(directory / f"results-{pid[:12]}.jsonl", 144):
            key, sid = row["attempt_id"], row["scenario_id"]
            require(
                key in checked
                and sid in expected_scenarios
                and (key, sid) not in row_keys,
                "Unknown or duplicate result join",
            )
            row_keys.add((key, sid))
            receipt, scenario = checked[key], expected_scenarios[sid]
            for field, value in (
                ("profile_id", pid),
                ("training_seed", receipt["seed"]),
                ("cpu_cap_seconds", receipt["hard_worker_cpu_seconds"]),
                ("method", receipt["method"]),
                ("candidate_status", receipt["candidate_status"]),
                ("worker_cpu_seconds", receipt["worker_inclusive_cpu_seconds"]),
                ("retained_epochs", receipt["completed_epochs"]),
                ("parameters_sha256", receipt["parameters_sha256"]),
            ):
                same(row[field], value, f"Result {field}")
            same(pid, joined[key]["profile_id"], "Result file profile")
            if learners[key] is None:
                fields(
                    row,
                    ROW_FIELDS | {"value", "policy_gap", "reason"},
                    "Unavailable result",
                )
                require(
                    row["value"] is None
                    and row["policy_gap"] is None
                    and row["reason"] == receipt["termination"]["kind"],
                    "Unavailable candidate has fabricated results",
                )
            else:
                fields(row, ROW_FIELDS | RESULT_FIELDS, "Available result")
                require(
                    row["evaluation"] == "exact_environment"
                    and row["budget_violations"] == 0,
                    "Invalid exact evaluation",
                )
                for field in (*METRICS, "policy_gap"):
                    number(row[field], -1e-10 if field == "policy_gap" else 0)
                number(row["terminal_payoff"], 0, 1 + 1e-10)
                number(row["policy_states"], 1, 20_000, integer=True)
                close(
                    row["oracle_value"] - row["value"], row["policy_gap"], "Policy gap"
                )
                cost = row["environment_cost"] + row["controller_cost"]
                duration = row["environment_seconds"] + row["controller_seconds"]
                require(
                    cost <= scenario.budget + 1e-10
                    and duration <= scenario.deadline + 1e-10,
                    "Resource expectations exceed hard support budgets",
                )
                close(
                    row["net_terminal_utility"],
                    row["terminal_payoff"]
                    - profile.resource_weight * cost
                    - profile.latency_weight * duration,
                    "Terminal utility",
                )
                fields(row["actions"], ACTIONS, "Action counts")
                close(
                    sum(number(value) for value in row["actions"].values()),
                    row["decision_calls"],
                    "Action count total",
                )
                fields(
                    row["offline_oracle"],
                    {
                        "wall_ns",
                        "cpu_ns",
                        "reachable_states",
                        "timing_scope",
                        "total_stats_including_regret_queries",
                    },
                    "Offline oracle meter",
                )
                fields(
                    row["offline_policy_evaluation"],
                    {"wall_ns", "cpu_ns", "scope"},
                    "Offline policy meter",
                )
                for meter in (row["offline_oracle"], row["offline_policy_evaluation"]):
                    for timing in ("wall_ns", "cpu_ns"):
                        number(meter[timing], upper=10**15, integer=True)
                number(
                    row["offline_oracle"]["reachable_states"], 1, 20_000, integer=True
                )
                stats = row["offline_oracle"]["total_stats_including_regret_queries"]
                fields(
                    stats,
                    {
                        "visited_states",
                        "max_states",
                        "forecast_calls",
                        "expansion_count",
                        "legal_mask_calls",
                    },
                    "Offline oracle work",
                )
                for value in stats.values():
                    number(value, upper=10**8, integer=True)
                if recompute_results:
                    fresh = evaluate(
                        scenario, profile, Controller("fast", profile, learners[key])
                    )
                    for field in (
                        *METRICS,
                        "value",
                        "policy_gap",
                        "oracle_value",
                        "net_terminal_utility",
                        "policy_states",
                    ):
                        close(
                            row[field],
                            fresh[field],
                            f"Exact replay {key}/{sid}/{field}",
                        )
                    for action in ACTIONS:
                        close(
                            row["actions"][action],
                            fresh["actions"][action],
                            "Exact replay actions",
                        )
                    for meter in ("offline_oracle", "offline_policy_evaluation"):
                        same(
                            {
                                k: v
                                for k, v in row[meter].items()
                                if k not in ("cpu_ns", "wall_ns")
                            },
                            {
                                k: v
                                for k, v in fresh[meter].items()
                                if k not in ("cpu_ns", "wall_ns")
                            },
                            "Exact replay work scope",
                        )
                    replayed += 1
            rows.append(row)
    require(
        row_keys == set(itertools.product(expected_attempts, expected_scenarios)),
        "Incomplete 576-row Cartesian denominator",
    )
    expected_summary = []
    for pid, cap, method in itertools.product(expected_profiles, (1, 2, 4), METHODS):
        group = [
            r
            for r in receipts
            if r["profile_id"] == pid
            and r["method"] == method
            and r["hard_worker_cpu_seconds"] == cap
        ]
        outcomes = [
            r
            for r in rows
            if r["profile_id"] == pid
            and r["method"] == method
            and r["cpu_cap_seconds"] == cap
            and r["value"] is not None
        ]
        expected_summary.append(
            {
                "profile_id": pid,
                "cpu_cap_seconds": cap,
                "method": method,
                "attempts": len(group),
                "available": sum(r["candidate_status"] == "Available" for r in group),
                "mean_worker_cpu_seconds": statistics.mean(
                    r["worker_inclusive_cpu_seconds"] for r in group
                ),
                "mean_retained_epochs": statistics.mean(
                    r["completed_epochs"] for r in group
                ),
                "mean_value_available_only": statistics.mean(
                    r["value"] for r in outcomes
                )
                if outcomes
                else None,
                "mean_policy_gap_available_only": statistics.mean(
                    r["policy_gap"] for r in outcomes
                )
                if outcomes
                else None,
            }
        )
    fields(
        report,
        {
            "schema",
            "status",
            "plan_sha256",
            "worker_attempts",
            "comparison_rows",
            "available",
            "unavailable",
            "total_worker_cpu_seconds",
            "summary",
            "authority",
            "limitations",
        },
        "Campaign report",
    )
    require(
        report["schema"] == "hepta.ctrl1.cpu-report.v1"
        and report["status"] == "COMPLETED_CPU_ALLOWANCE_SENSITIVITY"
        and report["authority"] == "none",
        "Campaign does not report a completed non-promoting sensitivity",
    )
    available = sum(r["candidate_status"] == "Available" for r in receipts)
    for field, value in (
        ("worker_attempts", 72),
        ("comparison_rows", 576),
        ("available", available),
        ("unavailable", 72 - available),
    ):
        same(report[field], value, f"Report {field}")
    close(
        report["total_worker_cpu_seconds"],
        sum(r["worker_inclusive_cpu_seconds"] for r in receipts),
        "Total worker CPU including failures",
    )
    same(
        report["summary"],
        expected_summary,
        "Summary recomputed from original receipts and results",
    )
    same(plan["sources"], source_manifest(), "Sources after audit")
    return {
        "status": "PASS",
        "plan_sha256": digest(plan),
        "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "workers": 72,
        "comparison_rows": 576,
        "attempt_events": 144,
        "available": available,
        "unavailable": 72 - available,
        "recomputed_rows": replayed,
        "null_rows_verified": 8 * (72 - available),
        "termination_counts": dict(
            sorted(Counter(r["termination"]["kind"] for r in receipts).items())
        ),
        "original_execution_root": next(iter(execution_roots), None),
        "authority": "none",
        "scope": "archive consistency and optional frozen-evaluator replay; not independent execution attestation",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--recompute-results", action="store_true")
    args = parser.parse_args()
    try:
        result = audit(args.directory, args.recompute_results)
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        OverflowError,
        RecursionError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                allow_nan=False,
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True, allow_nan=False))
