#!/usr/bin/env python3
"""Validate retained Linux installed-product evidence without promoting it.

The validator binds a product receipt to one exact qualification subject, package
receipt, CI run/attempt and hosted runner image. It does not turn Xvfb, virtual
input or an ephemeral keyring into physical-host or release acceptance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

PRODUCT_SCHEMA = "hepta.native-linux-product-qualification.v2"
MEASUREMENT_SCHEMA = "hepta.native.ordinary-linux-measurement.v2"
SUMMARY_SCHEMA = "hepta.ui.native.linux-product-observation.v1"
PACKAGE_SCHEMA = "hepta.ui-native-package-receipt.v1"
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
PRODUCT_RELATIVE = Path("native-evidence/ordinary-linux-product/product-receipt.json")
PACKAGE_RELATIVE = Path("native-package/package-receipt.json")
NEGATIVE_FLAGS = (
    "physicalDisplayAcceptance",
    "physicalInputAcceptance",
    "screenReaderAcceptance",
    "cjkImeAcceptance",
    "independentAcceptance",
    "productionKeyCustodyAcceptance",
    "release",
)
POSITIVE_FLAGS = (
    "keyringCredentialLifecycleObserved",
    "visibleWindowObserved",
    "virtualFocusObserved",
    "keyboardEventsDelivered",
    "normalCloseVerified",
    "ownerStateUnchanged",
)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f"missing, unsafe or oversized product evidence: {path}")
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
    )
    if not isinstance(value, dict):
        raise ValueError("product evidence must be a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_digest_map(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label} must be a nonempty digest map")
    result = {}
    for name, digest in value.items():
        if not isinstance(name, str) or not name or "\\" in name:
            raise ValueError(f"{label} contains an unsafe path")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{label} contains an unsafe path")
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError(f"{label} contains an invalid digest")
        result[name] = digest
    return result


def positive_number(value: object, label: str) -> None:
    if type(value) not in (int, float) or value <= 0:
        raise ValueError(f"{label} must be a positive measured number")


def validate_credential_receipts(receipt: dict) -> None:
    provision = receipt.get("keyringProvisionReceipt")
    deletion = receipt.get("keyringDeleteReceipt")
    if not isinstance(provision, dict) or set(provision) != {
        "schema",
        "account",
        "token_digest",
    }:
        raise ValueError("invalid keyring provision receipt")
    if not isinstance(deletion, dict) or set(deletion) != {
        "schema",
        "account",
        "deleted",
    }:
        raise ValueError("invalid keyring deletion receipt")
    account = provision.get("account")
    if (
        provision.get("schema")
        != "hepta.native-gateway-credential-provision.v1"
        or not isinstance(account, str)
        or not account
        or not isinstance(provision.get("token_digest"), str)
        or not DIGEST.fullmatch(provision["token_digest"])
        or "token" in provision
    ):
        raise ValueError("keyring provision did not retain a safe receipt")
    if (
        deletion.get("schema") != "hepta.native-gateway-credential-delete.v1"
        or deletion.get("account") != account
        or deletion.get("deleted") is not True
    ):
        raise ValueError("keyring credential deletion was not observed")


def validate_measurements(
    starts: object, package_digests: dict[str, str], connection_session: str
) -> None:
    if not isinstance(starts, list) or len(starts) != 2:
        raise ValueError("exactly two ordinary GUI starts are required")
    sessions = set()
    processes = set()
    for index, start in enumerate(starts):
        if not isinstance(start, dict):
            raise ValueError("ordinary GUI start must be an object")
        session = start.get("session")
        session_id = session.get("session_id") if isinstance(session, dict) else None
        if not isinstance(session_id, str) or not session_id or session_id == connection_session:
            raise ValueError("ordinary GUI start has an invalid or reused session")
        if session_id in sessions:
            raise ValueError("ordinary GUI restart reused a session identity")
        sessions.add(session_id)
        process_id = start.get("process_id")
        if type(process_id) is not int or process_id <= 0 or process_id in processes:
            raise ValueError("ordinary GUI start has an invalid process identity")
        processes.add(process_id)
        if type(start.get("normal_close_exit_code")) is not int or start[
            "normal_close_exit_code"
        ] != 0:
            raise ValueError("ordinary GUI did not close normally")
        measurement = start.get("measurements")
        if not isinstance(measurement, dict):
            raise ValueError("ordinary GUI measurement is missing")
        if measurement.get("schema") != MEASUREMENT_SCHEMA:
            raise ValueError("ordinary GUI measurement schema is invalid")
        if measurement.get("packageBinarySha256") != package_digests:
            raise ValueError("ordinary GUI measurement is for another package")
        if type(measurement.get("sampleIndex")) is not int or measurement[
            "sampleIndex"
        ] != index:
            raise ValueError("ordinary GUI sample index is invalid")
        for key in (
            "launchToReadinessMs",
            "launchToVisibleWindowMs",
            "keyboardCommandMs",
            "normalCloseMs",
            "residentKiBAtObservation",
        ):
            positive_number(measurement.get(key), key)
        before = measurement.get("focusedWindowBefore")
        after = measurement.get("focusedWindowAfter")
        if type(before) is not int or before <= 0 or type(after) is not int or after != before:
            raise ValueError("virtual focus was not retained by the native window")
        if measurement.get("virtualFocusObserved") is not True:
            raise ValueError("virtual focus observation is missing")
        if measurement.get("keyboardEventsDelivered") is not True:
            raise ValueError("keyboard traversal observation is missing")
        for key in (
            "inputLatencyMeasured",
            "soakMeasured",
            "productionThresholdEvaluated",
        ):
            if measurement.get(key) is not False:
                raise ValueError(f"unsupported performance promotion: {key}")


def validate_bundle(bundle: Path, expected: dict[str, object]) -> dict:
    if not bundle.is_dir() or bundle.is_symlink():
        raise ValueError("product evidence bundle must be a real directory")
    receipt_path = bundle / PRODUCT_RELATIVE
    package_path = bundle / PACKAGE_RELATIVE
    receipt = read_json(receipt_path)
    package_receipt = read_json(package_path)
    identity_fields = (
        "candidateSha",
        "sourceSha",
        "sourceTreeSha",
        "sourceKind",
        "workflowSha",
        "runId",
        "runAttempt",
    )
    if receipt.get("schema") != PRODUCT_SCHEMA:
        raise ValueError("unknown Linux product receipt schema")
    for key in identity_fields:
        if receipt.get(key) != expected.get(key):
            raise ValueError(f"Linux product receipt has foreign {key}")
    for key in ("candidateSha", "sourceSha", "sourceTreeSha", "workflowSha"):
        if not isinstance(receipt.get(key), str) or not SHA.fullmatch(receipt[key]):
            raise ValueError(f"Linux product receipt has invalid {key}")
    if receipt.get("sourceKind") not in {"head", "merge"}:
        raise ValueError("Linux product receipt has invalid source kind")
    runner = receipt.get("runner")
    if not isinstance(runner, dict) or runner != expected.get("runner"):
        raise ValueError("Linux product receipt has foreign runner image")
    if set(runner) != {"ImageOS", "ImageVersion", "RUNNER_ARCH"} or any(
        not isinstance(value, str) or not value for value in runner.values()
    ):
        raise ValueError("Linux product runner image is incomplete")
    for key in POSITIVE_FLAGS:
        if receipt.get(key) is not True:
            raise ValueError(f"required Linux product observation missing: {key}")
    for key in NEGATIVE_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"unsupported Linux product promotion: {key}")
    if (
        receipt.get("environment")
        != "isolated Linux Xvfb/DBus with real OS keyring and owner-format fixture"
    ):
        raise ValueError("Linux product environment is not the isolated hosted lane")
    if package_receipt.get("schema") != PACKAGE_SCHEMA:
        raise ValueError("unknown package receipt schema")
    if package_receipt.get("platform") != "linux":
        raise ValueError("Linux product receipt is bound to a non-Linux package")
    manifest = package_receipt.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("package manifest is missing")
    package_digests = require_digest_map(
        manifest.get("binarySha256"), "package binary digests"
    )
    if receipt.get("packageBinarySha256") != package_digests:
        raise ValueError("Linux product binary digests differ from the package receipt")
    expected_manifest_digest = hashlib.sha256(
        (json.dumps(manifest, indent=2) + "\n").encode()
    ).hexdigest()
    if receipt.get("packageManifestSha256") != expected_manifest_digest:
        raise ValueError("Linux product manifest digest is invalid")
    if not isinstance(receipt.get("gatewaySha256"), str) or not DIGEST.fullmatch(
        receipt["gatewaySha256"]
    ):
        raise ValueError("Linux product gateway digest is invalid")
    validate_credential_receipts(receipt)
    connection = receipt.get("normalConnection")
    connection_session = (
        connection.get("session", {}).get("session_id")
        if isinstance(connection, dict)
        and isinstance(connection.get("session"), dict)
        else None
    )
    if not isinstance(connection_session, str) or not connection_session:
        raise ValueError("normal connection session identity is missing")
    validate_measurements(
        receipt.get("ordinaryGuiStarts"), package_digests, connection_session
    )
    return {
        "schema": SUMMARY_SCHEMA,
        "receipt": PRODUCT_RELATIVE.as_posix(),
        "receiptSha256": sha256_file(receipt_path),
        "receiptBytes": receipt_path.stat().st_size,
        "packageReceiptSha256": sha256_file(package_path),
        **{key: receipt[key] for key in identity_fields},
        "runner": runner,
        "packageBinarySha256": package_digests,
        "gatewaySha256": receipt["gatewaySha256"],
        "ordinaryGuiStartCount": 2,
        "keyringCredentialLifecycleObserved": True,
        "virtualFocusObserved": True,
        "normalCloseVerified": True,
        "ownerStateUnchanged": True,
        **{key: False for key in NEGATIVE_FLAGS},
    }
