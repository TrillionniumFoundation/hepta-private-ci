"""Stdlib V8 tensor-byte audit, independent of the model implementation.

The bounded decoder only accepts contiguous detached CPU FP32 state dictionaries.
No Torch, endpoint model, trainer, data generator or neural scorer is imported.
"""
from collections import OrderedDict
from hashlib import sha256
import io
import json
import math
from pathlib import Path, PurePosixPath
import pickle
import struct
import time
import zipfile

from binding_review import _check
from bridge_feedback_review import _FLOAT, _Storage, _Tensor
from bridge_review import BASE_SHAPES, EXTRA_NAMES, _parameter_sha

ARMS = ("bridge", "endpoint", "broken", "local")
BRIDGE_SHAPES = dict(BASE_SHAPES, **{name: [32, 32] for name in EXTRA_NAMES["bridge"]})
ENDPOINT_EXTRA = {"endpoint_branch." + name + ".weight": [32, 32]
                  for name in ("input", "match", "value", "output")}
ENDPOINT_EXTRA["endpoint_branch.slot_queries"] = [2, 32]
LOCAL_EXTRA = {"head.endpoint_local." + name + ".weight": [32, 32]
               for name in ("input", "hidden1", "hidden2", "output")}
LOCAL_EXTRA.update({"head.endpoint_local.norm." + name: [32] for name in ("weight", "bias")})


def parameter_shapes(arm):
    _check(arm in ARMS, "registered endpoint architecture arm required")
    extra = {} if arm == "bridge" else LOCAL_EXTRA if arm == "local" else ENDPOINT_EXTRA
    return dict(BRIDGE_SHAPES, **extra)


def checkpoint_tensors(path, shapes):
    """Decode named FP32 payloads, retaining bytes for old-tensor comparison."""
    _check(Path(path).stat().st_size <= 8 * 1024 ** 2, "checkpoint byte limit exceeded")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _check(len(names) == len(set(names)) <= 512 and all(not PurePosixPath(n).is_absolute()
               and ".." not in PurePosixPath(n).parts for n in names)
               and sum(v.file_size for v in archive.infolist()) <= 16 * 1024 ** 2,
               "bounded unique relative ZIP records required")
        records = [n for n in names if n.endswith("/data.pkl")]
        _check(len(records) == 1, "one state pickle required")
        prefix, storages = records[0][:-8], {}
        _check(archive.read(prefix + "byteorder") == b"little", "little endian FP32 required")

        def rebuild(storage, offset, size, stride, requires_grad, hooks, metadata=None):
            _check(isinstance(storage, _Storage) and type(offset) is int and offset >= 0
                   and type(size) is tuple and type(stride) is tuple and 1 <= len(size) <= 4
                   and all(type(n) is int and 0 < n <= 8192 for n in size)
                   and requires_grad is False and isinstance(hooks, (dict, OrderedDict)) and not hooks
                   and metadata is None, "bounded detached tensor reconstruction required")
            expected, count = [], 1
            for axis in reversed(size):
                expected.append(count)
                count *= axis
            _check(tuple(reversed(expected)) == stride and offset + count <= storage.count,
                   "contiguous tensor storage bounds required")
            return _Tensor(storage, offset, size)

        class Reader(pickle.Unpickler):
            def find_class(self, module, name):
                allowed = {("collections", "OrderedDict"): OrderedDict, ("torch", "FloatStorage"): _FLOAT,
                           ("torch._utils", "_rebuild_tensor_v2"): rebuild}
                _check((module, name) in allowed, "unregistered pickle global")
                return allowed[module, name]

            def persistent_load(self, value):
                _check(type(value) is tuple and len(value) == 5 and value[0] == "storage"
                       and value[1] is _FLOAT and value[3] == "cpu" and type(value[2]) is str
                       and value[2].isascii() and value[2].isdigit() and len(value[2]) <= 16
                       and type(value[4]) is int and 0 < value[4] <= 1_000_000,
                       "bounded CPU FP32 storage required")
                _check(value[2] not in storages or storages[value[2]] == value[4], "storage length changed")
                storages[value[2]] = value[4]
                return _Storage(value[2], value[4])

        raw = archive.read(records[0])
        _check(len(raw) <= 1_048_576, "state pickle limit exceeded")
        stream = io.BytesIO(raw)
        state = Reader(stream).load()
        _check(stream.tell() == len(raw) and isinstance(state, (dict, OrderedDict))
               and set(state) == set(shapes), "registered complete state dictionary required")
        _check({n for n in names if n.startswith(prefix + "data/")}
               == {prefix + "data/" + key for key in storages}, "unreferenced/missing tensor storage")
        payloads = {key: archive.read(prefix + "data/" + key) for key in storages}
        _check(all(len(payloads[k]) == count * 4 for k, count in storages.items()), "FP32 storage byte count mismatch")
        result = {}
        for name, tensor in sorted(state.items()):
            _check(isinstance(tensor, _Tensor) and list(tensor.shape) == list(shapes[name]),
                   "checkpoint tensor geometry mismatch")
            count = math.prod(tensor.shape)
            data = payloads[tensor.storage.key][tensor.offset * 4:(tensor.offset + count) * 4]
            _check(len(data) == count * 4 and all(math.isfinite(v) for (v,) in struct.iter_unpack("<f", data)),
                   "nonfinite/truncated tensor payload")
            result[name] = (tuple(tensor.shape), data)
        return result


def tensor_summary(tensors):
    return dict(training_parameter_sha256=_parameter_sha(tensors),
        execution_parameter_sha256=_parameter_sha(tensors, typed=True),
        parameter_count=sum(math.prod(shape) for shape, _ in tensors.values()),
        tensors=len(tensors), finite_FP32_tensors_decoded=True)


def audit_initial_tensors(tensors, warmup, arm):
    _check(set(tensors) == set(parameter_shapes(arm)) and set(warmup) == set(BRIDGE_SHAPES),
           "complete initial architecture tensor coverage required")
    _check(all(tuple(shape) == tuple(parameter_shapes(arm)[name]) and len(data) == math.prod(shape) * 4
               for name, (shape, data) in tensors.items()), "registered initial tensor geometry required")
    _check(all(tensors[name] == warmup[name] for name in BRIDGE_SHAPES),
           "old warmup tensor bytes were not preserved in the initial model")
    if arm != "bridge":
        output = "head.endpoint_local.output.weight" if arm == "local" else "endpoint_branch.output.weight"
        _check(all(value == 0. for (value,) in struct.iter_unpack("<f", tensors[output][1])),
               "new residual output must initialize to exact zero")
    result = tensor_summary(tensors)
    _check(result["parameter_count"] == (42562 if arm == "bridge" else 46722),
           "initial parameter count differs from the registered arm")
    return dict(passed=True, arm=arm, **result, old_tensor_count=22, old_tensor_bytes_equal=True,
                added_parameter_count=0 if arm == "bridge" else 4160,
                initial_predictions_neurally_reexecuted=False)


def audit_identity(identity, arm):
    _check(arm in ARMS, "registered architecture arm required")
    endpoints = arm in ("endpoint", "broken")
    expected = dict(schema="hepta.endpoint-reader.v8", arm=arm, input_dim=384, hidden_dim=32,
        max_hops=8, max_facts=256, max_tokens=1024, parameter_count=42562 + (4160 if arm != "bridge" else 0),
        common_parameter_count=42562, added_parameter_count=0 if arm == "bridge" else 4160,
        old_fact_bridge_retained=True, public_feature_arguments=6, state_transition="TokenReader-v4",
        residual_location="parallel_endpoint_prepare" if endpoints else "local_head_hidden" if arm == "local" else "none",
        endpoint_input="LayerNorm_h(project(LayerNorm_input(raw_fact_tokens)))" if endpoints else None,
        shared_entity_match_projection=endpoints, self_key_index_edges=False,
        broken_self_payload_possible=arm == "broken", fact_axis_unit="caller_supplied_fact_or_token_chunk",
        slot_semantics="learned_latent_endpoints_not_certified_entity_parser", broken_payload_only=arm == "broken",
        public_value_order="raw_valid_token_SHA256_then_input_index",
        hash_tie_limit="index_tie_break_no_unconditional_equivariance_claim",
        zero_or_one_valid_fact_message="zero_for_endpoint_and_broken",
        pure_binding_causal_identification=False, same_parameter_count_is_same_compute=False)
    _check(identity == expected, "registered endpoint architecture metadata changed")


def audit_initialization(folder, record, warmup, arm, seed, sources):
    folder = Path(folder)
    audit_identity(record["architecture"], arm)
    _check(record["schema"] == "hepta.endpoint.initialization.v8" and record["arm"] == arm
           and record["seed"] == seed and record["file"] == "initialization.pt"
           and record["raw_file"] == "initialization.bin" and record["training_source_groups"] == list(sources),
           "initialization file/seed/source provenance changed")
    pt, raw = folder / "initialization.pt", (folder / "initialization.bin").read_bytes()
    _check(sha256(pt.read_bytes()).hexdigest() == record["file_sha256"]
           and sha256(raw).hexdigest() == record["raw_file_sha256"], "initialization file SHA changed")
    tensors = checkpoint_tensors(pt, parameter_shapes(arm))
    summary = audit_initial_tensors(tensors, warmup, arm)
    position, seen = 0, set()
    for item in record["tensors"]:
        name = item["name"]
        _check(name in tensors and name not in seen and item["offset"] == position
               and item["dtype"] == "torch.float32" and item["shape"] == list(tensors[name][0])
               and item["role"] == ("common" if name in BRIDGE_SHAPES else "extra"), "initialization raw tensor identity/layout changed")
        payload = tensors[name][1]
        _check(item["nbytes"] == len(payload) and raw[position:position + len(payload)] == payload
               and item["sha256"] == sha256(payload).hexdigest(), "raw sidecar differs from actual checkpoint tensor bytes")
        position += len(payload)
        seen.add(name)
    _check(seen == set(tensors) and position == len(raw)
           and [t["name"] for t in record["tensors"]] == sorted(tensors), "complete sorted initial raw tensor coverage required")
    for key in ("training_parameter_sha256", "execution_parameter_sha256", "parameter_count"):
        _check(record[key] == summary[key], "initialization named digest/count differs from decoded tensors")
    common = tensor_summary(warmup)
    _check(record["common_parameter_count"] == 42562
           and record["extra_parameter_count"] == summary["added_parameter_count"]
           and record["common_training_parameter_sha256"] == common["training_parameter_sha256"]
           and record["common_execution_parameter_sha256"] == common["execution_parameter_sha256"],
           "common warmup initialization dual-digest binding changed")
    return tensors, dict(**summary, raw_sidecar_and_checkpoint_bytes_equal=True)


def audit_extra_matching(arms):
    _check(set(arms) == set(ARMS), "all four initial tensor sets required")
    _check(all(arms["endpoint"][name] == arms["broken"][name] for name in ENDPOINT_EXTRA),
           "endpoint and broken must start with identical complete added tensor bytes")
    left = ("input", "match", "value", "output")
    right = ("input", "hidden1", "hidden2", "output")
    _check(all(arms["endpoint"][f"endpoint_branch.{a}.weight"] == arms["local"][f"head.endpoint_local.{b}.weight"]
               for a, b in zip(left, right)), "local and endpoint four role-matched matrices must start byte-identical")
    return dict(passed=True, endpoint_broken_all_extra_bytes_equal=True, local_four_matrix_bytes_equal=True,
                slot_queries_and_local_affine_parameters_not_equated=True)


def audit_learning_change(record, initial, final, arm, initial_record, final_record):
    from retention_v7_review import same
    from binding_review import _cost
    _check(record["schema"] == "hepta.endpoint.learning-change.v8" and record["arm"] == arm
           and record["initial_weight_sha256"] == initial_record["file_sha256"]
           and record["final_weight_sha256"] == final_record["file_sha256"]
           and record["initial_training_parameter_sha256"] == initial_record["training_parameter_sha256"]
           and record["final_training_parameter_sha256"] == final_record["training_parameter_sha256"]
           and record["final_execution_parameter_sha256"] == final_record["execution_parameter_sha256"]
           and record["scope"] == "training_connection_only_not_causal_success", "learning-change source/checkpoint scope changed")
    _check([item["name"] for item in record["tensors"]] == sorted(initial), "complete learning-change tensor coverage required")
    groups = {role: dict(tensors=0, changed_tensors=0, delta_l2=0.) for role in ("common", "extra")}
    for item in record["tensors"]:
        name = item["name"]
        shape, before = initial[name]
        final_shape, after = final[name]
        role = "common" if name in BRIDGE_SHAPES else "extra"
        _check(shape == final_shape and item["shape"] == list(shape) and item["role"] == role
               and item["before_sha256"] == sha256(before).hexdigest() and item["after_sha256"] == sha256(after).hexdigest(),
               "learning-change tensor hashes/geometry changed")
        left = [value for (value,) in struct.iter_unpack("<f", before)]
        right = [value for (value,) in struct.iter_unpack("<f", after)]
        differences = [a - b for a, b in zip(right, left)]
        l2 = math.sqrt(sum(v * v for v in differences))
        same(item["l2"], l2, "learning-change delta norm mismatch", atol=1e-10, rtol=1e-8)
        same(item["maximum_absolute_delta"], max(map(abs, differences)), "learning-change max delta mismatch")
        _check(item["before_nonzeros"] == sum(v != 0. for v in left)
               and item["after_nonzeros"] == sum(v != 0. for v in right), "learning-change nonzero count mismatch")
        groups[role]["tensors"] += 1
        groups[role]["changed_tensors"] += int(before != after)
        groups[role]["delta_l2"] += l2 * l2
    for role, expected in groups.items():
        expected["delta_l2"] = math.sqrt(expected["delta_l2"])
        _check(record["groups"][role]["tensors"] == expected["tensors"]
               and record["groups"][role]["changed_tensors"] == expected["changed_tensors"], "learning-change group count mismatch")
        same(record["groups"][role]["delta_l2"], expected["delta_l2"], "learning-change group norm mismatch")
    return dict(passed=True, groups=groups, cost_once=_cost(record["phase_cost"]),
                scope="actual_weight_change_not_evidence_of_benefit_or_causal_identification")


def review(run, code, natural_cases, *, stage="prepare"):
    from binding_review import _cost, _digest, audit_source_inventory
    from bridge_feedback_review import audit_manifest
    from endpoint_v8_review import audit_binding_panel, audit_start_predictions, audit_support_transform, review_completed
    from retention_v7_checkpoint_review import file_sha, natural_panel, review as review_v7
    from retention_v7_review import audit_plan
    started = time.perf_counter_ns(), time.process_time_ns()
    run, code = Path(run), Path(code)
    _check(stage in ("prepare", "training"), "explicit prepare/training audit stage required")
    guarded = {}

    def bind(path):
        path = Path(path).resolve()
        digest = file_sha(path)
        _check(str(path) not in guarded or guarded[str(path)] == digest, "audit input changed between reads")
        guarded[str(path)] = digest
        return path

    def load(path):
        return json.loads(bind(path).read_text())

    names = ("binding_review.py", "bridge_feedback_review.py", "bridge_review.py", "bridge_revision_review.py",
             "retention_v7_review.py", "retention_v7_checkpoint_review.py", "endpoint_v8_review.py", "endpoint_v8_checkpoint_review.py")
    for name in names:
        bind(code / name)
    design, parts = load(run / "design.json"), load(run / "all-cases.json")
    _check(design["schema"] == "hepta.endpoint.campaign.v8" and design["primary"] == "endpoint"
           and design["arms"] == list(ARMS) and design["order"] == {str(s): list(ARMS[i:] + ARMS[:i]) for i, s in enumerate((41, 47, 53))},
           "registered V8 primary/arms/order changed")
    _check(design["training"] == dict(recipe="diverse", logical_updates=500, streams=["natural", "transfer", "retention"],
        batch_size=16, depth=3, learning_rate=.001, pair_weight=.5, anchor_weight=0., diagnostic_interval=100,
        wall_time_ns=1_800_000_000_000, optimizer_updates=1500, candidate_exposures=24000, stop_rule="fixed_final_no_selection"),
        "registered common diverse recipe changed")
    _check(design["teacher"] == dict(source="actual_V7_cache", role="unused_compatibility_reference", new_forward_calls=0,
        active_distillation=False, cost_is_historical=True) and design["natural_start"] == dict(
        source="actual_V7_full_natural_start", new_forward_calls=0, cost_is_historical=True)
        and design["initial_panel"] == dict(role="reader_train", candidate_observations=1536, steps=3,
        four_arms_actually_executed=True, probability_equality="exact_same_seed"), "historical/start/initial observation scope changed")
    _check(all(design[k] is False for k in ("encoder_new_forward_authorized", "diagnostics_select_models", "feedback_authorized",
        "fresh_authorized", "automatic_downstream_opening", "official_validation_read", "hosted_ci_consulted", "production_authorized"))
        and design["diagnostics"] == ["verified_support_deleted3", "reset3", "full1"]
        and design["full3_reused_from_final_panel"] is True, "V8 diagnostic/downstream boundaries changed")
    previous_roots = {Path(r["folder"]).parent for r in design["historical"]["observations"].values()}
    _check(len(previous_roots) == 1 and set(design["historical"]["observations"]) == {"41", "47", "53"}, "one complete V7 provenance chain required")
    previous = next(iter(previous_roots))
    prior_design, prior_completion = load(previous / "design.json"), load(previous / "training-completion.json")
    _check(file_sha(previous / "design.json") == design["previous_v7_design_sha256"]
           and file_sha(previous / "training-completion.json") == design["previous_v7_training_completion_sha256"]
           and prior_completion["runtime_source_sha256"] == prior_design["runtime_source_sha256"]
           and set(prior_completion["gates"]) == {"41", "47", "53"}, "V7 actual completed provenance changed")
    prior = review_v7(previous, code, natural_cases, stage="prepare")
    for path, digest in prior["inputs_sha256"].items():
        _check(file_sha(bind(path)) == digest, "independent V7 input audit chain changed")
    inventory = design["runtime_source_sha256"]
    added = {"endpoint_reader.py", "endpoint_campaign_utils.py", "endpoint_campaign.py"}
    _check(len(inventory) == 61 and set(inventory) == set(prior_design["runtime_source_sha256"]) | added
           and all(inventory[n] == sha for n, sha in prior_design["runtime_source_sha256"].items()), "old 58 runtime bytes or V8 three-file inventory changed")
    for name in inventory:
        bind(code / name)
    sources = audit_source_inventory(code, inventory)
    _check(file_sha(bind(code / "ENDPOINT_V8_PROTOCOL.md")) == design["protocol_sha256"], "frozen V8 protocol changed")
    old_parts, natural = load(previous / "all-cases.json"), load(natural_cases)
    expected_parts = {role: old_parts[role] for role in ("reader_train", "internal_tune", "augmentation")}
    expected_parts.update(natural_train=natural["train"], natural_internal=natural["tune"])
    _check(parts == expected_parts and design["natural_case_ids"] == prior_design["natural_case_ids"]
           and design["natural_constants"] == prior_design["natural_constants"] and design["gates"] == prior_design["gates"], "complete V7 data or fixed qualification reused incorrectly")
    _check(design["historical"]["warmups"] == prior_design["historical_warmups"]
           and design["reused_cache_files_sha256"] == prior_design["extended_cache_files_sha256"], "historical warmup/cache reference changed")
    transform = load(run / "support-transform.json")
    support = audit_support_transform(transform, parts["reader_train"])
    expected_files = {"all-cases.json", "support-transform.json"} | {f"seed-{s}/training-plan.json" for s in (41, 47, 53)} | {
        f"seed-{s}/{arm}/initialization.{suffix}" for s in (41, 47, 53) for arm in ARMS for suffix in ("json", "pt", "bin")}
    _check(set(design["prepared_files_sha256"]) == expected_files, "complete 41-file prepared input inventory required")
    for name, digest in design["prepared_files_sha256"].items():
        _check(file_sha(bind(run / name)) == digest, "prepared V8 input changed")
    prep = load(run / "preparation-completion.json")
    _check(prep["design_sha256"] == file_sha(run / "design.json")
           and prep["exact_initial_probability_equality"] == {str(s): True for s in (41, 47, 53)}
           and prep["actual_initial_candidate_observations"] == 1536 and prep["encoder_new_forward_batches"] == prep["encoder_new_sequences"] == 0
           and prep["reused_cache_generation_cost_not_additive"] is True and prep["completed_ns"] > design["created_ns"], "actual prepare completion/cost scope changed")
    expected_panels = {f"seed-{s}/{arm}/initial-binding-train.json" for s in (41, 47, 53) for arm in ARMS}
    _check(set(prep["initial_panels_sha256"]) == expected_panels, "all twelve actual initial panels required")
    initial, reports, panel_cost = {}, [], dict(cpu_ns=0, wall_ns=0)
    for seed in (41, 47, 53):
        historical = design["historical"]["warmups"][str(seed)]
        core_folder = Path(historical["folder"])
        core = audit_manifest(core_folder / "warmup-model.json", expected_arm="bridge")
        warmup = checkpoint_tensors(bind(core_folder / "warmup.pt"), BRIDGE_SHAPES)
        observation = design["historical"]["observations"][str(seed)]
        _check(Path(observation["folder"]).resolve() == (previous / f"seed-{seed}").resolve()
               and observation["reused_teacher_neural_calls"] == observation["reused_natural_start_neural_calls"] == 0
               and set(observation["files_sha256"]) == {"teacher.json", "teacher-logits.bin", "start-natural-train.json", "training-plan.json", "diverse-model.json", "diverse-training.json"}, "six-file historical observation reference changed")
        for name, digest in observation["files_sha256"].items():
            _check(file_sha(bind(Path(observation["folder"]) / name)) == digest, "historical teacher/start/plan file changed")
        start = natural_panel(natural["train"], load(previous / f"seed-{seed}/start-natural-train.json"), core,
                              "complete_natural_training_partition_before_updates")
        plan = load(run / f"seed-{seed}/training-plan.json")
        _check(plan == load(previous / f"seed-{seed}/training-plan.json"), "V8 plan differs from actual V7 diverse schedule")
        audit_plan(plan, natural["train"], parts["reader_train"], parts["augmentation"])
        arms, panels, init_reports = {}, {}, []
        initial[seed] = {}
        for arm in ARMS:
            folder = run / f"seed-{seed}" / arm
            record = load(folder / "initialization.json")
            tensors, summary = audit_initialization(folder, record, warmup, arm, seed, core["training_source_groups"])
            path = folder / "initial-binding-train.json"
            _check(file_sha(bind(path)) == prep["initial_panels_sha256"][str(path.relative_to(run))], "initial panel bytes changed")
            panel = load(path)
            checked = audit_binding_panel(parts["reader_train"], panel, record)
            for axis, value in checked["costs"].items():
                panel_cost[axis] += value
            arms[arm], panels[arm] = tensors, panel
            initial[seed][arm] = (record, tensors)
            init_reports.append(dict(arm=arm, checkpoint=summary, panel=checked))
        reports.append(dict(seed=seed, arms=init_reports, extra_matching=audit_extra_matching(arms),
            initial_probabilities=audit_start_predictions(panels), reused_natural_start_metrics=start["metrics"]))
    _check(all(_cost(prep["phase_cost"])[axis] >= value for axis, value in panel_cost.items()), "prepare outer cost omits actual initial panels")
    result = dict(schema="hepta.endpoint.independent-review.v8", passed=True, stage=stage, sources=sources,
        source_inventory_count=61, old_runtime_58_unchanged=True, prepared_input_files=41, support_transform=support,
        previous_v7_prepare_audit_passed=True, initializations=reports, initial_candidate_observations=1536,
        preparation_cost=dict(outer_phase_once=_cost(prep["phase_cost"]), initial_panels_nested_not_added=panel_cost,
            historical_teacher_and_natural_start_not_recharged=True), training_audited=False, feedback_audited=False,
        fresh_audited=False, torch_imported=False, independent_neural_execution=False, official_validation_read=False)
    if stage == "training":
        result.update(review_completed(run, previous, code, design, parts, initial, transform, load, bind))
    _check(all(file_sha(path) == digest for path, digest in guarded.items()), "independent audit inputs changed during review")
    result.update(immutable_inputs_unchanged=True, inputs_sha256=guarded,
        auditor_source_sha256={name: file_sha(code / name) for name in names},
        audit_cost=dict(cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
            scope="stdlib_parse_hash_decode_numeric_replay_excludes_process_startup_output_serialization"),
        limitations=["No neural rerun; clocks and gradient norms are consistency checked observations.",
                     "Support masks reconstructed; transformed fact FP32 values authenticated by recorded hashes, not independently decoded."])
    return result
