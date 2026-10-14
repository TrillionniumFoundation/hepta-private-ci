"""Real TRAIN-only, budget-matched HNMF MemoryCell type specialization (SHADOW).

Preassigned functional types are metadata, never inferred from held-out labels.
Both typed and unspecialized arms train two physical Heads with equal starting
weights, parameters, optimizer calls, minibatch counts, and routed forward calls.
No native Encoder invocation, memory writer, model Selector or authority exists.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite

import torch

from experiments.shared_stem_cell.execution import Head, fit, measured, parameters
from amcn_core import digest, is_sha, require, shadow_disposition
from amcn_learning import FeatureMatrix

KINDS = frozenset({"sensory", "episodic", "semantic", "procedural",
                   "predictive", "salience", "meta_memory"})
ARMS = ("frozen", "single_shared", "untyped_equal_budget",
        "typed_equal_budget", "typed_swapped_negative")
HELDOUT = ("select", "future_a", "future_b", "retention")
PROFILE = "hepta.amcn.typed-equal-budget.shadow.v1"


def type_inventory_digest(matrix, type_by_row):
    """Exact case-to-type precommit payload; hash alone is not a signature."""
    require(isinstance(matrix, FeatureMatrix), "frozen feature matrix required")
    require(isinstance(type_by_row, dict)
            and set(type_by_row) == {r.row_id for r in matrix.rows},
            "missing/foreign typed case")
    require(all(type(v) is str and v in KINDS for v in type_by_row.values()),
            "unknown functional memory type")
    return digest({"profile": PROFILE, "features": matrix.identity,
                   "types": [(r.row_id, type_by_row[r.row_id]) for r in matrix.rows]})


def train_typed_budget(matrix, train_labels, type_by_row, *,
                       expected_type_digest, kind="gated", steps=24,
                       batch=2, seed=17, train_sampling="uniform"):
    """Return physically learned Heads plus label-blind sealed predictions.

    The fixed metadata route invokes exactly ONE Head in each two-Head arm,
    even for the unspecialized control. TRAIN labels never include SELECT,
    FUTURE_A, FUTURE_B or RETENTION values. All rows remain in the census.
    """
    require(type(steps) is int and 1 <= steps <= 256 and
            type(batch) is int and 1 <= batch <= 16 and
            type(seed) is int and 0 <= seed <= 2**31 - 1, "training work/seed bound")
    require(kind in ("linear", "gated", "low_rank"), "unknown Head architecture")
    require(train_sampling in ("uniform", "balanced_binary"),
            "unregistered TRAIN sampler")
    require(is_sha(expected_type_digest)
            and expected_type_digest == type_inventory_digest(matrix, type_by_row),
            "typed route not bound to external type inventory")
    kinds = sorted(set(type_by_row.values()))
    require(len(kinds) == 2, "pilot must compare exactly two functional memory types")
    indices, train_y = matrix.train_labels(train_labels)
    require(len(indices) >= 2 * batch, "training set too small")
    groups = {k: [i for i in indices if type_by_row[matrix.rows[i].row_id] == k]
              for k in kinds}
    for group in groups.values():
        require(len(group) >= batch and
                len({matrix.rows[i].source_root for i in group}) >= 2 and
                {train_labels[matrix.rows[i].row_id] for i in group} == {0, 1},
                "each type requires balanced relevance labels and independent roots")
    # Functional types describe QUERY/learning tasks, not exclusive custody
    # of a source. A single admitted source may support temporal and semantic
    # TRAIN tasks. FeatureMatrix independently prevents source/family reuse
    # across SELECT/FUTURE_A/FUTURE_B. Head lineage must track the union of
    # original witnesses for each independently trained type.
    for split in ("future_a", "future_b"):
        require({type_by_row[r.row_id] for r in matrix.rows if r.split == split}
                == set(kinds), "missing type or future diagnostic partition")
    require(matrix.backend_profile in ("mechanics_fixture",
            "local_hf_snapshot_checked_unreviewed"), "unqualified feature origin")
    require(matrix.x.shape[1] <= 8192, "feature width")

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        frozen = Head(matrix.x.shape[1], 2, kind=kind,
                      rank=min(8, matrix.x.shape[1])).eval()
    before = parameters(frozen)
    learned = {}
    meters = {}
    pool = {}

    def training_positions(selected):
        if train_sampling == "uniform":
            return selected
        pos = [j for j in selected if train_labels[matrix.rows[j].row_id] == 1]
        neg = [j for j in selected if train_labels[matrix.rows[j].row_id] == 0]
        require(pos and neg, "class-balanced sampler requires both TRAIN classes")
        width = max(len(pos), len(neg))
        # Only TRAIN ids are repeated; never bring in heldout support labels.
        # Both arms retain identical sampled minibatch counts and update steps.
        return ([pos[j % len(pos)] for j in range(width)]
                + [neg[j % len(neg)] for j in range(width)])

    with measured() as wall:
        for arm in ("untyped_equal_budget", "typed_equal_budget"):
            heads, receipts = {}, {}
            for i, k in enumerate(kinds):
                selected = indices if arm == "untyped_equal_budget" else groups[k]
                sampled = training_positions(selected)
                y = torch.tensor([train_labels[matrix.rows[j].row_id] for j in sampled],
                                 dtype=torch.long)
                trained, receipt = fit(deepcopy(frozen), matrix.x[sampled], y,
                                       steps=steps, batch=batch, seed=seed + i)
                require(parameters(trained)["sha256"] != before["sha256"],
                        "Head did not learn")
                heads[k] = trained
                receipts[k] = receipt
                pool[arm + "/" + k] = {
                    "unique_train_rows": len(selected),
                    "train_positive": sum(train_labels[matrix.rows[j].row_id] for j in selected),
                    "train_negative": len(selected) - sum(train_labels[matrix.rows[j].row_id] for j in selected),
                    "sampler_pool_rows_including_repetitions": len(sampled)}
            learned[arm], meters[arm] = heads, receipts
        single_positions = training_positions(indices)
        y_all = torch.tensor([train_labels[matrix.rows[j].row_id] for j in single_positions],
                             dtype=torch.long)
        single, single_cost = fit(deepcopy(frozen), matrix.x[single_positions], y_all,
                                  steps=steps, batch=batch, seed=seed)
    require(parameters(frozen) == before, "frozen parameter control mutated")

    def budget(arm):
        items = list(meters[arm].values())
        return {"parameters": sum(x["parameters"] for x in items),
                "parameter_bytes": sum(x["parameter_bytes"] for x in items),
                "optimizer_steps": sum(x["steps"] for x in items),
                "examples_processed": sum(x["examples_processed"] for x in items),
                "head_sha256": {k: parameters(learned[arm][k])["sha256"]
                                for k in kinds}}

    control_budget, typed_budget = budget("untyped_equal_budget"), budget("typed_equal_budget")
    for metric in ("parameters", "parameter_bytes", "optimizer_steps", "examples_processed"):
        require(control_budget[metric] == typed_budget[metric], "unequal training budget")
    require(control_budget["parameters"] == 2 * before["parameters"],
            "two-Head size contract")

    predictions = []
    counts = {arm: 0 for arm in ARMS}
    with torch.no_grad():
        for j, row in enumerate(matrix.rows):
            if row.split not in HELDOUT:
                continue
            k = type_by_row[row.row_id]
            other = kinds[1 - kinds.index(k)]
            x = matrix.x[j:j + 1]
            models = {"frozen": frozen, "single_shared": single,
                      "untyped_equal_budget": learned["untyped_equal_budget"][k],
                      "typed_equal_budget": learned["typed_equal_budget"][k],
                      "typed_swapped_negative": learned["typed_equal_budget"][other]}
            probabilities = {}
            for arm, model in models.items():
                p = float(model(x).softmax(-1)[0, 1].item())
                require(isfinite(p) and 0 <= p <= 1, "invalid physical probability")
                probabilities[arm] = p
                counts[arm] += 1
            predictions.append({"row_id": row.row_id, "family": row.family,
                                "split": row.split, "input_sha256": row.input_sha256,
                                "memory_type": k, "probabilities": probabilities})
    require(predictions and len({r["row_id"] for r in predictions}) == len(predictions),
            "missing or duplicated prediction")
    require(len(set(counts.values())) == 1, "unpaired physical inference calls")
    receipt = shadow_disposition(
        profile=PROFILE, frozen_feature_sha256=matrix.identity,
        encoder_sha256=matrix.encoder_sha256,
        encoder_execution_receipt=matrix.encoder_execution_receipt,
        backend_profile=matrix.backend_profile, functional_types=kinds,
        precommitted_type_inventory_sha256=expected_type_digest,
        externally_authenticated_type_precommit=False,
        baseline_head=before, single_head=parameters(single),
        single_head_work=single_cost, untyped_budget=control_budget,
        typed_budget=typed_budget, training_sampling=train_sampling,
        training_pool_receipt=pool,
        physical_inference_calls=counts,
        training_wall=wall, prediction_sha256=digest(predictions),
        actual_model_update=True, future_labels_opened_during_training=False,
        independent_future_time_verified=False, independent_reader_results=None,
        strong_hybrid_rag_comparison=None, physical_source_bytes=None,
        measured_end_to_end_compression_ratio=None)
    return {"predictions": predictions, "receipt": receipt,
            "trained_heads": learned, "single_head": single, "frozen_head": frozen}
