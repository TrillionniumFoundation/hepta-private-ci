"""Pure stdlib V6 audit of architecture, shared initialization and real costs.

Initial FP32 tensors are independently decoded from the explicit raw sidecar.
Trained .pt checkpoints retain the narrower file-byte/receipt audit from V5.
"""

from hashlib import sha256
import json
import math
from pathlib import Path
import struct

from binding_review import (audit_checkpoint, audit_natural_panel, audit_panel, audit_protocol, audit_scores,
    audit_source_inventory, audit_warmup)


ARMS = ("base", "bridge", "wide")
SEEDS = (41, 47, 53)
BASE_SHAPES = {"project.weight": [32, 384], "query.weight": [32, 128], "query.bias": [32],
    "relation.weight": [32, 256], "relation.bias": [32], "token_score.weight": [1, 32],
    "token_key.weight": [32, 32], "fact_score.weight": [1, 32], "fact_key.weight": [32, 32],
    "state_query.weight": [32, 64], "proposal.weight": [32, 100], "proposal.bias": [32],
    "update_gate.weight": [32, 100], "update_gate.bias": [32], "head.0.weight": [32, 97],
    "head.0.bias": [32], "head.2.weight": [2, 32], "head.2.bias": [2]}
EXTRA_NAMES = {"base": (), "bridge": tuple("fact_bridge." + name + ".weight" for name in ("query", "key", "value", "output")),
    "wide": tuple("head.local_residual." + name + ".weight" for name in ("input", "hidden1", "hidden2", "output"))}


def _check(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path):
    return json.loads(Path(path).read_text())


def _file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _material(metadata_path):
    metadata_path = Path(metadata_path)
    metadata = _read(metadata_path)
    _check(metadata["schema"] == "hepta.bridge.initialization.v1" and metadata["arm"] in ARMS
           and type(metadata["seed"]) is int and metadata["seed"] in SEEDS, "registered architecture arm and seed required")
    binary_path = metadata_path.parent / metadata["file"]
    _check(Path(metadata["file"]).name == metadata["file"], "initialization binary must be a sibling file")
    data = binary_path.read_bytes()
    _check(sha256(data).hexdigest() == metadata["file_sha256"], "initialization binary byte hash mismatch")
    expected = dict(BASE_SHAPES, **{name: [32, 32] for name in EXTRA_NAMES[metadata["arm"]]})
    tensors, position = {}, 0
    for tensor in sorted(metadata["tensors"], key=lambda item: item["offset"]):
        name, shape = tensor["name"], tensor["shape"]
        _check(name in expected and name not in tensors and shape == expected[name]
               and all(type(size) is int and size > 0 for size in shape), "initial tensor name/shape differs from registered architecture")
        _check(tensor["dtype"] == "torch.float32" and type(tensor["offset"]) is int and tensor["offset"] == position,
               "contiguous little-endian FP32 initialization required")
        count = math.prod(shape)
        _check(type(tensor["nbytes"]) is int and tensor["nbytes"] == count * 4, "initial tensor byte count mismatch")
        payload = data[position:position + tensor["nbytes"]]
        _check(len(payload) == tensor["nbytes"] and sha256(payload).hexdigest() == tensor["sha256"], "initial tensor payload hash mismatch")
        _check(all(math.isfinite(value) for (value,) in struct.iter_unpack("<f", payload)), "nonfinite initial FP32 tensor")
        common = name in BASE_SHAPES
        _check(tensor["role"] == ("common" if common else "extra"), "common/extra role binding mismatch")
        tensors[name] = (shape, payload)
        position += len(payload)
    _check(set(tensors) == set(expected) and position == len(data), "initial parameter coverage incomplete or trailing bytes present")
    return metadata, tensors


def _parameter_sha(tensors, *, typed=False):
    digest = sha256()
    for name, (shape, data) in sorted(tensors.items()):
        digest.update(name.encode())
        digest.update(str(tuple(shape)).encode())
        if typed:
            digest.update(b"torch.float32")
        digest.update(data)
    return digest.hexdigest()


def audit_initialization(metadata_path):
    metadata, tensors = _material(metadata_path)
    common = {name: value for name, value in tensors.items() if name in BASE_SHAPES}
    total = sum(math.prod(shape) for shape, _ in tensors.values())
    extra = total - sum(math.prod(shape) for shape, _ in common.values())
    expected_extra = 0 if metadata["arm"] == "base" else 4096
    _check(total == 38466 + expected_extra and metadata["parameter_count"] == total
           and metadata["common_parameter_count"] == 38466 and metadata["extra_parameter_count"] == extra,
           "independent architecture parameter count mismatch")
    training, execution = _parameter_sha(tensors), _parameter_sha(tensors, typed=True)
    _check(training == metadata["training_parameter_sha256"] and execution == metadata["execution_parameter_sha256"],
           "independently reconstructed initial parameter digest mismatch")
    if expected_extra:
        output = EXTRA_NAMES[metadata["arm"]][-1]
        _check(all(value == 0 for (value,) in struct.iter_unpack("<f", tensors[output][1])), "residual output initialization must be zero")
    return dict(passed=True, arm=metadata["arm"], seed=metadata["seed"], parameter_count=total,
        common_parameter_count=38466, extra_parameter_count=extra, training_parameter_sha256=training,
        execution_parameter_sha256=execution, common_training_parameter_sha256=_parameter_sha(common),
        common_execution_parameter_sha256=_parameter_sha(common, typed=True),
        initial_tensor_values_independently_decoded=True, binary_file_sha256=metadata["file_sha256"])


def audit_common_initializations(paths, historical_base_receipt):
    """Compare common values, then authenticate the base's historical starting point."""
    _check(set(paths) == set(ARMS), "all three initial architecture arms required")
    material = {arm: _material(path) for arm, path in paths.items()}
    reports = {arm: audit_initialization(path) for arm, path in paths.items()}
    _check(len({metadata["seed"] for metadata, _ in material.values()}) == 1,
           "shared initialization comparison requires one seed")
    for arm, (metadata, tensors) in material.items():
        _check(metadata["arm"] == arm and all(tensors[name] == material["base"][1][name] for name in BASE_SHAPES),
               "common initial tensor bytes differ across architecture arms")
    _check(reports["base"]["training_parameter_sha256"] == historical_base_receipt["initial_model_sha256"],
           "base initialization differs from the actual historical V5 run")
    paired_extra = all(material["bridge"][1][left] == material["wide"][1][right]
                       for left, right in zip(EXTRA_NAMES["bridge"], EXTRA_NAMES["wide"]))
    return dict(passed=True, seed=reports["base"]["seed"], arms=reports,
        common_initial_tensor_bytes_equal=True, historical_base_initialization_authenticated=True,
        extra_matrices_initial_bytes_also_equal=paired_extra,
        exact_initial_predictions_independently_executed=False)


def audit_architecture(identity, initialization):
    arm = initialization["arm"]
    expected_extra = 0 if arm == "base" else 4096
    _check(identity["schema"] == "hepta-bridge-reader-v1" and identity["arm"] == arm
           and identity["input_dim"] == 384 and identity["hidden_dim"] == 32 and identity["max_hops"] == 8
           and identity["max_facts"] == 256 and identity["max_tokens"] == 1024,
           "unregistered architecture dimensions or capacity bounds")
    _check(identity["parameter_count"] == 38466 + expected_extra and identity["base_parameter_count"] == 38466
           and identity["added_parameter_count"] == expected_extra and identity["state_transition"] == "TokenReader-v4"
           and identity["cross_fact_attention"] is (arm == "bridge")
           and identity["residual_location"] == {"base": "none", "bridge": "cross_fact_prepare", "wide": "local_head_hidden"}[arm],
           "architecture metadata disagrees with decoded initialization")
    return dict(passed=True, arm=arm, parameter_count=38466 + expected_extra,
                added_parameter_count=expected_extra, equal_parameter_count_is_equal_actual_compute=False)


def audit_stop_schedule(receipt, cases):
    """Recompute admission from every raw diagnostic on the fixed 250-step grid."""
    _check(receipt["requested_steps"] == 8000 and receipt["batch_size"] == 16 and receipt["depth"] == 3
           and receipt["learning_rate"] == .001 and receipt["pair_weight"] == .5
           and receipt["optimizer"] == "Adam_foreach_false"
           and receipt["stop_rule"]["diagnostic_interval"] == 250,
           "V6 warmup differs from the fixed V5 training schedule")
    completed = receipt["completed_steps"]
    _check(type(completed) is int and 250 <= completed <= 8000 and completed % 250 == 0,
           "completed warmup must stop on the registered diagnostic grid")
    diagnostics = receipt["diagnostics"]
    _check([item["optimizer_step"] for item in diagnostics] == list(range(0, completed + 1, 250)),
           "scheduled warmup diagnostic missing or reordered")
    passed = []
    for item in diagnostics:
        result = audit_scores(cases, item["binding"]["probabilities"], item["binding"])
        if (result["cases"] == 128 and result["groups"] == 32
                and result["accuracy"] == result["both_worlds_correct"] == result["all_four_correct"] == 1
                and result["probability_CE"] <= .10):
            passed.append(item["optimizer_step"])
    qualified = bool(passed)
    if qualified:
        _check(passed[0] == completed and receipt["status"] == "train_gate_passed",
               "warmup continued beyond the earliest full training gate")
    else:
        _check(completed == 8000 and receipt["status"] == "max_updates_reached",
               "unqualified warmup did not complete its registered maximum budget")
    return dict(passed=True, independently_qualified=qualified, optimizer_updates=completed,
                training_exposures=completed * 16, diagnostics=len(diagnostics),
                earliest_gate_step=passed[0] if passed else None,
                equal_budget_cap_implies_equal_actual_cost=False)


def audit_arm_admission(runs, reported=None):
    """Each family needs all three fits; wide never substitutes for failed bridge."""
    _check(set(runs) == set(ARMS), "all registered architecture arms required")
    admitted = {}
    for arm, results in runs.items():
        _check(len(results) == 3 and {item["seed"] for item in results} == set(SEEDS), "all three seeds required per architecture")
        admitted[arm] = all(item["independently_qualified"] for item in results)
    if reported is not None:
        _check(reported == admitted, "reported architecture admission differs from raw training gates")
    return dict(passed=True, admitted=admitted, preferred_arm="bridge", bridge_continuation_authorized=admitted["bridge"],
                wide_substitution_authorized=False, fresh_evaluation_authorized_by_warmup_alone=False)


def review_run(run, code, *, natural_cases=None):
    """Audit initialization plus every completed warmup, never fresh scores.

    Full warmup review requires warmup-completion.json. Prior natural material
    defaults to the independently verified V5 material next to these run folders;
    callers may explicitly supply its natural-cases.json for relocated evidence.
    """
    run, code = Path(run), Path(code)
    design, parts = _read(run / "design.json"), _read(run / "all-cases.json")
    guarded = {run / "design.json", run / "all-cases.json", Path(__file__)}
    guarded.update(code / name for name in design["runtime_source_sha256"])
    guarded.update(run / name for name in design["initialization_files_sha256"])
    for baseline in design["historical_baselines"].values():
        guarded.update(Path(baseline["folder"]) / name for name in baseline["files_sha256"])
        guarded.add(Path(baseline["folder"]).parent / "design.json")
    if (run / "warmup-completion.json").exists():
        guarded.add(run / "warmup-completion.json")
        material = Path(natural_cases) if natural_cases is not None else run.parent / "reader-v5-independent-audit" / "natural-cases.json"
        guarded.update((material, material.parent / "material-provenance.json"))
        guarded.update(run / f"seed-{seed}" / arm / filename for seed in SEEDS for arm in ("bridge", "wide")
            for filename in ("warmup.pt", "warmup-model.json", "warmup-training.json", "warmup-binding-train.json",
                             "warmup-natural-internal.json", "warmup-gate.json"))
    initial_hashes = {str(path.resolve()): _file_sha(path) for path in guarded}
    result = dict(schema="hepta.bridge.independent-review.v1",
        sources=audit_source_inventory(code, design["runtime_source_sha256"]),
        protocol=audit_protocol(parts, design["membership"]), initializations=[], warmups=[],
        coverage=[], new_fit_costs=dict(cpu_ns=0, wall_ns=0), reused_historical_fit_costs=dict(cpu_ns=0, wall_ns=0),
        new_panel_costs=dict(cpu_ns=0, wall_ns=0), reused_historical_panel_costs=dict(cpu_ns=0, wall_ns=0))
    _check(design["primary_variant"] == "bridge" and design["control_variant"] == "wide"
           and design["gate"]["control_cannot_replace_failed_primary"] is True
           and design["same_parameter_count_is_same_compute"] is False
           and design["same_budget_limit_is_same_actual_cost"] is False, "primary arm or comparison scope changed")
    _check(design["training"] == dict(max_updates=8000, batch_size=16, depth=3, learning_rate=.001,
        pair_weight=.5, diagnostic_interval=250, wall_time_budget_ns=1_800_000_000_000,
        loss="last_hop_CE_plus_world_pair_margin", stopping="earliest_full_train_gate"), "fixed training recipe changed")
    _check(set(design["initialization_files_sha256"]) == {f"seed-{seed}/{arm}/initialization.{suffix}"
        for seed in SEEDS for arm in ARMS for suffix in ("json", "bin")}, "initialization file inventory incomplete")
    for relative, expected in design["initialization_files_sha256"].items():
        path = run / relative
        _check(_file_sha(path) == expected, "frozen initialization file changed")
        guarded.add(path)
    previous_folders = {Path(value["folder"]).parent for value in design["historical_baselines"].values()}
    _check(len(previous_folders) == 1, "historical baselines must come from one actual V5 run")
    previous = next(iter(previous_folders))
    _check(_file_sha(previous / "design.json") == design["previous_v5_design_sha256"], "historical V5 design byte hash mismatch")
    previous_design = _read(previous / "design.json")
    guarded.add(previous / "design.json")
    _check(all(design["runtime_source_sha256"].get(name) == expected for name, expected in previous_design["runtime_source_sha256"].items()),
           "original 48-file V5 runtime changed")
    complete_path = run / "warmup-completion.json"
    completed = _read(complete_path) if complete_path.exists() else None
    natural = None
    if completed is not None:
        natural_path = Path(natural_cases) if natural_cases is not None else run.parent / "reader-v5-independent-audit" / "natural-cases.json"
        provenance_path = natural_path.parent / "material-provenance.json"
        provenance = _read(provenance_path)
        _check(_file_sha(natural_path) == provenance["natural_cases_file_sha256"]
               and provenance["design_sha256"] == design["previous_v5_design_sha256"]
               and provenance["official_train_sha256"] == previous_design["train_file_sha256"],
               "independent natural reference material is not bound to the reused V5 source")
        natural = _read(natural_path)["tune"]
        guarded.update((natural_path, provenance_path, complete_path))
        _check([json.dumps([row[k] for k in ("source_split", "paragraph_id", "question_id", "answer_id")], separators=(",", ":"))
                for row in natural] == design["natural_case_ids"]["tune"], "natural internal case identities changed")
        _check(completed["runtime_source_sha256"] == design["runtime_source_sha256"], "completed warmup source inventory changed")
    admissions = {arm: [] for arm in ARMS}
    expected_old = {"warmup.pt", "warmup-model.json", "warmup-training.json", "warmup-binding-train.json",
                    "warmup-natural-internal.json", "warmup-gate.json"}
    for seed in SEEDS:
        baseline = design["historical_baselines"][str(seed)]
        old_folder = Path(baseline["folder"])
        _check(old_folder == previous / f"seed-{seed}" and set(baseline["files_sha256"]) == expected_old
               and baseline["reused_historical_training"] is True and baseline["newly_performed_training"] is False,
               "historical baseline source or reuse scope changed")
        for filename, expected in baseline["files_sha256"].items():
            path = old_folder / filename
            _check(_file_sha(path) == expected, "actual historical baseline evidence changed")
            guarded.add(path)
        old_receipt = _read(old_folder / "warmup-training.json")
        paths = {arm: run / f"seed-{seed}" / arm / "initialization.json" for arm in ARMS}
        common = audit_common_initializations(paths, old_receipt)
        _check(common["seed"] == seed and baseline["initial_training_parameter_sha256"] == old_receipt["initial_model_sha256"], "historical base init record differs from actual receipt")
        result["initializations"].append(common)
        for arm in ARMS:
            initial = common["arms"][arm]
            identity = _read(paths[arm])["architecture"]
            audit_architecture(identity, initial)
            if completed is None:
                continue
            folder = old_folder if arm == "base" else run / f"seed-{seed}" / arm
            receipt, model = _read(folder / "warmup-training.json"), _read(folder / "warmup-model.json")
            panel, internal = _read(folder / "warmup-binding-train.json"), _read(folder / "warmup-natural-internal.json")
            guarded.update(folder / name for name in expected_old)
            trained = audit_panel(parts["reader_train"], panel, model)
            audit_checkpoint(folder / model["file"], model, receipt)
            fit = audit_warmup(receipt, parts["reader_train"], trained["metrics"])
            schedule = audit_stop_schedule(receipt, parts["reader_train"])
            internal_report = audit_natural_panel(natural, internal, model)
            _check(receipt["seed"] == seed and receipt["initial_model_sha256"] == initial["training_parameter_sha256"]
                   and receipt["parameter_count"] == initial["parameter_count"], "run differs from the decoded architecture initialization")
            _check(_read(folder / "warmup-gate.json")["passed"] is fit["qualified"], "standalone training gate contradicts independent raw scores")
            if arm == "base":
                _check(baseline["historical_fit_cpu_ns"] == receipt["cpu_ns"] and baseline["historical_fit_wall_ns"] == receipt["wall_ns"]
                       and baseline["trained_execution_parameter_sha256"] == model["execution_parameter_sha256"], "historical cost or selected model identity changed")
            else:
                audit_architecture(model["architecture"], initial)
                _check(model["seed"] == seed and model["initial_execution_parameter_sha256"] == initial["execution_parameter_sha256"], "new model manifest initial execution digest changed")
                _check(completed["gates"][str(seed)][arm]["passed"] is fit["qualified"], "completed arm gate contradicts raw scores")
            admissions[arm].append(dict(seed=seed, independently_qualified=fit["qualified"]))
            result["warmups"].append(dict(seed=seed, arm=arm, historical_reuse=arm == "base", fit=fit,
                schedule=schedule, training_panel=trained, natural_internal_panel=internal_report))
            for axis in ("cpu_ns", "wall_ns"):
                result["reused_historical_fit_costs" if arm == "base" else "new_fit_costs"][axis] += receipt[axis]
                result["reused_historical_panel_costs" if arm == "base" else "new_panel_costs"][axis] += trained["costs"][axis] + internal_report["costs"][axis]
            result["coverage"].append(dict(seed=seed, arm=arm, folder=str(folder.resolve()),
                artifacts=sorted(expected_old), reuse="historical_not_new" if arm == "base" else "new_training"))
    if completed is not None:
        admission = audit_arm_admission(admissions)
        _check(completed["admitted"] == {arm: admission["admitted"][arm] for arm in ("bridge", "wide")}
               and completed["primary_all_passed"] is admission["bridge_continuation_authorized"], "completed admission or primary selection changed")
        result["admission"] = admission
        phase = completed["phase_cost"]
        _check(phase["cpu_ns"] >= result["new_fit_costs"]["cpu_ns"] + result["new_panel_costs"]["cpu_ns"], "new phase CPU below disjoint new fit/panel subscopes")
        result["new_whole_phase_cost"] = phase
        if not admission["bridge_continuation_authorized"]:
            markers = ("continuation-start.json", "continuation-completion.json", "feedback-start.json",
                       "all-models-frozen.json", "evaluation-start.json", "completion.json")
            _check(not any((run / name).exists() for name in markers), "failed primary arm opened downstream work")
            result["downstream_scope"] = "continuation_feedback_fresh_not_executed_primary_train_gate_closed"
        else:
            result["downstream_scope"] = "primary_continuation_authorized_further_stages_not_audited_here"
    _check(set(initial_hashes) == {str(path.resolve()) for path in guarded}, "review discovered an input outside its initial immutable inventory")
    after = {path: _file_sha(path) for path in initial_hashes}
    _check(initial_hashes == after, "review input files changed during read-only audit")
    result.update(passed=True, warmup_phase_complete=completed is not None,
        scope="all_nine_initializations_and_nine_actual_warmups" if completed is not None else "initialization_and_source_only_no_partial_warmup_read",
        guarded_input_files=len(after), input_sha256=after, historical_costs_not_charged_as_new=True,
        outer_phase_costs_not_added_to_nested_fit_or_panel_costs=True, official_validation_read=False,
        fresh_prediction_outputs_read=False, trained_tensors_independently_decoded=False)
    return result


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--natural-cases", type=Path)
    args = parser.parse_args()
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    result = review_run(args.run, args.code, natural_cases=args.natural_cases)
    result["audit_cost"] = dict(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
                                scope="complete_audit_call_excluding_output_serialization")
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
