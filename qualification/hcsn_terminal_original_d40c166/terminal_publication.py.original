"""Bind a future supervisor terminal original to the N256 receipt.

This module validates metadata only. It does not launch or observe a process,
write an output, invoke the provider, or perform numerical work.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from qualification.hcsn_currentstate_n256_execution_admission_bridge import (
    admission_bridge,
)
from qualification.hcsn_currentstate_n256_execution_receipt_contract import (
    receipt_contract,
)
from qualification.hcsn_currentstate_n256_execution_receipt_publisher_intent import (
    publisher,
)


OBSERVATION_SCHEMA = "hcsn-n256-supervisor-terminal-observation-v1"
PUBLICATION_SCHEMA = "hcsn-n256-terminal-publication-v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}")
OBSERVATION_FIELDS = {
    "schema",
    "execution_key",
    "capture_session_id",
    "host_alias",
    "job_id",
    "execution_request_sha256",
    "result_manifest_sha256",
    "stdout_sha256",
    "stderr_sha256",
    "execution_started_at_utc",
    "execution_completed_at_utc",
    "process_exit_code",
    "timed_out",
    "execution_complete",
    "historical_negative_and_unknown_preserved",
    "largegrid_qualification",
    "production_adoption",
    "observation_sha256",
}
PUBLICATION_FIELDS = {
    "schema",
    "provider_admission_sha256",
    "execution_freeze_sha256",
    "result_manifest_sha256",
    "terminal_observation_sha256",
    "execution_receipt_sha256",
    "execution_key",
    "capture_session_id",
    "host_alias",
    "historical_negative_and_unknown_preserved",
    "largegrid_qualification",
    "production_adoption",
    "publication_sha256",
}


class TerminalPublicationError(ValueError):
    """Raised before an unbound terminal original can be published."""


class TerminalOriginalRequired(RuntimeError):
    """Raised when a future supervisor terminal original is absent."""


@dataclass(frozen=True)
class TerminalPublication:
    receipt: dict
    publication: dict


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require_sha(value, field):
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise TerminalPublicationError(f"missing or invalid SHA-256: {field}")


def _require_token(value, field):
    if not isinstance(value, str) or TOKEN_RE.fullmatch(value) is None:
        raise TerminalPublicationError(f"missing or invalid token: {field}")


def _load_record(path, name):
    if path is None:
        raise TerminalOriginalRequired(f"N256 {name} is not supplied")
    try:
        value = json.loads(Path(path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TerminalPublicationError(f"invalid {name}") from error
    if not isinstance(value, dict):
        raise TerminalPublicationError(f"invalid {name}")
    return value


def _validate_observation(observation, admission, freeze, manifest):
    if set(observation) != OBSERVATION_FIELDS:
        raise TerminalPublicationError("terminal observation field set mismatch")
    if observation["schema"] != OBSERVATION_SCHEMA:
        raise TerminalPublicationError("terminal observation schema mismatch")
    admission_bridge.validate_postexecution_bundle(admission, freeze, manifest)
    for field in (
        "execution_request_sha256",
        "result_manifest_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "observation_sha256",
    ):
        _require_sha(observation[field], field)
    for field in ("execution_key", "capture_session_id", "host_alias", "job_id"):
        _require_token(observation[field], field)
    if observation["execution_key"] != admission["execution_key"]:
        raise TerminalPublicationError("terminal observation execution key mismatch")
    if observation["capture_session_id"] != freeze["capture_session_id"]:
        raise TerminalPublicationError("terminal observation capture session mismatch")
    if observation["host_alias"] != freeze["host_alias"]:
        raise TerminalPublicationError("terminal observation host mismatch")
    if observation["execution_request_sha256"] != freeze["execution_request_sha256"]:
        raise TerminalPublicationError("terminal observation request mismatch")
    if observation["result_manifest_sha256"] != _sha(manifest):
        raise TerminalPublicationError("terminal observation manifest mismatch")
    if type(observation["process_exit_code"]) is not int:
        raise TerminalPublicationError("process exit code must be an integer")
    if type(observation["timed_out"]) is not bool:
        raise TerminalPublicationError("timed-out fact must be a boolean")
    if type(observation["execution_complete"]) is not bool:
        raise TerminalPublicationError("execution-complete fact must be a boolean")
    if observation["timed_out"] or not observation["execution_complete"]:
        raise TerminalPublicationError("terminal observation is incomplete or timed out")
    if observation["historical_negative_and_unknown_preserved"] is not True:
        raise TerminalPublicationError("historical negative or UNKNOWN state was erased")
    if observation["largegrid_qualification"] is not False:
        raise TerminalPublicationError("terminal observation cannot grant qualification")
    if observation["production_adoption"] is not False:
        raise TerminalPublicationError("terminal observation cannot adopt production")
    payload = dict(observation)
    digest = payload.pop("observation_sha256")
    if digest != _sha(payload):
        raise TerminalPublicationError("terminal observation digest mismatch")


def validate_terminal_publication(
    publication, receipt, observation, admission, freeze, manifest
):
    """Validate one persisted publication against every bound original."""

    _validate_observation(observation, admission, freeze, manifest)
    receipt_contract.validate_future_execution_receipt(
        receipt, admission, freeze, manifest
    )
    if not isinstance(publication, dict) or set(publication) != PUBLICATION_FIELDS:
        raise TerminalPublicationError("terminal publication field set mismatch")
    if publication["schema"] != PUBLICATION_SCHEMA:
        raise TerminalPublicationError("terminal publication schema mismatch")
    expected = {
        "provider_admission_sha256": admission["admission_sha256"],
        "execution_freeze_sha256": freeze["freeze_sha256"],
        "result_manifest_sha256": _sha(manifest),
        "terminal_observation_sha256": observation["observation_sha256"],
        "execution_receipt_sha256": receipt["receipt_sha256"],
        "execution_key": admission["execution_key"],
        "capture_session_id": freeze["capture_session_id"],
        "host_alias": freeze["host_alias"],
    }
    for field, value in expected.items():
        if publication[field] != value:
            raise TerminalPublicationError(f"terminal publication {field} mismatch")
    if publication["historical_negative_and_unknown_preserved"] is not True:
        raise TerminalPublicationError("historical negative or UNKNOWN state was erased")
    if publication["largegrid_qualification"] is not False:
        raise TerminalPublicationError("terminal publication cannot grant qualification")
    if publication["production_adoption"] is not False:
        raise TerminalPublicationError("terminal publication cannot adopt production")
    payload = dict(publication)
    digest = payload.pop("publication_sha256")
    _require_sha(digest, "publication_sha256")
    if digest != _sha(payload):
        raise TerminalPublicationError("terminal publication digest mismatch")
    return True


def build_terminal_publication(
    *,
    provider_admission_path,
    execution_freeze_path,
    result_manifest_path,
    terminal_observation_path,
):
    """Return a receipt plus a publication record without writing either."""

    admission = _load_record(provider_admission_path, "provider admission")
    freeze = _load_record(execution_freeze_path, "execution freeze")
    manifest = _load_record(result_manifest_path, "result manifest")
    observation = _load_record(terminal_observation_path, "terminal observation")
    _validate_observation(observation, admission, freeze, manifest)
    receipt = publisher.build_receipt_record(
        provider_admission_path=provider_admission_path,
        execution_freeze_path=execution_freeze_path,
        result_manifest_path=result_manifest_path,
        execution_started_at_utc=observation["execution_started_at_utc"],
        execution_completed_at_utc=observation["execution_completed_at_utc"],
        process_exit_code=observation["process_exit_code"],
        execution_complete=observation["execution_complete"],
    )
    receipt_contract.validate_future_execution_receipt(
        receipt, admission, freeze, manifest
    )
    payload = {
        "schema": PUBLICATION_SCHEMA,
        "provider_admission_sha256": admission["admission_sha256"],
        "execution_freeze_sha256": freeze["freeze_sha256"],
        "result_manifest_sha256": _sha(manifest),
        "terminal_observation_sha256": observation["observation_sha256"],
        "execution_receipt_sha256": receipt["receipt_sha256"],
        "execution_key": admission["execution_key"],
        "capture_session_id": freeze["capture_session_id"],
        "host_alias": freeze["host_alias"],
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
    }
    publication = dict(payload)
    publication["publication_sha256"] = _sha(payload)
    validate_terminal_publication(
        publication, receipt, observation, admission, freeze, manifest
    )
    return TerminalPublication(receipt=receipt, publication=publication)
