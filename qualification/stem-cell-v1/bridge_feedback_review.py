"""Stdlib V6 feedback audit, separate from the frozen neural runtime.

Checks actual checkpoint bytes with a restricted CPU FP32 ZIP decoder, but does
not reexecute a network or authenticate recorded gradients, clocks or history.
Fresh output is opened only by an explicit ``--fresh`` invocation.
"""
from collections import OrderedDict, namedtuple
from hashlib import sha256
import io
import json
import math
from pathlib import Path, PurePosixPath
import pickle
import random
import struct
import zipfile

from binding_review import (_check, _cost, _digest, _group_batches, _id, audit_checkpoint,
    audit_fresh_gate, audit_panel, audit_protocol, audit_scores, audit_source_inventory)
from bridge_review import BASE_SHAPES, EXTRA_NAMES, audit_architecture
from bridge_revision_review import _hash, _number, audit_calls, audit_events, transitions

SEEDS = (41, 47, 53)
_Storage = namedtuple("_Storage", "key count")
_Tensor = namedtuple("_Tensor", "storage offset shape")
_FLOAT = object()


def read(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def checkpoint_digests(path, shapes):
    """Decode only bounded contiguous detached CPU FP32 state dictionaries."""
    _check(Path(path).stat().st_size <= 8 * 1024 ** 2, "checkpoint byte limit exceeded")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _check(len(names) == len(set(names)) <= 512 and all(not PurePosixPath(n).is_absolute()
               and ".." not in PurePosixPath(n).parts for n in names)
               and sum(v.file_size for v in archive.infolist()) <= 16 * 1024 ** 2, "bounded unique relative ZIP records required")
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
            _check(tuple(reversed(expected)) == stride and offset + count <= storage.count, "contiguous tensor storage bounds required")
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
                       and type(value[4]) is int and 0 < value[4] <= 1_000_000, "bounded CPU FP32 storage required")
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
        training, execution, parameters = sha256(), sha256(), 0
        for name, tensor in sorted(state.items()):
            _check(isinstance(tensor, _Tensor) and list(tensor.shape) == list(shapes[name]), "checkpoint tensor geometry mismatch")
            count = math.prod(tensor.shape)
            data = payloads[tensor.storage.key][tensor.offset * 4:(tensor.offset + count) * 4]
            _check(len(data) == count * 4 and all(math.isfinite(v) for (v,) in struct.iter_unpack("<f", data)), "nonfinite/truncated tensor payload")
            header = name.encode() + str(tensor.shape).encode()
            training.update(header + data)
            execution.update(header + b"torch.float32" + data)
            parameters += count
        return dict(training_parameter_sha256=training.hexdigest(), execution_parameter_sha256=execution.hexdigest(),
                    parameter_count=parameters, checkpoint_tensors_decoded=True, torch_imported=False)


def audit_manifest(path, *, expected_arm=None):
    path, record = Path(path), read(path)
    arm = record["architecture"]["arm"]
    _check(arm in EXTRA_NAMES and (expected_arm is None or arm == expected_arm), "selected architecture arm mismatch")
    audit_architecture(record["architecture"], dict(arm=arm))
    audit_checkpoint(path.parent / record["file"], record)
    shapes = dict(BASE_SHAPES, **{name: [32, 32] for name in EXTRA_NAMES[arm]})
    decoded = checkpoint_digests(path.parent / record["file"], shapes)
    _check(all(record[k] == decoded[k] for k in decoded if k.endswith("sha256") or k == "parameter_count"), "named checkpoint digests/count mismatch")
    return record


def audit_verifier(native, previous_design, seed, reader_sources, provenance):
    native = Path(native)
    _check(file_sha(native / "all-artifacts-frozen.json") == previous_design["previous_native_freeze_sha256"], "original verifier global freeze changed")
    frozen = read(native / "all-artifacts-frozen.json")
    folder = native / f"seed-{seed}"
    _check(file_sha(folder / "artifacts.json") == frozen["artifact_manifests_sha256"][str(seed)], "original verifier manifest changed")
    artifact = read(folder / "artifacts.json")["verifier"]
    _check(Path(artifact["file"]).name == artifact["file"], "verifier artifact must be a sibling file")
    path = folder / artifact["file"]
    _check(file_sha(path) == artifact["file_sha256"] == provenance["file_sha256"]
           and Path(provenance["file_path"]).resolve() == path.resolve(), "original verifier checkpoint byte/path mismatch")
    decoded = checkpoint_digests(path, BASE_SHAPES)
    sources = artifact["training_source_groups"]
    _check(decoded["training_parameter_sha256"] == artifact["model_sha256"]
           and decoded["execution_parameter_sha256"] == provenance["model_sha256"], "legacy/execution verifier digests were mixed or changed")
    _check(len(sources) == len(set(sources)) == 8 and set(sources).isdisjoint(reader_sources)
           and provenance["training_source_groups"] == sources and provenance["synthetic_trained"] is False
           and provenance["original_training_reused_not_recharged"] is True, "independent verifier source/synthetic/reuse scope mismatch")
    for value in sources:
        _hash(value)
    recipe, fit = read(native / "design.json"), read(folder / "verifier-training.json")
    _check(recipe["verifier"]["counterfactual_train"] is False and fit["actual_intervention_exposures"] == 0
           and fit["model_sha256"] == decoded["training_parameter_sha256"], "original natural-only verifier recipe/fit differs")
    return dict(passed=True, seed=seed, provenance=provenance, decoded=decoded,
                source_groups=sources, historical_training_charged_again=False)


def audit_revision_fit(receipt, plan, natural, binding, core, *, expected_updates=256):
    _check(receipt["schema"] == "hepta.revision-paired-fit.v1" and receipt["status"] == "completed"
           and receipt["forced_candidates"] is False and receipt["final_evaluation_authorized"] is False
           and receipt["feedback_schema"] == "verifier_p0_p1_agreement_evidence_present.v1"
           and receipt["learning_rate"] == .001 and receipt["pair_weight"] == .5
           and receipt["depth_supervision"] == "last_hop_CE_plus_binding_pair", "revision training policy changed")
    _check(plan["updates"] == expected_updates and plan["batch_size"] == 16
           and plan["schema"] == "hepta.binding.continuation-plan.v1" and plan["seed"] == core["seed"]
           and plan["logical_update_order"] == ["natural", "binding"]
           and plan["plan_sha256"] == _digest({k: v for k, v in plan.items() if k != "plan_sha256"})
           and receipt["plan_sha256"] == plan["plan_sha256"], "revision plan hash/budget mismatch")
    rng = random.Random(f"hepta-binding-natural-v5/{plan['seed']}")
    batches = dict(natural=[rng.sample(range(len(natural)), 16) for _ in range(expected_updates)],
                   binding=_group_batches(binding, expected_updates, 16, plan["seed"]))
    for stream, rows in (("natural", natural), ("binding", binding)):
        _check(plan[stream + "_case_ids"] == [_id(r) for r in rows]
               and plan[stream + "_targets"] == [r["label"] for r in rows]
               and plan[stream + "_source_groups"] == [r["source_hash"] for r in rows]
               and plan[stream + "_batches"] == batches[stream], "revision plan differs from source rows/deterministic schedule")
    sources = set(core["training_source_groups"]) | {r["source_hash"] for r in natural + binding}
    provenance = receipt["verifier_provenance"]
    _check(receipt["initial_core_sha256"] == core["execution_parameter_sha256"]
           and receipt["initial_verifier_sha256"] == provenance["model_sha256"]
           and receipt["initial_models_equal"] is True and receipt["reader_training_source_groups"] == sorted(sources)
           and receipt["verifier_provenance_sha256"] == _digest(provenance), "revision core/verifier/source initial binding mismatch")
    _check(receipt["natural_sequence_sha256"] == _digest(batches["natural"])
           and receipt["binding_sequence_sha256"] == _digest(batches["binding"])
           and len(receipt["updates"]) == expected_updates * 2 and set(receipt["models"]) == {"real", "zero"}
           and receipt["requested_logical_updates"] == expected_updates and receipt["batch_size"] == 16,
           "revision sequence/update coverage mismatch")
    summaries = {arm: dict(completed_updates=0, natural_updates=0, binding_updates=0, natural_exposures=0,
        binding_exposures=0, feedback_nonzero_gradient_updates=0, feedback_nonzero_updates_by_column=[0] * 4,
        transitions={}, actual_calls={name: 0 for name in ("reader_prepare", "reader_step", "verifier_prepare", "verifier_step")})
        for arm in ("real", "zero")}
    current = {arm: core["execution_parameter_sha256"] for arm in summaries}
    nested = dict(cpu_ns=0, wall_ns=0)
    for position, paired in enumerate(receipt["updates"]):
        logical, stream = position // 2, "natural" if position % 2 == 0 else "binding"
        indices = batches[stream][logical]
        rows = [((natural if stream == "natural" else binding)[i]) for i in indices]
        ids = [_id(r) for r in rows]
        _check(paired["logical_step"] == logical + 1 and paired["stream"] == stream and paired["indices"] == indices
               and paired["sample_sha256"] == _digest(ids) and set(paired["arms"]) == {"real", "zero"}, "matched update sample/order mismatch")
        for arm, row in paired["arms"].items():
            _check(row["mode"] == arm and row["case_ids"] == ids and row["targets"] == [r["label"] for r in rows]
                   and row["initial_reader_sha256"] == current[arm]
                   and row["verifier_sha256"] == provenance["model_sha256"], "on-policy update/model chain mismatch")
            trace = audit_events(row["events"], row["verifier_observations"], rows, current[arm], provenance["model_sha256"], arm)
            _check(row["initial_predictions"] == trace["initial"] and row["final_predictions"] == trace["final"]
                   and row["transitions"] == transitions(trace["initial"], trace["final"], rows, training=True), "training correction/damage replay mismatch")
            forward = audit_calls(row["forward_cost"], arm, 16)
            cost = _cost(row)
            _check(all(cost[k] >= forward[k] for k in cost), "optimizer update omitted forward costs")
            for key in nested:
                nested[key] += cost[key]
            values = row["feedback_gradient_l2_by_column"]
            _check(len(values) == 4, "four feedback gradient columns required")
            for value in values:
                _number(value)
            norm = _number(row["feedback_column_gradient_l2"])
            _check(math.isclose(norm, math.sqrt(sum(v * v for v in values)), rel_tol=2e-5, abs_tol=1e-12)
                   and row["feedback_column_gradients_nonzero"] is (norm > 0), "feedback gradient norm/count mismatch")
            if arm == "zero":
                _check(norm == 0 and values == [0.] * 4, "zero control recorded trained feedback columns")
            _check(_number(row["parameter_gradient_l2"]) + 1e-8 >= norm
                   and len(row["hop_state_gradient_l2"]) == 3
                   and all(v is not None and _number(v) >= 0 for v in row["hop_state_gradient_l2"]), "recorded gradient path incomplete")
            weight = .5 if stream == "binding" else 0.
            ce, pair = _number(row["binary_cross_entropy"]), _number(row["pair_loss"])
            _check(row["pair_weight"] == weight and math.isclose(_number(row["loss"]), ce + weight * pair, rel_tol=1e-5, abs_tol=1e-6), "revision objective mismatch")
            summary = summaries[arm]
            for key in ("completed_updates", stream + "_updates"):
                summary[key] += 1
            summary[stream + "_exposures"] += 16
            summary["feedback_nonzero_gradient_updates"] += int(norm > 0)
            summary["feedback_nonzero_updates_by_column"] = [old + int(v > 0) for old, v in zip(summary["feedback_nonzero_updates_by_column"], values)]
            summary["transitions"] = {k: summary["transitions"].get(k, 0) + v for k, v in row["transitions"].items()}
            for key, value in row["forward_cost"]["calls"].items():
                summary["actual_calls"][key] += value
            current[arm] = _hash(row["updated_reader_sha256"])
        _check(paired["arms"]["real"]["input_feature_sha256s"] == paired["arms"]["zero"]["input_feature_sha256s"]
               and len(paired["arms"]["real"]["input_feature_sha256s"]) == 6, "matched arms used different/public-outcome tensor boundaries")
        for value in paired["arms"]["real"]["input_feature_sha256s"]:
            _hash(value)
    for arm, expected in summaries.items():
        final = receipt["models"][arm]
        _check(all(final[key] == value for key, value in expected.items()) and final["model_sha256"] == current[arm]
               == final["execution_parameter_sha256"] and final["frozen"] is True
               and final["parameter_count"] == core["parameter_count"]
               and final["parameter_bytes"] == core["parameter_count"] * 4, "final arm counters/typed digest/parameter bytes mismatch")
        _hash(final["training_parameter_sha256"])
    _check(summaries["real"]["feedback_nonzero_gradient_updates"] > 0
           and receipt["feedback_training_verified"] is True and receipt["original_core_unchanged"] is True
           and receipt["verifier_unchanged"] is True and receipt["identical_source_and_call_schedules"] is True
           and receipt["completed_logical_updates"] == expected_updates, "trained feedback/core freeze qualification failed")
    outer = _cost(receipt)
    _check(all(outer[k] >= nested[k] for k in outer) and receipt["formula_flops"] is None
           and receipt["nested_costs_additive"] is False, "shared fit outer accounting omitted/double-counted work")
    return dict(passed=True, plan_sha256=plan["plan_sha256"], models=summaries, outer_cost_once=outer,
                all_four_real_columns_received_nonzero_gradient=all(v > 0 for v in summaries["real"]["feedback_nonzero_updates_by_column"]),
                nested_update_costs_not_added=nested, recorded_gradients_independently_executed=False)


def expected_models():
    return {f"seed-{seed}/{arm}/{name}-model.json": arm for seed in SEEDS for arm in ("bridge", "wide")
            for name in (("warmup", "natural_only", "replay", "contrastive", "revision-real", "revision-zero") if arm == "bridge" else ("warmup",))}


def audit_freeze(run, parts):
    run, frozen = Path(run), read(Path(run) / "all-models-frozen.json")
    _check(set(frozen["manifests"]) == set(expected_models()), "exact 21-model freeze membership required")
    models = {}
    for name, arm in expected_models().items():
        _check(file_sha(run / name) == frozen["manifests"][name], "frozen selected manifest changed")
        models[name] = audit_manifest(run / name, expected_arm=arm)
        _check(models[name]["seed"] == int(Path(name).parts[0].split("-")[1]), "selected model seed differs from its frozen slot")
    gates = {"warmup-completion.json", "continuation-completion.json"} | {f"seed-{s}/bridge/retention-gates.json" for s in SEEDS}
    _check(set(frozen["gate_evidence_sha256"]) == gates, "complete gate file freeze required")
    for name, expected in frozen["gate_evidence_sha256"].items():
        _check(file_sha(run / name) == expected, "frozen gate evidence changed")
    warm, retained = [], []
    for seed in SEEDS:
        folder = run / f"seed-{seed}" / "bridge"
        for result, name in ((warm, "warmup"), (retained, "contrastive")):
            panel = read(folder / (name + "-binding-train.json"))
            audited = audit_panel(parts["reader_train"], panel, models[f"seed-{seed}/bridge/{name}-model.json"])
            result.append(dict(seed=seed, metrics=audited["metrics"]))
    _check(read(run / "warmup-completion.json")["primary_all_passed"] is True
           and read(run / "continuation-completion.json")["contrastive_all_passed"] is True,
           "reported primary learning/retention gate is closed")
    for before, after in zip(warm, retained):
        baseline, metrics = before["metrics"], after["metrics"]
        _check(baseline["cases"] == metrics["cases"] == 128 and baseline["groups"] == metrics["groups"] == 32
               and baseline["accuracy"] == baseline["both_worlds_correct"] == baseline["all_four_correct"] == 1.
               and baseline["probability_CE"] <= .10
               and all(metrics[k] + 1e-12 >= .95 and baseline[k] - metrics[k] <= .05 + 1e-12
                       for k in ("accuracy", "both_worlds_correct")), "independent primary fitting/retention gate failed")
        _check(read(run / f"seed-{before['seed']}/bridge/retention-gates.json")["contrastive"]["passed"] is True,
               "standalone contrastive retention gate is closed")
    _check(type(frozen["frozen_ns"]) is int and frozen["frozen_ns"] > 0
           and all(type(m["frozen_ns"]) is int and 0 < m["frozen_ns"] <= frozen["frozen_ns"] for m in models.values()),
           "global freeze predates selected model freezing")
    start_path = run / "evaluation-start.json"
    gate = dict(passed=True, model_freezes=21, fresh_started_ns=None)
    if start_path.exists():
        gate = audit_fresh_gate(warm, retained, list(models.values()), all_models_frozen_ns=frozen["frozen_ns"], fresh_started_ns=read(start_path)["started_ns"])
        _check(read(start_path)["all_models_frozen_sha256"] == file_sha(run / "all-models-frozen.json"), "fresh start freeze binding changed")
    return models, dict(passed=True, boundary=gate, fresh_started=start_path.exists(), frozen_ns=frozen["frozen_ns"])


def review(run, code, native, source, natural_cases, *, fresh=False):
    """Audit complete feedback artifacts only; no automatic final-data fallback."""
    run, code, native, source, natural_cases = map(Path, (run, code, native, source, natural_cases))
    design, parts = read(run / "design.json"), read(run / "all-cases.json")
    snapshots = {}

    def track(path):
        path = Path(path).resolve()
        snapshots[str(path)] = file_sha(path)

    def guard(path):
        track(path)
        return read(path)

    guard(run / "design.json")
    guard(run / "all-cases.json")
    audit_protocol(parts, design["membership"])
    for filename in ("bridge_feedback_review.py", "bridge_revision_review.py", "binding_review.py", "bridge_review.py"):
        track(Path(__file__).parent / filename)
    audit_source_inventory(code, design["runtime_source_sha256"])
    for name in design["runtime_source_sha256"]:
        snapshots[str((code / name).resolve())] = file_sha(code / name)
    previous = {Path(item["folder"]).parent for item in design["historical_baselines"].values()}
    _check(len(previous) == 1, "one historical V5 source required")
    previous = next(iter(previous))
    previous_design = guard(previous / "design.json")
    _check(file_sha(previous / "design.json") == design["previous_v5_design_sha256"], "previous V5 design binding changed")
    _check(len(previous_design["runtime_source_sha256"]) == 48
           and all(design["runtime_source_sha256"].get(k) == v for k, v in previous_design["runtime_source_sha256"].items()),
           "original 48-file runtime changed")
    for record in design["historical_baselines"].values():
        for name, expected in record["files_sha256"].items():
            path = Path(record["folder"]) / name
            track(path)
            _check(file_sha(path) == expected, "historical base selection changed")
        manifest = read(Path(record["folder"]) / "warmup-model.json")
        decoded = checkpoint_digests(Path(record["folder"]) / manifest["file"], BASE_SHAPES)
        _check(all(manifest[key] == decoded[key] for key in ("training_parameter_sha256", "execution_parameter_sha256", "parameter_count"))
               and manifest["frozen_ns"] < design["created_ns"]
               and record["reused_historical_training"] is True and record["newly_performed_training"] is False,
               "historical base checkpoint digests/time/reuse scope mismatch")
    material, provenance = guard(natural_cases), guard(natural_cases.parent / "material-provenance.json")
    _check(file_sha(natural_cases) == provenance["natural_cases_file_sha256"]
           and provenance["design_sha256"] == design["previous_v5_design_sha256"]
           and provenance["official_train_sha256"] == previous_design["train_file_sha256"]
           == file_sha(source / "train.jsonl"), "natural reference/source bytes provenance changed")
    track(source / "train.jsonl")
    official = {}
    for line in (source / "train.jsonl").read_text().splitlines():
        passage = json.loads(line)
        source_sha = sha256(passage["passage"]["text"].encode()).hexdigest()
        for question in passage["passage"]["questions"]:
            for answer in question["answers"]:
                official[_digest(["train", str(passage["idx"]), str(question["idx"]), str(answer["idx"])])] = (answer["label"], source_sha)
    natural = material["train"]
    _check([_id(r) for r in natural] == design["natural_case_ids"]["train"]
           and all(official[_digest(json.loads(_id(r)))] == (r["label"], r["source_hash"]) for r in natural), "natural training rows differ from official source")
    frozen = guard(run / "all-models-frozen.json")
    _check(frozen["runtime_source_sha256"] == design["runtime_source_sha256"], "global freeze runtime differs from design")
    for name in set(frozen["manifests"]) | set(frozen["gate_evidence_sha256"]):
        track(run / name)
    for name in expected_models():
        manifest = read(run / name)
        track((run / name).parent / manifest["file"])
        track((run / name).parent / manifest["training_receipt_file"])
    for seed in SEEDS:
        for name in ("warmup", "contrastive"):
            track(run / f"seed-{seed}" / "bridge" / (name + "-binding-train.json"))
    if (run / "evaluation-start.json").exists():
        track(run / "evaluation-start.json")
    models, freeze = audit_freeze(run, parts)
    fits, verifiers, selected, total = {}, {}, {}, dict(cpu_ns=0, wall_ns=0)
    for seed in SEEDS:
        folder = run / f"seed-{seed}" / "bridge"
        receipt, plan = guard(folder / "revision-pair-training.json"), guard(folder / "revision-plan.json")
        core = models[f"seed-{seed}/bridge/contrastive-model.json"]
        fit = audit_revision_fit(receipt, plan, natural, parts["reader_train"], core)
        for path in (native / "all-artifacts-frozen.json", native / "design.json",
                     native / f"seed-{seed}" / "artifacts.json", native / f"seed-{seed}" / "verifier-training.json",
                     native / f"seed-{seed}" / "verifier.pt"):
            track(path)
        verifier = audit_verifier(native, previous_design, seed, set(receipt["reader_training_source_groups"]), receipt["verifier_provenance"])
        for arm in ("real", "zero"):
            manifest = models[f"seed-{seed}/bridge/revision-{arm}-model.json"]
            wrapper = guard(folder / manifest["training_receipt_file"])
            _check(wrapper["shared_training_receipt"] == "revision-pair-training.json"
                   and wrapper["shared_receipt_sha256"] == file_sha(folder / "revision-pair-training.json")
                   and wrapper["model_receipt"] == receipt["models"][arm]
                   and manifest["initial_execution_parameter_sha256"] == core["execution_parameter_sha256"]
                   and manifest["execution_parameter_sha256"] == receipt["models"][arm]["execution_parameter_sha256"]
                   and manifest["training_parameter_sha256"] == receipt["models"][arm]["training_parameter_sha256"]
                   and manifest["training_source_groups"] == receipt["reader_training_source_groups"], "selected model wrapper/shared receipt/typed checkpoint mismatch")
            selected[seed, arm] = manifest
        fits[str(seed)], verifiers[seed] = fit, verifier["provenance"]
        for key in total:
            total[key] += fit["outer_cost_once"][key]
    result = dict(schema="hepta.bridge.feedback-review.v1", passed=True, fits=fits, freeze=freeze,
        shared_fit_costs_once=total, pure_stdlib=True, independent_neural_execution=False,
        checkpoint_tensor_digests_independently_reconstructed=True, fresh_audited=False)
    if fresh:
        _check(freeze["fresh_started"] and (run / "completion.json").is_file(), "complete fresh evaluation required")
        from bridge_revision_review import review_fresh
        completion = guard(run / "completion.json")
        _check(completion["source_sha256"] == design["runtime_source_sha256"]
               and completion["all_models_frozen_sha256"] == file_sha(run / "all-models-frozen.json"), "fresh completion source/freeze binding changed")
        result.update(fresh_audited=True, fresh=review_fresh(run, parts, selected, verifiers))
    _check(all(file_sha(path) == digest for path, digest in snapshots.items()), "audit inputs mutated")
    result["guarded_inputs_sha256"] = snapshots
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "code", "previous-native", "source", "natural-cases", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    report = review(args.run, args.code, args.previous_native, args.source, args.natural_cases, fresh=args.fresh)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
