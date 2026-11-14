"""Outcome-blind source selection and raw MultiRC campaign aggregation."""
from collections import Counter, defaultdict
import json
from pathlib import Path

import torch

from execution_meter import POLICY_SCHEMA, WorkLedger
from group_reader_training import ReaderBatch
from multirc_data import score_multirc
from paired_execution import PHASES


ARMS = ("static", "one_step", "fixed", "adaptive", "native_ndu", "no_verifier",
        "reset_state", "query_only")
COHORTS = ("full", "deleted", "permuted")
PARAGRAPH_CAPS = dict(train=32, tune=8, verifier_fit=8, critic_fit=8, critic_calibration=8, final=16)


def write_json(root, name, value):
    (Path(root) / name).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def select_paragraphs(cases, count):
    """Select complete paragraphs lexically by content hash, never by label."""
    sources = sorted({case.source_hash for case in cases})[:count]
    if len(sources) != count:
        raise ValueError("insufficient registered source paragraphs")
    return [case for case in cases if case.source_hash in set(sources)]


def gate_cases(cases, questions=8):
    keys = sorted({case.question_key for case in cases})[:questions]
    if len(keys) != questions:
        raise ValueError("insufficient complete training questions for gate")
    return [case for case in cases if case.question_key in set(keys)]


def deleted_batch(batch):
    return ReaderBatch(torch.zeros_like(batch.facts), batch.query.clone(),
                       torch.zeros_like(batch.mask), batch.targets.clone(), batch.source_groups)


def predict_batch(model, batch, depth, *, batch_size=32):
    """Observe no-gradient diagnostics without feeding targets to the model."""
    policy = dict(schema=POLICY_SCHEMA, mode="strict", wall_time_ns=180_000_000_000,
                  max_process_rss_bytes=None, rapl_zone=None, rapl_max_power_watts=None)
    meter = WorkLedger(policy, dict.fromkeys(PHASES, 10**16))
    predictions = []
    with meter.scope("evaluation", "bank"), torch.no_grad():
        for start in range(0, len(batch.targets), batch_size):
            indices = list(range(start, min(len(batch.targets), start + batch_size)))
            public = batch.take(indices)
            logits = model(public.facts, public.query, steps=depth, mask=public.mask)
            predictions.extend(logits.argmax(-1).tolist())
    return predictions, meter.report()


def training_feedback(verifier):
    """Frozen external model agreement, never a gold-label verifier."""
    def callback(batch, guesses):
        with torch.no_grad():
            _, logits = verifier.step(batch.facts, batch.query, mask=batch.mask)
            probabilities = logits.softmax(-1)
            agreement = logits.argmax(-1).eq(torch.tensor(guesses)).to(torch.float32).unsqueeze(-1)
            present = batch.mask.any(-1).to(torch.float32).unsqueeze(-1)
            return torch.cat((probabilities, agreement, present), dim=-1)
    return callback


def summarize(cases, rows, majority_prediction):
    if [row["case_id"] for row in rows] != [case.case_id for case in cases]:
        raise ValueError("complete, aligned question candidate rows required")
    summary = score_multirc(cases, [row["prediction"] for row in rows])
    summary["questions"] = len({case.question_key for case in cases})
    summary["n"] = len(cases)
    summary["baselines"] = {name: score_multirc(cases, [value] * len(cases)) for name, value in
                             (("all_positive", 1), ("all_negative", 0),
                              ("training_majority", majority_prediction))}
    for key in ("steps", "cpu_ns", "wall_ns", "native_subprocess_wall_ns"):
        summary[key] = sum(row[key] for row in rows)
    for key in ("formula_flops", "native_child_cpu_ns", "total_online_cpu_ns"):
        summary[key] = sum(row[key] for row in rows) if all(row[key] is not None for row in rows) else None
    times = sorted(row["wall_ns"] for row in rows)
    summary.update(valid_executions=sum(row["valid"] for row in rows),
                   statuses=dict(Counter(row["status"] for row in rows)),
                   p50_wall_ns=times[len(times) // 2],
                   p95_wall_ns=times[min(len(times) - 1, int(.95 * len(times)))],
                   strict_equal_compute=False,
                   timing_scope="outer_online_parent_cpu_and_wall_plus_separate_child_cpu")
    return summary


def freeze_manifest(parts):
    groups = {name: sorted({case.source_hash for case in cases}) for name, cases in parts.items()}
    seen = set()
    for sources in groups.values():
        if seen.intersection(sources):
            raise ValueError("source paragraph leaked between fitting and final partitions")
        seen.update(sources)
    questions = defaultdict(list)
    for case in parts["final"]:
        questions[json.dumps(case.question_key, separators=(",", ":"))].append(case.case_id)
    return dict(partitions=groups, final_case_ids=[case.case_id for case in parts["final"]],
                final_question_candidate_ids=dict(questions))
