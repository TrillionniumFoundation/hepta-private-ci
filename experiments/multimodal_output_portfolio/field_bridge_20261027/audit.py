"""Independently reread delivered media, rebuild targets, and optionally replay native receipts.

Run only after EVALUATION_COMPLETE. No generator forward pass or parameter fit is
performed. Local hashes/timestamps establish internal consistency, not an external
attestation of execution, isolation, or real-world outcome ownership.
"""

import argparse
from collections import defaultdict
from contextlib import nullcontext
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from ..v6.data import DIGIT_OFFSET, VOCAB, make_batch
from ..v6.neural import parameter_hash
from ..v6.observer import CAPTION, observe_tensors, read_bundle
from .adapters import load_adapter, make_model
from .controls import choose, history_features
from .native_bridge import NativeBridge, Q24
from .protocol import P
from .run import digest, object_hash, setup, source_manifest, write_json
from .task import ACTIONS


def require(condition, message):
    if not condition:
        raise ValueError(message)


def untimed(value):
    if isinstance(value, dict):
        return {k: untimed(v) for k, v in value.items() if k not in {"native_ns", "bridge_roundtrip_ns"}}
    return [untimed(v) for v in value] if isinstance(value, list) else value


def native_check(path, x0, x1, prefix, reset, binary_sha, bridge, report):
    records = [json.loads(line) for line in path.open()]
    summary = json.loads(path.with_name(path.name + ".summary.json").read_text())
    require(len(records) == len(x0) == len(x1), f"Native row count: {path}")
    features, elapsed, roundtrip = [], 0, 0
    for index, (record, first, second) in enumerate(zip(records, x0, x1, strict=True)):
        raw = np.asarray([first, second], dtype="<f8")
        require(raw.shape == (2, 8) and np.isfinite(raw).all() and raw.min() >= 0 and raw.max() <= 1, "Native input")
        public_sha = hashlib.sha256(raw.tobytes()).hexdigest()
        request = dict(case=f"{prefix}:{index:08d}", readback_digest=public_sha,
                       features_q24=np.rint((2 * raw[0] - 1) * Q24).astype(np.int64).tolist(),
                       next_features_q24=np.rint((2 * raw[1] - 1) * Q24).astype(np.int64).tolist(), reset_before_readout=reset)
        require(record["case_index"] == index and record["request"] == request and record["public_feature_sha256"] == public_sha, "Native input binding")
        require(record["schema"] == "hepta.field-bridge.public-feature-receipt.v1" and record["public_feature_byte_encoding"] == "2x8 little-endian float64 row-major, first then second", "Native feature encoding")
        receipt = record["native"]
        require(receipt["case"] == request["case"] and receipt["binary_sha256"] == binary_sha and receipt["source_pin"] == P["source_base"], "Native identity")
        require(receipt["original_sparse_tick_calls"] == len(receipt["ticks"]) == 2 and receipt["feature_count"] == 8, "Native tick count")
        require(not receipt["native_owner_integration"] and receipt["checkpoint_reset_intervention"] == reset and receipt["next_public_observation_provided"], "Native boundary")
        for stage, tick in enumerate(receipt["ticks"]):
            drive = [component for q in request["features_q24" if stage == 0 else "next_features_q24"] for component in (max(-q, 0), max(q, 0))] + [Q24 // 4, 0, 0, 0]
            require(tick["drive_q24"] == drive and tick["stage"] == stage and tick["sequence"] == (1 if reset or stage == 0 else 2), "Native event mapping")
            require(tick["logical_clock_micros"] == stage + 1 and tick["fresh_public_observation"], "Native observation sequence")
            require(tick["authority"] == "DENY_ALL" and tick["requires_calibration"] and not tick["native_owner_integration"], "Native authority")
            require(all(len(tick[key]) == 20 for key in ("activation_q24", "eligibility_q24", "threshold_q24")), "Native state width")
        first_tick, second_tick = receipt["ticks"]
        require(second_tick["checkpoint_before"] == first_tick["checkpoint_before" if reset else "checkpoint_after"], "Native checkpoint chain")
        if bridge is not None:
            require(untimed(bridge.tick_pair(**request)) == untimed(receipt), "Native deterministic replay mismatch")
        features.append(np.asarray(second_tick["activation_q24"] + second_tick["eligibility_q24"], dtype=np.float64) / Q24)
        elapsed += sum(tick["native_ns"] for tick in receipt["ticks"])
        roundtrip += receipt["bridge_roundtrip_ns"]
    features = np.asarray(features, dtype="<f8")
    require(summary["rows"] == len(records) and summary["original_sparse_tick_calls"] == 2 * len(records), "Native summary count")
    require(summary["reset_before_readout"] == reset and summary["feature_width"] == 40, "Native summary profile")
    require(summary["native_ns"] == elapsed and summary["bridge_roundtrip_ns"] == roundtrip, "Native timing accounting")
    require(summary["feature_matrix_sha256"] == hashlib.sha256(features.tobytes()).hexdigest(), "Native feature hash")
    require(summary["target_accesses"] == 0 and summary["authority"] == "DENY_ALL" and not summary["native_owner_integration"], "Native summary authority")
    report["native_receipt_files"][str(path)] = digest(path)
    report["native_recorded_ticks"] += 2 * len(records)
    return features


@torch.inference_mode()
def reconstruct_features(observer, observation, media, receipts):
    pixels = torch.cat([item[0] for item in media])
    logits = torch.tensor([receipt["public_text_logits"] for receipt in receipts], dtype=torch.float32)
    require(logits.shape == (len(media), 2, len(VOCAB)) and torch.isfinite(logits).all(), "Preview logits shape")
    for value, receipt in zip(logits, receipts, strict=True):
        require(hashlib.sha256(value.numpy().astype("<f4", copy=False).tobytes()).hexdigest() == receipt["public_text_logits_sha256"], "Preview logits hash")
    text = logits.softmax(-1)[:, :, DIGIT_OFFSET:DIGIT_OFFSET + 10].amax(-1)
    image = torch.stack([observer(pixels[:, :, :, start:start + 28]).softmax(-1) for start in (0, 28)], dim=1)
    confidence, predicted = image.max(-1)
    disagreement = torch.ones(len(media), 2)
    for index, (_, caption, _) in enumerate(media):
        parsed = CAPTION.fullmatch(caption.strip())
        if parsed:
            disagreement[index] = torch.tensor([int(parsed[side + 1]) != int(predicted[index, side]) for side in (0, 1)])
    missing = 1 - observation.mask.float().flatten(1).mean(1)
    entropy = -(torch.special.xlogy(pixels, pixels) + torch.special.xlogy(1 - pixels, 1 - pixels)).flatten(1).mean(1) / math.log(2)
    return torch.cat((text, confidence, disagreement, missing[:, None], entropy[:, None]), dim=1).clamp(0, 1).numpy()


def audit(args):
    started, out = time.perf_counter_ns(), Path(args.out).resolve()
    load = lambda name: json.loads((out / name).read_text())
    done, frozen, source, env = [load(name) for name in ("EVALUATION_COMPLETE.json", "TRAINING_COMPLETE.json", "SOURCE_FREEZE.json", "ENVIRONMENT.json")]
    require(source_manifest() == source["files"] == frozen["source_files"] == done["source_files"], "Frozen source changed")
    require(source["protocol_sha256"] == object_hash(P) and done["training_complete_sha256"] == digest(out / "TRAINING_COMPLETE.json"), "Protocol/training freeze")
    require(done["row_sha256"] == digest(out / "rows.jsonl") and done["source_models_unchanged"], "Evaluation completion identity")
    binary_sha = env["native_binary_sha256"]
    require(binary_sha == frozen["native_binary_sha256"] and (args.native_sha256 is None or args.native_sha256 == binary_sha), "Native binary freeze")
    corpus, observers, originals, identities = setup(args, audit=True)
    require(json.loads(json.dumps(identities)) == env["source_models"], "Original model identity")
    report = dict(schema="hepta.field-bridge.independent-audit.v1", passed=False, score_max_discrepancy={}, feature_max_discrepancy=0.0,
                  native_receipt_files={}, native_recorded_ticks=0, model_hashes={}, controller_hashes={}, media_files=0, decision_files=0,
                  native_replay_enabled=args.native is not None, source_files=source["files"], original_models=identities,
                  original_archive_sha256=P["asset_sha256"], corpus_manifest=corpus.manifest, rows_sha256=done["row_sha256"])
    report["observer_parameter_sha256"] = {name: parameter_hash(observer) for name, observer in observers.items()}
    for seed in P["seeds"]:
        info = frozen["seeds"][str(seed)]
        for profile in ("frozen", "ordinary", "field", "generic", "richer"):
            path = out / "training" / str(seed) / f"{profile}.pt"
            if profile == "frozen":
                model = make_model(originals[seed], seed)
            else:
                require(digest(path) == info["profiles"][profile]["file_sha256"], "Adapted checkpoint file hash")
                model, _ = load_adapter(path, originals[seed], seed, identities[seed]["file_sha256"])
            report["model_hashes"][f"{seed}-{profile}"] = parameter_hash(model)
    rows = [json.loads(line) for line in (out / "rows.jsonl").open()]
    arms, groups, keys = {**P["canonical_arms"], **P["supplementary_arms"]}, defaultdict(list), set()
    expected = {(seed, arm, split, condition, pair) for seed in P["seeds"] for arm in arms for split in ("test", "retention")
                for condition in P[f"{split}_conditions"] for pair in range(P[f"{split}_pairs"])}
    for row in rows:
        key = tuple(row[k] for k in ("seed", "arm", "split", "corruption", "pair"))
        require(key not in keys, "Duplicate evaluation row")
        keys.add(key)
        groups[key[:4] + (row["batch_start"],)].append(row)
    require(keys == expected and len(rows) == done["rows"], "Complete registered cohort")
    readback_ledger = hashlib.sha256()
    with NativeBridge(args.native, binary_sha) if args.native else nullcontext() as bridge:
        for seed in P["seeds"]:
            for profile in ("frozen", "ordinary", "field"):
                root = out / "runtime" / f"{seed}-{profile}"
                require(json.loads((root / "READOUTS.json").read_text())["models"] == frozen["seeds"][str(seed)]["readouts"][profile], "Frozen readout identity")
                membership = json.loads((root / "BANK_IDENTITIES.json").read_text())
                with np.load(root / "banks.npz", allow_pickle=False) as banks:
                    for stage, split, count_key, offset_key, added, prefix in (
                        ("train", "train", "runtime_train_pairs", "runtime_train_offset", 0, "fit"),
                        ("dev", "validation", "readout_development_pairs", "readout_development_offset", 701, "dev")):
                        source_ids = [list(pair) for ci, condition in enumerate(P["training_conditions"])
                                      for pair in make_batch(corpus, split, P[count_key], (seed + added) * 1009 + ci,
                                                             offset=P[offset_key], corruption=condition).source_ids]
                        require(source_ids == membership["train" if stage == "train" else "development"], "Runtime bank source membership")
                        native_check(root / f"{stage}-native.jsonl", banks[f"{stage}_x0"], banks[f"{stage}_x1"],
                                     f"{prefix}-{seed}-{profile}", False, binary_sha, bridge, report)
        for (seed, arm, split, condition, start), group in sorted(groups.items()):
            group.sort(key=lambda row: row["pair"])
            size, ci = min(P["evaluation_batch_size"], P[f"{split}_pairs"] - start), P[f"{split}_conditions"].index(condition)
            require(start % P["evaluation_batch_size"] == 0 and len(group) == size, "Evaluation batch coverage")
            batch_seed, noise_seed = 271027 + start + ci * 10000, seed * 100003 + start + ci * 1009
            batch = make_batch(corpus, split, size, batch_seed, offset=P[f"{split}_offset"] + start, corruption=condition)
            info, (profile, control) = frozen["seeds"][str(seed)], arms[arm]
            readout = None if control == "fixed" else info["readouts"][profile]["native" if control == "reset" else control]
            controller_sha = object_hash({"action": info["fixed_action"]} if readout is None else readout)
            report["controller_hashes"][f"{seed}-{arm}"] = controller_sha
            media, features = [[], [], []], [np.array([r[f"public_features{stage}"] for r in group], dtype=np.float32) for stage in (0, 1)]
            require(all(x.shape == (size, 8) and np.isfinite(x).all() and x.min() >= 0 and x.max() <= 1 for x in features), "Public field range")
            for index, row in enumerate(group):
                require((row["pair"], row["batch_size"], row["batch_seed"], row["noise_seed"]) == (start + index, size, batch_seed, noise_seed), "Episode RNG/offset identity")
                require(row["source_ids"] == list(batch.source_ids[index]) and row["private_labels_after_decision"] == batch.target.labels[index].tolist(), "Private target reconstruction")
                require(row["model_sha"] == report["model_hashes"][f"{seed}-{profile}"] and row["controller_sha"] == controller_sha, "Deployed model/controller identity")
                case = f"pair-{row['pair']:04d}"
                case_root = Path("outputs") / str(seed) / arm / split / condition / case
                require(len(row["artifacts"]) == 3, "Three delivered media phases")
                for stage, (phase, receipt) in enumerate(zip(("preview0", "preview1", "final"), row["artifacts"], strict=True)):
                    paths = {kind: str(case_root / phase / filename) for kind, filename in (("image", "image.png"), ("text", "caption.txt"))}
                    require(receipt["paths"] == paths and receipt["phase"] == phase and receipt["case_id"] == case, "Artifact case binding")
                    require(all((out / path).resolve().is_relative_to(out) for path in paths.values()), "Artifact path escaped output root")
                    actual = read_bundle({kind: str(out / path) for kind, path in paths.items()})
                    require(actual[2] == receipt["sha256"], "Delivered bytes changed")
                    media[stage].append(actual)
                    readback_ledger.update(json.dumps([paths, actual[2]], sort_keys=True).encode())
                    report["media_files"] += 2
                decision_path = out / case_root / "decision.json"
                decision, receipts = json.loads(decision_path.read_text()), row["artifacts"]
                field_sha = hashlib.sha256(np.stack([x[index] for x in features]).tobytes()).hexdigest()
                require(decision["case_id"] == case and decision["action"] == ACTIONS[row["action"]] and decision["model_sha256"] == row["model_sha"], "Committed decision identity")
                require(decision["public_features_sha256"] == field_sha and decision["preview_sha256"] == [r["sha256"] for r in receipts[:2]], "Decision preview binding")
                require(decision["preview_logits_sha256"] == [r["public_text_logits_sha256"] for r in receipts[:2]], "Decision logits binding")
                times = [receipts[0]["readback_monotonic_ns"], receipts[0]["evidence_monotonic_ns"], receipts[1]["readback_monotonic_ns"], receipts[1]["evidence_monotonic_ns"], decision["committed_monotonic_ns"], receipts[2]["readback_monotonic_ns"]]
                require(all(left < right for left, right in zip(times, times[1:])), "Preview/decision/final chronology")
                require(row["refinement_count"] == 1 + (row["action"] != 0), "Actual action charge")
                require(all(row["resources"][k] == 0 for k in ("prepare_target_accesses", "finish_target_accesses", "finish_unchosen_continuations_executed")), "Deployment access/execution contract")
                require(row["resources"]["native_tick_calls"] == (2 if control in {"native", "reset"} else 0), "Deployment tick accounting")
                readback_ledger.update(digest(decision_path).encode())
                report["decision_files"] += 1
            for stage in (0, 1):
                rebuilt = reconstruct_features(observers["reward"], batch.observation, media[stage], [r["artifacts"][stage] for r in group])
                report["feature_max_discrepancy"] = max(report["feature_max_discrepancy"], float(np.max(np.abs(rebuilt - features[stage]))))
            if control in {"native", "reset"}:
                prefix = f"{seed}-{arm}-{split}-{condition}-{start}"
                representation = native_check(out / "native" / f"{prefix}.jsonl", *features, prefix, control == "reset", binary_sha, bridge, report)
            else:
                representation = history_features(*features)
            actions = np.full(size, info["fixed_action"]) if readout is None else choose(readout, representation)
            require(actions.tolist() == [r["action"] for r in group], "Frozen controller action reproduction")
            pixels, captions = torch.cat([item[0] for item in media[2]]), [item[1] for item in media[2]]
            for name, observer in observers.items():
                scores = observe_tensors(observer, pixels, captions, batch.target.pixels, batch.target.labels)
                for row, score in zip(group, scores, strict=True):
                    require(row[name].keys() == score.keys(), "Score component inventory")
                    for component, value in score.items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            require(math.isfinite(row[name][component]), "Nonfinite recorded score")
                            key = f"{name}.{component}"
                            report["score_max_discrepancy"][key] = max(report["score_max_discrepancy"].get(key, 0.0), abs(value - row[name][component]))
                        else:
                            require(value == row[name][component], f"Categorical score mismatch: {name}.{component}")
        report["native_replayed_ticks"] = 0 if bridge is None else 2 * bridge.request_count
    require(report["feature_max_discrepancy"] <= 1e-7 and max(report["score_max_discrepancy"].values(), default=0) <= 1e-7, "Reconstructed feature/score tolerance exceeded")
    require(source_manifest() == source["files"], "Source changed during audit")
    report.update(passed=True, rows=len(rows), batches=len(groups), score_rows=2 * len(rows), observer_digit_examples=8 * len(rows),
                  observer_forward_calls=8 * len(groups), generator_forward_calls=0, native_binary_sha256=binary_sha,
                  media_decision_ledger_sha256=readback_ledger.hexdigest(), numeric_tolerance=1e-7, audit_wall_ns=time.perf_counter_ns() - started,
                  limitations=["Same-host recorded chronology and hashes are not external execution attestation.", "Generator source/model identities are checked without regenerating outputs.", "Native replay is conditional on the recorded public inputs; it does not establish production ownership."])
    write_json(out / "INDEPENDENT_AUDIT.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("assets", "out", "native", "native-sha256"):
        parser.add_argument("--" + option, required=option in {"assets", "out"})
    arguments = parser.parse_args()
    result = audit(arguments)
    print(json.dumps({key: result[key] for key in ("passed", "rows", "media_files", "native_recorded_ticks", "native_replayed_ticks", "feature_max_discrepancy", "score_max_discrepancy")}))
