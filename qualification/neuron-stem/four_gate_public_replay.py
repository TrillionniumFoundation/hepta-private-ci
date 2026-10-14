#!/usr/bin/env python3
"""Real mmBERT + human-labelled CLINC150 replay, NOT live Hepta learning evidence.

Reuses existing Head, scoring and pre-label journal helpers. Domain is supplied
by this conditional benchmark, never claimed as an inferred routing decision.
No synthetic calendar windows, current no-change model or third gate reviewer.
"""
import argparse
from collections import defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time
import urllib.request

from four_gate_capture import tensor_digest
from four_gate_common import canonical, digest, require, write_once
from four_gate_pretrained import MODEL, REVISION, file_hash, load_pinned
from hf_trial import make_head
from prequential_trial import prediction_precommit, score_prediction, accuracy_brier
from qualified_eval import strict_json_loads

DATA_REV = "828f8093932c8fe6ca7936c3d2e52903b1c523de"
DATA_PINS = {
    "data/data_full.json": (2495390, "7a7b26c5f2dfbbf213f3e67d2dd0727e1af545aa"),
    "data/domains.json": (3818, "60a74358e52060e60b6128ae4efe679e9d6ba69c"),
    "LICENSE": (19467, "1a16e05564d2aaa880bbe9e506a0a0226d8742cc"),
}
DOMAINS = ("home", "utility", "work", "meta")


def read_public_data(directory):
    directory.mkdir(parents=True, exist_ok=False)
    for name, (size, blob) in DATA_PINS.items():
        url = f"https://raw.githubusercontent.com/clinc/oos-eval/{DATA_REV}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read(size + 1)
        require(len(raw) == size, "public source size drift")
        require(hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == blob,
                "public source immutable Git blob drift")
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return (strict_json_loads((directory / "data/data_full.json").read_text()),
            strict_json_loads((directory / "data/domains.json").read_text()))


def dataset_view(data, domains):
    """Frozen publisher partitions; no invented domain, label or sample identity."""
    groups = defaultdict(list)
    for split in ("train", "val", "test", "oos_train", "oos_test"):
        require(type(data[split]) is list and data[split], "missing publisher partition")
        for ordinal, entry in enumerate(data[split]):
            require(type(entry) is list and len(entry) == 2 and all(type(v) is str and v for v in entry),
                    "invalid original human-labelled sample")
            text, intent = entry
            require(len(text) <= 4096, "unbounded public utterance")
            groups[(split, intent)].append({"publisher_split": split, "publisher_ordinal": ordinal,
                "state": text, "intent": intent, "source_input_sha256": digest(text)})
    views = {name: [] for name in ("train", "calibration", "retention", "replay", "oos_train", "oos_test")}
    for domain in DOMAINS:
        options = domains[domain]
        require(len(options) == 15 and len(set(options)) == 15, "official 15-intent domain required")
        for intent in options:
            require(all(len(groups[(split, intent)]) >= needed
                        for split, needed in (("train", 8), ("val", 20), ("test", 10))), "incomplete selected intent")
            for split, origin, first, last in (("train", "train", 0, 8),
                    ("calibration", "val", 0, 10), ("retention", "val", 10, 20),
                    ("replay", "test", 0, 10)):
                for original in groups[(origin, intent)][first:last]:
                    views[split].append({**original, "cell_id": domain, "options": options,
                        "label": options.index(intent), "scope_id": "public-clinc-conditional",
                        "case_id": f"{origin}:{original['publisher_ordinal']}",
                        "question": f"Given the supplied domain {domain}, classify this request."})
    for split, limit in (("oos_train", 100), ("oos_test", 200)):
        require(len(groups[(split, "oos")]) >= limit, "missing genuine out-of-scope examples")
        views[split] = groups[(split, "oos")][:limit]
    # Preserve every selected sample and disclose any cross-partition overlap.
    # The unfiltered replay is not a source-independent generalization estimate.
    inputs = defaultdict(set)
    for split, rows in views.items():
        for row in rows:
            inputs[row["source_input_sha256"]].add(split)
    overlaps = {key: sorted(value) for key, value in inputs.items() if len(value) > 1}
    random.Random(20261011).shuffle(views["replay"])
    return views, overlaps


def head_digest(head):
    return digest({name: tensor_digest(value) for name, value in head.state_dict().items()})


def combine_cells(probabilities, support):
    """Combine all Cell predictions without accepting a gold domain or label."""
    require(set(probabilities) == set(support) == set(DOMAINS), "complete group inputs")
    require(all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1
                for v in support.values()) and sum(support.values()) > 0, "invalid group support")
    combined = []
    for domain in DOMAINS:
        p = probabilities[domain]
        require(len(p) == 15 and all(math.isfinite(v) and 0 <= v <= 1 for v in p)
                and abs(sum(p) - 1) <= 1e-5, "invalid conditional Cell distribution")
        combined.extend(v * support[domain] / sum(support.values()) for v in p)
    return combined


def run(args):
    import torch
    from torch import nn

    torch.set_num_threads(2)
    torch.manual_seed(20261011)
    args.output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    data, domains = read_public_data(args.output / "publisher")
    views, overlaps = dataset_view(data, domains)
    source_sha = subprocess.check_output(["git", "-C", str(args.source_root), "rev-parse", "HEAD"], text=True).strip()
    write_once(args.output / "replay-plan.json", {"schema": "hepta.public-replay-plan.v1",
        "source_sha": source_sha, "publisher_revision": DATA_REV, "publisher_pins": DATA_PINS,
        "view_sha256": digest(views), "domain_given_not_inferred": True,
        "domains": DOMAINS, "seed": 20261011, "pretrain_steps": 64, "update_steps": 2,
        "learning_rate": .003, "head_budget": 16384, "max_tokens": 64,
        "counts": {key: len(rows) for key, rows in views.items()},
        "group_evaluation": "normalized_domain_support_times_conditional_class_probability",
        "no_change_available": False, "genuine_future_windows": False,
        "overlap_policy": "retain_all_disclose_source_overlap_no_independence_claim",
        "cross_partition_input_overlap": overlaps})
    model, tokenizer, inventory, loading = load_pinned(args.model_dir)
    model_cost = {"cpu_ns": time.process_time_ns() - start_cpu,
                  "wall_ns": time.perf_counter_ns() - start_wall}
    all_rows = [row for rows in views.values() for row in rows]
    by_input = {row["source_input_sha256"]: row["state"] for row in all_rows}
    features, forward_events = {}, []
    for start in range(0, len(by_input), 32):
        ids = list(by_input)[start:start + 32]
        tokens = tokenizer([by_input[key] for key in ids], padding=True, truncation=True,
                           max_length=64, return_tensors="pt")
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        with torch.inference_mode():
            output = model(**tokens).last_hidden_state.float()
            mask = tokens["attention_mask"].unsqueeze(-1).float()
            vectors = (output * mask).sum(1) / mask.sum(1).clamp_min(1)
        forward_events.append({"inputs": ids, "tokens": int(mask.sum().item()),
            "input_tensor_sha256": tensor_digest(tokens["input_ids"]),
            "cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - wall})
        features.update({key: vectors[i].clone() for i, key in enumerate(ids)})
    train_matrix = torch.stack([features[r["source_input_sha256"]] for r in views["train"]])
    mean, scale = train_matrix.mean(0), train_matrix.std(0).clamp_min(.1)
    features = {key: ((value - mean) / scale).clamp(-8, 8) for key, value in features.items()}
    heads, frozen, optimizers, supports, rejectors = {}, {}, {}, {}, {}
    pretrain_cpu = time.process_time_ns()
    for index, domain in enumerate(DOMAINS):
        torch.manual_seed(20261011 + index)
        head = make_head(torch, nn, "swiglu", 384, 15, 16384)[0]
        optimizer = torch.optim.AdamW(head.parameters(), lr=.003)
        train = [r for r in views["train"] if r["cell_id"] == domain]
        x = torch.stack([features[r["source_input_sha256"]] for r in train])
        y = torch.tensor([r["label"] for r in train])
        for _ in range(64):
            optimizer.zero_grad()
            nn.functional.cross_entropy(head(x), y).backward()
            nn.utils.clip_grad_norm_(head.parameters(), 1.)
            optimizer.step()
        heads[domain], optimizers[domain] = head.eval(), optimizer
        frozen[domain] = copy.deepcopy(head).eval().requires_grad_(False)
        supports[domain] = (x.mean(0), x.std(0).clamp_min(.1))
        # Same approved historical pool for all detectors; confidence uses no
        # separate fit and the support method deliberately uses its ID subset.
        outside = [r for r in views["train"] if r["cell_id"] != domain] + views["oos_train"]
        nx = torch.stack([features[r["source_input_sha256"]] for r in outside])
        detector = nn.Linear(384, 1)
        opt = torch.optim.AdamW(detector.parameters(), lr=.003)
        xx, yy = torch.cat((x, nx)), torch.cat((torch.ones(len(x)), torch.zeros(len(nx))))
        for _ in range(64):
            opt.zero_grad()
            nn.functional.binary_cross_entropy_with_logits(detector(xx).squeeze(-1), yy).backward()
            opt.step()
        rejectors[domain] = detector.eval().requires_grad_(False)
    training_cpu = time.process_time_ns() - pretrain_cpu
    frozen_ids = {key: head_digest(value) for key, value in frozen.items()}
    def evaluate(rows, collection):
        results = defaultdict(list)
        with torch.inference_mode():
            for row in rows:
                probs = collection[row["cell_id"]](features[row["source_input_sha256"]]).softmax(-1).tolist()
                results[row["cell_id"]].append(score_prediction(probs, row["label"]))
        return {key: accuracy_brier(value) for key, value in results.items()}
    retention_before = evaluate(views["retention"], frozen)
    outcomes, updates = [], []
    with (args.output / "prediction-journal.jsonl").open("xb") as journal:
        for order, row in enumerate(views["replay"]):
            domain = row["cell_id"]
            head, optimizer = heads[domain], optimizers[domain]
            x = features[row["source_input_sha256"]]
            logits = head(x)
            probs = logits.detach().softmax(-1).tolist()
            with torch.inference_mode():
                control = frozen[domain](x).softmax(-1).tolist()
            stamp = datetime.now(timezone.utc).isoformat()
            entry = prediction_precommit({**row, "event_time": stamp}, probs, head_digest(head), order)
            entry.update({"frozen_control_probabilities": control,
                          "frozen_control_head_digest": frozen_ids[domain]})
            envelope = {"schema": "hepta.public-replay-envelope.v1", "precommit": entry,
                "model": MODEL, "revision": REVISION, "publisher_case": row["case_id"],
                "time_semantics": "replay_clock_not_data_collection", "genuine_future_observation": False}
            journal.write(canonical(envelope) + b"\n")
            journal.flush()
            os.fsync(journal.fileno())
            # Only now is this row's publisher label supplied to the candidate optimizer.
            truth = row["label"]
            outcomes.append({"case_id": row["case_id"], "cell_id": domain,
                "publisher_label": truth, "trained": score_prediction(probs, truth),
                "frozen": score_prediction(control, truth), "independent_runtime_observer": False})
            before = time.process_time_ns()
            for _ in range(2):
                optimizer.zero_grad()
                nn.functional.cross_entropy(head(x).unsqueeze(0), torch.tensor([truth])).backward()
                nn.utils.clip_grad_norm_(head.parameters(), 1.)
                optimizer.step()
            updates.append({"case_id": row["case_id"], "pre_head": entry["head_digest"],
                            "post_head": head_digest(head), "cpu_ns": time.process_time_ns() - before})
    require(all(head_digest(frozen[key]) == value for key, value in frozen_ids.items()), "frozen Head mutated")
    retention_after = evaluate(views["retention"], heads)
    selective = []
    for domain in DOMAINS:
        center, spread = supports[domain]
        for arm, collection in (("frozen", frozen), ("trained", heads)):
            def scores(row):
                with torch.inference_mode():
                    x = features[row["source_input_sha256"]]
                    p = collection[domain](x).softmax(-1).tolist()
                    support = float(torch.exp(-((x - center) / spread).square().mean() / 2))
                    rejection = float(rejectors[domain](x).sigmoid().item())
                return p, {"confidence": max(p), "feature_support": support, "learned_rejector": rejection}
            calibration = [scores(r)[1] for r in views["calibration"] if r["cell_id"] == domain]
            thresholds = {method: sorted(r[method] for r in calibration)[int(.05 * len(calibration))]
                          for method in ("confidence", "feature_support", "learned_rejector")}
            for kind, rows in (("known", [r for r in views["retention"] if r["cell_id"] == domain]),
                               ("unknown", views["oos_test"])):
                for row in rows:
                    p, values = scores(row)
                    selective.append({"cell_id": domain, "arm": arm, "kind": kind,
                        "input_sha256": row["source_input_sha256"], "probabilities": p,
                        "publisher_label": row.get("label"), "scores": values,
                        "accepted": {name: value >= thresholds[name] for name, value in values.items()},
                        "correct": None if kind == "unknown" else p.index(max(p)) == row["label"],
                        "head_digest": head_digest(collection[domain]), "thresholds": thresholds})
    # Separate group evaluation receives only features and all Cell outputs.
    # The evaluator consults the true domain ONLY after prediction, unlike the
    # explicitly domain-conditioned per-Cell learning statistic above.
    group_records = []
    for arm, collection in (("frozen", frozen), ("trained", heads)):
        def group_predict(x):
            with torch.inference_mode():
                probabilities = {d: h(x).softmax(-1).tolist() for d, h in collection.items()}
                q = {d: float(rejectors[d](x).sigmoid().item()) for d in DOMAINS}
                joint = combine_cells(probabilities, q)
                support = max(float(torch.exp(-((x - supports[d][0]) / supports[d][1]).square().mean() / 2))
                              for d in DOMAINS)
                return joint, {"confidence": max(joint), "feature_support": support,
                               "learned_rejector": max(q.values())}
        calibrated = [group_predict(features[r["source_input_sha256"]])[1] for r in views["calibration"]]
        thresholds = {method: sorted(r[method] for r in calibrated)[int(.05 * len(calibrated))]
                      for method in ("confidence", "feature_support", "learned_rejector")}
        for kind, rows in (("known", views["retention"]), ("unknown", views["oos_test"])):
            for row in rows:
                probabilities, values = group_predict(features[row["source_input_sha256"]])
                # Assessment, not an input to group_predict or combine_cells.
                truth = None if kind == "unknown" else DOMAINS.index(row["cell_id"]) * 15 + row["label"]
                group_records.append({"arm": arm, "kind": kind, "input_sha256": row["source_input_sha256"],
                    "probabilities": probabilities, "publisher_label": truth,
                    "correct": None if truth is None else probabilities.index(max(probabilities)) == truth,
                    "accepted": {name: value >= thresholds[name] for name, value in values.items()},
                    "scores": values, "thresholds": thresholds,
                    "gold_domain_provided_to_predictor": False, "learned_cell_depth": 1})
    write_once(args.output / "group-routing.json", group_records)
    detector_ids = {domain: {"rejector": head_digest(rejectors[domain]),
        "support": digest([tensor_digest(v) for v in supports[domain]])} for domain in DOMAINS}
    for row in selective:
        row["detector_artifacts"] = detector_ids[row["cell_id"]]
    for name, value in (("outcomes", outcomes), ("updates", updates), ("selective", selective),
                        ("forward-events", forward_events)):
        write_once(args.output / f"{name}.json", value)
    weights = {f"{arm}.{domain}.{key}": value for arm, collection in (("frozen", frozen), ("trained", heads))
               for domain, head in collection.items() for key, value in head.state_dict().items()}
    weights.update({f"rejector.{domain}.{key}": value for domain, head in rejectors.items()
                    for key, value in head.state_dict().items()})
    for domain, (center, spread) in supports.items():
        weights[f"support.{domain}.center"], weights[f"support.{domain}.scale"] = center, spread
    weights["normalizer.mean"], weights["normalizer.scale"] = mean, scale
    with (args.output / "candidate-heads.pt").open("xb") as stream:
        torch.save(weights, stream)
        stream.flush()
        os.fsync(stream.fileno())
    summary = {"schema": "hepta.public-replay-observations.v1", "source_sha": source_sha,
        "dataset_revision": DATA_REV, "model_revision": REVISION, "physical_files": inventory,
        "cross_partition_input_overlap": overlaps,
        "loading_info": loading, "domain_given_not_inferred": True,
        "prequential": {arm: accuracy_brier([r[arm] for r in outcomes]) for arm in ("frozen", "trained")},
        "retention_before": retention_before, "retention_after": retention_after,
        "candidate_heads_sha256": file_hash(args.output / "candidate-heads.pt"),
        "prelabel_journal_sha256": file_hash(args.output / "prediction-journal.jsonl"),
        "initial_head_digests": frozen_ids, "final_head_digests": {d: head_digest(h) for d, h in heads.items()},
        "head_parameters_each": sum(p.numel() for p in heads[DOMAINS[0]].parameters()),
        "normalizer_sha256": digest({"mean": tensor_digest(mean), "scale": tensor_digest(scale)}),
        "observed_cost": {"download_and_load": model_cost, "initial_head_and_detector_training_cpu_ns": training_cpu,
                          "updates_cpu_ns": sum(row["cpu_ns"] for row in updates),
                          "whole_process_cpu_ns": time.process_time_ns() - start_cpu,
                          "whole_process_wall_ns": time.perf_counter_ns() - start_wall},
        "no_change_available": False, "independent_source_cluster_count_known": False,
        "detector_artifacts": detector_ids, "pretraining_contamination_assessed": False,
        "group_routing_accuracy": {arm: sum(r["correct"] for r in group_records if r["arm"] == arm and r["kind"] == "known") /
            sum(r["arm"] == arm and r["kind"] == "known" for r in group_records) for arm in ("frozen", "trained")},
        "genuine_future_windows": False, "three_way_learning_gate_passed": False,
        "production_promotion_permitted": False,
        "attribution": "Larson et al. (2019), An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction; CLINC150, CC BY 3.0. See publisher LICENSE."}
    write_once(args.output / "summary.json", summary)
    print(canonical({"prequential": summary["prequential"], "replay_events": len(outcomes),
        "real_mmbert_and_head_updates_executed": True, "three_way_learning_gate_passed": False}).decode(), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
