"""Newly registered finite diagnostics; no training, scoring, or checkpoint restore.

This is a 2026-10-30 implementation, not recovered bytes of the lost 2026-10-29
supplement. Only stdlib is imported until the complete-study metadata gate passes.
"""

import argparse
import ast
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import stat
import statistics
import sys
import time


PREFIX = "experiments/parameter_field_fullstudy_20261029/"
EPISODE = "execution04_durable_20261030"
ATTEMPT = "attempt02"  # Preserved original operational API identity, not episode 02.
PLAN_SCHEMA = "hepta.fullstudy.postseal-plan.2"
PIPELINE_SCHEMA = "hepta.fullstudy.pipeline-completion.4"
PROTOCOL_SHA = "2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55"
SEEDS = (17, 29, 43)
MODES = ("field12", "full_current_state", "history6")
DIMENSIONS = {"field12": 12, "full_current_state": 54740, "history6": 114}
BASELINES = {17: 2, 29: 3, 43: 3}
PHASES = ("A", "B", "C", "W", "R")
COMPONENTS = ("parameters", "momentum", "gradients", "buffers")
PHASE_FREEZES = {
    "A": "2a5219147d38ebb6514059bd69e2d3489bf7d69d213cd01343455f63a08a53d2",
    "C": "5f427c8a8cebe8c96a2a0d81318e22d286dc0aaa8b3dbf4d5844df2177949c6d",
}
FROZEN_SOURCES = {
    PREFIX + "heads.py": "19254959a30e3719024841dc91376d1ecdfa018c30427b962a265e3b3d4647f7",
    PREFIX + "bank.py": "710a9a069f2d8bdbb208e16db62bc55fb1a07cbd3f9686546b46056673402653",
    PREFIX + "branching.py": "3825744797572e8a28aedec57fb0e6ed924586ea4b3c0f49accb0bf7bfbeee79",
    PREFIX + "witness.py": "7f81ff7660e3bb4a99e9b7b4addf2705b2f55bffd3e80c6d47ef5737278f7f08",
    PREFIX + "run.py": "46f437e8756c83ae1abfedb7b36544f71a86093098363a8730b18357bf36c1c3",
    PREFIX + "report_results.py": "ccfe0f9fa555906f9cda0834424a5396c7146f523a47a4cd8696134d007e614f",
    PREFIX + "analysis.py": "46ace84fa720026daa2f0b9de95b8c446f4e87ae6f1873ba43e9bceaca3f73e2",
    PREFIX + "finalize_v2.py": "6fbf4a7a994120b6c0ae577a10d9ba992ad483d253ff0afb9aea42af8bb705ac",
    PREFIX + "register_summary_v2.py": "b20351ee0a242bf25352d67a912af3a3dcb6d7503c8e38f9973a437bb3d20184",
    PREFIX + "analysis_launch_v2.py": "708003e123a97dbf17f8ba1fd2f7086ec70fc52f2f6a1dc41bf88c6882d4fdbb",
    "experiments/multimodal_output_portfolio/field_bridge_v3_20261027/learning.py":
        "97c3baabe208fd8d5e8ac9beb5ae4a244b3c8d6aac565e727fd64eed8c1371b7",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha_valid(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_relative(value):
    require(isinstance(value, str) and bool(value), "Empty relative path")
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == value
            and value != ".", "Unsafe or noncanonical relative path")
    return value


def regular(path):
    path = Path(path).absolute()
    require(path.resolve(strict=True) == path and stat.S_ISREG(path.lstat().st_mode),
            "Input must be regular without symlink traversal: " + str(path))
    return path


def fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def disjoint(left, right):
    return left != right and not left.is_relative_to(right) and not right.is_relative_to(left)


def finite_json(stream):
    def reject(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    return json.load(stream, parse_constant=reject)


class Inputs:
    """Hash and consume the same descriptor, with before/after metadata checks."""

    def __init__(self):
        self.rows = {}

    @contextmanager
    def opened(self, path, expected_sha, expected_bytes=None, role="metadata"):
        require(sha_valid(expected_sha), "Externally fixed or sealed SHA256 required")
        path = regular(path)
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            require(fingerprint(path.stat()) == fingerprint(before), "Input changed before hashing")
            require(expected_bytes is None or before.st_size == expected_bytes, "Input byte count differs")
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
            require(actual == expected_sha and fingerprint(path.stat()) == fingerprint(before),
                    "Input hash or metadata differs: " + str(path))
            stream.seek(0)
            previous = self.rows.get(str(path))
            require(previous is None or previous["sha256"] == actual, "Conflicting input identities")
            if previous is None:
                self.rows[str(path)] = {"path": str(path), "bytes": before.st_size, "sha256": actual,
                    "fingerprint": list(fingerprint(before)), "roles": [role]}
            elif role not in previous["roles"]:
                previous["roles"].append(role)
            yield stream
            require(fingerprint(os.fstat(stream.fileno())) == fingerprint(path.stat()) == fingerprint(before),
                    "Consumed input changed: " + str(path))

    def read_json(self, path, digest, size=None, role="metadata"):
        with self.opened(path, digest, size, role) as stream:
            return finite_json(stream)

    def hash_only(self, path, digest, size=None, role="sealed_identity"):
        with self.opened(path, digest, size, role):
            pass

    def descriptor(self, path):
        row = self.rows[str(Path(path).absolute())]
        return {key: row[key] for key in ("path", "bytes", "sha256")}

    def descriptor_json(self, item, role):
        require(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"}
                and type(item["bytes"]) is int and item["bytes"] >= 0, "Malformed external descriptor")
        return self.read_json(item["path"], item["sha256"], item["bytes"], role)

    def unchanged(self):
        for row in self.rows.values():
            require(list(fingerprint(regular(row["path"]).stat())) == row["fingerprint"],
                    "Consumed input changed before supplement completion")


class SealedRaw:
    """No scientific JSON or arrays may be decoded before admit() is called."""

    def __init__(self, root, entries, inputs):
        self.root, self.entries, self.inputs, self.admitted = root, entries, inputs, False

    def descriptor(self, relative, absolute=True):
        relative = safe_relative(relative)
        require(relative in self.entries, "Artifact absent from fixed manifest: " + relative)
        entry = self.entries[relative]
        return {"path": str(self.root / relative) if absolute else relative,
                "bytes": entry["bytes"], "sha256": entry["sha256"]}

    def metadata(self, relative):
        permitted = (relative == "controller/EXECUTION.json" or
            re.fullmatch(r"operations/(?:[ABR]-seed-(?:17|29|43)|[CW]-all)\.COMPLETE\.json", relative) or
            re.fullmatch(r"analysis_operations/[A-Za-z0-9]+/(?:COMPLETE|WORKER_COMPLETE)\.json", relative))
        require(permitted, "Not a permitted pre-gate metadata file")
        return self.inputs.descriptor_json(self.descriptor(relative), "completion_metadata")

    def admit(self):
        self.admitted = True

    def read_json(self, relative):
        require(self.admitted, "Scientific payload read blocked before complete-study gate")
        return self.inputs.descriptor_json(self.descriptor(relative), "sealed_scientific_diagnostic")

    @contextmanager
    def npz(self, relative, np):
        require(self.admitted, "Array read blocked before complete-study gate")
        item = self.descriptor(relative)
        with self.inputs.opened(item["path"], item["sha256"], item["bytes"], "sealed_diagnostic_array") as stream:
            with np.load(stream, allow_pickle=False) as saved:
                yield saved


def required_seals():
    names, jobs = {"controller/EXECUTION.json"}, {}
    for phase in PHASES:
        for seed in SEEDS if phase in ("A", "B", "R") else (None,):
            token = f"{phase}-seed-{seed}" if seed is not None else f"{phase}-all"
            operation = f"operations/{token}.COMPLETE.json"
            science = f"stage_{phase}/seed-{seed}/COMPLETE.json" if seed is not None else f"stage_{phase}/COMPLETE.json"
            names.update((operation, science))
            jobs[f"{phase}-{seed}" if seed is not None else phase] = operation
        if phase in ("A", "B", "C"):
            endpoint = f"stage_{phase}/" + ("endpoint_evaluation" if phase == "C" else "endpoints") + "/ENDPOINTS.json"
            names.add(endpoint)
            jobs[phase + "_endpoint"] = endpoint
    require(len(names) == 26 and len(jobs) == 14, "Internal fixed-population error")
    return names, jobs


def verify_original_sources(source, plan, finalizer, inputs):
    require(plan["frozen_sources"] == FROZEN_SOURCES and plan["original_phase_freezes"] == PHASE_FREEZES,
            "Original diagnostic source or phase pins changed")
    union = {}
    for phase, digest in PHASE_FREEZES.items():
        relative = PREFIX + f"registrations/{phase}_SOURCE_FREEZE.json"
        ancestor = inputs.read_json(source / relative, digest, role="original_phase_source_freeze")
        require(ancestor["protocol_sha256"] == PROTOCOL_SHA, "Original phase protocol differs")
        for path, value in ancestor["source_files"].items():
            safe_relative(path)
            require(path not in union or union[path] == value, "Original phase source conflict")
            union[path] = value
    for path, value in FROZEN_SOURCES.items():
        require(path not in union or union[path] == value, "Original and diagnostic source pins conflict")
        union[path] = value
    for relative, digest in union.items():
        require(finalizer["source_files"].get(relative) == digest,
                "Finalizer lacks original source identity: " + relative)
        inputs.hash_only(source / relative, digest, role="unchanged_original_source")
    return len(union)


def gate(args, inputs, output):
    """Only explicit metadata and streaming identity hashes before full admission."""
    root, source = Path(args.raw_root).resolve(strict=True), Path(args.source_root).resolve(strict=True)
    plan = inputs.read_json(args.plan, args.expected_plan_sha256, role="new_pre_endpoint_plan")
    require(plan.get("schema") == PLAN_SCHEMA and plan.get("status") == "PRE_ENDPOINT"
            and plan.get("execution_episode") == EPISODE and plan.get("attempt_id") == ATTEMPT
            and plan.get("protocol_sha256") == PROTOCOL_SHA
            and plan.get("new_implementation_not_recovered_old_bytes") is True
            and plan.get("scientific_payloads_opened_during_preparation") is False, "Wrong supplement declaration")
    require(str(root) == plan["execution_context"]["raw_root"]
            and str(source) == plan["execution_context"]["source_root"], "Registered roots differ")
    operations = Path(plan["execution_context"]["operations_root"]).resolve()
    require(all(disjoint(output, p) for p in (root, source, operations)), "Output overlaps a protected root")
    inputs.hash_only(__file__, plan["implementation"]["sha256"], plan["implementation"]["bytes"], "new_supplement_source")

    pipeline = inputs.read_json(args.pipeline_complete, args.expected_pipeline_sha256, role="pipeline_completion")
    require(Path(args.pipeline_complete).name == "COMPLETE.json"
            and pipeline.get("schema") == PIPELINE_SCHEMA and pipeline.get("complete") is True
            and pipeline.get("execution_episode") == EPISODE
            and not Path(args.pipeline_complete).with_name("FAILED.json").exists(), "Primary pipeline is not complete")
    artifacts = pipeline.get("artifacts", {})
    require(set(artifacts) == {"verified", "manifest", "aggregate_results", "finalizer_freeze"},
            "Pipeline public artifact interface differs")
    verified = inputs.read_json(args.verified, args.expected_verified_sha256, role="literal_verification")
    manifest = inputs.read_json(args.manifest, args.expected_manifest_sha256, role="literal_manifest")
    finalizer = inputs.read_json(args.finalizer_freeze, args.expected_finalizer_sha256, role="finalizer_freeze")
    for key, path in (("verified", args.verified), ("manifest", args.manifest), ("finalizer_freeze", args.finalizer_freeze)):
        require(artifacts[key] == inputs.descriptor(path), "Pipeline does not bind actual " + key)
    manifest_path, verified_path = regular(args.manifest), regular(args.verified)
    require(manifest_path.is_relative_to(root) and manifest_path.name == "MANIFEST.json"
            and verified_path.name == "VERIFIED.json" and verified_path.parent == manifest_path.parent
            and not verified_path.with_name("FAILED.json").exists(), "Wrong or failed finalization location")
    manifest_relative = {**inputs.descriptor(args.manifest), "path": manifest_path.relative_to(root).as_posix()}
    require(verified.get("schema") == "hepta.fullstudy.cas-literal-verification.1"
            and verified.get("archive_verification_complete") is True
            and verified.get("temporary_directory_removed_after_success") is True
            and verified.get("manifest") == manifest_relative
            and manifest.get("schema") == "hepta.fullstudy.cas-container-manifest.1"
            and manifest.get("attempt_id") == ATTEMPT and Path(manifest["root"]).resolve() == root
            and manifest.get("binding") == verified.get("binding")
            and manifest.get("all_raw_root_artifacts_and_failures_included") is True, "Literal verification binding differs")
    cas = Path(manifest["cas_root"]).resolve()
    require(cas == root.with_name(root.name + "_cas") and disjoint(output, cas), "Wrong CAS or overlapping output")
    entries = manifest["logical_paths"]
    require(isinstance(entries, dict) and entries, "Empty literal manifest")
    for relative, item in entries.items():
        safe_relative(relative)
        require(type(item["bytes"]) is int and item["bytes"] >= 0 and sha_valid(item["sha256"])
                and item["storage"] in ("cas", "direct")
                and item["blob"] == (item["sha256"] if item["storage"] == "cas" else None), "Malformed literal entry")
    require(manifest["logical_artifact_count"] == verified["logical_files_restored"] == len(entries)
            and manifest["logical_artifact_bytes"] == verified["logical_bytes_restored"] == sum(x["bytes"] for x in entries.values())
            and verified["logical_paths_verified"] == sorted(entries), "Literal restore population is incomplete")

    binding = verified["binding"]
    require(binding.get("source_freeze_sha256") == args.expected_finalizer_sha256
            and binding.get("attempt_id") == ATTEMPT and sha_valid(binding.get("operational_amendment_sha256"))
            and finalizer.get("execution_kind") == "evidence_finalization" and finalizer.get("allowed_phases") == ["FINALIZE"]
            and finalizer.get("attempt_id") == ATTEMPT and finalizer.get("protocol_sha256") == PROTOCOL_SHA
            and finalizer.get("registered_commit") == binding.get("registered_commit")
            and re.fullmatch(r"[0-9a-f]{40}", str(binding.get("registered_commit")))
            and finalizer.get("operational_amendment_sha256") == binding["operational_amendment_sha256"],
            "Finalizer source/protocol/operational ancestry differs")
    aggregate_desc = finalizer["actual_aggregate_source_freeze"]
    require(disjoint(output, Path(aggregate_desc["path"]).resolve().parent), "Output overlaps aggregate registration")
    aggregate = inputs.descriptor_json(aggregate_desc, "aggregate_source_freeze")
    analysis_id = aggregate.get("analysis_id", "")
    require(re.fullmatch(r"[A-Za-z0-9]+", analysis_id) and aggregate.get("execution_kind") == "aggregate_analysis"
            and aggregate.get("allowed_phases") == ["ANALYSIS"] and aggregate.get("attempt_id") == ATTEMPT
            and aggregate.get("protocol_sha256") == PROTOCOL_SHA
            and aggregate.get("report_module") == "experiments.parameter_field_fullstudy_20261029.report_results"
            and aggregate.get("operational_amendment_sha256") == binding["operational_amendment_sha256"],
            "Aggregate registration differs")
    output_relative = safe_relative(aggregate["output_relative"])
    report_inputs = aggregate["report_inputs"]
    require(disjoint(output, Path(report_inputs["path"]).resolve().parent), "Output overlaps report-input registration")
    inputs.hash_only(report_inputs["path"], report_inputs["sha256"], report_inputs["bytes"], "registered_report_inputs")
    store = SealedRaw(root, entries, inputs)
    science_names, jobs = required_seals()
    control = f"analysis_operations/{analysis_id}"
    aggregate_names = {control + "/COMPLETE.json", control + "/WORKER_COMPLETE.json",
                       output_relative + "/RESULTS.json", output_relative + "/REPORT.md"}
    all_names = science_names | aggregate_names
    expected = {str(root / name): store.descriptor(name)["sha256"] for name in all_names}
    require(len(expected) == 30 and finalizer.get("required_scientific_seals") == expected
            and aggregate.get("required_scientific_seals") == {str(root / n): expected[str(root / n)] for n in science_names}
            and all(finalizer.get("artifacts", {}).get(path) == digest for path, digest in expected.items()),
            "Exact 30/26 scientific completion seals differ")
    require(artifacts["aggregate_results"] == store.descriptor(output_relative + "/RESULTS.json"),
            "Pipeline binds another scientific report")
    for name in sorted(all_names):
        item = store.descriptor(name)
        failure = (root / name).with_name("FAILED.json")
        if name.startswith("operations/"):
            failure = (root / name).with_name(Path(name).name.replace(".COMPLETE.json", ".FAILED.json"))
        require(not failure.exists(), "Failure marker blocks completed interpretation: " + name)
        inputs.hash_only(item["path"], item["sha256"], item["bytes"], "whole_study_seal")
    execution = store.metadata("controller/EXECUTION.json")
    require(execution.get("complete") is True and execution.get("oom_admission_paused") is False
            and set(execution["jobs"]) == set(jobs), "Fourteen-job controller incomplete")
    for job, name in jobs.items():
        row = execution["jobs"][job]
        require(row.get("complete") is True and row.get("exit_code") == 0
                and row.get("completion") == store.descriptor(name, absolute=False), "Unsealed controller job: " + job)
    for phase in PHASES:
        for seed in SEEDS if phase in ("A", "B", "R") else (None,):
            token = f"{phase}-seed-{seed}" if seed is not None else f"{phase}-all"
            op = store.metadata(f"operations/{token}.COMPLETE.json")
            name = f"stage_{phase}/seed-{seed}/COMPLETE.json" if seed is not None else f"stage_{phase}/COMPLETE.json"
            require(op.get("complete") is True and op.get("post_execution_storage_check") is True
                    and op.get("attempt_id") == ATTEMPT and op.get("phase") == phase and op.get("seed") == seed
                    and op.get("scientific_source_bytes_unchanged") is True
                    and op.get("scientific_protocol_sha256") == PROTOCOL_SHA
                    and op.get("operational_amendment_sha256") == binding["operational_amendment_sha256"]
                    and op.get("scientific_complete") == store.descriptor(name, absolute=False), "Scientific operation differs")
    complete, worker = store.metadata(control + "/COMPLETE.json"), store.metadata(control + "/WORKER_COMPLETE.json")
    require(complete.get("worker_receipt") == store.descriptor(control + "/WORKER_COMPLETE.json")
            and complete.get("outputs") == [store.descriptor(output_relative + "/" + n) for n in ("RESULTS.json", "REPORT.md")],
            "Aggregate outputs are not bound")
    for row in (complete, worker):
        require(row.get("complete") is True and row.get("post_execution_storage_check") is True
                and row.get("source_freeze_sha256") == aggregate_desc["sha256"]
                and row.get("report_inputs_sha256") == report_inputs["sha256"]
                and row.get("operational_amendment_sha256") == binding["operational_amendment_sha256"]
                and row.get("scheduled_gradient_microsteps") == 0 and row.get("endpoint_scoring_performed") is False
                and row.get("refitting_performed") is False, "Aggregate completion gate differs")
    count = verify_original_sources(source, plan, finalizer, inputs)
    protocol = inputs.read_json(source / PREFIX / "PROTOCOL.json", PROTOCOL_SHA, role="unchanged_scientific_protocol")
    store.admit()
    return plan, store, protocol, {"status": "FULL_PRIMARY_PIPELINE_AND_LITERAL_RESTORE_VERIFIED",
        "execution_episode": EPISODE, "admitted_at": utc(), "controller_jobs": 14, "completion_seals": 30,
        "original_source_files_verified": count, "pipeline": inputs.descriptor(args.pipeline_complete),
        "verified": inputs.descriptor(args.verified), "manifest": inputs.descriptor(args.manifest),
        "finalizer_freeze": inputs.descriptor(args.finalizer_freeze),
        "scientific_payloads_decoded_before_gate": False, "endpoint_arrays_decoded": False}


def vector4(values):
    require(isinstance(values, (list, tuple)) and len(values) == 4
            and all(type(v) in (float, int) and math.isfinite(v) for v in values), "Expected four finite values")
    return [float(value) for value in values]


def optimal_set(values):
    return [a for a, value in enumerate(values) if value == max(values)]


def witness_regrets(original, reflected):
    original, reflected = vector4(original), vector4(reflected)
    first, second = [max(original) - v for v in original], [max(reflected) - v for v in reflected]
    worst, average = [max(a, b) for a, b in zip(first, second)], [(a + b) / 2 for a, b in zip(first, second)]
    return {"original_best_actions": optimal_set(original), "reflected_best_actions": optimal_set(reflected),
        "common_best_actions": sorted(set(optimal_set(original)) & set(optimal_set(reflected))),
        "original_regret_by_action": first, "reflected_regret_by_action": second,
        "shared_deterministic_action_minimax_regret": min(worst),
        "minimax_actions": [a for a, value in enumerate(worst) if value == min(worst)],
        "equal_state_mixture_minimum_average_regret": min(average),
        "equal_state_mixture_optimal_actions": [a for a, value in enumerate(average) if value == min(average)],
        "shared_deterministic_action_restriction": True, "all_field_policy_lower_bound": False}


def equal_dynamics_checks(row, outputs):
    values, branches = vector4(row["action_values"]), row["branches"]
    require(len(branches) == 4 and {b["action"] for b in branches} == set(range(4))
            and set(outputs) == set(range(4)), "Incomplete four-action population")
    by_action, groups, details, issues = {b["action"]: b for b in branches}, defaultdict(list), [], []
    for branch in branches:
        groups[branch["first"]["dynamics"]].append(branch["action"])
        if branch["value"] != values[branch["action"]]:
            issues.append({"kind": "branch_value_differs_from_action_values", "actions": [branch["action"]]})
    for first, actions in sorted(groups.items()):
        actions = sorted(actions)
        reference = actions[0]
        checks = {
            "first_components_equal": all(by_action[a]["first"]["components"] == by_action[reference]["first"]["components"] for a in actions),
            "terminal_dynamics_equal": all(by_action[a]["terminal"]["dynamics"] == by_action[reference]["terminal"]["dynamics"] for a in actions),
            "action_values_equal": all(values[a] == values[reference] for a in actions),
            "output_hash_vectors_equal": all(outputs[a]["output_sha256"] == outputs[reference]["output_sha256"] for a in actions),
            "output_row_identities_equal": all((outputs[a]["source_ids"], outputs[a]["conditions"]) ==
                (outputs[reference]["source_ids"], outputs[reference]["conditions"]) for a in actions),
        }
        details.append({"first_dynamics": first, "actions": actions, "nontrivial": len(actions) > 1, **checks})
        issues.extend({"kind": "equal_first_dynamics_but_" + name.removesuffix("_equal") + "_differ",
                       "actions": actions, "first_dynamics": first} for name, equal in checks.items() if not equal)
    return details, issues


def numeric_summary(values):
    require(values and all(math.isfinite(v) for v in values), "Empty or nonfinite diagnostic")
    return {"n": len(values), "zero_count": sum(v == 0 for v in values), "nonzero_count": sum(v != 0 for v in values),
        "minimum": min(values), "median": statistics.median(values), "mean": statistics.fmean(values), "maximum": max(values)}


def frozen_choose(source, inputs, np):
    path = source / PREFIX / "heads.py"
    with inputs.opened(path, FROZEN_SOURCES[PREFIX + "heads.py"], role="exact_deployed_choose_source") as stream:
        module = ast.parse(stream.read().decode("utf-8"), filename=str(path))
    definitions = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in ("predict", "choose")]
    require([n.name for n in definitions] == ["predict", "choose"] and all(not n.decorator_list for n in definitions),
            "Frozen prediction/choice AST population differs")
    namespace = {"np": np}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["choose"]


def selection_metrics(head, feature, advantages, choose):
    values = vector4(advantages)
    action, choice = choose(head, feature)
    scores = vector4(choice["predicted_advantages"])
    return {"choice": choice, "exact_max_score_tie": scores.count(max(scores)) > 1,
        "optimal_action_set": optimal_set(values), "chosen_action_is_optimal": action in optimal_set(values),
        "gated_selection_regret": max(values) - values[action],
        "rowwise_ungated_selection_regret": max(values) - values[choice["greedy_action"]],
        "chosen_baseline_aligned_advantage": values[action], "attainable_gain": max(values)}


def parent_id(row):
    return f"schedule-{row['schedule_id']}-{row['prefix']}-step-{row['step']}"


def expected_parents():
    return [f"schedule-{s}-{p}-step-{t}" for s in range(6000, 6004)
            for p in ("baseline", "balanced") for t in range(0, 288, 48)]


def bank_analysis(store, np):
    banks, summaries, details, differences, issues = {}, [], [], [], []
    for seed in SEEDS:
        base = f"stage_A/seed-{seed}/bank/"
        bank = store.read_json(base + "BANK.json")
        require(bank.get("complete") is True and bank.get("seed") == seed and len(bank["records"]) == 48
                and [parent_id(r) for r in bank["records"]] == expected_parents(), "A parent population/order differs")
        banks[seed] = bank
        totals, measures = Counter(parents=48), defaultdict(lambda: {"l2": [], "max_abs": [], "zero_norm_representation_difference_count": 0})
        for row in bank["records"]:
            stem, baseline = parent_id(row), BASELINES[seed]
            require(row["baseline"] == baseline and row["prefix_replay_equal"] is True, "Parent baseline/replay differs")
            values, advantages = vector4(row["action_values"]), vector4(row["advantages"])
            if advantages != [v - values[baseline] for v in values]:
                issues.append({"seed": seed, "parent": stem, "kind": "advantage_arithmetic_differs"})
            outputs = {}
            for action in range(4):
                name = base + f"{stem}-action-{action}.npz"
                with store.npz(name, np) as saved:
                    data = {key: saved[key].tolist() for key in ("output_sha256", "source_ids", "conditions")}
                    require(data["output_sha256"] and len({len(v) for v in data.values()}) == 1
                            and all(sha_valid(v) for v in data["output_sha256"]), "Malformed saved output identity")
                    rewards = saved["values_reward"]
                    require(rewards.shape == (len(data["output_sha256"]),) and np.isfinite(rewards).all(), "Malformed saved branch rewards")
                    if float(rewards.mean()) != values[action]:
                        issues.append({"seed": seed, "parent": stem, "action": action, "kind": "saved_reward_mean_differs_from_label"})
                    data["artifact"] = store.descriptor(name)
                    outputs[action] = data
            groups, found = equal_dynamics_checks(row, outputs)
            issues.extend({"seed": seed, "parent": stem, **item} for item in found)
            totals.update(action_groups=len(groups), nontrivial_groups=sum(g["nontrivial"] for g in groups), integrity_issues=len(found))
            details.append({"seed": seed, "parent": stem, "parent_sha256": row["parent_sha256"],
                "baseline": baseline, "action_values": values, "advantages": advantages, "groups": groups,
                "outputs": {str(a): {"artifact": outputs[a]["artifact"], "output_vector_sha256":
                    sha_bytes(json.dumps(outputs[a]["output_sha256"], separators=(",", ":")).encode())} for a in range(4)}})
            require(set(row["first_legal_successor_differences"]) == {"0", "1", "2", "3"}, "Missing successor differences")
            accepted = {b["action"]: b["accepted"] for b in row["branches"]}
            for action in range(4):
                difference = row["first_legal_successor_differences"][str(action)]
                differences.append({"seed": seed, "parent": stem, "parent_clock": row["step"],
                    "successor_clock": row["step"] + 48, "action": action, "baseline": baseline,
                    "guard_accepted": accepted[action], "same_parent_baseline_reference": True, "difference": difference})
                for component in COMPONENTS:
                    data = difference[component]
                    require(all(type(data[k]) in (float, int) and math.isfinite(data[k]) and data[k] >= 0 for k in ("l2", "max_abs")),
                            "Invalid stored successor norm")
                    for subset in ("all_actions", "nonbaseline_actions") if action != baseline else ("all_actions",):
                        target = measures[(subset, component)]
                        for key in ("l2", "max_abs"):
                            target[key].append(data[key])
                        target["zero_norm_representation_difference_count"] += data["l2"] == 0 and data["first_different_tensor"] is not None
            # Absent-vs-zero momentum can change optimizer hash with zero numerical norm.
            totals["zero_momentum_norm_with_optimizer_component_difference"] += sum(
                row["first_legal_successor_differences"][str(a)]["momentum"]["l2"] == 0 and
                "optimizer" in row["first_legal_successor_differences"][str(a)]["different_components"] for a in range(4))
        summaries.append({"seed": seed, "counts": dict(totals), "successor_difference_summaries": {
            subset: {component: {**{k: numeric_summary(measures[(subset, component)][k]) for k in ("l2", "max_abs")},
                "zero_norm_representation_difference_count": measures[(subset, component)]["zero_norm_representation_difference_count"]}
                for component in COMPONENTS} for subset in ("all_actions", "nonbaseline_actions")}})
    return banks, summaries, details, differences, issues


def calibration_analysis(store, banks, np, choose):
    summaries, rows = [], []
    for seed in SEEDS:
        records = banks[seed]["records"]
        expected_y = np.asarray([r["advantages"] for r in records], dtype=np.float64)
        expected_fit = np.asarray([r["schedule_id"] != 6003 for r in records], dtype=bool)
        for mode in MODES:
            base = f"stage_A/seed-{seed}/bank/{mode}"
            with store.npz(base + "-head.npz", np) as saved:
                metadata = json.loads(saved["metadata_json"].item())
                require(metadata == banks[seed]["heads"][mode] and set(saved.files) == {"metadata_json", "mean", "scale", "coefficients", "intercept"},
                        "Head metadata or array population differs")
                head = {**metadata, **{key: saved[key].copy() for key in ("mean", "scale", "coefficients", "intercept")}}
            dimension = DIMENSIONS[mode]
            require(head["baseline"] == BASELINES[seed] and head["dimension"] == dimension
                    and head["fit_count"] == 36 and head["calibration_count"] == 12 and head["ridge"] == 1
                    and math.isfinite(head["threshold"]) and head["threshold"] >= 0
                    and head["mean"].shape == head["scale"].shape == (dimension,)
                    and head["coefficients"].shape == (dimension, 4) and head["intercept"].shape == (4,)
                    and all(np.isfinite(head[key]).all() for key in ("mean", "scale", "coefficients", "intercept"))
                    and (head["scale"] > 0).all(), "Frozen head contract differs")
            subset = []
            with store.npz(base + "-bank.npz", np) as saved:
                x, y, fit = saved["features"], saved["advantages"], saved["fit_mask"]
                require(x.shape == (48, dimension) and np.isfinite(x).all() and np.array_equal(y, expected_y)
                        and np.array_equal(fit, expected_fit), "Calibration row partition or labels differ")
                for index in np.flatnonzero(~expected_fit):
                    item = {"seed": seed, "mode": mode, "parent": parent_id(records[index]), "bank_row": int(index),
                        "baseline": BASELINES[seed], **selection_metrics(head, x[index], y[index].tolist(), choose)}
                    rows.append(item)
                    subset.append(item)
            require(len(subset) == 12, "Incomplete per-head calibration population")
            gain = statistics.fmean(r["attainable_gain"] for r in subset)
            regret = statistics.fmean(r["gated_selection_regret"] for r in subset)
            summaries.append({"seed": seed, "mode": mode, "calibration_rows": 12,
                "override_count": sum(r["choice"]["override"] for r in subset),
                "exact_max_score_tie_count": sum(r["exact_max_score_tie"] for r in subset),
                "fallback_counts": dict(Counter(r["choice"]["fallback_reason"] or "no_fallback" for r in subset)),
                "outside_fit_norm_count": sum(r["choice"]["outside_fit_norm"] for r in subset),
                "outside_fit_norm_forces_fallback": False,
                "gated_regret": numeric_summary([r["gated_selection_regret"] for r in subset]),
                "mean_gated_regret_over_mean_attainable_gain": regret / gain if gain > 0 else None,
                "gated_optimal_set_accuracy": sum(r["chosen_action_is_optimal"] for r in subset) / 12,
                "mean_chosen_advantage": statistics.fmean(r["chosen_baseline_aligned_advantage"] for r in subset),
                "mean_attainable_gain": gain,
                "rowwise_ungated_mean_regret": statistics.fmean(r["rowwise_ungated_selection_regret"] for r in subset),
                "original_batched_ungated_diagnostics": metadata["diagnostics"],
                "calibration_rows_dependent_and_used_to_choose_tau": True, "new_independent_samples": 0, "certificate": False})
            del head, x, y, fit
    require(len(rows) == 108 and len({(r["seed"], r["parent"]) for r in rows}) == 36, "Fixed calibration population differs")
    return summaries, rows


def witness_analysis(store, banks):
    complete = store.read_json("stage_W/COMPLETE.json")
    require(complete.get("complete") is True and complete.get("schema") == "hepta.fullstudy.constructed-momentum-witness.1"
            and len(complete["records"]) == 3 and {r["seed"] for r in complete["records"]} == set(SEEDS), "Incomplete W population")
    results, issues = [], []
    for record in sorted(complete["records"], key=lambda r: r["seed"]):
        seed = record["seed"]
        require(record["parent"] == {"schedule": 6000, "prefix": "baseline", "clock": 48}
                and record["constructed_off_policy"] is True and record["reachable_state_guarantee"] is False,
                "W construction differs")
        original = next(r for r in banks[seed]["records"] if parent_id(r) == "schedule-6000-baseline-step-48")
        if record["original_action_values"] != original["action_values"]:
            issues.append({"seed": seed, "kind": "W_original_values_differ_from_sealed_A_parent"})
        require(record["original_bank_sha256"] == store.descriptor(f"stage_A/seed-{seed}/bank/BANK.json")["sha256"]
                and record["original_head_sha256"] == store.descriptor(f"stage_A/seed-{seed}/bank/field12-head.npz")["sha256"],
                "W binds a different bank/head")
        results.append({"seed": seed, "parent": record["parent"],
            **witness_regrets(record["original_action_values"], record["reflected_action_values"]),
            **{k: record[k] for k in ("original_action_values", "reflected_action_values", "field_before", "field_after",
                "absolute_field_drift", "normalized_field_drift", "near_field", "near_field_tolerance", "head_choices")},
            "field_coordinate_values_exactly_equal": record["field_before"] == record["field_after"],
            "recorded_ranking_changed": record["ranking_changed"], "recorded_best_action_set_changed": record["best_action_set_changed"],
            "recorded_head_choices_same": record["head_choices"]["original"] == record["head_choices"]["reflected"],
            "constructed_off_policy": True, "reachable_state_guarantee": False,
            "interpretation": "Finite pair with a hypothetical common deterministic action. Near H12 is not identical input; no all-field-policy lower bound."})
    return results, issues


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_jsonl(path, rows):
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def costs(wall, cpu):
    return {"wall_seconds": time.monotonic() - wall, "cpu_seconds": time.process_time() - cpu,
        "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
        "scheduled_gradient_microsteps": 0, "endpoint_scoring_calls": 0, "head_fits": 0, "new_independent_samples": 0,
        "scope": "Supplement only; exclude from overlapping inclusive wrapper totals; historical costs remain unchanged."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("raw-root", "source-root", "plan", "expected-plan-sha256", "pipeline-complete", "expected-pipeline-sha256",
                 "verified", "expected-verified-sha256", "manifest", "expected-manifest-sha256",
                 "finalizer-freeze", "expected-finalizer-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--execute-post-seal", action="store_true")
    args = parser.parse_args()
    wall, cpu, started = time.monotonic(), time.process_time(), utc()
    inputs, output, admitted, created = Inputs(), Path(args.output).resolve(), False, False
    try:
        require(args.execute_post_seal, "Explicit post-seal execution required")
        root = Path(args.raw_root).resolve()
        protected = [root, root.with_name(root.name + "_cas"), Path(args.source_root).resolve(), Path(__file__).resolve().parent]
        protected += [Path(getattr(args, k)).resolve().parent for k in ("plan", "pipeline_complete", "verified", "manifest", "finalizer_freeze")]
        require(not output.exists() and all(disjoint(output, p) for p in protected), "Output exists or overlaps protected inputs")
        plan, store, protocol, gate_receipt = gate(args, inputs, output)
        admitted = True
        # No output directory is created until every protected registration and CAS
        # location has also been checked by the complete metadata gate.
        output.mkdir(parents=True, exist_ok=False)
        created = True
        write_json(output / "GATE.json", gate_receipt)
        import numpy as np  # Only after all primary completion/literal/source gates.
        choose = frozen_choose(Path(args.source_root).resolve(), inputs, np)
        banks, summaries, details, differences, issues = bank_analysis(store, np)
        calibration, calibration_rows = calibration_analysis(store, banks, np, choose)
        witness, witness_issues = witness_analysis(store, banks)
        issues.extend(witness_issues)
        write_json(output / "BANK_SUMMARY.json", {"models": summaries,
            "resolution": {"A_B_guard_boundary_microsteps": protocol["shared_guard48_learning"]["macro_steps"],
                "A_B_horizon": protocol["shared_guard48_learning"]["scheduled_microsteps"],
                "C_adaptation_unchanged": protocol["stage_C"]["adaptation_steps_and_guard"]},
            "optimizer_numeric_component": "momentum; absence/presence additionally visible in optimizer component hash",
            "warning": "Recorded transaction-boundary norms only; no checkpoint reload. Zero numeric norm need not mean equal representations."})
        write_jsonl(output / "EQUAL_DYNAMICS_GROUPS.jsonl", details)
        write_jsonl(output / "SUCCESSOR_DIFFERENCES.jsonl", differences)
        write_json(output / "GATED_CALIBRATION.json", {"models_and_modes": calibration,
            "registered_parent_slots": 36, "head_mode_rows": 108, "new_independent_samples": 0,
            "warning": "The same dependent calibration parents selected tau. Original diagnostics used batched ungated argmax; deployed AST is evaluated rowwise. No refit, extra validation, or uniform certificate."})
        write_jsonl(output / "GATED_CALIBRATION_ROWS.jsonl", calibration_rows)
        write_json(output / "W_SHARED_ACTION_REGRET.json", {"records": witness,
            "scope": "A shared deterministic action for the two fixed constructed states; 50:50 state mixture. Randomized minimax can differ. Near-field does not force identical controller inputs or establish reachable occupancy."})
        write_json(output / "INTEGRITY_ISSUES.json", {"issue_count": len(issues), "issues": issues,
            "any_issue_precludes_unqualified_interpretation": True, "primary_results_not_rewritten": True})
        inputs.unchanged()
        write_json(output / "INPUTS.json", {"inputs": list(inputs.rows.values()), "all_consumed_bytes_sha_verified": True,
            "metadata_stable_at_end": True, "raw_inputs_modified": False})
        outputs = []
        for path in sorted(output.iterdir()):
            with path.open("rb") as stream:
                outputs.append({"path": path.name, "bytes": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()})
        result = {"schema": "hepta.fullstudy.postseal-supplement.2", "complete": True,
            "status": "COMPLETE_WITH_INTEGRITY_ISSUES" if issues else "COMPLETE_DESCRIPTIVE_SUPPLEMENT",
            "execution_episode": EPISODE, "new_implementation_not_recovered_old_bytes": True,
            "started_at": started, "completed_at": utc(), "plan": inputs.descriptor(args.plan), "gate": gate_receipt,
            "outputs": outputs, "integrity_issue_count": len(issues), "costs": costs(wall, cpu),
            "runtime": {"python": sys.version, "numpy": np.__version__}, "endpoint_arrays_decoded": False,
            "scientific_admission_criteria_changed": False, "new_independent_samples": 0}
        write_json(output / "COMPLETE.json", result)
        print(json.dumps({"status": result["status"], "output": str(output), "integrity_issue_count": len(issues)}))
        return 3 if issues else 0
    except BaseException as error:
        failure = {"complete": False, "status": "FAILED_AFTER_GATE" if admitted else "BLOCKED_BEFORE_SCIENTIFIC_READ",
            "execution_episode": EPISODE, "error_type": type(error).__name__, "message": str(error),
            "started_at": started, "failed_at": utc(), "costs": costs(wall, cpu),
            "consumed_inputs": list(inputs.rows.values()), "partial_supplement_retained": created,
            "output_directory_created": created, "raw_inputs_modified": False}
        if created:
            try:
                write_json(output / "FAILED.json", failure)
            except OSError as receipt_error:
                failure["failure_receipt_write_error"] = str(receipt_error)
        print(json.dumps(failure, allow_nan=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
