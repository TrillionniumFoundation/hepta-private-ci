"""Physical CPU Top-1 research probe over an already trained P2 two-Head bank.

The existing P2 producer runs BOTH Heads before selecting a route. This
non-authorizing probe computes only the selected Head on each heldout row.
It never loads a Stem, trains, reads outcome labels, selects a model, or grants
a CellSplit/Final-use/Codex effect. Self-reported CPU timings are diagnostic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

import p2_real_cell_split as original
import p2_real_cell_split_review as numeric

SCHEMA = "hepta.p2.actual-selected-head-physical-shadow.v1"
ARMS = ("fixed_two_cell", "adaptive_train_only")
REPEATS = 13
Q24 = 1 << 24
MAX_INPUT_BYTES = 16 * 1024 * 1024


def require(ok, why):
    if not ok:
        raise ValueError(why)


def unique_pairs(pairs):
    data = {}
    for key, value in pairs:
        require(key not in data, "duplicate original JSON key")
        data[key] = value
    return data


def read_bounded(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                 getattr(os, "O_NONBLOCK", 0))
    try:
        st = os.fstat(fd)
        import stat
        require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= MAX_INPUT_BYTES,
                "expected a bounded regular original report")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        check = os.fstat(fd)
        require(len(raw) == st.st_size and
                (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) ==
                (check.st_dev, check.st_ino, check.st_size, check.st_mtime_ns),
                "original report mutated during reading")
    finally:
        os.close(fd)
    return json.loads(raw, object_pairs_hook=unique_pairs,
                      parse_constant=lambda c: (_ for _ in ()).throw(ValueError("invalid numeric constant")))


def materialize(record):
    require(type(record) is dict and record.get("schema") == original.SCHEMA
            and record.get("authority") == "DENY_ALL"
            and record.get("production_promotion_permitted") is False
            and record.get("selection_authorized") is False
            and record.get("report_sha256") ==
                numeric.digest({k:v for k,v in record.items() if k != "report_sha256"}),
            "untrusted mutable or authorizing parent report")
    cases = record.get("source_heldout_cases")
    features = record.get("source_features_q24")
    require(type(cases) is list and len(cases) == 96 and
            type(features) is dict and
            set(features) == {c["case_id"] for c in cases},
            "exact registered 96-row input coverage required")
    require(len({c["case_id"] for c in cases}) == 96 and
            all(type(c) is dict and set(c) == {
                "case_id", "group_id", "split", "joint_input_digest"}
                for c in cases), "unknown or duplicated original heldout case")
    require({c["split"] for c in cases} == {"test", "calibration"} and
            sum(c["split"] == "test" for c in cases) == 64 and
            sum(c["split"] == "calibration" for c in cases) == 32,
            "actual original heldout partitions required")
    rows = [features[c["case_id"]] for c in cases]
    require(all(type(row) is list and len(row) == 384 and
                all(type(q) is int and abs(q) <= 8 * Q24 for q in row)
                for row in rows), "exact bounded original Q24 payload required")
    cutoff = record.get("cutoff_feature0_train_median")
    require(type(cutoff) is float and math.isfinite(cutoff),
            "train-only cutoff not fixed")
    torch.set_num_threads(1)
    x = torch.tensor(rows, dtype=torch.float32) / Q24
    require(bool(torch.isfinite(x).all()), "nonfinite reconstructed heldout vectors")
    arms = record.get("compared_arms")
    require(type(arms) is dict and set(arms) == set(original.ARMS),
            "original P2 arm inventory altered")
    return x, float(cutoff)


def parameters_from_exact_fp32(arm):
    arrays = numeric.decode_weights(arm["weights"])
    h = hashlib.sha256()
    for name in sorted(arrays):
        h.update(name.encode("ascii") + b"\0" +
                 arrays[name].astype("<f4",copy=False).tobytes())
    require(h.hexdigest() == arm["final_weights_sha256"],
            "source trained tensor bytes no longer match saved digest")
    return {name: torch.tensor(array.copy(), dtype=torch.float32)
            for name,array in arrays.items()}


def selected_heads(x, arm, cutoff):
    if arm["arm"] == "adaptive_train_only" and arm["split_proposed"] is False:
        return torch.zeros((len(x),), dtype=torch.long)
    require(arm["arm"] in ARMS and arm["split_proposed"] is True,
            "only original fixed or train-only adaptive selection supported")
    return (x[:, 0] >= cutoff).to(dtype=torch.long)


def single_head(selected_x, weight, head):
    """Only the requested Head's tensors enter forward operators."""
    down = selected_x @ weight["down"][head]
    gate = torch.sigmoid(selected_x[:, :64] @ weight["gate"][head] +
                         weight["g_bias"][head])
    delta = (F.silu(down) * gate) @ weight["up"][head]
    return (selected_x + delta) @ weight["out"][head] + weight["out_bias"][head]


def sparse_selected_forward(x, choice, weight):
    require(choice.shape == (len(x),) and choice.dtype == torch.long and
            bool(((choice == 0) | (choice == 1)).all()), "invalid original Top-1 roster")
    logits = torch.empty((len(x), 2), dtype=torch.float32)
    groups = []
    executed_rows = 0
    with torch.no_grad():
        for head in (0, 1):
            indices = torch.nonzero(choice == head).flatten()
            groups.append(len(indices))
            if len(indices):
                slice_ = x.index_select(0, indices)
                # Never call the other Head on this slice.
                result = single_head(slice_, weight, head)
                logits.index_copy_(0, indices, result)
                executed_rows += len(indices)
    require(executed_rows == len(x) and sum(groups) == len(x),
            "each original heldout case must execute exactly one Head")
    return logits, groups


def paired_actual_cpu_ns(dense, sparse):
    """Alternate physical CPU runs to limit order bias; not service p99."""
    samples = {"dense":[], "sparse":[]}
    names = {"dense":dense, "sparse":sparse}
    with torch.no_grad():
        for _ in range(3):
            dense()
            sparse()
        for rep in range(REPEATS):
            order = ("dense", "sparse") if rep % 2 == 0 else ("sparse", "dense")
            for key in order:
                before = time.process_time_ns()
                output = names[key]()
                elapsed = max(1, time.process_time_ns() - before)
                require(bool(torch.isfinite(output).all()), "nonfinite physical Torch output")
                samples[key].append(elapsed)
    return samples["dense"], samples["sparse"]

def run(record):
    x, cutoff = materialize(record)
    result = {}
    for name in ARMS:
        arm = record["compared_arms"][name]
        require(type(arm) is dict and arm.get("arm") == name and
                type(arm.get("split_proposed")) is bool and
                type(arm.get("logits")) is list and len(arm["logits"]) == 96,
                "missing original trained Head/route/score")
        weight = parameters_from_exact_fp32(arm)
        choice = selected_heads(x, arm, cutoff)
        dense_model = original.TwoHeads(1)
        with torch.no_grad():
            for pname, param in dense_model.named_parameters():
                param.copy_(weight[pname])
        def dense():
            return original.routing(dense_model(x), x, name,
                                    split=arm["split_proposed"], threshold=cutoff)
        def sparse():
            return sparse_selected_forward(x, choice, weight)[0]
        with torch.no_grad():
            expected_dense = dense()
            actual, counts = sparse_selected_forward(x, choice, weight)
        frozen_logits = torch.tensor(arm["logits"], dtype=torch.float32)
        deviation = max(torch.max(torch.abs(expected_dense - actual)).item(),
                        torch.max(torch.abs(actual - frozen_logits)).item())
        require(math.isfinite(deviation) and deviation <= original.TOLERANCE,
                "sparse selected Head diverges from original dense routed output")
        dense_ns, sparse_ns = paired_actual_cpu_ns(dense, sparse)
        result[name] = {
            "split_proposed": arm["split_proposed"],
            "source_weights_sha256": arm["final_weights_sha256"],
            "group_selected_row_counts": counts,
            "selected_case_head_indices": choice.tolist(),
            "actual_sparse_logits": actual.detach().tolist(),
            "max_abs_dense_and_original_logit_delta": float(deviation),
            "dense_two_head_forward_rows": 2 * len(x),
            "sparse_selected_head_forward_rows": len(x),
            "sparse_head_dispatch_groups": sum(int(n > 0) for n in counts),
            "dense_head_compute_skipped_in_sparse": len(x),
            "real_cpu_dense_process_ns": dense_ns,
            "real_cpu_sparse_process_ns": sparse_ns,
        }
    return {
        "schema": SCHEMA,
        "original_p2_report_sha256": record["report_sha256"],
        "original_source_heldout_sha256": numeric.digest(record["source_heldout_cases"]),
        "original_source_q24_sha256": numeric.digest(record["source_features_q24"]),
        "original_heldout_rows": 96,
        "original_train_only_threshold": cutoff,
        "bench_repetitions_each_mode": REPEATS,
        "pretrained_encoder_loaded_in_probe": False,
        "pretrained_encoder_forward_calls_in_probe": 0,
        "actual_local_cpu_selected_head_execution": True,
        "full_task_cpu_cost_matched": False,
        "pretrained_model_origin_independently_authenticated": False,
        "source_original_labels_seen_by_probe": False,
        "future_window_prospective": False,
        "independent_ndu_selection_authorized": False,
        "production_admission": "BLOCKED",
        "authority_posture": "DENY_ALL",
        "arms": result,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original-report", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        result = run(read_bounded(args.original_report))
        output = numeric.canonical(result) + b"\n"
        require(len(output) <= MAX_INPUT_BYTES, "physical diagnostic too large")
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps({"result": "PHYSICAL_TOP1_REFERENCE_ONLY",
                          "report_sha256":hashlib.sha256(output).hexdigest(),
                          "production_admission":"BLOCKED"},sort_keys=True))
        return 0
    except (ValueError, RuntimeError, OSError, TypeError, KeyError, OverflowError) as err:
        print(f"BLOCKED: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
