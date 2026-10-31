"""Qualify frozen native policies against PyTorch, real broker IO and cold recovery.

Every model is frozen before this audit; all cases and failures are retained.
This is an implementation/recovery audit, not a fresh architecture-efficacy test.
"""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time

import numpy as np
import torch

from ..round7.broker import BrokerClient
from ..round7.data import task_configuration
from ..round7.model import load_model
from ..round7.policy import Policy
from ..round7.task import ACTIONS, State, features, generate_episode, initial_state, legal_actions
from .native_policy import NativePolicy

HERE = Path(__file__).resolve().parent
R7 = HERE.parent / "round7"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def child_cpu():
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return value.ru_utime + value.ru_stime


def policy_model(path):
    record = json.loads(path.read_text())
    if record.get("schema") == "round8-fixed-cell-calibrator-v1":
        from .calibration import load_calibrated
        return load_calibrated(path)[0]
    return load_model(path)[0]


def native_rollout(model_path, binary, folder, *, episode_seed, parameters, seed, head, deployment, restart):
    folder.mkdir(parents=True, exist_ok=False)
    reference = Policy(policy_model(model_path), head=head, deployment=deployment, seed=seed)
    wall, cpu, children = time.perf_counter(), time.process_time(), child_cpu()
    records, processes, stages, errors = [], [], defaultdict(int), defaultdict(float)
    native = None
    broker = None
    try:
        broker = BrokerClient(folder / "artifacts")
        start = broker.start(episode_seed, parameters)
        if not start.get("ok"):
            raise AssertionError(start)
        state = State.from_dict(start["state"])
        native = NativePolicy(model_path, binary=binary, owner_dir=folder / "owner", seed=seed, head=head, deployment=deployment)
        while not state.terminated:
            action, prediction = native.act(state)
            expected_action, expected = reference.act(state)
            for key in ("q", "mass", "moments", "expected_event_count", "event_count"):
                error = float(np.max(np.abs(np.asarray(prediction[key]) - expected[key])))
                errors[key] = max(errors[key], error)
                if error > 2e-10:
                    raise AssertionError(("native/PyTorch mismatch", key, error, str(model_path)))
            if action != expected_action:
                raise AssertionError(("native/PyTorch action mismatch", action, expected_action))
            result = broker.step(action)
            if not result.get("ok"):
                raise AssertionError(("actual broker effect failed", result))
            records.append(dict(before=state.to_dict(), prediction=prediction, action=action, result=result))
            for key, value in prediction["costs"].items():
                stages[key] += value
            for key in ("native_runtime_nanos", "persistence_nanos", "complete_owner_nanos", "durable_bytes_written"):
                stages[key] += prediction["native_receipt"][key]
            stages["native_roundtrip_nanos"] += prediction["prediction_ns"]
            state = State.from_dict(result["state"])
            if restart and len(records) == 1 and not state.terminated:
                snapshot = native.snapshot()
                native.close()
                processes.append(process_record(native))
                native = NativePolicy(model_path, binary=binary, owner_dir=folder / "owner", seed=seed, head=head,
                                      deployment=deployment, ack=snapshot["acknowledged_pair_sha256"])
                if native.ready["pair"]["state"] != dict(calls=snapshot["calls"], mass=snapshot["mass"]):
                    raise AssertionError("cold process did not restore exact policy state")
        snapshot = native.snapshot()
        native.close()
        processes.append(process_record(native))
        broker.close()
        broker = None
        if len({row["pid"] for row in processes}) != len(processes):
            raise AssertionError("cold recovery reused a process")
        return dict(model=str(model_path.relative_to(HERE.parent.parent.parent)), model_sha256=sha(model_path),
            episode_seed=episode_seed, policy_seed=seed, head=head, deployment=deployment,
            restarted=restart, records=records, final_state=state.to_dict(), snapshot=snapshot,
            processes=processes, stage_totals=dict(stages), max_errors=dict(errors),
            parent_cpu_seconds=time.process_time() - cpu, child_cpu_seconds=child_cpu() - children,
            full_wall_seconds=time.perf_counter() - wall,
            source_reads=sum(len(r["result"]["info"]["broker_io"]["source_reads"]) for r in records),
            source_bytes_read=sum(r["result"]["info"]["broker_io"]["source_bytes_read"] for r in records),
            source_io_seconds=sum(r["result"]["info"]["broker_io"]["source_io_seconds"] for r in records),
            actual_terminal_readback=bool(records[-1]["result"].get("artifact", {}).get("client_readback_verified")),
            scope="Original R7 BrokerClient/ArtifactWorker; native cell+encoder+readout selects actual actions")
    finally:
        if native is not None:
            native.close()
        if broker is not None:
            broker.close()


def process_record(native):
    return dict(pid=native.ready["pid"], child_cpu_seconds=native.child_cpu_seconds,
        peak_rss_kib=native.peak_rss_kib, model_load_nanos=native.ready["model_load_nanos"],
        recovery_nanos=native.ready["recovery_nanos"], startup_roundtrip_nanos=native.startup_roundtrip_nanos,
        exit_code=native.process.returncode)


def semantic_trace(run):
    return [dict(action=r["action"], q=r["prediction"]["q"], mass=r["prediction"]["mass"],
                 event_count=r["prediction"]["event_count"], state=r["result"]["state"],
                 native_checkpoint=r["prediction"]["native_receipt"]["native_checkpoint"],
                 pair_after=r["prediction"]["native_receipt"]["pair_after"])
            for r in run["records"]]


def owner_hashes(folder):
    return {name: sha(folder / name) for name in ("pair.json", "journal.bin", "witness.bin")}


def rejection_audit(model_path, binary, output):
    output.mkdir()
    state = initial_state(generate_episode(710311))
    native = NativePolicy(model_path, binary=binary, owner_dir=output / "owner", seed=71, deployment="hard")
    checks = {}
    try:
        native.act(state)
        snapshot = native.snapshot()
        before = owner_hashes(output / "owner")
        bad = dict(pair_before="0" * 64, sequence=2, features=features(state).tolist(),
                   legal=[a in legal_actions(state) for a in ACTIONS], public_state_sha256=state.digest())
        result = native.request(bad)
        checks["stale_request_rejects_without_state_or_rng_change"] = not result["ok"] and owner_hashes(output / "owner") == before
        try:
            concurrent = NativePolicy(model_path, binary=binary, owner_dir=output / "owner", seed=71,
                                      deployment="hard", ack=snapshot["acknowledged_pair_sha256"])
            concurrent.close()
            checks["exclusive_native_owner"] = False
        except RuntimeError:
            checks["exclusive_native_owner"] = owner_hashes(output / "owner") == before
    finally:
        native.close()
    variants = ("wrong_seed", "wrong_head", "wrong_model", "tampered_pair", "pending_pair")
    for variant in variants:
        folder = output / variant
        shutil.copytree(output / "owner", folder)
        model = model_path
        kwargs = dict(seed=71, head=1, deployment="hard", ack=snapshot["acknowledged_pair_sha256"])
        if variant == "wrong_seed": kwargs["seed"] = 72
        if variant == "wrong_head": kwargs["head"] = 0
        if variant == "wrong_model":
            model = output / "changed_model.json"
            record = json.loads(model_path.read_text())
            record["state_dict"]["readout.2.bias"][0] += 1e-5
            write(model, record)
        if variant == "tampered_pair":
            pair = json.loads((folder / "pair.json").read_text())
            pair["state"]["calls"] += 1
            (folder / "pair.json").write_text(json.dumps(pair))
        if variant == "pending_pair": (folder / "pair.pending").write_bytes(b"interrupted-pair-fixture")
        before = owner_hashes(folder)
        try:
            invalid = NativePolicy(model, binary=binary, owner_dir=folder, **kwargs)
            invalid.close()
            checks[variant] = False
        except RuntimeError:
            checks[variant] = owner_hashes(folder) == before
    for variant in ("unknown_schema", "future_kernel", "unknown_tensor", "calibrated_missing_encoder"):
        record = json.loads(model_path.read_text())
        if variant == "unknown_schema": record["schema"] = "future-brownian-kernel-v2"
        if variant == "future_kernel": record["kernel_version"] = "continuous-brownian-v2"
        if variant == "unknown_tensor": record["state_dict"]["core.unknown"] = 0.0
        if variant == "calibrated_missing_encoder": record["schema"] = "round8-fixed-cell-calibrator-v1"
        path = output / (variant + ".json")
        write(path, record)
        try:
            invalid = NativePolicy(path, binary=binary, owner_dir=output / (variant + "_owner"))
            invalid.close()
            checks[variant] = False
        except RuntimeError:
            checks[variant] = not (output / (variant + "_owner/journal.bin")).exists()
    write(output / "REPORT.json", dict(checks=checks, passed=all(checks.values()),
        scope="Identity/frontier/tamper/partial-publication guards; the pending-file fixture is not a SIGKILL or arbitrary-crash atomicity claim"))
    if not all(checks.values()):
        raise AssertionError(checks)
    return checks


def main(args):
    torch.set_num_threads(1)
    args.output.mkdir(parents=True, exist_ok=False)
    build = json.loads(args.build_report.read_text())
    if not build["success"] or sha(args.binary) != build["binary_sha256"]:
        raise ValueError("native binary build identity mismatch")
    for filename, expected in build["sources"].items():
        if sha(HERE / "native" / filename) != expected:
            raise ValueError(("compiled native source differs", filename))
    cases = []
    for mode in ("direct", "continuous", "clocked", "first_passage"):
        for fit in range(11, 16):
            model = R7 / "evidence/fits_primary" / f"{mode}_none_{fit}.json"
            for head in (0, 1):
                for deployment in ("mean", "hard"):
                    for condition in (0, 1):
                        cases.append((model, mode, fit, head, deployment, condition, "r7"))
            for stage in ("readout", "content_readout"):
                model = HERE / "evidence/calibration_models" / f"{mode}_none_{fit}_{stage}.json"
                if not model.exists():
                    raise FileNotFoundError(model)
                for deployment in ("mean", "hard"):
                    cases.append((model, mode, fit, 1, deployment, 0, stage))
    write(args.output / "REGISTERED.json", dict(schema="hepta.native-qualification.v1", cases=[
        dict(model=str(r[0]), model_sha256=sha(r[0]), mode=r[1], fit=r[2], head=r[3], deployment=r[4], condition=r[5], stage=r[6])
        for r in cases], native_build_sha256=sha(args.build_report), binary_sha256=sha(args.binary),
        plan="For each frozen model/case, execute continuous and separately spawned cold-resumed native policies through original real broker; compare every decision with the Python frozen model."))
    raw_path = args.output / "RAW.jsonl.gz"
    summaries, errors, stages, cpu = [], defaultdict(float), defaultdict(int), defaultdict(float)
    start = time.perf_counter()
    try:
        with gzip.open(raw_path, "wt", encoding="utf-8") as stream:
            for index, (model, mode, fit, head, deployment, condition, stage) in enumerate(cases):
                runs = []
                for restart in (False, True):
                    run = native_rollout(model, args.binary, args.output / "runs" / f"case_{index:04d}_{int(restart)}",
                        episode_seed=8103100 + fit * 100 + condition, parameters=task_configuration(fit + condition,
                        "nominal" if condition == 0 else "missing"), seed=9103100 + fit, head=head,
                        deployment=deployment, restart=restart)
                    runs.append(run)
                    stream.write(json.dumps(run, sort_keys=True, allow_nan=False) + "\n")
                    stream.flush()
                    for key, value in run["max_errors"].items(): errors[key] = max(errors[key], value)
                    for key, value in run["stage_totals"].items(): stages[key] += value
                    cpu["parent"] += run["parent_cpu_seconds"]
                    cpu["all_children"] += run["child_cpu_seconds"]
                    cpu["native_children"] += sum(p["child_cpu_seconds"] for p in run["processes"])
                    cpu["full_wall"] += run["full_wall_seconds"]
                equal = semantic_trace(runs[0]) == semantic_trace(runs[1]) and runs[0]["snapshot"] == runs[1]["snapshot"]
                if not equal:
                    raise AssertionError(("cold continuation differs", index))
                summaries.append(dict(index=index, mode=mode, fit=fit, head=head, deployment=deployment, stage=stage,
                    exact_cold_continuation=True, decisions=len(runs[0]["records"]), actual_terminal_readback=all(r["actual_terminal_readback"] for r in runs),
                    cold_recovery_exercised=len(runs[1]["processes"]) > 1,
                    processes=sum(len(r["processes"]) for r in runs), source_reads=runs[0]["source_reads"],
                    utility=runs[0]["records"][-1]["result"]["artifact"]["output"]["utility"]))
                if index % 20 == 0: print(json.dumps(dict(completed=index + 1, total=len(cases))), flush=True)
        guards = rejection_audit(R7 / "evidence/fits_primary/first_passage_none_11.json", args.binary, args.output / "guards")
        report = dict(schema="hepta.r7-native-qualification.v1", passed=True, kernel_version="r7-finite-v1",
            implementation_scope="Rust actually executes encoder, finite-state law, RNG, learned heads in original NeuronModelPort; original BrokerClient performs effects.",
            numerical_scope="Independent implementation agreement for R7 finite law, with stable Gaussian tails; not continuous OU first-passage accuracy or new Brownian-kernel qualification.",
            cases=len(cases), executions=2 * len(cases), processes=sum(s["processes"] for s in summaries),
            exact_paired_continuation_matches=len(summaries),
            exact_cold_continuation_pairs=sum(s["cold_recovery_exercised"] for s in summaries), actual_terminal_readbacks=sum(s["actual_terminal_readback"] for s in summaries),
            max_errors=dict(errors), costs=dict(cpu), native_stage_totals=dict(stages), guards=guards,
            cases_summary=summaries, raw_sha256=sha(raw_path), native_build_sha256=sha(args.build_report),
            binary_sha256=sha(args.binary), source_digest=build["source_digest"], total_wall_seconds=time.perf_counter() - start,
            cost_note="Stage nanoseconds are disjoint inside inference. native_runtime overlaps inference; owner includes runtime and persistence. all_children includes native+broker; native_children is a subset. Python comparison oracle is included in parent CPU. No architecture speed/energy claim.",
            recovery_scope="Exact acknowledged policy-decision boundaries with surviving original broker. Broker process restart and arbitrary-crash business completion are not implemented.",
            energy_joules=None, production_activation=False)
        write(args.output / "REPORT.json", report)
        print(json.dumps({key: report[key] for key in ("passed", "cases", "executions", "processes", "max_errors", "total_wall_seconds")}))
    except BaseException as error:
        write(args.output / "FAILURE.json", dict(error=repr(error), completed=len(summaries), summaries=summaries,
            raw_sha256=sha(raw_path) if raw_path.exists() else None))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "build-report", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    main(parser.parse_args())
