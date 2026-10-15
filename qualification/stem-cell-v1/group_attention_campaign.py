"""Paired real-Granite evidence-attention curriculum versus original Group Core.

Research/SHADOW/DENY_ALL. Frozen shared token snapshots, equal initial Core
weights, minibatch/depth schedule and train source rows. Extra auxiliary
attention work is physically paid, so equality of actual compute is NOT claimed.
Independent label review lives in group_attention_campaign_review.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
from dataclasses import replace as dataclass_replace
import time

import torch

from execution_meter import WorkLedger, TRANSFORMER_POLICY_SCHEMA
from group_attention_curriculum import build_train_attention
from group_checkpoint_audit import verify_checkpoint_file
from safetensors.torch import save_file as write_safetensors
from group_campaign import packed, critic_rows
from group_core import Core
from group_critic import fit_critic
from group_encoder import FrozenTokenEncoder, acquire, digest_json, file_digest
from group_features import FeatureCache
from group_loop import execute_group, parameter_digest
from group_tasks import compose_tasks, delete_evidence, feedback_vector, make_tasks, supported_answer, verify
from group_training import StaticHead, fit_model, matched_static
from collections import Counter
from paired_execution import PHASES
from transformer_work import PROFILE


OPTIMIZER_PROFILES = {
    "sgd_v1": {"core_optimizer_kind": "sgd", "core_learning_rate": 0.05},
    "adam_v1": {"core_optimizer_kind": "adam", "core_learning_rate": 0.008},
}


def summarize(rows):
    times = sorted(x["wall_ns"] for x in rows)
    return dict(n=len(rows), correct=sum(x["success"] for x in rows),
                failed_episodes=sum(not x["valid_execution"] for x in rows),
                unsupported_attempts=sum(x["unsupported_attempt"] for x in rows),
                steps=sum(x["steps"] for x in rows),
                verifier_calls=sum(x["verifier_calls"] for x in rows),
                execution_statuses=dict(Counter(x["execution_status"] for x in rows)),
                cpu_ns=sum(x["cpu_ns"] for x in rows),
                wall_ns=sum(times),
                p50_ns=times[len(times) // 2],
                p95_ns=times[min(len(times) - 1, int(.95 * len(times)))])


def run(snapshot, output, *, seed=41, train_count=256, heldout_count=96,
        steps=120, attention_weight=0.1, training_profile="sgd_v1",
        terminal_guard=False, training_feedback_policy="legacy_oracle_v1"):
    if (type(seed) is not int or seed < 0 or type(train_count) is not int
            or not 16 <= train_count <= 2048 or type(heldout_count) is not int
            or not 12 <= heldout_count <= 256 or type(steps) is not int
            or not 1 <= steps <= 10000 or type(attention_weight) not in (int, float)
            or not math.isfinite(attention_weight) or not 0 < attention_weight <= 1
            or type(training_profile) is not str
            or training_profile not in OPTIMIZER_PROFILES
            or type(terminal_guard) is not bool
            or type(training_feedback_policy) is not str
            or training_feedback_policy not in ("legacy_oracle_v1", "no_verifier_v1")):
        raise ValueError("registered finite bounded paired campaign required")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    # Initialize Torch's lazy framework registrations before entering any
    # strict per-operator metering scope. This is lifecycle-paid (the clocks
    # start above), not silently attributed to one SGD or search operation.
    lazy_start_wall, lazy_start_cpu = time.perf_counter_ns(), time.process_time_ns()
    import torch._dynamo  # noqa: F401
    lazy_setup_cost = dict(wall_ns=time.perf_counter_ns() - lazy_start_wall,
                           cpu_ns=time.process_time_ns() - lazy_start_cpu)
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    tasks = {"train": make_tasks("train", train_count, seed=seed),
             "validation": make_tasks("validation", heldout_count, seed=seed),
             "test": make_tasks("test", heldout_count, seed=seed),
             "long": make_tasks("test", heldout_count, seed=seed + 1, longer=True)}
    tasks["deleted"] = [delete_evidence(t) for t in tasks["test"]]
    short = [t for t in tasks["test"] if t.depth == 2]
    tasks["composition"] = [compose_tasks(a, b) for a in short for b in short
                            if a.family != b.family][:heldout_count]
    if not tasks["composition"]:
        raise ValueError("composition cohort lacks distinct public source families")
    groups = [set(t.source_group for t in tasks[s]) for s in ("train", "validation", "test", "long")]
    if any(a & b for i, a in enumerate(groups) for b in groups[i + 1:]):
        raise ValueError("independent source groups crossed train/validation/test/long")
    source_files = ("group_core.py", "group_training.py", "group_attention_curriculum.py",
                    "group_step_supervision.py", "group_attention_campaign.py",
                    "group_attention_campaign_review.py", "group_campaign_review.py",
                    "group_tasks.py", "group_encoder.py", "group_features.py",
                    "hf_encoder_kernel.py", "execution_meter.py", "aten_work.py",
                    "group_campaign.py", "group_loop.py", "group_critic.py",
                    "system2_execution.py", "ndu_continuation.py",
                    "paired_execution.py", "transformer_work.py", "next_round_matrix.py",
                    "group_checkpoint_audit.py", "group_trace_semantic_audit.py",
                    "group_attention_slot_review.py", "group_token_id_binding.py",
                    "group_abort_trace_audit.py", "group_attention_coverage.py",
                    "group_terminal_evidence.py",
                    "group_terminal_receipt_review.py",
                    "group_feedback_factorial_review.py",
                    "group_feedback_factorial_campaign.py")
    frozen_optimizer = OPTIMIZER_PROFILES[training_profile]
    protocol = dict(schema="hepta.group.paired-step-campaign.v1",
        training_profile=training_profile,
        terminal_guard=terminal_guard,
        training_feedback_policy=training_feedback_policy,
        optimizer_policy=dict(frozen_optimizer),
        optimizer_comparison_scope="registered_training_regime_not_isolated_optimizer_effect",
        seed=seed, steps=steps, train_count=train_count,
        heldout_count=heldout_count, max_depth=4, attention_weight=attention_weight,
        train_source_groups=[t.source_group for t in tasks["train"]],
        frozen_candidate_arms=["static", "wide", "core", "attention",
                               "core_fixed", "attention_fixed",
                               "core_ndu", "attention_ndu"],
        critic_fit_splits=["validation_fit", "validation_calibration"],
        live_system2_modes=["fixed", "ndu"],
        model_init_shared=["core", "attention"], training_sample_seed=seed,
        evaluation_cohorts=["test", "long", "deleted", "composition"],
        causal_composition_independence=False,
        source_sha256={p: file_digest(Path(__file__).parent / p) for p in source_files},
        public_cases={cohort: [dict(case_id=t.task_id, source_group=t.source_group,
                                    family=t.family, text=t.text)
                               for t in cases] for cohort, cases in tasks.items()},
        pretrained_encoder_required=True, matched_total_compute=False,
        future_natural_task_efficacy=False, production_authorized=False)
    (root / "protocol.json").write_text(json.dumps(protocol, sort_keys=True))
    encoder_wall, encoder_cpu = time.perf_counter_ns(), time.process_time_ns()
    encoder = FrozenTokenEncoder(snapshot, max_tokens=256)
    cache = FeatureCache("agent:step-campaign", 1,
                         max_entries=sum(map(len, tasks.values())),
                         max_bytes=512 * 1024 * 1024)
    policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=PROFILE,
                  mode="observe", wall_time_ns=1_800_000_000_000,
                  max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)
    meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**15))
    features = {}
    for cohort, cases in tasks.items():
        features[cohort] = []
        for task in cases:
            identity = encoder.identity(task.text, scope=cache.scope, generation=cache.generation)
            with meter.scope("inference", "encoder"):
                features[cohort].append(cache.get_or_encode(
                    identity, lambda t=task, i=identity: encoder.encode(t.text, i)))
    train_forward_token_witnesses = [
        encoder.token_id_witnesses[snapshot.identity]
        for snapshot in features["train"]]
    encoder_cost = dict(actual_forward_calls=encoder.calls,
        token_id_witness_schema="hepta.group.encoder-token-ids.v1",
        train_forward_token_id_witnesses=train_forward_token_witnesses,
        logical_requests=sum(map(len, tasks.values())),
        wall_ns=time.perf_counter_ns() - encoder_wall,
        cpu_ns=time.process_time_ns() - encoder_cpu,
        feature_cache_canonical_bytes=cache.nbytes,
        encoder_meter=meter.report(), model_material=encoder.material,
        full_formula_flops_qualified=False)
    (root / "encoder.json").write_text(json.dumps(encoder_cost, sort_keys=True))
    teacher_wall, teacher_cpu = time.perf_counter_ns(), time.process_time_ns()
    teacher, teacher_receipt, per_operation_targets = build_train_attention(
        tasks["train"], features["train"], encoder.tokenizer, max_depth=4,
        token_id_witnesses=train_forward_token_witnesses, return_operation_masks=True)
    teacher_receipt["cpu_ns"] = time.process_time_ns() - teacher_cpu
    teacher_receipt["wall_ns"] = time.perf_counter_ns() - teacher_wall
    (root / "teacher.json").write_text(json.dumps(teacher_receipt, sort_keys=True))
    x, mask = packed(features["train"])
    labels = torch.tensor([t.target for t in tasks["train"]])
    if teacher.shape != (len(labels), 4, x.shape[1]):
        raise ValueError("attention teacher feature alignment failed")
    core = Core(384, 32, 8)
    initial_core_digest = parameter_digest(core)
    wide, geometry = matched_static(core, 384)
    def feedback(indices, guesses):
        return torch.tensor(
            [feedback_vector(v.accepted, v.feedback)
             for v in (verify(tasks["train"][i], guess)
                       for i, guess in zip(indices, guesses))], dtype=torch.float32)
    models, training = {}, {}
    for name, model, depth, special in (
            ("static", StaticHead(384, 8), 1, False),
            ("wide", wide, 1, False),
            ("core", core, 4, False),
            ("attention", core, 4, True)):
        optimizer_kind = ("sgd" if name in ("static", "wide")
                          else frozen_optimizer["core_optimizer_kind"])
        learning_rate = (0.05 if name in ("static", "wide")
                         else frozen_optimizer["core_learning_rate"])
        models[name], training[name] = fit_model(
            model, x, mask, labels, steps=steps, seed=seed, max_depth=depth,
            optimizer_kind=optimizer_kind, learning_rate=learning_rate,
            feedback_fn=(feedback if depth > 1
                         and training_feedback_policy == "legacy_oracle_v1" else None),
            attention_targets=teacher if special else None,
            operation_targets=per_operation_targets if special else None,
            attention_weight=attention_weight,
            terminal_guard=terminal_guard if special else False,
            training_feedback_policy=training_feedback_policy)
        if training[name]["status"] != "completed" or training[name]["completed_steps"] != steps:
            raise ValueError("partial training cannot be scored as completed")
    if (teacher_receipt["operation_mask_sha256"] !=
            training["attention"]["operation_target_sha256"]
            or teacher_receipt["coverage_loss_contract"] !=
               training["attention"]["attention_loss_contract"]
            or not training["attention"]["operation_coverage_enabled"]
            or training["attention"].get("terminal_guard_enabled") is not terminal_guard
            or any(training[k].get("training_feedback_policy") != training_feedback_policy
                   for k in training)):

        raise ValueError("required public fact coverage was lost in measured training")
    if (training["core"]["parameter_count"] != training["attention"]["parameter_count"]
            or training["core"]["initial_model_sha256"] != initial_core_digest
            or training["attention"]["initial_model_sha256"] != initial_core_digest
            or any(training[name]["trained_model_sha256"] != parameter_digest(models[name])
                   for name in training)
            or training["core"]["sample_and_depth_sha256"] !=
               training["attention"]["sample_and_depth_sha256"]):
        raise ValueError("paired initial weights, terminal weights or sampling controls drifted")
    # Store the exact starting Core and all four fitted model tensors, not just
    # uncheckable parameter labels. The independent auditor uses stdlib only.
    archive_wall, archive_cpu = time.perf_counter_ns(), time.process_time_ns()
    checkpoint_models = {"core_initial": core, **models}
    checkpoints = {}
    for checkpoint_id, candidate in checkpoint_models.items():
        output_path = root / f"group-{checkpoint_id}.safetensors"
        write_safetensors({name: value.detach().cpu().contiguous().clone()
                           for name, value in candidate.state_dict().items()},
                          str(output_path))
        checked = verify_checkpoint_file(output_path)
        if checked["model_sha256"] != parameter_digest(candidate):
            raise ValueError("safetensors bytes do not match source weights")
        checkpoints[checkpoint_id] = dict(
            file=output_path.name,
            model_sha256=checked["model_sha256"],
            checkpoint_sha256=checked["checkpoint_sha256"],
            bytes=checked["bytes"],
            tensor_count=len(checked["tensors"]),
            authority="DENY_ALL")
    checkpoint_cost = dict(
        wall_ns=time.perf_counter_ns() - archive_wall,
        cpu_ns=time.process_time_ns() - archive_cpu,
        total_artifact_bytes=sum(v["bytes"] for v in checkpoints.values()),
        files=checkpoints,
        independent_execution_attested=False)

    # Fit model-specific frozen critics ONLY on the separate validation group.
    # This pays the complete existing propose/verify/value/revise executor.
    critic_start_wall, critic_start_cpu = time.perf_counter_ns(), time.process_time_ns()
    critics, critic_receipts = {}, {}
    for owner in ("core", "attention"):
        midpoint = len(tasks["validation"]) // 2
        fit_rows = critic_rows(models[owner], tasks["validation"][:midpoint],
                               features["validation"][:midpoint], 4)
        cal_rows = critic_rows(models[owner], tasks["validation"][midpoint:],
                               features["validation"][midpoint:], 4)
        for records, label in ((fit_rows, "validation_fit"),
                               (cal_rows, "validation_calibration")):
            for item in records:
                item["split"] = label
        critics[owner] = fit_critic(fit_rows, cal_rows, cutoff_ns=time.time_ns(),
                                    steps=80, seed=seed)
        critic_receipts[owner] = dict(metadata=critics[owner].metadata,
            parameters_sha256=critics[owner].params_sha256,
            fit_rows=len(fit_rows), calibration_rows=len(cal_rows))
    critic_cost = dict(wall_ns=time.perf_counter_ns() - critic_start_wall,
                       cpu_ns=time.process_time_ns() - critic_start_cpu,
                       receipts=critic_receipts,
                       separate_fits_charged=True,
                       source_group_independence_claimed=False)

    rows, summaries, system2_traces = [], {}, []
    execution_arms = (
        ("static", "static", "direct"),
        ("wide", "wide", "direct"),
        ("core", "core", "direct"),
        ("attention", "attention", "direct"),
        ("core_fixed", "core", "fixed"),
        ("attention_fixed", "attention", "fixed"),
        ("core_ndu", "core", "ndu"),
        ("attention_ndu", "attention", "ndu"),
    )
    if [a for a, _, _ in execution_arms] != protocol["frozen_candidate_arms"]:
        raise ValueError("execution arms differ from predeclared policy")
    for cohort in protocol["evaluation_cohorts"]:
        for name, owner, execution_mode in execution_arms:
            model = models[owner]
            arm_rows = []
            for task, snapshot in zip(tasks[cohort], features[cohort]):
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                if execution_mode == "direct":
                    with torch.no_grad():
                        t, m = packed([snapshot])
                        depth = 1 if owner in ("static", "wide") else 4
                        guess = int(model(t, steps=depth, mask=m).argmax(1))
                    status, count_steps, verifier_calls, search_work = (
                        "direct_forward", depth, 0, None)
                    valid = True
                else:
                    # The live proposer/checker/controller receives only
                    # public evidence; the original held-out target is retained
                    # exclusively by the external scoring loop below.
                    public_task = dataclass_replace(task, target=-1)
                    result = execute_group(public_task, model, snapshot,
                                           critics[owner], mode=execution_mode,
                                           max_steps=4)
                    candidate = result["candidate"]
                    guess = (ord(candidate) - 65
                             if isinstance(candidate, str) and len(candidate) == 1
                             and "A" <= candidate <= "H" else -1)
                    status = result["status"]
                    count_steps = result["workspace_steps"]
                    verifier_calls = sum(t["kind"] == "verify" for t in result["trace"])
                    search_work = result["work_observation"]["phase_flops"]["search"]
                    valid = status not in {
                        "budget_exhausted", "callback_failed", "resource_budget_stop",
                        "ndu_stop:expired_policy", "ndu_stop:continuation_support_violated"}
                wall_ns, cpu_ns = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
                trace_sha256 = None
                if execution_mode != "direct":
                    trace_payload = dict(
                        schema="hepta.group.system2-full-trace.v2",
                        authority="DENY_ALL",
                        cohort=cohort, arm=name, case_id=task.task_id,
                        mode=execution_mode, status=status,
                        feature_sha256=snapshot.digest,
                        model_sha256=parameter_digest(model),
                        critic_sha256=critics[owner].params_sha256,
                        final_candidate=result["candidate"],
                        calls=result["calls"],
                        trace=result["trace"],
                        workspace_bindings=result["workspace_bindings"],
                        verifier_statuses=result["verifier_statuses"],
                        proposed_candidates=result["proposed_candidates"],
                        ndu_decisions=result.get("ndu_decisions", []),
                        independent_success_established=False,
                        production_authorized=False)
                    trace_sha256 = digest_json(trace_payload)
                    system2_traces.append(trace_payload)
                truth = supported_answer(task)
                supported = truth is not None
                success = bool(supported and valid and guess == truth)
                row = dict(cohort=cohort, arm=name, case_id=task.task_id,
                    source_group=task.source_group, feature_sha256=snapshot.digest,
                    model_sha256=parameter_digest(model), prediction=guess,
                    evidence_supported=supported, success=success,
                    unsupported_attempt=not supported,
                    execution_mode=execution_mode, execution_status=status,
                    full_trace_sha256=trace_sha256,
                    valid_execution=bool(valid), steps=count_steps,
                    verifier_calls=verifier_calls, search_formula_work=search_work,
                    cpu_ns=cpu_ns, wall_ns=wall_ns)
                arm_rows.append(row)
                rows.append(row)
            summaries[f"{cohort}.{name}"] = summarize(arm_rows)
            print(json.dumps({"cohort": cohort, "arm": name, **summaries[f"{cohort}.{name}"]}),
                  flush=True)
    encoder.verify_files()
    from hf_encoder_kernel import verify_loaded_safetensors
    final_loaded_tensor_verification = verify_loaded_safetensors(
        torch, encoder.model, encoder.root)
    report = dict(schema="hepta.group.paired-step-observation.v1",
        protocol_sha256=digest_json(protocol), seed=seed,
        runtime=dict(python=platform.python_version(), torch=torch.__version__),
        initial_core_sha256=initial_core_digest, training=training,
        checkpoint_materialization=checkpoint_cost,
        wide_parameter_match=geometry, encoder_cost=encoder_cost,
        final_loaded_tensor_verification=final_loaded_tensor_verification,
        teacher=teacher_receipt, summaries=summaries, critic_cost=critic_cost,
        torch_lazy_setup_cost=lazy_setup_cost,
        real_system2_callbacks_executed=True,
        heldout_target_stripped_before_system2_callbacks=True,
        same_model_critic_frozen_on_validation_only=True,
        actual_lifecycle_cpu_ns=time.process_time_ns() - start_cpu,
        actual_lifecycle_wall_ns=time.perf_counter_ns() - start_wall,
        same_initial_core=True, same_training_cases=True, same_optimizer_updates=True,
        identical_training_sample_schedule=True, equal_actual_training_work=False,
        source_group_independence_attested=False,
        genuine_pretrained_encoder_executed=True, natural_future_win_established=False,
        independent_model_execution_attested=False, production_authorized=False,
        authority="DENY_ALL")
    report["full_system2_trace_count"] = len(system2_traces)
    report["full_system2_trace_manifest_sha256"] = digest_json(system2_traces)
    (root / "system2-traces.json").write_text(
        json.dumps(system2_traces, sort_keys=True, allow_nan=False))
    (root / "observations.json").write_text(json.dumps(rows, sort_keys=True, allow_nan=False))
    (root / "report.json").write_text(json.dumps(report, sort_keys=True, allow_nan=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--train-count", type=int, default=256)
    parser.add_argument("--heldout-count", type=int, default=96)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--attention-weight", type=float, default=.1)
    parser.add_argument("--training-profile", choices=sorted(OPTIMIZER_PROFILES),
                        default="sgd_v1")
    parser.add_argument("--training-feedback-policy",
                        choices=("legacy_oracle_v1", "no_verifier_v1"),
                        default="legacy_oracle_v1")
    parser.add_argument("--terminal-guard", action="store_true",
                        help="research: suppress final labels before all TRAIN evidence slots")
    parser.add_argument("--acquire", action="store_true")
    args = parser.parse_args()
    if args.acquire:
        acquire(args.snapshot)
    run(args.snapshot, args.output, seed=args.seed, train_count=args.train_count,
        heldout_count=args.heldout_count, steps=args.steps,
        attention_weight=args.attention_weight, training_profile=args.training_profile,
        terminal_guard=args.terminal_guard,
        training_feedback_policy=args.training_feedback_policy)


if __name__ == "__main__":
    main()
