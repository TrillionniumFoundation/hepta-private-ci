"""Linux descriptor-relative, explicitly scoped rootfs inventory candidate."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable

from .parsers import DiscoveryError, ordering_graph, parse_os_release, parse_packages, parse_unit


@dataclass(frozen=True)
class DiscoveryScope:
    """Host-verified enrollment reference, NOT a credential or self-issued grant.

    Host must provide an isolated frozen rootfs and keep root_fd alive until return.
    This structure only narrows an already-authorized read, never grants access.
    """
    root_device: int
    root_inode: int
    host_digest: str
    enrollment_receipt_digest: str
    expires_unix_ns: int
    unit_paths: tuple[str, ...] = ()
    os_release_path: str = "etc/os-release"


@dataclass(frozen=True)
class DiscoveryCandidate:
    """Canonical immutable candidate bytes; not ExternalSystemManifestV1 admission."""
    payload: bytes
    sha256: str


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_at(root_fd: int, root_device: int, path: str, limit: int) -> tuple[bytes, tuple[int, ...]]:
    """Walk each component without following symlinks; never open a path globally."""
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise DiscoveryError("invalid_relative_path")
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current)
            os.close(current)
            current = child
            if os.fstat(current).st_dev != root_device:
                raise DiscoveryError("mount_boundary")
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=current)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_dev != root_device or before.st_nlink != 1):
                raise DiscoveryError("unsupported_file")
            if before.st_size > limit:
                raise DiscoveryError("byte_limit")
            chunks = []
            remaining = limit + 1
            while remaining:
                part = os.read(fd, min(65_536, remaining))
                if not part:
                    break
                chunks.append(part)
                remaining -= len(part)
            data = b"".join(chunks)
            if len(data) > limit:
                raise DiscoveryError("byte_limit")
            after = os.fstat(fd)
            linked = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
            if _signature(before) != _signature(after) or _signature(after) != _signature(linked) or len(data) != after.st_size:
                raise DiscoveryError("inventory_drift")
            return data, _signature(after)
        finally:
            os.close(fd)
    finally:
        os.close(current)


def discover(root_fd: int, scope: DiscoveryScope, *, clock: Callable[[], int] = time.time_ns) -> DiscoveryCandidate:
    """Read only os-release, dpkg status and <=64 explicitly named service files.

    No network, subprocess, recursive scan, package mutation or service invocation.
    Errors return no partial manifest. Authenticating enrollment, revocation and
    rootfs isolation remains the host's responsibility, not a digest comparison.
    """
    if (type(root_fd) is not int or root_fd < 0
            or type(scope.root_device) is not int or type(scope.root_inode) is not int
            or type(scope.expires_unix_ns) is not int
            or not isinstance(scope.os_release_path, str)
            or not isinstance(scope.unit_paths, tuple)
            or any(not isinstance(path, str) for path in scope.unit_paths)):
        raise DiscoveryError("invalid_scope_shape")
    for digest in (scope.host_digest, scope.enrollment_receipt_digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest == "0" * 64:
            raise DiscoveryError("invalid_scope_digest")
    if clock() >= scope.expires_unix_ns:
        raise DiscoveryError("expired_scope")
    if len(scope.unit_paths) > 64 or len(set(scope.unit_paths)) != len(scope.unit_paths):
        raise DiscoveryError("duplicate_or_excess_unit")
    if scope.os_release_path not in {"etc/os-release", "usr/lib/os-release"}:
        raise DiscoveryError("path_outside_scope")
    paths = [(scope.os_release_path, 16_384), ("var/lib/dpkg/status", 2_097_152)]
    names = set()
    for path in sorted(scope.unit_paths):
        if not re.fullmatch(r"(?:etc|usr/lib)/systemd/system/[A-Za-z0-9_:@.-]{1,200}\.service", path):
            raise DiscoveryError("path_outside_scope")
        name = path.rsplit("/", 1)[-1]
        if name in names:
            raise DiscoveryError("ambiguous_unit_override")
        names.add(name)
        paths.append((path, 65_536))
    fd = None
    try:
        fd = os.dup(root_fd)
        root = os.fstat(fd)
        if not stat.S_ISDIR(root.st_mode) or (root.st_dev, root.st_ino) != (scope.root_device, scope.root_inode):
            raise DiscoveryError("root_identity_mismatch")
        contents = {}
        evidence = []
        total = 0
        for path, limit in paths:
            if clock() >= scope.expires_unix_ns:
                raise DiscoveryError("expired_scope")
            data, identity = _read_at(fd, root.st_dev, path, limit)
            total += len(data)
            if total > 4_194_304:
                raise DiscoveryError("total_byte_limit")
            contents[path] = data
            evidence.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "identity": identity})
        os_id, version = parse_os_release(contents[scope.os_release_path])
        packages, records = parse_packages(contents["var/lib/dpkg/status"])
        units = tuple(sorted(parse_unit(path.rsplit("/", 1)[-1], contents[path]) for path in scope.unit_paths))
        order, blocked, missing = ordering_graph(units)
        # A second descriptor-relative pass rejects observable replacement/drift.
        for source in evidence:
            data, identity = _read_at(fd, root.st_dev, source["path"], source["bytes"])
            if identity != source["identity"] or hashlib.sha256(data).hexdigest() != source["sha256"]:
                raise DiscoveryError("inventory_drift")
        if clock() >= scope.expires_unix_ns:
            raise DiscoveryError("expired_scope")
        payload = {
            "schema": "hepta.scoped-discovery-candidate.v1",
            "scope": {**asdict(scope), "unit_paths": sorted(scope.unit_paths)},
            "os": {"id": os_id, "version_id": version}, "sources": evidence,
            "installed_packages": [asdict(package) for package in packages], "package_records": records,
            "units": [asdict(unit) for unit in units], "ordering": order,
            "ordering_blocked": blocked, "unresolved_dependencies": missing,
            "coverage": "selected_metadata_only", "drop_ins_resolved": False,
            "host_snapshot_required": True, "runtime_authority": False, "activation": False,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        return DiscoveryCandidate(encoded, hashlib.sha256(encoded).hexdigest())
    except OSError:
        raise DiscoveryError("filesystem_rejected") from None
    finally:
        if fd is not None:
            os.close(fd)
