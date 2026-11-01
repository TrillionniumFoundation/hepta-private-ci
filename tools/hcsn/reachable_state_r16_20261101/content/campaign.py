"""Two-freeze content learning campaign with fresh independent key confirmation."""

import argparse
import gzip
import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
from scipy.stats import t
from threadpoolctl import threadpool_limits

from .models import configurations, fit_encoders, predict
from .task import DOMAINS, digest, episode, exact_address_oracle, paired_views, registry, task_fee


ROOT = Path(__file__).parent
SOURCE_FILES = ("__init__.py", "task.py", "models.py", "campaign.py", "PROTOCOL.json")
KINDS = ("cosine", "ridge", "gated_delta")


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def run_train(seed, protocol):
    started = time.process_time()
    owner = registry(seed)
    train_a, train_b = paired_views(owner, "train", protocol["namespace"]["training_pairs"] + seed)
    select_a, select_b = paired_views(owner, "selection", protocol["namespace"]["selection_pairs"] + seed)
    encoders, encoder_index = fit_encoders(train_a, train_b, select_a, select_b)
    weight = encoders[encoder_index]["weight"]
    examples = [episode(owner, "selection", protocol["namespace"]["selection_episodes"] + seed * 1000 + i)
                for i in range(protocol["selection_episodes"])]
    candidates, selected = {}, {}
    for kind in KINDS:
        candidates[kind] = []
        for config in configurations(kind):
            before = time.process_time()
            rows = []
            for public, private in examples:
                prediction = predict(public, weight, kind, config)
                rows.append(float(np.mean(np.array(prediction["answers"]) == private["targets"])))
            candidates[kind].append(dict(config=config, episode_accuracy=rows,
                                         accuracy=float(np.mean(rows)), cpu_seconds=time.process_time() - before))
        selected[kind] = max(range(len(candidates[kind])), key=lambda i: (candidates[kind][i]["accuracy"], -i))
    best_kind = max(KINDS, key=lambda k: (candidates[k][selected[k]]["accuracy"], -KINDS.index(k)))
    return dict(seed=seed, encoders=encoders, selected_encoder=encoder_index,
                candidates=candidates, selected=selected, selected_ordinary=best_kind,
                data_digests=dict(train_pairs=digest([train_a.tolist(), train_b.tolist()]),
                                  selection_pairs=digest([select_a.tolist(), select_b.tolist()]),
                                  selection_streams=[p["public_sha256"] for _, p in examples]),
                cpu_seconds=time.process_time() - started)


def training(args, protocol):
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    frozen = dict(schema="hcsn-r16-content-fit-freeze-v1", source_commit=args.source_commit,
                  source_hashes=source_hashes(), protocol_sha256=digest(protocol), fits=[])
    for seed in protocol["fit_seeds"]:
        fitted = run_train(seed, protocol)
        frozen["fits"].append(fitted)
        write(args.output / f"fit_{seed}.json", fitted)
        print(json.dumps(dict(stage="train", seed=seed, selected=fitted["selected_ordinary"])), flush=True)
    frozen["measured_training_cpu_seconds"] = time.process_time() - started
    frozen["sha256"] = digest(frozen)
    write(args.output / "FROZEN_MODELS.json", frozen)


def confirmation(args, protocol):
    frozen = json.loads(args.frozen.read_text())
    expected = frozen.pop("sha256")
    if digest(frozen) != expected or frozen["source_hashes"] != source_hashes():
        raise ValueError("Source or fitted model freeze mismatch")
    if frozen["source_commit"] != args.source_commit or frozen["protocol_sha256"] != digest(protocol):
        raise ValueError("Publication/protocol mismatch")
    if [fit["seed"] for fit in frozen["fits"]] != protocol["fit_seeds"]:
        raise ValueError("Incomplete or reordered fit freeze")
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {domain: {kind: [] for kind in (*KINDS, "selected_ordinary", "oracle")} for domain in DOMAINS}
    started = time.process_time()
    for fit in frozen["fits"]:
        owner, seed = registry(fit["seed"]), fit["seed"]
        weight = fit["encoders"][fit["selected_encoder"]]["weight"]
        for domain_index, domain in enumerate(DOMAINS):
            before = time.process_time()
            rows = []
            for index in range(protocol["confirmation_episodes_per_fit_domain"]):
                sample_seed = protocol["namespace"]["confirmation_episodes"] + seed * 10000 + domain_index * 1000 + index
                public, private = episode(owner, "confirmation", sample_seed, domain)
                fee, outcomes = task_fee(public), {}
                for kind in KINDS:
                    config = fit["candidates"][kind][fit["selected"][kind]]["config"]
                    prediction = predict(public, weight, kind, config)
                    prediction["accuracy"] = float(np.mean(np.array(prediction["answers"]) == private["targets"]))
                    prediction["utility"] = prediction["accuracy"] - fee
                    outcomes[kind] = prediction
                oracle_start = time.process_time()
                oracle = exact_address_oracle(public, private["key_ids"])
                outcomes["oracle"] = dict(answers=oracle, accuracy=float(np.mean(np.array(oracle) == private["targets"])),
                                          cpu_seconds=time.process_time() - oracle_start)
                outcomes["oracle"]["utility"] = outcomes["oracle"]["accuracy"] - fee
                rows.append(dict(owner=private, fee=fee, outcomes=outcomes))
            # Store every query answer and truth, including failures, with exact regeneration identity.
            archive = dict(seed=seed, domain=domain, model_sha256=digest(fit), rows=rows,
                           worker_cpu_seconds_before_serialization=time.process_time() - before)
            serial_start = time.process_time()
            with gzip.open(args.output / f"raw_{seed}_{domain}.json.gz", "wt") as stream:
                json.dump(archive, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            serial_cpu = time.process_time() - serial_start
            for kind in (*KINDS, "oracle"):
                summary[domain][kind].append(dict(seed=seed, accuracy=float(np.mean([r["outcomes"][kind]["accuracy"] for r in rows])),
                    utility=float(np.mean([r["outcomes"][kind]["utility"] for r in rows])),
                    online_cpu_seconds=float(np.sum([r["outcomes"][kind]["cpu_seconds"] for r in rows])),
                    episodes=len(rows)))
            summary[domain]["selected_ordinary"].append(dict(summary[domain][fit["selected_ordinary"]][-1],
                                                              selected_family=fit["selected_ordinary"]))
            write(args.output / f"receipt_{seed}_{domain}.json", dict(cpu_seconds=time.process_time() - before,
                   serialization_cpu_seconds=serial_cpu, source_commit=args.source_commit, model_commit=args.model_commit))
            print(json.dumps(dict(stage="confirm", seed=seed, domain=domain)), flush=True)
    gates, statistics = {}, {}
    critical = float(t.ppf(1 - .05 / len(DOMAINS), len(protocol["fit_seeds"]) - 1))
    for domain in DOMAINS:
        statistics[domain] = {}
        for kind, rows in summary[domain].items():
            values = np.array([r["accuracy"] for r in rows])
            low = float(values.mean() - critical * values.std(ddof=1) / np.sqrt(len(values)))
            statistics[domain][kind] = dict(mean_accuracy=float(values.mean()), simultaneous_accuracy_lower=low,
                                            mean_utility=float(np.mean([r["utility"] for r in rows])))
        gates[domain] = statistics[domain]["selected_ordinary"]["simultaneous_accuracy_lower"] > .90
    report = dict(schema="hcsn-r16-content-confirmation-v1", source_commit=args.source_commit,
                  model_commit=args.model_commit, frozen_models_sha256=expected,
                  per_fit=summary, statistics=statistics, domain_gates=gates, acceptance=all(gates.values()),
                  independent_unit="fit; n=8", critical_t=critical,
                  cpu_seconds_including_raw_serialization=time.process_time() - started,
                  scope="Synthetic learned binding with strong ordinary retrieval; no HX comparison or general semantic-memory claim.")
    write(args.output / "SUMMARY.json", report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train", "confirm", "development"))
    parser.add_argument("--source-commit")
    parser.add_argument("--model-commit")
    parser.add_argument("--frozen", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    if args.stage != "development" and not re.fullmatch("[a-f0-9]{40}", args.source_commit or ""):
        raise ValueError("Published source commit is required")
    if args.stage == "confirm" and (args.frozen is None or not re.fullmatch("[a-f0-9]{40}", args.model_commit or "")):
        raise ValueError("Published fitted-model commit is required")
    with threadpool_limits(limits=1):
        if args.stage == "development":
            args.output.mkdir(parents=True, exist_ok=False)
            write(args.output / "DEVELOPMENT.json", run_train(protocol["development_seed"], protocol))
        elif args.stage == "train":
            training(args, protocol)
        else:
            confirmation(args, protocol)


if __name__ == "__main__":
    main()
