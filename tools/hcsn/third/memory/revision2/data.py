"""Fresh development-only data, with content checks against previous cohorts."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from benchmarks.data import make_data, fingerprint


def input_hashes(data):
    return {hashlib.sha256(x.tobytes()+dt.tobytes()).hexdigest()
            for x, dt in zip(data["x"], data["dt"])}


def make_suite(task, seed, protocol):
    base = protocol["data_seed_base"]+1000*seed
    training = [make_data(task, base+length, protocol["training_examples_per_length"], length)
                for length in protocol["training_lengths"]]
    suite = {"validation32": make_data(task, base+201, protocol["validation_examples"], 32),
             "diagnostic128": make_data(task, base+428, protocol["diagnostic_examples"], 128),
             "diagnostic512": make_data(task, base+812, protocol["diagnostic_examples"], 512)}
    hashes = {f"train{length}": fingerprint(d) for length, d in zip(protocol["training_lengths"], training)}
    hashes.update({k: fingerprint(v) for k, v in suite.items()})
    return training, suite, hashes


def historical_inputs(task, length):
    seen = set()
    for path in ("next/sequence/protocol.json", "next/ridge/protocol.json"):
        p = json.loads((ROOT/path).read_text())
        for seed in p["training_seeds"]:
            base = p["data_seed_base"]+1000*seed
            specs = []
            if length in p["training_lengths"]:
                specs.append((base+length, p["training_examples_per_length"]))
            if length == 32:
                specs.append((base+201, p["evaluation_examples"]))
            if length in p["heldout_lengths"]:
                specs.append((base+300+length, p["evaluation_examples"]))
            for rng, count in specs:
                seen.update(input_hashes(make_data(task, rng, count, length)))
    if length in (128, 512):
        from next.sequence.challenge import retrieval
        for path in ("next/sequence/challenge_protocol.json", "next/ridge/challenge_protocol.json"):
            p = json.loads((ROOT/path).read_text())
            for index, spec in enumerate(p["tasks"]):
                if spec["trained_task"] != task or spec["length"] != length:
                    continue
                for seed in p["training_seeds"]:
                    rng = p["data_seed_base"]+1000*seed+index
                    data = make_data(task, rng, spec["examples"], length) if task == "memory" else retrieval(
                        rng, spec["examples"], length, spec["associations"], spec["filler_noise"])
                    seen.update(input_hashes(data))
    return seen


def audit_freshness(protocol):
    rows = []
    for task in protocol["tasks"]:
        old = {n: historical_inputs(task, n) for n in (32, 128, 512)}
        new_seen = {n: set() for n in (32, 128, 512)}
        training_seen = set()
        prepared = []
        for seed in protocol["seeds"]:
            train, suite, hashes = make_suite(task, seed, protocol)
            training_seen.update(input_hashes(train[-1]))
            prepared.append((seed, suite, hashes))
        for seed, suite, hashes in prepared:
            for name, data in suite.items():
                length = data["x"].shape[1]
                current = input_hashes(data)
                overlap = len(current & old[length])+len(current & new_seen[length])
                if length == 32:
                    overlap += len(current & training_seen)
                rows.append(dict(task=task, seed=seed, split=name, sha256=hashes[name],
                                 exact_input_overlap=overlap))
                new_seen[length].update(current)
    return dict(passed=all(r["exact_input_overlap"] == 0 for r in rows), checks=rows,
                scope="Development evaluations against old v3/v4 train/evaluation/challenge inputs, "
                      "all new matching-length training and other development evaluations. "
                      "Short finite-vocabulary training samples themselves can repeat.")
