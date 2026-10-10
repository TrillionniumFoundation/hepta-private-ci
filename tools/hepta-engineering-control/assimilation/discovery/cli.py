"""Machine-readable entry point for explicitly scoped Debian discovery."""

import argparse
from collections.abc import Sequence
import json
import os
import stat
import sys
from typing import NoReturn

from .parsers import DiscoveryError
from .reader import DiscoveryScope, discover
from ..contracts import ProposalError, build_assimilation_proposal


RESULT_SCHEMA = "hepta.assimilation.discovery-cli-result.v1"
SCOPE_SCHEMA = "hepta.assimilation.discovery-scope-input.v1"
MAX_SCOPE_BYTES = 65_536
SCOPE_FIELDS = {
    "schema",
    "rootDevice",
    "rootInode",
    "hostIdentityDigest",
    "enrollmentReceiptDigest",
    "expiresUnixNs",
    "osReleasePath",
    "unitPaths",
}
FIXED_OMISSIONS = (
    "apt_sources_and_keyrings_not_collected",
    "configuration_state_log_backup_ownership_not_observed",
    "credentials_and_secrets_not_collected",
    "dbus_socket_network_not_observed",
    "health_resource_restart_failure_behavior_not_observed",
    "non_atomic_snapshot",
    "runtime_process_cgroup_namespace_mount_not_observed",
    "selected_units_only",
    "systemd_dropins_aliases_generators_enablement_not_resolved",
)


class CliFailure(ValueError):
    """A fixed safe error code and its process exit class."""

    def __init__(self, code: str, exit_code: int = 2):
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise CliFailure("invalid_arguments")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="python3 -m assimilation.discovery",
        description="Read a bounded Debian rootfs inventory candidate; grants no authority.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Explicit absolute rootfs path",
    )
    parser.add_argument(
        "--scope-receipt",
        required=True,
        help="Explicit absolute host-provided scope-input JSON path",
    )
    parser.add_argument(
        "--unit",
        action="append",
        required=True,
        metavar="RELATIVE_SERVICE_PATH",
        help="Selected service path; repeat for each unit and match the scope input exactly",
    )
    parser.add_argument(
        "--proposal-config",
        help="Optional absolute JSON file of objective and retained UTF-8 owner evidence",
    )
    return parser


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CliFailure("duplicate_json_member")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    del value
    raise CliFailure("invalid_scope_json")


def _bounded_json_integer(value: str) -> int:
    if len(value.lstrip("-")) > 20:
        raise ValueError
    return int(value)


def _file_signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_scope_input(path: str) -> dict[str, object]:
    if not os.path.isabs(path):
        raise CliFailure("scope_path_not_absolute")
    fd = None
    try:
        fd = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        )
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > MAX_SCOPE_BYTES
        ):
            raise CliFailure("scope_receipt_rejected")
        chunks: list[bytes] = []
        remaining = MAX_SCOPE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        linked = os.stat(path, follow_symlinks=False)
        if (
            len(raw) > MAX_SCOPE_BYTES
            or len(raw) != after.st_size
            or _file_signature(before) != _file_signature(after)
            or _file_signature(after) != _file_signature(linked)
        ):
            raise CliFailure("scope_receipt_rejected")
    except CliFailure:
        raise
    except OSError:
        raise CliFailure("scope_receipt_rejected") from None
    finally:
        if fd is not None:
            os.close(fd)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_int=_bounded_json_integer,
        )
    except CliFailure:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise CliFailure("invalid_scope_json") from None
    if not isinstance(value, dict):
        raise CliFailure("invalid_scope_shape")
    return value


def _bounded_integer(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _scope_from_input(
    value: dict[str, object], selected: Sequence[str]
) -> DiscoveryScope:
    if set(value) != SCOPE_FIELDS or value.get("schema") != SCOPE_SCHEMA:
        raise CliFailure("invalid_scope_shape")
    root_device, root_inode = value["rootDevice"], value["rootInode"]
    expiry = value["expiresUnixNs"]
    unit_paths = value["unitPaths"]
    if (
        not _bounded_integer(root_device, 2**64 - 1)
        or not _bounded_integer(root_inode, 2**64 - 1)
        or not _bounded_integer(expiry, 2**63 - 1)
        or not isinstance(value["hostIdentityDigest"], str)
        or not isinstance(value["enrollmentReceiptDigest"], str)
        or not isinstance(value["osReleasePath"], str)
        or not isinstance(unit_paths, list)
        or not unit_paths
        or len(unit_paths) > 64
        or any(not isinstance(path, str) for path in unit_paths)
    ):
        raise CliFailure("invalid_scope_shape")
    if len(unit_paths) != len(set(unit_paths)):
        raise CliFailure("invalid_scope_shape")
    if len(selected) != len(set(selected)) or tuple(sorted(selected)) != tuple(
        sorted(unit_paths)
    ):
        raise CliFailure("selected_units_scope_mismatch")
    return DiscoveryScope(
        root_device=root_device,
        root_inode=root_inode,
        host_digest=value["hostIdentityDigest"],
        enrollment_receipt_digest=value["enrollmentReceiptDigest"],
        expires_unix_ns=expiry,
        unit_paths=tuple(sorted(unit_paths)),
        os_release_path=value["osReleasePath"],
    )


def _emit(value: dict[str, object]) -> None:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _reject(code: str, exit_code: int) -> int:
    if not code or any(
        ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in code
    ):
        code = "internal_error"
        exit_code = 70
    try:
        _emit(
            {
                "activation": False,
                "authorityGranted": False,
                "error": {"code": code},
                "partialCandidate": False,
                "schema": RESULT_SCHEMA,
                "status": "REJECTED",
            }
        )
        sys.stderr.write(f"hepta-assimilation-discovery: {code}\n")
    except BrokenPipeError:
        return 74
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """Run one scoped read and emit exactly one result object on stdout."""
    try:
        args = _parser().parse_args(argv)
        if sys.platform != "linux":
            raise CliFailure("unsupported_platform", 3)
        if not os.path.isabs(args.root):
            raise CliFailure("root_path_not_absolute")
        scope = _scope_from_input(_read_scope_input(args.scope_receipt), args.unit)
        try:
            root_fd = os.open(
                args.root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError:
            raise CliFailure("root_open_rejected", 3) from None
        try:
            candidate = discover(root_fd, scope)
        finally:
            os.close(root_fd)
        payload = json.loads(candidate.payload)
        omissions = list(FIXED_OMISSIONS)
        if payload["unresolved_dependencies"]:
            omissions.append("unresolved_service_dependencies")
        if payload["ordering_blocked"]:
            omissions.append("ordering_cycle_or_dependents_blocked")
        result = {
            "activation": False,
            "authorityGranted": False,
            "candidate": payload,
            "candidateBytes": len(candidate.payload),
            "candidateSha256": candidate.sha256,
            "coverage": {
                "class": "selected_metadata_only",
                "omissions": sorted(omissions),
            },
            "schema": RESULT_SCHEMA,
            "status": "DISCOVERED_CANDIDATE",
            "trustBoundary": {
                "consentVerifiedByCli": False,
                "enrollmentAuthenticatedByCli": False,
                "revocationCheckedByCli": False,
                "rootfsFreezeVerifiedByCli": False,
                "signatureVerifiedByCli": False,
            },
        }
        if args.proposal_config:
            config = _read_scope_input(args.proposal_config)
            if set(config) != {
                "systemId",
                "proposalId",
                "objectiveDigest",
                "ownerIdentity",
                "observedAt",
                "evidenceUtf8",
            }:
                raise CliFailure("invalid_proposal_config")
            retained = config["evidenceUtf8"]
            if not isinstance(retained, dict) or any(
                not isinstance(value, str) for value in retained.values()
            ):
                raise CliFailure("invalid_proposal_config")
            bundle = build_assimilation_proposal(
                candidate,
                system_id=config["systemId"],
                proposal_id=config["proposalId"],
                objective_digest=config["objectiveDigest"],
                owner_identity=config["ownerIdentity"],
                observed_at=config["observedAt"],
                evidence={
                    key: value.encode("utf-8") for key, value in retained.items()
                },
            )
            result["reviewBundle"] = json.loads(bundle.payload)
            result["reviewBundleSha256"] = bundle.sha256
        _emit(result)
        return 0
    except CliFailure as error:
        return _reject(error.code, error.exit_code)
    except DiscoveryError as error:
        return _reject(str(error), 3)
    except ProposalError as error:
        return _reject(str(error), 3)
    except (BrokenPipeError, KeyboardInterrupt):
        return 74
    except Exception:
        return _reject("internal_error", 70)
