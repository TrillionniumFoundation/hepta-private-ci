#!/usr/bin/env python3
"""PFT2: simulated transport with actual disk/process recovery of ridge statistics."""
import argparse
import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import numpy as np


def encoded(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def hashed(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def array_hash(value):
    value = np.ascontiguousarray(value, dtype="<f8")
    return hashlib.sha256(str(value.shape).encode() + value.tobytes()).hexdigest()


def seal(message):
    message["contribution_id"] = hashed([message[key] for key in
                                        ["parent_id", "coordinate_id", "objective_id", "client_id", "data_sha256"]])
    message["payload_sha256"] = hashed({key: value for key, value in message.items() if key != "payload_sha256"})
    return message


def durable_write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        stream.write(encoded(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Receiver:
    def __init__(self, header):
        self.header = header
        self.messages = {}

    def accept(self, message):
        for key, status in [("parent_id", "rejected_stale_parent"),
                            ("coordinate_id", "rejected_wrong_coordinates"),
                            ("objective_id", "rejected_wrong_objective")]:
            if message.get(key) != self.header[key]:
                return status
        size = self.header["size"]
        try:
            gram, moment = np.asarray(message["gram"], dtype=float), np.asarray(message["moment"], dtype=float)
            if gram.shape != (size, size) or moment.shape != (size,):
                return "rejected_shape"
            if not np.isfinite(gram).all() or not np.isfinite(moment).all():
                return "rejected_nonfinite"
            if not isinstance(message["count"], int) or message["count"] < 1:
                return "rejected_count"
            expected = seal({key: value for key, value in message.items() if key != "payload_sha256"})
            if expected["contribution_id"] != message["contribution_id"] or expected["payload_sha256"] != message["payload_sha256"]:
                return "rejected_integrity"
        except (KeyError, ValueError, TypeError):
            return "rejected_malformed"
        identity = message["contribution_id"]
        if identity in self.messages:
            return "duplicate" if self.messages[identity]["payload_sha256"] == message["payload_sha256"] else "rejected_conflicting_contribution"
        if not np.allclose(gram, gram.T, atol=1e-10, rtol=1e-10) or np.linalg.eigvalsh(gram)[0] < -1e-9 * max(1.0, np.linalg.norm(gram)):
            return "rejected_non_psd_gram"
        self.messages[identity] = copy.deepcopy(message)
        return "accepted"

    def sums(self):
        size = self.header["size"]
        gram, moment = np.zeros((size, size)), np.zeros(size)
        for identity in sorted(self.messages):
            gram += np.asarray(self.messages[identity]["gram"])
            moment += np.asarray(self.messages[identity]["moment"])
        return gram, moment

    def checkpoint(self, path):
        body = {"header": self.header, "messages": [self.messages[key] for key in sorted(self.messages)]}
        durable_write(path, {"body": body, "body_sha256": hashed(body)})

    @classmethod
    def restore(cls, path):
        envelope = json.loads(Path(path).read_text())
        body = envelope["body"]
        if hashed(body) != envelope["body_sha256"]:
            raise ValueError("Checkpoint checksum does not match")
        receiver = cls(body["header"])
        for message in body["messages"]:
            if receiver.accept(message) != "accepted":
                raise ValueError("Checkpoint contains invalid or duplicate contribution")
        return receiver


def worker(job_path):
    job = json.loads(Path(job_path).read_text())
    receiver = Receiver.restore(job["ledger"])
    restored_count = len(receiver.messages)
    counts = Counter(receiver.accept(message) for message in job["messages"])
    receiver.checkpoint(job["ledger"])
    gram, moment = receiver.sums()
    durable_write(job["result"], {"pid": os.getpid(), "restored_count": restored_count,
                  "counts": dict(counts), "accepted_ids": sorted(receiver.messages),
                  "gram": gram.tolist(), "moment": moment.tolist()})


def client_features(rng, size, client, clients, count):
    focused = np.arange(size) % clients == client
    scales = np.where(focused, 2.0, 0.12)
    mean = np.where(focused, (1 if client % 2 else -1) * 0.8, 0.0)
    return rng.normal(size=(count, size)) * scales + mean


def relative(actual, expected):
    return float(np.linalg.norm(actual - expected) / max(np.linalg.norm(expected), 1e-15))


def experiment(size, seed, clients, ridge):
    rng = np.random.default_rng(np.random.SeedSequence([seed, size, 721]))
    basis = np.linalg.qr(rng.normal(size=(size, size)))[0]
    parent = rng.normal(scale=0.1, size=size)
    truth = rng.normal(size=size) / np.sqrt(size)
    header = {"size": size, "parent_id": array_hash(parent), "coordinate_id": array_hash(basis),
              "objective_id": hashed({"loss": "sum squared residual", "ridge": ridge, "version": 1})}
    messages, matrices, residuals, local_data = [], [], [], []
    for client in range(clients):
        count = max(6, size // 3) + 2 * client
        raw = client_features(rng, size, client, clients, count)
        target = raw @ truth + rng.normal(scale=0.05, size=count)
        matrix, residual = raw @ basis, target - raw @ parent
        gram, moment = matrix.T @ matrix, matrix.T @ residual
        message = {**header, "client_id": str(client), "count": count,
                   "data_sha256": hashed([array_hash(raw), array_hash(target)]),
                   "gram": gram.tolist(), "moment": moment.tolist()}
        messages.append(seal(message))
        matrices.append(matrix)
        residuals.append(residual)
        local_data.append((gram, moment, count))
    matrix, residual = np.vstack(matrices), np.concatenate(residuals)
    central_gram, central_moment = matrix.T @ matrix, matrix.T @ residual
    central = np.linalg.solve(central_gram + ridge * np.eye(size), central_moment)
    total = len(residual)
    local_average = sum(count / total * np.linalg.solve(gram + ridge * count / total * np.eye(size), moment)
                        for gram, moment, count in local_data)
    order = rng.permutation(clients).tolist()
    direct = Receiver(header)
    direct_status = Counter(direct.accept(messages[index]) for index in order + order[::-1])
    direct_gram, direct_moment = direct.sums()
    invalid = copy.deepcopy(messages[0])
    invalid["gram"][0][0] = float("inf")
    nonfinite_status = direct.accept(invalid)
    stale = copy.deepcopy(messages[0])
    stale["parent_id"] = hashed("superseded parent")
    seal(stale)
    wrong_coordinates = copy.deepcopy(messages[1])
    wrong_coordinates["coordinate_id"] = hashed("different action basis")
    seal(wrong_coordinates)
    conflict = copy.deepcopy(messages[0])
    conflict["gram"][0][0] += 1.0
    seal(conflict)
    tampered = copy.deepcopy(messages[1])
    tampered["moment"][0] += 1.0
    first_count = clients - 2
    initial = Receiver(header)
    for index in order[:first_count]:
        if initial.accept(messages[index]) != "accepted":
            raise RuntimeError("Valid initial contribution rejected")
    initial_gram, initial_moment = initial.sums()
    partial = np.linalg.solve(initial_gram + ridge * np.eye(size), initial_moment)
    with tempfile.TemporaryDirectory(prefix="pft2-recovery-") as temp:
        directory = Path(temp)
        ledger, job_path, result_path = directory / "ledger.json", directory / "job.json", directory / "result.json"
        initial.checkpoint(ledger)
        checkpoint_hash = hashlib.sha256(ledger.read_bytes()).hexdigest()
        del initial
        replay = [messages[index] for index in order[::-1] + order]
        job = {"ledger": str(ledger), "result": str(result_path),
               "messages": replay + [stale, wrong_coordinates, conflict, tampered]}
        durable_write(job_path, job)
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--restore-job", str(job_path)],
                                   check=True, capture_output=True, text=True, timeout=60)
        restored = json.loads(result_path.read_text())
        final_ledger_hash = hashlib.sha256(ledger.read_bytes()).hexdigest()
    gram, moment = np.asarray(restored["gram"]), np.asarray(restored["moment"])
    aggregated = np.linalg.solve(gram + ridge * np.eye(size), moment)
    test_rng = np.random.default_rng(np.random.SeedSequence([seed, size, 999]))
    test_balanced = np.vstack([client_features(test_rng, size, client, clients, 128) for client in range(clients)])
    test_shift = test_rng.standard_t(5, size=(1024, size)) / np.sqrt(5 / 3)
    def mse(action, test):
        return float(np.mean((test @ (parent + basis @ action - truth)) ** 2))
    checks = {"central_equivalence": relative(aggregated, central) < 1e-9,
              "sufficient_statistics_equivalence": relative(gram, central_gram) < 1e-12 and relative(moment, central_moment) < 1e-12,
              "order_and_duplicates_invariant": np.array_equal(gram, direct_gram) and np.array_equal(moment, direct_moment),
              "exactly_one_contribution_per_client": len(restored["accepted_ids"]) == clients,
              "independent_process_restore": restored["pid"] != os.getpid() and restored["restored_count"] == first_count,
              "stale_rejected": restored["counts"].get("rejected_stale_parent") == 1,
              "coordinate_rejected": restored["counts"].get("rejected_wrong_coordinates") == 1,
              "conflict_rejected": restored["counts"].get("rejected_conflicting_contribution") == 1,
              "tamper_rejected": restored["counts"].get("rejected_integrity") == 1,
              "nonfinite_rejected": nonfinite_status == "rejected_nonfinite"}
    return {"size": size, "seed": seed, "clients": clients, "samples": total, "ridge": ridge,
            "header": header, "source_data_hashes": [m["data_sha256"] for m in messages],
            "contribution_payload_hashes": [m["payload_sha256"] for m in messages],
            "central_parameter_sha256": array_hash(parent + basis @ central),
            "aggregated_parameter_sha256": array_hash(parent + basis @ aggregated),
            "checkpoint_before_restart_sha256": checkpoint_hash, "checkpoint_after_restart_sha256": final_ledger_hash,
            "arrival_order": order, "dropped_clients_before_recovery": order[first_count:],
            "direct_status": dict(direct_status), "recovery_status": restored["counts"],
            "central_relative_error": relative(aggregated, central),
            "partial_dropout_relative_error": relative(partial, central),
            "local_weight_average_relative_error": relative(local_average, central),
            "balanced_holdout_mse": {"central": mse(central, test_balanced), "aggregated": mse(aggregated, test_balanced),
                                     "local_average": mse(local_average, test_balanced)},
            "shifted_holdout_mse": {"central": mse(central, test_shift), "aggregated": mse(aggregated, test_shift),
                                    "local_average": mse(local_average, test_shift)}, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results/pft2.json")
    parser.add_argument("--seed", type=int, default=731)
    parser.add_argument("--num-seeds", type=int, default=3)
    parser.add_argument("--sizes", default="8,16,32,64")
    parser.add_argument("--clients", type=int, default=7)
    parser.add_argument("--ridge", type=float, default=0.01)
    parser.add_argument("--restore-job", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.restore_job:
        worker(args.restore_job)
        return
    sizes = [int(value) for value in args.sizes.split(",")]
    if min(sizes) < 2 or args.clients < 3 or args.num_seeds < 1 or args.ridge <= 0:
        parser.error("Sizes>=2, clients>=3, num-seeds>=1 and ridge>0 required.")
    start = time.perf_counter()
    records = [experiment(size, seed, args.clients, args.ridge) for size in sizes
               for seed in range(args.seed, args.seed + args.num_seeds)]
    summary = {"runs": len(records), "all_protocol_checks": all(all(r["checks"].values()) for r in records),
               "max_central_relative_error": max(r["central_relative_error"] for r in records),
               "mean_local_average_relative_error": float(np.mean([r["local_weight_average_relative_error"] for r in records])),
               "local_average_worse_shifted_holdout_runs": sum(r["shifted_holdout_mse"]["local_average"] > r["shifted_holdout_mse"]["central"] for r in records)}
    payload = {"experiment": "PFT2", "protocol_version": "shared-parent-ridge-stats-v1",
               "created_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "numpy": np.__version__,
               "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "configuration": {"sizes": sizes, "seed": args.seed, "num_seeds": args.num_seeds, "clients": args.clients, "ridge": args.ridge},
               "transport": "SIMULATED message delivery on one host; recovery runs in a separate real Python process from an fsynced disk checkpoint.",
               "objective": "theta=theta_parent+B*a; sum_i||X_i*B*a-(y_i-X_i*theta_parent)||^2+ridge*||a||^2. Shared parent and orthogonal B. Local-average comparator allocates ridge proportional to each client's sample count.",
               "limitations": ["No physical multi-host network, latency, partitions, service discovery or Byzantine consensus tested.",
                               "Hashes detect identity/integrity mismatch; a coherent fabricated dataset/statistic is not detected.",
                               "Independent-process checkpoint restore is exercised; forced OS power loss and filesystem corruption are not.",
                               "Sufficient statistics can leak private information; no privacy mechanism is claimed.",
                               "Different parent, coordinates or objective require recomputation; no asynchronous nonlinear aggregation claim.",
                               "Finite float64 sums/solves yield numerical equivalence, not identical parameter bytes across central and aggregated accumulation."],
               "records": records, "summary": summary, "elapsed_seconds": time.perf_counter() - start}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded(payload) + "\n")
    print(encoded({"output": str(args.output), "summary": summary, "elapsed_seconds": payload["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
