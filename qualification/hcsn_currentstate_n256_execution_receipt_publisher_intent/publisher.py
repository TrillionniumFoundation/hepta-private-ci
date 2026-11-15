"""Construct a canonical #6359 receipt after authentic execution facts exist.

This module does not write or publish the receipt.  It performs no provider,
numerical, model, Torch, or optimizer work.  The caller must supply the exact
admission, freeze, and result-manifest originals plus authoritative process
facts; the existing receipt contract performs the final fail-closed check.
"""

import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_execution_receipt_contract import (
    receipt_contract,
)


class ReceiptOriginalRequired(RuntimeError):
    """Raised before validation when a required external original is absent."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _record(path, name):
    if path is None:
        raise ReceiptOriginalRequired(f"N256 {name} is not supplied")
    try:
        value = json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid {name}")
    return value


def build_receipt_record(
    *,
    provider_admission_path,
    execution_freeze_path,
    result_manifest_path,
    execution_started_at_utc,
    execution_completed_at_utc,
    process_exit_code,
    execution_complete,
):
    """Return one validated receipt record without writing or executing it."""

    required = (
        (provider_admission_path, "provider admission"),
        (execution_freeze_path, "execution freeze"),
        (result_manifest_path, "result manifest"),
    )
    for path, name in required:
        if path is None:
            raise ReceiptOriginalRequired(f"N256 {name} is not supplied")

    admission = _record(provider_admission_path, "provider admission")
    freeze = _record(execution_freeze_path, "execution freeze")
    manifest = _record(result_manifest_path, "result manifest")
    if type(process_exit_code) is not int:
        raise ValueError("process exit code must be an integer, not a boolean")
    if type(execution_complete) is not bool:
        raise ValueError("execution-complete fact must be a boolean")
    payload = {
        "schema": receipt_contract.SCHEMA,
        "provider_admission_sha256": admission.get("admission_sha256"),
        "execution_freeze_sha256": freeze.get("freeze_sha256"),
        "result_manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest(),
        "execution_key": admission.get("execution_key"),
        "capture_session_id": freeze.get("capture_session_id"),
        "host_alias": freeze.get("host_alias"),
        "execution_started_at_utc": execution_started_at_utc,
        "execution_completed_at_utc": execution_completed_at_utc,
        "process_exit_code": process_exit_code,
        "execution_complete": execution_complete,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
    }
    receipt = dict(payload)
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    receipt_contract.validate_future_execution_receipt(
        receipt, admission, freeze, manifest
    )
    return receipt
