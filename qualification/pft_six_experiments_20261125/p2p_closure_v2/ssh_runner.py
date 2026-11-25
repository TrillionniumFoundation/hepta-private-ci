#!/usr/bin/env python3
"""Initiate direct peer SSH sessions and supervise a real remote crash/restart."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from types import SimpleNamespace

from sufficient import State, digest, durable, encode, sha, sources
from stream_peer import Frames, check_hello, hello, receive_contributions, send_contributions

PROXY_SHA = "62806672b699d794e2fe9c738a281727fa1fd6595266440a747f8a4145d449e9"


def command(config, size, seed, round_id, resume, local_test):
    peer_script = str(Path(config["peer_code_root"]) / "stream_peer.py")
    argv = [config["peer_python"], peer_script, "--node", "pocket4", "--model", config["peer_model"],
            "--root", config["peer_result_root"], "--round-id", round_id, "--size", str(size), "--seed", str(seed)]
    if config.get("peer_external"):
        argv.extend(["--external", config["peer_external"].format(size=size, seed=seed)])
    if resume:
        argv.append("--resume")
    if local_test:
        return argv + ["--local-test"]
    proxy = Path.home() / ".ssh/hepta-transport/ssh_transport.py"
    if sha(proxy.read_bytes()) != PROXY_SHA:
        raise ValueError("Existing transport source changed")
    proxy_command = shlex.join([config["proxy_python"], str(proxy), "--inventory",
                               str(proxy.parent / "inventory.json"), "--peer", "pocket4", "--verbose"])
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ForwardAgent=no",
            "-o", "ClearAllForwardings=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1",
            "-o", "ProxyCommand=" + proxy_command, "pocket4", shlex.join(argv)]


def transport_receipt(stderr, config, local_test):
    if local_test:
        return {"kind": "local_pipe_test", "not_multihost_evidence": True}
    reports = []
    for line in stderr.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "selected" in value and value.get("peer") == "pocket4":
            reports.append(value)
    if len(reports) != 1 or not reports[0]["selected"]:
        raise ValueError("Missing direct socket selection receipt")
    value, selected = reports[0], reports[0]["selected"]
    valid = selected["local_address"][0] == config["local_source"] and selected["remote_address"][0] == config["peer_address"]
    if not valid or selected["transport"] != config["required_transport"] or selected["port"] != 22:
        raise ValueError("Connection did not use the authorized direct endpoint")
    return {"kind": "direct_peer_ssh", "from_node": "ai395", "to_node": "pocket4", "port": 22,
            "selected_transport": selected["transport"], "interface_bound": selected["interface_bound"],
            "endpoint_verified": valid, "selection_elapsed_ms": value["elapsed_ms"],
            "attempt_count": len(value["attempts"]), "proxy_source_sha256": PROXY_SHA,
            "raw_private_receipt_sha256": sha(stderr.encode()), "strict_host_key_checking": True,
            "batch_mode": True, "agent_forwarding": False, "controller_relays_training_bytes": False}


def run_case(config, size, seed, local_test):
    round_id = config["round_prefix"] + f"-n{size}-s{seed}"
    started = time.monotonic()
    args = SimpleNamespace(node="ai395", root=config["local_result_root"], model=config["local_model"],
                           round_id=round_id, size=size, seed=seed, resume=False,
                           external=config.get("local_external", "").format(size=size, seed=seed) or None)
    state = State(args)
    attempts, crash_verified = [], False
    for attempt in range(2):
        launch = time.monotonic()
        stderr_path = state.folder / f"ssh_attempt_{attempt}.private.log"
        with stderr_path.open("wb") as error_stream:
            process = subprocess.Popen(command(config, size, seed, round_id, attempt > 0, local_test),
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error_stream, bufsize=0)
            channel = Frames(process.stdout, process.stdin, state)
            peer = None
            expected_crash = False
            try:
                peer = check_hello(state, channel.receive("hello"))
                state.metrics["ssh_start_seconds"] += time.monotonic() - launch
                if attempt:
                    crash = peer["crash_receipt"]
                    crash_verified = peer["restored_contributions"] == 5 and peer["restore_ledger_sha256"] == crash["ledger_sha256"]
                    crash_verified = crash_verified and peer["previous_pid"] == crash["pid"] and peer["pid"] != crash["pid"]
                    if not crash_verified:
                        raise ValueError("Remote restart did not restore the expected durable state")
                    recovery_gap = (peer["unix_ns"] - crash["unix_ns"]) / 1e9
                channel.send("hello", hello(state))
                send_contributions(channel, state)
                receive_contributions(channel, state)
                own = state.solve()
                remote = channel.receive("candidate")["payload"]
                if remote["candidate_sha256"] != own["candidate_sha256"] or remote["aggregate_sha256"] != own["aggregate_sha256"]:
                    raise ValueError("Independent peer solutions differ")
                channel.send("candidate_confirm", {"candidate_sha256": own["candidate_sha256"], "aggregate_sha256": own["aggregate_sha256"]})
                done = channel.receive("done")["payload"]
                if done["candidate_sha256"] != own["candidate_sha256"]:
                    raise ValueError("Peer completion candidate mismatch")
                channel.send("done_ack", {"candidate_sha256": own["candidate_sha256"]})
            except EOFError:
                if attempt != 0 or peer is None:
                    raise
                expected_crash = True
            finally:
                process.stdin.close()
                process.stdout.close()
                try:
                    exit_code = process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
                    raise TimeoutError("Peer process did not terminate")
        stderr = stderr_path.read_text()
        receipt = transport_receipt(stderr, config, local_test)
        attempts.append({"attempt": attempt, "peer_pid": peer["pid"] if peer else None,
                         "ssh_exit_code": exit_code, "wall_seconds": time.monotonic() - launch,
                         "transport": receipt})
        if expected_crash:
            if exit_code != 17:
                raise ValueError("Expected actual remote exit code 17")
            tick = time.monotonic()
            time.sleep(0.35)
            state.metrics["fault_wait_seconds"] += time.monotonic() - tick
            continue
        if exit_code != 0 or not crash_verified:
            raise ValueError("Peer completion did not close the crash/recovery lifecycle")
        result = state.finish({"transport": "local_pipe_test" if local_test else "direct_peer_ssh_usb4",
                               "ssh_attempts": attempts, "peer_pid": peer["pid"], "peer_same_candidate": True,
                               "actual_exit_17_verified": True, "restored_checkpoint_verified": crash_verified,
                               "remote_recovery_gap_seconds": recovery_gap, "peer_solution": remote,
                               "case_wall_seconds": time.monotonic() - started})
        return result
    raise RuntimeError("No successful recovered peer session")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--local-test", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    root = Path(config["local_result_root"])
    root.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    records = []
    for size, seed in config["cases"]:
        try:
            result = run_case(config, size, seed, args.local_test)
        except Exception as error:
            durable(root / "failure.json", encode({"size": size, "seed": seed,
                    "error_type": type(error).__name__, "error": str(error), "completed": len(records),
                    "sources": sources(), "wall_seconds": time.monotonic() - start}) + b"\n")
            raise
        records.append({"round_id": result["round_id"], "size": size, "seed": seed,
                        "candidate_sha256": result["solution"]["candidate_sha256"],
                        "case_wall_seconds": result["case_wall_seconds"]})
        print(json.dumps(records[-1]), flush=True)
    report = {"record_kind": "pft2_direct_peer_ssh_supervisor", "schema_version": 1,
              "node": "ai395", "pid": os.getpid(), "sources": sources(), "local_test": args.local_test,
              "completed_cases": len(records), "records": records, "wall_seconds": time.monotonic() - start,
              "timing_note": "Node wall times overlap. Pipe read waits include peer computation and persistence; phase times are not additive across hosts."}
    raw = encode(report) + b"\n"
    durable(root / "supervisor_result.json", raw)
    print(json.dumps({"completed_cases": len(records), "supervisor_sha256": sha(raw), "wall_seconds": report["wall_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
