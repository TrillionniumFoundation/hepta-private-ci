"""One admitted ai395 -> pocket4 SSH round; no listeners, model, or retries."""
import argparse
import base64
import os
from pathlib import Path
import platform
import resource
import shlex
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

from profile_io import canonical, digest, fields, parse, read_named, require, sha, write_new
from exact_equations import OBJECTIVE, ROSTER, contribution, solve

FRAME_CAP = 65536
RESULT_CAP = 262144
PROXY_SHA = "62806672b699d794e2fe9c738a281727fa1fd6595266440a747f8a4145d449e9"
SOURCE_NAMES = {"profile_io.py", "exact_equations.py", "peer.py"}


def timeout(_signum, _frame):
    raise TimeoutError("fixed peer deadline exhausted")


def limits(node):
    resource.setrlimit(resource.RLIMIT_CPU, (10, 11))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (RESULT_CAP, RESULT_CAP))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(50 if node == "ai395" else 45)


class Frames:
    def __init__(self, reader, writer, common_sha256, node):
        self.reader, self.writer, self.common_sha256 = reader, writer, common_sha256
        self.node = node
        self.peer = next(value for value in ROSTER if value != node)
        self.sent, self.received = [], []

    def exact(self, count):
        chunks = bytearray()
        while len(chunks) < count:
            part = self.reader.read(count - len(chunks))
            require(part, "unexpected peer EOF")
            chunks.extend(part)
        return bytes(chunks)

    def send(self, kind, payload):
        require(len(self.sent) < 3, "three outgoing frames only")
        body = {"schema": "hepta.fixed-peer-frame.v1", "common_sha256": self.common_sha256,
                "node": self.node, "to": self.peer, "sequence": len(self.sent), "kind": kind,
                "payload": payload}
        raw = canonical({"body": body, "sha256": sha(canonical(body))})
        require(len(raw) <= FRAME_CAP, "outgoing frame bound")
        framed = struct.pack("!I", len(raw)) + raw
        view = memoryview(framed)
        while view:
            count = self.writer.write(view)
            require(type(count) is int and count > 0, "short peer write")
            view = view[count:]
        self.writer.flush()
        self.sent.append({"kind": kind, "bytes": len(framed), "sha256": sha(framed)})

    def receive(self, kind):
        require(len(self.received) < 3, "three incoming frames only")
        prefix = self.exact(4)
        count = struct.unpack("!I", prefix)[0]
        require(0 < count <= FRAME_CAP, "incoming frame bound")
        raw = self.exact(count)
        envelope = parse(raw, FRAME_CAP)
        fields(envelope, ("body", "sha256"), "frame envelope")
        body = envelope["body"]
        fields(body, ("schema", "common_sha256", "node", "to", "sequence", "kind", "payload"), "frame")
        require(raw == canonical(envelope) and envelope["sha256"] == sha(canonical(body)), "canonical frame hash")
        require(body["schema"] == "hepta.fixed-peer-frame.v1" and body["common_sha256"] == self.common_sha256
                and body["node"] == self.peer and body["to"] == self.node
                and type(body["sequence"]) is int and body["sequence"] == len(self.received)
                and body["kind"] == kind, "wrong, stale, duplicate, or out-of-order frame")
        self.received.append({"kind": kind, "bytes": count + 4, "sha256": sha(prefix + raw)})
        return body["payload"]


def load(args):
    root = Path(args.root)
    common_raw = read_named(root / "common.json", args.common_sha256, 32768)
    common = parse(common_raw, 32768)
    require(common_raw == canonical(common), "canonical common protocol")
    require(common["schema"] == "hepta.fixed-peer-common.v1" and common["active"] is True,
            "inactive or wrong common protocol")
    digest(common["root_admission_sha256"])
    require(common["roster"] == ROSTER and common["objective"] == OBJECTIVE, "fixed roster/objective")
    require(common["round"] == "pft-v5-rational-usb4-20261126-8a32-01", "single fixed round")
    require(set(common["row_sha256"]) == set(ROSTER)
            and len(set(common["row_sha256"].values())) == 2, "distinct pinned local rows")
    require(set(common["source_sha256"]) == SOURCE_NAMES, "exact protocol source set")
    for name in SOURCE_NAMES:
        read_named(Path(__file__).parent / name, common["source_sha256"][name], 65536)
    require(socket.gethostname() == common["hostnames"][args.node], "physical hostname changed")
    row_raw = read_named(root / "row.json", common["row_sha256"][args.node], 16384)
    row = parse(row_raw, 16384)
    require(row_raw == canonical(row), "canonical local row")
    write_new(root / "run.claim.json", canonical({"common_sha256": args.common_sha256,
              "node": args.node, "pid": os.getpid(), "started_ns": time.time_ns()}), 1024)
    return root, common, row


def hello(common, node):
    value = {"node": node, "hostname": socket.gethostname(), "pid": os.getpid(),
             "python": platform.python_version(), "implementation": platform.python_implementation(),
             "executable": sys.executable, "source_sha256": common["source_sha256"],
             "ssh_connection": os.environ.get("SSH_CONNECTION", "") if node == "pocket4" else None}
    check_hello(common, value, node)
    return value


def check_hello(common, value, expected_node):
    fields(value, ("node", "hostname", "pid", "python", "implementation", "executable",
                   "source_sha256", "ssh_connection"), "hello")
    require(value["node"] == expected_node and value["hostname"] == common["hostnames"][expected_node]
            and value["source_sha256"] == common["source_sha256"]
            and value["implementation"] == "CPython"
            and value["python"] == common["python_versions"][expected_node], "peer runtime/source identity")
    require(type(value["pid"]) is int and value["pid"] > 1, "live peer process identity")
    if expected_node == "pocket4":
        parts = value["ssh_connection"].split()
        route = common["transport"]
        require(len(parts) == 4 and parts[0] == route["local_source"]
                and parts[2] == route["peer_address"] and parts[3] == "22"
                and parts[1].isdigit() and 0 < int(parts[1]) <= 65535, "remote direct SSH endpoint")
    else:
        require(value["ssh_connection"] is None, "initiator identity scope")
    return value


def session(channel, common, node, row):
    own = contribution(common, node, row, common["row_sha256"][node])
    greeting = hello(common, node)
    if node == "ai395":
        channel.send("hello", greeting)
        peer = check_hello(common, channel.receive("hello"), channel.peer)
        channel.send("contribution", own)
        remote = channel.receive("contribution")
    else:
        peer = check_hello(common, channel.receive("hello"), channel.peer)
        channel.send("hello", greeting)
        remote = channel.receive("contribution")
        channel.send("contribution", own)
    contributions = {node: own, channel.peer: remote}
    step = solve(common, contributions)
    confirmation = {"step_sha256": sha(canonical(step)), "delta_sha256": step["delta_sha256"],
                    "contribution_sha256": step["contribution_sha256"]}
    if node == "ai395":
        channel.send("step", confirmation)
        received = channel.receive("step")
    else:
        received = channel.receive("step")
        require(received == confirmation, "independent rational solutions differ")
        channel.send("step", confirmation)
    require(received == confirmation, "independent rational solutions differ")
    return {"node_identity": greeting, "peer_identity": peer, "contributions": contributions,
            "step": step, "step_sha256": confirmation["step_sha256"],
            "frames_sent": channel.sent, "frames_received": channel.received,
            "peer_confirmed_same_step": True}


def ssh_command(config, common, common_sha256):
    read_named(config["proxy_source"], PROXY_SHA, 65536)
    read_named(config["inventory"], config["inventory_sha256"], 65536)
    read_named(config["known_hosts"], config["known_hosts_sha256"], 262144)
    proxy = shlex.join([config["proxy_python"], config["proxy_source"], "--inventory",
                        config["inventory"], "--peer", "pocket4", "--verbose"])
    remote = [config["peer_python"], "-B", str(Path(config["peer_code_root"]) / "peer.py"),
              "--node", "pocket4", "--root", config["peer_run_root"], "--common-sha256", common_sha256]
    options = ["BatchMode=yes", "StrictHostKeyChecking=yes", "ForwardAgent=no", "ClearAllForwardings=yes",
               "ConnectTimeout=8", "ConnectionAttempts=1", "ControlMaster=no", "ControlPath=none",
               "ControlPersist=no", "ProxyJump=none", "ProxyUseFdpass=yes", "GlobalKnownHostsFile=/dev/null",
               "HostKeyAlias=hepta-node-pocket4", "CheckHostIP=no", "User=alex", "Port=22",
               "UpdateHostKeys=no", "PermitLocalCommand=no",
               "UserKnownHostsFile=" + config["known_hosts"], "ProxyCommand=" + proxy]
    return ["ssh", "-T"] + [part for option in options for part in ("-o", option)] + ["pocket4", shlex.join(remote)]


def direct_receipt(raw, common):
    require(len(raw) <= 16384, "SSH stderr cap")
    reports = []
    for line in raw.splitlines():
        try:
            value = parse(line, 16384)
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict) and value.get("peer") == "pocket4" and "selected" in value:
            reports.append(value)
    require(len(reports) == 1 and reports[0]["selected"], "one direct socket selection receipt")
    value, route = reports[0]["selected"], common["transport"]
    require(value["local_address"][0] == route["local_source"]
            and value["remote_address"][0] == route["peer_address"]
            and value["transport"] == route["required_transport"] and value["port"] == 22
            and value["interface"] == "br-usb4" and value["interface_bound"] is True,
            "authorized direct transport changed")
    return {"from_node": "ai395", "to_node": "pocket4", "proxy_source_sha256": PROXY_SHA,
            "selection": reports[0], "stderr_sha256": sha(raw), "stderr_bytes": len(raw),
            "stderr_base64": base64.b64encode(raw).decode("ascii"),
            "strict_host_key_checking": True, "controller_relays_contributions": False}


def initiator(args, root, common, row):
    config = parse(read_named(root / "ssh.json", args.ssh_sha256, 16384), 16384)
    argv = ssh_command(config, common, args.common_sha256)
    stderr = bytearray()
    stderr_overflow = []
    reader = None

    def drain():
        while True:
            part = process.stderr.read(1024)
            if not part:
                return
            remaining = 16384 - len(stderr)
            stderr.extend(part[:remaining])
            if len(part) > remaining:
                stderr_overflow.append(True)
                process.stderr.close()
                return

    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
    try:
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        result = session(Frames(process.stdout, process.stdin, args.common_sha256, args.node), common, args.node, row)
        process.stdin.close()
        require(process.stdout.read(1) == b"", "unexpected extra peer bytes")
        deadline = time.monotonic() + 5
        while True:
            observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if observed is not None:
                break
            require(time.monotonic() < deadline, "SSH process exit deadline")
            time.sleep(0.01)
        require(observed.si_code == os.CLD_EXITED and observed.si_status == 0, "remote process failed")
        reader.join(timeout=2)
        require(not reader.is_alive(), "stderr reader unfinished")
        require(not stderr_overflow, "SSH stderr cap")
        result["transport"] = direct_receipt(bytes(stderr), common)
        result["ssh_config_sha256"] = args.ssh_sha256
        result["ssh_argv"] = argv
        return result
    finally:
        # WNOWAIT above never reaps. Retain the leader's PID until group cleanup.
        signal.alarm(0)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        if reader is not None and reader.ident is not None:
            reader.join(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=ROSTER, required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--common-sha256", required=True)
    parser.add_argument("--ssh-sha256")
    args = parser.parse_args()
    started, cpu_started = time.monotonic(), time.process_time()
    limits(args.node)
    root, common, row = load(args)
    try:
        if args.node == "ai395":
            result = initiator(args, root, common, row)
        else:
            result = session(Frames(sys.stdin.buffer, sys.stdout.buffer, args.common_sha256, args.node), common, args.node, row)
            require(sys.stdin.buffer.read(1) == b"", "unexpected trailing initiator bytes")
        result.update({"schema": "hepta.fixed-peer-run.v1", "status": "PEER_STEP_AGREED",
                       "common_sha256": args.common_sha256, "wall_seconds": time.monotonic() - started,
                       "cpu_seconds": time.process_time() - cpu_started, "model_forwards": 0,
                       "vjp": 0, "rational_solves": 1, "real_independent_users": False,
                       "candidate_materialized": False, "nonlinear_validated": False, "adopted": False})
        write_new(root / "result.json", canonical(result), RESULT_CAP)
    except Exception as error:
        write_new(root / "failure.json", canonical({"node": args.node, "common_sha256": args.common_sha256,
                  "error_type": type(error).__name__, "message": str(error)[:2048]}), 4096)
        raise
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
