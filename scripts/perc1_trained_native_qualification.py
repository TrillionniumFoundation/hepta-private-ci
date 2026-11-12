"""Cold-reconstruct one already-used TRAIN actor prefix; no labels or efficacy test."""

import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from perc1 import acquisition, cord_task
from perc1.capture_entry import decode_native_wire
from perc1.owner import Owner
from perc1.schema import canonical, require, sha
from perc1.source_feature_profile import bind_head, observed_prefix
from perc1.source_entry import operator_source_config
import perc1_trained_native
from perc1_trained_native import envelope


def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter_ns()
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    actor_done_raw = (args.pilot / "ACTOR_DONE.json").read_bytes()
    actor_done = json.loads(actor_done_raw)
    frozen = {
        name: (args.pilot / name).read_bytes()
        for name in ("PLAN.json", "HEAD.json", "PROFILE.json", "PAIRS.json")
    }
    for name, key in (
        ("PLAN.json", "plan"),
        ("HEAD.json", "head"),
        ("PROFILE.json", "profile"),
        ("PAIRS.json", "pairs"),
    ):
        require(
            sha(frozen[name]) == actor_done[key + "_file_sha256"],
            "pilot artifact differs from frozen actor completion",
        )
    plan = json.loads(frozen["PLAN.json"])
    source_dir = Path(cord_task.__file__).parent
    code_paths = {name: source_dir / name for name in plan["source_pins"]}
    require(
        all(
            sha(path.read_bytes()) == plan["source_pins"][name]
            for name, path in code_paths.items()
        ),
        "pilot source differs from frozen plan",
    )
    code_paths.update(
        driver=Path(__file__), exporter=Path(perc1_trained_native.__file__)
    )
    code_pins = {name: sha(path.read_bytes()) for name, path in code_paths.items()}
    binary_sha256 = sha(args.binary.read_bytes())
    source_id = "cord-v2-train-00000"
    task_raw = (args.pilot / "tasks" / source_id / "TASK.json").read_bytes()
    task = json.loads(task_raw)
    require(
        task["split"] == "train", "native qualification requires reused TRAIN source"
    )
    original = (args.pilot / "tasks" / source_id / "original.image").read_bytes()
    require(sha(original) == task["image_sha256"], "original training image changed")
    head_raw = frozen["HEAD.json"]
    head = json.loads(head_raw)
    profile = json.loads(frozen["PROFILE.json"])
    bind_head(profile, head)
    config, _, binding = operator_source_config(
        args.pilot / (source_id + "-config.json")
    )
    require(
        task["sources"] == config["sources"] and task["model"] == config["model"],
        "public task differs from original source owner catalog",
    )
    with Owner(config["state_dir"], binding, config["budget_units"]) as owner:
        receipt = owner.receipt("initial")
        wire = decode_native_wire(receipt["result"], source_root=owner.root)
        prefix = observed_prefix(owner, task["task_sha256"], ["initial"], profile)
        candidates = cord_task.candidates(task, prefix, cord_task.text(owner, receipt))
        source_evidence = receipt["result"]["source_evidence"]
        require(
            source_evidence["artifacts"]["document"]["sha256"] == sha(original),
            "retained capture does not bind the checked original document",
        )
    # Deliberately project only public features; no score/target/confirmation labels are used.
    pair_features = {
        row["candidate_id"]: row["features"]
        for row in json.loads(frozen["PAIRS.json"])
        if row["split"] == "train" and row["source_group"] == source_id
    }
    require(
        set(pair_features) == {c["id"] for c in candidates},
        "retained TRAIN candidate inventory changed",
    )
    require(
        all(c["features"] == pair_features[c["id"]] for c in candidates),
        "wire/profile reconstruction differs from recorded TRAIN features",
    )
    bindings = dict(
        feature_extractor_sha256=head["training_receipt"]["feature_extractor_sha256"],
        feature_profile_sha256=sha(profile),
        original_image_sha256=sha(original),
        producer_wire_sha256=sha(wire),
        latent_receipt_sha256=receipt["receipt_sha256"],
        source_evidence_sha256=sha(source_evidence),
        source_manifest_sha256=sha(task_raw),
        projection_sha256=profile["projection_sha256"],
        observed_prefix_sha256=sha(prefix),
        source_owner_binding_sha256=sha(binding),
        pilot_actor_done_sha256=sha(actor_done_raw),
        pilot_plan_sha256=sha(frozen["PLAN.json"]),
        native_binary_sha256=binary_sha256,
        native_export_driver_sha256=code_pins["driver"],
    )
    exported = envelope(head_raw, candidates, bindings)
    with (root / "head.json").open("xb") as stream:
        stream.write(head_raw)
    write(root / "features.json", exported)
    provenance = dict(
        schema="perc1.cord-native-export.v1",
        source_id=source_id,
        split="train",
        source_bindings=bindings,
        feature_rows_sha256=exported["feature_rows_sha256"],
        carrier_digest=exported["carrier_digest"],
        candidate_ids=exported["candidate_ids"],
        head_raw_sha256=sha(head_raw),
        head_canonical_sha256=sha(head),
        actor_features_reconstructed_from_cold_owner_and_profile=True,
        every_exported_row_equals_retained_train_pair=True,
        original_source_bytes_and_wire_verified=True,
        confirmation_labels_opened=False,
        pilot_plan_and_completion_artifacts_verified=True,
        driver_and_dependency_sha256=code_pins,
        scientific_qualified=False,
        fresh_independent_confirmation_tasks=0,
        source_scope="previously used, pre-plan exposed TRAIN row 0; this is numeric/durability verification",
    )
    write(root / "PROVENANCE.json", provenance)
    calls = []

    def invoke(mode, owner_name, output_name):
        command = [str(args.binary), mode, str(root / owner_name)]
        if mode != "read":
            command += [str(root / "features.json"), str(root / "head.json")]
        command.append(str(root / output_name))
        before = time.perf_counter_ns()
        result = subprocess.run(command, capture_output=True, timeout=30)
        wall = time.perf_counter_ns() - before
        for stream in ("stdout", "stderr"):
            with (root / (output_name + "." + stream + ".log")).open("xb") as opened:
                opened.write(getattr(result, stream))
        calls.append(
            dict(
                mode=mode,
                returncode=result.returncode,
                wall_ns=wall,
                stdout_sha256=sha(result.stdout),
                stderr_sha256=sha(result.stderr),
            )
        )
        require(
            result.returncode == 0,
            "native command failed: " + result.stderr.decode(errors="replace"),
        )
        return json.loads((root / output_name).read_bytes())

    first = invoke("start", "normal-owner", "START.json")
    cold = invoke("read", "normal-owner", "COLD.json")
    pending = invoke("lose-ack", "lost-owner", "LOST_ACK.json")
    recovered = invoke("read", "lost-owner", "RECOVERED.json")
    replayed = invoke("read", "lost-owner", "REPLAYED.json")
    p = head["parameters"]
    x = (np.asarray(exported["rows"], dtype=np.float64) - head["means"]) / head[
        "scales"
    ]
    expected = (
        np.tanh(x @ p["w1"] + p["b1"]) @ p["w2"] + p["b2"] + head["calibration"]["bias"]
    )
    actual = np.asarray(first["raw_outputs_f64"])
    np.testing.assert_allclose(actual, expected, rtol=5e-12, atol=5e-12)
    choice = acquisition.choose(
        head, [{k: c[k] for k in ("id", "features", "upper_cost")} for c in candidates]
    )
    expected_choice = choice["candidate_id"] or "abstain"
    require(
        first["decision"]["selected_candidate"]
        == first["native_fp64_selected_candidate"]
        == expected_choice,
        "native Cell selection differs from frozen Python acquisition policy",
    )
    require(
        first["decision"] == cold["decision"]
        and first["raw_bits_u64"] == cold["raw_bits_u64"],
        "committed cold read changed",
    )
    require(
        pending["raw_bits_u64"]
        == recovered["raw_bits_u64"]
        == replayed["raw_bits_u64"],
        "original pending inference changed",
    )
    require(
        recovered["decision"] == replayed["decision"],
        "recovered committed decision changed on cold replay",
    )
    require(
        [
            v["trained_head_inference_executions"]
            for v in (first, cold, pending, recovered, replayed)
        ]
        == [1, 0, 1, 0, 0],
        "native execution count changed",
    )
    require(
        [v["inference_readbacks"] for v in (first, cold, pending, recovered, replayed)]
        == [0, 0, 0, 1, 0],
        "native readback count changed",
    )
    require(
        sha(args.binary.read_bytes()) == binary_sha256
        and all(
            sha(path.read_bytes()) == code_pins[name]
            for name, path in code_paths.items()
        ),
        "native binary/driver/dependency changed during qualification",
    )
    require(
        all((args.pilot / name).read_bytes() == raw for name, raw in frozen.items())
        and (args.pilot / "ACTOR_DONE.json").read_bytes() == actor_done_raw,
        "pilot artifacts changed during qualification",
    )
    report = dict(
        schema="perc1.cord-trained-native-qualification.v1",
        status="PASS_TRAIN_NUMERIC_AND_DURABILITY_ONLY",
        scientific_status="HOLD",
        authority_granted=False,
        production_daemon_integrated=False,
        parameter_v3_exercised=False,
        native_controlled_original_pilot_actor=False,
        source_id=source_id,
        source_split="train",
        candidate_rows=len(candidates),
        feature_width=len(exported["rows"][0]),
        carrier_scalars=len(first["carrier_q24"]),
        head_sha256=sha(head_raw),
        provenance_sha256=sha((root / "PROVENANCE.json").read_bytes()),
        native_binary_sha256=binary_sha256,
        original_libraries_ref="a5583f0f4a12d9618a3a5bc5ed0e7062a7463f39",
        max_raw_output_absolute_error=float(np.max(np.abs(actual - expected))),
        python_and_native_selected_candidate=expected_choice,
        actual_native_mlp_executions=2,
        original_pending_readbacks=1,
        cold_replays=2,
        fresh_independent_confirmation_tasks=0,
        output_adapter=first["output_adapter"],
        feature_codec=first["native_feature_codec"],
        producer_wire_and_profile_reconstruction_verified=True,
        calls=calls,
        driver_wall_ns=time.perf_counter_ns() - started,
        cost_scope="inclusive driver and individual subprocess wall; nested model timings are not additive; no energy/provider/RSS claim",
        terminal_task_net_benefit_established=False,
    )
    write(root / "REPORT.json", report)
    print(canonical(report).decode())


if __name__ == "__main__":
    main()
