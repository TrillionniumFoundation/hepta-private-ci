"""Fresh real-file task parity for the explicit native Q24 deployment profile.

The Python task owner performs packet reads/content inference and external cell
physics. Rust executes the frozen residual model and actual native action owner.
Restart tests occur after an acknowledged completed effect; this is not an
arbitrary-crash exactly-once effect protocol.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..recurrent_owner_v2_20261031.owner import CellOwner
from ..task_policy_v2_20261031.planner import OneRead
from ..task_value_factorial_20261030.task import ACTIONS, ContentAdapter, Owner, build_cohort, score_terminal
from .client import NativeClient, canonical_digest
from .reference import NUMERIC_CONTRACT, infer


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_one(session, adapter, confusion, protocol, checkpoint_path, cell_parameters, backend, native_binary, out):
    start, cpu = time.perf_counter(), time.process_time()
    checkpoint = None
    if backend == "python":
        checkpoint = json.loads(checkpoint_path.read_text())
        checkpoint["weights"] = {k:np.asarray(v, float) for k,v in checkpoint["weights"].items()}
        checkpoint["norm"] = {k:np.asarray(v, float) for k,v in checkpoint["norm"].items()}
    owner = Owner(session["folder"], adapter, confusion, protocol["multiplier"], protocol["latency_price"])
    cell = CellOwner("analytic", cell_parameters)
    planner = OneRead(owner.meta, confusion, protocol["multiplier"], protocol["latency_price"])
    objective = canonical_digest(dict(confusion=confusion, public_sha256=owner.public_sha256,
                                     cell_parameters_sha256=cell.parameters_sha256, multiplier=protocol["multiplier"],
                                     latency_price=protocol["latency_price"], numeric_contract=NUMERIC_CONTRACT))
    native = NativeClient(native_binary, checkpoint_path, out, "task."+session["id"], objective) if backend == "native" else None
    traces, accounting, failure, restored = [], [], None, False
    try:
        while not owner.terminal:
            state = (owner.job, owner.tick, owner.budget, owner.posterior)
            driver = 2*owner.posterior-1
            prior = planner.q(*state)
            features = planner.features(*state, prior=prior)
            feasible = np.isfinite(prior)
            snapshot = cell.snapshot()
            public = canonical_digest(dict(public_sha256=owner.public_sha256, state=state,
                                           cell_snapshot_sha256=snapshot["sha256"]))
            if native is None:
                action, q, drive = infer(checkpoint, features, prior, feasible)
                receipt = None
            else:
                receipt = native.query(features, prior, feasible, snapshot["sha256"], public)
                action, q = receipt["action_index"], np.asarray(receipt["q_values"])
                if receipt["external_cell_snapshot_sha256"] != snapshot["sha256"]:
                    raise AssertionError("Native owner did not bind the actual external cell snapshot")
            try:
                event = owner.act(ACTIONS[action])
            except FileNotFoundError:
                failure = "FileNotFoundError"
                event = owner.events[-1]
            interval = cell.advance(cell.sequence+1, driver, event["duration"], reset=ACTIONS[action] == "FIRE")
            traces.append(dict(state=list(state), action=action, q=np.where(feasible, q, 0.).tolist(),
                external_cell_snapshot_sha256=snapshot["sha256"], event=event, cell_interval=interval,
                native_receipt=receipt))
            if len(traces) == 1 and not owner.terminal:
                task_snapshot, cell_snapshot = owner.snapshot(), cell.snapshot()
                if native is not None:
                    sequence, anchor = native.sequence, native.anchor
                    accounting.append(native.close())
                    native = NativeClient(native_binary, checkpoint_path, out, "task."+session["id"],
                                          objective, sequence, anchor)
                restored_owner = Owner(session["folder"], adapter, confusion, protocol["multiplier"], protocol["latency_price"])
                restored_owner.restore(task_snapshot)
                restored_cell = CellOwner("analytic", cell_parameters)
                restored_cell.restore(cell_snapshot)
                owner, cell, restored = restored_owner, restored_cell, True
        score = score_terminal(owner)
    finally:
        if native is not None:
            accounting.append(native.close())
    child_cpu = sum(a["child_process_usage"]["user_cpu_seconds"]+a["child_process_usage"]["system_cpu_seconds"] for a in accounting)
    return dict(session_id=session["id"], backend=backend, score=score, counts=owner.counts,
        task_elapsed=owner.task_elapsed, failure=failure, restored=restored,
        lifecycle_metadata_file_reads=1+int(restored), traces=traces, native_process_accounting=accounting,
        parent_cpu_seconds=time.process_time()-cpu, native_child_cpu_seconds=child_cpu,
        complete_cpu_seconds=time.process_time()-cpu+child_cpu, wall_seconds=time.perf_counter()-start,
        final_cell_snapshot=cell.snapshot())


def verify(binary, checkpoint_file, calibration_file, out):
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    protocol = json.loads((root/"task_value_factorial_20261030/PROTOCOL.json").read_text())
    protocol["data_seed_base"] = 987103100
    confusion = json.loads(calibration_file.read_text())["confusion"]
    cell_file = root/"task_value_factorial_20261030/evidence/preflight_01/models/seed1234.json.gz"
    model = json.loads(gzip.decompress(cell_file.read_bytes()))
    cell_parameters = model["cellfits"]["analytic"]["parameters"]
    adapter = ContentAdapter()
    cases = []
    for split, spec in (("iid", protocol), ("ood", dict(protocol, **protocol["ood"]))):
        cohort = build_cohort(out/"data"/split, "validation", 91031, 16, spec)
        cases.extend((split, row) for row in cohort["records"])
    fault_protocol = dict(protocol, deadlines=[10], read_budgets=[4], packet_reliabilities=[.9],
                          packet_prices=[.015], step_durations=[.4])
    fault = build_cohort(out/"data"/"failure", "validation", 91033, 1, fault_protocol)["records"][0]
    folder = Path(fault["folder"])
    meta = json.loads((folder/"public.json").read_text())
    renamed = []
    for name in sum(meta["packets"], []):
        path = folder/name
        renamed.append(dict(path=name, sha256=sha(path)))
        path.rename(path.with_suffix(".missing"))
    cases.append(("failed_read", fault))
    ordering = np.random.default_rng(11931)
    rows, comparisons = [], []
    for index, (split, session) in enumerate(cases):
        pair = {}
        for backend in ordering.permutation(["python", "native"]):
            result = run_one(session, adapter, confusion, protocol, checkpoint_file, cell_parameters,
                str(backend), binary, out/"owners"/f"{index}_{backend}")
            result["split"] = split
            pair[str(backend)] = result
            rows.append(result)
        left, right = pair["python"], pair["native"]
        comparisons.append(dict(index=index, split=split, session_id=session["id"],
            actions_equal=[r["action"] for r in left["traces"]] == [r["action"] for r in right["traces"]],
            score_equal=left["score"] == right["score"], counts_equal=left["counts"] == right["counts"],
            task_elapsed_equal=left["task_elapsed"] == right["task_elapsed"],
            final_cell_equal=left["final_cell_snapshot"] == right["final_cell_snapshot"],
            failure_equal=left["failure"] == right["failure"],
            paired_cpu_delta_seconds=right["complete_cpu_seconds"]-left["complete_cpu_seconds"],
            paired_wall_delta_seconds=right["wall_seconds"]-left["wall_seconds"]))
    accepted = all(all(r[key] for key in ("actions_equal", "score_equal", "counts_equal",
        "task_elapsed_equal", "final_cell_equal", "failure_equal")) for r in comparisons)
    failure_rows = [row for row in rows if row["split"] == "failed_read"]
    accepted = accepted and all(r["failure"] == "FileNotFoundError" and r["counts"]["failed_read_attempts"] == 1
        and r["score"]["charged_cost"] > 0 for r in failure_rows)
    source_files = [Path(__file__), Path(__file__).with_name("client.py"), Path(__file__).with_name("reference.py"),
                    root/"recurrent_owner_v2_20261031/owner.py", root/"task_policy_v2_20261031/planner.py"]
    report = dict(schema="hepta.task.native-bridge.actual-task-parity.v1", accepted=accepted,
        source_sha256={str(p.relative_to(root)):sha(p) for p in source_files},
        python_weight_loading="Parse and convert frozen arrays once per rollout, no repeated per-decision conversion",
        numeric_contract=NUMERIC_CONTRACT, model_sha256=sha(checkpoint_file), binary_sha256=sha(binary),
        calibration_sha256=sha(calibration_file), external_cell_model_file_sha256=sha(cell_file),
        external_cell_parameters=cell_parameters, adapter_setup=adapter.setup, case_count=len(cases),
        completed_file_reads=sum(r["counts"]["packet_file_reads"] for r in rows),
        content_invocations=sum(r["counts"]["content_invocations"] for r in rows),
        failure_rows=len(failure_rows), restored_rollouts=sum(r["restored"] for r in rows),
        comparisons=comparisons, fault_injection_renamed_packets=renamed,
        total_complete_cpu_seconds=sum(r["complete_cpu_seconds"] for r in rows),
        total_native_child_cpu_seconds=sum(r["native_child_cpu_seconds"] for r in rows),
        total_wall_seconds=sum(r["wall_seconds"] for r in rows), task_utility_admission=False,
        native_physics_executed=False, production_activation=False,
        scope="Fresh development integration parity, not efficacy. Frozen learned native MLP and real native durable action owner; actual packet reads, content model, bounded planner and cell physics remain external. External cell is bound for lifecycle qualification, not used to claim an analytic-cell policy advantage.")
    with (out/"REPORT.json").open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    with (out/"ROLLOUTS.json.gz").open("xb") as stream:
        stream.write(gzip.compress(json.dumps(rows, allow_nan=False, separators=(",", ":")).encode(), mtime=0))
    print(json.dumps({k:v for k,v in report.items() if k not in ("comparisons", "fault_injection_renamed_packets", "adapter_setup")}, indent=2))
    return accepted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if verify(args.binary, args.checkpoint, args.calibration, args.out) else 1)
