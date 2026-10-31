"""Freeze original V6, select fixed plans on old dev, then open allocated pairs."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from ..supplement_sources import load_registered
from .engine import enumerate_public, materialize, paths, policy_request
from .registry import (EXPECTED, HERE, MANIFEST_SHA, VIEWS, case_batch, load_original,
                       old_validation, sha, source_pins, write_json)


HISTORICAL = ("fixed_dev_tuned", "risk_neutral_mpc", "risk_aware_recursive", "allocation_only")
SUPPLEMENT_SHA = "6ef40ba738e23ac8cec74d4824632e259eb395cfd64d2a6f4bcfbd1b55e184d4"
SETTINGS = {
    "horizon": 3, "training_seed": 17, "training_profile": "terminal_entropic_ndu",
    "gamma": 2., "continuation_price": .002, "pair_count": 64, "draws": 2,
    "views": list(VIEWS), "view_assignment": "case_index modulo six; one view per source pair",
    "development": {"role": "validation", "pair_offset": 256, "observation_seed": 840001,
                    "initial_noise_seeds": [9310001, 9310003], "observer": "reward"},
    "evaluation": {"role": "closure_v6_oracle", "pair_offset": 0, "observation_seed": 860001,
                   "initial_noise_seeds": [9470001, 9470003], "observer": "audit"},
    "noise_rule": "initial_noise_seeds[draw] + 1009 * case; shared across every path and policy",
    "control": {"cost_penalty": .002, "gamma": 2., "horizon": 2, "search_fraction": .5, "search_work_limit": 32.},
    "historical_work_budget": 64, "bootstrap_seed": 6251041, "bootstrap_replicates": 2000,
    "runtime_threads": 1, "model_update_during_inference": False,
    "oracle_scope": "private-truth finite deterministic endpoint upper bound, not a deployable policy or FBSDE optimum",
    "cost_scope": "oracle penalizes continuation depth only; omits its enumeration/search/observer cost and is not a cost-feasible policy",
}


def ce(values):
    values = np.asarray(values, dtype=np.float64)
    z = -SETTINGS["gamma"] * values
    shift = z.max()
    return float(-(shift + np.log(np.exp(z - shift).mean())) / SETTINGS["gamma"])


def emit(stream, row):
    stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def collect(corpus, original, output, phase, selected):
    snapshot, forecast, observers, identity = load_original(original)
    cfg = SETTINGS[phase]
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    table = {mode: np.empty((64, 2, len(paths(mode)))) for mode in ("full", "allocation")}
    census, identities, policy_n, parity_n = {}, [], 0, 0
    policy_names = tuple(selected) + HISTORICAL if phase == "evaluation" else ()
    with gzip.open(output / "endpoints.jsonl.gz", "xt", compresslevel=3) as endpoints, \
            gzip.open(output / "policies.jsonl.gz", "xt", compresslevel=3) as policy_log:
        for case in range(64):
            batch, view = case_batch(corpus, cfg["role"], case, cfg["pair_offset"], cfg["observation_seed"])
            identities.extend(batch.source_ids[0]); census[view] = census.get(view, 0) + 1
            for draw, base_seed in enumerate(cfg["initial_noise_seeds"]):
                noise_seed = base_seed + 1009 * case
                common = {"case": case, "draw": draw, "view": view, "noise_seed": noise_seed,
                          "source_ids": list(batch.source_ids[0])}
                records = []
                # Feasible controls run before any oracle endpoint is generated.
                if policy_names:
                    shift = (2 * case + draw) % len(policy_names)
                    order = policy_names[shift:] + policy_names[:shift]
                    for rank, policy in enumerate(order):
                        destination = output / "outputs" / f"policy-c{case:03}-d{draw}-{policy}"
                        row = policy_request(snapshot, forecast, batch.observation, noise_seed, policy,
                            selected, destination, observers[cfg["observer"]], batch.target, SETTINGS["control"])
                        row.update(common, execution_order=rank, output_directory=str(destination.relative_to(output)))
                        emit(policy_log, row); records.append(row); policy_n += 1
                indexed = {}
                for mode in ("full", "allocation"):
                    for index, (path, pixels, caption, trace) in enumerate(enumerate_public(snapshot, batch.observation, noise_seed, mode)):
                        destination = output / "outputs" / f"tree-c{case:03}-d{draw}-{mode}-n{index:03}"
                        actual = materialize(destination, pixels, caption, observers[cfg["observer"]], batch.target)
                        row = {**common, **trace, **actual, "mode": mode, "path": list(path), "node": index,
                               "output_directory": str(destination.relative_to(output))}
                        emit(endpoints, row); table[mode][case, draw, index] = actual["metrics"]["utility"]
                        indexed[mode, path] = row
                for record in records:
                    endpoint = indexed[record["mode"], tuple(record["actions"])]
                    if (record["output_hashes"] != endpoint["output_hashes"]
                            or record["metrics"] != endpoint["metrics"]
                            or record["final_state_sha256"] != endpoint["state_sha256"]):
                        raise ValueError("Executed feasible policy differs from its enumerated endpoint")
                    parity_n += 1
            if case % 8 == 7:
                print(json.dumps({"phase": phase, "completed_pairs": case + 1, "policy_requests": policy_n,
                                  "wall_seconds": (time.perf_counter_ns() - wall) / 1e9}), flush=True)
    if len(set(identities)) != 128:
        raise ValueError("Independent source census changed")
    snapshot.verify_integrity(); forecast.verify_integrity()
    np.savez(output / "utilities.npz", **table)
    completion = {"status": "completed", "phase": phase, "identity": identity,
        "source_pairs": 64, "individual_sources": 128, "source_ids_sha256": hashlib.sha256("\n".join(identities).encode()).hexdigest(),
        "view_source_counts": census, "draws_per_source": 2, "endpoint_outputs": 12800,
        "nodes_per_group": {"full": 85, "historical_allocation": 15, "common_initial_allocation_subset": 15},
        "policy_requests": policy_n, "policy_endpoint_exact_parity": parity_n,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "source_sha256": source_pins(), "endpoints_sha256": sha(output / "endpoints.jsonl.gz"),
        "policies_sha256": sha(output / "policies.jsonl.gz"), "utilities_sha256": sha(output / "utilities.npz")}
    write_json(output / "completion.json", completion)
    return table, completion


def select(table):
    selected, scores = {}, {}
    allocation_paths = set(paths("allocation"))
    for space, mode in (("fixed", "full"), ("common_allocation", "full"), ("historical_allocation", "allocation")):
        records = []
        for index, path in enumerate(paths(mode)):
            if space == "common_allocation" and path not in allocation_paths:
                continue
            utility = table[mode][:, :, index] - SETTINGS["continuation_price"] * len(path)
            records.append({"path": list(path), "mode": mode, "space": space,
                            "mean": float(utility.mean()), "ce": ce(utility)})
        scores[space] = records
        for objective in ("mean", "ce"):
            chosen = max(records, key=lambda r: r[objective])
            selected[f"strong_{space}_{objective}"] = {k: chosen[k] for k in ("path", "mode", "space")}
    return {"selected": selected, "scores": scores, "selection_target": "reward observer utility minus .002 continuation depth",
            "tie_rule": "first candidate in depth then declared action order", "audit_observer_used": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("development", "freeze", "evaluation"))
    for name in ("original", "cache", "manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--development", type=Path)
    parser.add_argument("--protocol", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1); torch.use_deterministic_algorithms(True)
    if sha(args.manifest) != MANIFEST_SHA:
        raise ValueError("Source manifest changed")
    if args.phase == "freeze":
        dev = json.loads((args.development / "completion.json").read_text())
        if dev["source_sha256"] != source_pins() or dev["status"] != "completed":
            raise ValueError("Development code changed before freeze")
        allocation = HERE.parent / "SUPPLEMENT_ALLOCATION.json"
        if sha(allocation) != SUPPLEMENT_SHA:
            raise ValueError("Supplement allocation changed")
        pins = source_pins()
        pins.update({str((args.original / name).resolve()): sha(args.original / name) for name in (*EXPECTED, "historical-run.py")})
        pins[str((args.development / "selection.json").resolve())] = sha(args.development / "selection.json")
        protocol = {"schema": "hepta.closure.original-v6-oracle.v1", "study": "v6_oracle", "registered_unix_ns": time.time_ns(),
            "source_allocation_sha256": SUPPLEMENT_SHA, "frozen_candidate_sha256": pins, "settings": SETTINGS,
            "selected": json.loads((args.development / "selection.json").read_text())["selected"], "identity": dev["identity"],
            "original": str(args.original.resolve()), "development": str(args.development.resolve()),
            "new_sources_opened": False, "independent_generator_seeds": 1}
        write_json(args.output, protocol)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "registration.json", {"settings": SETTINGS, "source_sha256": source_pins(),
        "registered_unix_ns": time.time_ns(), "phase": args.phase,
        "protocol_sha256": sha(args.protocol) if args.protocol else None})
    if args.phase == "development":
        corpus = old_validation(args.cache, args.manifest, args.original)
        table, _ = collect(corpus, args.original, args.output, "development", {})
        write_json(args.output / "selection.json", select(table))
    else:
        protocol = json.loads(args.protocol.read_text())
        if protocol["settings"] != SETTINGS or protocol["original"] != str(args.original.resolve()):
            raise ValueError("Frozen evaluation settings changed")
        corpus = load_registered(args.cache, args.manifest, HERE.parent / "SUPPLEMENT_ALLOCATION.json", "v6_oracle", args.protocol)
        collect(corpus, args.original, args.output, "evaluation", protocol["selected"])


if __name__ == "__main__":
    main()
