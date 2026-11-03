"""Independent bindings for fixed-budget skill fit records and saved tensors."""

import math

import numpy as np

from audit_skill_longrun_support import canonical, file_bytes, identity, load, sha


def fit_check(folder, previous_path, untrained_path, state, seed, stage, mode, context):
    paths, check, process_audit = context["paths"], context["check"], context["processes"]
    label = str(folder.relative_to(paths.run))
    process, request, response = process_audit.read(folder / "fit", "fit_worker.py")
    context["fit_records"].append((process, response))
    fields = {"mode", "checkpoint", "initial_checkpoint", "output", "canonical_features_path",
              "source_rows_path", "database", "encoder_sha", "seed", "stage", "protocol_path", "protocol_sha256"}
    check("fit_request_fields:" + label, set(request) == fields)
    check("fit_request_contract:" + label,
          request["mode"] == mode and request["seed"] == seed and request["stage"] == stage
          and request["encoder_sha"] == context["encoder_sha"]
          and request["protocol_sha256"] == context["protocol_sha"]
          and paths.resolve(request["checkpoint"]) == previous_path
          and paths.resolve(request["initial_checkpoint"]) == untrained_path
          and paths.resolve(request["output"]) == folder / "checkpoint"
          and paths.resolve(request["canonical_features_path"]) == paths.run / "inputs/canonical.npz"
          and paths.resolve(request["source_rows_path"]) == folder / "active-train-sources.json"
          and paths.resolve(request["database"]) == folder / "sources.sqlite"
          and paths.resolve(request["protocol_path"]) == context["protocol_path"])
    check("fit_response_contract:" + label,
          response["schema"] == "hepta.memory.adapter-skill-longrun-fit.v1"
          and response["kind"] == "skill" and response["seed"] == seed and response["stage"] == stage
          and response["mode"] == mode and response["protocol_sha256"] == context["protocol_sha"]
          and response["loaded_previous_parameters"] == (mode == "update")
          and not response["held_inputs_opened"] and not response["native_runtime_executed"])
    keys = ("kind", "index", "source_id", "version", "value")
    active = [{key: row[key] for key in keys} for row in state if row["active"]]
    indexes, ids = [row["index"] for row in active], [row["source_id"] for row in active]
    check("all_and_only_active_replay:" + label,
          load(folder / "active-train-sources.json") == active
          and response["active_source_ids"] == sorted(ids)
          and response["source_rows_sha256"] == identity(folder / "active-train-sources.json")["sha256"]
          and response["source_database"] == identity(folder / "sources.sqlite")
          and response["canonical_features"] == context["feature_identity"])
    training = response["training"]
    check("fixed_fit_budget:" + label,
          training["schema"] == "memory-adapter.training.v1"
          and (training["steps"], training["batch_size"], training["lr"], training["updated_head"],
               training["seed"], training["sample_presentations"])
          == (600, 32, 0.01, True, seed + stage, 19200)
          and training["diagnostic_forward_rows"] == 2 * len(active)
          and training["available_rows"] == training["unique_rows_seen"] == len(active))
    targets = {f"op{index}": sha(np.asarray([row["value"][index] for row in active], dtype="<i8").tobytes())
               for index in range(4)}
    check("fit_feature_target_source_binding:" + label,
          training["features_sha256"] == sha(context["features"]["skill"][indexes].astype("<f4").tobytes())
          and training["targets_sha256"] == targets and training["source_ids_sha256"] == sha(canonical(ids)))
    counts = {"adapter": 3072, "head": 10780, "total": 13852, "trainable": 13852}
    check("fit_parameter_budget:" + label, training["parameter_counts"] == response["parameter_counts"] == counts)
    check("fit_finite_optimization:" + label,
          all(math.isfinite(training[name]) and training[name] >= 0 for name in ("initial_loss", "final_loss", "wall_seconds", "cpu_seconds"))
          and set(training["max_gradient_norm"]) == {"A", "B", "head.weight", "head.bias"}
          and all(math.isfinite(value) and value > 0 for value in training["max_gradient_norm"].values()))
    schedule = response["sample_schedule"]
    schedule_path = paths.resolve(schedule["path"])
    check("sample_schedule_identity:" + label,
          schedule_path == folder / "sample-schedule.i64"
          and identity(schedule_path) == {key: schedule[key] for key in ("bytes", "sha256")}
          and schedule["sha256"] == training["sample_schedule_sha256"]
          and schedule["bytes"] == 600 * 32 * 8 and schedule["dtype"] == "<i8" and schedule["shape"] == [600, 32])
    sampled = np.frombuffer(schedule_path.read_bytes(), dtype="<i8")
    check("sample_schedule_index_bounds:" + label, sampled.size == 19200
          and sampled.min() >= 0 and sampled.max() < len(active) and set(sampled.tolist()) == set(range(len(active))))
    previous, untrained = context["manifests"][str(previous_path)], context["manifests"][str(untrained_path)]
    expected_start = previous["parameter_sha256"] if mode == "update" else untrained["parameter_sha256"]
    manifest = context["decode_checkpoint"](folder / "checkpoint")
    check("parameter_continuity_or_clean_rebuild:" + label,
          training["initial_parameter_sha256"] == expected_start
          and response["initial_architecture_parameter_sha256"] == untrained["parameter_sha256"]
          and training["final_parameter_sha256"] == response["parameter_sha256"] == manifest["parameter_sha256"]
          and training["initial_parameter_sha256"] != training["final_parameter_sha256"]
          and manifest["source_ids"] == sorted(ids) and manifest["config"]["seed"] == seed)
    expected_history = [*previous["training_history"], training] if mode == "update" else [training]
    check("training_history_chain:" + label, manifest["training_history"] == expected_history)
    check("checkpoint_save_receipt:" + label,
          response["checkpoint"] == {"parameter_sha256": manifest["parameter_sha256"],
              "manifest_sha256": identity(folder / "checkpoint/manifest.json")["sha256"],
              "stored_bytes": file_bytes(folder / "checkpoint")})
    return process, response, manifest
