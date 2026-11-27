"""Dedicated frozen Procedural replay export; no news-report impersonation.

Produces the existing native linear bundle framing with a derived manifest.
Its new provenance field is authenticated as bytes by the native manifest pin;
the native reader does NOT validate its source-closure or contract semantics.
No issuer, owner admission, live Encoder or execution authority is created here.
"""

import argparse
import json
from pathlib import Path

from procedure_native_format import canonical, feature_identity, frame_bundle, sha, source_records_digest
from procedure_native_validation import CLASSES, SEEDS, directory_reader, load_frozen_run


def build_envelopes(run):
    plan, result, encoder = run["plan"], run["result"], run["encoder"]
    indices = [index for index, query in enumerate(run["queries"]) if query["split"] == "heldout"]
    width = encoder["shape"][1]
    feature_bytes = b"".join(run["features"][index * width * 4:(index + 1) * width * 4] for index in indices)
    sources = [encoder["source_record_digests"][index] for index in indices]
    queries = [run["queries"][index] for index in indices]
    feature = feature_identity(encoder["feature_identity"], width)
    input_pins = {"feature_bytes_digest": sha(feature_bytes), "source_records_digest": source_records_digest(sources)}
    batch = {"schema": "hepta.procedural-native-input.v1", "identity": feature, "rows": len(indices),
             "features_file": "heldout.features.f32le", "feature_bytes": len(feature_bytes),
             "source_record_digests": sources, "query_ids": [query["query_id"] for query in queries],
             "input_pins": input_pins, "maximum_multiply_adds": len(indices) * width * 4,
             "source": "actual frozen Granite pooled outputs; no new Encoder execution during export",
             "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}
    source_policy = {"native_authenticates_complete_manifest_bytes": True,
        "native_validates_procedure_contract_semantics": False,
        "native_expands_or_revalidates_learning_ancestor_closure": False,
        "native_validates_current_query_source_authority": False,
        "requires_external_current_source_validation": True,
        "runtime_procedure_outcome_or_execution_authority": False,
        "new_host_owner_instances_require_independently_current_frontier": True}
    runtime = {"schema": "hepta.procedural-replay-recorded-runtime.v1",
               "execution_environment": plan["execution_environment"],
               "training_runtime": result["runtime"], "device": plan["encoder"]["device"],
               "preprocessing_digest": encoder["feature_identity"]["preprocess_sha256"]}
    output = {"heldout.features.f32le": feature_bytes,
              "heldout.batch.json": canonical(batch) + b"\n",
              "heldout.scorer.json": canonical({"schema": "hepta.procedural-native-scorer.v1",
                  "query_ids": batch["query_ids"], "class_order": CLASSES,
                  "observed_classes": [run["observed_labels"][query["query_id"]] for query in queries],
                  "purpose": "Read only after inference; never supplied as model input or routing features.",
                  "replay_sha256": run["replay_sha256"]}) + b"\n"}
    exported = {}
    for seed in SEEDS:
        head = run["heads"][seed]
        original = head["manifest"]
        provenance = {"schema": "hepta.procedural-replay-export-provenance.v1", "seed": seed,
            "plan_sha256": run["plan_sha256"], "result_sha256": run["result_sha256"],
            "original_manifest_sha256": sha(head["original_manifest"]),
            "original_replay_owner_sha256": sha(head["owner_bytes"]),
            "source_snapshot_sha256": run["source_snapshot_sha256"],
            "frozen_source_code_sha256": plan["source_code_sha256"],
            "replay_sha256": run["replay_sha256"], "encoder_manifest_sha256": run["encoder_manifest_sha256"],
            "class_order": CLASSES, "class_contracts": plan["contracts"],
            "task_target": "Select one of four fixed file programs; no program synthesis or action permission.",
            "complete_learning_ancestor_digests": run["learning_ancestor_digests"],
            "ancestor_count": len(run["learning_ancestor_digests"]),
            "query_feature_identity": encoder["feature_identity"],
            "query_source_records": [{"query": query, "feature_source_record_digest": source}
                                     for query, source in zip(queries, sources)],
            "query_batch_input_pins": input_pins, "query_batch_sha256": sha(output["heldout.batch.json"]),
            "source_validation_policy": source_policy,
            "actual_observer_boundary": "Separate reference code reread files; no independent runtime signer.",
            "quality": {"all_seeds_exceed_all_strong_baselines": result["all_seeds_exceed_all_strong_baselines"],
                        "evaluation": result["arms"][f"head_seed_{seed}"]["evaluation"],
                        "production_activation_allowed": False},
            "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}
        # Preserve every original JSON value and all original bytes in a separate
        # file. The new manifest digest intentionally differs from the old one.
        manifest = canonical({**original, "procedure_replay_provenance_v1": provenance}) + b"\n"
        datasets = head["datasets"]
        pins = {"manifest_digest": sha(manifest), "weights_digest": sha(head["weights"]),
                "source_frontier_digest": sha(canonical({"schema": "hepta.cell-head-input-frontier.v1",
                    "train": datasets["train"], "calibration": datasets["calibration"]})),
                "training_dataset_digest": datasets["train"], "calibration_dataset_digest": datasets["calibration"],
                "training_code_digest": sha(canonical(plan["source_code_sha256"])),
                "runtime_tuple_digest": sha(canonical(runtime)),
                "trained_tensor_digest": original["report"]["trained_tensor_sha256"]}
        bundle, retained = frame_bundle(manifest, head["weights"], feature, pins)
        retained.update(original_manifest_digest=sha(head["original_manifest"]),
            original_replay_owner_digest=sha(head["owner_bytes"]),
            procedure_provenance_digest=sha(canonical(provenance)),
            frozen_plan_digest=run["plan_sha256"], frozen_result_digest=run["result_sha256"],
            source_validation_policy=source_policy, production_activation_allowed=False,
            native_execution_performed=False, authority="DENY_ALL", mode="SHADOW_ONLY",
            recorded_runtime=runtime, verified_tensor_inventory=head["tensors"])
        retained["owner_manifest_requirements"] = {
            "kind": "Parameters", "provenance_mode": "DatasetDerived",
            "source_dataset_digests": sorted([datasets["train"], datasets["calibration"]]),
            "required_lineage_digests": sorted([pins["manifest_digest"], pins["trained_tensor_digest"],
                                                 pins["source_frontier_digest"]]),
            "note": "The existing native reader expects exactly two dataset digests. The 526-member "
                    "closure remains an explicitly external current-host validation obligation."}
        prefix = f"seed-{seed}/"
        output.update({prefix + "head.bundle": bundle, prefix + "manifest.json": manifest,
                       prefix + "original_manifest.json": head["original_manifest"],
                       prefix + "original_replay_owner.json": head["owner_bytes"],
                       prefix + "weights.npz": head["weights"],
                       prefix + "pins.json": canonical(retained) + b"\n"})
        exported[str(seed)] = {"artifact_digest": retained["artifact_digest"],
            "manifest_digest": pins["manifest_digest"], "original_manifest_digest": sha(head["original_manifest"]),
            "weights_digest": pins["weights_digest"], "bundle_bytes": len(bundle)}
    output["export_summary.json"] = canonical({"schema": "hepta.procedural-native-export.v1",
        "plan_sha256": run["plan_sha256"], "result_sha256": run["result_sha256"],
        "class_order": CLASSES, "ancestor_count": len(run["learning_ancestor_digests"]),
        "native_feature_rows": len(indices), "seeds": exported,
        "source_validation_policy": source_policy, "native_execution_performed": False,
        "artifact_owner_admission_performed": False, "authority": "DENY_ALL", "mode": "SHADOW_ONLY",
        "production_activation_allowed": False}) + b"\n"
    return output


def export(evidence, output, plan_sha256, result_sha256):
    run = load_frozen_run(directory_reader(evidence), plan_sha256, result_sha256)
    members = build_envelopes(run)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in members.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return json.loads(members["export_summary.json"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.evidence, args.output, args.expected_plan_sha256,
                            args.expected_result_sha256), sort_keys=True, indent=2))
