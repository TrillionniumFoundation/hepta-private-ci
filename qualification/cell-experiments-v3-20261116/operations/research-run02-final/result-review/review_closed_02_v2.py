"""Independent closed Run02 analysis. stdlib only; no model/tokenizer/verifier execution."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_support_02 as support
from review_support_02 import *
import collections

freeze, result = read(RUN + "/FREEZE.json"), read(RUN + "/RESULT.json")
diag = read("research-diagnostic-02/DIAGNOSTIC.json")
for rel, expected, obj in ((RUN + "/FREEZE.json", EXPECTED_FREEZE, freeze),
                           (RUN + "/RESULT.json", EXPECTED_RESULT, result),
                           ("research-diagnostic-02/DIAGNOSTIC.json", EXPECTED_DIAG, diag)):
    check(reads[rel]["sha256"] == expected, rel + ": expected SHA")
    sealed(obj, rel); scoped(obj, rel)
check(result["freeze_digest"] == diag["freeze_digest"] == digest(freeze), "exact operation freeze")
check(result["status"] == "RESEARCH_COMPLETE_UNQUALIFIED" and result["fit_attempts_started"] == 4 and
      result["fits_completed"] == 4 and result["fit_counter_errors"] == [], "four completed fits")
check(result["completed_fit_arms"] == list(ARMS), "four fit identities")
for name, expected in freeze["source_inventory"].items():
    rel = "candidate-qwen-03/" + name
    check(rel in members and members[rel]["sha256"] == expected, rel + ": frozen member inventory")
for directory, inv in (("research-sft-v1-source", freeze["research_inventory"]),
                       ("e1e2-operation-helpers-04", freeze["helper_inventory"])):
    for name, expected in inv.items():
        rel = directory + "/" + name; raw(rel)
        check(reads[rel]["sha256"] == expected, rel + ": actual frozen source")
for rel in (BUSINESS, PROTOCOL, VERIFIER):
    check(reads[rel]["sha256"] == freeze["source_inventory"][rel.split("/", 1)[1]], rel + ": pure reader source")
context = read(RUN + "/INPUTS.json")
check(reads[RUN + "/INPUTS.json"]["sha256"] == freeze["inputs_sha256"], "frozen context bytes")
parent = read("probe-qwen-parent-03/parent.json")
parent_result = read("probe-qwen-parent-03/RESULT.json")
parent_readiness = read("probe-qwen-parent-03/repository/READINESS.json")
original = read("probe-qwen-parent-03/PREPARED_A_RECORDS.json")
check(context["parent"] == parent and digest(parent) == freeze["parent_digest"] and
      context["records"][:6] == original and len(original) == 6, "actual original A and parent")
check(parent_result["status"] == "COMPLETE" and parent_result["successful_A_tasks"] == 0 and
      freeze["parent_successful_A_tasks"] == 0 and context["gate"]["successful_A_tasks"] == 0,
      "complete zero baseline; no positive witness substituted")
check(reads["probe-qwen-parent-03/RESULT.json"]["sha256"] == freeze["baseline_result_sha256"] ==
      "33d0d5359edf547afa6d5de36a9db5f691b14a5eca4387c0ebcdd36b6d6f550d", "exact parent03 result")
raw("probe-qwen-parent-03/FREEZE.json")
check(reads["probe-qwen-parent-03/FREEZE.json"]["sha256"] == freeze["baseline_freeze_sha256"], "parent03 freeze")
check(context["generation_digest"] == read("probe-qwen-parent-03/MODEL_LOADED.json")["generation_digest"],
      "unchanged frozen greedy generation")
check(parent["runtime"]["min_cuda_free_bytes"] == 4294967296, "unchanged 4 GiB guard")
cohorts = {a: read(COLLECT + "/" + a + ".records.json") for a in ARMS}
collection, plans = read(COLLECT + "/RESULT.json"), read(COLLECT + "/PLANS.json")
sealed(collection, "collection"); scoped(collection, "collection")
check(collection["plans_digest"] == digest(plans) and set(plans) == set(ARMS), "four retained plans")
check(cohorts["final_answer"] == cohorts["trajectory"] == original, "same original targets A")
for arm in ARMS:
    plan = read(COLLECT + "/" + arm + ".plan.json"); scoped(plan, arm + " plan")
    check(plan == plans[arm] and plan["records_digest"] == digest(cohorts[arm]) and
          plan["operation_id"] == freeze["operation_id"] + "/" + arm, arm + ": exact plan")
    check(plan["training"]["steps"] == 64 and plan["training"]["sequence_tokens"] == 1536 and
          plan["mode"] == freeze["fitting_modes"][arm], arm + ": frozen settings")
    for kind in ("records", "plan"):
        rel = COLLECT + "/" + arm + "." + kind + ".json"
        check(reads[rel]["sha256"] == collection["plans"][arm][kind + "_sha256"], rel + ": bound bytes")
shadow = []
for i, record in enumerate(original):
    observed, _ = interaction(COLLECT + "/shadow/" + str(i), record, parent,
                              context["generation_digest"], collection["pid"], execute=False)
    shadow.append(observed)
reuse = read(COLLECT + "/CONTROLLED_REUSE.json")
controlled = reuse["observations"]
check(controlled == parent_readiness["rows"][:6] == context["gate"]["controlled_observations"] and
      reuse["source_readiness_digest"] == digest(parent_readiness) and
      reuse["new_model_calls"] == reuse["new_verifier_calls"] == 0, "exact old parent controlled reuse")
for i, record in enumerate(original):
    old = controlled[i]
    observed, _ = interaction("probe-qwen-parent-03/repository/" + str(i), record, parent,
                              context["generation_digest"], old["steps"][0]["output"]["pid"], new=False)
    check({**observed, "task_digest": digest(record)} == old, "exact reused parent row with aggregate task digest " + str(i))
check(sum(len(x["steps"]) for x in controlled) == collection["controlled_reused_model_calls"] == 12,
      "12 reused calls excluded from new counts")
for mode, observed_rows in (("shadow", shadow), ("controlled", controlled)):
    arm = mode + "_correction"
    for i, (record, observed) in enumerate(zip(original, observed_rows)):
        expected = copy.deepcopy(record); expected["record_id"] += "/" + mode; expected["teacher_id"] = None
        events = []
        for step in observed["steps"]:
            events.extend([{"actor": "student", "kind": "action", "content": step["output"]["answer"],
                            "executed": step["executed"], "receipt_sha256": step["receipt_sha256"],
                            "policy_sha256": step["output"]["loaded_model_digest"],
                            "receipt_actor": "student", "trainable": False},
                           {"actor": "environment", "kind": "observation", "content": step["feedback"],
                            "executed": False, "trainable": False}])
        events.append({"actor": "curator", "kind": "correction", "content": record["final_answer"],
                       "executed": False, "trainable": True})
        expected["trajectory"] = [{"index": j, **event} for j, event in enumerate(events)]
        expected["derivation"] = {"original_record_digest": digest(record), "mode": mode,
                                 "student_attempts_digest": digest(observed), "independent_sample_increment": 0,
                                 "correction_origin": "verified authored reference on training split only"}
        prefix = COLLECT + "/corrections/" + mode + "/" + str(i)
        ref = reference(prefix, cohorts[arm][i], expected, "collection", arm, i)
        expected["protocol_reference_receipt"] = ref
        expected["verified_outcome"] = {"success": True, "receipt_sha256": ref["receipt_sha256"],
                                       "verifier_name": "repo_patch", "verifier_version": "1"}
        check(expected == cohorts[arm][i] == read(prefix + "/RECORD.json"), prefix + ": exact authored cohort")

training_rows, train_starts, all_steps, candidates = {}, [], [], {}
for arm in ARMS:
    prefix = RUN + "/workers/" + arm + "-primary/research-model"
    started, training = read(prefix + "/STARTED.json"), read(prefix + "/TRAINING.json")
    model, steps = read(prefix + "/manifest.json"), [json.loads(x) for x in raw(prefix + "/STEPS.jsonl").splitlines()]
    scoped(training, arm + " training"); scoped(model, arm + " model")
    train_starts.append(started["started_at_ns"]); all_steps.extend(steps); candidates[arm] = model
    refs = [reference(prefix + "/references/" + str(i), row, row, "fit", arm, i)
            for i, row in enumerate(cohorts[arm])]
    check(read(prefix + "/REFERENCE_RECHECKS.json") == refs, arm + ": reference aggregate no new calls")
    check(training["status"] == "COMPLETE" and training["steps"] == len(steps) == 64 and
          training["plan_digest"] == started["plan_digest"] == digest(plans[arm]) and
          training["records_digest"] == digest(cohorts[arm]) and
          training["source_inventory"] == plans[arm]["source_inventory"], arm + ": completed bound training")
    check(training["parent_model_digest"] == digest(parent) and training["research_model_digest"] == digest(model)
          and model["base_manifest"] == parent and model["runtime"] == parent["runtime"] and
          model["training_plan_digest"] == digest(plans[arm]), arm + ": bound saved candidate")
    counts = [[0] * len(x) for x in training["record_turn_updates"]]
    for index, step in enumerate(steps):
        group = index % 6; turn = (index // 6) % len(counts[group]); counts[group][turn] += 1
        check(step["step"] == index + 1 and step["turn"] == turn and
              step["task_id"] == cohorts[arm][group]["task_id"] and
              step["record_id"] == cohorts[arm][group]["record_id"], arm + ": scheduled step " + str(index + 1), "training")
        check(math.isfinite(step["loss"]) and math.isfinite(step["gradient_norm_before_clip"]) and
              0 < step["supervised_tokens"] <= step["input_tokens"] <= 1536 and
              step["padded_positions"] == 1536, arm + ": numeric step " + str(index + 1), "training")
    check(counts == training["record_turn_updates"] and [x["loss"] for x in steps] == training["losses"],
          arm + ": retained update/loss accounting", "training")
    sums = {"input_tokens_consumed": sum(x["input_tokens"] for x in steps),
            "supervised_tokens": sum(x["supervised_tokens"] for x in steps),
            "padded_training_token_positions": sum(x["padded_positions"] for x in steps)}
    check(all(training["cost"][k] == v for k, v in sums.items()), arm + ": actual token sums", "cost")
    check(training["parameter_change"] is True and training["parameter_before"] != training["parameter_after"],
          arm + ": recorded parameter change", "training")
    artifact = adapter_check(model, training)
    training_rows[arm] = {"training_path": prefix + "/TRAINING.json", "manifest_path": prefix + "/manifest.json",
                          "manifest_sha256": reads[prefix + "/manifest.json"]["sha256"], "model_digest": digest(model),
                          "steps": len(steps), "encoded_supervised_turns": training["encoded_supervised_turns"],
                          "record_turn_updates": counts, "loss_first": steps[0]["loss"], "loss_last": steps[-1]["loss"],
                          "all_gradient_norms_finite": all(math.isfinite(x["gradient_norm_before_clip"]) for x in steps),
                          "cost": training["cost"], "artifact": artifact, "parameter_after": training["parameter_after"],
                          "mode": training["mode"], "parameter_change": training["parameter_change"]}
check(collection["completed_at_ns"] < min(train_starts), "all plans frozen before first fit")
check(len({x["artifact"]["recorded_parameter_before"] for x in training_rows.values()}) == 1 and
      len({x["parameter_after"] for x in training_rows.values()}) == 4, "same recorded init; four distinct saved results")

workers, evaluations, summary_rows, panel_costs, child_rows = {}, {}, [], [], []
check(len(result["children"]) == len(freeze["schedule"]) == 13, "all 13 scheduled child outcomes")
for entry, child in zip(freeze["schedule"], result["children"]):
    arm, phase = entry["arm"], entry["phase"]; name = arm + "-" + phase
    workerpath = RUN + "/workers/" + name; processpath = RUN + "/processes/" + name
    job, launch, ex = read(RUN + "/jobs/" + name + ".json"), read(processpath + "/LAUNCH.json"), read(processpath + "/EXIT.json")
    worker = read(workerpath + "/RESULT.json"); workers[(arm, phase)] = worker
    sealed(job, name + " job"); sealed(ex, name + " exit"); sealed(worker, name + " worker"); scoped(worker, name)
    check(job["schedule_entry"] == entry and job["freeze_sha256"] == EXPECTED_FREEZE and
          worker["job_digest"] == digest(job) and worker["freeze_digest"] == digest(freeze), name + ": job/freeze")
    check(ex["exit_code"] == 0 and not ex["timed_out"] and not ex["automatic_retry"] and
          ex["pid"] == worker["pid"] and child["exit"] == ex and child["result"] == worker and
          child["result_error"] is None and child["result_sha256"] == reads[workerpath + "/RESULT.json"]["sha256"],
          name + ": actual exact child exit/result")
    for kind in ("stdout", "stderr"):
        path = processpath + "/" + kind + ".log"; raw(path)
        check(ex[kind + "_sha256"] == reads[path]["sha256"], name + ": terminal " + kind)
    check(launch["automatic_retry"] is False and 0 < launch["timeout_seconds"] <= entry["wall_seconds"] and
          launch["argv"][-1] == RAM + "/" + RUN + "/jobs/" + name + ".json", name + ": bounded launch")
    child_rows.append({"arm": arm, "phase": phase, "pid": ex["pid"], "exit_code": ex["exit_code"],
                       "worker_result_sha256": reads[workerpath + "/RESULT.json"]["sha256"], "cost": worker["worker_cost"]})
    if phase == "collect":
        continue
    model = parent if arm in ("parent", "retrieval") else candidates[arm]
    identity = worker["manifest"]; manifest_path = relpath(identity["path"])
    check(read(manifest_path) == model and reads[manifest_path]["sha256"] == identity["sha256"] and
          identity["model_digest"] == digest(model) and read(workerpath + "/MODEL_IDENTITY.json") == identity,
          name + ": exact saved manifest")
    epath = workerpath + "/evaluation"; evaluation = read(epath + "/EVALUATION.json")
    loaded = read(epath + "/MODEL_LOADED.json"); sealed(evaluation, name + " evaluation"); scoped(evaluation, name + " evaluation")
    check(worker["evaluation"] == evaluation and evaluation["status"] == "COMPLETE" and
          evaluation["model_digest"] == loaded["model_digest"] == digest(model) and
          evaluation["pid"] == loaded["pid"] == worker["pid"] and
          loaded["generation_digest"] == evaluation["generation_digest"] == context["generation_digest"],
          name + ": actually loaded evaluation identity")
    check(worker["training"] == (read(workerpath + "/research-model/TRAINING.json")
          if phase == "primary" and arm in ARMS else None), name + ": no cold or baseline fitting")
    panels = context["panels"]
    shown = context["retrieval_panels"] if arm == "retrieval" else panels
    check(read(epath + "/ORIGINAL_PANELS.json") == panels and read(epath + "/SHOWN_PANELS.json") == shown and
          evaluation["original_panels_digest"] == digest(panels) and evaluation["shown_panels_digest"] == digest(shown),
          name + ": exact exposed task panels")
    row_index, by_panel, ev_steps, calls = 0, {}, [], []
    for panel, records in panels.items():
        ppath = epath + "/" + panel; panel_rows, start_count = [], len(output_rows)
        for i, (original_row, shown_row) in enumerate(zip(records, shown[panel])):
            raw_row, evidence = interaction(ppath + "/" + str(i), shown_row, model,
                                            context["generation_digest"], worker["pid"])
            augmented = {**raw_row, "panel": panel, "original_task_digest": digest(original_row),
                         "shown_task_digest": digest(shown_row), "business_evidence": evidence}
            check(evaluation["rows"][row_index] == augmented, name + ": exact raw task row " + str(row_index))
            panel_rows.append(raw_row); ev_steps.extend(raw_row["steps"])
            calls.extend(x["completed_original_calls"] for x in evidence); row_index += 1
            summary_rows.append({"arm": arm, "phase": phase, "panel": panel, "task_id": original_row["task_id"],
                                 "first": raw_row["first_attempt_success"], "final": raw_row["success"],
                                 "attempts": len(raw_row["steps"]), "raw_result_path": ppath + "/" + str(i) + "/RESULT.json"})
        by_panel[panel] = {"tasks": len(records), "successful_tasks": sum(x["success"] for x in panel_rows),
                           "first_attempt_successes": sum(x["first_attempt_success"] for x in panel_rows)}
        m = read(ppath + "/MEASUREMENT.json"); sealed(m, name + " " + panel)
        observed_outputs = output_rows[start_count:]; expected_calls = sum(len(x["steps"]) for x in panel_rows)
        check(m == evaluation["panel_measurements"][panel] and m["status"] == "COMPLETE" and
              m["model_calls"] == m["student_verifier_calls"] == m["persisted_requests"] == expected_calls and
              m["completed_task_ids"] == [x["task_id"] for x in panel_rows] and
              m["calls_without_completed_output_receipt"] == 0 and not m["raw_receipt_read_errors"],
              name + " " + panel + ": raw panel count", "cost")
        check(all(m[k] == m[k + "_measured_subtotal"] == sum(x[k] for x in observed_outputs)
                  for k in ("input_tokens", "output_tokens")), name + " " + panel + ": raw token sum", "cost")
        panel_costs.append({"arm": arm, "phase": phase, "panel": panel, "cost": m["cost"],
                            "model_calls": expected_calls, "input_tokens": m["input_tokens"],
                            "output_tokens": m["output_tokens"]})
    measured_calls = [x for x in calls if type(x) is int]
    check(row_index == len(evaluation["rows"]) == 9 and evaluation["by_panel"] == by_panel and
          evaluation["successful_tasks"] == sum(x["successful_tasks"] for x in by_panel.values()), name + ": outcome counts", "business")
    check(evaluation["model_calls"] == evaluation["verifier_calls"] == len(ev_steps) and
          all(evaluation[k] == sum(x["output"][k] for x in ev_steps) for k in ("input_tokens", "output_tokens")) and
          evaluation["output_cap_hits"] == sum(x["output"]["hit_output_limit"] for x in ev_steps) and
          evaluation["executed_attempts"] == sum(x["executed"] for x in ev_steps), name + ": evaluation counters", "cost")
    check(evaluation["completed_original_calls"] == (sum(measured_calls) if len(calls) == len(measured_calls) else None) and
          evaluation["completed_original_calls_measured_subtotal"] == (sum(measured_calls) if measured_calls else None) and
          evaluation["completed_original_calls_missing_attempts"] == len(calls) - len(measured_calls),
          name + ": missing subject counts stay unknown", "cost")
    evaluations[(arm, phase)] = evaluation

cold = {}
for arm in ALL_ARMS:
    primary, repeat = workers[(arm, "primary")], workers[(arm, "cold")]
    a, b = evaluations[(arm, "primary")], evaluations[(arm, "cold")]
    def answers(e):
        return [(row["task_id"], row["first_attempt_success"], row["success"],
                 [(x["output"]["answer"], x["output"]["output_token_ids"], x["output"]["output_tokens"])
                  for x in row["steps"]]) for row in e["rows"]]
    differences = []
    for left, right in zip(a["rows"], b["rows"]):
        for n, (one, two) in enumerate(zip(left["steps"], right["steps"])):
            changed = {k: {"primary": one["output"][k], "cold": two["output"][k]}
                       for k in ("input_tokens", "messages_sha256") if one["output"][k] != two["output"][k]}
            if changed:
                differences.append({"task_id": left["task_id"], "panel": left["panel"], "attempt": n,
                                    "fields": changed, "preceding_primary_feedback": left["steps"][n-1]["feedback"] if n else None,
                                    "preceding_cold_feedback": right["steps"][n-1]["feedback"] if n else None})
    job = read(RUN + "/jobs/" + arm + "-cold.json")
    same_identity = primary["manifest"] == repeat["manifest"]
    different_pid = primary["pid"] != repeat["pid"]
    same_outputs = answers(a) == answers(b)
    check(same_identity and different_pid and same_outputs and job["primary_manifest"] == primary["manifest"] and
          job["primary_pid"] == primary["pid"] and
          job["primary_result_sha256"] == reads[RUN + "/workers/" + arm + "-primary/RESULT.json"]["sha256"],
          arm + ": exact cold candidate, new process, same answers and output tokens", "cold")
    cold[arm] = {"same_candidate": same_identity, "different_worker_pid": different_pid,
                 "raw_answers_output_tokens_and_business_equal": same_outputs,
                 "all_request_histories_and_input_token_counts_equal": not differences,
                 "actual_request_differences": differences, "primary_pid": primary["pid"], "cold_pid": repeat["pid"],
                 "model_digest": primary["manifest"]["model_digest"], "by_panel": a["by_panel"],
                 "optimizer_or_rng_resume_tested": False, "new_independent_samples": 0}
    check(all(result["cold_comparisons"][arm][k] is True for k in
              ("same_manifest", "different_worker_pid", "raw_answers_and_tokens_equal", "business_outcomes_equal")),
          arm + ": aggregate cold report")

actual_sets = {"outputs": visited_outputs, "requests": visited_requests, "steps": visited_steps, "references": visited_refs}
patterns = {"outputs": r"/output-[0-9]+\.json$", "requests": r"/request-[0-9]+\.json$",
            "steps": r"/step-[0-9]+\.json$", "references": r"/REFERENCE\.json$"}
for kind, pattern in patterns.items():
    check(actual_sets[kind] == {p for p in members if p.startswith(RUN + "/workers/") and re.search(pattern, p)},
          kind + ": exhaustive retained file coverage", "coverage")
totals = {"model_calls": len(output_rows), "input_tokens": sum(x["input_tokens"] for x in output_rows),
          "output_tokens": sum(x["output_tokens"] for x in output_rows),
          "student_verifier_calls": sum(x["business_evidence"] is not None for x in attempt_rows),
          "reference_calls": len(references), "training_steps": len(all_steps),
          "padded_training_positions": sum(x["padded_positions"] for x in all_steps)}
for key in ("model_calls", "input_tokens", "output_tokens", "student_verifier_calls", "reference_calls", "training_steps"):
    check(totals[key] == result["ledger"][key], key + ": independent study-ledger count", "cost")
check(totals == {"model_calls": 202, "input_tokens": 92217, "output_tokens": 30896,
                 "student_verifier_calls": 196, "reference_calls": 36, "training_steps": 256,
                 "padded_training_positions": 393216}, "exact actual retained totals", "cost")
for key in ("input_tokens", "output_tokens"):
    check(diag["cost_ledger"][key] is None and diag["cost_ledger"][key + "_measured_subtotal"] == totals[key],
          key + ": preserve different diagnostic completeness scope", "cost")
check(result["ledger"]["global_totals_unknown"] is False and diag["cost_ledger"]["global_totals_unknown"] is True and
      result["cost"]["complete"] is False, "generation ledger complete; diagnostic and full resource costs not complete", "scope")
check(not result["ledger"]["measurement_errors"] and not result["ledger"]["measurement_gaps"] and
      not result["ledger"]["budget_violations"], "study ledger no retained gaps/budget violation")
check(len(references) == 36 and sum(x["evidence"]["business_success"] is True for x in references) == 36,
      "all 36 actual authored reference business calls", "business")

terminal = read("operations/RESEARCH_TERMINAL_INDEX_02.json")
closure = read("operations/RESEARCH_TARGET_CLOSURE_READBACK_02.json")
check(reads["operations/RESEARCH_TERMINAL_INDEX_02.json"]["sha256"] == manifest["terminal_index_sha256"] and
      terminal["writers_stopped_confirmed"] is True and closure["owned_wait_returncode"] == 0,
      "closed export terminal and target-owned wait")
for entry in manifest["writer_observations"]:
    directory = entry["owned_directory"]
    ex, started, intent = (read(directory + "/" + x + ".json") for x in ("EXIT", "STARTED", "INTENT"))
    check(ex["wait_returncode"] == 0 and ex["exit_source"] == "subprocess.Popen.wait" and
          ex["started_sha256"] == reads[directory + "/STARTED.json"]["sha256"] and
          ex["intent_sha256"] == reads[directory + "/INTENT.json"]["sha256"], directory + ": real owned wait chain")
    for kind in ("stdout", "stderr"):
        path = directory + "/" + kind + ".log"; raw(path)
        check(reads[path] == ex[kind], directory + ": complete " + kind)
    for key in ("launch_freeze", "observation", "source"):
        raw(entry[key + "_path"])
        check(reads[entry[key + "_path"]]["sha256"] == entry[key + "_sha256"], directory + ": terminal input " + key)
for outcome in manifest["verified_writer_outcomes"]:
    check(outcome["actual_wait_returncode"] == 0 and not outcome["controller_status_rewritten"] and
          all(x["stopped"] and x["reason"] == "pid_absent" for x in outcome["process_observations"]),
          outcome["role"] + ": retained writer-stop observations")
for outcome in manifest["verified_worker_outcomes"]:
    path = outcome["launch_path"]; raw(path); raw(path.replace("LAUNCH.json", "EXIT.json"))
    check(reads[path]["sha256"] == outcome["launch_sha256"] and
          reads[path.replace("LAUNCH.json", "EXIT.json")]["sha256"] == outcome["terminal_sha256"] and
          outcome["exit_code"] == 0 and outcome["process_observation"]["stopped"] is True,
          path + ": archive worker stop binding")
check(len(manifest["verified_worker_outcomes"]) == len(closure["workers"]) == 13, "all workers closed")
expected_launches = {p for p in members if p.startswith(RUN + "/processes/") and p.endswith("/LAUNCH.json")}
check({x["launch_path"] for x in manifest["verified_worker_outcomes"]} ==
      {x["launch_path"] for x in closure["workers"]} == expected_launches, "all actual launches covered by closure")
for item in closure["workers"]:
    terminal_path = item["launch_path"].replace("LAUNCH.json", "EXIT.json")
    exited = read(terminal_path)
    check(item["actual_wait_returncode"] == exited["exit_code"] == 0 and
          item["terminal_sha256"] == reads[terminal_path]["sha256"] and
          item["launch_sha256"] == reads[item["launch_path"]]["sha256"] and item["stop"]["stopped"] is True and
          item["stop"]["expected"]["pid"] == exited["pid"], terminal_path + ": exact closure mapping")
for outcome in manifest["verified_writer_outcomes"]:
    directory = next(x["owned_directory"] for x in manifest["writer_observations"] if x["role"] == outcome["role"])
    ex = read(directory + "/EXIT.json")
    check(outcome["owned_exit_sha256"] == reads[directory + "/EXIT.json"]["sha256"] and
          outcome["process_observations"][0]["expected"] == ex["child_identity"], directory + ": stopped child identity")
previous_raw = plain(ROOT / "research-final-evidence-01/research-sft-01/RESULT.json")
check(hashlib.sha256(previous_raw).hexdigest() == "bbb77cb25b2f7e28caa3a71f7112d549734b3ff8bbdd32b562fc2bbbf5bc0e33",
      "separate retained Run01 identity")
previous = json.loads(previous_raw)
def compact_evaluation(value):
    return {k: v for k, v in value.items() if k not in ("rows", "panel_measurements", "retrieval_bindings")}
report = {"schema": "hepta.independent-closed-research02-review.v1", "started_at_ns": START_NS,
          "completed_at_ns": time.time_ns(), "source": {"archive": EXPECTED_ZIP, "manifest": EXPECTED_MANIFEST,
          "freeze": EXPECTED_FREEZE, "result": EXPECTED_RESULT, "diagnostic": EXPECTED_DIAG},
          "new_model_calls": 0, "new_verifier_calls": 0, "new_tokenizer_calls": 0, "new_C_read": False,
          "method": "stdlib byte/hash and pure receipt readers; no code/tests/model execution",
          "checks": support.checks, "categories": support.categories, "failures": support.failures,
          "file_read_identities": reads, "training": training_rows, "task_outcomes": summary_rows,
          "attempts": attempt_rows, "references": references, "cold": cold,
          "evaluations": {a + "-" + p: compact_evaluation(v) for (a, p), v in evaluations.items()},
          "panel_costs": panel_costs, "worker_costs": child_rows, "retained_counts": totals,
          "study_ledger_unchanged": result["ledger"], "diagnostic_ledger_unchanged": diag["cost_ledger"],
          "coordinator_cost_unchanged": result["cost"], "parent03_cost_separate": result["prior_readiness_operation"],
          "run01_separate": {"result_sha256": hashlib.sha256(previous_raw).hexdigest(), "status": previous["status"],
          "fit_attempts_started": previous["fit_attempts_started"], "fits_completed": previous["fits_completed"],
          "cost": previous["cost"], "ledger": previous["ledger"]},
          "diagnostic_preserved": {"binding_errors": diag["binding_errors"], "frozen_baselines": diag["frozen_baselines"],
          "fixed_expert_slots": diag["fixed_expert_slots"], "separate_shadow_arm": diag["separate_shadow_arm"]},
          "input_panel_order": list(context["panels"]), "source_tasks": len({r["task_id"] for r in context["records"]}),
          "source_ids": sorted({r["source_id"] for r in context["records"]}),
          "baseline_success_retention_ratio": None, "candidate_selected": None,
          **{k: False for k in QUALS}, "new_independent_samples": 0}
encoded = canonical(report) + b"\n"
target = OUT / "CLOSED_RESULT_REVIEW_02_FINAL.json"
with target.open("xb") as stream:
    stream.write(encoded); stream.flush()
    import os
    os.fsync(stream.fileno())
reference_summary = {"calls": len(references), "business_passes": sum(x["evidence"]["business_success"] is True for x in references),
    "original_completed_calls": sum(x["evidence"]["completed_original_calls"] for x in references),
    "control_observations": sum(x["evidence"]["control_count"] for x in references),
    "collector": sum(x["phase"] == "collection" for x in references), "fit": sum(x["phase"] == "fit" for x in references),
    "nested_wall_seconds": sum(x["cost"]["wall_seconds"] for x in references)}
summary = {"checks": support.checks, "failures": support.failures, "files_read": len(reads),
    "readout_sha256": hashlib.sha256(encoded).hexdigest(), "training": training_rows, "cold": cold,
    "outcomes_primary": [x for x in summary_rows if x["phase"] == "primary"],
    "evaluation_counts_cost": {a + "-" + p: {k: v for k, v in e.items() if k in
        ("by_panel", "model_calls", "verifier_calls", "input_tokens", "output_tokens", "executed_attempts",
         "output_cap_hits", "completed_original_calls", "completed_original_calls_measured_subtotal",
         "completed_original_calls_missing_attempts", "cost")} for (a, p), e in evaluations.items()},
    "reference_summary": reference_summary, "retained_totals": totals,
    "all_new_attempt_business_reasons": dict(collections.Counter(x["verification_reason"] for x in attempt_rows
        if x["business_evidence"] is not None)),
    "primary_attempt_business_reasons": dict(collections.Counter(x["verification_reason"] for x in attempt_rows
        if "-primary/" in x["path"] and x["business_evidence"] is not None)),
    "primary_successful_answers_equal_authored_target": sum(x["answer_equals_authored_target"] for x in attempt_rows
        if "-primary/" in x["path"] and (x["business_evidence"] or {}).get("business_success") is True),
    "primary_successful_attempts": sum((x["business_evidence"] or {}).get("business_success") is True for x in attempt_rows
        if "-primary/" in x["path"]),
    "shadow": {"calls": sum("/shadow/" in x["path"] for x in output_rows),
       "input_tokens": sum(x["input_tokens"] for x in output_rows if "/shadow/" in x["path"]),
       "output_tokens": sum(x["output_tokens"] for x in output_rows if "/shadow/" in x["path"])},
    "generation_wall_seconds_subtotal": sum(x["wall_seconds"] for x in output_rows),
    "coordinator_cost": result["cost"], "run01_cost": previous["cost"], "source_ids": report["source_ids"],
    "baseline_success_retention_ratio": None, "candidate_selected": None, **{k: False for k in QUALS}}
summary_bytes = canonical(summary) + b"\n"
with (OUT / "SUMMARY_READOUT_02.json").open("xb") as stream:
    stream.write(summary_bytes); stream.flush(); os.fsync(stream.fileno())
print(json.dumps({"status": "PASS" if not support.failures else "REVIEW_MISMATCH",
                  "checks": support.checks, "files_read": len(reads), "failures": support.failures,
                  "output": str(target), "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                  "counts": totals, "primary_outcomes": {a: cold[a]["by_panel"] for a in ALL_ARMS},
                  "new_model_calls": 0, "new_verifier_calls": 0, "new_C_read": False}, sort_keys=True))
sys.exit(0 if not support.failures else 2)
