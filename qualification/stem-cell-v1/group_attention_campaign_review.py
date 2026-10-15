"""Independent stdlib-only replay of Group evidence-attention campaign records.

Recomputes symbolic labels from public text; never imports model, Torch,
teacher, fitting code, or checkpoint. Artifact identities are NOT signatures,
and untrusted self-reported execution timing is not hardware attestation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path

from group_campaign_review import _parse
from group_checkpoint_audit import verify_checkpoint_file

ARMS = ("static", "wide", "core", "attention",
        "core_fixed", "attention_fixed", "core_ndu", "attention_ndu")
DIRECT = ("static", "wide", "core", "attention")
SYSTEM2 = ("core_fixed", "attention_fixed", "core_ndu", "attention_ndu")
MODELS = {"static": "static", "wide": "wide", "core": "core",
          "attention": "attention", "core_fixed": "core",
          "attention_fixed": "attention", "core_ndu": "core",
          "attention_ndu": "attention"}
MODES = {"static": "direct", "wide": "direct", "core": "direct",
         "attention": "direct", "core_fixed": "fixed",
         "attention_fixed": "fixed", "core_ndu": "ndu",
         "attention_ndu": "ndu"}
INVALID_STATUSES = {"budget_exhausted", "callback_failed",
                    "resource_budget_stop", "ndu_stop:expired_policy",
                    "ndu_stop:continuation_support_violated"}
COHORTS = ("test", "long", "deleted", "composition")
REQUIRED_SOURCES = (
    "group_core.py", "group_training.py", "group_attention_curriculum.py",
    "group_step_supervision.py", "group_attention_campaign.py",
    "group_attention_campaign_review.py", "group_campaign_review.py",
    "group_tasks.py", "group_encoder.py", "group_features.py",
    "hf_encoder_kernel.py", "execution_meter.py", "aten_work.py",
    "group_campaign.py", "group_loop.py", "group_critic.py",
    "system2_execution.py", "ndu_continuation.py",
    "paired_execution.py", "transformer_work.py", "next_round_matrix.py",
    "group_checkpoint_audit.py",
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _summarize(rows):
    times = sorted(x["wall_ns"] for x in rows)
    return dict(n=len(rows), correct=sum(x["success"] for x in rows),
                unsupported_attempts=sum(x["unsupported_attempt"] for x in rows),
                steps=sum(x["steps"] for x in rows),
                verifier_calls=sum(x["verifier_calls"] for x in rows),
                execution_statuses=dict(Counter(x["execution_status"] for x in rows)),
                cpu_ns=sum(x["cpu_ns"] for x in rows), wall_ns=sum(times),
                p50_ns=times[len(times) // 2],
                p95_ns=times[min(len(times) - 1, int(.95 * len(times)))])


def _verify_system2_trace(row, record, critic_sha):
    """Strict callback-order and workspace replay from the retained raw trace.

    Digests and self-reported work are structural checks, NOT execution
    attestations, signed external outcomes, or independent timing witnesses.
    """
    fields = {
        "schema", "authority", "cohort", "arm", "case_id", "mode", "status",
        "feature_sha256", "model_sha256", "critic_sha256", "final_candidate",
        "calls", "trace", "workspace_bindings", "verifier_statuses",
        "ndu_decisions", "independent_success_established",
        "production_authorized",
    }
    if (type(record) is not dict or set(record) != fields
            or record["schema"] != "hepta.group.system2-full-trace.v1"
            or record["authority"] != "DENY_ALL"
            or record["production_authorized"] is not False
            or record["independent_success_established"] is not False
            or record["cohort"] != row["cohort"] or record["arm"] != row["arm"]
            or record["case_id"] != row["case_id"]
            or record["mode"] != row["execution_mode"]
            or record["status"] != row["execution_status"]
            or record["feature_sha256"] != row["feature_sha256"]
            or record["model_sha256"] != row["model_sha256"]
            or record["critic_sha256"] != critic_sha
            or row["full_trace_sha256"] != _digest(record)):
        raise ValueError("System2 trace identity or provenance mismatch")
    step_count = row["steps"]
    if (type(record["trace"]) is not list or type(record["calls"]) is not int
            or record["calls"] != len(record["trace"])
            or type(record["workspace_bindings"]) is not list
            or len(record["workspace_bindings"]) != step_count
            or type(record["verifier_statuses"]) is not list
            or len(record["verifier_statuses"]) != step_count):
        raise ValueError("missing or fabricated System2 callback/workspace counts")
    expected = []
    ended_after_value = (row["execution_status"].startswith("ndu_stop:")
                         or row["execution_status"] == "utility_stop")
    for step in range(step_count):
        expected.extend(("propose", "verify"))
        if step < step_count - 1 or ended_after_value:
            expected.append("value")
    if [entry.get("kind") for entry in record["trace"]] != expected:
        raise ValueError("invalid causal propose/verify/value callback order")
    for index, entry in enumerate(record["trace"], start=1):
        digest = entry.get("output_digest")
        if (type(entry.get("call")) is not int or entry["call"] != index
                or entry.get("status") != "completed"
                or type(entry.get("elapsed_ns")) is not int
                or entry["elapsed_ns"] < 0
                or type(digest) is not str or len(digest) != 64
                or not all(ch in "0123456789abcdef" for ch in digest)):
            raise ValueError("incomplete or forged callback output receipt")
    for index, item in enumerate(record["workspace_bindings"], start=1):
        if (type(item) is not dict or item.get("step") != index
                or item.get("feature_sha256") != row["feature_sha256"]
                or item.get("model_sha256") != row["model_sha256"]
                or type(item.get("state_sha256")) is not str
                or len(item["state_sha256"]) != 64):
            raise ValueError("workspace state generation or model changed")
    if (record["final_candidate"] != (
            chr(65 + row["prediction"]) if row["prediction"] >= 0 else None)):
        raise ValueError("final logged candidate differs from independently scored row")
    if (row["success"] and
            (record["verifier_statuses"][-1] != "supported"
             or row["execution_status"] != "verifier_accepted_not_independent_eval")):
        raise ValueError("unverifiable accepted System2 answer")
    if row["cohort"] == "deleted" and any(
            v != "missing_evidence" for v in record["verifier_statuses"]):
        raise ValueError("deleted evidence was treated as available")
    value_calls = expected.count("value")
    if row["execution_mode"] == "ndu":
        if (type(record["ndu_decisions"]) is not list
                or len(record["ndu_decisions"]) != value_calls
                or any(type(x) is not dict or
                       type(x.get("continue_computation")) is not bool
                       for x in record["ndu_decisions"])):
            raise ValueError("unreplayed or malformed NDU decisions")
    elif record["ndu_decisions"] != []:
        raise ValueError("fixed-depth control cannot emit NDU decisions")
    return True


def review(root):
    root = Path(root)
    protocol = json.loads((root / "protocol.json").read_text())
    rows = json.loads((root / "observations.json").read_text())
    report = json.loads((root / "report.json").read_text())
    teacher = json.loads((root / "teacher.json").read_text())
    encoder = json.loads((root / "encoder.json").read_text())
    raw_traces = json.loads((root / "system2-traces.json").read_text())
    if (protocol["schema"] != "hepta.group.paired-step-campaign.v1"
            or report["schema"] != "hepta.group.paired-step-observation.v1"
            or report["protocol_sha256"] != _digest(protocol)
            or tuple(protocol["frozen_candidate_arms"]) != ARMS
            or protocol["evaluation_cohorts"] != list(COHORTS)
            or report["authority"] != "DENY_ALL" or report["production_authorized"]
            or report["natural_future_win_established"]
            or report["equal_actual_training_work"]):
        raise ValueError("unregistered protocol, authority or unsupported efficacy assertion")
    hashes = protocol.get("source_sha256")
    if type(hashes) is not dict or set(hashes) != set(REQUIRED_SOURCES):
        raise ValueError("complete exact-source inventory required")
    for filename in REQUIRED_SOURCES:
        expected_sha = hashlib.sha256(
            (Path(__file__).parent / filename).read_bytes()).hexdigest()
        if hashes[filename] != expected_sha:
            raise ValueError("campaign or independent reviewer source SHA differs")
    public, seen_groups, replay_labels = protocol["public_cases"], {}, {}
    if set(public) != {"train", "validation", *COHORTS}:
        raise ValueError("complete training and heldout cohorts required")
    for cohort, cases in public.items():
        identifiers = set()
        seen_groups[cohort] = set()
        replay_labels[cohort] = {}
        for case in cases:
            cid, source = case["case_id"], case["source_group"]
            if cid in identifiers or source in seen_groups[cohort]:
                raise ValueError("duplicate public case or source group")
            identifiers.add(cid)
            seen_groups[cohort].add(source)
            answer, _, _ = _parse(case, missing=cohort == "deleted")
            replay_labels[cohort][cid] = answer
        if not cases:
            raise ValueError("empty heldout cohort")
    if not (seen_groups["train"] == set(protocol["train_source_groups"])):
        raise ValueError("training source membership drift")
    if any(seen_groups[a] & seen_groups[b] for a, b in
           (("train", "validation"), ("train", "test"), ("train", "long"),
            ("validation", "test"), ("validation", "long"), ("test", "long"))):
        raise ValueError("leaked train/test/long source groups")
    if (seen_groups["test"] != seen_groups["deleted"]
            or set(replay_labels["test"]) != set(replay_labels["deleted"])):
        raise ValueError("deleted cohort does not preserve original cases")
    if (protocol.get("critic_fit_splits") != ["validation_fit", "validation_calibration"]
            or protocol.get("live_system2_modes") != ["fixed", "ndu"]
            or not report.get("real_system2_callbacks_executed")
            or not report.get("heldout_target_stripped_before_system2_callbacks")
            or not report.get("same_model_critic_frozen_on_validation_only")):
        raise ValueError("live System2 and disjoint frozen-critic protocol required")
    critic = report.get("critic_cost")
    if (type(critic) is not dict or type(critic.get("cpu_ns")) is not int
            or critic["cpu_ns"] <= 0 or type(critic.get("wall_ns")) is not int
            or critic["wall_ns"] <= 0 or set(critic.get("receipts", {})) != {"core", "attention"}
            or not critic.get("separate_fits_charged")
            or critic.get("source_group_independence_claimed")):
        raise ValueError("measured frozen critics required")
    mid = len(public["validation"]) // 2
    for model_owner in ("core", "attention"):
        receipt = critic["receipts"][model_owner]
        metadata = receipt["metadata"]
        if (metadata["source_groups"]["fit"] != sorted(
                    c["source_group"] for c in public["validation"][:mid])
                or metadata["source_groups"]["calibration"] != sorted(
                    c["source_group"] for c in public["validation"][mid:])
                or receipt["parameters_sha256"] in ("", "0" * 64)
                or receipt["fit_rows"] != mid * 3
                or receipt["calibration_rows"] != (len(public["validation"]) - mid) * 3
                or metadata["future_support_guaranteed"]
                or metadata["confidence_bound_established"]):
            raise ValueError("critic source-bound validation provenance mismatch")
    if (teacher["source_groups_sha256"] != _digest(sorted(seen_groups["train"]))
            or teacher["authority"] != "DENY_ALL" or not teacher["train_only"]
            or teacher["supervised_steps"] < len(public["train"])
            or teacher["tokenizer_calls"] != len(public["train"])
            or report["teacher"] != teacher or report["encoder_cost"] != encoder
            or type(encoder["actual_forward_calls"]) is not int
            or encoder["actual_forward_calls"] <= 0):
        raise ValueError("teacher or physical Encoder receipt mismatch")
    training = report["training"]
    if (set(training) != set(DIRECT)
            or training["core"]["sample_and_depth_sha256"] !=
               training["attention"]["sample_and_depth_sha256"]
            or training["core"]["parameter_count"] != training["attention"]["parameter_count"]
            or not training["attention"]["attention_supervision_enabled"]
            or training["core"]["attention_supervision_enabled"]
            or training["attention"]["attention_target_sha256"] !=
               teacher["teacher_tensor_sha256"]):
        raise ValueError("paired training schedule or teacher digest mismatch")
    def valid_sha(value):
        return (type(value) is str and len(value) == 64
                and value != "0" * 64
                and all(ch in "0123456789abcdef" for ch in value))
    for name in DIRECT:
        receipt = training[name]
        if (receipt["status"] != "completed" or
                receipt["completed_steps"] != protocol["steps"] or
                receipt["seed"] != protocol["seed"] or
                receipt["cpu_ns"] <= 0 or receipt["wall_ns"] <= 0 or
                receipt["parameter_count"] <= 0 or
                not valid_sha(receipt.get("initial_model_sha256")) or
                not valid_sha(receipt.get("trained_model_sha256"))):
            raise ValueError("partial, unbound or unmeasured training")
    if (not valid_sha(report.get("initial_core_sha256"))
            or any(training[name]["initial_model_sha256"] !=
                   report["initial_core_sha256"] for name in ("core", "attention"))):
        raise ValueError("paired initial model tensor digest mismatch")
    if (type(raw_traces) is not list
            or report.get("full_system2_trace_count") != len(raw_traces)
            or report.get("full_system2_trace_manifest_sha256") != _digest(raw_traces)):
        raise ValueError("missing or altered full System2 trajectory manifest")
    traces = {}
    for receipt in raw_traces:
        if type(receipt) is not dict:
            raise ValueError("malformed System2 trace row")
        key = (receipt.get("cohort"), receipt.get("arm"), receipt.get("case_id"))
        if key in traces:
            raise ValueError("duplicate System2 trace entry")
        traces[key] = receipt
    # Replay exact archived initial and fitted model bytes using no Torch and
    # no original serializer. These attest byte consistency, NOT training acts.
    saved = report.get("checkpoint_materialization")
    checkpoint_names = {"core_initial", *DIRECT}
    if (type(saved) is not dict or
            set(saved.get("files", {})) != checkpoint_names or
            type(saved.get("cpu_ns")) is not int or saved["cpu_ns"] <= 0 or
            type(saved.get("wall_ns")) is not int or saved["wall_ns"] <= 0 or
            saved.get("independent_execution_attested") is not False):
        raise ValueError("complete bounded checkpoint cost and inventory required")
    checkpoint_bytes = 0
    for name in sorted(checkpoint_names):
        entry = saved["files"][name]
        expected_name = f"group-{name}.safetensors"
        if (type(entry) is not dict or entry.get("file") != expected_name or
                entry.get("authority") != "DENY_ALL"):
            raise ValueError("unexpected or unbound checkpoint file")
        replay = verify_checkpoint_file(root / expected_name)
        checkpoint_bytes += replay["bytes"]
        reference = (report["initial_core_sha256"] if name == "core_initial"
                     else training[name]["trained_model_sha256"])
        if (entry.get("model_sha256") != reference or
                replay["model_sha256"] != reference or
                entry.get("checkpoint_sha256") != replay["checkpoint_sha256"] or
                entry.get("bytes") != replay["bytes"] or
                entry.get("tensor_count") != len(replay["tensors"])):
            raise ValueError("stored model bytes disagree with trained/initial SHA and manifest")
    if saved.get("total_artifact_bytes") != checkpoint_bytes:
        raise ValueError("checkpoint archive storage cost differs from actual bytes")
    expected = {(cohort, arm, case["case_id"]) for cohort in COHORTS
                for arm in ARMS for case in public[cohort]}
    cases = {cohort: {r["case_id"]: r for r in public[cohort]} for cohort in COHORTS}
    seen, by_arm, model_hashes, feature_hashes = set(), defaultdict(list), defaultdict(set), defaultdict(set)
    for row in rows:
        key = row["cohort"], row["arm"], row["case_id"]
        if key not in expected or key in seen:
            raise ValueError("unexpected, duplicate or out-of-cohort observation")
        seen.add(key)
        cohort, arm, cid = key
        case = cases[cohort][cid]
        label = replay_labels[cohort][cid]
        mode = MODES[arm]
        if (type(row["prediction"]) is not int
                or not -1 <= row["prediction"] <= 7
                or type(row["success"]) is not bool
                or type(row["valid_execution"]) is not bool
                or type(row["evidence_supported"]) is not bool
                or type(row["unsupported_attempt"]) is not bool
                or type(row["execution_status"]) is not str
                or row["execution_mode"] != mode
                or row["source_group"] != case["source_group"]
                or row["evidence_supported"] != (label is not None)
                or row["unsupported_attempt"] != (label is None)
                or row["valid_execution"] !=
                   (row["execution_status"] not in INVALID_STATUSES)
                or row["success"] != (label is not None
                                     and row["valid_execution"]
                                     and row["prediction"] == label)):
            raise ValueError("independently replayed evidence outcome differs")
        if (type(row["steps"]) is not int or not 1 <= row["steps"] <= 4
                or type(row["verifier_calls"]) is not int
                or not 0 <= row["verifier_calls"] <= 4):
            raise ValueError("bounded physical System2 steps and verifier calls required")
        if mode == "direct":
            if (row["execution_status"] != "direct_forward"
                    or row["steps"] != (1 if arm in ("static", "wide") else 4)
                    or row["verifier_calls"] != 0
                    or row["search_formula_work"] is not None
                    or row["prediction"] == -1):
                raise ValueError("direct control contains fabricated System2 work")
        else:
            if (row["execution_status"] == "direct_forward"
                    or row["verifier_calls"] != row["steps"]
                    or type(row["search_formula_work"]) is not int
                    or row["search_formula_work"] <= 0
                    or mode == "fixed" and row["steps"] != 4
                    or (row["execution_status"] == "verifier_accepted_not_independent_eval")
                        != row["success"]):
                raise ValueError("missing or inconsistent actual System2 verifier/compute evidence")
        if any(type(row[name]) is not int or row[name] <= 0
               for name in ("wall_ns", "cpu_ns")):
            raise ValueError("missing physical observation")
        for field in ("feature_sha256", "model_sha256"):
            value = row[field]
            if (type(value) is not str or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("unbound digest")
        if arm in SYSTEM2:
            owner = MODELS[arm]
            _verify_system2_trace(row, traces.get(key),
                                  critic["receipts"][owner]["parameters_sha256"])
        elif row.get("full_trace_sha256") is not None:
            raise ValueError("direct control must not claim an executed System2 trace")
        feature_hashes[(cohort, cid)].add(row["feature_sha256"])
        model_hashes[arm].add(row["model_sha256"])
        by_arm[f"{cohort}.{arm}"].append(row)
    expected_trace_keys = {key for key in expected if key[1] in SYSTEM2}
    if set(traces) != expected_trace_keys:
        raise ValueError("missing or extra full System2 execution trajectories")
    if seen != expected or any(len(v) != 1 for v in
                               (*feature_hashes.values(), *model_hashes.values())):
        raise ValueError("incomplete pairs, drifting frozen models or feature mismatch")
    for arm, owner in MODELS.items():
        if model_hashes[arm] != model_hashes[owner]:
            raise ValueError("loop execution changed the frozen model artifact")
    for arm in DIRECT:
        if model_hashes[arm] != {training[arm]["trained_model_sha256"]}:
            raise ValueError("evaluation model digest differs from frozen fitted weight bytes")
    for cid in replay_labels["test"]:
        if feature_hashes[("deleted", cid)] == feature_hashes[("test", cid)]:
            raise ValueError("deleted and original evidence cannot reuse a snapshot")
    summaries = {k: _summarize(values) for k, values in by_arm.items()}
    if report["summaries"] != summaries:
        raise ValueError("reported scores/timing disagree with complete raw observations")
    # Paired deltas are descriptive evidence, not a causal model or matched
    # total-compute acceptance test. Recompute directly from raw observations.
    paired = {}
    for cohort in COHORTS:
        core_rows = {r["case_id"]: r for r in by_arm[f"{cohort}.core"]}
        candidate_rows = {r["case_id"]: r for r in by_arm[f"{cohort}.attention"]}
        if core_rows.keys() != candidate_rows.keys():
            raise ValueError("attention/core pairs do not match")
        rescued = sum(candidate_rows[k]["success"] and not v["success"]
                      for k, v in core_rows.items())
        harmed = sum(v["success"] and not candidate_rows[k]["success"]
                     for k, v in core_rows.items())
        paired[cohort] = dict(n=len(core_rows), rescued=rescued, harmed=harmed,
            correct_delta=rescued-harmed,
            core_online_cpu_ns=sum(v["cpu_ns"] for v in core_rows.values()),
            attention_online_cpu_ns=sum(v["cpu_ns"] for v in candidate_rows.values()),
            core_training_cpu_ns=training["core"]["cpu_ns"],
            attention_training_cpu_ns=training["attention"]["cpu_ns"],
            equal_total_compute_demonstrated=False,
            independent_future_samples_established=False)
    loop_comparisons = {}
    for cohort in COHORTS:
        loop_comparisons[cohort] = {}
        for mode in ("fixed", "ndu"):
            left = {r["case_id"]: r for r in by_arm[f"{cohort}.core_{mode}"]}
            right = {r["case_id"]: r for r in by_arm[f"{cohort}.attention_{mode}"]}
            if left.keys() != right.keys():
                raise ValueError("missing paired System2 episode")
            loop_comparisons[cohort][mode] = dict(
                n=len(left),
                rescued=sum(right[k]["success"] and not v["success"] for k,v in left.items()),
                harmed=sum(v["success"] and not right[k]["success"] for k,v in left.items()),
                baseline_verifier_calls=sum(v["verifier_calls"] for v in left.values()),
                candidate_verifier_calls=sum(v["verifier_calls"] for v in right.values()),
                baseline_cpu_ns=sum(v["cpu_ns"] for v in left.values()),
                candidate_cpu_ns=sum(v["cpu_ns"] for v in right.values()),
                equal_total_compute_demonstrated=False,
                model_execution_independently_attested=False)
    return dict(schema="hepta.group.paired-attention-independent-review.v1",
                passed=True, authority="DENY_ALL",
                complete_group_replay=True,
                public_evidence_labels_independently_recomputed=True,
                teacher_bound_to_train_sources=True,
                exact_archived_model_bytes_replayed=True,
                same_initial_core_claim_still_unattested=True,
                equal_compute_claim_allowed=False,
                real_host_execution_independently_attested=False,
                future_task_efficacy_proved=False,
                descriptive_paired=paired,
                real_system2_descriptive_paired=loop_comparisons,
                observation_sha256=_digest(rows),
                protocol_sha256=_digest(protocol),
                paired_summaries=summaries)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    with Path(args.output).open("x") as stream:
        json.dump(review(args.root), stream, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
