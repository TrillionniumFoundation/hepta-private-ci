"""Physical batch receipts and train-internal threshold selection for V4."""
from collections import defaultdict
from dataclasses import replace
import math
import time

import torch

from execution_meter import TRANSFORMER_POLICY_SCHEMA, WorkLedger
from group_encoder import digest_json
from multirc_data import score_multirc
from paired_execution import PHASES
from transformer_work import PROFILE


ARMS = ("pooled", "token", "intervention", "recurrent", "one_step", "reset_state", "query_only")
COHORTS = ("full", "deleted")
ARM_DEPTHS = dict(pooled=1, token=1, intervention=1, recurrent=3, one_step=1, reset_state=3, query_only=1)
PUBLIC_TENSORS = ("facts", "question", "candidate", "fact_mask", "question_mask", "candidate_mask")


class DeletedDataset:
    """A separately trained query control with labels unchanged and evidence absent."""

    def __init__(self, data):
        self.data, self.targets, self.source_groups = data, data.targets, data.source_groups

    def validate(self, input_dim):
        self.data.validate(input_dim)

    def take(self, indices):
        batch = self.data.take(indices)
        return replace(batch, facts=torch.zeros_like(batch.facts), fact_mask=torch.zeros_like(batch.fact_mask),
                       evidence_targets=None, evidence_supervision=None)


def model_inputs(batch, *, deleted=False):
    values = [getattr(batch, name) for name in PUBLIC_TENSORS]
    if deleted:
        values[0], values[3] = torch.zeros_like(values[0]), torch.zeros_like(values[3])
    return values


def infer(model, cases, bank, *, depth=1, deleted=False, batch_size=8, prefix="evaluation", reset=False):
    """Targets never enter model arguments; receipts count each physical batch once."""
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("evaluation requires a frozen model")
    if not cases or type(batch_size) is not int or not 1 <= batch_size <= 64 or not 1 <= depth <= model.max_hops:
        raise ValueError("nonempty cases and bounded inference batch/depth required")
    probabilities, batches = [], []
    with torch.no_grad():
        for start in range(0, len(cases), batch_size):
            selected = cases[start:start + batch_size]
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            policy = dict(schema=TRANSFORMER_POLICY_SCHEMA, arithmetic_profile=PROFILE,
                          mode="observe", wall_time_ns=600_000_000_000,
                          max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)
            meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**18))
            batch = bank.batch(selected)
            with meter.scope("evaluation", "proposer"):
                logits = model(*model_inputs(batch, deleted=deleted), steps=depth, reset_state=reset)
                positive = logits.softmax(-1)[:, 1].tolist()
                if len(positive) != len(selected) or any(not math.isfinite(p) or not 0 <= p <= 1 for p in positive):
                    raise ValueError("finite aligned positive probabilities required")
            observation = meter.report()
            probabilities.extend(positive)
            batches.append(dict(batch_id=f"{prefix}/{start // batch_size}",
                case_ids=[case.case_id for case in selected], steps=depth,
                proposal_steps=len(selected) * depth, cpu_ns=time.process_time_ns() - cpu,
                wall_ns=time.perf_counter_ns() - wall,
                formula_flops=observation["phase_flops"]["evaluation"], work_observation=observation))
    return probabilities, batches


def choose_threshold(cases, probabilities):
    """Same preregistered grid and tie breaks for every arm; no final outcomes."""
    if (not cases or len(cases) != len(probabilities)
            or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities)):
        raise ValueError("aligned complete tuning questions required")
    candidates = []
    for index in range(1, 20):
        threshold = index / 20
        metrics = score_multirc(cases, [int(p >= threshold) for p in probabilities])
        candidates.append(dict(threshold=threshold, metrics=metrics))
    selected = max(candidates, key=lambda row: (row["metrics"]["f1_a"],
        row["metrics"]["exact_match"], -abs(row["threshold"] - .5), -row["threshold"]))
    return dict(threshold=selected["threshold"], candidates=candidates,
                criterion="F1a_then_EM_then_nearest_0.5_then_lower", final_outcomes_used=False)


def summarize_panel(cases, rows, batches):
    if [row["case_id"] for row in rows] != [case.case_id for case in cases]:
        raise ValueError("unaligned or incomplete question candidates")
    batch_ids = [row["batch_id"] for row in batches]
    physical_cases = [case_id for row in batches for case_id in row["case_ids"]]
    if (len(batch_ids) != len(set(batch_ids)) or physical_cases != [case.case_id for case in cases]
            or any(row["batch_id"] not in batch_ids for row in rows)):
        raise ValueError("unique aligned physical inference receipts required")
    metrics = score_multirc(cases, [row["prediction"] for row in rows])
    metrics.update(n=len(rows), raw_argmax_metrics=score_multirc(cases, [row["raw_argmax"] for row in rows]),
        physical_batches=len(batches), cpu_ns=sum(row["cpu_ns"] for row in batches),
        wall_ns=sum(row["wall_ns"] for row in batches),
        proposal_steps=sum(row["proposal_steps"] for row in batches),
        formula_flops=sum(row["formula_flops"] for row in batches)
            if all(row["formula_flops"] is not None for row in batches) else None,
        batch_size_max=max(len(row["case_ids"]) for row in batches),
        timing_scope="physical_sequential_batch_includes_padding_and_measurement",
        per_answer_latency_measured=False, strict_equal_compute=False)
    metrics["raw_argmax_metrics"]["n"] = len(rows)
    return metrics


def evaluate_panel(models, cases, bank, protocol, *, prefix):
    protocol_sha = digest_json(protocol)
    observations, receipts, summaries = [], [], {}
    for cohort in protocol["expected_cohorts"]:
        for arm in protocol["expected_arms"]:
            deleted = cohort == "deleted" or protocol["arm_input_transforms"].get(arm) == "delete_evidence"
            probabilities, batches = infer(models[arm], cases, bank, depth=protocol["arm_depths"][arm],
                deleted=deleted, prefix=f"{prefix}/{cohort}/{arm}", reset=arm == "reset_state")
            by_case = {case_id: row["batch_id"] for row in batches for case_id in row["case_ids"]}
            panel = []
            for case, probability in zip(cases, probabilities):
                feature = bank.public(case, deleted=deleted)
                panel.append(dict(case_id=case.case_id, arm=arm, cohort=cohort,
                    batch_id=by_case[case.case_id], p_positive=probability,
                    prediction=int(probability >= protocol["arm_thresholds"][arm]),
                    raw_argmax=int(probability > .5), valid=True,
                    feature_sha256=feature["feature_sha256"], model_sha256=protocol["arm_model_sha256"][arm],
                    protocol_sha256=protocol_sha))
            for row in batches:
                row.update(arm=arm, cohort=cohort)
            observations.extend(panel)
            receipts.extend(batches)
            summaries[f"{cohort}.{arm}"] = summarize_panel(cases, panel, batches)
    return observations, receipts, summaries


def evidence_deltas(rows):
    pairs = defaultdict(dict)
    for row in rows:
        pairs[(row["arm"], row["case_id"])][row["cohort"]] = row
    results = {}
    for arm in sorted({key[0] for key in pairs}):
        matched = [value for (name, _), value in pairs.items() if name == arm]
        if any(set(value) != {"full", "deleted"} for value in matched):
            raise ValueError("paired evidence diagnostic requires both cohorts")
        shifts = [abs(value["full"]["p_positive"] - value["deleted"]["p_positive"]) for value in matched]
        results[arm] = dict(n=len(matched), prediction_flips=sum(value["full"]["prediction"] !=
            value["deleted"]["prediction"] for value in matched),
            raw_argmax_flips=sum(value["full"]["raw_argmax"] != value["deleted"]["raw_argmax"] for value in matched),
            mean_absolute_probability_shift=sum(shifts) / len(shifts),
            maximum_absolute_probability_shift=max(shifts), causal_truth_claim=False)
    return results
