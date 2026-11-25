"""Cold-process cost replay of sealed relation candidates; never opens test.

Each method pays its own interpreter/optimizer initialization, parent load,
train/dev generation and feature extraction. Numerical differences are reported,
never used to replace the original candidates or to select a method.
"""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from copy import deepcopy
import json
from pathlib import Path
import resource
import subprocess
import sys
import traceback

import numpy as np
import torch

from . import baselines_run as companion
from . import programs
from . import provenance


PARENTS = tuple(f"n8-s{s}" for s in (17011, 27011, 37011))


def freeze(root, original_root):
    p = companion.load(original_root)
    if p["suite"] != "programs":
        raise ValueError("a frozen program campaign is required")
    parents = {}
    for parent_id in PARENTS:
        directory = original_root/parent_id
        seal = programs.validate_prepared(directory, p)
        parents[parent_id] = {"seal_sha256": programs.digest(directory/"SEAL.json"),
                              "parent_digest": seal["parent_digest"]}
    protocol = {"schema": "hcsn-known-rule-cold-cost-replay-v1",
        "original_root": str(original_root.resolve()), "original_protocol_sha256": programs.identity(p),
        "implementation": companion.implementation(), "cost_replay_sha256": programs.digest(__file__),
        "runtime": p["runtime"], "parents": parents, "methods": list(programs.METHODS),
        "slots": [f"{parent}--{method}" for parent in PARENTS for method in programs.METHODS],
        "selection": "none; original sealed candidates remain authoritative",
        "splits": ["train", "dev"], "test_constructed": False,
        "scope": "fresh process per parent/method including independent parent load, features, update, evidence and validation; original transfer/test experiments not replayed",
        "candidate_comparison_atol": 1e-10, "candidate_comparison_rtol": 1e-10,
        "discovery_cost": None, "discovery_cost_reason": "human/agent rule authoring was not instrumented"}
    root.mkdir(parents=True, exist_ok=False)
    programs.create_json(root/"PROTOCOL.json", protocol)
    return protocol


def load(root):
    protocol = provenance.read(root/"PROTOCOL.json")
    if protocol["implementation"] != companion.implementation() or protocol["cost_replay_sha256"] != programs.digest(__file__):
        raise ValueError("cost replay source changed")
    p = companion.load(Path(protocol["original_root"]))
    if programs.identity(p) != protocol["original_protocol_sha256"] or p["runtime"] != protocol["runtime"]:
        raise ValueError("original program protocol/runtime changed")
    if protocol["splits"] != ["train", "dev"] or protocol["test_constructed"] is not False:
        raise ValueError("cost replay has no holdout capability")
    return protocol, p


def compare_tensor_dict(actual, expected, protocol):
    if set(actual) != set(expected):
        raise ValueError("candidate tensor schema changed")
    return {name: {"exact": bool(torch.equal(actual[name], expected[name])),
        "close": bool(torch.allclose(actual[name], expected[name],
            atol=protocol["candidate_comparison_atol"], rtol=protocol["candidate_comparison_rtol"])),
        "max_abs_error": float((actual[name]-expected[name]).abs().max())} for name in actual}


def one_method(root, protocol, p, slot):
    if slot not in protocol["slots"]:
        raise ValueError("undeclared replay slot")
    parent_id, method = slot.split("--")
    directory = root/slot; directory.mkdir(parents=True, exist_ok=False)
    phases, details = [], {"labels_read": 0, "closures": 0, "solves": 0}
    status, error = "completed", None
    old_directory = Path(protocol["original_root"])/parent_id
    programs.create_json(directory/"STARTED.json", {"slot": slot, "protocol_sha256": programs.identity(protocol),
                                                   "started_unix": time.time()})
    with programs.phase(phases, "sealed_original_preflight_and_parent_load"):
        if programs.digest(old_directory/"SEAL.json") != protocol["parents"][parent_id]["seal_sha256"]:
            raise ValueError("original candidate seal changed")
        seal = programs.validate_prepared(old_directory, p)
        prepared = provenance.read(old_directory/"PREPARED.json")
        parent, parent_identity = companion.load_parent(p, parent_id)
        parent.eval()
        if parent_identity != seal["parent_identity"] or programs.tensor_digest(parent.state_dict()) != seal["parent_digest"]:
            raise ValueError("selected parent identity changed")
        reference = torch.load(old_directory/(method+".pt"), weights_only=True, map_location="cpu")
    with programs.phase(phases, "independent_train_development_generation"):
        training = programs.make_pair_data("train", p)
        development = programs.make_pair_data("dev", p)
        if training.digest() != prepared["train_digest"] or development.digest() != prepared["dev_digest"]:
            raise ValueError("replay data differs from original sealed data")
    with programs.phase(phases, "independent_parent_feature_extraction"):
        train_cache = programs.extract(parent, training, chunk=p["chunk"])
        dev_cache = programs.extract(parent, development, chunk=p["chunk"])
    with programs.phase(phases, "feature_identity_validation_and_evidence_write"):
        features_exact = {}
        for split, cache, pairs in (("TRAIN", train_cache, training), ("DEV", dev_cache, development)):
            actual = {**{k: v.numpy() for k, v in cache.items()},
                      "labels": pairs.labels.numpy(), "source": pairs.a.source.numpy()}
            with np.load(old_directory/(split+"_FEATURES.npz"), allow_pickle=False) as archived:
                if set(archived.files) != set(actual):
                    raise ValueError("sealed feature array schema changed")
                features_exact[split] = {key: bool(np.array_equal(value, archived[key])) for key, value in actual.items()}
                if not all(features_exact[split].values()):
                    raise ValueError("recomputed features differ; no candidate replacement permitted")
            np.savez_compressed(directory/(split+"_FEATURES.npz"), **actual)
    with programs.phase(phases, "projection_dictionary_and_incumbent_construction"):
        incumbent = programs.RelationHead(parent.readout.state_dict())
        design = incumbent.dictionary(train_cache["a"], train_cache["b"])
        head = deepcopy(incumbent)
    try:
        with programs.phase(phases, "program_generation_or_initialization"):
            if method in ("STRICT_WSP", "HYBRID"):
                head.load_state_dict(programs.strict_program(parent.readout.state_dict()))
        if method in ("BP", "ANALYTIC", "HYBRID"):
            with programs.phase(phases, "supervised_update_with_cold_optimizer_setup"):
                programs.fit_head(head, design, training.labels, method, p, receipt=details)
    except Exception as exc:
        status, error, head = "failed_kept_incumbent", repr(exc), deepcopy(incumbent)
    with programs.phase(phases, "development_validation"):
        metrics, scores = programs.metrics(head, dev_cache, development)
    with programs.phase(phases, "candidate_write_reload_and_original_comparison"):
        candidate = {"slot": slot, "original_protocol_sha256": programs.identity(p),
                     "cost_protocol_sha256": programs.identity(protocol), "model_state": head.state_dict()}
        with (directory/"CANDIDATE.pt").open("xb") as out:
            torch.save(candidate, out)
        loaded = torch.load(directory/"CANDIDATE.pt", weights_only=True, map_location="cpu")
        if programs.tensor_digest(loaded["model_state"]) != programs.tensor_digest(head.state_dict()):
            raise ValueError("replay serialization changed candidate")
        comparison = compare_tensor_dict(head.state_dict(), reference["model_state"], protocol)
        original_head = programs.RelationHead(parent.readout.state_dict())
        original_head.load_state_dict(reference["model_state"])
        _, old_scores = programs.metrics(original_head, dev_cache, development)
        score_comparison = {"exact": bool(torch.equal(scores, old_scores)),
            "max_abs_error": float((scores-old_scores).abs().max()),
            "decision_disagreements": int(((scores > 0) != (old_scores > 0)).sum())}
        np.savez_compressed(directory/"DEV_PREDICTIONS.npz", scores=scores.numpy(),
            original_scores=old_scores.numpy(), labels=development.labels.numpy(), source=development.a.source.numpy())
        if programs.tensor_digest(parent.state_dict()) != seal["parent_digest"]:
            raise ValueError("protected parent changed")
    result = {"slot": slot, "status": status, "error": error, "parent_identity": parent_identity,
        "protocol_sha256": programs.identity(protocol), "original_protocol_sha256": programs.identity(p),
        "original_candidate_sha256": programs.digest(old_directory/(method+".pt")),
        "original_status": prepared["methods"][method]["status"], "optimization": details,
        "original_optimization": prepared["methods"][method]["optimization"],
        "development": metrics, "features_exact": features_exact, "candidate_comparison": comparison,
        "candidate_all_exact": all(v["exact"] for v in comparison.values()),
        "candidate_all_close": all(v["close"] for v in comparison.values()),
        "development_score_comparison": score_comparison,
        "candidate_sha256": programs.digest(directory/"CANDIDATE.pt"), "phases": phases,
        "test_constructed": False, "original_candidates_replaced": False, "discovery_cost": None,
        "scope": protocol["scope"]}
    programs.create_json(directory/"RESULT.json", result)
    return status


def worker(root, protocol, p, slot):
    status, error = "failed", None
    try:
        status = one_method(root, protocol, p, slot)
    except Exception:
        error = traceback.format_exc()
        raise
    finally:
        directory = root/slot; directory.mkdir(parents=True, exist_ok=True)
        programs.create_json(directory/"WORKER_COST.json", {"status": status, "error": error,
            "protocol_sha256": programs.identity(protocol), "process_cpu_through_receipt": time.process_time(),
            "wall_from_first_module_statement": time.perf_counter()-ENTRY_WALL,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            "scope": "fresh worker imports, protocol/parent/candidate load, all computations, evidence and result writes; receipt serialization and shutdown excluded",
            "energy_joules": None})
    return 0 if status == "completed" else 1


def campaign(root, protocol):
    programs.create_json(root/"CAMPAIGN_CLAIM.json", {"protocol_sha256": programs.identity(protocol), "started_unix": time.time()})
    start, cpu = time.perf_counter(), time.process_time(); failures = []
    logs = root/"logs"; logs.mkdir()
    for slot in protocol["slots"]:
        before = resource.getrusage(resource.RUSAGE_CHILDREN); launched = time.perf_counter()
        def limits():
            resource.setrlimit(resource.RLIMIT_CPU, (180, 190))
            resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
        timed_out = False
        with (logs/(slot+".stdout")).open("xb") as out, (logs/(slot+".stderr")).open("xb") as err:
            try:
                process = subprocess.run([sys.executable, "-m", __package__+".cost_replay", "worker",
                    "--root", str(root), "--slot", slot], stdout=out, stderr=err,
                    timeout=300, preexec_fn=limits)
                code = process.returncode
            except subprocess.TimeoutExpired:
                code, timed_out = 124, True
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {"slot": slot, "protocol_sha256": programs.identity(protocol), "returncode": code,
            "timed_out": timed_out, "launch_to_exit_wall_seconds": time.perf_counter()-launched,
            "child_user_cpu_seconds": after.ru_utime-before.ru_utime,
            "child_system_cpu_seconds": after.ru_stime-before.ru_stime,
            "scope": "fresh sequential child; interpreter startup through shutdown; no shared feature allocation"}
        directory = root/slot; directory.mkdir(exist_ok=True)
        programs.create_json(directory/"LAUNCH_COST.json", record)
        print(json.dumps(record), flush=True)
        if code != 0:
            failures.append(slot)
    programs.create_json(root/"TERMINAL.json", {"status": "completed_with_failures" if failures else "completed",
        "failed_slots": failures, "campaign_wall_seconds": time.perf_counter()-start,
        "coordinator_cpu_seconds": time.process_time()-cpu, "finished_unix": time.time(),
        "scope": "coordinator CPU excludes children; campaign wall includes all children"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "campaign", "worker"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--slot")
    args = parser.parse_args(); torch.set_num_threads(1)
    if args.action == "freeze":
        if args.original_root is None:
            parser.error("freeze requires --original-root")
        protocol = freeze(args.root, args.original_root)
        print(json.dumps({"protocol_sha256": programs.identity(protocol), "test_constructed": False}), flush=True)
        return 0
    protocol, p = load(args.root)
    if args.action == "campaign":
        campaign(args.root, protocol); return 0
    if args.slot not in protocol["slots"]:
        parser.error("worker requires a declared slot")
    return worker(args.root, protocol, p, args.slot)


if __name__ == "__main__":
    raise SystemExit(main())
