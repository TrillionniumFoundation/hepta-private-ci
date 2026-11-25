#!/usr/bin/env python3
"""Probe one task listener and existing strict SSH identities without changing rules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time


def emit(path, result):
    content = json.dumps(result, allow_nan=False, sort_keys=True) + "\n"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content)
    os.replace(temporary, path)


def run(command, timeout=8):
    try:
        value = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"exit": value.returncode, "stdout": value.stdout[:9000],
                "stderr": value.stderr[:2500]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"error_type": type(error).__name__, "error": str(error)}


def connection(config, destination, bind_device):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    if bind_device:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                        (config["interface"] + "\0").encode())
    sock.bind((config["source"], 0))
    sock.connect(destination)
    return sock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["server", "client"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    path = Path(args.output)
    start = time.monotonic()
    result = {"node": config["node"], "mode": args.mode, "pid": os.getpid(),
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if args.mode == "server":
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                                (config["interface"] + "\0").encode())
            listener.bind((config["source"], config["port"]))
            listener.listen(4)
            listener.settimeout(0.5)
            result.update({"listening": True, "bound_socket": listener.getsockname(),
                           "device_bound": True, "accepted": []})
            emit(path, result)
            print(json.dumps({"node": config["node"], "listening": True}), flush=True)
            deadline = start + 240
            while time.monotonic() < deadline:
                try:
                    sock, peer = listener.accept()
                except TimeoutError:
                    continue
                with sock:
                    sock.settimeout(2)
                    token = sock.recv(256)
                    valid = peer[0] == config["peer"] and token == config["token"].encode()
                    if valid:
                        sock.sendall(hashlib.sha256(token).hexdigest().encode())
                    result["accepted"].append({"peer": peer, "valid": valid})
                    emit(path, result)
                if len(result["accepted"]) >= 2:
                    break
    else:
        result["probes"] = []
        for bound in [False, True]:
            tick = time.monotonic()
            record = {"device_bound": bound, "success": False}
            try:
                with connection(config, (config["peer"], config["port"]), bound) as sock:
                    token = config["token"].encode()
                    sock.sendall(token)
                    record["success"] = sock.recv(256) == hashlib.sha256(token).hexdigest().encode()
            except OSError as error:
                record.update({"error_type": type(error).__name__, "errno": error.errno})
            record["elapsed_seconds"] = time.monotonic() - tick
            result["probes"].append(record)
        result["ssh_configs"] = []
        for alias in config["ssh_aliases"]:
            value = run(["ssh", "-G", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", alias])
            selected = [line for line in value.get("stdout", "").splitlines()
                        if line.split(" ")[0] in {"hostname", "user", "port", "identityfile", "proxyjump", "proxycommand", "stricthostkeychecking", "userknownhostsfile"}]
            result["ssh_configs"].append({"alias": alias, "exit": value.get("exit"), "settings": selected,
                                          "error": value.get("stderr", value.get("error", ""))})
        peer = config["peer"]
        known = run(["ssh-keygen", "-F", peer])
        result["peer_known_host_present"] = known.get("exit") == 0
        if result["peer_known_host_present"]:
            command = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                       "-o", "ConnectTimeout=4", "-o", "ConnectionAttempts=1",
                       "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
                       config["peer_user"] + "@" + peer, "/usr/bin/python3", "-c",
                       "'import os,socket; print(socket.gethostname(), os.getuid())'"]
            result["strict_direct_ssh"] = run(command)
    result["elapsed_seconds"] = time.monotonic() - start
    emit(path, result)
    print(json.dumps({"node": config["node"], "mode": args.mode,
                      "result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "success": result.get("probes", result.get("accepted")),
                      "strict_direct_ssh": result.get("strict_direct_ssh")}), flush=True)


if __name__ == "__main__":
    main()
