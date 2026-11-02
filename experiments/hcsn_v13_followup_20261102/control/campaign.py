"""Seal new value readers, then execute historical TEST only after publication."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from ..joint_core.campaign import configure
from ..joint_core.data import legacy_data, labels_of
from .runtime import episode, sha
from .value_fit import ROOT, read_plan, load, write


def freeze(run):
    plan = read_plan(run)
    candidates = []
    for task in plan["protocol"]["tasks"]:
        for family in plan["protocol"]["families"]:
            for seed in plan["protocol"]["seeds"]:
                directory = run / f"fit-{task}-{family}-{seed}"
                _, _, _, metadata = load(directory)
                if metadata["plan_sha256"] != sha(run / "PLAN.json") or metadata["test_opened"]:
                    raise RuntimeError("Candidate differs from this untouched TEST plan")
                candidates.append({"directory": directory.name, "task": task, "family": family, "seed": seed,
                    "files": {name: sha(directory / name) for name in ("VALUE.pt", "CANDIDATE.json", "FUTURE_TARGETS.jsonl.gz")}})
    for task in plan["protocol"]["tasks"]:
        for seed in plan["protocol"]["seeds"]:
            metadata = [json.loads((run / item["directory"] / "CANDIDATE.json").read_text())
                        for item in candidates if item["task"] == task and item["seed"] == seed]
            if len({m["initial_reader_state_sha256"] for m in metadata}) != 1 or len({m["minibatch_stream_sha256"] for m in metadata}) != 1:
                raise RuntimeError("Common reader initialization or minibatch stream differs")
    write(run / "CANDIDATES.json", {"schema": "hcsn-v13-joint-value-candidates.v1", "models": candidates,
          "plan_sha256": sha(run / "PLAN.json"), "test_opened": False})


def publication_gate(run, publication):
    receipt = json.loads(publication.read_text())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if receipt.get("local_head") != head or receipt.get("all_stage_root_trees_exact") is not True:
        raise RuntimeError("Verified publication must bind the current complete local source tree")
    if len(receipt.get("remote_head", "")) != 40:
        raise RuntimeError("Exact published remote commit required")
    plan = read_plan(run)
    candidates = json.loads((run / "CANDIDATES.json").read_text())
    if candidates["plan_sha256"] != sha(run / "PLAN.json") or candidates["test_opened"]:
        raise RuntimeError("Reader seal changed before TEST")
    required = [run / "PLAN.json", run / "CANDIDATES.json"]
    required += [ROOT / path for path in plan["source_sha256"]]
    required += [run / path for path in plan["packets"]]
    for item in candidates["models"]:
        directory = run / item["directory"]
        for name, digest in item["files"].items():
            if sha(directory / name) != digest:
                raise RuntimeError("Published new value candidate changed")
            required.append(directory / name)
        metadata = json.loads((directory / "CANDIDATE.json").read_text())
        core = ROOT / metadata["model_directory"]
        required += [core / name for name in ("TRAIN.json", "weights.pt", "NORMALIZATION.npz")]
    entries = subprocess.check_output(["git", "ls-tree", "-rz", head]).split(b"\0")
    committed = {row.split(b"\t", 1)[1].decode(): row.split(b"\t", 1)[0].split()[2].decode()
                 for row in entries if row}
    for path in required:
        content = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if committed.get(str(path.resolve().relative_to(ROOT))) != blob:
            raise RuntimeError("Required bytes are not in the actual published local tree")
    return plan, candidates, receipt


def evaluate(run, publication):
    plan, candidates, receipt = publication_gate(run, publication)
    out = run / "evaluation"
    out.mkdir()
    write(out / "BEFORE_TEST_GATE.json", {"remote_head": receipt["remote_head"], "local_head": receipt["local_head"],
          "publication_sha256": sha(publication), "candidates_sha256": sha(run / "CANDIDATES.json"),
          "gate_passed_before_test_loader": True, "scientific_confirmation": False})
    packets, identities = {}, {}
    for task in plan["protocol"]["tasks"]:
        data = legacy_data(task, "test")
        packets[task] = {key: data[key] for key in ("x", "valid", "observed", "relative_times")}
        packets[task]["labels"] = np.asarray(labels_of(data), dtype=np.int64)
        np.savez_compressed(out / (task + "-historical-TEST.npz"), **packets[task])
        identities[task] = {"ids": data["ids"].astype(str).tolist(), "source_array_sha256": data["metadata"]["array_sha256"],
                            "materialized_packet_sha256": sha(out / (task + "-historical-TEST.npz")),
                            "role": "previously exposed historical TEST development replay"}
    write(out / "TEST_IDENTITIES.json", identities)
    rows = []
    with gzip.open(out / "TRACES.jsonl.gz", "xt") as stream:
        for item in candidates["models"]:
            candidate = load(run / item["directory"])
            data = packets[item["task"]]
            public = {key: data[key] for key in ("x", "valid", "observed", "relative_times")}
            for index, truth in enumerate(data["labels"]):
                for policy in plan["protocol"]["policies"]:
                    execution, updates = episode(candidate, public, index, policy)
                    correct = int(execution["output"]["predicted_class"] == int(truth))
                    utility = correct - execution["observation_fee"] - execution["latency_fee"] - execution["deadline_penalty"]
                    row = {"task": item["task"], "family": item["family"], "seed": item["seed"], "index": index,
                           "policy": policy, "label_for_scoring_only": int(truth), "correct": correct,
                           "requests": execution["requested_observations"], "utility": utility}
                    rows.append(row)
                    stream.write(json.dumps({**row, "execution": execution, "updates": updates}, allow_nan=False) + "\n")
    write(out / "SUMMARY.json", {"schema": "hcsn-v13-joint-dynamic-historical-evaluation.v1", "rows": rows,
          "executions": len(rows), "remote_candidate_head": receipt["remote_head"], "trace_sha256": sha(out / "TRACES.jsonl.gz"),
          "test_identities_sha256": sha(out / "TEST_IDENTITIES.json"),
          "scope": "Actual new joint content inference and frozen new-head value policy on previously exposed historical TEST",
          "scientific_confirmation": False, "all_blockers_closed": False, "production_activation": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "evaluate"))
    parser.add_argument("--run", type=Path, required=True); parser.add_argument("--publication", type=Path)
    args = parser.parse_args(); configure()
    if args.command == "freeze": freeze(args.run)
    else: evaluate(args.run, args.publication)
