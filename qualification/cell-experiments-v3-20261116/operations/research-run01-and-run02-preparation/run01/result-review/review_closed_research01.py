"""Read-only review of closed research01 receipts. No model, tokenizer or verifier runs."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

ROOT = Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
CLOSED = ROOT / "research-final-evidence-01"
EXPORT = ROOT / "research-final-export-01"
OUT = ROOT / "research-results-review-01"
RUN = "research-sft-01"
COLLECT = RUN + "/workers/corrections-collect"
RAM = "/dev/shm/hepta-cell-experiments-v3-20261116-0c078a"
ARMS = ("final_answer", "trajectory", "shadow_correction", "controlled_correction")
ALL_ARMS = ("parent", "retrieval") + ARMS
EXPECTED_MANIFEST = "785f5f4c4bfbb9f5c68131cfe1116c870274dd0cb7ec9473c671ebe38af039cf"
EXPECTED_ZIP = "3b6b10a9bfdcb2cf3c7df965dd45e5cac3143463b3b8a615ff544aeb417b437a"
EXPECTED_FREEZE = "ff08f18b0479ae089303787ec71013d558cf057b685e9c93432504877364db41"
EXPECTED_RESULT = "bbb77cb25b2f7e28caa3a71f7112d549734b3ff8bbdd32b562fc2bbbf5bc0e33"
EXPECTED_DIAG = "b623702d5611bd24bd3f9736300938c6e02f2ec75bed838962d33b05e6b7af37"
QUALIFICATIONS = ("scientific_confirmation_qualified", "native_cell_adoption",
                  "proof_of_useful_work_eligible", "circuit_qualified", "new_C")
reads, failures, checked, categories = {}, [], 0, {}
start_ns = time.time_ns()

def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

def digest(v):
    return hashlib.sha256(canonical(v)).hexdigest()

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None

def check(value, label, category="binding"):
    global checked
    checked += 1
    categories[category] = categories.get(category, 0) + 1
    if not value:
        failures.append({"check": label, "category": category})
    return bool(value)

def plain_bytes(path):
    path = Path(path)
    for parent in (path,) + tuple(path.parents):
        if parent == ROOT.parent:
            break
        require(not parent.is_symlink(), "symlink in read path: " + str(parent))
    st = path.stat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "regular exclusive file required")
    require(st.st_size <= 8 * 1024 * 1024, "bounded evidence read required")
    content = path.read_bytes()
    after = path.stat()
    require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "file changed")
    return content

manifest_raw = plain_bytes(EXPORT / "TRANSFER_MANIFEST.json")
require(hashlib.sha256(manifest_raw).hexdigest() == EXPECTED_MANIFEST, "closed manifest differs")
manifest = json.loads(manifest_raw)
members_raw = plain_bytes(EXPORT / "MEMBERS.jsonl")
require(hashlib.sha256(members_raw).hexdigest() == manifest["members"]["sha256"],
        "member list differs")
members_list = [json.loads(line) for line in members_raw.splitlines()]
members = {x["path"]: x for x in members_list}
require(len(members) == len(members_list) == manifest["member_count"] == 694,
        "archive member inventory differs")
archive_raw = plain_bytes(EXPORT / manifest["archive"]["transport_path"])
require(len(archive_raw) == manifest["archive"]["bytes"] == 1590081 and
        hashlib.sha256(archive_raw).hexdigest() == manifest["archive"]["sha256"] == EXPECTED_ZIP,
        "closed ZIP identity differs")
del archive_raw

def raw(rel):
    p = Path(rel)
    require(not p.is_absolute() and ".." not in p.parts, "relative archive member required")
    require(rel in members, "missing closed archive member: " + rel)
    content = plain_bytes(CLOSED / p)
    identity = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    require(identity["bytes"] == members[rel]["bytes"] and
            identity["sha256"] == members[rel]["sha256"], "archive/extracted file mismatch: " + rel)
    reads[rel] = identity
    return content

def read(rel):
    return json.loads(raw(rel))

def sealed(value, label, exclusions=("receipt_sha256",)):
    return check(value.get("receipt_sha256") ==
                 digest({k: v for k, v in value.items() if k not in exclusions}),
                 label + ": inner receipt", "receipt")

def scoped(value, label):
    for key in QUALIFICATIONS:
        check(value.get(key) is False, label + ": " + key, "qualification")
    check(value.get("candidate_selected") is None, label + ": candidate_selected", "qualification")

freeze = read(RUN + "/FREEZE.json")
result = read(RUN + "/RESULT.json")
diag = read("research-diagnostic-01/DIAGNOSTIC.json")
check(reads[RUN + "/FREEZE.json"]["sha256"] == EXPECTED_FREEZE, "frozen operation identity")
check(reads[RUN + "/RESULT.json"]["sha256"] == EXPECTED_RESULT, "operation result identity")
check(reads["research-diagnostic-01/DIAGNOSTIC.json"]["sha256"] == EXPECTED_DIAG, "diagnostic identity")
sealed(freeze, "freeze")
sealed(result, "result")
sealed(diag, "diagnostic")
for label, value in (("freeze", freeze), ("result", result), ("diagnostic", diag)):
    scoped(value, label)
check(result["freeze_digest"] == diag["freeze_digest"] == digest(freeze), "freeze semantic digest")
check(result["status"] == "RESEARCH_PARTIAL_UNQUALIFIED" and
      diag["status"] == "RESEARCH_DIAGNOSTIC_COMPLETE_UNQUALIFIED", "partial/unqualified status")
check(diag["binding_errors"] == [], "diagnostic binding errors absent")

source_paths = {
    "business": "candidate-qwen-03/scripts/cell_experiments/circuit_receipts_v3.py",
    "data": "candidate-qwen-03/scripts/cell_experiments/data.py",
    "probe": "candidate-qwen-03/scripts/cell_experiments/causal_probe_v3.py",
    "correction": "candidate-qwen-03/scripts/cell_experiments/repo_interaction_v2.py",
    "verifier": "candidate-qwen-03/scripts/cell_experiments/repo_execution.py",
}
sources = {}
for name, rel in source_paths.items():
    sources[name] = raw(rel).decode()
    check(reads[rel]["sha256"] == freeze["source_inventory"][rel.split("/", 1)[1]],
          name + ": original frozen source")
for name, expected in freeze["research_inventory"].items():
    rel = "research-sft-v1-source/" + name
    sources[name] = raw(rel).decode()
    check(reads[rel]["sha256"] == expected, name + ": research source")
for name, expected in freeze["helper_inventory"].items():
    rel = "e1e2-operation-helpers-04/" + name
    raw(rel)
    check(reads[rel]["sha256"] == expected, name + ": helper source")

# AST-select only three pure receipt-reading functions. No module imports or verifier execution.
tree = ast.parse(sources["business"])
allowed = ("semantic_identity", "completed_original_calls", "business_evidence")
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in allowed]
require(len(nodes) == 3, "pure business receipt reader functions changed")
ns = {"hashlib": hashlib, "digest": digest, "require": require, "sha": sha}
exec(compile(ast.Module(body=nodes, type_ignores=[]), source_paths["business"], "exec"), ns)

parent = read("probe-qwen-parent-03/parent.json")
parent_result = read("probe-qwen-parent-03/RESULT.json")
parent_freeze = read("probe-qwen-parent-03/FREEZE.json")
parent_readiness = read("probe-qwen-parent-03/repository/READINESS.json")
parent_loaded = read("probe-qwen-parent-03/MODEL_LOADED.json")
original = read("probe-qwen-parent-03/PREPARED_A_RECORDS.json")
check(reads["probe-qwen-parent-03/RESULT.json"]["sha256"] == freeze["baseline_result_sha256"] ==
      "33d0d5359edf547afa6d5de36a9db5f691b14a5eca4387c0ebcdd36b6d6f550d", "actual complete parent03")
check(reads["probe-qwen-parent-03/FREEZE.json"]["sha256"] == freeze["baseline_freeze_sha256"],
      "actual parent03 freeze")
check(digest(parent) == freeze["parent_digest"] == diag["parent_model_digest"] ==
      "f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6", "exact parent model")
check(parent["runtime"]["min_cuda_free_bytes"] == 4294967296, "unchanged 4 GiB threshold")
check(parent_result["status"] == "COMPLETE" and parent_result["successful_A_tasks"] == 0 and
      freeze["parent_successful_A_tasks"] == 0 and diag["parent_A_last_successes"] == 0,
      "actual complete zero-A baseline")
check(len(original) == 6 and len({x["task_id"] for x in original}) == 6,
      "six original A task identities")
for name, value in (("parent result", parent_result), ("parent readiness", parent_readiness)):
    sealed(value, name)

cohorts = {a: read(COLLECT + "/" + a + ".records.json") for a in ARMS}
collection = read(COLLECT + "/RESULT.json")
plans = read(COLLECT + "/PLANS.json")
sealed(collection, "collection")
scoped(collection, "collection")
check(collection["status"] == "RESEARCH_PLANS_FROZEN" and collection["plans_digest"] == digest(plans),
      "complete four-plan collection")
check(cohorts["final_answer"] == cohorts["trajectory"] == original,
      "answer/trajectory reuse exact prepared A records")
check(set(plans) == set(ARMS), "four original fit plans")
for a in ARMS:
    p = read(COLLECT + "/" + a + ".plan.json")
    check(p == plans[a] and digest(cohorts[a]) == p["records_digest"], a + ": plan/cohort")
    check(reads[COLLECT + "/" + a + ".plan.json"]["sha256"] ==
          collection["plans"][a]["plan_sha256"] and
          reads[COLLECT + "/" + a + ".records.json"]["sha256"] ==
          collection["plans"][a]["records_sha256"], a + ": collection byte bindings")
    check(p["training"]["steps"] == 64 and p["training"]["sequence_tokens"] == 1536,
          a + ": unchanged planned budget")
    scoped(p, a + " plan")

references, measurements = [], []
def reference_check(prefix, record, request_record, phase, arm, index):
    errors_before = len(failures)
    ref = read(prefix + "/REFERENCE.json")
    request = read(prefix + "/REFERENCE_REQUEST.json")
    measured = read(prefix + "/REFERENCE_MEASUREMENT.json")
    sealed(ref, prefix, ("receipt_sha256", "success"))
    sealed(measured, prefix + " measurement")
    expected_answer = hashlib.sha256(record["final_answer"].encode()).hexdigest()
    check(request["record_digest"] == digest(request_record) and
          request["record_id"] == ref["record_id"] == record["record_id"], prefix + ": record identity")
    check(request["answer_sha256"] == ref["answer_sha256"] == expected_answer, prefix + ": target")
    check(ref["input_sha256"] == hashlib.sha256(record["task"]["input"].encode()).hexdigest(),
          prefix + ": input")
    check(ref["parameters_sha256"] == digest(record["task"]["verifier"]["parameters"]) and
          ref["verifier"] == [record["task"]["verifier"]["name"], record["task"]["verifier"]["version"]] and
          ref["verifier_source_sha256"] == reads[source_paths["verifier"]]["sha256"],
          prefix + ": verifier binding")
    check(measured["reference_sha256"] == reads[prefix + "/REFERENCE.json"]["sha256"] and
          measured["status"] == "COMPLETE" and request["automatic_retry"] is False,
          prefix + ": intent/measurement")
    evidence = None
    try:
        evidence = ns["business_evidence"]({
            "semantic_receipt": ref, "semantic_receipt_sha256": ref["receipt_sha256"],
            "raw_answer": record["final_answer"], "success": ref["success"]})
        check(evidence["business_success"] is True, prefix + ": business success", "business")
    except Exception as error:
        check(False, prefix + ": business evidence " + repr(error), "business")
    check(ref["student_execution_claimed"] is False and ref["production_eligible"] is False and
          ref["result"]["full_repository_integration"] is False and
          ref["result"]["independent_user_evidence"] is False,
          prefix + ": bounded authored-reference scope", "scope")
    measurements.append(measured["cost"])
    references.append({
        "phase": phase, "arm": arm, "index": index, "record_id": record["record_id"],
        "task_id": record["task_id"], "source_id": record["source_id"],
        "reference_path": prefix + "/REFERENCE.json", "reference_sha256": reads[prefix + "/REFERENCE.json"]["sha256"],
        "receipt_sha256": ref["receipt_sha256"], "business_evidence": evidence,
        "reference_callback_wall_ns": ref["result"]["wall_ns"],
        "measurement_wall_seconds": measured["cost"]["wall_seconds"],
        "all_checked_bindings_match": len(failures) == errors_before})
    return ref

shadow_rows, shadow_outputs = [], []
for i, row in enumerate(original):
    prefix = COLLECT + "/shadow/" + str(i)
    observed = read(prefix + "/RESULT.json")
    request = read(prefix + "/request-0.json")
    output = read(prefix + "/output-0.json")
    step = read(prefix + "/step-0.json")
    sealed(step, prefix + " step")
    check(observed["steps"] == [step] and step["output"] == output, prefix + ": raw/aggregate")
    check(request == {"record_id": row["record_id"],
          "task": {"input": row["task"]["input"], "messages": row["task"]["messages"]}} and
          step["request_sha256"] == digest(request), prefix + ": actual request")
    check(output["loaded_model_digest"] == digest(parent) and
          output["messages_sha256"] == digest(request["task"]["messages"]) and
          output["input_sha256"] == hashlib.sha256(row["task"]["input"].encode()).hexdigest() and
          output["generation_config_sha256"] == parent_loaded["generation_digest"], prefix + ": policy/history")
    check(output["output_tokens"] == len(output["output_token_ids"]) and
          0 < output["input_tokens"] <= 4096 and 0 <= output["output_tokens"] <= 384,
          prefix + ": recorded tokens")
    check(step["verification"] is None and step["executed"] is False and
          step["semantic_measurement"] == "unmeasured" and observed["success"] is None and
          observed["first_attempt_success"] is None, prefix + ": no shadow business claim")
    shadow_rows.append(observed)
    shadow_outputs.append(output)

reuse = read(COLLECT + "/CONTROLLED_REUSE.json")
controlled = reuse["observations"]
check(controlled == parent_readiness["rows"][:6] and
      reuse["source_readiness_digest"] == digest(parent_readiness) and
      reuse["new_model_calls"] == reuse["new_verifier_calls"] == 0, "controlled exact parent reuse")
for i, observed in enumerate(controlled):
    for n, step in enumerate(observed["steps"]):
        prefix = "probe-qwen-parent-03/repository/" + str(i)
        check(read(prefix + "/step-" + str(n) + ".json") == step and
              read(prefix + "/output-" + str(n) + ".json") == step["output"],
              prefix + ": exact reused raw step " + str(n))
        request = read(prefix + "/request-" + str(n) + ".json")
        sealed(step, prefix + ": old step " + str(n))
        check(step["request_sha256"] == digest(request), prefix + ": old request binding " + str(n))
check(sum(len(x["steps"]) for x in controlled) == collection["controlled_reused_model_calls"] == 12,
      "12 retained old controlled calls, not new calls")

for mode, observed_rows in (("shadow", shadow_rows), ("controlled", controlled)):
    arm = mode + "_correction"
    for i, (row, observed) in enumerate(zip(original, observed_rows)):
        record = cohorts[arm][i]
        expected = copy.deepcopy(row)
        expected["record_id"] += "/" + mode
        expected["teacher_id"] = None
        events = []
        for step in observed["steps"]:
            events.extend([
                {"actor": "student", "kind": "action", "content": step["output"]["answer"],
                 "executed": step["executed"], "receipt_sha256": step["receipt_sha256"],
                 "policy_sha256": step["output"]["loaded_model_digest"],
                 "receipt_actor": "student", "trainable": False},
                {"actor": "environment", "kind": "observation", "content": step["feedback"],
                 "executed": False, "trainable": False}])
        events.append({"actor": "curator", "kind": "correction", "content": row["final_answer"],
                       "executed": False, "trainable": True})
        expected["trajectory"] = [{"index": j, **event} for j, event in enumerate(events)]
        expected["derivation"] = {
            "original_record_digest": digest(row), "mode": mode,
            "student_attempts_digest": digest(observed), "independent_sample_increment": 0,
            "correction_origin": "verified authored reference on training split only"}
        prefix = COLLECT + "/corrections/" + mode + "/" + str(i)
        ref = reference_check(prefix, record, expected, "collect", arm, i)
        expected["protocol_reference_receipt"] = ref
        expected["verified_outcome"] = {"success": True, "receipt_sha256": ref["receipt_sha256"],
                                       "verifier_name": "repo_patch", "verifier_version": "1"}
        check(record == expected == read(prefix + "/RECORD.json"), prefix + ": exact constructed correction")

primary_rows, starts = [], []
for arm in ALL_ARMS:
    worker = RUN + "/workers/" + arm + "-primary"
    fail = read(worker + "/FAILED.json")
    ex = read(RUN + "/processes/" + arm + "-primary/EXIT.json")
    sealed(ex, arm + ": process exit")
    check(ex["exit_code"] == 1 and ex["timed_out"] is False and ex["automatic_retry"] is False,
          arm + ": actual failed process")
    check(fail["error"] == "ValueError('selected CUDA device has insufficient free memory')" and
          fail["status"] == "FAILED_PRESERVED" and fail["partial_files_preserved"] is True,
          arm + ": resource rejection")
    check('causal_probe_v3.py", line 311, in check_device' in fail["traceback"],
          arm + ": resource guard source")
    scoped(fail, arm + " failure")
    absent = [worker + "/RESULT.json", worker + "/evaluation/RESULT.json"]
    row = {"arm": arm, "pid": ex["pid"], "exit_code": ex["exit_code"], "timed_out": ex["timed_out"],
           "error": fail["error"], "worker_cost": fail["cost"],
           "worker_failed_sha256": reads[worker + "/FAILED.json"]["sha256"],
           "process_exit_sha256": reads[RUN + "/processes/" + arm + "-primary/EXIT.json"]["sha256"]}
    if arm in ARMS:
        train_dir = worker + "/research-model"
        started = read(train_dir + "/STARTED.json")
        train_failed = read(train_dir + "/FAILED.json")
        starts.append(started["started_at_ns"])
        check(started["plan_digest"] == digest(plans[arm]), arm + ": attempted exact plan")
        check('research_sft_train_v1.py", line 135, in train' in fail["traceback"],
              arm + ": failed before Predictor/optimizer")
        refs = [reference_check(train_dir + "/references/" + str(i), record, record,
                                "fit_precheck", arm, i) for i, record in enumerate(cohorts[arm])]
        check(read(train_dir + "/REFERENCE_RECHECKS.json") == refs, arm + ": summary equals six raw calls")
        check(train_failed["error"] == fail["error"], arm + ": nested failure identity")
        absent += [train_dir + "/" + name for name in
                   ("STEPS.jsonl", "TRAINING.json", "manifest.json", "adapter_model.safetensors",
                    "optimizer.pt", "NATIVE_EXAMPLES.json")]
        row.update({"fit_started_at_ns": started["started_at_ns"], "training_cost": train_failed["cost"],
                    "train_failed_sha256": reads[train_dir + "/FAILED.json"]["sha256"],
                    "completed_reference_rechecks": len(refs)})
    else:
        check('research_sft_execution_v1.py", line 129, in evaluate' in fail["traceback"],
              arm + ": failed before evaluation Predictor")
    check(all(p not in members for p in absent), arm + ": no downstream completed artifacts")
    row["checked_absent_artifact_paths"] = absent
    primary_rows.append(row)

check(max(p["created_at_ns"] for p in plans.values()) <= collection["completed_at_ns"] <
      min(starts), "all plans retained before first fit")
check(result["fit_attempts_started"] == 4 and result["fits_completed"] == 0 and
      result["fit_counter_errors"] == [], "actual four entries zero completed fits")
check(all(x["status"] == "BLOCKED" for x in result["cold_comparisons"].values()) and
      not any(p.startswith(RUN + "/workers/") and "-cold/" in p for p in members),
      "no cold run or recovery claim")
check(not any(p.startswith(RUN + "/workers/") and
              (p.endswith("/STEPS.jsonl") or p.endswith("/TRAINING.json")) for p in members),
      "no retained optimizer steps or completed training")

owned = read("owned-research-sft-01/EXIT.json")
owned_intent = raw("owned-research-sft-01/INTENT.json")
owned_start = raw("owned-research-sft-01/STARTED.json")
check(owned["intent_sha256"] == hashlib.sha256(owned_intent).hexdigest() and
      owned["started_sha256"] == hashlib.sha256(owned_start).hexdigest(), "owned process chain")
check(owned["wait_returncode"] == 0 and owned["exit_source"] == "subprocess.Popen.wait",
      "actual coordinator wait 0 means reporting completed")
for kind in ("stdout", "stderr"):
    content = raw("owned-research-sft-01/" + kind + ".log")
    check(owned[kind]["sha256"] == hashlib.sha256(content).hexdigest() and
          owned[kind]["bytes"] == len(content), "owned " + kind + " bytes")

ledger = result["ledger"]
check(ledger["completed_output_receipts"] == len(shadow_outputs) == 6 and
      ledger["input_tokens_measured_subtotal"] == sum(x["input_tokens"] for x in shadow_outputs) == 1727 and
      ledger["output_tokens_measured_subtotal"] == sum(x["output_tokens"] for x in shadow_outputs) == 1764,
      "measured shadow call/token subtotal")
check(ledger["authored_reference_receipts"] == ledger["authored_reference_request_files"] ==
      len(references) == 36, "36 individual references counted once")
check(ledger["reference_batch_summaries_counted_again"] is False and
      ledger["completed_training_step_receipts"] == ledger["student_verification_receipts"] == 0,
      "no reference-summary double count or student/optimizer receipts")
check(ledger["global_totals_unknown"] is True and
      all(ledger[k] is None for k in ("model_calls", "input_tokens", "output_tokens",
                                    "training_steps", "reference_calls", "student_verifier_calls")),
      "partial aggregate unknowns retained")
check(ledger["measurement_errors"] == ledger["measurement_gaps"] == ledger["budget_violations"] == [],
      "no retained-ledger errors/gaps or observed budget violations")
check(all(result["cost"][k] is None for k in ("gpu_active_seconds", "energy_joules", "monetary_cost"))
      and result["cost"]["complete"] is False and result["cost"]["nested_scopes_are_not_additive"] is True,
      "global cost remains incomplete, nonadditive")
check(all(v["status"] == "UNAVAILABLE" and v["replacement"] is None
          for v in list(diag["fixed_expert_slots"].values()) +
                   list(diag["frozen_baselines"].values()) + [diag["separate_shadow_arm"]]),
      "all six diagnostic arms unavailable")
check(diag["first_attempt_opportunity"]["union_successes"] is None and
      diag["first_attempt_opportunity"]["routing_executions"] == 0, "no circuit union outcome")

output = {
    "schema": "hepta.research01-independent-retained-review.v1",
    "status": "REVIEW_COMPLETE" if not failures else "REVIEW_FOUND_MISMATCHES",
    "scope": "Closed run01 originals only; pure byte/hash/receipt analysis. No model, tokenizer, verifier or test executed.",
    "new_C_read": False, "new_model_calls": 0, "new_verifier_calls": 0, "new_training_steps": 0,
    "source_archive": {"manifest_sha256": EXPECTED_MANIFEST, "zip_sha256": EXPECTED_ZIP,
                       "zip_bytes": 1590081, "members": len(members),
                       "members_sha256": hashlib.sha256(members_raw).hexdigest(),
                       "selected_read_count": len(reads), "source_snapshot_claimed_atomic": False},
    "operation": {"freeze_sha256": EXPECTED_FREEZE, "result_sha256": EXPECTED_RESULT,
                  "diagnostic_sha256": EXPECTED_DIAG, "status": result["status"],
                  "fit_entries": result["fit_attempts_started"], "completed_fits": result["fits_completed"],
                  "completed_optimizer_step_receipts": ledger["completed_training_step_receipts"],
                  "coordinator_wait_returncode": owned["wait_returncode"]},
    "checks": {"count": checked, "categories": categories, "mismatches": failures},
    "reference_summary": {
        "new_individual_reference_executions": len(references),
        "collector_rechecks": sum(x["phase"] == "collect" for x in references),
        "fit_precheck_rechecks": sum(x["phase"] == "fit_precheck" for x in references),
        "unique_original_A_tasks": len({r["task_id"] for r in original}),
        "all_business_success": all(x["business_evidence"] and x["business_evidence"]["business_success"] is True for x in references),
        "completed_original_subject_calls": sum((x["business_evidence"] or {}).get("completed_original_calls", 0) or 0 for x in references),
        "control_observations": sum((x["business_evidence"] or {}).get("control_count", 0) or 0 for x in references),
        "reference_callback_wall_seconds_subtotal": sum(x["reference_callback_wall_ns"] for x in references) / 1e9,
        "reference_measurement_wall_seconds_subtotal": sum(x["wall_seconds"] for x in measurements),
        "cost_scope": "Nested reference callbacks/measurements; do not add to worker or coordinator wall/CPU.",
        "student_success_claimed": False, "independent_sample_increment": 0,
        "full_repository_integration": False, "independent_user_evidence": False},
    "references": references,
    "primaries": primary_rows,
    "shadow": {"completed_calls": len(shadow_outputs),
               "input_tokens_measured_subtotal": sum(x["input_tokens"] for x in shadow_outputs),
               "output_tokens_measured_subtotal": sum(x["output_tokens"] for x in shadow_outputs),
               "generation_wall_seconds_subtotal": sum(x["wall_seconds"] for x in shadow_outputs),
               "scope": "Render/tokenize/generate/decode; excludes model load and verification; nested in collector cost.",
               "business_verification": "unmeasured", "business_success": None},
    "controlled_reuse": {"retained_parent_calls": 12, "new_calls_from_reuse": 0,
                        "new_verifier_calls_from_reuse": 0, "new_independent_samples": 0},
    "retained_ledger": ledger,
    "coordinator_cost": result["cost"],
    "owned_wrapper_wall_seconds": owned["child_wall_seconds"],
    "conclusions": {
        "sole_logged_primary_terminal_class": "resource admission rejection before model initialization",
        "training_efficacy": "unavailable",
        "new_primary_A_or_B_business_outcomes": "unavailable",
        "cold_identity_or_recovery_evidence": "unavailable; not launched",
        "prior_success_A_retention": None,
        "prior_success_A_denominator": 0,
        "counterfactual_model_fit_capacity": "not established by threshold rejection",
        "GPU_cause_attribution": "not measured by this review; check_device error omits actual free bytes",
        "scientific_confirmation_qualified": False, "native_cell_adoption": False,
        "proof_of_useful_work_eligible": False, "circuit_qualified": False,
        "candidate_selected": None},
    "started_at_ns": start_ns, "completed_at_ns": time.time_ns(),
    "review_script_sha256": hashlib.sha256(plain_bytes(Path(__file__))).hexdigest(),
    "read_file_identities": reads}
content = json.dumps(output, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode() + b"\n"
path = OUT / "CLOSED_RESULT_REVIEW_01.json"
with path.open("xb") as stream:
    stream.write(content)
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({"path": str(path), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                  "status": output["status"], "checks": output["checks"],
                  "reference_summary": output["reference_summary"],
                  "operation": output["operation"], "read_files": len(reads)}, sort_keys=True))
