"""Historical TRAIN engineering replay; no new cohort, training or quality claim."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

from .boundary import BoundaryError, FrozenInput, Packet, canonical, digest
from .runtime import Session
from .v13_bridge import BASE_COMMIT, ROOT, V13Core


HERE = Path(__file__).resolve().parent
RUN = ROOT / "experiments/hcsn_v13_followup_20261102/joint_core/results/run001"
FAMILIES = ("hx_full", "gru", "ssm")


def context(family):
    import numpy as np
    import torch
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    core = V13Core(RUN / f"fit-async_av-{family}-13301")
    source = RUN / "async_av-TRAIN.npz"
    source_bytes, plan_bytes = source.read_bytes(), (RUN / "PLAN.json").read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    if hashlib.sha256(plan_bytes).hexdigest() != core.metadata["plan_sha256"]:
        raise BoundaryError("Training plan is not the one bound to the frozen candidate")
    plan = json.loads(plan_bytes)
    if source_sha != plan["input_sha256"][source.name]:
        raise BoundaryError("Original TRAIN tensor bytes changed")
    with np.load(io.BytesIO(source_bytes), allow_pickle=False) as data:
        rows = data["x"][0].copy()
    adapter = hashlib.sha256((RUN.parents[1] / "data.py").read_bytes()).hexdigest()
    specification = {"source_id": "historical-train-first-sequence", "family_id": "historical-v13",
        "session_id": "engineering-session", "world_id": "exposed-training-world", "clock_id": "source-clock",
        "sha256": source_sha, "max_end_ns": 66_000_000_000, "sync_uncertainty_ns": 0,
        "release_offset_ns": 0, "origin": "recorded_features",
        "encoders": {m: {"sha256": adapter, "width": 55} for m in ("audio", "video")}}
    frozen = FrozenInput({"schema": "hcsn-v14-frozen-input.v1", "role": "development",
                          "arrival_clock_id": "arrival-clock", "sources": [specification]})
    return rows, core, frozen, specification


def packet(rows, spec, index):
    row = rows[index % 6]
    modality = "audio" if row[51] == 1 else "video"
    end = round(float(row[53]) * 3 * 1_000_000_000) + (index // 6) * 3_000_000_000
    return Packet(spec["source_id"], modality, spec["sha256"], spec["encoders"][modality]["sha256"],
                  spec["clock_id"], end - 1_000_000_000, end, (end,), tuple(row.tolist()), "")


def opened(path, frozen, core):
    return Session(path, frozen, core, "engineering-session", "source-clock", memory_bytes=1 << 20)


def advance(session, rows, spec, begin, end, deadline, pending_only=False):
    output = []
    for i in range(begin, end):
        if time.monotonic() >= deadline:
            raise TimeoutError("Owned engineering worker exceeded its 90-second budget")
        item = packet(rows, spec, i)
        now = max(session.receipt()["frontier_ns"], item.end_ns)
        read_id = "read-" + str(i)
        session.issue(read_id, item.source_id, item.modality, item.start_ns, item.end_ns, now_ns=now)
        if pending_only:
            return output
        receipt = session.complete(read_id, item, now_ns=now)
        output.append({"step": i + 1, "receipt": receipt, "output": session.output()})
    return output


def resume(family, out, deadline):
    plan = json.loads((out / "PLAN.json").read_text())
    if any(hashlib.sha256((HERE / p).read_bytes()).hexdigest() != sha for p, sha in plan["source_sha256"].items()):
        raise BoundaryError("Replay source changed across process restart")
    rows, core, frozen, spec = context(family)
    session = opened(out / f"{family}-restart.sqlite", frozen, core)
    before = session.receipt()
    if before["pending_read_ids"] != ["read-3"] or before["charge_units"] != 4:
        raise BoundaryError("Pending READ did not survive process restart")
    records = advance(session, rows, spec, 3, 6, deadline)
    report = {"before": before, "records": records, "after": session.receipt()}
    session.close()
    (out / f"{family}-resumed.json").write_bytes(canonical(report))


def family_run(family, out, deadline):
    import numpy as np
    rows, core, frozen, spec = context(family)
    session = opened(out / f"{family}-restart.sqlite", frozen, core)
    observed = advance(session, rows, spec, 0, 3, deadline)
    advance(session, rows, spec, 3, 4, deadline, pending_only=True)
    session.close()
    subprocess.run([sys.executable, "-m", __package__ + ".engineering_replay", "--out", str(out),
                    "--resume-family", family], check=True, timeout=max(1, deadline-time.monotonic()))
    resumed = json.loads((out / f"{family}-resumed.json").read_text())
    observed += resumed["records"]
    x = core.torch.tensor(rows[None], dtype=core.torch.float64)
    with core.torch.inference_mode():
        expected = core.torch.softmax(core.model((x-core.center)/core.scale), -1)[0].numpy()
    actual = np.asarray([r["output"]["probabilities"] for r in observed])
    difference = float(np.max(np.abs(actual-expected)))
    if difference > 1e-12:
        raise ArithmeticError("Original six-prefix forward parity failed")
    session = opened(out / f"{family}-restart.sqlite", frozen, core)
    late = packet(rows, spec, 6)
    session.issue("late", late.source_id, late.modality, late.start_ns, late.end_ns, now_ns=3_000_000_000)
    session.reset("reset", now_ns=3_000_000_000)
    reset_receipt, reset_output = session.receipt(), session.output()
    rejected = False
    try:
        session.complete("late", late, now_ns=late.end_ns)
    except BoundaryError:
        rejected = True
    if not rejected or session.receipt() != reset_receipt or reset_output != {"probabilities": None}:
        raise BoundaryError("RESET/pending cancellation failed")
    after_reset = advance(session, rows, spec, 6, 7, deadline)[0]["output"]
    fresh = core.output(core.step(core.initial(), late, 1_000_000_000))
    if after_reset != fresh:
        raise BoundaryError("Post-RESET recurrent state differs from a fresh core")
    session.close()
    long = opened(out / f"{family}-long.sqlite", frozen, core)
    long_records = advance(long, rows, spec, 0, 128, deadline)
    long_receipt = long.receipt()
    with long.transaction() as state:
        long_steps, visible_rows = state["core"]["steps"], len(state["core"]["rows"])
    if long_steps != 128 or visible_rows != 6:
        raise BoundaryError("Long stream lost persistent state or exceeded visible-history bound")
    long.close()
    (out / f"{family}-long-records.json").write_bytes(canonical(long_records))
    return {"family": family, "model_id": core.model_id, "execution_id": core.execution_id,
        "execution": core.execution, "parameter_count": core.metadata["parameter_count"],
        "weights_sha256": core.metadata["weights_sha256"], "source_sha256": spec["sha256"],
        "six_prefix_max_abs_difference": difference, "six_outputs": actual.tolist(),
        "six_reference_outputs": expected.tolist(), "cold_process_pending_read_recovery": True,
        "reset_late_completion_rejected": rejected, "reset_state_matches_fresh": after_reset == fresh,
        "long_steps": long_steps, "visible_rows": visible_rows, "long_receipt": long_receipt,
        "long_records_sha256": digest(long_records), "long_context_accuracy_qualified": False}


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume-family", choices=FAMILIES)
    args = parser.parse_args()
    if args.resume_family:
        return resume(args.resume_family, args.out, started + 90)
    args.out.mkdir(parents=True, exist_ok=False)
    plan = {"base_commit": BASE_COMMIT, "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(HERE.glob("*.py"))}, "families": list(FAMILIES), "seed": 13301,
            "scope": "Historical TRAIN feature replay; shifted repeated rows are a synthetic timing transform, not new worlds"}
    (args.out / "PLAN.json").write_bytes(canonical(plan))
    try:
        reports = [family_run(f, args.out, started + 90) for f in FAMILIES]
        own, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {"status": "ENGINEERING_PASS", "plan_sha256": digest(plan), "families": reports,
            "wall_seconds_from_main_before_heavy_imports": time.monotonic()-started,
            "self_cpu_seconds": own.ru_utime+own.ru_stime, "children_cpu_seconds": children.ru_utime+children.ru_stime,
            "self_ru_maxrss": own.ru_maxrss, "children_ru_maxrss": children.ru_maxrss,
            "ru_maxrss_units": "bytes" if sys.platform == "darwin" else "KiB",
            "complete_process_family_peak_bytes": None, "gpu_peak_bytes": None, "device_energy_joules": None,
            "parameter_budget_matched": False, "training_time_matched": False, "training_time_seconds": None,
            "new_training_performed": False, "independent_confirmation": False, "production_activation": False,
            "measurement_scope": "Includes loads, CPU forwards, SQLite transactions, subprocess restart and collection through this receipt; excludes raw AV decode, encoder execution, capture, training and report-write tail"}
        (args.out / "RESULT.json").write_bytes(canonical(result))
        print(json.dumps({"status": result["status"], "families": len(reports)}))
    except BaseException:
        (args.out / "FAILURE.txt").write_text(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
