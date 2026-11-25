#!/usr/bin/env python3
"""Bounded read-only route and per-socket diagnostics for two registered hosts."""
import argparse
import hashlib
import json
import os
import pathlib
import socket
import subprocess
import time


def command(argv, limit=12000):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        return {"command": argv, "exit": result.returncode,
                "stdout": result.stdout[:limit], "stderr": result.stderr[:1000],
                "truncated": len(result.stdout) > limit}
    except Exception as error:
        return {"command": argv, "error_type": type(error).__name__, "error": str(error)}


def text_file(path, limit=2000):
    try:
        return pathlib.Path(path).read_text()[:limit]
    except OSError as error:
        return type(error).__name__


def connect_probe(config, bind_device):
    start = time.monotonic()
    record = {"path_label": config["label"], "device_bound": bind_device,
              "target_port": 22, "success": False}
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(1.5)
    try:
        if bind_device:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                                  (config["interface"] + "\0").encode())
        record["bind_device_set"] = bind_device
        connection.bind((config["source"], 0))
        connection.connect((config["peer"], 22))
        banner = connection.recv(256)
        record.update({"success": True, "source_socket": connection.getsockname(),
                       "destination_socket": connection.getpeername(),
                       "ssh_banner": banner.decode(errors="replace").strip()})
    except OSError as error:
        record.update({"error_type": type(error).__name__, "errno": error.errno,
                       "error": str(error)})
    finally:
        connection.close()
    record["elapsed_seconds"] = time.monotonic() - start
    return record


def self_listener(config):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.settimeout(1.0)
    try:
        listener.bind((config["source"], 0))
        listener.listen(1)
        address = listener.getsockname()
        with socket.create_connection(address, timeout=1) as client:
            accepted, peer = listener.accept()
            with accepted:
                client.sendall(b"pft2-local-listener-check")
                valid = accepted.recv(64) == b"pft2-local-listener-check"
        return {"path_label": config["label"], "success": valid, "bound_socket": address}
    except OSError as error:
        return {"path_label": config["label"], "success": False,
                "error_type": type(error).__name__, "errno": error.errno, "error": str(error)}
    finally:
        listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads(pathlib.Path(args.config).read_text())
    result = {"configured_host": config["node"], "pid": os.getpid(),
              "uid": os.getuid(), "source_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
              "rules": command(["ip", "-j", "rule", "show"]), "paths": [], "owner_processes": []}
    for path in config["paths"]:
        path_result = {"label": path["label"], "route": command(["ip", "-j", "route", "get", path["peer"], "from", path["source"]]),
                       "route_with_device": command(["ip", "-j", "route", "get", path["peer"], "from", path["source"], "oif", path["interface"]]),
                       "rp_filter": text_file("/proc/sys/net/ipv4/conf/" + path["interface"] + "/rp_filter"),
                       "self_listener": self_listener(path), "connection_probes": []}
        for bound in [False, True]:
            path_result["connection_probes"].append(connect_probe(path, bound))
        result["paths"].append(path_result)
    result["rp_filter_all"] = text_file("/proc/sys/net/ipv4/conf/all/rp_filter")
    result["capabilities"] = [line for line in text_file("/proc/self/status", 8000).splitlines() if line.startswith("Cap")]
    result["firewall_read"] = command(["nft", "list", "ruleset"], 6000)
    result["network_service_states"] = command(["systemctl", "is-active", "ufw", "firewalld", "nftables", "warp-svc", "tailscaled"], 1000)
    for pid in config.get("observed_network_pids", []):
        prefix = pathlib.Path("/proc") / str(pid)
        try:
            argv = (prefix / "cmdline").read_bytes().decode(errors="replace").split("\0")
            result["owner_processes"].append({"pid": pid, "comm": (prefix / "comm").read_text().strip(),
                                              "script_paths": [arg for arg in argv if arg.endswith(".py")],
                                              "cgroup": (prefix / "cgroup").read_text()[:1000]})
        except OSError as error:
            result["owner_processes"].append({"pid": pid, "error_type": type(error).__name__})
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    output.write_text(content)
    print(json.dumps({"configured_host": config["node"], "source_sha256": result["source_sha256"],
                      "result_sha256": hashlib.sha256(content.encode()).hexdigest(), "bytes": len(content),
                      "path_probes": [{"label": p["label"], "probes": p["connection_probes"]} for p in result["paths"]]}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
