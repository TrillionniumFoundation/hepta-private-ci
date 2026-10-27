"""Trusted host Docker orchestration; never mounted into build/business containers."""

import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import uuid

from .contract import (
    IMAGE_ROOTS,
    PLATFORM,
    SYNAPSE_ID,
    SYNAPSE_REF,
    validate_image_inspect,
)
from .files import describe, physical, read_json, write_json


def mount(source, destination, *, writable=False):
    source = physical(source)
    if not source.exists() or any(
        char in str(source) + str(destination) for char in ",\n\r"
    ):
        raise ValueError(
            "Docker bind mount must reference an existing canonical local path"
        )
    return [
        "--mount",
        f"type=bind,src={source},dst={destination}" + ("" if writable else ",readonly"),
    ]


def process_command(contract, entry, arguments):
    return [
        contract["tools"]["env"]["path"],
        "-i",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "TZ=UTC",
        "PYTHONDONTWRITEBYTECODE=1",
        contract["tools"]["python3"]["path"],
        "-I",
        str(entry),
        *arguments,
    ]


class DockerControl:
    def __init__(self, commands, output, contract, socket):
        self.commands, self.output, self.contract = commands, output, contract
        self.socket = Path(socket).resolve(strict=True)
        if not stat.S_ISSOCK(self.socket.stat().st_mode):
            raise ValueError("Docker controller requires a local Unix socket")
        if commands.environment.get("DOCKER_HOST") != "unix://" + str(self.socket):
            raise ValueError(
                "Docker control environment does not bind the inspected local socket"
            )
        self.prefix = "hepta-linux-" + uuid.uuid4().hex
        self.label = "hepta.linux.qualification=" + self.prefix
        self.containers, self.networks, self.volumes = [], [], []
        write_json(
            self.output / "RESOURCE_OWNER.json",
            {
                "schema": "hepta.synapse.linux.resource-owner.v1",
                "prefix": self.prefix,
                "label": self.label,
                "docker_socket": str(self.socket),
                "docker_tool": commands.tools["docker"],
                "scope": "only locally generated resources with this exact random label",
                "host_docker_control_is_privileged": True,
            },
        )

    def json(self, args, label):
        _, path = self.commands.run("docker", args, label=label)
        return read_json(path)

    def preflight(self):
        if (platform.system(), platform.machine()) != (
            "Linux",
            "aarch64",
        ) or os.getuid() == 0:
            raise ValueError(
                "Qualification controller must run on native ARM64 Linux as a non-root user"
            )
        info = self.json(["info", "--format", "{{json .}}"], "docker-info")
        if info["OSType"] != "linux" or info["Architecture"] not in {
            "aarch64",
            "arm64",
        }:
            raise ValueError("Actual local Docker daemon is not native Linux ARM64")
        binfmt = Path("/proc/sys/fs/binfmt_misc")
        entries = (
            {
                path.name: path.read_text()
                for path in binfmt.iterdir()
                if path.is_file() and path.name != "register"
            }
            if binfmt.exists()
            else {}
        )
        if any("qemu" in (name + value).lower() for name, value in entries.items()):
            raise ValueError(
                "Foreign-architecture emulation is not part of this qualification"
            )
        builder = self.json(
            ["image", "inspect", self.contract["image"]["reference"]], "builder-image"
        )
        validate_image_inspect(builder, self.contract["image"])
        synapse = self.json(["image", "inspect", SYNAPSE_REF], "synapse-image")
        validate_image_inspect(
            synapse,
            {
                "reference": SYNAPSE_REF,
                "config_id": SYNAPSE_ID,
                "os": "linux",
                "architecture": "arm64",
            },
        )
        labels = synapse[0]["Config"].get("Labels", {})
        if (
            labels.get("org.opencontainers.image.version")
            != self.contract["synapse"]["version"]
            or labels.get("org.opencontainers.image.revision")
            != self.contract["synapse"]["revision"]
        ):
            raise ValueError("Actual Synapse OCI labels differ from the original pin")
        receipt = {
            "schema": "hepta.synapse.linux.controller.v1",
            "scope": "native-linux-arm64",
            "kernel": platform.uname()._asdict(),
            "uid": os.getuid(),
            "gid": os.getgid(),
            "free_bytes": shutil.disk_usage(self.output).free,
            "memory": Path("/proc/meminfo").read_text(),
            "binfmt_entries": entries,
            "docker_info": info,
            "docker_version": self.json(
                ["version", "--format", "{{json .}}"], "docker-version"
            ),
            "builder_inspect": builder,
            "synapse_inspect": synapse,
            "authority_boundary": "Trusted controller and transport sidecar have broad Docker authority. Build and business containers receive no socket or Docker client mount.",
            "mac_or_windows_qualification": False,
            "promotion_allowed": False,
        }
        write_json(self.output / "CONTROLLER_PREFLIGHT.json", receipt)
        return receipt

    def create(self, role, options, image, arguments):
        name = self.prefix + "-" + role
        if not re.fullmatch(r"[a-z0-9-]+", role):
            raise ValueError("Invalid fixture container role")
        self.commands.run(
            "docker",
            [
                "create",
                "--pull=never",
                "--platform",
                PLATFORM,
                "--name",
                name,
                "--label",
                self.label,
                *options,
                image,
                *arguments,
            ],
            label="create-" + role,
        )
        self.containers.append(name)
        return name

    def isolated(self, role, mounts, arguments):
        return self.create(
            role,
            [
                "--network",
                "none",
                "--read-only",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=1024",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,mode=1777",
                *mounts,
                "--entrypoint",
                self.contract["tools"]["env"]["path"],
            ],
            self.contract["image"]["reference"],
            arguments[1:],
        )

    def start(self, name, *, attach=False):
        return self.commands.run(
            "docker",
            ["start", *(["--attach"] if attach else []), name],
            label="start-" + name.removeprefix(self.prefix + "-"),
        )

    def inspect(self, name, label):
        values = self.json(["container", "inspect", name], label)
        if (
            len(values) != 1
            or values[0]["Config"].get("Labels", {}).get("hepta.linux.qualification")
            != self.prefix
        ):
            raise ValueError("Container is not owned by this qualification")
        return values[0]

    def check_isolated(self, name, *, expected_running, expected_mounts):
        value = self.inspect(name, "inspect-isolated")
        host = value["HostConfig"]
        if (
            value["Image"] != self.contract["image"]["config_id"]
            or value["State"]["Running"] != expected_running
        ):
            raise ValueError("Actual business/build image or running state differs")
        if (
            host["NetworkMode"] != "none"
            or not host["ReadonlyRootfs"]
            or host["Privileged"]
            or host.get("PidMode")
            or host.get("Devices")
        ):
            raise ValueError(
                "Build/business container inherited unreviewed host authority"
            )
        if host["CapDrop"] != ["ALL"] or not any(
            option.startswith("no-new-privileges") for option in host["SecurityOpt"]
        ):
            raise ValueError("Container capabilities/no-new-privileges differ")
        if (
            value["Config"]["User"] != f"{os.getuid()}:{os.getgid()}"
            or host.get("GroupAdd")
            or host.get("PortBindings")
        ):
            raise ValueError("Business/build user, groups or published ports differ")
        actual = {
            (item["Source"], item["Destination"], bool(item["RW"]))
            for item in value["Mounts"]
            if item["Type"] == "bind"
        }
        if actual != set(expected_mounts) or any(
            item["Type"] not in {"bind", "tmpfs"} for item in value["Mounts"]
        ):
            raise ValueError(
                "Actual mount set differs; Docker socket must never reach business/build code"
            )
        for source, destination, writable in actual:
            if (
                destination.startswith(IMAGE_ROOTS)
                or source == str(self.socket)
                or destination == "/hepta-control"
            ):
                raise ValueError(
                    "A mount substituted image/toolchain inputs or exposed Docker"
                )
        return value

    def cleanup(self):
        """Run after observed command termination; retain logs even on failed qualification."""
        failures = []
        # A signal can arrive between Docker create and its successful return.
        # Recover actual owned names from the already persisted random label.
        for attribute, arguments in (
            ("containers", ["ps", "-a", "--format", "{{.Names}}"]),
            ("networks", ["network", "ls", "--format", "{{.Name}}"]),
            ("volumes", ["volume", "ls", "--format", "{{.Name}}"]),
        ):
            try:
                _, listing = self.commands.run(
                    "docker",
                    [*arguments, "--filter", "label=" + self.label],
                    label="recover-owned-" + attribute,
                    timeout_seconds=30,
                )
                names = listing.read_text().splitlines()
                if any(
                    not re.fullmatch(re.escape(self.prefix) + r"-[a-z0-9-]+", name)
                    for name in names
                ):
                    raise ValueError(
                        "Owned-label discovery returned an unexpected resource name"
                    )
                setattr(
                    self,
                    attribute,
                    list(dict.fromkeys([*getattr(self, attribute), *names])),
                )
            except (OSError, ValueError, RuntimeError) as error:
                failures.append({"resource": attribute, "error": str(error)})
        for name in reversed(self.containers):
            try:
                _, inspected = self.commands.run(
                    "docker",
                    ["container", "inspect", name],
                    label="cleanup-owned-container",
                    timeout_seconds=30,
                )
                values = read_json(inspected)
                if (
                    len(values) != 1
                    or values[0]["Config"]
                    .get("Labels", {})
                    .get("hepta.linux.qualification")
                    != self.prefix
                ):
                    raise ValueError(
                        "Cleanup cannot touch a container owned by another invocation"
                    )
                self.commands.run(
                    "docker",
                    ["logs", name],
                    label="container-final-log",
                    required=False,
                    timeout_seconds=30,
                )
                self.commands.run(
                    "docker",
                    ["stop", "--time", "30", name],
                    label="container-stop",
                    timeout_seconds=45,
                )
                self.commands.run(
                    "docker", ["rm", name], label="container-remove", timeout_seconds=30
                )
            except (OSError, ValueError, RuntimeError) as error:
                failures.append({"resource": name, "error": str(error)})
        for kind, names in (("network", self.networks), ("volume", self.volumes)):
            for name in reversed(names):
                try:
                    _, inspected = self.commands.run(
                        "docker",
                        [kind, "inspect", name],
                        label="cleanup-owned-" + kind,
                        timeout_seconds=30,
                    )
                    values = read_json(inspected)
                    if (
                        len(values) != 1
                        or values[0].get("Labels", {}).get("hepta.linux.qualification")
                        != self.prefix
                    ):
                        raise ValueError(
                            "Cleanup cannot touch a resource owned by another invocation"
                        )
                    self.commands.run(
                        "docker",
                        [kind, "rm", name],
                        label="remove-" + kind,
                        timeout_seconds=30,
                    )
                except (OSError, ValueError, RuntimeError) as error:
                    failures.append({"resource": name, "error": str(error)})
        for kind, command in (
            ("containers", ["ps", "-aq"]),
            ("networks", ["network", "ls", "-q"]),
            ("volumes", ["volume", "ls", "-q"]),
        ):
            try:
                _, observed = self.commands.run(
                    "docker",
                    [*command, "--filter", "label=" + self.label],
                    label="absent-" + kind,
                    timeout_seconds=30,
                )
                if observed.read_text().strip():
                    failures.append(
                        {"resource": kind, "error": "owned resource survived teardown"}
                    )
            except (OSError, ValueError, RuntimeError) as error:
                failures.append({"resource": kind, "error": str(error)})
        receipt = {
            "schema": "hepta.synapse.linux.teardown.v1",
            "all_owned_resources_absent": not failures,
            "failures": failures,
            "names": {
                "containers": self.containers,
                "networks": self.networks,
                "volumes": self.volumes,
            },
        }
        write_json(self.output / "TEARDOWN.json", receipt)
        return receipt
