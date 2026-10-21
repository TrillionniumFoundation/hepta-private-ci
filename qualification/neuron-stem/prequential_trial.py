#!/usr/bin/env python3
"""Shadow-only test-then-learn continual Cell trial with one frozen shared Stem.

Future labels are revealed to the learner only after a prediction is
materialized. Cell-local Heads have isolated optimizers, a distinct frozen
same-initialization control, and explicitly measured update costs. This is
an offline chronological replay, not live NDU, production learning or proof
of long-term efficacy.
"""
import argparse
from collections import OrderedDict, defaultdict
import copy
import hashlib
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time

from hf_trial import make_head
from jina_v5 import FrozenJinaV5, research_environment, sha256_record
from jina_v5_trial import effective_weights_digest, render_case
from q24_bridge import Q24, quantize_q24
from qualified_eval import audit_dataset, read_jsonl, write_json


class BoundedFeatureCache:
    """Per-run, byte-accounted LRU of immutable frozen Stem feature vectors.

    This bounds only retained per-case tensors, not PyTorch allocator, model
    weights, tokenizer or producer-internal caches. An oversized single vector
    fails closed instead of silently creating a resource-unbounded trial.
    """

    def __init__(self, max_bytes):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("invalid frozen Feature cache byte ceiling")
        self.max_bytes = max_bytes
        self.entries = OrderedDict()
        self.resident_bytes = 0
        self.peak_resident_bytes = 0
        self.evictions = 0
        self.hits = 0
        self.misses = 0

    def get_or_build(self, key, build):
        if key in self.entries:
            self.hits += 1
            self.entries.move_to_end(key)
            return self.entries[key][0]
        self.misses += 1
        value = build()
        elements = value.numel()
        element_size = value.element_size()
        if (type(elements) is not int or type(element_size) is not int or
                elements <= 0 or element_size <= 0 or
                elements * element_size > self.max_bytes):
            raise ValueError("one Stem feature exceeds frozen cache budget")
        retained = elements * element_size
        while self.resident_bytes + retained > self.max_bytes:
            _, (_, evicted_bytes) = self.entries.popitem(last=False)
            self.resident_bytes -= evicted_bytes
            self.evictions += 1
        self.entries[key] = (value, retained)
        self.resident_bytes += retained
        self.peak_resident_bytes = max(self.peak_resident_bytes, self.resident_bytes)
        return value


def iso_time(row):
    try:
        t = datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise ValueError("naive event timestamp")
        return t.astimezone(timezone.utc)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("time must contain an explicit UTC-resolvable offset") from exc


def prepare_chronology(dataset, task_id):
    source_audit = audit_dataset(dataset)
    task_rows = [row for row in dataset if row["task_id"] == task_id]
    if not task_rows:
        raise ValueError("no task matching the required ID")
    if not all(any(row["split"] == split for row in task_rows)
               for split in ("train", "calibration", "test", "future", "ood")):
        raise ValueError("selected task requires all five partitions")
    cells = {}
    seen_inputs = set()
    for row in task_rows:
        ident = row.get("cell_id")
        if not isinstance(ident, str) or not ident:
            raise ValueError("cell_id must be an explicit nonempty string")
        key = (row["scope_id"], ident)
        if key in cells and cells[key] != task_id:
            raise ValueError("Cell identity changed task")
        cells[key] = task_id
        if row["split"] == "future":
            fingerprint = sha256_record([row["scope_id"], ident, row["state"],
                                          row["question"], row["options"]])
            if fingerprint in seen_inputs:
                raise ValueError("duplicate future Cell input")
            seen_inputs.add(fingerprint)
    widths = {len(row["options"]) for row in task_rows}
    if len(widths) != 1:
        raise ValueError("task option count inconsistent")
    future = sorted((row for row in task_rows if row["split"] == "future"),
                    key=lambda row: (iso_time(row), row["case_id"]))
    if not future or max(iso_time(row) for row in task_rows if row["split"] != "future") >= iso_time(future[0]):
        # OOD may be deliberately sampled after future; only train/calibration/
        # test must precede future, as enforced by audit_dataset.
        earlier = [row for row in task_rows
                   if row["split"] in ("train", "calibration", "test")]
        if max(iso_time(row) for row in earlier) >= iso_time(future[0]):
            raise ValueError("future overlaps earlier observed evaluation windows")
    return task_rows, future, sorted(cells), widths.pop(), source_audit


def accuracy_brier(outcomes):
    if not outcomes:
        return None
    return {
        "events": len(outcomes),
        "accuracy": sum(x["correct"] for x in outcomes) / len(outcomes),
        "multiclass_brier": sum(x["brier"] for x in outcomes) / len(outcomes),
    }


def score_prediction(probs, truth):
    if not isinstance(probs, (list, tuple)) or not 0 <= truth < len(probs):
        raise ValueError("malformed prediction/label")
    if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probs):
        raise ValueError("invalid predicted probability")
    if abs(sum(probs) - 1.0) > 1e-5:
        raise ValueError("invalid distribution mass")
    return {
        "correct": int(max(range(len(probs)), key=probs.__getitem__) == truth),
        "brier": sum((p - float(j == truth)) ** 2 for j, p in enumerate(probs)) / len(probs),
    }


def prediction_precommit(row, probabilities, head_digest, event_order):
    """Deterministic label-free prediction journal record, before learning."""
    if type(event_order) is not int or event_order < 0:
        raise ValueError("invalid logical event order")
    if not isinstance(head_digest, str) or len(head_digest) != 64:
        raise ValueError("missing trained Head identity")
    if not isinstance(probabilities, list) or len(probabilities) < 2:
        raise ValueError("invalid pre-label probabilities")
    if any(type(p) not in (int, float) or not math.isfinite(p) or p < 0 or p > 1
           for p in probabilities) or abs(sum(probabilities) - 1.0) > 1e-5:
        raise ValueError("pre-label probability normalization invalid")
    return {
        "schema": "hepta.jina-v5-prequential-prediction-precommit.v1",
        "case_id": row["case_id"], "cell_id": row["cell_id"],
        "scope_id": row["scope_id"], "event_time": row["event_time"],
        "event_order": event_order,
        "input_digest": sha256_record([row["state"], row["question"], row["options"]]),
        "head_digest": head_digest,
        "probabilities": probabilities,
        "outcome_included": False,
        "production_promotion_permitted": False,
    }


def model_only_ood_receipt(row, arm, probabilities, *, model, revision,
                           weights_digest, generation, feature_manifest_digest):
    """Label-free model output, deliberately without production no-change."""
    if arm not in ("frozen", "trained") or row.get("split") not in ("calibration", "ood"):
        raise ValueError("only learned/frozen calibration and OOD model records allowed")
    if (not isinstance(revision, str) or len(revision) != 40 or
            any(c not in "0123456789abcdef" for c in revision) or
            not isinstance(weights_digest, str) or len(weights_digest) != 64 or
            any(c not in "0123456789abcdef" for c in weights_digest) or
            type(generation) is not int or generation <= 0 or
            not isinstance(feature_manifest_digest, str) or
            len(feature_manifest_digest) != 64 or
            any(c not in "0123456789abcdef" for c in feature_manifest_digest)):
        raise ValueError("OOD model snapshot revision/generation/Encoder manifest not pinned")
    if (not isinstance(probabilities, list) or
            len(probabilities) != len(row["options"]) or
            any(type(p) not in (float, int) or not math.isfinite(p) or p < 0 or p > 1
                for p in probabilities) or abs(sum(probabilities) - 1.0) > 1e-5):
        raise ValueError("OOD model predictions must be finite and normalized")
    return {
        "case_id": row["case_id"], "arm": arm,
        "scope_id": row["scope_id"], "cell_id": row["cell_id"],
        "split": row["split"], "event_time": row["event_time"],
        "input_digest": sha256_record([row["state"], row["question"], row["options"]]),
        "probabilities": probabilities,
        "model_id": model, "model_revision": revision,
        "weights_digest": weights_digest, "generation": generation,
        "feature_manifest_digest": feature_manifest_digest,
        "status": "Succeeded", "production_promotion_permitted": False,
    }


def trial(args):
    import psutil
    import torch
    from torch import nn

    if args.model not in ("jina-v5-text-nano", "jina-v5-text-small"):
        raise ValueError("prequential trial is text-only; Omni requires a separate qualified trainer")
    if type(args.generation) is not int or args.generation <= 0:
        raise ValueError("Stem/Cell generation must be a positive integer")
    if not 1 <= args.max_cells <= 4096 or args.pretrain_steps < 0 or args.update_steps < 0:
        raise ValueError("training parameters outside finite bounded profile")
    if not all(math.isfinite(v) and v > 0
               for v in (args.learning_rate, args.max_grad_norm)):
        raise ValueError("learning rates/gradient limits must be positive")
    if not 0 <= args.max_retention_brier_regression <= 1:
        raise ValueError("invalid retention regression tolerance")
    if not all(type(v) is int and v > 0 for v in
               (args.max_total_head_parameters, args.max_dataset_cases,
                args.max_future_events, args.threads)):
        raise ValueError("event/parameter/thread bounds must be positive")
    feature_cache_bytes = getattr(args, "max_feature_cache_bytes", 64 * 1024 * 1024)
    if (type(feature_cache_bytes) is not int or
            not 4 * 1024 <= feature_cache_bytes <= 512 * 1024 * 1024 or
            args.dimension * 4 > feature_cache_bytes):
        raise ValueError("unregistered or undersized frozen Feature cache byte budget")
    rows = read_jsonl(args.dataset)
    if len(rows) > args.max_dataset_cases:
        raise ValueError("dataset exceeds precommitted bounded event envelope")
    task_rows, future, keys, classes, audit = prepare_chronology(rows, args.task_id)
    if args.emit_ood_model_receipts:
        oo = [row for row in task_rows if row["split"] == "ood"]
        if not oo or min(iso_time(row) for row in oo) <= max(
                iso_time(row) for row in future):
            raise ValueError("OOD model traces require post-future chronological events")
    if len(future) > args.max_future_events:
        raise ValueError("future replay exceeds bounded event envelope")
    if len(keys) > args.max_cells:
        raise ValueError("dataset would instantiate more than approved Cell limit")
    _, dry_run_parameters = make_head(torch, nn, args.head, args.dimension,
                                      classes, args.budget)
    if dry_run_parameters * len(keys) > args.max_total_head_parameters:
        raise ValueError("total Cell Head weight/optimizer budget exceeded")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest = Path(str(args.output) + ".manifest.json")
    prediction_journal_path = Path(str(args.output) + ".prediction-journal.jsonl")
    ood_model_path = Path(str(args.output) + ".ood-model-receipts.jsonl")
    destinations = [args.output, manifest, prediction_journal_path]
    if args.emit_ood_model_receipts:
        destinations.append(ood_model_path)
    if any(p.exists() for p in destinations):
        raise ValueError("refusing to overwrite frozen evidence")
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    stem = FrozenJinaV5(
        args.model, args.revision, task="classification", dimension=args.dimension,
        modality="text", max_tokens=args.max_tokens, device=args.device,
        cache_entries=args.cache_entries, allow_download=args.allow_model_download,
        allow_pinned_remote_code=args.allow_pinned_remote_code,
        snapshot_dir=args.snapshot, store_root=args.store_root,
        expected_snapshot_digest=args.expected_snapshot_digest,
    )
    feature_cache = BoundedFeatureCache(feature_cache_bytes)

    def feature(row):
        # Include immutable input content and Scope/Cell identity. A reused
        # case_id with changed options must never return a stale feature.
        key = (row["case_id"], row["scope_id"], row["cell_id"],
               sha256_record([row["state"], row["question"], row["options"]]))

        def encode():
            v, _ = stem.encode_batch(
                [render_case(row, "joint")], scope_id=row["scope_id"],
                principal_id=args.principal_id, generation=args.generation,
                authority_epoch=args.authority_epoch, intent="document",
            )
            return torch.tensor(
                [x / Q24 for x in quantize_q24(v[0])],
                dtype=torch.float32, device=args.device)

        return feature_cache.get_or_build(key, encode)

    cell_heads, control_heads, optimizers, parameter_total = {}, {}, {}, 0
    for index, key in enumerate(keys):
        torch.manual_seed(args.seed + index)
        head, params = make_head(
            torch, nn, args.head, args.dimension, classes, args.budget)
        head = head.to(args.device)
        if params > args.budget:
            raise ValueError("Cell exceeded actual head parameter ceiling")
        optimizers[key] = torch.optim.AdamW(head.parameters(), lr=args.learning_rate)
        cell_heads[key] = head
        parameter_total += params

    # Only historical train labels are used during the initial training phase.
    train_rows = sorted((row for row in task_rows if row["split"] == "train"),
                        key=lambda row: (iso_time(row), row["case_id"]))
    start_train = time.perf_counter_ns()
    for row in train_rows:
        key = (row["scope_id"], row["cell_id"])
        head, opt = cell_heads[key], optimizers[key]
        head.train()
        for _ in range(args.pretrain_steps):
            logits = head(feature(row))
            loss = nn.functional.cross_entropy(
                logits.unsqueeze(0), torch.tensor([row["label"]], device=args.device))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), args.max_grad_norm)
            opt.step()
            if not all(torch.isfinite(p).all().item() for p in head.parameters()):
                raise ValueError("nonfinite local Cell weights after pretraining")
    train_ms = (time.perf_counter_ns() - start_train) / 1e6
    for key, head in cell_heads.items():
        control_heads[key] = copy.deepcopy(head).eval()
        head.eval()

    held_out_rows = [row for row in task_rows if row["split"] == "test"]
    def retention_by_cell():
        measures = defaultdict(list)
        for old in held_out_rows:
            cell_key = (old["scope_id"], old["cell_id"])
            with torch.inference_mode():
                p = torch.softmax(cell_heads[cell_key](feature(old)),
                                  dim=-1).cpu().tolist()
            measures[str(cell_key)].append(score_prediction(p, old["label"]))
        return {key: accuracy_brier(observations)
                for key, observations in sorted(measures.items())}

    retention_before = retention_by_cell()
    initial_digests = {
        str(key): effective_weights_digest(cell_heads[key]) for key in keys}

    # Capture historical calibration BEFORE any future label-driven update.
    # Two Head arms are recorded; the genuine production no-change baseline
    # MUST be supplied independently and is never fabricated here.
    ood_partials = []
    if args.emit_ood_model_receipts:
        for row in sorted((r for r in task_rows if r["split"] == "calibration"),
                          key=lambda r: (iso_time(r), r["case_id"])):
            key = (row["scope_id"], row["cell_id"])
            with torch.inference_mode():
                frozen_p = torch.softmax(control_heads[key](feature(row)),
                                         dim=-1).cpu().tolist()
                initial_p = torch.softmax(cell_heads[key](feature(row)),
                                          dim=-1).cpu().tolist()
            if any(abs(x - y) > 1e-6 for x, y in zip(frozen_p, initial_p)):
                raise ValueError("learned/frozen calibration heads differ before future learning")
            for arm, prob in (("frozen", frozen_p), ("trained", initial_p)):
                ood_partials.append(model_only_ood_receipt(
                    row, arm, prob, model=args.model, revision=args.revision,
                    weights_digest=initial_digests[str(key)], generation=args.generation,
                    feature_manifest_digest=stem.manifest_digest))

    outcomes, frozen_outcomes, records = [], [], []
    update_ms = 0.
    process = psutil.Process()
    journal_hash = hashlib.sha256()
    # Exclusive create: a restart must never quietly append to an old
    # incomplete run or claim that two generations are the same journal.
    prediction_journal_path.open("x", encoding="utf-8").close()
    for index, row in enumerate(future):
        key = (row["scope_id"], row["cell_id"])
        head, frozen, optimizer = cell_heads[key], control_heads[key], optimizers[key]
        observed = feature(row)
        with torch.inference_mode():
            learned_prob = torch.softmax(head(observed), dim=-1).cpu().tolist()
            frozen_prob = torch.softmax(frozen(observed), dim=-1).cpu().tolist()
        # Prediction evidence is calculated BEFORE any access to this event's
        # label is used for an update. The label is only read below this fence.
        before_digest = effective_weights_digest(head)
        frozen_digest = effective_weights_digest(frozen)
        if frozen_digest != initial_digests[str(key)]:
            raise ValueError("frozen same-initialization Head mutated during future replay")
        precommit = prediction_precommit(row, learned_prob, before_digest, index)
        # Seal both controls BEFORE future labels are revealed. A prediction
        # alone cannot prove that a frozen control kept its actual weights.
        precommit["frozen_control_head_digest"] = frozen_digest
        precommit["frozen_control_probabilities"] = frozen_prob
        precommit["record_digest"] = sha256_record(precommit)
        line = (json.dumps(precommit, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")) + "\n").encode("utf-8")
        # Durable write-ahead boundary before revealing a training label.
        # The journal is advisory/unsigned; fsync does not authenticate input.
        with prediction_journal_path.open("ab") as journal:
            journal.write(line)
            journal.flush()
            os.fsync(journal.fileno())
        journal_hash.update(line)
        sealed = precommit["record_digest"]
        # Offline replay owns outcome labels; a real stream must obtain an
        # authenticated outcome from a separate result/evaluation owner.
        truth = row["label"]
        outcomes.append(score_prediction(learned_prob, truth))
        frozen_outcomes.append(score_prediction(frozen_prob, truth))
        began_update = time.perf_counter_ns()
        head.train()
        for _ in range(args.update_steps):
            logits = head(observed)
            loss = nn.functional.cross_entropy(
                logits.unsqueeze(0), torch.tensor([truth], device=args.device))
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), args.max_grad_norm)
            optimizer.step()
            if not all(torch.isfinite(p).all().item() for p in head.parameters()):
                raise ValueError("nonfinite local Cell weights after update")
        head.eval()
        duration = (time.perf_counter_ns() - began_update) / 1e6
        update_ms += duration
        after_digest = effective_weights_digest(head)
        records.append({
            "event_order": index, "event_time": row["event_time"],
            "case_id": row["case_id"], "scope_id": row["scope_id"],
            "cell_id": row["cell_id"],
            "prediction_seal_before_label_update": sealed,
            "preupdate_head_digest": before_digest,
            "postupdate_head_digest": after_digest,
            "frozen_control_head_digest": frozen_digest,
            "trained_probabilities": learned_prob,
            "frozen_same_initialization_probabilities": frozen_prob,
            "outcome_label_revealed_after_prediction": True,
            "local_update_steps_after_prediction": args.update_steps,
            "local_update_wall_ms": duration,
            "rss_bytes": process.memory_info().rss,
        })
    # No train/test labels may be used after the future window starts to
    # update weights, and controls remain at their post-pretrain parameters.
    final_digests = {
        str(key): effective_weights_digest(cell_heads[key]) for key in keys}
    frozen_final_digests = {
        str(key): effective_weights_digest(control_heads[key]) for key in keys}
    if frozen_final_digests != initial_digests:
        raise ValueError("frozen historical-control Head tensor changed during future events")
    if args.emit_ood_model_receipts:
        ood_rows = sorted((row for row in task_rows if row["split"] == "ood"),
                          key=lambda row: (iso_time(row), row["case_id"]))
        if not ood_rows or min(iso_time(row) for row in ood_rows) <= max(
                iso_time(row) for row in future):
            raise ValueError("OOD model traces require post-future chronological events")
        for row in ood_rows:
            key = (row["scope_id"], row["cell_id"])
            with torch.inference_mode():
                learned_p = torch.softmax(cell_heads[key](feature(row)),
                                          dim=-1).cpu().tolist()
                frozen_p = torch.softmax(control_heads[key](feature(row)),
                                         dim=-1).cpu().tolist()
            for arm, prob, digest in (
                    ("frozen", frozen_p, frozen_final_digests[str(key)]),
                    ("trained", learned_p, final_digests[str(key)])):
                ood_partials.append(model_only_ood_receipt(
                    row, arm, prob, model=args.model, revision=args.revision,
                    weights_digest=digest, generation=args.generation,
                    feature_manifest_digest=stem.manifest_digest))
        raw_ood = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False, separators=(",", ":")) + "\n"
                          for row in ood_partials).encode("utf-8")
        with ood_model_path.open("xb") as stream:
            stream.write(raw_ood)
            stream.flush()
            os.fsync(stream.fileno())
        ood_model_sha256 = hashlib.sha256(raw_ood).hexdigest()
    else:
        ood_model_sha256 = None
    retention_after = retention_by_cell()
    retention_regressions = {
        key: retention_after[key]["multiclass_brier"]
             - retention_before[key]["multiclass_brier"]
        for key in retention_before
        if retention_after[key]["multiclass_brier"]
           - retention_before[key]["multiclass_brier"]
           > args.max_retention_brier_regression
    }
    result = {
        "schema": "hepta.jina-v5-cell-prequential-shadow.v1",
        "status": "offline_test_then_learn_descriptive_not_production_evidence",
        "production_promotion_permitted": False,
        "independent_ndu_signature_verified": False,
        "genuine_future_outcomes_authenticated": False,
        "model": args.model, "revision": args.revision,
        "generation": args.generation,
        "feature_manifest_digest": stem.manifest_digest,
        "local_snapshot_census_sha256": stem.snapshot_attestation["manifest_sha256"],
        "local_snapshot_attested_twice": stem.snapshot_attestation["attested_twice_around_model_load"],
        "local_snapshot_attestation_ms": stem.snapshot_attestation_ms,
        "model_code_and_adapter_bytes_hashed": True,
        "dataset_audit": audit, "task_id": args.task_id,
        "principal_id": args.principal_id,
        "cells": len(keys), "head": args.head,
        "per_cell_head_parameters": parameter_total // len(keys),
        "total_cell_head_parameters": parameter_total,
        "seed": args.seed, "feature_dimension": args.dimension,
        "pretrain_steps_per_historical_event": args.pretrain_steps,
        "update_steps_per_future_event": args.update_steps,
        "max_dataset_cases": args.max_dataset_cases,
        "max_future_events": args.max_future_events,
        "max_total_head_parameters": args.max_total_head_parameters,
        "precommitted_max_per_cell_retention_brier_regression": args.max_retention_brier_regression,
        "future_event_count": len(future),
        "pre_label_prediction_journal": str(prediction_journal_path),
        "pre_label_prediction_journal_sha256": journal_hash.hexdigest(),
        "pre_label_prediction_journal_event_count": len(records),
        "pre_label_predictions_fsynced": True,
        "pretrain_wall_ms": train_ms, "future_update_wall_ms": update_ms,
        "initial_head_digests": initial_digests,
        "final_head_digests": final_digests,
        "frozen_final_head_digests": frozen_final_digests,
        "offline_ood_model_receipts_sha256": ood_model_sha256,
        "offline_ood_model_receipts_path": (
            str(ood_model_path) if args.emit_ood_model_receipts else None),
        "production_no_change_ood_receipts_present": False,
        "frozen_future_metrics": accuracy_brier(frozen_outcomes),
        "learned_future_metrics": accuracy_brier(outcomes),
        "held_out_test_retention_before": retention_before,
        "held_out_test_retention_after": retention_after,
        "per_cell_retention_regressions": retention_regressions,
        "no_retention_regression_above_precommitted_tolerance": not bool(retention_regressions),
        "observed_future_brier_gain_vs_frozen": (
            accuracy_brier(frozen_outcomes)["multiclass_brier"]
            - accuracy_brier(outcomes)["multiclass_brier"]
        ),
        "encoder_calls": stem.encoder_calls, "cache_hits": stem.cache_hits,
        "max_feature_cache_bytes": feature_cache.max_bytes,
        "feature_cache_peak_resident_bytes": feature_cache.peak_resident_bytes,
        "feature_cache_resident_bytes": feature_cache.resident_bytes,
        "feature_cache_retained_cases": len(feature_cache.entries),
        "feature_cache_evictions": feature_cache.evictions,
        "feature_cache_hits": feature_cache.hits,
        "feature_cache_misses": feature_cache.misses,
        "feature_cache_is_not_process_rss": True,
        "model_load_ms": stem.load_ms,
        "max_observed_rss_bytes": max(row["rss_bytes"] for row in records),
        "environment": research_environment(),
        "temporal_receipts": records,
        "limitations": [
            "Offline replay labels are not authenticated live outcomes",
            "This reports descriptive prequential effects, not causal NDU",
            "Observed label is never trained before its prediction seal",
            "Same Cell Head used for prediction and bounded local update, no selector promotion",
            "Not a Rust checked Q24 checkpoint/CAS/signed inference production receipt",
        ],
    }
    write_json(args.output, result)
    write_json(manifest, {
        "schema": "hepta.jina-v5-cell-prequential-run-manifest.v1",
        "trial_digest": sha256_record(result),
        "production_promotion_permitted": False,
        "source_model_revision": args.revision,
        "source_worker_generation": args.generation,
        "source_feature_manifest_digest": stem.manifest_digest,
        "dataset_digest": audit["dataset_digest"],
        "signed_evaluator_receipt": False,
        "prediction_journal_sha256": journal_hash.hexdigest(),
    })


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--principal-id", required=True)
    p.add_argument("--model", required=True,
                   choices=("jina-v5-text-nano", "jina-v5-text-small"))
    p.add_argument("--revision", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--head", choices=("linear", "film", "rank8", "rank16", "mlp", "swiglu"),
                   default="linear")
    p.add_argument("--dimension", type=int, default=256)
    p.add_argument("--budget", type=int, choices=(2048, 16384, 65536, 262144),
                   default=16384)
    p.add_argument("--pretrain-steps", type=int, default=4)
    p.add_argument("--update-steps", type=int, default=1)
    p.add_argument("--learning-rate", type=float, default=.0005)
    p.add_argument("--max-grad-norm", type=float, default=1.)
    p.add_argument("--max-cells", type=int, default=4096)
    p.add_argument("--max-total-head-parameters", type=int, default=100000000)
    p.add_argument("--max-dataset-cases", type=int, default=100000)
    p.add_argument("--max-future-events", type=int, default=50000)
    p.add_argument("--max-retention-brier-regression", type=float, default=.01)
    p.add_argument("--emit-ood-model-receipts", action="store_true",
                   help="Emit only real frozen/learned model traces; never invent no-change")
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--cache-entries", type=int, default=256)
    p.add_argument("--max-feature-cache-bytes", type=int, default=64 * 1024 * 1024,
                   help="hard cap on retained local Q24-decoded case features, not process RSS")
    p.add_argument("--device", default="cpu")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--seed", type=int, default=20261011)
    p.add_argument("--generation", type=int, default=1)
    p.add_argument("--authority-epoch", type=int, default=1)
    p.add_argument("--store-root", type=Path, required=True,
                   help="approved models--jinaai--REPO local cache root")
    p.add_argument("--snapshot", type=Path, required=True,
                   help="exact cache snapshots/FULL40SHA directory")
    p.add_argument("--expected-snapshot-digest", required=True,
                   help="separately reviewed 64-hex full local file-census digest")
    p.add_argument("--allow-pinned-remote-code", action="store_true")
    p.add_argument("--allow-model-download", action="store_true")
    trial(p.parse_args())


if __name__ == "__main__":
    main()
