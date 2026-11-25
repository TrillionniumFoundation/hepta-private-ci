"""One fixed statistic exchange over the hosts' existing authenticated SSH path.

Linux engineering qualification only. This entry does not generate training data,
change SSH trust, open a new listening port, or accept a remote shell callback.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time

import numpy as np

import direct_snapshot
from direct_snapshot import require
from distributed import Receiver, array_hash, durable_write, hashed
from ssh_framed_io import MAX_FRAME, Stream, collect_stderr, terminate_owned_child, wait_owned_child

SCHEMA = "pft-direct-ssh-frozen-snapshot-v2"
SOURCES = (*direct_snapshot.SOURCES, "ssh_framed_io.py", "ssh_snapshot.py")
QUANTIZATION = 10 ** 10


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def context(config):
    frozen = config["frozen"]
    keys = ("round_id", "hosts", "addresses", "expected_contributions", "expected_contribution_ids",
            "parent", "original_source_sha256", "size", "seed")
    return hashed({"schema": SCHEMA, "sources": config["source_sha256"],
                   "frozen": {key: frozen[key] for key in keys}, "roster": config["roster"],
                   "reference_sha256": config["reference_sha256"],
                   "quantization": QUANTIZATION, "deadline_seconds": 45, "frame_limit": MAX_FRAME})


def prepare(config):
    require(sys.platform.startswith("linux") and all(hasattr(os, name) for name in
            ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT", "CLD_EXITED", "CLD_KILLED", "CLD_DUMPED")),
            "This SSH qualification requires Linux WNOWAIT process ownership")
    require(config["schema"] == SCHEMA and config["deadline_seconds"] == 45,
            "Unknown SSH namespace or delivery budget")
    require(config["source_sha256"] == {
        name: sha_file(Path(__file__).parent / name) for name in SOURCES
    }, "Pinned SSH implementation differs")
    frozen = config["frozen"]
    require(frozen["size"] == 8 and frozen["seed"] == 731, "Only the one original engineering case is admitted")
    require(len(config["roster"]) == 2 and config["context_id"] == context(config),
            "The two-host SSH context differs")
    for peer, address in zip(config["roster"], frozen["addresses"]):
        require(address == [peer["address"], 22], "Only the registered existing SSH endpoint is permitted")
        require(re.fullmatch(r"[A-Za-z0-9_.-]+", peer["alias"]) is not None,
                "An exact configured SSH alias is required")
        require(re.fullmatch(r"[A-Za-z0-9_.-]+", peer["user"]) is not None,
                "The existing SSH account must be explicit")
        for key in ("stage", "python"):
            value = peer[key]
            require(value.startswith("/") and re.fullmatch(r"[A-Za-z0-9_./-]+", value) is not None
                    and ".." not in Path(value).parts, "A fixed absolute runtime path is required")
        require(Path(peer["python"]).name in {"python", "python3"}, "Only the admitted Python runtime is permitted")
    if frozen["node"] == 0:
        require(re.fullmatch(r"[0-9a-f]{64}", config["remote_config_sha256"]) is not None,
                "An independent responder configuration digest is required")
    for path, digest in config["ssh"]["file_sha256"].items():
        require(sha_file(path) == digest, "Existing SSH configuration, inventory or trust changed")
    projected = direct_snapshot.prepare(frozen, Path(frozen["output"]))
    reference_raw = Path(config["reference"]).read_bytes()
    require(hashlib.sha256(reference_raw).hexdigest() == config["reference_sha256"],
            "The previously published central reference changed")
    original = json.loads(reference_raw)
    require(original["source_sha256"] == frozen["original_source_sha256"], "Central reference source differs")
    records = [item for item in original["records"] if item["size"] == 8 and item["seed"] == 731]
    require(len(records) == 1, "Ambiguous original central reference")
    reference = records[0]
    require(hashed(reference["audit_candidate_integer_grid"]) == reference["audit_candidate_sha256"],
            "Central reference grid is corrupt")
    return projected, reference


def identity(config, config_sha256):
    node = config["frozen"]["node"]
    value = {"node": node, "hostname": socket.gethostname(), "uid": os.getuid(),
             "pid": os.getpid(), "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
             "executable": sys.executable, "python": sys.version, "numpy": np.__version__,
             "config_sha256": config_sha256, "context_id": config["context_id"]}
    check_identity(config, value, node)
    return value


def check_identity(config, value, node):
    require(isinstance(value, dict), "Peer identity must be an object")
    peer = config["roster"][node]
    require(value.get("node") == node and type(value.get("node")) is int
            and value.get("hostname") == peer["hostname"] and value.get("boot") == peer["boot"]
            and value.get("uid") == peer["uid"] and value.get("executable") == peer["python"]
            and value.get("context_id") == config["context_id"]
            and type(value.get("pid")) is int and value["pid"] > 0,
            "SSH application process differs from the frozen host roster")


def check_connection(config, connection):
    require(isinstance(connection, str), "The responder must be started by native SSH")
    parts = connection.split()
    require(len(parts) == 4 and parts[0] == config["roster"][0]["address"]
            and parts[2] == config["roster"][1]["address"] and parts[3] == "22"
            and parts[1].isdigit() and 0 < int(parts[1]) < 65536,
            "SSH_CONNECTION differs from the registered direct USB4 endpoints")
    return {"client": [parts[0], int(parts[1])], "server": [parts[2], 22]}


def accept_contribution(receiver, config, message, owner):
    frozen = config["frozen"]
    require(isinstance(message, dict) and message.get("client_id") == str(owner)
            and message.get("payload_sha256") == frozen["expected_contributions"][owner]
            and message.get("contribution_id") == frozen["expected_contribution_ids"][owner],
            "The actual peer contribution differs from the admitted owner or frozen payload")
    require(receiver.accept(message) == "accepted", "The strict Receiver rejected the contribution")


def solve(receiver, config, reference, folder):
    frozen = config["frozen"]
    require(sorted(receiver.messages) == sorted(frozen["expected_contribution_ids"]),
            "Both exact original contributions are required before solving")
    snapshot = receiver.freeze(frozen["round_id"])
    receiver.checkpoint(folder / "ledger.json")
    gram, moment = receiver.sums()
    ridge = .01
    require(receiver.header["objective_id"] == hashed({"ridge": ridge, "loss": "sum squared residual", "version": 1}),
            "Actual ridge objective differs")
    parent = np.asarray(frozen["parent"], dtype=float)
    require(array_hash(parent) == receiver.header["parent_id"], "Actual parent differs")
    action = np.linalg.solve(gram + ridge * np.eye(len(moment)), moment)
    values, vectors = np.linalg.eigh((gram + gram.T) * .5)
    tolerance = 64 * np.finfo(float).eps * len(moment) * max(1., float(np.max(np.abs(values))))
    active = values > tolerance
    support_error = float(np.linalg.norm(vectors[:, ~active].T @ moment) / max(np.linalg.norm(moment), 1e-15))
    require(support_error <= 1e-12, "Discarded directions contain a material target component")
    directional = vectors[:, active] @ ((vectors[:, active].T @ moment) / (values[active] + ridge))
    directional_error = float(np.linalg.norm(directional - action) / max(np.linalg.norm(action), 1e-15))
    normal_error = float(np.linalg.norm((gram + ridge * np.eye(len(moment))) @ action - moment)
                         / max(np.linalg.norm(moment), 1e-15))
    raw_candidate = parent + action
    require(np.isfinite(raw_candidate).all() and directional_error <= 1e-10 and normal_error <= 1e-10,
            "Independent analytic directions or normal equation differ")
    grid = [round(float(item) * QUANTIZATION) for item in raw_candidate]
    require(grid == reference["audit_candidate_integer_grid"], "Peer-derived solve differs from the old central reference")
    # This protocol explicitly admits canonical 1e-10 weights. Full precision
    # values and their errors remain in the evidence; no hidden hash tolerance.
    candidate = np.asarray(grid, dtype=float) / QUANTIZATION
    central_error = float(np.linalg.norm(raw_candidate - candidate) / max(np.linalg.norm(candidate), 1e-15))
    result = {"accepted_ids": sorted(receiver.messages), "statistics_snapshot_id": snapshot["snapshot_id"],
              "candidate": candidate.tolist(), "candidate_sha256": array_hash(candidate),
              "raw_candidate": raw_candidate.tolist(), "raw_candidate_sha256": array_hash(raw_candidate),
              "candidate_integer_grid": grid, "quantization_step": 1 / QUANTIZATION,
              "effective_rank": int(np.count_nonzero(active)), "feature_dimension": len(moment),
              "effective_direction_relative_error": directional_error, "normal_residual_relative": normal_error,
              "discarded_target_relative_norm": support_error,
              "central_reference_relative_error_including_quantization": central_error,
              "central_reference_grid_sha256": reference["audit_candidate_sha256"],
              "central_reference_artifact_sha256": config["reference_sha256"],
              "ledger_sha256": sha_file(folder / "ledger.json")}
    durable_write(folder / "CANDIDATE.json", result)
    return result


def check_summary(own, other):
    require(isinstance(other, dict), "Peer summary must be an object")
    for key in ("accepted_ids", "statistics_snapshot_id", "candidate", "candidate_sha256",
                "candidate_integer_grid", "quantization_step", "central_reference_grid_sha256",
                "central_reference_artifact_sha256"):
        require(other.get(key) == own[key], "Independent peer candidate or snapshot differs")
    raw = np.asarray(other.get("raw_candidate"), dtype=float)
    local = np.asarray(own["raw_candidate"], dtype=float)
    require(raw.shape == local.shape and np.isfinite(raw).all(), "Invalid peer full-precision candidate")
    error = float(np.linalg.norm(raw - local) / max(np.linalg.norm(local), 1e-15))
    require(error <= 1e-12, "Independent full-precision peer solves differ")
    return error


def exchange(config, projected, reference, stream, own, ssh_connection=None):
    node, folder = projected["node"], Path(projected["directory"])
    receiver = Receiver(projected["header"])
    accept_contribution(receiver, config, projected["message"], node)
    receiver.checkpoint(folder / "ledger.json")
    if node == 0:
        stream.send("hello", {"identity": own})
        hello = stream.receive("hello")
        check_identity(config, hello.get("identity"), 1)
        require(hello["identity"]["config_sha256"] == config["remote_config_sha256"], "Responder configuration pin differs")
        observed = check_connection(config, hello.get("ssh_connection"))
        stream.send("contribution", projected["message"])
        accept_contribution(receiver, config, stream.receive("contribution"), 1)
    else:
        observed = check_connection(config, ssh_connection)
        hello = stream.receive("hello")
        check_identity(config, hello.get("identity"), 0)
        stream.send("hello", {"identity": own, "ssh_connection": ssh_connection})
        accept_contribution(receiver, config, stream.receive("contribution"), 0)
        receiver.checkpoint(folder / "ledger.json")
        stream.send("contribution", projected["message"])
    result = solve(receiver, config, reference, folder)
    if node == 0:
        stream.send("summary", result)
        other = stream.receive("summary")
        peer_error = check_summary(result, other)
        commit = {"initiator_summary_sha256": hashed(result), "responder_summary_sha256": hashed(other)}
        stream.send("commit", commit)
        complete = stream.receive("complete")
        require(complete == {"commit_sha256": hashed(commit)}, "Final direct peer confirmation differs")
    else:
        other = stream.receive("summary")
        peer_error = check_summary(result, other)
        stream.send("summary", result)
        commit = stream.receive("commit")
        require(commit == {"initiator_summary_sha256": hashed(other), "responder_summary_sha256": hashed(result)},
                "Initiator did not confirm this independent result")
        stream.send("complete", {"commit_sha256": hashed(commit)})
    return {**result, "peer_full_precision_relative_error": peer_error, "peer_summary_sha256": hashed(other),
            "peer_identity": hello["identity"], "ssh_connection": observed, "transfers": stream.events}


def ssh_argv(config):
    ssh, peer = config["ssh"], config["roster"][1]
    require(set(ssh) == {"file_sha256", "guard", "inventory", "identity_file", "known_hosts",
                         "host_key_alias", "server_host_key", "client_public_key"}, "Unknown SSH transport option")
    for key in ("guard", "inventory", "known_hosts"):
        require(ssh[key] in ssh["file_sha256"], "SSH guard, inventory and trust must be pinned")
    proxy = shlex.join(["/usr/bin/python3", ssh["guard"], "--inventory", ssh["inventory"],
                        "--peer", peer["alias"], "--verbose"])
    options = ["BatchMode=yes", "PasswordAuthentication=no", "KbdInteractiveAuthentication=no",
               "StrictHostKeyChecking=yes", "UpdateHostKeys=no", "IdentityAgent=none", "IdentitiesOnly=yes",
               "ControlMaster=no", "ControlPath=none", "ClearAllForwardings=yes", "ForwardAgent=no",
               "ForwardX11=no", "PermitLocalCommand=no", "ConnectionAttempts=1", "ConnectTimeout=5",
               "ServerAliveInterval=2", "ServerAliveCountMax=2", "RequestTTY=no", "ProxyUseFdpass=yes",
               "HostKeyAlgorithms=ssh-ed25519", "IdentityFile=" + ssh["identity_file"],
               "UserKnownHostsFile=" + ssh["known_hosts"], "HostKeyAlias=" + ssh["host_key_alias"],
               "GlobalKnownHostsFile=/dev/null", "KnownHostsCommand=none", "ProxyJump=none",
               "Hostname=" + peer["address"], "User=" + peer["user"], "Port=22",
               "ProxyCommand=" + proxy]
    # Keep the existing guard and exact trust roots while excluding unrelated
    # ambient Match exec / KnownHostsCommand / Include callbacks.
    argv = ["/usr/bin/ssh", "-F", "/dev/null", "-T", "-v"]
    for option in options:
        argv.extend(["-o", option])
    # The only remote command is this source-pinned entry with a source-pinned
    # configuration. There is no configurable executable callback or shell body.
    remote = shlex.join([peer["python"], peer["stage"] + "/ssh_snapshot.py",
                         peer["stage"] + "/SSH_CONFIG.json", "--expected", config["remote_config_sha256"]])
    return argv + [peer["alias"], remote]


def check_ssh_diagnostics(config, raw, observed):
    text = raw.decode("utf-8", errors="replace")
    reports = []
    for line in text.splitlines():
        if line.startswith("{"):
            value = json.loads(line)
            if "selected" in value:
                reports.append(value)
    require(len(reports) == 1 and len(reports[0]["attempts"]) == 1,
            "SSH guard must select the registered USB4 endpoint without fallback")
    selected = reports[0]["selected"]
    own, peer = config["roster"]
    require(selected["transport"] == "usb4" and selected["status"] == "connected"
            and selected["interface_bound"] is True and selected["interface_policy"] == "required"
            and selected["interface"] == own["interface"]
            and selected["local_address"] == observed["client"]
            and selected["remote_address"] == observed["server"], "Guard and responder endpoints differ")
    require("Server host key: ssh-ed25519 " + config["ssh"]["server_host_key"] in text
            and any("Server accepts key:" in line and config["ssh"]["client_public_key"] in line
                    for line in text.splitlines())
            and 'using "publickey"' in text, "Existing SSH cryptographic identities were not observed")
    return reports[0]


def run(path, expected):
    raw_config = Path(path).read_bytes()
    require(hashlib.sha256(raw_config).hexdigest() == expected, "Independent SSH configuration pin differs")
    config = json.loads(raw_config)
    projected, reference = prepare(config)
    own = identity(config, expected)
    folder = Path(projected["directory"])
    folder.mkdir(mode=0o700)
    started = time.monotonic()
    deadline = started + 45
    durable_write(folder / "STARTED.json", {**own, "started_unix_ns": time.time_ns(),
                  "scope": "engineering_frozen_statistics", "delivery_deadline_seconds": 45,
                  "child_reap_budget_seconds": 4, "diagnostic_join_budget_seconds": .1})
    process, stderr_state, stderr_thread, stderr_stop, failure = None, None, None, None, None
    try:
        if projected["node"] == 0:
            argv = ssh_argv(config)
            durable_write(folder / "SSH_ARGV.json", argv)
            environment = {**os.environ, "LC_ALL": "C", "SSH_ASKPASS_REQUIRE": "never"}
            environment.pop("SSH_AUTH_SOCK", None)
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True, env=environment)
            durable_write(folder / "SSH_CHILD.json", {"pid": process.pid, "owned_process_group": process.pid})
            stderr_state, stderr_thread, stderr_stop, cancel = collect_stderr(process, deadline)
            stream = Stream(process.stdout.fileno(), process.stdin.fileno(), folder, 0,
                            projected["round_id"], config["context_id"], deadline, cancel)
            result = exchange(config, projected, reference, stream, own)
            process.stdin.close()
            observed_exit = wait_owned_child(process, deadline, cancel)
            stderr_thread.join(timeout=max(.001, deadline - time.monotonic()))
            require(observed_exit == 0 and not stderr_thread.is_alive() and stderr_state["eof"]
                    and not stderr_state["overflow"] and stderr_state["error"] is None,
                    "The fixed SSH responder did not finish within the admitted bounds")
            result["ssh_guard"] = check_ssh_diagnostics(config, bytes(stderr_state["raw"]), result["ssh_connection"])
        else:
            stream = Stream(sys.stdin.fileno(), sys.stdout.fileno(), folder, 1,
                            projected["round_id"], config["context_id"], deadline)
            result = exchange(config, projected, reference, stream, own, os.environ.get("SSH_CONNECTION"))
        require(time.monotonic() <= deadline, "The single SSH application deadline was exceeded")
        durable_write(folder / "result.json", {**result, "identity": own})
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)[:500]}
        raise
    finally:
        teardown_started = time.monotonic()
        teardown_error = None
        try:
            if process is not None:
                try:
                    terminate_owned_child(process)
                finally:
                    if stderr_thread is not None:
                        stderr_stop.set()
                        stderr_thread.join(timeout=.1)
                for stream_file in (process.stdin, process.stdout):
                    stream_file.close()
                if stderr_thread is None or not stderr_thread.is_alive():
                    process.stderr.close()
                else:
                    raise RuntimeError("Owned SSH diagnostic pipe did not close after bounded reaping")
        except BaseException as error:
            teardown_error = {"type": type(error).__name__, "message": str(error)[:500]}
        if stderr_state is not None:
            (folder / "SSH.stderr").write_bytes(stderr_state["raw"])
        durable_write(folder / "END.json", {**own, "status": "FAILED" if failure or teardown_error else "COMPLETE",
                      "error": failure, "wall_seconds": time.monotonic() - started,
                      "teardown_seconds": time.monotonic() - teardown_started,
                      "teardown_error": teardown_error,
                      "ssh_stderr_eof": None if stderr_state is None else stderr_state["eof"],
                      "ssh_child_exit_code": None if process is None else process.returncode,
                      "training_runs": 0, "real_user_adoptions": 0, "data_generated": False,
                      "scope": "engineering_frozen_statistics"})
        if teardown_error is not None:
            raise RuntimeError("Owned SSH cleanup did not reach a definite bounded terminal state")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()
    run(args.config, args.expected)


if __name__ == "__main__":
    main()
