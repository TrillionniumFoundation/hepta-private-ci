"""Host meters and admission around actual disposable model operations."""

import json
from pathlib import Path
import resource
import sys
import time

from artifact_inventory import measure
from budget_ledger import BudgetExceeded, BudgetLedger, canonical, digest, quantities
from cohort_contract import file_sha, retain


def ledger_for(path, arm, protocol, protocol_sha):
    budget = protocol["common_budget"]
    return BudgetLedger(
        path,
        arm=arm,
        protocol_sha256=protocol_sha,
        **{k: budget[k] for k in ("limits", "gauges", "prices", "cost_limit")},
    )


def usage():
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(
        cpu_ns=int((value.ru_utime + value.ru_stime) * 10**9),
        rss=value.ru_maxrss * 1024,
    )


def model_call(
    ledger,
    event,
    request,
    *,
    implementation,
    directory,
    expected_updates=0,
    maximum_seconds=None,
):
    try:
        return _model_call(
            ledger,
            event,
            request,
            implementation=implementation,
            directory=directory,
            expected_updates=expected_updates,
            maximum_seconds=maximum_seconds,
        )
    except BaseException as error:
        row = next(
            (r for r in ledger.snapshot()["events"] if r["event"] == event), None
        )
        if row and row["state"] == "reserved":
            ledger.abandon(
                event,
                reason="operation lacks complete admitted settlement: " + str(error),
            )
        raise


def _model_call(
    ledger,
    event,
    request,
    *,
    implementation,
    directory,
    expected_updates=0,
    maximum_seconds=None,
):
    """Actual trainer receipts and raw generated token rows determine settlement."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(Path(implementation) / "scripts/memory_cell_network"))
    from model_process import ChildFailure, run_child

    state = ledger.snapshot()
    remaining = {
        k: state["config"]["limits"][k] - state["used"][k] - state["pending"][k]
        for k in state["used"]
    }
    timeout = min(remaining["wall_ns"] // 10**9 - 2, 400 if expected_updates else 180)
    if maximum_seconds is not None:
        timeout = min(timeout, maximum_seconds)
    if timeout <= 0:
        raise BudgetExceeded("no whole-second child deadline remains")
    query_count = len(request.get("questions", []))
    reserve = quantities(
        dict(
            wall_ns=(timeout + 1) * 10**9,
            cpu_ns=min(remaining["cpu_ns"], 2 * (timeout + 1) * 10**9),
            decoder_updates=expected_updates,
            train_tokens=expected_updates * 256,
            decoder_queries=query_count,
            input_tokens=query_count * 192,
            output_tokens=query_count * 16,
            read_bytes=min(remaining["read_bytes"], 2 * 1024**3),
            write_bytes=min(remaining["write_bytes"], 64 * 1024**2),
        )
    )
    reservation = ledger.reserve(
        event,
        "train" if expected_updates else "infer",
        reserve,
        request_sha256=digest(request),
    )
    if reservation["state"] != "reserved":
        raise ValueError("this non-replay launcher never reexecutes a terminal event")
    retain(directory / "request.json", request)
    before, clock, parent_cpu = usage(), time.perf_counter_ns(), time.process_time_ns()
    try:
        receipt = run_child(
            Path(__file__).with_name("budget_model_worker.py"),
            ["--implementation", str(implementation)],
            input_text=json.dumps(request),
            timeout=timeout,
            cwd=directory,
            receipt_dir=directory / "process",
            operation="budget " + request["phase"],
        )
        output = json.loads(receipt["stdout"])
    except BaseException as error:
        ledger.abandon(
            event,
            reason="child failed before complete model-work receipt: " + str(error),
        )
        raise
    after = usage()
    elapsed = time.perf_counter_ns() - clock
    training = output.get("receipts", [])
    rows = output.get("journal", {}).get("rows", [])
    measured_updates = sum(r["steps"] for r in training)
    if measured_updates != expected_updates:
        ledger.abandon(
            event, reason="actual optimizer steps differ from the reserved operation"
        )
        raise ValueError("unexpected optimizer work")
    io = output["worker_process_io_before_stdout"]
    actual = quantities(
        dict(
            wall_ns=elapsed,
            cpu_ns=after["cpu_ns"]
            - before["cpu_ns"]
            + time.process_time_ns()
            - parent_cpu,
            decoder_updates=measured_updates,
            train_tokens=sum(r["input_tokens"] for r in training),
            decoder_queries=len(rows),
            input_tokens=sum(r["input_tokens"] for r in rows),
            output_tokens=sum(r["generated_tokens"] for r in rows),
            read_bytes=io["rchar"],
            write_bytes=io["wchar"] + len(receipt["stdout"].encode()),
        )
    )
    record = dict(
        request_sha256=digest(request),
        process_receipt_path=receipt["receipt_path"],
        process_receipt_sha256=file_sha(receipt["receipt_path"]),
        actual=actual,
        child_cpu_delta_ns=after["cpu_ns"] - before["cpu_ns"],
        peak_child_rss_upper_bound_bytes=after["rss"],
        process_io_semantics="Linux /proc/self/io rchar/wchar includes logical reads/writes; stdout added after worker observation",
        raw_kernel_io=io,
        model_receipts=training,
        source_values_in_reader_request=False if request["phase"] == "read" else None,
        supervised_tokens_subset_of_training_input_tokens=sum(
            r["supervised_tokens"] for r in training
        ),
        unmeasured=[
            "storage_byte_ns",
            "network packet overhead",
            "OS dependency file closure",
        ],
        output=output,
    )
    retain(directory / "measurement.json", record)
    ledger.settle(event, actual, receipt_sha256=digest(record))
    return record


def allocate_parent(ledger, measurement):
    actual = measurement["actual"]
    identity = digest(measurement)
    ledger.reserve(
        "shared-parent",
        "train",
        actual,
        request_sha256=digest(["parent", identity]),
        cost_origin="allocated_shared",
        shared_receipt_sha256=identity,
    )
    ledger.settle("shared-parent", actual, receipt_sha256=identity)


def inventory(ledger, components, output, *, peak_rss=0):
    before, cpu = time.perf_counter_ns(), time.process_time_ns()
    expected_read = sum(
        p.stat().st_size
        for c in components
        for p in (
            [Path(c["path"])]
            if Path(c["path"]).is_file()
            else Path(c["path"]).rglob("*")
        )
        if p.is_file()
    )
    request = dict(components=components)
    event = "inventory:" + str(Path(output).name)
    ledger.reserve(
        event,
        "recover",
        dict(
            wall_ns=30 * 10**9,
            cpu_ns=30 * 10**9,
            read_bytes=expected_read + 1024**2,
            write_bytes=8 * 1024**2,
        ),
        request_sha256=digest(request),
    )
    report = measure(components)
    retain(output, report)
    actual = dict(
        wall_ns=time.perf_counter_ns() - before,
        cpu_ns=time.process_time_ns() - cpu,
        read_bytes=report["hash_read_bytes"],
        write_bytes=Path(output).stat().st_size,
    )
    ledger.settle(event, actual, receipt_sha256=digest(report))
    ledger.observe_inventory(
        dict(
            retained_bytes=report["logical_bytes"],
            private_bytes=report["private_bytes"],
            peak_rss_bytes=peak_rss,
        ),
        inventory_sha256=report["inventory_sha256"],
    )
    return report
