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


def seal_detached_typed_bank(trial, matrix, type_by_row, destination, *,
                             source_binding_sha256):
    """Persist genuinely trained detached 2+2 Head tensors; no Artifact Selection.

    The caller must provide a Source owner-bound witness digest separately.
    This exact byte seal is a research integrity primitive, not issuer trust,
    credential authority, source deletion, parameter unlearning or deployment.
    """
    import os
    from pathlib import Path
    from hashlib import sha256
    from safetensors.torch import save as safe_save
    require(isinstance(matrix, FeatureMatrix) and
            is_sha(source_binding_sha256), "externally pinned source binding required")
    require(isinstance(trial, dict) and set(trial) ==
            {"predictions", "receipt", "trained_heads", "single_head", "frozen_head"},
            "complete fitted typed Head bank required")
    metrics = trial["receipt"]["metrics"]
    require(trial["receipt"].get("production_accepted") is False
            and metrics["frozen_feature_sha256"] == matrix.identity
            and metrics["precommitted_type_inventory_sha256"] ==
            type_inventory_digest(matrix, type_by_row), "fitted trial identity drift")
    types = sorted(set(type_by_row.values()))
    require(len(types) == 2 and metrics["functional_types"] == types,
            "invalid frozen functional type inventory")
    models = {"frozen": trial["frozen_head"], "single_shared": trial["single_head"]}
    for arm in ("typed_equal_budget", "untyped_equal_budget"):
        require(set(trial["trained_heads"][arm]) == set(types),
                "incomplete typed/unsplit physical Head bank")
        for kind in types:
            models[arm + "__" + kind] = trial["trained_heads"][arm][kind]
    require(all(isinstance(model, Head) and model.kind == "gated"
                for model in models.values()), "safetensors-v1 only seals gated Heads")
    output = Path(destination)
    require(not output.exists() and not output.is_symlink(), "create-only Head bank")
    output.mkdir(parents=True, mode=0o700)
    entries = {}
    for key, model in sorted(models.items()):
        state = {k: v.detach().cpu().contiguous()
                 for k, v in model.state_dict().items()}
        require(state and all(v.dtype == torch.float32 and
                bool(torch.isfinite(v).all()) for v in state.values()),
                "FP32 finite Head parameters required")
        payload = safe_save(state)
        filename = key + ".safetensors"
        with (output / filename).open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        entries[key] = {"file": filename, "sha256": sha256(payload).hexdigest(),
                        "bytes": len(payload), "parameters": parameters(model)}
    manifest = {"schema": "hepta.amcn.typed-bank.safetensors.shadow.v1",
                "feature_sha256": matrix.identity,
                "source_binding_sha256": source_binding_sha256,
                "type_inventory_sha256": type_inventory_digest(matrix, type_by_row),
                "stem_sha256": matrix.encoder_sha256,
                "feature_width": matrix.x.shape[1],
                "head_kind": "gated",
                "types": types, "entries": entries,
                "trained_sampling": metrics["training_sampling"],
                "production_accepted": False}
    require(len(entries) == 6, "exactly six persisted Heads required")
    raw = canonical_bank_json(manifest)
    with (output / "manifest.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(str(output), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"manifest_sha256": sha256(raw).hexdigest(),
            "manifest": manifest, "physical_models_saved": len(entries),
            "candidate_only": True, "production_accepted": False}


def canonical_bank_json(payload):
    import json
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def reload_pinned_typed_bank(directory, *, expected_manifest_sha256,
                             expected_feature_sha256, expected_source_binding_sha256):
    """Physical safetensors readback of each original Head; never infer grants."""
    from pathlib import Path
    from hashlib import sha256
    import json
    from safetensors.torch import load as safe_load
    require(all(is_sha(x) for x in (expected_manifest_sha256,
            expected_feature_sha256, expected_source_binding_sha256)),
            "missing external exact readback pins")
    base = Path(directory)
    require(base.is_dir() and not base.is_symlink(), "unsafe Head bank directory")
    manifest_file = base / "manifest.json"
    require(manifest_file.is_file() and not manifest_file.is_symlink() and
            0 < manifest_file.stat().st_size <= 65536, "missing bank manifest")
    manifest_raw = manifest_file.read_bytes()
    require(sha256(manifest_raw).hexdigest() == expected_manifest_sha256,
            "original Head bank manifest changed")
    manifest = json.loads(manifest_raw)
    require(manifest.get("schema") == "hepta.amcn.typed-bank.safetensors.shadow.v1"
            and manifest.get("production_accepted") is False
            and manifest.get("feature_sha256") == expected_feature_sha256
            and manifest.get("source_binding_sha256") == expected_source_binding_sha256
            and manifest.get("head_kind") == "gated", "incompatible pinned bank")
    types, entries, width = manifest.get("types"), manifest.get("entries"), manifest.get("feature_width")
    require(isinstance(types, list) and len(types) == 2 and
            types == sorted(set(types)) and all(x in KINDS for x in types) and
            type(width) is int and 1 <= width <= 8192,
            "invalid geometry/types")
    needed = {"frozen", "single_shared"} | {
        arm + "__" + kind for arm in ("typed_equal_budget", "untyped_equal_budget")
        for kind in types}
    require(isinstance(entries, dict) and set(entries) == needed,
            "head inventory missing or excessive")
    models = {}
    for key in sorted(needed):
        item = entries[key]
        require(isinstance(item, dict) and set(item) ==
                {"file", "sha256", "bytes", "parameters"} and
                item["file"] == key + ".safetensors" and is_sha(item["sha256"])
                and type(item["bytes"]) is int and 0 < item["bytes"] <= 2 * 1024 * 1024,
                "unbounded or misleading original tensor manifest")
        path = base / item["file"]
        require(path.is_file() and not path.is_symlink()
                and path.stat().st_size == item["bytes"], "unsafe physical Head")
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == item["sha256"], "tampered Head bytes")
        physical = safe_load(raw)
        model = Head(width, 2, kind="gated", rank=min(8, width)).eval()
        reference = model.state_dict()
        require(set(physical) == set(reference)
                and all(physical[k].shape == reference[k].shape and
                        physical[k].dtype == torch.float32 and
                        bool(torch.isfinite(physical[k]).all()) for k in physical),
                "malformed Head tensor layout")
        model.load_state_dict(physical, strict=True)
        require(parameters(model) == item["parameters"], "trained numeric parameter drift")
        models[key] = model.eval()
    return {"models": models, "manifest": manifest,
            "physical_head_bytes_verified": True, "production_accepted": False}
