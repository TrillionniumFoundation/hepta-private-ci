"""Observe a Runtime-owned native worker across an explicit owner stop/restart.

The coordinator performs Runtime process_cancel/process_status/process_start
outside this script and preserves their actual receipts. This script never
starts, retries, restarts or signals a worker. A lost read stays unresolved.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import network_study
from network_followup import IsolatedConnection, save, sha


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def owner_status(path, node, stopped=False):
    status = json.loads(path.read_bytes())
    require(status.get("job_id") == node["runtime_job_id"], "owner status belongs to a different job")
    if stopped:
        require(status.get("state") not in (None, "running", "starting", "queued"),
                "original owner has not confirmed a terminal job")
        require(status.get("cancelled") is True and status.get("timed_out") is False,
                "an explicit owner cancellation, rather than timeout, is required")
        require(status.get("output_complete") is True, "owner terminal output is not complete")
    else:
        require(status.get("state") == "running", "original owner does not report the worker as running")
    return status


def stats(connection, request_id):
    result, _ = connection.call({"kind": "stats"}, request_id)
    require(result.get("ok") is True, "worker refused the current binding")
    return result


def validate_read(result, fixture):
    require(result.get("ok") is True, "worker read was rejected")
    require(result.get("parameter_sha256") == fixture["parameter_sha256"], "loaded parameters changed")
    require(result.get("values") == fixture["values"], "reloaded native outputs differ from the frozen fixture")


def before(node, fixture):
    connection = IsolatedConnection(node)
    try:
        initial = stats(connection, "lifecycle-before-stats")
        result, elapsed = connection.call({"kind": "read", "features": fixture["features"]},
                                          "lifecycle-original-read")
        validate_read(result, fixture)
        terminal = stats(connection, "lifecycle-before-terminal")
        require(terminal["rows"] - initial["rows"] == len(fixture["features"]), "unexpected original inference count")
        return {"node": node, "initial": initial, "read": result, "read_rpc_ns": elapsed,
                "terminal": terminal, "original_request_id": "lifecycle-original-read"}
    finally:
        connection.close()


def watch_stop(node, fixture, output, duration):
    """Wait in a bounded live read loop; transport failure never authorizes replay."""
    connection = IsolatedConnection(node)
    completed = []
    deadline = time.monotonic() + duration
    try:
        initial = stats(connection, "lifecycle-watch-initial")
        require(initial["parameter_sha256"] == fixture["parameter_sha256"], "watch loaded different parameters")
        save(output / "WATCH_READY.json", {"node": node, "at_unix_ns": time.time_ns(),
                                          "initial": initial})
        sequence = 0
        while time.monotonic() < deadline:
            request_id = f"lifecycle-live-read-{sequence}"
            try:
                result, elapsed = connection.call({"kind": "read", "features": [fixture["features"][0]]},
                                                  request_id)
            except (OSError, TimeoutError, RuntimeError) as error:
                return {"completed": completed, "unresolved_request_id": request_id,
                        "transport_error": repr(error), "failed_at_unix_ns": time.time_ns(),
                        "automatic_retry_count": 0, "owner_stop_still_requires_terminal_receipt": True}
            require(result.get("ok") and result.get("values") == [fixture["values"][0]],
                    "a live read returned a different value before stop")
            require(result.get("parameter_sha256") == fixture["parameter_sha256"],
                    "live read parameter identity changed")
            completed.append({"request_id": request_id, "rpc_ns": elapsed,
                              "compute_ns": result["compute_ns"]})
            sequence += 1
            # Low observation load; this is a lifecycle test, not a throughput test.
            time.sleep(0.05)
        raise TimeoutError("owner stop was not observed within the bounded watch period")
    finally:
        connection.close()


def stopped(node):
    connection = None
    try:
        connection = IsolatedConnection(node)
        result, _ = connection.call({"kind": "stats"}, "lifecycle-stopped-endpoint")
    except (OSError, TimeoutError, RuntimeError) as error:
        return {"old_endpoint_unavailable": True, "transport_error": repr(error),
                "automatic_retry_count": 0}
    finally:
        if connection is not None:
            connection.close()
    raise ValueError(f"a service still answered at the old endpoint: {result}")


def after(node, fixture, previous):
    old = previous["node"]
    require(node["name"] == old["name"], "restart must be on the same configured physical host")
    require(node["runtime_job_id"] != old["runtime_job_id"], "restart reused the old Runtime job id")
    require(node["generation"] > old["generation"], "deployment generation did not increase")
    require(node["artifact_sha256"] == old["artifact_sha256"], "recovery substituted a different model artifact")
    connection = IsolatedConnection(node)
    try:
        initial = stats(connection, "lifecycle-restarted-initial")
        require(initial["rows"] == 0 and initial["requests"] == 0 and initial["compute_ns"] == 0,
                "new process already executed inference before this recovery probe")
        require(initial["parameter_sha256"] == previous["terminal"]["parameter_sha256"],
                "the new process loaded different parameters")
        # Keep the new instance/address and change only generation. This isolates
        # the generation check from an incidental changed instance or TCP port.
        stale, _ = connection.call({"kind": "read", "features": fixture["features"]},
                                   previous["original_request_id"], generation=old["generation"])
        require(stale.get("ok") is False and stale.get("error") == "binding_mismatch",
                "an old deployment generation was accepted by the new process")
        after_stale = stats(connection, "lifecycle-after-stale")
        require(all(after_stale[key] == initial[key] for key in ("rows", "requests", "compute_ns")),
                "an old-generation request executed numeric model work")
        result, elapsed = connection.call({"kind": "read", "features": fixture["features"]},
                                          "lifecycle-new-generation-read")
        validate_read(result, fixture)
        terminal = stats(connection, "lifecycle-restarted-terminal")
        require(terminal["rows"] == len(fixture["features"]) and terminal["requests"] == 1,
                "unexpected inference after restart")
        return {"node": node, "initial": initial, "stale_request": stale, "after_stale": after_stale,
                "read": result, "read_rpc_ns": elapsed, "terminal": terminal,
                "same_parameter_reload": True, "old_generation_numeric_work": 0,
                "old_pending_agent_operation_resumed": False,
                "scope": "Runtime-owned process restart and numeric-parameter reload; no durable Agentd turn resumption"}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "watch-stop", "stopped", "after"))
    parser.add_argument("--deployments", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--owner-status", type=Path, required=True,
                        help="Actual parsed process_status response, with job_id and state")
    parser.add_argument("--node", default="x230")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch-seconds", type=int, default=90)
    args = parser.parse_args()
    require(10 <= args.watch_seconds <= 180, "watch duration must remain bounded")
    deployment = json.loads(args.deployments.read_bytes())
    matches = [node for node in deployment["nodes"] if node["name"] == args.node]
    require(len(matches) == 1, "exactly one original node binding is required")
    node = matches[0]
    require(bool(node.get("runtime_job_id")), "original Runtime job id is required")
    fixture = json.loads(args.fixture.read_bytes())
    require(1 <= len(fixture["features"]) <= 64 and len(fixture["features"]) == len(fixture["values"]),
            "one bounded original fixture batch is required")
    source_paths = [Path(__file__).resolve(), Path(network_study.__file__).resolve(),
                    Path(__file__).with_name("network_followup.py").resolve()]
    sources = {str(path): sha(path) for path in source_paths}
    if args.phase == "before":
        args.output.mkdir(parents=True, exist_ok=False)
        save(args.output / "PROTOCOL.json", {"schema": "hepta.native-cell-owner-restart.v1",
            "sources": sources, "original_deployment_sha256": sha(args.deployments),
            "fixture_sha256": sha(args.fixture), "original_node": node,
            "automatic_worker_start_or_retry": False})
    else:
        protocol = json.loads((args.output / "PROTOCOL.json").read_bytes())
        require(protocol["sources"] == sources and protocol["fixture_sha256"] == sha(args.fixture),
                "lifecycle source or fixture changed between phases")
        if args.phase != "after":
            require(protocol["original_deployment_sha256"] == sha(args.deployments),
                    "the original deployment changed before stop was confirmed")
    start, cpu = time.perf_counter(), time.process_time()
    record = {"phase": args.phase, "started_at_unix_ns": time.time_ns(),
              "owner_status_sha256": sha(args.owner_status), "deployment_sha256": sha(args.deployments)}
    try:
        record["owner_status"] = owner_status(args.owner_status, node, stopped=args.phase == "stopped")
        if args.phase == "before":
            record["result"] = before(node, fixture)
        elif args.phase == "watch-stop":
            record["result"] = watch_stop(node, fixture, args.output, args.watch_seconds)
        elif args.phase == "stopped":
            record["result"] = stopped(node)
        else:
            stop_record = json.loads((args.output / "stopped.json").read_bytes())
            require(stop_record["status"] == "passed", "original owner stop has not passed")
            watch_record = json.loads((args.output / "watch-stop.json").read_bytes())
            require(watch_record["status"] == "passed" and watch_record["result"]["completed"],
                    "an active original read loop was not observed before stop")
            require(watch_record["result"]["automatic_retry_count"] == 0,
                    "an unresolved read was retried")
            previous = json.loads((args.output / "before.json").read_bytes())["result"]
            require(stop_record["owner_status"]["job_id"] == previous["node"]["runtime_job_id"],
                    "terminal receipt is not for the original worker")
            record["result"] = after(node, fixture, previous)
        record["status"] = "passed"
    except Exception as error:
        record.update(status="failed", error=repr(error))
    record.update(ended_at_unix_ns=time.time_ns(), wall_seconds=time.perf_counter() - start,
                  coordinator_cpu_seconds=time.process_time() - cpu)
    save(args.output / (args.phase + ".json"), record)
    print(json.dumps({key: record.get(key) for key in ("phase", "status", "error", "wall_seconds")}), flush=True)
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
