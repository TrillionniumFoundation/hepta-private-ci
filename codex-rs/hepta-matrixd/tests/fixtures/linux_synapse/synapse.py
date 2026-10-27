"""The original pinned server and unchanged loopback proxy, controlled externally."""

import json
import os
from pathlib import Path
import secrets
import time

from .contract import PROXY, SYNAPSE_REF, SYNAPSE_VERSION
from .docker_control import mount
from .files import copy_file, describe, read_json, verify, write_bytes, write_json


CONFIGURE = """
import hashlib, json, pathlib, yaml
p = pathlib.Path('/data/homeserver.yaml')
c = yaml.safe_load(p.read_text())
assert c.get('registration_shared_secret')
c.update({'allow_public_rooms_over_federation': False, 'allow_public_rooms_without_auth': False,
          'enable_metrics': False, 'enable_registration': False,
          'enable_registration_without_verification': False, 'federation_domain_whitelist': {},
          'report_stats': False, 'suppress_key_server_warning': True, 'trusted_key_servers': []})
p.write_text(yaml.safe_dump(c, sort_keys=True))
print(json.dumps({'homeserver_config_sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                  'public_rooms_over_federation': c['allow_public_rooms_over_federation'],
                  'public_rooms_without_auth': c['allow_public_rooms_without_auth'],
                  'registration': c['enable_registration'], 'registration_without_verification': c['enable_registration_without_verification'],
                  'metrics': c['enable_metrics'], 'report_stats': c['report_stats'],
                  'federation_domain_whitelist': c['federation_domain_whitelist'], 'trusted_key_servers': c['trusted_key_servers']}))
"""

REGISTER = """
import os, pathlib, subprocess, sys, tempfile
password = sys.stdin.buffer.read()
fd, name = tempfile.mkstemp(prefix='hepta-password-')
try:
    with os.fdopen(fd, 'wb') as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(password)
    subprocess.run(['register_new_matrix_user', '--config', '/data/homeserver.yaml',
                    '--user', sys.argv[1], '--password-file', name, '--no-admin',
                    'http://127.0.0.1:8008'], check=True)
finally:
    pathlib.Path(name).unlink()
"""

READY = """
import time, urllib.request
deadline = time.monotonic() + 30
while True:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8008/_matrix/client/versions', timeout=2) as r:
            assert r.status == 200
            print(r.read().decode())
            break
    except Exception:
        if time.monotonic() >= deadline:
            raise
        time.sleep(.25)
"""


def start_synapse(control, credentials):
    volume, network = control.prefix + "-data", control.prefix + "-internal"
    control.commands.run(
        "docker",
        ["volume", "create", "--label", control.label, volume],
        label="synapse-volume",
    )
    control.volumes.append(volume)
    generate = control.create(
        "generate",
        [
            "--network",
            "none",
            "-e",
            "SYNAPSE_SERVER_NAME=localhost",
            "-e",
            "SYNAPSE_REPORT_STATS=no",
            "-v",
            volume + ":/data",
        ],
        SYNAPSE_REF,
        ["generate"],
    )
    control.start(generate, attach=True)
    if control.inspect(generate, "generated-state")["State"]["ExitCode"] != 0:
        raise ValueError("Pinned Synapse configuration generation failed")
    configure = control.create(
        "configure",
        ["--network", "none", "--entrypoint", "python3", "-v", volume + ":/data"],
        SYNAPSE_REF,
        ["-c", CONFIGURE],
    )
    control.start(configure, attach=True)
    if control.inspect(configure, "configured-state")["State"]["ExitCode"] != 0:
        raise ValueError("Pinned Synapse configuration hardening failed")
    _, config_log = control.commands.run(
        "docker", ["logs", configure], label="public-server-configuration"
    )
    config = read_json(config_log)
    expected = {
        "public_rooms_over_federation": False,
        "public_rooms_without_auth": False,
        "registration": False,
        "registration_without_verification": False,
        "metrics": False,
        "report_stats": False,
        "federation_domain_whitelist": {},
        "trusted_key_servers": [],
    }
    if {key: config.get(key) for key in expected} != expected:
        raise ValueError("Synapse public configuration constraints differ")
    control.commands.run(
        "docker",
        ["network", "create", "--internal", "--label", control.label, network],
        label="internal-network",
    )
    control.networks.append(network)
    server = control.create(
        "synapse",
        [
            "--network",
            network,
            "--security-opt=no-new-privileges",
            "-v",
            volume + ":/data",
        ],
        SYNAPSE_REF,
        [],
    )
    control.start(server)
    control.commands.run(
        "docker", ["exec", server, "python3", "-c", READY], label="actual-server-ready"
    )
    for name, capability in (
        ("hepta-agent-a", "agent-a-password"),
        ("hepta-agent-b", "agent-b-password"),
        ("hepta-human", "human-password"),
    ):
        password = secrets.token_hex(32)
        write_bytes(credentials / capability, password.encode())
        control.commands.run(
            "docker",
            ["exec", "-i", server, "python3", "-c", REGISTER, name],
            label="register-" + name,
            input_bytes=(password + "\n").encode(),
        )
    version = control.commands.text(
        "docker",
        [
            "exec",
            server,
            "python3",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('matrix-synapse'))",
        ],
        label="actual-synapse-version",
    )
    if version != SYNAPSE_VERSION:
        raise ValueError("Running Synapse package differs from its pinned version")
    inspected = control.inspect(server, "running-synapse")
    network_inspect = control.json(["network", "inspect", network], "network-inspect")
    if (
        not network_inspect[0]["Internal"]
        or inspected["HostConfig"].get("PortBindings")
        or any(inspected["NetworkSettings"].get("Ports", {}).values())
    ):
        raise ValueError(
            "Synapse must remain on an internal network with no published port"
        )
    return server, {
        "config": config,
        "inspect": inspected,
        "network_inspect": network_inspect,
        "version": version,
    }


def start_proxy(control, runtime, server, source, tool_bundle, control_binary, output):
    """Only this trusted sidecar receives the Docker socket; no shared PID/mount namespace."""
    directory = output / "proxy"
    directory.mkdir(mode=0o700)
    proxy_source = source / PROXY
    copy_file(proxy_source, directory / "synapse-loopback-proxy.py")
    docker_file = control_binary / "docker"
    verify(
        docker_file,
        {key: control.contract["control_docker"][key] for key in ("bytes", "sha256")},
    )
    runtime_identity = control.inspect(runtime, "runtime-before-proxy")
    command = [
        "-i",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "PYTHONDONTWRITEBYTECODE=1",
        "DOCKER_HOST=unix:///hepta-docker.sock",
        "DOCKER_CONFIG=/tmp/docker-config",
        control.contract["tools"]["python3"]["path"],
        "-I",
        "/proxy.py",
        "--docker",
        "/hepta-control/docker",
        "--container",
        server,
        "--ready",
        "/proxy-output/ready.json",
    ]
    proxy = control.create(
        "proxy",
        [
            "--network",
            "container:" + runtime_identity["Id"],
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--group-add",
            str(control.socket.stat().st_gid),
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,mode=1777",
            *mount(proxy_source, "/proxy.py"),
            *mount(tool_bundle, "/hepta-tools"),
            *mount(control_binary, "/hepta-control"),
            *mount(control.socket, "/hepta-docker.sock"),
            *mount(directory, "/proxy-output", writable=True),
            "--entrypoint",
            control.contract["tools"]["env"]["path"],
        ],
        control.contract["image"]["reference"],
        command,
    )
    control.start(proxy)
    deadline = time.monotonic() + 30
    while not (directory / "ready.json").exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Unchanged loopback proxy did not publish readiness")
        time.sleep(0.1)
    ready = read_json(directory / "ready.json")
    if (
        ready.get("schema_version") != 1
        or ready.get("transport") != "docker-exec-loopback-proxy-v1"
        or ready.get("host") != "127.0.0.1"
        or ready.get("target") != "127.0.0.1:8008"
        or ready.get("container") != server
        or not 1024 <= ready.get("port", 0) <= 65535
        or ready.get("pid", 0) <= 0
    ):
        raise ValueError(
            "Proxy ready evidence does not bind the original internal transport"
        )
    inspected = control.inspect(proxy, "proxy-inspect")
    if (
        not inspected["State"]["Running"]
        or inspected["HostConfig"]["NetworkMode"]
        != "container:" + runtime_identity["Id"]
        or inspected["HostConfig"].get("PidMode")
    ):
        raise ValueError("Proxy must share only the runtime network namespace")
    write_json(
        directory / "AUTHORITY_BOUNDARY.json",
        {
            "schema": "hepta.synapse.linux.proxy.v1",
            "trusted_privileged_fixture_infrastructure": True,
            "broad_docker_authority": True,
            "business_container_has_docker_socket": False,
            "pid_namespace_shared": False,
            "filesystem_namespace_shared": False,
            "network_namespace_shared": True,
            "source": describe(proxy_source),
            "ready": describe(directory / "ready.json"),
            "inspect": inspected,
        },
    )
    return proxy, ready
