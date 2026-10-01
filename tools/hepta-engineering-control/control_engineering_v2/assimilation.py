"""Consent-bound, non-propagating external-system assimilation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from collections.abc import Iterable, Mapping

from .control_plane import (
    EngineeringError,
    bounded_tuple,
    checked_id,
    checked_sha256,
    semantic_digest,
)

READ_ONLY_OPERATIONS = frozenset({"query_version", "query_health", "read_status"})
_MAX_CONSENT_OPERATIONS = 16
_MAX_CONSENT_ROOTS = 64
_MAX_UNIX_NS = 2**63 - 1
_MAX_OPERATION_DEADLINE_MILLIS = 5_000
_MAX_OPERATION_OUTPUT_BYTES = 65_536
DENIED_OPERATIONS = frozenset(
    {
        "install_package",
        "remove_package",
        "write_configuration",
        "start_service",
        "stop_service",
        "enable_service",
        "register_peer",
        "copy_credential",
        "escalate_privilege",
        "activate_production",
    }
)


@dataclass(frozen=True)
class OwnerConsentReceipt:
    owner_principal: str
    target_identity_digest: str
    allowed_operations: tuple[str, ...]
    allowed_roots: tuple[str, ...]
    observed_unix_ns: int
    expires_unix_ns: int
    receipt_digest: str


@dataclass(frozen=True)
class ExternalManifestCandidate:
    target_identity_digest: str
    os_id: str
    os_version: str
    package_inventory_digest: str
    service_graph_digest: str
    mutable_state_digest: str
    provenance_digest: str
    omissions: tuple[str, ...]
    raw_secrets_copied: bool = False
    authority_granted: bool = False


@dataclass(frozen=True)
class TypedOperation:
    operation_id: str
    operation_class: str
    input_schema_digest: str
    output_schema_digest: str
    deadline_millis: int
    maximum_output_bytes: int
    terminal_observer: str
    idempotency: str
    external_effect: bool = False


@dataclass(frozen=True)
class SandboxParityReceipt:
    target_identity_digest: str
    manifest_digest: str
    operations_digest: str
    exact_fixture_digest: str
    fault_results_digest: str
    rollback_digest: str
    evaluator_principal: str
    generator_principal: str
    passed: bool
    network_unrestricted: bool = False
    production_credentials_exposed: bool = False
    authority_delta: bool = False


@dataclass(frozen=True)
class AssimilationProposal:
    proposal_id: str
    target_identity_digest: str
    consent_receipt_digest: str
    manifest_digest: str
    operations_digest: str
    sandbox_receipt_digest: str
    state: str
    activation: bool = False
    federation: bool = False
    propagation: bool = False
    authority_granted: bool = False


@dataclass(frozen=True)
class SandboxObservation:
    """A bounded read result from an enrolled disposable rootfs.

    This is deliberately an observation, never an effect receipt.  The adapter
    does not invoke systemd, dpkg, a shell, D-Bus or the network, and cannot
    turn an observation into consent or activation.
    """

    operation: str
    target_identity_digest: str
    payload: bytes
    payload_sha256: str
    authority_granted: bool = False
    activation: bool = False
    network_unrestricted: bool = False
    production_credentials_exposed: bool = False


class DebianSandboxAdapter:
    """Credential-free, read-only Debian fixture adapter (A1 dormant slice).

    ``root_label`` is an owner-issued scope label in ``OwnerConsentReceipt``;
    it is not inferred from a filesystem path.  The adapter rejects the host
    root, symlinked files, path traversal, expired consent and every operation
    outside the read-only consent set.  Service queries inspect unit metadata
    only; they never start/stop or otherwise call a host service manager.
    """

    _SERVICE = re.compile(r"[A-Za-z0-9_:@.-]{1,200}\.service\Z")
    _MAX_FILE_BYTES = 2 * 1024 * 1024

    def __init__(self, root: str | os.PathLike[str], consent: OwnerConsentReceipt, *, root_label: str, now_ns: int | None = None, clock=None):
        self._clock = time.time_ns if clock is None else clock
        if not callable(self._clock):
            raise EngineeringError("invalid_sandbox_clock")
        self._consent = validate_consent(consent, now_ns=now_ns if now_ns is not None else self._clock())
        if not isinstance(root_label, str) or root_label not in self._consent.allowed_roots:
            raise EngineeringError("sandbox_scope_not_enrolled")
        path = Path(root)
        try:
            resolved = path.resolve(strict=True)
            stat_result = resolved.stat()
        except (OSError, RuntimeError):
            raise EngineeringError("sandbox_root_unavailable") from None
        if not resolved.is_dir() or resolved == Path("/"):
            raise EngineeringError("sandbox_root_rejected")
        # Enrollment pins the directory identity. Each read reopens that root
        # and walks only descriptor-relative, non-symlink directory entries.
        if path.is_symlink():
            raise EngineeringError("sandbox_root_symlink")
        self._root = resolved
        self._root_identity = (stat_result.st_dev, stat_result.st_ino)

    @property
    def target_identity_digest(self) -> str:
        return self._consent.target_identity_digest

    def _check(self, operation: str) -> None:
        if operation not in READ_ONLY_OPERATIONS:
            raise EngineeringError("operation_widens_authority")
        validate_consent(self._consent, now_ns=self._clock())
        if operation not in self._consent.allowed_operations:
            raise EngineeringError("operation_not_consented")

    def _read(self, relative: str, *, limit: int) -> bytes:
        if type(limit) is not int or not 0 < limit <= self._MAX_FILE_BYTES:
            raise EngineeringError("sandbox_byte_limit")
        if not isinstance(relative, str) or relative.startswith("/") or "\\" in relative:
            raise EngineeringError("sandbox_path_rejected")
        parts = relative.split("/")
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise EngineeringError("sandbox_path_rejected")
        if relative not in {"etc/os-release", "var/lib/dpkg/status"} and not (
            relative.startswith("etc/systemd/system/") and self._SERVICE.fullmatch(parts[-1])
        ):
            raise EngineeringError("sandbox_path_outside_adapter")
        operation = {
            "etc/os-release": "query_version",
            "var/lib/dpkg/status": "read_status",
        }.get(relative, "query_health")
        self._check(operation)
        descriptors: list[int] = []
        links: list[tuple[int, str, int]] = []

        def check_root() -> None:
            current = self._root.stat(follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != self._root_identity:
                raise EngineeringError("sandbox_root_drift")

        def check_links() -> None:
            for parent, name, child in links:
                entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
                opened = os.fstat(child)
                if (entry.st_dev, entry.st_ino, entry.st_mode) != (opened.st_dev, opened.st_ino, opened.st_mode):
                    raise EngineeringError("sandbox_path_drift")

        try:
            check_root()
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            parent = os.open(self._root, directory_flags)
            descriptors.append(parent)
            opened_root = os.fstat(parent)
            if (opened_root.st_dev, opened_root.st_ino) != self._root_identity:
                raise EngineeringError("sandbox_root_drift")
            for part in parts[:-1]:
                child = os.open(part, directory_flags, dir_fd=parent)
                descriptors.append(child)
                links.append((parent, part, child))
                if os.fstat(child).st_dev != self._root_identity[0]:
                    raise EngineeringError("sandbox_path_rejected")
                parent = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
            descriptors.append(fd)
            links.append((parent, parts[-1], fd))
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_dev != self._root_identity[0] or before.st_size > limit:
                raise EngineeringError("sandbox_file_rejected")
            check_root()
            check_links()
            value = b""
            while len(value) <= limit:
                chunk = os.read(fd, min(65_536, limit + 1 - len(value)))
                if not chunk:
                    break
                value += chunk
            if len(value) > limit:
                raise EngineeringError("sandbox_byte_limit")
            after = os.fstat(fd)
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink):
                raise EngineeringError("sandbox_file_drift")
            check_root()
            check_links()
            self._check(operation)
            return value
        except EngineeringError:
            raise
        except OSError:
            raise EngineeringError("sandbox_file_unavailable") from None
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _observation(self, operation: str, payload: object) -> SandboxObservation:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
        self._check(operation)
        return SandboxObservation(operation, self.target_identity_digest, encoded, hashlib.sha256(encoded).hexdigest())

    def query_version(self) -> SandboxObservation:
        self._check("query_version")
        try:
            raw = self._read("etc/os-release", limit=16_384).decode("utf-8", "strict")
        except UnicodeDecodeError:
            raise EngineeringError("sandbox_encoding_rejected") from None
        values: dict[str, str] = {}
        for line in raw.splitlines():
            key, sep, value = line.partition("=")
            if sep and key in {"ID", "VERSION_ID"}:
                values[key] = value.strip().strip('"')
        if values.get("ID") != "debian" or not values.get("VERSION_ID"):
            raise EngineeringError("unsupported_initial_target")
        return self._observation("query_version", {"id": "debian", "version_id": values["VERSION_ID"]})

    def query_health(self, service_name: str) -> SandboxObservation:
        self._check("query_health")
        if not isinstance(service_name, str) or not self._SERVICE.fullmatch(service_name):
            raise EngineeringError("invalid_service_name")
        raw = self._read(f"etc/systemd/system/{service_name}", limit=65_536)
        return self._observation("query_health", {"service": service_name, "unit_present": True, "unit_sha256": hashlib.sha256(raw).hexdigest()})

    def read_status(self) -> SandboxObservation:
        self._check("read_status")
        raw = self._read("var/lib/dpkg/status", limit=self._MAX_FILE_BYTES)
        return self._observation("read_status", {"status_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})


def validate_consent(
    receipt: OwnerConsentReceipt,
    *,
    now_ns: int | None = None,
) -> OwnerConsentReceipt:
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or not 0 <= now <= _MAX_UNIX_NS:
        raise EngineeringError("invalid_time")
    if not isinstance(receipt, OwnerConsentReceipt):
        raise EngineeringError("invalid_consent_receipt")
    if (
        type(receipt.observed_unix_ns) is not int
        or type(receipt.expires_unix_ns) is not int
        or not 0 <= receipt.observed_unix_ns <= _MAX_UNIX_NS
        or not 0 <= receipt.expires_unix_ns <= _MAX_UNIX_NS
        or not receipt.observed_unix_ns <= now < receipt.expires_unix_ns
    ):
        raise EngineeringError("consent_expired")
    operations = _bounded_ids(
        receipt.allowed_operations,
        _MAX_CONSENT_OPERATIONS,
        "consent_operation_limit",
        "operation",
    )
    if not operations or not set(operations).issubset(READ_ONLY_OPERATIONS):
        raise EngineeringError("consent_scope_widens_authority")
    if set(operations) & DENIED_OPERATIONS:
        raise EngineeringError("denied_assimilation_operation")
    roots = _bounded_ids(
        receipt.allowed_roots,
        _MAX_CONSENT_ROOTS,
        "consent_root_limit",
        "root_reference",
    )
    if not roots:
        raise EngineeringError("empty_consent_scope")
    checked_sha256(receipt.target_identity_digest, "invalid_target_identity")
    checked_sha256(receipt.receipt_digest, "invalid_consent_digest")
    return OwnerConsentReceipt(
        checked_id(receipt.owner_principal, "invalid_owner_principal"),
        receipt.target_identity_digest,
        operations,
        roots,
        receipt.observed_unix_ns,
        receipt.expires_unix_ns,
        receipt.receipt_digest,
    )


def _bounded_ids(
    values: Iterable[str], limit: int, code: str, label: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise EngineeringError("invalid_" + label)
    try:
        bounded = bounded_tuple(values, limit, code)
    except TypeError:
        raise EngineeringError("invalid_" + label) from None
    return tuple(sorted({checked_id(value, label) for value in bounded}))


def _validate_manifest_candidate(manifest: ExternalManifestCandidate) -> None:
    if not isinstance(manifest, ExternalManifestCandidate):
        raise EngineeringError("invalid_manifest_candidate")
    if manifest.raw_secrets_copied is not False or manifest.authority_granted is not False:
        raise EngineeringError("manifest_boundary_violation")
    checked_sha256(manifest.target_identity_digest, "target_identity")
    for digest in (
        manifest.package_inventory_digest,
        manifest.service_graph_digest,
        manifest.mutable_state_digest,
        manifest.provenance_digest,
    ):
        checked_sha256(digest, "manifest_digest")
    if manifest.os_id != "debian":
        raise EngineeringError("unsupported_initial_target")
    checked_id(manifest.os_version, "os_version")
    if not isinstance(manifest.omissions, (tuple, list)):
        raise EngineeringError("invalid_omission")
    _bounded_ids(manifest.omissions, 64, "omission_limit_exceeded", "omission")


def build_manifest_candidate(
    consent: OwnerConsentReceipt,
    observations: Mapping[str, str],
    omissions: Iterable[str],
    *,
    now_ns: int | None = None,
) -> ExternalManifestCandidate:
    value = validate_consent(consent, now_ns=now_ns)
    required = {
        "os_id",
        "os_version",
        "package_inventory_digest",
        "service_graph_digest",
        "mutable_state_digest",
        "provenance_digest",
    }
    if (
        not isinstance(observations, Mapping)
        or len(observations) != len(required)
        or set(observations) != required
    ):
        raise EngineeringError("manifest_observation_shape")
    for field in required - {"os_id", "os_version"}:
        checked_sha256(observations[field], "invalid_manifest_digest")
    if observations["os_id"] != "debian" or not observations["os_version"]:
        raise EngineeringError("unsupported_initial_target")
    checked_id(observations["os_version"], "os_version")
    omission_values = _bounded_ids(
        omissions, 64, "omission_limit_exceeded", "omission"
    )
    return ExternalManifestCandidate(
        value.target_identity_digest,
        observations["os_id"],
        observations["os_version"],
        observations["package_inventory_digest"],
        observations["service_graph_digest"],
        observations["mutable_state_digest"],
        observations["provenance_digest"],
        omission_values,
    )


def synthesize_read_only_contracts(
    consent: OwnerConsentReceipt,
    manifest: ExternalManifestCandidate,
    *,
    now_ns: int | None = None,
) -> tuple[TypedOperation, ...]:
    value = validate_consent(consent, now_ns=now_ns)
    _validate_manifest_candidate(manifest)
    if manifest.target_identity_digest != value.target_identity_digest:
        raise EngineeringError("target_identity_drift")
    manifest_digest = semantic_digest(asdict(manifest))
    result: list[TypedOperation] = []
    for name in value.allowed_operations:
        body = {
            "target": value.target_identity_digest,
            "operation": name,
            "manifest": manifest_digest,
        }
        result.append(
            TypedOperation(
                semantic_digest(body)[:32],
                name,
                semantic_digest(
                    {"operation": name, "direction": "input", "version": 1}
                ),
                semantic_digest(
                    {"operation": name, "direction": "output", "version": 1}
                ),
                _MAX_OPERATION_DEADLINE_MILLIS,
                _MAX_OPERATION_OUTPUT_BYTES,
                "explicit_target_adapter",
                "read_only_repeatable",
            )
        )
    return tuple(result)


def propose_dormant_assimilation(
    consent: OwnerConsentReceipt,
    manifest: ExternalManifestCandidate,
    operations: Iterable[TypedOperation],
    sandbox: SandboxParityReceipt,
    *,
    now_ns: int | None = None,
) -> AssimilationProposal:
    value = validate_consent(consent, now_ns=now_ns)
    _validate_manifest_candidate(manifest)
    if not isinstance(sandbox, SandboxParityReceipt):
        raise EngineeringError("invalid_sandbox_receipt")
    try:
        raw_operations = bounded_tuple(
            operations, _MAX_CONSENT_OPERATIONS, "operation_limit_exceeded"
        )
    except TypeError:
        raise EngineeringError("invalid_operation_set") from None
    if not raw_operations or any(
        not isinstance(item, TypedOperation) for item in raw_operations
    ):
        raise EngineeringError("invalid_operation_set")
    operation_values = tuple(raw_operations)
    operation_ids: set[str] = set()
    operation_classes: set[str] = set()
    for item in operation_values:
        checked_id(item.operation_class, "operation_class")
        if (
            item.external_effect is not False
            or item.operation_class not in READ_ONLY_OPERATIONS
        ):
            raise EngineeringError("operation_widens_authority")
        if item.operation_class not in value.allowed_operations:
            raise EngineeringError("operation_not_consented")
        checked_id(item.operation_id, "operation_id")
        checked_sha256(item.input_schema_digest, "input_schema_digest")
        checked_sha256(item.output_schema_digest, "output_schema_digest")
        checked_id(item.terminal_observer, "terminal_observer")
        if (
            type(item.deadline_millis) is not int
            or not 0 < item.deadline_millis <= _MAX_OPERATION_DEADLINE_MILLIS
            or type(item.maximum_output_bytes) is not int
            or not 0 < item.maximum_output_bytes <= _MAX_OPERATION_OUTPUT_BYTES
            or item.idempotency != "read_only_repeatable"
        ):
            raise EngineeringError("invalid_read_only_operation")
        if (
            item.operation_id in operation_ids
            or item.operation_class in operation_classes
        ):
            raise EngineeringError("duplicate_operation")
        operation_ids.add(item.operation_id)
        operation_classes.add(item.operation_class)
    if (
        manifest.target_identity_digest != value.target_identity_digest
        or sandbox.target_identity_digest != value.target_identity_digest
    ):
        raise EngineeringError("target_identity_drift")
    manifest_digest = semantic_digest(asdict(manifest))
    operations_digest = semantic_digest([asdict(item) for item in operation_values])
    if (
        sandbox.manifest_digest != manifest_digest
        or sandbox.operations_digest != operations_digest
    ):
        raise EngineeringError("sandbox_input_drift")
    checked_id(sandbox.evaluator_principal, "evaluator_principal")
    checked_id(sandbox.generator_principal, "generator_principal")
    if sandbox.evaluator_principal == sandbox.generator_principal:
        raise EngineeringError("evaluator_identity_collision")
    if sandbox.passed is not True:
        raise EngineeringError("sandbox_parity_failed")
    if (
        sandbox.network_unrestricted is not False
        or sandbox.production_credentials_exposed is not False
        or sandbox.authority_delta is not False
    ):
        raise EngineeringError("sandbox_boundary_violation")
    for digest in (
        sandbox.exact_fixture_digest,
        sandbox.fault_results_digest,
        sandbox.rollback_digest,
    ):
        checked_sha256(digest, "invalid_sandbox_digest")
    sandbox_digest = semantic_digest(asdict(sandbox))
    body = {
        "target": value.target_identity_digest,
        "consent": value.receipt_digest,
        "manifest": manifest_digest,
        "operations": operations_digest,
        "sandbox": sandbox_digest,
    }
    return AssimilationProposal(
        semantic_digest(body)[:32],
        value.target_identity_digest,
        value.receipt_digest,
        manifest_digest,
        operations_digest,
        sandbox_digest,
        "dormant_candidate",
    )
