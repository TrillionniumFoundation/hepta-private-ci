"""Qualify frozen Cell requests using an existing configured runtime host.

Each cold observation creates a fresh MCP process and reads the original job.
An unknown submission remains in the bridge ledger and is never resubmitted.
"""

import argparse
import os
from pathlib import Path
import platform
import sys
import time
import traceback

from runtime_process_bridge import RuntimeProcessBridge
from runtime_stdio import StdioRuntime, canonical, file_digest, require, strict_json


def write_new(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def session(profile, database, request, output, label, cold):
    record = {"schema": "hepta.cell.configured-runtime-session.v1", "status": "FAIL",
              "cold": cold, "request": request, "profile": profile}
    runtime = bridge = None
    try:
        runtime = StdioRuntime(profile["runtime"], timeout_seconds=60)
        record["runtime"] = runtime.identity
        bridge = RuntimeProcessBridge(profile, database, runtime.call,
                                      transport_identity=runtime.identity)
        observed = bridge.execute(request)
        deadline = time.monotonic() + profile["process"]["timeout_seconds"] + 45
        while observed["state"] != "TERMINAL" and observed.get("job_id") and time.monotonic() < deadline:
            time.sleep(0.25)
            observed = bridge.observe(request["request_id"])
        record["observation"] = observed
        require(observed["state"] == "TERMINAL", "original job has no complete terminal witness")
        require(observed["runtime_state"] == "succeeded" and observed["exit_code"] == 0,
                "original worker process failed")
        calls = [r["request"]["params"]["name"] for r in runtime.records
                 if r["request"].get("method") == "tools/call"]
        require(calls.count("process_status") >= 2 and "process_read" in calls,
                "original owner publication and output were not reobserved")
        require(calls.count("process_start") == (0 if cold else 1), "unexpected process resubmission")
        domain = strict_json(bytes.fromhex(observed["streams"]["stdout"]["bytes_hex"]))
        require(domain.get("candidate_sha256") == profile["candidate_sha256"], "different candidate")
        record.update(status="PASS", domain=domain)
        return observed, domain
    except BaseException:
        record["error"] = traceback.format_exc()
        raise
    finally:
        if bridge:
            bridge.close()
        if runtime:
            record["protocol"] = runtime.records
            runtime.close()
        write_new(output / (label + ".json"), record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("candidate", "inputs", "runtime-source", "runtime-binary",
                 "runtime-config", "build-receipt", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    for flag in ("remote-bundle", "remote-python", "remote-state"):
        parser.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    started = time.monotonic()
    report = {"schema": "hepta.cell.configured-runtime-lane.v1", "status": "FAIL",
              "actual_runtime_transport": False, "completed_requests": [],
              "final_use_capability_boundary_qualified": False,
              "ordinary_daemon_qualification": False, "independent_real_task_benefit": False,
              "harness_sha256": file_digest(__file__)}
    try:
        candidate = strict_json(args.candidate.read_bytes())
        candidate_hash, pins = file_digest(args.candidate), candidate["runtime_identity"]
        controller = {"system": platform.system(), "machine": platform.machine(),
                      "release": platform.release(), "python": platform.python_version(),
                      "hostname_sha256": __import__("hashlib").sha256(platform.node().encode()).hexdigest(),
                      "python_sha256": file_digest(Path(sys.executable).resolve())}
        require(controller == pins["controller_device"], "controller device differs from frozen runtime")
        build = strict_json(args.build_receipt.read_bytes())
        require(build["status"] == "PASS" and build["head"] == pins["source_commit"]
                and build["tree"] == pins["source_tree"] and build["source_status"] == ""
                and build["binary_sha256"] == pins["binary_sha256"], "source build receipt mismatch")
        require(candidate["source_bases"]["runtime"] == pins["source_commit"], "runtime source mismatch")
        required = {"runtime_stdio.py", "runtime_process_contract.py", "runtime_process_bridge.py"}
        helpers = {}
        for item in candidate["files"]:
            if item["root"] == "cells" and item["path"] in {"scripts/" + n for n in required}:
                name = Path(item["path"]).name
                require(file_digest(Path(__file__).parent / name) == item["sha256"], "bridge source changed")
                helpers[name] = item["sha256"]
        require(set(helpers) == required, "candidate omits controller bridge sources")
        inputs_pin = [i for i in candidate["files"] if i["root"] == "artifacts" and i["path"] == "inputs.json"]
        require(len(inputs_pin) == 1 and file_digest(args.inputs) == inputs_pin[0]["sha256"], "task data changed")
        inputs = strict_json(args.inputs.read_bytes())
        runtime = {"source_root": str(args.runtime_source), "source_commit": pins["source_commit"],
                   "binary": str(args.runtime_binary), "binary_sha256": pins["binary_sha256"],
                   "config": str(args.runtime_config), "config_sha256": pins["config_sha256"]}
        report.update(candidate_sha256=candidate_hash, runtime_identity=pins, helpers=helpers,
                      build_receipt_sha256=file_digest(args.build_receipt))
        environment = candidate["device"]["thread_settings"]
        require(all(isinstance(v, str) for v in environment.values()), "explicit numeric thread settings required")
        bundle, state = args.remote_bundle.rstrip("/"), args.remote_state.rstrip("/")
        common = {"schema": "hepta.cell.runtime-process-bridge.v1", "candidate_sha256": candidate_hash,
                  "max_output_bytes": 4 * 1024 * 1024, "runtime": runtime}
        process = {"host": "cell_worker", "executable": args.remote_python, "cwd": bundle + "/cells",
                   "env": environment, "cpu_quota_percent": 200, "memory_max_bytes": 1073741824, "nice": 10}
        worker = {**common, "namespace": "joint-cell-" + candidate_hash + "-worker",
                  "process": {**process, "timeout_seconds": 120,
                              "args": ["-B", bundle + "/cells/scripts/hepta_cell_joint_worker.py",
                                       "--candidate", bundle + "/candidate/candidate.json",
                                       "--database", state + "/cells.sqlite"]}}
        campaign = {**common, "namespace": "joint-cell-" + candidate_hash + "-campaign",
                    "process": {**process, "timeout_seconds": 300,
                                "args": ["-B", bundle + "/cells/scripts/hepta_cell_campaign_worker.py",
                                         "--candidate", bundle + "/candidate/candidate.json",
                                         "--output", state + "/maintenance"]}}
        write_new(args.output / "worker-profile.json", worker)
        write_new(args.output / "campaign-profile.json", campaign)
        requests = [
            ("observe", worker, {"request_id": "runtime-observe", "cell_id": "MEM", "operation": "step",
                                 "payload": {"operation": "observe", "cursor": 0, "observation": inputs["observation"]}}),
            ("predict", worker, {"request_id": "runtime-predict", "cell_id": "MEM", "operation": "step",
                                 "payload": {"operation": "predict", "action": inputs["action"]}}),
            ("campaign", campaign, {"request_id": "runtime-maintenance", "cell_id": "MEM+PRED",
                                    "operation": "maintenance", "payload": {}}),
        ]
        for label, profile, request in requests:
            database = args.output / ("campaign.sqlite" if label == "campaign" else "worker.sqlite")
            first, domain = session(profile, database, request, args.output, label + "-first", False)
            recovered, again = session(profile, database, request, args.output, label + "-cold", True)
            require(first == recovered and domain == again, "cold owner output or identity changed")
            if label == "campaign":
                require(domain.get("schema") == "hepta.runtime-maintenance-observation.v1"
                        and domain.get("status") == "campaign_observed", "maintenance did not complete")
                require(domain.get("runtime_identity") == pins
                        and domain.get("native_image_sha256") == candidate["native"]["image_sha256"],
                        "maintenance runtime or native image changed")
                require(set(domain["native_counts"]) == {"memory", "predictor"}
                        and all(set(c) == {"completed"} and c["completed"] > 0
                                for c in domain["native_counts"].values()), "native learning owner incomplete")
                report.update(campaign_result=domain["campaign_result"], native_counts=domain["native_counts"],
                              campaign_result_sha256=domain["campaign_result_sha256"])
            else:
                require(domain.get("status") == "observed" and domain["continuation"]["phase"] == "completed",
                        "native Cell continuation incomplete")
                if label == "predict":
                    require(bool(domain["result"]["output"]["cell"]["logits"]), "model output absent")
            report["completed_requests"].append({"label": label, "job_id": first["job_id"],
                                                 "same_original_output": True, "cold_runtime_reobserved": True,
                                                 "second_process_start": False})
        report.update(actual_runtime_transport=True, status="PASS")
    except BaseException:
        report["error"] = traceback.format_exc()
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        write_new(args.output / "RESULT.json", report)
    print(canonical({"status": report["status"], "result_sha256": file_digest(args.output / "RESULT.json")}).decode())


if __name__ == "__main__":
    main()
