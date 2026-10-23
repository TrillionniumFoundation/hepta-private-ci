"""Precommitted same-host IPC replay of previously archived real E1 artifacts.

No model download, Encoder execution, training, new data claim or network service.
Latency is descriptive for this shared host; process startup is reported separately.
"""

import argparse
import ast
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import stat
import time
from unittest.mock import patch

import numpy as np
import torch

from cell_evolution_snapshot import EvolutionBudgetV1, EvolutionError, WithdrawalViewV1, group_digest, load_snapshot
from cell_process_owner import SnapshotProcessOwnerV1, SnapshotWorkerPoolV1
from cell_process_protocol import ProcessInferenceError
from feature_bundle import FeatureBundleV1, FeatureIdentityV1
from native_latent import LightCellHead

E2_INVENTORY_SHA256 = "55883610c693991ba68951a0380e8c19dcdfe70d048527c8fa34ac9c386a7a8a"
SEEDS = (7, 17, 29)
ARMS = ("parent", "split")
ROLES = ("future_1", "future_2", "ood")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(data)
    return sha(data)


def dependencies():
    directory = Path(__file__).resolve().parent
    pending, result = [Path(__file__).resolve()], {}
    while pending:
        path = pending.pop()
        if path.name in result:
            continue
        data = path.read_bytes()
        result[path.name] = sha(data)
        for node in ast.walk(ast.parse(data)):
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                     [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                candidate = directory / (name.split(".")[0] + ".py")
                if candidate.is_file():
                    pending.append(candidate)
    return dict(sorted(result.items()))


def read_pinned(root, records, name):
    record = records[name]
    path = root / name
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or not 0 < info.st_size == record["original_bytes"] <= 8 * 1024 * 1024):
        raise ValueError("source file boundary changed")
    data = path.read_bytes()
    if sha(data) != record["original_sha256"]:
        raise ValueError("source bytes differ from retained E2 inventory")
    return data


class Withdrawals:
    def __init__(self, scope):
        self.view = WithdrawalViewV1(scope)

    def __call__(self):
        return self.view

    def revoke(self, source):
        self.view = replace(self.view, epoch=self.view.epoch + 1,
            revoked_source_digests=tuple(sorted(set(self.view.revoked_source_digests) | {source})))


def reference(snapshot, bundle, provider):
    calls = {"head_example_calls": 0, "head_module_forwards": 0}
    original = LightCellHead.forward
    def observe(module, features, state):
        calls["head_example_calls"] += len(features)
        calls["head_module_forwards"] += 1
        return original(module, features, state)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    with patch.object(LightCellHead, "forward", new=observe):
        output = snapshot.predict_task(bundle, provider)
    return output, {**calls, "elapsed_ns": time.perf_counter_ns() - started,
                    "owner_cpu_ns": time.process_time_ns() - cpu}


def serializable(output):
    return {k: value.tolist() if isinstance(value, torch.Tensor) else value for k, value in output.items()}


def children_cpu():
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"user_seconds": value.ru_utime, "system_seconds": value.ru_stime,
            "minor_faults": value.ru_minflt, "major_faults": value.ru_majflt,
            "voluntary_context_switches": value.ru_nvcsw, "involuntary_context_switches": value.ru_nivcsw}


def total_head_calls(pool):
    return sum(h["example_calls"] for worker in pool.counts() for h in worker["heads"].values())


def must_reject(function):
    try:
        function()
    except (EvolutionError, ProcessInferenceError) as exc:
        return {"rejected": True, "error_type": type(exc).__name__, "reason": str(exc)}
    raise AssertionError("invalid process result was accepted")


def run_probe(source_root, inventory_path, output):
    torch.set_num_threads(1)
    torch.set_default_dtype(torch.float32)
    source_root, target = Path(source_root), Path(output)
    target.mkdir(parents=False, exist_ok=False)
    inventory_bytes = Path(inventory_path).read_bytes()
    if sha(inventory_bytes) != E2_INVENTORY_SHA256:
        raise ValueError("retained E2 inventory pin differs")
    inventory = json.loads(inventory_bytes)
    records = {r["source_path"]: r for r in inventory["files"]}
    prefixes = tuple(f"seed-{seed}/{arm}/" for seed in SEEDS for arm in ARMS)
    names = sorted(n for n in records if n.startswith(prefixes) or n in ("features.npz", "feature_manifest.json"))
    inputs = {n: {k: records[n][k] for k in ("original_bytes", "original_sha256")} for n in names}
    for name in names:
        read_pinned(source_root, records, name)
    plan = {"schema": "hepta.real-local-process-plan.v2", "source_evolution_inventory_sha256": E2_INVENTORY_SHA256,
        "source_root": str(source_root), "input_files": inputs, "seeds": list(SEEDS), "arms": list(ARMS),
        "roles": list(ROLES), "worker_counts": [1, 2], "repetitions_per_role": 2,
        "start_method": "spawn", "timeout_seconds": 30, "torch_threads_per_process": 1,
        "worker_lifetime_request_limit_including_load": 1024,
        "prior_plan_sha256": "ff4d575b9c3eec8bea3f719785ae89d9bd1fb6916ba8b6f99df5d9fce996650d",
        "change_from_v1": "bounded pool lifetime; same data, artifacts, predictions and scientific configuration",
        "paired_head_batch_shapes_preserved_across_worker_counts": True,
        "exact_float_prediction_and_route_parity_required": True,
        "controller": "host-created shared counters on actual worker Head forward hooks; trusted local code",
        "cpu_measurement": "owner process_time_ns; per-request worker process_time_ns; independently joined-child getrusage delta",
        "ipc_measurement": "actual send_bytes/recv_bytes payload lengths plus CPython POSIX four-byte frame headers; excludes spawn bootstrap",
        "inference_latency_includes": "owner integrity/frontier checks, routing, JSON/base64, IPC, worker artifact checks, selected Head, final owner checks",
        "tensor_residency": "full snapshot loaded in owner and every worker; duplicate copies reported, not equal total resident memory",
        "negative_cases": ["ancestral withdrawal before dispatch in every pool", "withdrawal after execution",
                           "generation commit after execution", "actual worker crash", "actual SIGSTOP timeout",
                           "lifetime request cap exhausted before routing"],
        "labels_used": False, "encoder_runs": 0, "optimizer_steps": 0, "new_data_or_holdout_claim": False,
        "physical_nodes": 1, "remote_network": False, "production_authentication": False,
        "latency_is_shared_host_descriptive_not_benchmark_qualification": True,
        "code_dependency_sha256": dependencies(), "runtime": {"python": platform.python_version(),
            "platform": platform.platform(), "torch": torch.__version__, "numpy": np.__version__},
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}
    plan_sha = write(target / "plan.json", plan)  # Immutable plan precedes all inference below.
    manifest = json.loads(read_pinned(source_root, records, "feature_manifest.json"))
    identity = FeatureIdentityV1(**manifest["feature_identity"])
    bundles = {}
    with np.load(source_root / "features.npz", allow_pickle=False) as archive:
        for role in ROLES:
            features = torch.from_numpy(archive[role].copy())
            mask = torch.ones((len(features), 5), dtype=torch.bool)
            mask[:, 0] = False
            bundles[role] = FeatureBundleV1.from_tensors(global_features=features, missing_mask=mask, identity=identity,
                source_record_digests=tuple(manifest["cohorts"][role]["source_record_digests"]))
            if bundles[role].manifest() != manifest["cohorts"][role]:
                raise ValueError("real feature reconstruction differs from E2 evidence")
    started = time.perf_counter_ns()
    ledger, pools, saved = [], [], {}
    for seed in SEEDS:
        for arm in ARMS:
            name = f"seed-{seed}/{arm}/snapshot.json"
            record = json.loads(read_pinned(source_root, records, name))
            withdrawals = Withdrawals(identity.scope_id)
            snapshot = load_snapshot(source_root / f"seed-{seed}/{arm}",
                expected_manifest_sha256=records[name]["original_sha256"],
                budget=EvolutionBudgetV1(**record["admitted_budget"]), withdrawal_provider=withdrawals)
            saved[(seed, arm)] = snapshot
            references = {}
            for role, bundle in bundles.items():
                references[role], counts = reference(snapshot, bundle, withdrawals)
                ledger.append({"seed": seed, "arm": arm, "role": role, "execution": "reference_in_process",
                               "observed": counts, **serializable(references[role])})
            for workers in (1, 2):
                withdrawals = Withdrawals(identity.scope_id)
                owner = SnapshotProcessOwnerV1(snapshot, withdrawals)
                cpu_before, owner_cpu = children_cpu(), time.process_time_ns()
                with SnapshotWorkerPoolV1(owner, worker_count=workers) as pool:
                    timings = []
                    for repetition in range(2):
                        for role, bundle in bundles.items():
                            result = pool.predict_task(bundle)
                            if (not torch.equal(result["task_probabilities"], references[role]["task_probabilities"])
                                    or result["routes"] != references[role]["routes"]
                                    or result["head_example_calls"] != len(bundle.source_record_digests)):
                                raise AssertionError("actual process execution changed frozen semantics")
                            timings.append(result["elapsed_ns"])
                            ledger.append({"seed": seed, "arm": arm, "role": role,
                                "execution": "spawn", "workers": workers, "repetition": repetition,
                                "reference_bitwise_equal": True, **serializable(result)})
                    parent = saved[(seed, "parent")]
                    source = group_digest(parent.report["router"]["source_groups"]["calibration"][0])
                    before = total_head_calls(pool)
                    withdrawals.revoke(source)
                    rejection = must_reject(lambda: pool.predict_task(bundles["future_1"]))
                    rejection.update({"source_kind": "ancestor_router_calibration_group", "source_sha256": source,
                        "head_calls_after_withdrawal": total_head_calls(pool) - before})
                    if rejection["head_calls_after_withdrawal"] != 0:
                        raise AssertionError("withdrawn snapshot executed a Head")
                    entry = {"seed": seed, "arm": arm, "workers": workers, "startup_ns": pool.startup_ns,
                        "inference_elapsed_ns": timings, "pids_and_total_forward_counts": pool.counts(),
                        "transport": pool.transport_receipt(), "pre_dispatch_revocation": rejection,
                        "resident_tensor_bytes_per_snapshot": snapshot.report["resident_tensor_bytes"],
                        "total_snapshot_tensor_bytes_owner_plus_workers": (workers + 1) * snapshot.report["resident_tensor_bytes"]}
                entry["joined_worker_os_usage"] = {k: v - cpu_before[k] for k, v in children_cpu().items()}
                entry["owner_cpu_ns_including_startup_shutdown"] = time.process_time_ns() - owner_cpu
                pools.append(entry)
                print(json.dumps({"seed": seed, "arm": arm, "workers": workers,
                    "bitwise_parity": True, "startup_ms": pool.startup_ns / 1e6}), flush=True)
    faults = []
    for kind in ("mid_request_revocation", "mid_request_generation", "crash", "timeout", "request_cap"):
        withdrawals = Withdrawals(identity.scope_id)
        initial = saved[(7, "split")] if kind == "mid_request_revocation" else saved[(7, "parent")]
        owner = SnapshotProcessOwnerV1(initial, withdrawals)
        with SnapshotWorkerPoolV1(owner, max_requests_per_worker=1 if kind == "request_cap" else 1024) as pool:
            original = pool._exchange
            def exchange(groups):
                result = original(groups)
                if kind == "mid_request_revocation":
                    withdrawals.revoke(saved[(7, "parent")].report["source_closure"][0])
                else:
                    owner.commit(saved[(7, "split")], expected_parent_manifest_sha256=initial.manifest_sha256)
                return result
            if kind == "crash":
                pool._workers[0][0].terminate()
                pool._workers[0][0].join(2)
            if kind == "timeout":
                pool._timeout = 0.1
                os.kill(pool._workers[0][0].pid, signal.SIGSTOP)
            start = time.perf_counter_ns()
            router_calls = [0]
            def observe_router(module, inputs):
                router_calls[0] += 1
            hook = initial.router._net.register_forward_pre_hook(observe_router) if initial.router else None
            if kind.startswith("mid_request"):
                with patch.object(pool, "_exchange", side_effect=exchange):
                    rejection = must_reject(lambda: pool.predict_task(bundles["future_1"]))
            else:
                rejection = must_reject(lambda: pool.predict_task(bundles["future_1"]))
            if hook:
                hook.remove()
            if kind == "request_cap" and (total_head_calls(pool) or router_calls[0]):
                raise AssertionError("exhausted lifetime budget executed a model")
            faults.append({"case": kind, **rejection, "elapsed_ns": time.perf_counter_ns() - start,
                "actual_head_calls_before_discard": total_head_calls(pool),
                "actual_owner_router_forwards": router_calls[0],
                "current_owner_generation": owner.current.generation,
                "reusing_failed_pool": must_reject(lambda: pool.predict_task(bundles["future_1"])),
                "transport": pool.transport_receipt()})
    for name in names:
        read_pinned(source_root, records, name)
    if dependencies() != plan["code_dependency_sha256"]:
        raise ValueError("experiment dependencies changed while running")
    ledger_sha = write(target / "prediction_ledger.json", ledger)
    report = {"schema": "hepta.real-local-process-report.v2", "plan_sha256": plan_sha,
        "prediction_ledger_sha256": ledger_sha, "elapsed_ns": time.perf_counter_ns() - started,
        "reference_batches": 18, "process_batches": 72, "all_predictions_and_routes_exact": True,
        "pools": pools, "faults": faults, "source_files_unchanged": True,
        "encoder_runs": 0, "optimizer_steps": 0, "physical_nodes": 1,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}
    write(target / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "inventory", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = run_probe(args.source_root, args.inventory, args.output)
    print(json.dumps({"all_exact": result["all_predictions_and_routes_exact"],
                      "elapsed_ms": result["elapsed_ns"] / 1e6}), flush=True)
