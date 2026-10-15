"""Independent bounded FP32 V9 checkpoint, initialization and drift review."""
from hashlib import sha256
import math
from pathlib import Path
import struct

from binding_review import _check, _cost
from endpoint_v8_checkpoint_review import BRIDGE_SHAPES, checkpoint_tensors, tensor_summary
from grounding_review import ARMS
from retention_v7_review import same

EXTRA = {"grounding.feature.weight": [32, 32], "grounding.metric.weight": [32, 32],
    "grounding.queries": [4, 32], "grounding.head.0.weight": [16, 6], "grounding.head.0.bias": [16],
    "grounding.head.2.weight": [2, 16], "grounding.head.2.bias": [2]}
SHAPES = dict(BRIDGE_SHAPES, **EXTRA)


def audit_identity(identity, arm):
    _check(arm in ARMS, "registered V9 arm required")
    expected = dict(schema="hepta.grounding-reader.v9", arm=arm, input_dim=384, hidden_dim=32,
        max_hops=8, max_facts=256, max_tokens=1024, parameter_count=44884, common_parameter_count=42562,
        added_parameter_count=2322, graph_depth_default=2, max_graph_depth=4, graph_reset_default=arm.endswith("_reset"),
        grounding_auxiliary_expected=arm.startswith("grounded_"), old_reader_state_transition="TokenReader-v4",
        old_reader_reset_changed=False, graph_state="unit_normalized_32d_frontier",
        graph_metric="shared_linear_cosine_for_slots_Q_C_walk_readout",
        graph_readout_features=["cos_frontier_C", "cos_frontier_Q", "cos_previous_frontier", "attention_max", "normalized_entropy", "public_presence"],
        grouped_fact_prepare="within_call_public_facts_and_masks_no_persistent_autograd_cache", public_feature_arguments=6,
        annotations_enter_forward=False, parameter_sharing_across_graph_hops=True,
        extra_last_logit_layer_zero_initialized=True, same_parameter_count_is_same_compute=False)
    _check(identity == expected, "registered V9 architecture metadata changed")


def audit_initialization(folder, record, warmup, core, arm, seed):
    folder = Path(folder)
    audit_identity(record["architecture"], arm)
    _check(record["schema"] == "hepta.grounding.initialization.v9" and record["seed"] == seed and record["arm"] == arm
           and record["file"] == "initialization.pt" and record["raw_file"] == "initialization.bin"
           and record["parameter_count"] == 44884 and record["common_parameter_count"] == 42562
           and record["training_source_groups"] == core["training_source_groups"], "initial model geometry/source identity changed")
    path, raw = folder / "initialization.pt", (folder / "initialization.bin").read_bytes()
    _check(sha256(path.read_bytes()).hexdigest() == record["file_sha256"]
           and sha256(raw).hexdigest() == record["raw_file_sha256"], "initial .pt/raw sidecar file SHA changed")
    tensors = checkpoint_tensors(path, SHAPES)
    _check(set(warmup) == set(BRIDGE_SHAPES) and all(tensors[n] == warmup[n] for n in BRIDGE_SHAPES),
           "all 22 actual V6 warmup tensors must remain byte-identical")
    for name in ("grounding.head.2.weight", "grounding.head.2.bias"):
        _check(all(v == 0. for (v,) in struct.iter_unpack("<f", tensors[name][1])), "new final logit layer must initialize to zero")
    position, seen = 0, set()
    for item in record["tensors"]:
        name = item["name"]
        _check(name in tensors and name not in seen and item["offset"] == position and item["dtype"] == "torch.float32"
               and item["shape"] == list(tensors[name][0]) and item["role"] == ("common" if name in BRIDGE_SHAPES else "extra"),
               "sorted contiguous initial tensor identity changed")
        payload = tensors[name][1]
        _check(item["nbytes"] == len(payload) and item["sha256"] == sha256(payload).hexdigest()
               and raw[position:position + len(payload)] == payload, "initial raw and checkpoint tensor bytes differ")
        position += len(payload)
        seen.add(name)
    summary = tensor_summary(tensors)
    _check(seen == set(SHAPES) and position == len(raw) and [r["name"] for r in record["tensors"]] == sorted(tensors)
           and all(record[k] == summary[k] for k in ("training_parameter_sha256", "execution_parameter_sha256", "parameter_count"))
           and record["common_training_parameter_sha256"] == core["training_parameter_sha256"]
           and record["common_execution_parameter_sha256"] == core["execution_parameter_sha256"], "initial complete tensor coverage or named digest changed")
    return tensors, dict(passed=True, **summary, old_tensor_bytes_equal=True, added_parameters=2322,
                         raw_sidecar_and_checkpoint_bytes_equal=True)


def audit_learning_change(record, initial, final, before_record, after_record):
    _check(record["schema"] == "hepta.grounding.learning-change.v9"
           and record["initial_execution_parameter_sha256"] == before_record["execution_parameter_sha256"]
           and record["final_execution_parameter_sha256"] == after_record["execution_parameter_sha256"]
           and [r["name"] for r in record["tensors"]] == sorted(SHAPES), "drift full tensor/source coverage changed")
    groups = {role: dict(tensors=0, changed_tensors=0, squared_delta=0.) for role in ("common", "extra")}
    for item in record["tensors"]:
        name = item["name"]
        shape, before = initial[name]
        final_shape, after = final[name]
        role = "common" if name in BRIDGE_SHAPES else "extra"
        _check(shape == final_shape and item["shape"] == list(shape) and item["role"] == role
               and item["before_sha256"] == sha256(before).hexdigest() and item["after_sha256"] == sha256(after).hexdigest(), "drift tensor bytes/shape binding changed")
        left = [v for (v,) in struct.iter_unpack("<f", before)]
        right = [v for (v,) in struct.iter_unpack("<f", after)]
        differences = [a - b for a, b in zip(right, left)]
        squared = sum(v * v for v in differences)
        same(item["l2"], math.sqrt(squared), "decoded drift L2 mismatch", atol=1e-10, rtol=1e-8)
        same(item["maximum_absolute_delta"], max(map(abs, differences)), "decoded drift max mismatch")
        _check(item["before_nonzeros"] == sum(v != 0. for v in left)
               and item["after_nonzeros"] == sum(v != 0. for v in right), "decoded drift nonzero counts mismatch")
        groups[role]["tensors"] += 1
        groups[role]["changed_tensors"] += int(before != after)
        groups[role]["squared_delta"] += squared
    return dict(passed=True, groups={role: dict(tensors=v["tensors"], changed_tensors=v["changed_tensors"],
        delta_l2=math.sqrt(v["squared_delta"])) for role, v in groups.items()}, cost_once=_cost(record["phase_cost"]),
        scope="actual_parameter_change_not_causal_success")


def review(run, code, natural_cases, *, stage="prepare"):
    from grounding_run_review import review as review_run
    return review_run(run, code, natural_cases, stage=stage)
