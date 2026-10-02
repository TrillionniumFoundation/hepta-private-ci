"""Closed public measurement use of the original fixed physical encoder.

This purpose observes its own producer and the entire encoder/backend services.
It cannot use a Fleet grant or grant model installation, promotion or answers.
"""

import grp
import os
from pathlib import Path
import pwd
import re
import socket
import struct
import subprocess
import time

from fixed_encoder_sources import protected_path, source_bytes, verify_large_source

PURPOSE = "PublicDevelopmentMeasurementOnlyV1"
MAX_RESPONSE_BYTES = 64 * 1024
SERVICE_FIELDS = {
    "unit_name",
    "unit_source",
    "exec_start",
    "user",
    "group",
    "uid",
    "gid",
    "main_pid",
    "start_ticks",
    "cgroup",
    "cgroup_device",
    "cgroup_inode",
    "cpu_millis_per_second",
    "memory_max_bytes",
}


def deadline_seconds(deadline_ns):
    remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
    if remaining <= 0:
        raise ValueError("closed measurement deadline")
    return min(2.0, remaining)


def kernel_identity(pid):
    root = Path("/proc") / str(pid)
    raw = (root / "stat").read_text()
    start_ticks = int(raw[raw.rfind(")") + 2 :].split()[19])
    fields = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines() if ":" in line)
    cgroups = (root / "cgroup").read_text().splitlines()
    if len(cgroups) != 1 or not cgroups[0].startswith("0::/"):
        raise ValueError("closed measurement requires unified cgroup")
    gids = [int(value) for value in fields["Gid"].split()]
    groups = [int(value) for value in fields["Groups"].split()]
    if (
        fields["NoNewPrivs"].split() != ["1"]
        or any(value != gids[0] for value in groups)
        or any(int(fields[key], 16) for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
    ):
        raise ValueError("closed measurement process boundary")
    return (
        start_ticks,
        [int(value) for value in fields["Uid"].split()],
        gids,
        cgroups[0][3:],
    )


def validate_service(service, allow_root=False, allow_credential_drop=False):
    late = allow_credential_drop and service.get("process_binding") == "RegisteredServiceMainPidV2"
    dropping = late or allow_credential_drop and service.get("process_binding") == "CredentialDroppingMainPidV1"
    required = SERVICE_FIELDS | {"process_binding"} if dropping else SERVICE_FIELDS
    if late:
        required -= {"main_pid", "start_ticks", "cgroup_device", "cgroup_inode"}
    if set(service) != required:
        raise ValueError("closed service fields")
    if (
        not re.fullmatch(r"[A-Za-z0-9_.@-]{1,128}\.service", service["unit_name"])
        or not isinstance(service["exec_start"], str)
        or not 0 < len(service["exec_start"]) <= 8192
        or type(service["uid"]) is not int
        or service["uid"] < (0 if allow_root else 1)
        or type(service["gid"]) is not int
        or service["gid"] < 0
        or not late
        and (type(service["main_pid"]) is not int or service["main_pid"] <= 1)
        or not late
        and (type(service["start_ticks"]) is not int or service["start_ticks"] <= 0)
        or type(service["cpu_millis_per_second"]) is not int
        or not 1 <= service["cpu_millis_per_second"] <= 4000
        or type(service["memory_max_bytes"]) is not int
        or not 1 <= service["memory_max_bytes"] <= 1024 * 1024 * 1024
    ):
        raise ValueError("closed service identity/resource ceiling")
    cgroup = service["cgroup"]
    if (
        not isinstance(cgroup, str)
        or not cgroup.startswith("/system.slice/")
        or len(cgroup) > 256
        or ".." in Path(cgroup).parts
        or not late
        and (service["cgroup_device"] < 0 or service["cgroup_inode"] <= 0)
    ):
        raise ValueError("closed nondelegated service cgroup")
    user, group = service["user"], service["group"]
    user_id = int(user or "0") if not user or user.isdecimal() else pwd.getpwnam(user).pw_uid
    group_id = int(group or "0") if not group or group.isdecimal() else grp.getgrnam(group).gr_gid
    expected = (0, 0) if dropping else (service["uid"], service["gid"])
    if (user_id, group_id) != expected:
        raise ValueError("service account names differ from actual registered UID/GID")
    if dropping:
        flags = (
            f"--reuid={service['uid']}",
            f"--regid={service['gid']}",
            "--clear-groups",
            "--no-new-privs",
            "--bounding-set=-all",
            "--inh-caps=-all",
            "--ambient-caps=-all",
        )
        if not service["exec_start"].startswith("{ path=/usr/bin/setpriv ; argv[]=/usr/bin/setpriv ") or not all(
            flag in service["exec_start"].split() for flag in flags
        ):
            raise ValueError("fixed Root producer credential-dropping declaration")


def service_properties(systemctl, service, deadline_ns):
    try:
        result = subprocess.run(
            [
                systemctl,
                "show",
                "--no-pager",
                "--property=Id,FragmentPath,ExecStart,User,Group,MainPID,ControlGroup,Delegate",
                service["unit_name"],
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
            timeout=deadline_seconds(deadline_ns),
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("closed service observation exceeded the original deadline") from error
    if result.returncode != 0 or not 0 < len(result.stdout) <= 64 * 1024:
        raise ValueError("closed service manager observation")
    properties = {}
    for line in result.stdout.decode("utf-8").splitlines():
        name, value = line.split("=", 1)
        if name in properties:
            raise ValueError("duplicate service property")
        properties[name] = value
    expected = {
        "Id": service["unit_name"],
        "FragmentPath": service["unit_source"]["path"],
        "ExecStart": service["exec_start"],
        "User": service["user"],
        "Group": service["group"],
        "MainPID": str(service["main_pid"]),
        "ControlGroup": service["cgroup"],
        "Delegate": "no",
    }
    if properties != expected:
        raise ValueError("service differs from the exact Root registration")


def cgroup_snapshot(service):
    root = protected_path(Path("/sys/fs/cgroup") / service["cgroup"].lstrip("/"), directory=True)
    info = root.stat()
    if (info.st_dev, info.st_ino) != (service["cgroup_device"], service["cgroup_inode"]):
        raise ValueError("original service cgroup was replaced")
    quota, period = (root / "cpu.max").read_text().split()
    if (
        quota == "max"
        or int(period) <= 0
        or int(quota) * 1000 != service["cpu_millis_per_second"] * int(period)
        or int((root / "memory.max").read_text()) != service["memory_max_bytes"]
    ):
        raise ValueError("service lost its finite original CPU/memory bounds")
    cpu = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
    numbers = [
        int(cpu["usage_usec"]),
        int((root / "memory.current").read_text()),
        int((root / "memory.peak").read_text()),
    ]
    if any(value < 0 for value in numbers) or numbers[1] > numbers[2]:
        raise ValueError("invalid actual service accounting")
    return {
        "unit": service["unit_name"],
        "pid": service["main_pid"],
        "start_ticks": service["start_ticks"],
        "uid": service["uid"],
        "cgroup": service["cgroup"],
        "cpu_usage_usec": numbers[0],
        "memory_current_bytes": numbers[1],
        "memory_peak_bytes": numbers[2],
    }


def observe_service(systemctl, service, deadline_ns):
    identity = kernel_identity(service["main_pid"])
    expected = (
        service["start_ticks"],
        [service["uid"]] * 4,
        [service["gid"]] * 4,
        service["cgroup"],
    )
    if identity != expected:
        raise ValueError("actual service kernel lifetime/UID differs")
    source_bytes(service["unit_source"], 64 * 1024)
    service_properties(systemctl, service, deadline_ns)
    snapshot = cgroup_snapshot(service)
    if kernel_identity(service["main_pid"]) != expected:
        raise ValueError("service changed during current observation")
    deadline_seconds(deadline_ns)
    return snapshot


def resolve_registered_producer(declaration, peer_pid):
    if declaration.get("process_binding") != "RegisteredServiceMainPidV2":
        return declaration
    # The actual socket peer must be the current main process of this exact
    # protected unit. Its lifetime and cgroup identity come from the kernel;
    # service_properties below compares MainPID and the full Root declaration.
    start, uids, gids, cgroup = kernel_identity(peer_pid)
    if (uids, gids, cgroup) != ([declaration["uid"]] * 4, [declaration["gid"]] * 4, declaration["cgroup"]):
        raise ValueError("registered producer kernel peer differs")
    meta = protected_path(Path("/sys/fs/cgroup") / cgroup.lstrip("/"), directory=True).stat()
    return {
        **declaration,
        "process_binding": "CredentialDroppingMainPidV1",
        "main_pid": peer_pid,
        "start_ticks": start,
        "cgroup_device": meta.st_dev,
        "cgroup_inode": meta.st_ino,
    }


def fingerprint(path):
    info = protected_path(path).stat()
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def encoder_self_service(declaration):
    derived = {"main_pid", "start_ticks", "cgroup_device", "cgroup_inode"}
    if (
        set(declaration) != SERVICE_FIELDS - derived | {"process_binding"}
        or declaration["process_binding"] != "EncoderSelfV1"
    ):
        raise ValueError("explicit Root encoder self service")
    pid = os.getpid()
    identity = kernel_identity(pid)
    if identity[1:] != ([0] * 4, [0] * 4, declaration["cgroup"]):
        raise ValueError("actual Root encoder service context")
    cgroup = protected_path(Path("/sys/fs/cgroup") / identity[3].lstrip("/"), directory=True).stat()
    return {
        **{key: value for key, value in declaration.items() if key != "process_binding"},
        "main_pid": pid,
        "start_ticks": identity[0],
        "cgroup_device": cgroup.st_dev,
        "cgroup_inode": cgroup.st_ino,
    }


class DevelopmentMeasurements:
    def __init__(self, config, pairs):
        declaration = config["public_development"]
        if set(declaration) != {
            "systemctl_source",
            "encoder_service",
            "backend_service",
            "batches",
        }:
            raise ValueError("closed public declaration fields")
        self.config, self.pairs = config, pairs
        # The encoder's own kernel/service context is obtained after exec;
        # Root cannot preregister a future PID or cgroup inode. Other peers
        # remain exact Root-registered MainPID observations.
        self.encoder = encoder_self_service(declaration["encoder_service"])
        self.backend = declaration["backend_service"]
        validate_service(self.encoder, allow_root=True)
        validate_service(self.backend)
        if (
            self.encoder["uid"] != 0
            or self.encoder["main_pid"] != os.getpid()
            or self.backend["main_pid"] != config["backend_pid"]
            or self.backend["uid"] != config["backend_uid"]
            or self.backend["cgroup"] != config["backend_cgroup"]
            or str(self.backend["start_ticks"]) != config["backend_start_time"]
            or self.backend["unit_source"] != config["backend_unit_source"]
        ):
            raise ValueError("public use must observe these actual physical services")
        sources = [
            declaration["systemctl_source"],
            self.encoder["unit_source"],
            self.backend["unit_source"],
        ]
        batches = declaration["batches"]
        if not isinstance(batches, list) or not 0 <= len(batches) <= 16:
            raise ValueError("closed public batch budget")
        self.batches, self.remaining = {}, {}
        for batch in batches:
            if set(batch) != {
                "batch_id",
                "purpose",
                "producer",
                "producer_sources",
                "pairs",
                "expires_at_ms",
                "max_requests",
            }:
                raise ValueError("closed batch fields")
            if (
                batch["purpose"] != PURPOSE
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", batch["batch_id"])
                or batch["batch_id"] in self.batches
                or type(batch["max_requests"]) is not int
                or not 1 <= batch["max_requests"] <= config["max_requests"]
                or not time.time_ns() // 1_000_000 < batch["expires_at_ms"] <= config["expires_at_ms"]
            ):
                raise ValueError("closed public batch purpose/window/budget")
            validate_service(batch["producer"], allow_credential_drop=True)
            if not isinstance(batch["producer_sources"], list) or not 1 <= len(batch["producer_sources"]) <= 32:
                raise ValueError("closed producer physical source closure")
            if batch["producer"].get("process_binding") in (
                "CredentialDroppingMainPidV1",
                "RegisteredServiceMainPidV2",
            ) and not any(source["path"] == "/usr/bin/setpriv" for source in batch["producer_sources"]):
                raise ValueError("fixed credential drop outside producer physical closure")
            if not isinstance(batch["pairs"], list) or not 1 <= len(batch["pairs"]) <= 1024:
                raise ValueError("closed public pair budget")
            registered = {}
            for pair in batch["pairs"]:
                if (
                    set(pair) != {"pair_id", "source_row_sha256"}
                    or pair["pair_id"] in registered
                    or pair["pair_id"] not in pairs
                    or pairs[pair["pair_id"]]["source_row_sha256"] != pair["source_row_sha256"]
                ):
                    raise ValueError("public declaration differs from actual frozen row")
                registered[pair["pair_id"]] = pair["source_row_sha256"]
            self.batches[batch["batch_id"]] = (batch, registered)
            self.remaining[batch["batch_id"]] = batch["max_requests"]
            sources.extend([batch["producer"]["unit_source"], *batch["producer_sources"]])
        self.systemctl = declaration["systemctl_source"]["path"]
        if self.systemctl != "/usr/bin/systemctl":
            raise ValueError("fixed original service manager executable")
        # The main encoder already verified this complete immutable physical
        # closure once. Retain identity, never rehash 274 MB for every row.
        physical = [
            *config["model_sources"],
            *config["program_sources"],
            *config["runtime_sources"],
            *config["numpy_sources"],
            config["preprocessor_source"],
            config["pairs_source"],
        ]
        self.current_sources = {}
        for source in sources:
            before = fingerprint(source["path"])
            verify_large_source(source, 512 * 1024 * 1024)
            if fingerprint(source["path"]) != before:
                raise ValueError("source changed during closed registration")
        for source in [*sources, *physical]:
            seen = fingerprint(source["path"])
            if seen[6] != source["size"]:
                raise ValueError("physical closure identity changed")
            if source["path"] in self.current_sources and self.current_sources[source["path"]] != seen:
                raise ValueError("inconsistent closed source identity")
            self.current_sources[source["path"]] = seen

    def revalidate_sources(self):
        for path, identity in self.current_sources.items():
            if fingerprint(path) != identity:
                raise ValueError("protected public physical closure changed")

    def measure(self, connection, request, preprocessor, numpy, pin, encode):
        started_ns = time.monotonic_ns()
        deadline_ns = started_ns + self.config["timeout_ms"] * 1_000_000
        if set(request) != {"purpose", "batch_id", "pair_id", "source_row_sha256"} or request["purpose"] != PURPOSE:
            raise ValueError("closed public request fields/purpose")
        batch, pairs = self.batches[request["batch_id"]]
        if (
            pairs.get(request["pair_id"]) != request["source_row_sha256"]
            or self.remaining[request["batch_id"]] <= 0
            or time.time_ns() // 1_000_000 >= min(batch["expires_at_ms"], self.config["expires_at_ms"])
        ):
            raise ValueError("closed public row/window/request budget")
        self.remaining[request["batch_id"]] -= 1
        pid, uid, gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        producer = resolve_registered_producer(batch["producer"], pid)
        if (pid, uid, gid) != (producer["main_pid"], producer["uid"], producer["gid"]):
            raise ValueError("closed public peer must be its actual registered MainPID")
        self.revalidate_sources()
        producer_before = observe_service(self.systemctl, producer, deadline_ns)
        services_before = [
            observe_service(self.systemctl, service, deadline_ns) for service in (self.encoder, self.backend)
        ]
        timeout_ms = max(1, int((deadline_ns - time.monotonic_ns()) / 1_000_000))
        result = encode(
            {**self.config, "timeout_ms": timeout_ms},
            preprocessor,
            numpy,
            self.pairs[request["pair_id"]],
            pin,
        )
        services_after = [
            observe_service(self.systemctl, service, deadline_ns) for service in (self.encoder, self.backend)
        ]
        producer_after = observe_service(self.systemctl, producer, deadline_ns)
        self.revalidate_sources()
        if time.time_ns() // 1_000_000 >= min(batch["expires_at_ms"], self.config["expires_at_ms"]):
            raise ValueError("closed public batch expired during measurement")
        for before, after in zip([producer_before, *services_before], [producer_after, *services_after], strict=True):
            if (
                before.keys() != after.keys()
                or any(before[key] != after[key] for key in ("unit", "pid", "start_ticks", "uid", "cgroup"))
                or before["cpu_usage_usec"] > after["cpu_usage_usec"]
                or before["memory_peak_bytes"] > after["memory_peak_bytes"]
            ):
                raise ValueError("service lifetime/accounting changed during physical measurement")
        manifests = [source for source in self.config["model_sources"] if "/manifests/" in source["path"]]
        if len(manifests) != 1:
            raise ValueError("fixed physical encoder manifest identity")
        result.update(
            {
                "schema": "hepta.fixed-nomic-public-development-pair.v1",
                "purpose": PURPOSE,
                "batch_id": request["batch_id"],
                "encoder_manifest_sha256": manifests[0]["sha256"],
                "measurement_elapsed_micros": (time.monotonic_ns() - started_ns) // 1000,
                "cost_context": {
                    "accounting": "entire-encoder-and-backend-service-conservative",
                    "producer_before": producer_before,
                    "producer_after": producer_after,
                    "services_before": services_before,
                    "services_after": services_after,
                },
            }
        )
        deadline_seconds(deadline_ns)
        return result
