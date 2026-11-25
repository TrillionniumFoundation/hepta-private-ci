"""One-time equivalence study on sealed HCSN train/development feature caches.

Original final tests are never opened. Development is descriptive verification,
not an independent new-user evaluation. New heads have the same linear response
in every method, with one global ridge penalty and no backbone update.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .pft_linear import solve_normal
from .pft_peer import canonical, create_json, run_ring, sha


PARENTS = [f"n{n}-s{s}" for n in (8, 32, 64) for s in (17011, 27011, 37011)]


def read(path):
    return json.loads(Path(path).read_text())


def design(cache):
    return np.column_stack((cache["a"].astype(np.float64),
                            cache["b"].astype(np.float64), np.ones(len(cache["a"]))))


def check_original(root):
    seal = read(root / "SEAL.json")
    for name in ("STARTED.json", "PREPARED.json", "TRAIN_FEATURES.npz", "DEV_FEATURES.npz"):
        if sha(root / name) != seal["files"][name]:
            raise ValueError("original feature or parent identity bytes changed: " + name)
    prepared = read(root / "PREPARED.json")
    started = read(root / "STARTED.json")
    if (prepared["parent_digest"] != seal["parent_digest"]
            or started["parent_identity"] != seal["parent_identity"]):
        raise ValueError("parent identity differs from original seal")
    return seal, prepared


def one_case(root, output, protocol_hash):
    wall = time.perf_counter()
    output.mkdir()
    seal, prepared = check_original(root)
    feature_started = time.perf_counter()
    with np.load(root / "TRAIN_FEATURES.npz", allow_pickle=False) as z:
        x, y, groups = design(z), 2 * z["labels"].astype(np.float64) - 1, z["source"].copy()
    # Only training determines scaling. The identical fixed transform is reused.
    scale = np.maximum(np.sqrt(np.mean(x * x, axis=0)), 1e-6)
    x = x / scale
    feature_seconds = time.perf_counter() - feature_started
    binding = dict(protocol_sha256=protocol_hash, parent_digest=seal["parent_digest"],
                   train_sha256=seal["files"]["TRAIN_FEATURES.npz"],
                   feature_transform="concat(a,b,1)/train_rms_floor_1e-6", scale=scale.tolist(),
                   target="2*[AND,OR,XOR]-1", loss="half_sum_squared_plus_0.1_norm_squared")
    create_json(output / "FEATURE_BINDING.json", binding)
    ridge = .2
    full_started = time.perf_counter()
    gram, rhs = x.T @ x, x.T @ y
    full = solve_normal(gram, rhs, ridge)
    full_seconds = time.perf_counter() - full_started
    sub_started = time.perf_counter()
    _, singular, vt = np.linalg.svd(x, full_matrices=False)
    rank = int(np.count_nonzero(singular > singular[0] * 1e-12))
    q = vt[:rank].T
    compressed = q @ solve_normal(q.T @ gram @ q, q.T @ rhs, ridge)
    compressed_seconds = time.perf_counter() - sub_started
    distribution_started = time.perf_counter()
    sources = sorted(set(groups.tolist()))
    if len(sources) != 12:
        raise ValueError("expected all twelve original training source groups")
    shards, local, counts = [], [], []
    for index, partition in enumerate((sources[:1], sources[1:3], sources[3:6], sources[6:])):
        take = np.isin(groups, partition)
        shard = output / f"shard{index}.npz"
        with shard.open("xb") as stream:
            np.savez_compressed(stream, x=x[take], y=y[take])
        shards.append(shard)
        counts.append(int(take.sum()))
        local.append(solve_normal(x[take].T @ x[take], x[take].T @ y[take], ridge * take.sum() / len(x)))
    distribute_seconds = time.perf_counter() - distribution_started
    ring = run_ring(shards, binding, output / "ring", ridge)
    peer_weights, peers = [], []
    for peer in range(4):
        with np.load(output / "ring" / f"peer{peer}" / "candidate.npz", allow_pickle=False) as z:
            peer_weights.append(z["weight"].copy())
        peers.append(read(output / "ring" / f"peer{peer}" / "RECEIPT.json"))
    # Verify only after every peer candidate has been written. No candidate selection.
    validation_started = time.perf_counter()
    with np.load(root / "DEV_FEATURES.npz", allow_pickle=False) as z:
        dx, dy = design(z) / scale, 2 * z["labels"].astype(np.float64) - 1
    weights = dict(full=full, compressed=compressed, peer=peer_weights[0],
                   naive_equal=np.mean(local, axis=0), naive_weighted=np.average(local, axis=0, weights=counts))
    metrics = {}
    for name, weight in weights.items():
        residual = x @ weight - y
        metrics[name] = dict(objective=float(.5 * (np.sum(residual ** 2) + ridge * np.sum(weight ** 2))),
            development_accuracy=np.mean((dx @ weight >= 0) == (dy > 0), axis=0).tolist(),
            development_squared_error=float(np.mean((dx @ weight - dy) ** 2)))
    with (output / "cold-observations.npz").open("xb") as stream:
        np.savez_compressed(stream, x=dx)
    cold_started = time.perf_counter()
    cold = subprocess.run([sys.executable, "-m", "qualification.hcsn_closure_20261124.pft_peer", "replay",
        "--candidate", str(output / "ring" / "peer0" / "candidate.npz"),
        "--observations", str(output / "cold-observations.npz"),
        "--output", str(output / "COLD.json")], capture_output=True, text=True, timeout=60)
    (output / "cold.stderr").write_text(cold.stderr)
    cold_seconds = time.perf_counter() - cold_started
    if cold.returncode:
        raise RuntimeError("cold replay failed; stderr preserved")
    cold_value = read(output / "COLD.json")
    errors = dict(compressed_weight=float(np.max(np.abs(full - compressed))),
                  peer_weight=float(max(np.max(np.abs(full - weight)) for weight in peer_weights)),
                  peer_agreement=float(max(np.max(np.abs(peer_weights[0] - w)) for w in peer_weights)),
                  cold_prediction=float(np.max(np.abs(np.asarray(cold_value["predictions"]) - dx @ peer_weights[0]))))
    passed = (np.allclose(full, compressed, rtol=1e-7, atol=1e-7)
              and all(np.allclose(full, w, rtol=1e-7, atol=1e-7) for w in peer_weights)
              and errors["cold_prediction"] == 0
              and cold_value["pid"] not in ring["peer_pids"])
    validation_seconds = time.perf_counter() - validation_started
    historical = dict(parent_launch_seconds=seal["parent_identity"]["inherited_launch_cost"]["launch_through_exit_wall_seconds"],
                      shared_cost=prepared["shared_cost"],
                      cost_scope="historical original measurements; not rerun, not speedup denominator")
    result = dict(parent=root.name, n=len(x), parameter_shape=list(full.shape), effective_rank=rank,
        shard_counts=counts, errors=errors, passed=bool(passed), metrics=metrics,
        own_feature_response_seconds=feature_seconds, direct_gram_solve_seconds=full_seconds,
        compression_and_solve_seconds=compressed_seconds, shard_write_and_local_control_seconds=distribute_seconds,
        ring_launch_to_exit_seconds=ring["launch_to_exit_seconds"],
        validation_including_cold_seconds=validation_seconds, cold_launch_to_exit_seconds=cold_seconds,
        peers=peers, historical=historical, total_case_wall_seconds=time.perf_counter() - wall,
        final_test_opened=False, independent_new_user_claim=False,
        cost_note="phase clocks are sequential except per-peer diagnostics; never sum parallel peer times; original feature costs separate")
    with (output / "SOLUTIONS.npz").open("xb") as stream:
        np.savez_compressed(stream, **weights, scale=scale)
    create_json(output / "RESULT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    originals = {p: dict(seal_sha256=sha(args.cache_root / p / "SEAL.json"),
                        train_sha256=sha(args.cache_root / p / "TRAIN_FEATURES.npz"),
                        dev_sha256=sha(args.cache_root / p / "DEV_FEATURES.npz")) for p in PARENTS}
    source = {p: sha(Path(__file__).with_name(p)) for p in ("pft_linear.py", "pft_peer.py", "pft_ring_qualification.py")}
    protocol = dict(schema="hcsn-pft-ring-equivalence-v1", parents=PARENTS, originals=originals,
        source_sha256=source, peers=4, ridge=.2, partition_sizes=[1, 2, 3, 6],
        transform="concat(a,b,1)/train_rms_floor_1e-6", target="2*[AND,OR,XOR]-1",
        action_rank_rtol=1e-12, solve_rtol=1e-7, solve_atol=1e-7,
        candidate_selection="none; every frozen parent, method and failure retained",
        final_test_access="prohibited; historical development only", source_scope="synthetic_sources_actual_HCSN_features")
    create_json(output / "PROTOCOL_FROZEN.json", protocol)
    protocol_hash = hashlib.sha256(canonical(protocol)).hexdigest()
    rows = []
    for parent in PARENTS:
        try:
            rows.append(one_case(args.cache_root / parent, output / parent, protocol_hash))
        except Exception as error:
            rows.append(dict(parent=parent, passed=False, error=repr(error)))
        print(json.dumps({"parent": parent, "passed": rows[-1]["passed"], "error": rows[-1].get("error")}), flush=True)
    result = dict(protocol_sha256=protocol_hash, rows=rows, expected=9,
                  passed=sum(row["passed"] for row in rows), total_wall_seconds=time.perf_counter() - started,
                  scope="same-host four-peer engineering equivalence; no new scientific performance or real A-B qualification")
    create_json(output / "RESULTS.json", result)
    raise SystemExit(0 if result["passed"] == 9 else 1)


if __name__ == "__main__":
    main()
