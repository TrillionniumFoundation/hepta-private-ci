"""Execute the single predeclared development diagnostic, never qualification."""

import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback
import types


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (HERE / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    protocol = json.loads((HERE / "protocol.json").read_text())
    if protocol["pairs_per_kind"] != 5 or protocol["iterations"] != {"ledger_only": 256, "full_update": 256}:
        raise ValueError("predeclared bounded workload changed")
    required = protocol["required_thread_environment"]
    if any(os.environ.get(key) != value for key, value in required.items()):
        raise ValueError("all three thread variables must equal 1 before NumPy import")
    for name, expected in protocol["artifact_sha256"].items():
        if digest(HERE / name) != expected:
            raise ValueError("diagnostic artifact bytes changed: " + name)
    for name, expected in protocol["runtime_source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("runtime source bytes changed: " + name)
    write("STARTED.json", {"protocol_sha256": digest(HERE / "protocol.json"),
        "thread_environment": {key: os.environ.get(key) for key in required},
        "started_unix_ns": time.time_ns(), "qualification": False,
        "retry_policy": "exclusive marker; do not rerun or discard pairs"})
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from independent.learning import CachedObjective, step_work
    from model import JointModel

    fixture = json.loads((HERE / "shared-ledger-fixture.json").read_text())["shared_ledger"]
    if len(fixture["stages"]) != 7 or len(fixture["totals"]) != 35:
        raise ValueError("actual seven-stage, 35-total-counter fixture changed")
    classes = {}
    for variant in ("old", "new"):
        source = (HERE / (variant + "-accounting.py")).read_text()
        module = types.ModuleType("accounting_diagnostic_" + variant)
        exec(compile(source, str(HERE / (variant + "-accounting.py")), "exec"), module.__dict__)
        classes[variant] = module.WorkLedger
    rng = np.random.default_rng(93017)
    x = rng.normal(0, 0.2, (64, 202))
    y = rng.integers(12, size=64)
    work = step_work((202, 12, 192, 32), "supervised", 64)
    counts = {"content_updates": 1, "optimizer_updates": 1, "model_forward_calls": 1,
        "model_forward_rows": 64, "model_backward_calls": 1, "model_backward_rows": 64,
        "training_examples": 64, "cross_entropy_calls": 1,
        "model_forward_macs": 64 * (202 * 32 + 2 * 32 * 12),
        "model_backward_macs": 64 * (202 * 32 + 4 * 32 * 12),
        "optimizer_elements": 202 * 32 + 32 + 2 * 32 * 12 + 2 * 12}

    def ledger_fixture(cls):
        ledger = cls("manual-benchmark", total_cap=fixture["total_cap"], prices=fixture["prices"])
        for stage, row in fixture["stages"].items():
            values = dict(row)
            ledger.record(stage, units=values.pop("consumed_units"), **values)
        if ledger.snapshot()["stages"] != fixture["stages"] or ledger.totals != fixture["totals"]:
            raise ValueError("public-record reconstruction changed retained stage counters")
        return ledger

    def timed(variant, kind):
        ledger = ledger_fixture(classes[variant])
        model = JointModel(202, 12, 192, hidden=32, seed=193)
        objective = CachedObjective("supervised", model)
        losses = []
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        if kind == "ledger_only":
            for _ in range(256):
                ledger.charge_kernel("search_train", "efficient_S", **work, counts=counts)
        else:
            for _ in range(256):
                losses.append(objective.step(model, x, y, 0.003, ledger=ledger))
        timing = {"cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - wall}
        return timing, ledger, model, losses

    def optimizer_digest(model):
        result = hashlib.sha256()
        for name in sorted(model._moments):
            m, v, step = model._moments[name]
            result.update(name.encode())
            result.update(m.astype("<f8", copy=False).tobytes())
            result.update(v.astype("<f8", copy=False).tobytes())
            result.update(str(step).encode())
        return result.hexdigest()

    report = {"schema": "hepta.corrected-accounting-development-diagnostic.v1", "qualification": False,
        "protocol_sha256": digest(HERE / "protocol.json"), "pairs": [],
        "thread_environment": {key: os.environ.get(key) for key in required},
        "observed_process_threads_after_import": len(list(Path("/proc/self/task").iterdir())),
        "fixture_stage_count_before": 7, "fixture_total_counter_count_before": 35,
        "iterations": protocol["iterations"], "cold_start_scope": protocol["timing_boundary"]}
    for kind in ("ledger_only", "full_update"):
        for pair in range(5):
            order = ("old", "new") if pair % 2 == 0 else ("new", "old")
            results = {variant: timed(variant, kind) for variant in order}
            receipts = {}
            for variant in order:
                timing, ledger, model, losses = results[variant]
                name = f"receipts/{kind}-p{pair + 1}-{variant}.json"
                receipt = {"timing": timing, "ledger": ledger.snapshot(), "ledger_digest": ledger.digest(),
                    "model_digest": model.digest(), "optimizer_sha256": optimizer_digest(model),
                    "model_updates": model.updates,
                    "losses_sha256": hashlib.sha256(np.asarray(losses, dtype="<f8").tobytes()).hexdigest()}
                write(name, receipt)
                receipts[variant] = {"file": name, "sha256": digest(HERE / name)}
            old, new = results["old"], results["new"]
            assert old[1].snapshot() == new[1].snapshot()
            assert old[1].digest() == new[1].digest()
            assert len(new[1].snapshot()["stages"]) == 8
            assert old[2].updates == new[2].updates == (256 if kind == "full_update" else 0)
            assert old[3] == new[3]
            assert old[2]._moments.keys() == new[2]._moments.keys()
            for key in old[2].params:
                assert np.array_equal(old[2].params[key], new[2].params[key]), key
            for key, (om, ov, ot) in old[2]._moments.items():
                nm, nv, nt = new[2]._moments[key]
                assert ot == nt and np.array_equal(om, nm) and np.array_equal(ov, nv), key
            saved = old[0]["cpu_ns"] - new[0]["cpu_ns"]
            row = {"kind": kind, "pair": pair + 1, "order": list(order),
                "old": old[0], "new": new[0], "receipts": receipts, "cpu_saved_ns": saved,
                "cpu_saving_fraction": saved / old[0]["cpu_ns"],
                "snapshots_params_adam_losses_updates_bitwise_equal": True}
            report["pairs"].append(row)
            write(f"pairs/{kind}-p{pair + 1}.json", row)
    report["summary"] = {}
    for kind in ("ledger_only", "full_update"):
        rows = [row for row in report["pairs"] if row["kind"] == kind]
        report["summary"][kind] = {"median_old_cpu_ns": statistics.median(row["old"]["cpu_ns"] for row in rows),
            "median_new_cpu_ns": statistics.median(row["new"]["cpu_ns"] for row in rows),
            "median_paired_cpu_saving_fraction": statistics.median(row["cpu_saving_fraction"] for row in rows),
            "negative_cpu_pairs": [row["pair"] for row in rows if row["cpu_saved_ns"] < 0]}
    report["claims_excluded"] = protocol["claims_excluded"]
    write("corrected-results.json", report)
    print(json.dumps({"results": str(HERE / "corrected-results.json"), "summary": report["summary"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        try:
            write("failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                                   "qualification": False, "retry_allowed": False})
        except Exception as archival_error:
            error.add_note("diagnostic failure persistence also failed: " + repr(archival_error))
        raise
