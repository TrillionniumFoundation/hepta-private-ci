"""Read retained research-SFT evidence only; no model, verifier, or C execution.

The three predeclared slots are an opportunity diagnostic, not a trained circuit.
Every positive outcome requires retained raw business evidence and adapter bytes.
"""
import argparse
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time

WORKSPACE = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
SLOTS = ("final_answer", "trajectory", "controlled_correction")
SEPARATE = "shadow_correction"
FIT_MODES = {"final_answer": "final_answer", "trajectory": "trajectory",
             "shadow_correction": "trajectory", "controlled_correction": "trajectory"}
ARMS = ("parent", "retrieval", *FIT_MODES)
BASELINE = {"RESULT.json": "33d0d5359edf547afa6d5de36a9db5f691b14a5eca4387c0ebcdd36b6d6f550d",
            "FREEZE.json": "02fa20ad7ce2d74d8631dd5a6ac1a2b8a5496a8632244fcdf4676eb1c21aad2c"}
SOURCE_MANIFEST = "f4baf14dfb07513ade469adf6877ce6cd15ac98fbcc0e390854fcf24c85ae2be"
HELPERS = {
    "qwen_development_io_v3.py": "4116cfc058cfbec9bdca4845e409d0c1c2071d9da9faa4b56f9d8aa6df5a2060",
    "qwen_development_inputs_v3.py": "6bd1b2d71857c5b541ca63ce815cbb05660b75284fc7065e5766e43d910fea20",
    "qwen_development_execution_v3.py": "b28824a766115de190946055225452743dc95482de53a3d872781a7922b77656",
    "run_qwen_development_v3.py": "1f8cbc7eb21cae9a1e82654b3234e839f7cbe6cfa055f40900d16a559d72bb20"}
SCOPE = {"research_only": True, "scientific_confirmation_qualified": False,
         "native_cell_adoption": False, "proof_of_useful_work_eligible": False,
         "circuit_qualified": False, "new_C": False, "candidate_selected": None,
         "independent_sample_increment": 0, "external_teacher_count_added": 0, "new_users": 0}
RULES = {"first_last_separate": True, "zero_baseline_retention": None,
         "failed_slot_replacement": False, "missing_evidence": "unavailable",
         "partial_cost": "unknown_totals_with_measured_subtotals",
         "panel_cost_scope": "actual_panel_only_excludes_load_close",
         "cost_scopes_additive": False, "union_not_routing": True,
         "new_independent_samples": 0, "new_teachers": 0, "new_users": 0}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def parse(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate JSON key")
            out[key] = value
        return out
    def constant(_):
        raise ValueError("nonfinite JSON value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def sealed(value):
    require(value.get("receipt_sha256") == digest(
        {key: item for key, item in value.items() if key != "receipt_sha256"}), "receipt seal differs")
    return value


def scope(value):
    for key, expected in SCOPE.items():
        actual = value.get(key)
        require(actual is expected if expected is None or type(expected) is bool
                else type(actual) is type(expected) and actual == expected, "research scope differs: " + key)


class Reader:
    """Track exact read bytes and reject links/escapes; never deserialize weights."""
    def __init__(self, root):
        self.root = Path(root)
        require(self.root.is_absolute() and self.root == self.root.resolve(), "nonsymlink root required")
        self.observed, self.errors = {}, []

    def path(self, value):
        path = Path(value)
        if not path.is_absolute():
            relative = PurePosixPath(str(value))
            require(str(relative) == str(value) and ".." not in relative.parts and "\\" not in str(value),
                    "normalized relative path required")
            path = self.root / relative
        require(path != self.root and path.is_relative_to(self.root), "path escapes evidence root")
        current = self.root
        for part in path.relative_to(self.root).parts:
            require(part not in ("..", ".") and part not in ("C", "confirmation")
                    and ".sealed." not in part and not part.startswith("catalog-C"), "forbidden evidence path")
            current /= part
            require(not current.is_symlink(), "symlink rejected")
        return path

    def hash(self, value, expected=None):
        path = self.path(value)
        require(path.is_file(), "regular evidence file missing: " + str(path))
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        entry = {"bytes": path.stat().st_size, "sha256": h.hexdigest()}
        key = path.relative_to(self.root).as_posix()
        require(key not in self.observed or self.observed[key] == entry, "evidence changed while reading")
        require(expected is None or entry["sha256"] == expected, "file SHA differs: " + key)
        self.observed[key] = entry
        return entry

    def raw(self, value, expected=None):
        entry = self.hash(value, expected)
        require(entry["bytes"] <= 64 * 1024**2, "bounded JSON evidence required")
        raw = self.path(value).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == entry["sha256"], "evidence changed after hash")
        return raw

    def read(self, value, expected=None):
        return parse(self.raw(value, expected))

    def optional(self, value):
        path = self.path(value)
        if not path.exists():
            return None
        try:
            value = self.read(path)
            require(isinstance(value, dict), "receipt must be a JSON object")
            return value
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.errors.append({"path": str(path.relative_to(self.root)),
                                "file": self.observed.get(str(path.relative_to(self.root))),
                                "error": repr(error)})
            return None

    def inventory(self, directory, mapping, exact=False):
        require(isinstance(mapping, dict) and 0 < len(mapping) <= 2048, "bounded source inventory required")
        directory = self.path(directory)
        for relative, expected in mapping.items():
            require(not Path(relative).is_absolute() and ".." not in Path(relative).parts,
                    "inventory path escapes directory")
            self.hash(directory / relative, expected)
        if exact:
            require(not any(p.is_symlink() for p in directory.rglob("*")), "source symlink rejected")
            actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if not p.is_dir()}
            require(actual == set(mapping), "exact source membership differs")

    def recheck(self):
        before = dict(self.observed)
        for relative, entry in before.items():
            require(self.hash(relative) == entry, "retained source changed")
        return before


def validate_rules(value, source_sha):
    require(value.get("schema") == "hepta.research-sft-diagnostic-freeze.v1"
            and value.get("status") == "FROZEN_PRE_FIT"
            and value.get("rule_version") == "research-diagnostic-v1", "frozen diagnostic rules required")
    scope(value)
    require(value.get("fixed_slots") == list(SLOTS) and value.get("separate_arm") == SEPARATE
            and value.get("rules") == RULES and value.get("baseline_bindings") == BASELINE,
            "predeclared diagnostic rules differ")
    require(value.get("slot_admission") == "complete_primary_fit_and_evaluation_plus_exact_cold_identity"
            and value.get("source_growth_options") == {"readiness": None, "updates_per_source": 64}
            and value.get("cost_matching") == "not_claimed_from_panel_measurements", "diagnostic admission details differ")
    require(value.get("diagnostic_source") == {"filename": "qwen_research_diagnostic_v1.py",
                                               "sha256": source_sha}, "diagnostic source differs")


def paired_metrics(before, after):
    """Known task outcomes only. A zero prior-success denominator remains null."""
    require(set(before) == set(after) and before, "paired task identities required")
    known = all(type(v) is bool for v in [*before.values(), *after.values()])
    old = [key for key, value in before.items() if value is True]
    lost = [key for key in old if after[key] is False]
    gained = [key for key in before if before[key] is False and after[key] is True]
    return {"tasks": len(before), "outcomes_complete": known,
            "before_successes": sum(v is True for v in before.values()) if known else None,
            "after_successes": sum(v is True for v in after.values()) if known else None,
            "after_success_rate": sum(v is True for v in after.values()) / len(after) if known else None,
            "previously_successful_tasks": len(old) if known else None,
            "lost_tasks": lost, "gained_tasks": gained,
            "retained_fraction_of_previous_successes": (len(old) - len(lost)) / len(old) if known and old else None,
            "scope": "same exposed tasks; zero prior successes cannot establish absence of forgetting"}


def fixed_union(arms):
    available = {name: set(arms[name]["A_first_successes"]) for name in SLOTS
                 if arms.get(name, {}).get("status") == "AVAILABLE"}
    union = set().union(*available.values()) if available else set()
    best = max(map(len, available.values())) if available else None
    complete = len(available) == len(SLOTS)
    reason = ("missing fixed expert slot" if not complete else "union <= best single slot"
              if len(union) <= best else "opportunity only; routing and full-system cost match untested")
    return {"fixed_slots": list(SLOTS), "available_slots": list(available),
            "unavailable_slots": [name for name in SLOTS if name not in available],
            "slot_replacement": False, "first_attempt_only": True,
            "all_slots_available": complete, "union_successes": len(union) if complete else None,
            "best_single_successes": best if complete else None,
            "available_slot_union_tasks": sorted(union), "available_slot_best_subtotal": best,
            "union_exceeds_best": len(union) > best if complete else None,
            "circuit_experiment_qualified": False, "full_system_cost_matched": False,
            "stop_reason": reason, "routing_executions": 0}


def attempt_row(reader, record, row, directory, model_digest, generation_digest,
                semantic, protocol, *, pid=None, execute=True):
    """Bind raw request/output/step files; no generated answer is repaired."""
    require(all(row.get(k) == record[k] for k in ("record_id", "task_id", "source_id", "lineage_id")),
            "attempt provenance differs")
    messages = copy.deepcopy(protocol.require_prepared(record))
    steps, outcomes = row.get("steps", []), []
    require(1 <= len(steps) <= (2 if execute else 1), "bounded actual attempts required")
    for number, step in enumerate(steps):
        sealed(step)
        request = {"record_id": record["record_id"],
                   "task": {"input": record["task"]["input"], "messages": copy.deepcopy(messages)}}
        output = step["output"]
        require(step.get("number") == number and step.get("request_sha256") == digest(request)
                and output.get("loaded_model_digest") == model_digest
                and output.get("input_sha256") == hashlib.sha256(record["task"]["input"].encode()).hexdigest()
                and output.get("messages_sha256") == digest(messages)
                and output.get("generation_config_sha256") == generation_digest, "raw model/request identity differs")
        require(type(output.get("pid")) is int and output["pid"] > 0
                and (pid is None or output["pid"] == pid)
                and type(output.get("input_tokens")) is int and 0 < output["input_tokens"] <= 4096
                and type(output.get("output_tokens")) is int
                and output["output_tokens"] == len(output.get("output_token_ids", []))
                and 0 <= output["output_tokens"] <= 384 and output.get("max_new_tokens") == 384,
                "raw token/worker budget differs")
        for name, value in (("request", request), ("output", output), ("step", step)):
            require(reader.read(directory / f"{name}-{number}.json") == value, "aggregate/raw evidence differs")
        if execute:
            evidence = semantic(record, output["answer"], step["verification"])
            outcome = evidence["business_success"]
            require(type(outcome) is bool and not any(outcomes), "unknown positive or attempts after success")
            feedback = protocol.feedback(step["verification"])
            require(step.get("executed") is evidence["verifier_executed"]
                    and step.get("execution_summary") == protocol.execution_summary(step["verification"])
                    and step.get("semantic_measurement") == "measured", "business execution binding differs")
        else:
            require(step.get("verification") is None and step.get("executed") is False
                    and step.get("execution_summary") is None and step.get("semantic_measurement") == "unmeasured",
                    "historical execution cannot be fresh shadow")
            outcome = None
            feedback = "Shadow prediction was recorded without applying the patch or executing tests."
        require(step.get("feedback") == feedback, "recorded feedback differs")
        outcomes.append(outcome)
        messages.extend([{"role": "assistant", "content": output["answer"]}, {"role": "tool", "content": feedback}])
    require(row.get("success") is outcomes[-1] and row.get("first_attempt_success") is outcomes[0],
            "first/last business summary differs")
    raw = reader.read(directory / "RESULT.json")
    require(all(row.get(k) == v for k, v in raw.items()) and raw.get("steps") == steps,
            "raw task result differs from aggregate")
    return {"first": outcomes[0], "last": outcomes[-1], "actual_model_calls": len(steps),
            "executed_attempts": sum(step["executed"] for step in steps)}


def adapter_identity(reader, directory, manifest, parent, plan, training, records):
    """Hash adapters and optimizer, without reading public base weights or Torch."""
    scope(manifest)
    require(manifest.get("schema") == "hepta.research-authored-sft-model.v1"
            and manifest.get("family") == "hepta-qwen25-coder-research-authored-sft-v1"
            and manifest.get("base_manifest") == parent and manifest.get("model_id") == parent["model_id"]
            and manifest.get("parent_model_digest") == digest(parent)
            and manifest.get("runtime") == parent["runtime"]
            and manifest.get("backend_versions") == parent["backend_versions"]
            and manifest.get("training_plan_digest") == digest(plan)
            and manifest.get("research_source_inventory") == plan["source_inventory"]
            and manifest.get("reference_admission_digest") == digest(plan["reference_admission"])
            and manifest.get("parent_successful_A_tasks") == plan["reference_admission"]["parent_successful_A_tasks"],
            "research adapter identity differs")
    adapter = reader.path(manifest["adapter_directory"])
    require(adapter.is_relative_to(directory), "adapter escapes its actual worker")
    entries = manifest.get("adapter_files", [])
    names = {item["path"] for item in entries}
    require(len(names) == len(entries) and {"adapter_config.json", "adapter_model.safetensors"} <= names
            and names <= {"adapter_config.json", "adapter_model.safetensors", "README.md"},
            "complete adapter byte inventory required")
    for item in entries:
        require(reader.hash(adapter / item["path"], item["sha256"])["bytes"] == item["bytes"], "adapter size differs")
    require({p.relative_to(adapter).as_posix() for p in adapter.rglob("*") if not p.is_dir()} == names,
            "adapter membership differs")
    config = reader.read(adapter / "adapter_config.json")
    expected = {"peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 4, "lora_alpha": 8,
                "lora_dropout": 0.0, "bias": "none", "inference_mode": True}
    require(all(config.get(k) == v for k, v in expected.items())
            and set(config.get("target_modules", [])) == {"q_proj", "v_proj"}, "adapter architecture differs")
    scope(training)
    require(training.get("schema") == "hepta.research-authored-sft-training.v1"
            and training.get("records_digest") == digest(records)
            and training.get("source_inventory") == plan["source_inventory"] and training.get("mode") == plan["mode"]
            and training.get("status") == "COMPLETE" and training.get("research_model_digest") == digest(manifest)
            and training.get("plan_digest") == digest(plan) and training.get("steps") == 64
            and training.get("parent_model_digest") == digest(parent), "actual completed training binding required")
    optimizer = training["optimizer"]
    optimizer_path = reader.path(optimizer["path"])
    require(optimizer_path == directory / "optimizer.pt"
            and reader.hash(optimizer_path, optimizer["sha256"])["bytes"] == optimizer["bytes"],
            "optimizer bytes missing or different")
    step_lines = reader.raw(directory / "STEPS.jsonl").splitlines()
    require(len(step_lines) == 64, "exactly 64 retained optimizer step receipts required")
    steps = [parse(line) for line in step_lines]
    require(all(type(row.get("loss")) in (int, float) and math.isfinite(row["loss"]) for row in steps)
            and training.get("losses") == [row["loss"] for row in steps], "training loss evidence differs")
    counts = training["record_turn_updates"]
    require(len(counts) == len(records) == 6 and all(row for row in counts), "six nonempty turn groups required")
    measured_counts = [[0] * len(row) for row in counts]
    for index, step in enumerate(steps):
        group = index % 6
        turn = (index // 6) % len(counts[group])
        require(step["step"] == index + 1 and step["task_id"] == records[group]["task_id"]
                and step["record_id"] == records[group]["record_id"] and step["turn"] == turn
                and step["padded_positions"] == 1536 and type(step["supervised_tokens"]) is int
                and 0 < step["supervised_tokens"] < step["input_tokens"] <= 1536,
                "actual step schedule or supervision accounting differs")
        measured_counts[group][turn] += 1
    require(measured_counts == counts
            and training["cost"]["padded_training_token_positions"] == 64 * 1536
            and training["cost"]["input_tokens_consumed"] == sum(row["input_tokens"] for row in steps)
            and training["cost"]["supervised_tokens"] == sum(row["supervised_tokens"] for row in steps),
            "training cost counters differ from actual step receipts")
    return digest(manifest)


def verify_training_references(reader, directory, records, semantic):
    receipts = []
    for index, record in enumerate(records):
        base = directory / "references" / str(index)
        request = reader.read(base / "REFERENCE_REQUEST.json")
        receipt = reader.read(base / "REFERENCE.json")
        measured = sealed(reader.read(base / "REFERENCE_MEASUREMENT.json"))
        require(request["record_digest"] == digest(record)
                and request["answer_sha256"] == hashlib.sha256(record["final_answer"].encode()).hexdigest()
                and measured["status"] == "COMPLETE"
                and measured["reference_sha256"] == reader.hash(base / "REFERENCE.json")["sha256"]
                and semantic(record, record["final_answer"], receipt)["business_success"] is True,
                "actual training reference recheck differs")
        receipts.append(receipt)
    require(reader.read(directory / "REFERENCE_RECHECKS.json") == receipts,
            "reference aggregate differs; individual calls counted only once")


def cold_identity(primary, cold, job, primary_file_sha):
    require(cold["manifest"] == primary["manifest"] and cold["pid"] != primary["pid"]
            and job["primary_manifest"] == primary["manifest"] and job["primary_pid"] == primary["pid"]
            and job["primary_result_sha256"] == primary_file_sha
            and cold.get("cold_manifest_exactly_matches_primary") is True,
            "cold identity chain differs")


def process_result(reader, run, name, freeze):
    job = sealed(reader.read(run / "jobs" / (name + ".json")))
    exit_receipt = sealed(reader.read(run / "processes" / name / "EXIT.json"))
    result = sealed(reader.read(run / "workers" / name / "RESULT.json"))
    require(exit_receipt.get("exit_code") == 0 and exit_receipt.get("timed_out") is False,
            "worker did not complete successfully")
    require(job.get("freeze_sha256") == reader.hash(run / "FREEZE.json")["sha256"]
            and result.get("job_digest") == digest(job) and result.get("freeze_digest") == digest(freeze)
            and result.get("pid") == exit_receipt.get("pid"), "actual worker/job/freeze identity differs")
    scope(result)
    require(job.get("schema") == "hepta.research-sft-job.v1"
            and result.get("schema") == "hepta.research-sft-worker.v1", "research worker namespace required")
    entry = job["schedule_entry"]
    require(entry in freeze["schedule"] and name == entry["arm"] + "-" + entry["phase"]
            and result.get("arm") == entry["arm"] and result.get("phase") == entry["phase"],
            "worker schedule binding differs")
    launch = reader.read(run / "processes" / name / "LAUNCH.json")
    argv = launch["argv"]
    require(len(argv) == 8 and argv[:4] == [freeze["runtime"]["python"], "-I", "-B",
                str(WORKSPACE / "research-sft-v1-source/research_sft_execution_v1.py")]
            and dict(zip(argv[4::2], argv[5::2])) == {
                "--job": str(run / "jobs" / (name + ".json")), "--helper-directory": freeze["helper_directory"]}
            and launch["timeout_seconds"] == job["worker_wall_seconds"]
            and launch.get("automatic_retry") is False, "worker launch differs")
    for name2 in ("stdout", "stderr"):
        reader.hash(run / "processes" / name / (name2 + ".log"), exit_receipt[name2 + "_sha256"])
    return job, result


def evaluation(reader, directory, report, context, manifest, arm, phase, semantic, protocol):
    sealed(report)
    scope(report)
    require(report.get("schema") == "hepta.research-sft-evaluation.v1"
            and report.get("status") == "COMPLETE" and report.get("arm") == arm and report.get("phase") == phase
            and report.get("model_digest") == digest(manifest)
            and report.get("generation_digest") == context["generation_digest"]
            and report.get("maximum_attempts") == 2 and report.get("max_new_tokens") == 384,
            "evaluation identity or budget differs")
    require(reader.read(directory / "EVALUATION.json") == report, "worker evaluation differs from raw receipt")
    panels = context["panels"]
    shown = context["retrieval_panels"] if arm == "retrieval" else panels
    require(reader.read(directory / "ORIGINAL_PANELS.json") == panels
            and reader.read(directory / "SHOWN_PANELS.json") == shown
            and report["original_panels_digest"] == digest(panels)
            and report["shown_panels_digest"] == digest(shown), "evaluation panel binding differs")
    loaded = reader.read(directory / "MODEL_LOADED.json")
    require(loaded["model_digest"] == digest(manifest) and loaded["generation_digest"] == context["generation_digest"]
            and digest(loaded["generation"]) == loaded["generation_digest"] and loaded["pid"] == report["pid"],
            "actual loaded model/generation differs")
    keys = [(panel, record["task_id"]) for panel, records in panels.items() for record in records]
    require([(r["panel"], r["task_id"]) for r in report["rows"]] == keys, "evaluation task order or coverage differs")
    outcomes, calls = {}, 0
    offset = 0
    for panel, records in panels.items():
        outcomes[panel] = {"first": {}, "last": {}}
        for index, (original, augmented) in enumerate(zip(records, shown[panel])):
            row = report["rows"][offset]
            require(row["original_task_digest"] == digest(original) and row["shown_task_digest"] == digest(augmented),
                    "original/shown task identity differs")
            measured = attempt_row(reader, augmented, row, directory / panel / str(index),
                                   digest(manifest), context["generation_digest"], semantic, protocol, pid=loaded["pid"])
            for attempt in ("first", "last"):
                outcomes[panel][attempt][row["task_id"]] = measured[attempt]
            calls += measured["actual_model_calls"]
            offset += 1
        measurement = sealed(reader.read(directory / panel / "MEASUREMENT.json"))
        started = reader.read(directory / panel / "STARTED.json")
        require(measurement == report["panel_measurements"][panel] and measurement["status"] == "COMPLETE"
                and measurement["completed_tasks"] == measurement["expected_tasks"] == len(records)
                and started["model_digest"] == digest(manifest)
                and started["original_records_digest"] == digest(records)
                and started["shown_records_digest"] == digest(shown[panel]), "actual panel measurement binding differs")
        summary = report["by_panel"][panel]
        require(summary["tasks"] == len(records)
                and summary["successful_tasks"] == sum(outcomes[panel]["last"].values())
                and summary["first_attempt_successes"] == sum(outcomes[panel]["first"].values()),
                "evaluation summary differs from raw business evidence")
    require(report["model_calls"] == calls and report["verifier_calls"] == calls, "evaluation call counts differ")
    return outcomes


def cost_ledger(reader, run, complete, raw_ledger, children):
    """Reuse the frozen runner's raw receipt ledger; retain disjoint scope labels."""
    ledger = raw_ledger(run, children, operation_complete=complete)
    panels, costs = [], []
    names = ("corrections-collect", *(a + "-" + p for a in ARMS for p in ("primary", "cold")))
    for name in names:
        worker = reader.path(run / "workers" / name)
        if not worker.exists():
            continue
        for panel in ("B_exposed", "A_retention"):
            directory = worker / "evaluation" / panel
            if not directory.exists():
                continue
            start = reader.optional(directory / "STARTED.json")
            end = next((directory / n for n in ("MEASUREMENT.json", "FAILED.json")
                        if (directory / n).exists()), None)
            measurement = reader.optional(end) if end is not None else None
            value = {"path": str(end or directory / "STARTED.json"),
                     "status": "STARTED_NO_END_MEASUREMENT", "cost": None, "model_calls": None,
                     "input_tokens": None, "output_tokens": None}
            if measurement is not None:
                try:
                    sealed(measurement)
                    cost = measurement["cost"]
                    require(start is not None and cost.get("includes_model_load_or_close") is False
                            and cost.get("nested_scopes_are_not_additive") is True
                            and cost.get("includes_completed_verifier_child_cpu") is True
                            and measurement.get("panel") == panel, "actual panel scope differs")
                    value.update({k: measurement.get(k) for k in (
                        "status", "cost", "model_calls", "input_tokens", "output_tokens",
                        "input_tokens_measured_subtotal", "output_tokens_measured_subtotal")})
                except (ValueError, KeyError, TypeError) as error:
                    reader.errors.append({"path": str(end), "error": repr(error)})
            panels.append(value)
        paths = [worker / "RESULT.json", worker / "FAILED.json",
                 worker / "research-model/TRAINING.json", worker / "research-model/FAILED.json"]
        for request in sorted(worker.rglob("REFERENCE_REQUEST.json")):
            end = request.parent / "REFERENCE_MEASUREMENT.json"
            paths.append(end if end.exists() else request.parent / "REFERENCE_FAILED.json")
        for path in paths:
            receipt = reader.optional(path)
            if receipt is not None:
                costs.append({"path": str(path), "status": receipt.get("status"),
                              "cost": receipt.get("worker_cost", receipt.get("cost"))})
    return {**ledger, "projection_source": "exact frozen run_research_sft_v1.raw_ledger",
            "actual_panel_measurements": panels, "other_nested_scope_measurements": costs,
            "additional_read_errors": copy.deepcopy(reader.errors), "nested_costs_added": False,
            "panel_costs_exclude_model_load_close": True, "full_system_cost": None,
            "full_system_cost_matched": False, "gpu_active_seconds": None, "energy_joules": None}

def collect_bindings(reader, run, freeze, context, contract, semantic, protocol):
    from cell_experiments.repo_interaction_v2 import corrected_record
    _, collection = process_result(reader, run, "corrections-collect", freeze)
    require(collection.get("status") == "RESEARCH_PLANS_FROZEN", "four research plans were not frozen")
    directory = run / "workers/corrections-collect"
    require(collection.get("controlled_new_model_calls") == collection.get("controlled_new_verifier_calls") == 0
            and collection.get("shadow_execute") is False, "controlled replay/shadow accounting differs")
    reuse = reader.read(directory / "CONTROLLED_REUSE.json")
    controlled = context["gate"]["controlled_observations"]
    require(reuse["observations"] == controlled and reuse["source_readiness_digest"] == digest(context["readiness"])
            and reuse["source_readiness_directory"] == freeze["readiness_directory"]
            and reuse["new_model_calls"] == reuse["new_verifier_calls"] == 0, "historical controlled bytes differ")
    shadows = []
    for index, record in enumerate(context["records"][:6]):
        shadow = reader.read(directory / "shadow" / str(index) / "RESULT.json")
        attempt_row(reader, record, shadow, directory / "shadow" / str(index), digest(context["parent"]),
                    context["generation_digest"], semantic, protocol, pid=collection["pid"], execute=False)
        shadows.append(shadow)
    full = reader.read(directory / "PLANS.json")
    require(set(full) == set(collection["plans"]) == set(FIT_MODES)
            and collection.get("plans_digest") == digest(full), "four-plan inventory differs")
    result = {}
    for arm, mode in FIT_MODES.items():
        binding = collection["plans"][arm]
        records = reader.read(binding["records_path"], binding["records_sha256"])
        plan = reader.read(binding["plan_path"], binding["plan_sha256"])
        require(plan == full[arm] and plan.get("mode") == mode
                and plan.get("operation_id") == freeze["operation_id"] + "/" + arm,
                "actual training plan mode or operation differs")
        contract.validate_plan(records, context, plan)
        if arm in ("final_answer", "trajectory"):
            require(records == context["records"][:6], "original A training bytes differ")
        else:
            correction_mode = "shadow" if arm == SEPARATE else "controlled"
            observations = shadows if correction_mode == "shadow" else controlled
            for index, (old, observed, actual) in enumerate(zip(context["records"][:6], observations, records)):
                expected = corrected_record(old, observed, correction_mode)
                reference_request = reader.read(directory / "corrections" / correction_mode / str(index) / "REFERENCE_REQUEST.json")
                require(reference_request["record_digest"] == digest(expected), "correction reference request differs")
                expected["protocol_reference_receipt"] = actual["protocol_reference_receipt"]
                expected["verified_outcome"] = actual["verified_outcome"]
                require(actual == expected, "correction context differs from its actual source observation")
                reference = reader.read(directory / "corrections" / correction_mode / str(index) / "REFERENCE.json")
                require(reference == actual["protocol_reference_receipt"]
                        and semantic(actual, actual["final_answer"], reference)["business_success"] is True,
                        "authored correction reference not bound")
        result[arm] = {"records": records, "plan": plan, "binding": binding}
    return collection, result


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def diagnose(reader, freeze, run):
    """Import only byte-verified code; call exclusively its read-only validators."""
    source = reader.path(freeze["source"])
    manifest = reader.read(WORKSPACE / "operations/QWEN_SOURCE_02.json", SOURCE_MANIFEST)
    require(manifest["files"] == freeze["source_inventory"] and len(manifest["files"]) == 119,
            "frozen source02 inventory differs")
    reader.inventory(source, manifest["files"], exact=True)
    helpers = reader.path(freeze["helper_directory"])
    require(helpers == WORKSPACE / "e1e2-operation-helpers-04"
            and freeze["helper_inventory"] == HELPERS, "actual helper04 binding differs")
    reader.inventory(helpers, HELPERS)
    research = WORKSPACE / "research-sft-v1-source"
    reader.inventory(research, freeze["research_inventory"])
    require(set(freeze["research_inventory"]) == {
        "research_sft_contract_v1.py", "research_sft_train_v1.py",
        "research_sft_execution_v1.py", "run_research_sft_v1.py"}, "four research modules required")
    sys.path[:0] = [str(research), str(source / "scripts")]
    contract = importlib.import_module("research_sft_contract_v1")
    h = contract.bind_helpers(helpers)
    runner = importlib.import_module("run_research_sft_v1")
    runner.configure(helpers)
    contract.scope_guard(freeze)
    require(freeze["profile"] == contract.PROFILE and freeze["admission_policy"] == contract.ADMISSION
            and freeze["workspace_root"] == freeze["artifact_root"] == str(WORKSPACE)
            and source == WORKSPACE / "candidate-qwen-03" and freeze["fit_plans_must_precede_all_fits"] is True
            and freeze["baseline_result_sha256"] == BASELINE["RESULT.json"]
            and freeze["baseline_freeze_sha256"] == BASELINE["FREEZE.json"], "research freeze identity differs")
    require(freeze["budget"] == h.io.BUDGET and freeze["schedule"] == h.runner.schedule()
            and freeze["fitting_modes"] == FIT_MODES, "research budget or schedule differs")
    from cell_experiments import protocol_v3 as protocol
    from cell_experiments.source_metrics_v3 import source_growth_metrics
    baseline = reader.path(freeze["readiness_directory"])
    require(baseline == WORKSPACE / "probe-qwen-parent-03", "actual parent03 baseline required")
    for name, expected in BASELINE.items():
        reader.hash(baseline / name, expected)
    reader.inventory(baseline, freeze["readiness_inventory"])
    context = contract.load_context(WORKSPACE, source, baseline)
    recorded_context = reader.read(freeze["inputs_path"], freeze["inputs_sha256"])
    require(recorded_context == context
            and freeze["parent_digest"] == digest(context["parent"])
            and freeze["parent_readiness_digest"] == digest(context["readiness"])
            and freeze["parent_successful_A_tasks"] == context["gate"]["successful_A_tasks"]
            and freeze["reference_admission_digest"] == digest(context["research_admission"])
            and freeze["runtime"] == context["runtime"],
            "operation INPUTS or measured baseline differs")
    context = recorded_context
    parent_outcomes = {"first": {}, "last": {}}
    for record, row in zip(context["records"][:6], context["readiness"]["rows"][:6]):
        for attempt, field in (("first", "first_attempt_success"), ("last", "success")):
            parent_outcomes[attempt][record["task_id"]] = row[field]
    # Freeze the exact selected run members being inspected; no claim of an atomic filesystem snapshot.
    for path in sorted(run.rglob("*")):
        require(not path.is_symlink(), "run symlink rejected")
        if path.is_file():
            require(path.stat().st_size <= 256 * 1024**2, "unexpected oversized run artifact")
            reader.hash(path)
    terminal = reader.optional(run / "RESULT.json")
    if terminal is not None:
        sealed(terminal)
        scope(terminal)
        require(terminal.get("schema") == "hepta.research-sft-result.v1"
                and terminal.get("freeze_digest") == digest(freeze), "research result binding differs")
    else:
        terminal = reader.optional(run / "FAILED.json")
    errors, arms, plans, collection = [], {}, {}, None
    try:
        collection, plans = collect_bindings(reader, run, freeze, context, contract, h.inputs.semantic, protocol)
    except (OSError, ValueError, TypeError, KeyError) as error:
        errors.append({"stage": "collection_binding", "error": repr(error)})
    for arm in ARMS:
        observed = {}
        try:
            primary_job, primary = process_result(reader, run, arm + "-primary", freeze)
            identity = primary["manifest"]
            candidate = reader.read(identity["path"], identity["sha256"])
            require(identity["model_digest"] == digest(candidate), "manifest digest differs")
            if arm in FIT_MODES:
                require(arm in plans, "actual complete collection binding missing")
                item = plans[arm]
                directory = run / "workers" / (arm + "-primary") / "research-model"
                require(Path(identity["path"]) == directory / "manifest.json"
                        and all(primary_job.get(k) == v for k, v in item["binding"].items())
                        and primary_job["collection_result_sha256"] == reader.hash(
                            run / "workers/corrections-collect/RESULT.json")["sha256"], "worker used a different frozen plan")
                training = reader.read(directory / "TRAINING.json")
                require(primary["training"] == training and training.get("records_digest") == digest(item["records"]),
                        "training receipt differs from actual cohort")
                started = reader.read(directory / "STARTED.json")
                require(started["plan_digest"] == digest(item["plan"])
                        and started["started_at_ns"] > collection["completed_at_ns"]
                        and all(p["plan"]["created_at_ns"] <= collection["completed_at_ns"] for p in plans.values()),
                        "all four plans must precede this actual fit")
                adapter_identity(reader, directory, candidate, context["parent"], item["plan"], training, item["records"])
                verify_training_references(reader, directory, item["records"], h.inputs.semantic)
            else:
                require(candidate == context["parent"], "frozen/retrieval arm must use the actual parent")
            metrics = evaluation(reader, run / "workers" / (arm + "-primary") / "evaluation",
                                 primary["evaluation"], context, candidate, arm, "primary", h.inputs.semantic, protocol)
            observed = {"primary_outcomes": metrics, "model_digest": digest(candidate),
                        "A_first_successes": sorted(k for k, v in metrics["A_retention"]["first"].items() if v),
                        "A_last_successes": sorted(k for k, v in metrics["A_retention"]["last"].items() if v),
                        "retention": {attempt: paired_metrics(parent_outcomes[attempt], metrics["A_retention"][attempt])
                                      for attempt in ("first", "last")}}
            cold_job, cold = process_result(reader, run, arm + "-cold", freeze)
            cold_identity(primary, cold, cold_job, reader.hash(
                run / "workers" / (arm + "-primary") / "RESULT.json")["sha256"])
            repeated = evaluation(reader, run / "workers" / (arm + "-cold") / "evaluation",
                                  cold["evaluation"], context, candidate, arm, "cold", h.inputs.semantic, protocol)
            raw = lambda result: [[(s["output"]["answer"], s["output"]["output_token_ids"]) for s in r["steps"]]
                                  for r in result["evaluation"]["rows"]]
            arms[arm] = {"status": "AVAILABLE", **observed,
                         "cold": {"identity_verified": True, "outcomes": repeated,
                                  "business_outcomes_equal": metrics == repeated,
                                  "raw_answers_and_tokens_equal": raw(primary) == raw(cold),
                                  "different_worker_pid": True, "independent_sample_increment": 0}}
        except (OSError, ValueError, TypeError, KeyError) as error:
            arms[arm] = {"status": "UNAVAILABLE", "reason": repr(error),
                         "retained_primary_observation_if_complete": observed or None, "replacement": None}
    source_rows = [{"task_id": row["task_id"], "source_id": row["source_id"],
                    "lineage_id": row["lineage_id"],
                    "observation_digest": hashlib.sha256(row["task"]["input"].encode()).hexdigest()}
                   for row in context["records"][:6]]
    growth = source_growth_metrics(source_rows, unit_field="source_id", updates_per_source=64, readiness=None)
    complete = (terminal is not None and terminal.get("status") == "RESEARCH_COMPLETE_UNQUALIFIED"
                and all(value["status"] == "AVAILABLE" for value in arms.values()) and not errors)
    ledger = cost_ledger(reader, run, complete, runner.raw_ledger, terminal.get("children", []) if terminal else [])
    require(not any(name.split(".")[0] in ("torch", "transformers", "peft") for name in sys.modules),
            "diagnostic imported a model library")
    return {"schema": "hepta.research-sft-diagnostic.v1", "status": "RESEARCH_DIAGNOSTIC_COMPLETE_UNQUALIFIED",
            "operation_status": terminal.get("status") if terminal else "TERMINAL_RECEIPT_MISSING",
            "freeze_digest": digest(freeze), "parent_model_digest": digest(context["parent"]),
            "baseline_bindings": BASELINE, "parent_A_outcomes": parent_outcomes,
            "parent_A_last_successes": context["gate"]["successful_A_tasks"],
            "fixed_expert_slots": {name: arms[name] for name in SLOTS},
            "separate_shadow_arm": arms[SEPARATE],
            "frozen_baselines": {name: arms[name] for name in ("parent", "retrieval")},
            "first_attempt_opportunity": fixed_union(arms), "binding_errors": errors,
            "source_growth": growth, "source_growth_projection": {
                "source": "the six actual authored A records; original source/task/lineage identities",
                "observation_digest": "SHA256 of actual prepared task input UTF-8 bytes",
                "readiness": None, "updates_per_source_64": "planning parameter only; no growth cohorts executed"},
            "cost_ledger": ledger, "coordinator_cost_separate_not_added": terminal.get("cost") if terminal else None,
            "historical_parent_cost_added": False, "diagnostic_model_calls": 0, "diagnostic_reference_calls": 0,
            "writer_stop_authentication_performed": False, "atomic_snapshot_claimed": False,
            "scope": "exploratory after observed baseline failure; old exposed A/B only; no E3/E4/E5/E6 or PoUW qualification",
            **SCOPE}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("freeze", "diagnostic-freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("freeze-sha256", "diagnostic-freeze-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    require(sys.dont_write_bytecode and sys.flags.isolated, "use Python -I -B")
    reader = Reader(WORKSPACE)
    output = reader.path(args.output)
    require(output == WORKSPACE / "research-diagnostic-02", "fixed diagnostic output required")
    output.mkdir(exist_ok=False)
    try:
        freeze = sealed(reader.read(args.freeze, args.freeze_sha256))
        rules = reader.read(args.diagnostic_freeze, args.diagnostic_freeze_sha256)
        source_sha = reader.hash(Path(__file__).absolute())["sha256"]
        validate_rules(rules, source_sha)
        run = reader.path(freeze["output"])
        require(run == WORKSPACE / "research-sft-02" and args.freeze == run / "FREEZE.json"
                and freeze.get("schema") == "hepta.research-sft-freeze.v1"
                and freeze.get("status") == "REFERENCE_ADMITTED"
                and freeze.get("diagnostic_freeze") == {
                    "path": str(args.diagnostic_freeze), "sha256": args.diagnostic_freeze_sha256},
                "operation/frozen diagnostic binding differs")
        result = diagnose(reader, freeze, run)
        inventory = reader.recheck()
        binding = {"schema": "hepta.research-diagnostic-read-inventory.v1",
                   "files": inventory, "file_count": len(inventory),
                   "scope": "exact selected files read and rehashed; no future history or atomic snapshot claim"}
        write_new(output / "INPUT_BINDINGS.json", binding)
        result.update(diagnostic_freeze_sha256=args.diagnostic_freeze_sha256,
                      diagnostic_source_sha256=source_sha, input_bindings_digest=digest(binding),
                      completed_at_ns=time.time_ns())
        write_new(output / "DIAGNOSTIC.json", {**result, "receipt_sha256": digest(result)})
        print(canonical({"status": result["status"], "output": str(output)}).decode(), flush=True)
    except BaseException as error:
        write_new(output / "FAILED.json", {"status": "DIAGNOSTIC_FAILED_PRESERVED", "error": repr(error),
                  "read_files": reader.observed, "raw_read_errors": reader.errors,
                  "model_calls": 0, "reference_calls": 0, "automatic_retry": False, **SCOPE})
        raise


if __name__ == "__main__":
    main()
