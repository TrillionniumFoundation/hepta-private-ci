"""Reopen every prospective selected output and independently audit its decision.

This verifier never calls the primary evaluator, runtime selector or generator.
All recorded native events are replayed; both frozen observers rescore actual
ZIP-member bytes. Statistics are separately recomputed by primary_results_audit.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import time
import zipfile

import numpy as np
import torch

from ..field_bridge_20261027.audit import reconstruct_features
from ..field_bridge_20261027.task import ACTIONS
from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from ..v6.observer import observe_tensors
from ..field_bridge_v2_20261027.learning import make_model
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge
from ..field_bridge_v2_20261027.primary_common import P, source_freeze, setup_primary, load_checkpoint
from .primary_audit_support import (require, file_sha, object_sha, matrix_sha, read_cas,
    transformed_inputs, runtime_features, actions_from_features, native_records)


def json_load(path):
    return json.loads(path.read_text())


def verify_resources(group, control):
    size, resource = len(group), group[0]["resources"]
    require(all(row["resources"] == resource for row in group), "Batch resource allocation differs")
    require(all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in resource.values()),
            "Nonfinite or negative deployment resource counter")
    actions = [row["action"] for row in group]
    expected = {"prepare_encoder_examples": 1, "prepare_encoder_batches": 1/size,
        "prepare_transition_examples": 1, "prepare_transition_batches": 1/size,
        "prepare_decoder_examples": 2, "prepare_decoder_batches": 2/size,
        "prepare_observer_digit_examples": 4, "prepare_observer_batches": 4/size,
        "prepare_target_accesses": 0, "finish_target_accesses": 0,
        "finish_unchosen_continuations_executed": 0, "finish_encoder_examples": 0,
        "finish_encoder_batches": 0, "finish_transition_examples": sum(a != 0 for a in actions)/size,
        "finish_transition_batches": len({a for a in actions if a != 0})/size,
        "finish_decoder_examples": 1, "finish_decoder_batches": 1/size,
        "finish_observer_digit_examples": 0, "finish_observer_batches": 0,
        "finish_decision_json_writes": 1, "native_tick_calls": 2 if control in {"native", "reset"} else 0}
    for phase, count in (("prepare", 2), ("finish", 1)):
        expected.update({f"{phase}_{key}": count for key in ("png_reads", "png_writes", "utf8_reads", "utf8_writes")})
    require(all(resource[key] == value for key, value in expected.items()), "Selected-only operation accounting differs")


def verify_decision(row, features, index):
    receipts, decision = row["artifacts"], row["decision"]
    raw = row["decision_bytes_utf8"].encode("utf-8")
    require(hashlib.sha256(raw).hexdigest() == row["decision_sha256"] and json.loads(raw) == decision,
            "Original committed decision bytes differ")
    require(decision["case_id"] == f"pair-{row['pair']:04d}" and decision["action"] == ACTIONS[row["action"]]
            and decision["model_sha256"] == row["model_sha"], "Committed decision identity differs")
    expected = hashlib.sha256(np.stack([value[index] for value in features]).astype("<f4", copy=False).tobytes()).hexdigest()
    require(decision["public_features_sha256"] == expected and
            decision["preview_sha256"] == [r["sha256"] for r in receipts[:2]] and
            decision["preview_logits_sha256"] == [r["public_text_logits_sha256"] for r in receipts[:2]],
            "Decision preview or public-feature binding differs")
    times = [receipts[0]["readback_monotonic_ns"], receipts[0]["evidence_monotonic_ns"],
             receipts[1]["readback_monotonic_ns"], receipts[1]["evidence_monotonic_ns"],
             decision["committed_monotonic_ns"], receipts[2]["readback_monotonic_ns"]]
    require(all(type(v) is int and v > 0 for v in times) and
            all(left < right for left, right in zip(times, times[1:])), "Preview/decision/final chronology differs")


def verify_selection(group, readout, control, action, features, native_stream, bridge, source_pin):
    size = len(group)
    require(all(row["native_batch_summary"] is None for row in group[1:]), "Duplicated native batch summary")
    summary = group[0]["native_batch_summary"]
    if control == "fixed":
        require(summary == {} and all(row["native_receipt_case"] is None for row in group),
                "Fixed policy carries a native receipt")
        expected = np.full(size, action)
    else:
        require(readout["authority"] == "DENY_ALL" and readout["native_owner_integration"] is False,
                "Controller authority differs")
        u0, u1 = transformed_inputs(readout, *features)
        native = None
        if control in {"native", "reset"}:
            first = group[0]
            prefix = f"{first['seed']}-{first['arm']}-{first['split']}-{first['corruption']}-{first['batch_start']}"
            records = [json.loads(next(native_stream)) for _ in range(size)]
            require([row["native_receipt_case"] for row in group] ==
                    [f"{prefix}:{index:08d}" for index in range(size)], "Native case linkage differs")
            require(readout["native_library_sha256"] == bridge.binary_sha256, "Controller native library differs")
            native = native_records(records, u0, u1, prefix, control == "reset", bridge,
                                    summary["native_batch_receipt"], source_pin)
            for key in ("native_ns", "bridge_roundtrip_ns", "ffi_run_ns", "original_sparse_tick_calls"):
                require(summary[key] == summary["native_batch_receipt"][key], "Native nested cost receipt differs")
            require(group[0]["resources"]["native_kernel_ns"] == summary["native_ns"]/size,
                    "Allocated kernel resource differs")
        else:
            require(control == "history" and all(row["native_receipt_case"] is None for row in group)
                    and summary["original_sparse_tick_calls"] == 0, "History control used native events")
        representation = runtime_features(readout, *features, native=native)
        expected = actions_from_features(readout, representation)
        require(summary["schema"] == "hepta.field-bridge-v2.primary-runtime-selection.v1" and
                summary["rows"] == size and summary["representation"] == readout["representation"] and
                summary["family"] == readout["family"] and summary["controller_sha256"] == object_sha(readout),
                "Runtime selection identity differs")
        require(summary["raw_history_sha256"] == matrix_sha(np.column_stack(features)) and
                summary["transformed_history_sha256"] == matrix_sha(np.column_stack((u0, u1))) and
                summary["feature_matrix_sha256"] == matrix_sha(representation) and
                summary["action_indices"] == expected.tolist(), "Complete runtime feature/action reconstruction differs")
        require(summary["reset_before_readout"] == (control == "reset") and
                summary["raw_history_preserved"] == readout["family"].startswith("raw16_") and
                summary["target_accesses"] == 0 and summary["authority"] == "DENY_ALL" and
                summary["native_owner_integration"] is False, "Runtime selection information boundary differs")
    require(expected.tolist() == [row["action"] for row in group], "Frozen policy action reproduction differs")


def verify_group(group, archive, referenced, native_stream, bridge, corpus, observers, frozen, model_hashes, report, ledger):
    first = group[0]
    seed, arm, split, condition, start = (first[k] for k in ("seed", "arm", "split", "corruption", "batch_start"))
    arms = {**P["canonical_arms"], **P["supplementary_arms"]}
    require(seed in P["seeds"] and arm in arms and split in {"test", "retention"}
            and condition in P[split+"_conditions"], "Unregistered evaluation batch")
    ci = P[split+"_conditions"].index(condition)
    size = min(P["evaluation_batch_size"], P[split+"_pairs"]-start)
    require(type(start) is int and 0 <= start < P[split+"_pairs"] and start % P["evaluation_batch_size"] == 0
            and len(group) == size, "Evaluation batch coverage differs")
    batch_seed, noise_seed = 271027+start+ci*10000, seed*100003+start+ci*1009
    batch = make_batch(corpus, split, size, batch_seed, offset=P[split+"_offset"]+start, corruption=condition)
    info, (profile, control) = frozen["seeds"][str(seed)], arms[arm]
    readout = None if control == "fixed" else info["readouts"][profile]["native" if control == "reset" else control]
    controller_sha = object_sha({"action": info["fixed_action"]} if readout is None else readout)
    features = [np.array([row[f"public_features{stage}"] for row in group], dtype=np.float32) for stage in (0, 1)]
    require(all(x.shape == (size, 8) and np.isfinite(x).all() and np.all((x >= 0) & (x <= 1)) for x in features),
            "Public feature dimensions or bounds differ")
    media = [[], [], []]
    for index, row in enumerate(group):
        require((row["pair"], row["batch_size"], row["batch_seed"], row["noise_seed"]) ==
                (start+index, size, batch_seed, noise_seed), "Episode RNG/offset identity differs")
        require(row["source_ids"] == list(batch.source_ids[index]) and
                row["private_labels_after_decision"] == batch.target.labels[index].tolist(), "Target source reconstruction differs")
        require(row["model_sha"] == model_hashes[f"{seed}-{profile}"] and row["controller_sha"] == controller_sha,
                "Deployed model/controller identity differs")
        require(type(row["action"]) is int and 0 <= row["action"] < 5 and
                row["refinement_count"] == 1+(row["action"] != 0), "Actual action/refinement charge differs")
        require(len(row["artifacts"]) == 3, "Missing media phase")
        for stage, phase in enumerate(("preview0", "preview1", "final")):
            receipt = row["artifacts"][stage]
            require(receipt["phase"] == phase and receipt["case_id"] == f"pair-{row['pair']:04d}",
                    "Media case/phase binding differs")
            actual = read_cas(archive, receipt, referenced)
            media[stage].append(actual)
            ledger.update(json.dumps([seed, arm, split, condition, row["pair"], phase, receipt["paths"], actual[2]],
                                     sort_keys=True).encode())
        verify_decision(row, features, index)
        ledger.update(row["decision_sha256"].encode())
    require(max(row["decision"]["committed_monotonic_ns"] for row in group) <
            min(row["artifacts"][2]["readback_monotonic_ns"] for row in group), "Final output preceded a batch choice")
    verify_resources(group, control)
    for stage in (0, 1):
        reconstructed = reconstruct_features(observers["reward"], batch.observation, media[stage],
                                             [row["artifacts"][stage] for row in group])
        report["feature_max_discrepancy"] = max(report["feature_max_discrepancy"],
                                               float(np.max(np.abs(reconstructed-features[stage]))))
    verify_selection(group, readout, control, info["fixed_action"], features, native_stream, bridge, P["source_base"])
    pixels, captions = torch.cat([m[0] for m in media[2]]), [m[1] for m in media[2]]
    for name, observer in observers.items():
        scores = observe_tensors(observer, pixels, captions, batch.target.pixels, batch.target.labels)
        for row, score in zip(group, scores, strict=True):
            require(row[name].keys() == score.keys(), "Score component inventory differs")
            for component, value in score.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    require(math.isfinite(row[name][component]), "Recorded score is nonfinite")
                    key = name+"."+component
                    report["score_max_discrepancy"][key] = max(report["score_max_discrepancy"].get(key, 0.),
                                                             abs(value-row[name][component]))
                else:
                    require(value == row[name][component], f"Categorical score differs: {name}.{component}")
    require(report["feature_max_discrepancy"] <= 1e-7 and max(report["score_max_discrepancy"].values()) <= 1e-7,
            "Delivered-output reconstruction tolerance exceeded")
    report["rows"] += size
    report["batches"] += 1
    return seed, arm, split, condition, start


def audit(args):
    root, started = args.run.resolve(), time.perf_counter_ns()
    frozen, done = json_load(root/"PRETEST_FREEZE.json"), json_load(root/"EVALUATION_COMPLETE.json")
    evaluation_subdirectory = done.get("evaluation_subdirectory", "eval")
    require(evaluation_subdirectory in {"eval", "eval_recovered"}, "Unregistered evaluation storage directory")
    sources, freeze_sha = source_freeze(), file_sha(root/"PRETEST_FREEZE.json")
    require(frozen["source_files"] == done["source_files"] == sources and
            done["pretest_freeze_sha256"] == freeze_sha and frozen["protocol_sha256"] == object_sha(P),
            "Primary source/protocol/pretest identity changed")
    require(frozen["test_retention_scored"] is False and frozen["audit_observer_used_for_selection"] is False,
            "Primary pretest fitting boundary differs")
    files = [root/"TRAINING_COMPLETE.json"] + [p for name in ("training", "runtime")
            for p in (root/name).rglob("*") if p.is_file()]
    require({str(p.relative_to(root)): file_sha(p) for p in sorted(files)} == frozen["files_sha256"],
            "Frozen training/runtime file inventory or identity changed")
    require(file_sha(root/"RESULT.json") == done["result_sha256"], "Primary result identity changed")
    corpus, observers, originals, identities = setup_primary(args, audit=True)
    require(set(observers) == {"reward", "audit"}, "Both independent observers are required")
    report = {"schema": "hepta.field-bridge.v2.primary-independent-media-audit.1", "passed": False,
        "rows": 0, "batches": 0, "feature_max_discrepancy": 0., "score_max_discrepancy": {},
        "model_hashes": {}, "archive_sha256": {}, "seed_completions_sha256": {},
        "unique_media_entries": 0, "unique_payload_bytes": 0, "source_files": sources,
        "pretest_freeze_sha256": freeze_sha, "audit_source_sha256": file_sha(Path(__file__)),
        "evaluation_subdirectory": evaluation_subdirectory,
        "audit_support_sha256": file_sha(Path(__file__).with_name("primary_audit_support.py")),
        "observer_parameter_sha256": {name: parameter_hash(observer) for name, observer in observers.items()},
        "original_model_identities": identities, "corpus_manifest": corpus.manifest}
    for seed in P["seeds"]:
        info = frozen["seeds"][str(seed)]
        require(info["original_identity"] == identities[seed], "Original model source identity differs")
        for profile in ("frozen", "ordinary", "field", "generic", "richer"):
            if profile == "frozen":
                model = make_model(originals[seed], seed, info["recipe"])
            else:
                receipt = info["profiles"][profile]
                path = root/receipt["checkpoint"]
                require(file_sha(path) == receipt["checkpoint_sha256"], "Frozen final model file differs")
                model, _, record = load_checkpoint(path, originals[seed], seed, info["recipe"])
                require(record["local_sha256"] == receipt["local_sha256"] and
                        record["optimizer_sha256"] == receipt["optimizer_sha256"], "Frozen complete training state differs")
            report["model_hashes"][f"{seed}-{profile}"] = parameter_hash(model)
    seen, ledger = set(), hashlib.sha256()
    group_key = lambda row: tuple(row[k] for k in ("seed", "arm", "split", "corruption", "batch_start"))
    with NativeFastBridge(args.native, frozen["native_library_sha256"]) as bridge:
        require(bridge.binary_sha256 == P["native_library_sha256"], "Registered native library differs")
        for seed in P["seeds"]:
            location, referenced = root/evaluation_subdirectory/str(seed), set()
            complete = json_load(location/"COMPLETE.json")
            require(complete == done["seeds"][str(seed)] and complete["seed"] == seed and
                    complete["source_files"] == sources and complete["pretest_freeze_sha256"] == freeze_sha
                    and complete["source_models_unchanged"] is True, "Seed evaluation completion differs")
            require(set(complete["files_sha256"]) == {"rows.jsonl.gz", "native.jsonl.gz", "media.zip"},
                    "Evaluation evidence inventory differs")
            for name, identity in complete["files_sha256"].items():
                require(file_sha(location/name) == identity, "Completed evaluation evidence changed")
            report["archive_sha256"][str(seed)] = complete["files_sha256"]["media.zip"]
            report["seed_completions_sha256"][str(seed)] = file_sha(location/"COMPLETE.json")
            before = report["rows"]
            with zipfile.ZipFile(location/"media.zip") as archive, gzip.open(location/"rows.jsonl.gz", "rt") as stream, \
                    gzip.open(location/"native.jsonl.gz", "rt") as native_stream:
                names = archive.namelist()
                require(len(names) == len(set(names)), "Duplicate ZIP members make byte identity ambiguous")
                rows = (json.loads(line) for line in stream)
                for key, group in itertools.groupby(rows, key=group_key):
                    require(key not in seen and key[0] == seed, "Duplicate or cross-seed batch")
                    seen.add(key)
                    verify_group(list(group), archive, referenced, native_stream, bridge, corpus, observers,
                                 frozen, report["model_hashes"], report, ledger)
                require(next(native_stream, None) is None, "Unconsumed native receipt or extra native action")
                require(referenced == set(names), "Unreferenced or missing content-addressed media")
                count, payload = len(names), sum(entry.file_size for entry in archive.infolist())
            expected_media = {"logical_files": 6*complete["rows"], "unique_files": count,
                              "unique_payload_bytes": payload, "schema": "hepta.field-bridge.v2.media-store.1",
                              "archive": "media.zip"}
            require(report["rows"]-before == complete["rows"] and
                    all(complete["media"][key] == value for key, value in expected_media.items()),
                    "Media deduplication or row accounting differs")
            report["unique_media_entries"] += count
            report["unique_payload_bytes"] += payload
            print(f"Independent media audit seed={seed} rows={report['rows']-before} passed", flush=True)
        report["native_replayed_ticks"] = 2*bridge.request_count
    expected = {(seed, arm, split, condition, start) for seed in P["seeds"]
                for arm in {**P["canonical_arms"], **P["supplementary_arms"]} for split in ("test", "retention")
                for condition in P[split+"_conditions"] for start in range(0, P[split+"_pairs"], P["evaluation_batch_size"])}
    require(seen == expected and report["rows"] == done["rows"] == P["expected_selected_output_rows"],
            "Incomplete prospectively registered eleven-arm cohort")
    require(report["native_replayed_ticks"] == 61440, "Native event coverage differs")
    require(report["feature_max_discrepancy"] <= 1e-7 and max(report["score_max_discrepancy"].values()) <= 1e-7,
            "Delivered-output reconstruction tolerance exceeded")
    require(source_freeze() == sources and file_sha(root/"PRETEST_FREEZE.json") == freeze_sha,
            "Frozen input changed during independent audit")
    report.update(passed=True, logical_media_files=6*report["rows"], decisions=report["rows"],
        independently_rescored_rows=2*report["rows"], observer_digit_examples=8*report["rows"],
        generator_forward_calls=0, native_library_sha256=bridge.binary_sha256,
        media_decision_ledger_sha256=ledger.hexdigest(), numeric_tolerance=1e-7,
        audit_wall_ns=time.perf_counter_ns()-started,
        limitations=["Same-host chronology and hashes are not independent external execution attestation.",
                     "Generator identities are checked; generation is not rerun or counterfactualized.",
                     "Native replay verifies the complete recorded public-input path, not production ownership.",
                     "Statistical inference and all fitted training/readout traces have separate independent audits."])
    with args.out.open("x") as destination:
        json.dump(report, destination, indent=2, sort_keys=True, allow_nan=False)
        destination.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--native", required=True)
    parser.add_argument("--out", type=Path, required=True)
    result = audit(parser.parse_args())
    print(json.dumps({key: result[key] for key in ("passed", "rows", "native_replayed_ticks",
                                                  "feature_max_discrepancy", "score_max_discrepancy")}))
