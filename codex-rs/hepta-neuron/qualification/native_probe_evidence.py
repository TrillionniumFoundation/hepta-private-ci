"""Validate the existing isolated native probe's retained diagnostic evidence.

This reader never executes effects or authenticates production authority. It assumes
an owner-protected output directory and the recorded reviewed child executable.
Source/hash consistency is not an independently signed observation. Process failure
alone never proves NotApplied; a valid observation survives later process failure.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

MAX_RECEIPT_BYTES = 32768
PROFILE = "hepta.model-native-evidence-evaluation.v3"
SHA = re.compile(r"(?!0{64}$)[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
SIZES = {"action": 6, "target": 4, "disposition": 6, "postcondition": 6, "ood": 2}


def read_native_receipt(path: Path) -> tuple[dict, str]:
    """Read one bounded regular file, rejecting symlinks and ambiguous JSON."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_RECEIPT_BYTES:
            raise ValueError("native_report_file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise ValueError("native_report_changed")

    def unique_fields(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("native_report_duplicate_field")
            result[key] = value
        return result

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("native_report_nonfinite")
        return result

    def invalid_constant(_value):
        raise ValueError("native_report_nonfinite")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields,
                       parse_float=finite_float, parse_constant=invalid_constant)
    if type(value) is not dict:
        raise ValueError("native_report_shape")
    return value, hashlib.sha256(raw).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _choice(packet: dict) -> dict:
    """Independent reduction of the fixed diagnostic head profile, never policy selection."""
    _require(type(packet) is dict and packet.get("schema") == "hepta.model-native-probe-input.v2",
             "packet_schema_mismatch")
    _require(type(packet.get("modelSupported")) is bool, "packet_support_shape")
    probabilities = packet["probabilities"]
    _require(type(probabilities) is dict and set(probabilities) == set(SIZES), "packet_head_shape")
    predicted = {}
    for key, size in SIZES.items():
        values = probabilities[key]
        _require(type(values) is list and len(values) == size, "packet_head_shape")
        _require(all(_number(v) and 0 <= v <= 1 for v in values), "packet_probability")
        _require(abs(sum(values) - 1) <= 1e-5, "packet_probability")
        predicted[key] = max(range(size), key=values.__getitem__)
    confidence = min(probabilities[key][predicted[key]] for key in
                     ("action", "target", "disposition", "postcondition"))
    ood = probabilities["ood"][1]
    abstained = (not packet["modelSupported"] or predicted["action"] != 2 or predicted["disposition"] != 0 or
                 predicted["postcondition"] != 2 or confidence < 0.95 or ood > 0.05)
    return {"predicted": predicted, "confidence": confidence, "ood": ood, "abstained": abstained}


def evaluate_native_receipt(path: Path, *, exit_code: int, timed_out: bool,
                            packet: dict, source: dict, expected_target: int,
                            expected_ood: bool) -> dict:
    """Keep task correctness, observed effect, and process completion separate.

    A retained observed copy with the wrong target is still an observed effect.
    A missing/corrupt/mismatched report is unknown, even for exit zero or three.
    No exception message, raw diagnostic text or target text enters the summary.
    """
    _require(type(exit_code) is int and type(timed_out) is bool, "process_evidence_shape")
    _require(type(expected_target) is int and type(expected_ood) is bool, "expected_label_shape")
    _require((-1 <= expected_target < 4) and (expected_ood or expected_target >= 0), "expected_label_shape")
    result = {"status": "native_indeterminate", "task_passed": False,
              "external_effect": None, "native_report_sha256": None,
              "native_evaluation_profile": PROFILE, "evidence_error": None}
    try:
        native, digest = read_native_receipt(path)
        result["native_report_sha256"] = digest
        _require(type(native.get("source")) is dict, "native_source_mismatch")
        for key in ("commit", "tree"):
            _require(type(source.get(key)) is str and GIT_SHA.fullmatch(source[key]) is not None and
                     native["source"].get(key) == source[key], "native_source_mismatch")
        _require(native["source"].get("dirty") is False, "native_source_mismatch")
        _require(native.get("productionActivation") is False, "native_scope_mismatch")
        choice = native.get("modelChoice")
        _require(type(choice) is dict and choice.get("authorityGranted") is False, "native_choice_shape")
        for key in ("requestId", "replySha256"):
            _require(type(packet.get(key)) is str and choice.get(key) == packet[key], "native_request_mismatch")
        _require(SHA.fullmatch(packet["replySha256"]) is not None, "native_request_mismatch")
        reduced = _choice(packet)
        _require(type(choice.get("modelSupported")) is bool and
                 choice["modelSupported"] is packet["modelSupported"], "native_support_mismatch")
        for key in ("confidence", "ood"):
            _require(_number(choice.get(key)) and abs(choice[key] - reduced[key]) <= 1e-12,
                     "native_choice_mismatch")
        if native.get("schema") == "hepta.native-model-abstention.v1":
            _require(reduced["abstained"] and choice.get("status") == "abstained" and
                     native.get("externalEffect") is False, "native_abstention_mismatch")
            predicted = choice.get("predicted")
            _require(type(predicted) is dict and set(predicted) == set(SIZES) and
                     all(type(predicted[key]) is int and predicted[key] == reduced["predicted"][key]
                         for key in SIZES), "native_choice_mismatch")
            result.update(status="abstained", external_effect=False,
                          task_passed=exit_code == 3 and not timed_out and expected_ood)
        else:
            _require(native.get("schema") == "hepta.native-x11-clipboard-qualification.v1",
                     "native_schema_mismatch")
            _require(choice.get("status") == "selected", "native_choice_mismatch")
            selected = choice.get("targetIndex")
            _require(type(selected) is int and 0 <= selected < 4 and
                     selected == reduced["predicted"]["target"], "native_target_mismatch")
            targets = packet["targets"]
            _require(type(targets) is list and len(targets) == 4, "native_target_mismatch")
            target = targets[selected]
            _require(type(target) is dict and type(target.get("generation")) is int and
                     target["generation"] == 1, "native_target_mismatch")
            for key in ("referenceId", "text"):
                _require(type(target.get(key)) is str and choice.get(key) == target[key], "native_target_mismatch")
            _require(native.get("realOsClipboard") is True and native.get("isolatedDisplay") is True and
                     native.get("tcpListenerEnabled") is False and native.get("backendAndAuthorityAreFixtures") is True and
                     native.get("independentPrincipalObservation") is False and native.get("operatorAcceptance") is False and
                     native.get("durableCrossProcessRecovery") is False, "native_scope_mismatch")
            for key in ("frameSha256", "sourceActionDigest", "outcomeDigest", "readbackSha256",
                        "executableSha256", "xvfbSha256"):
                _require(type(native.get(key)) is str and SHA.fullmatch(native[key]) is not None, "native_digest_shape")
            readback_matches = native["readbackSha256"] == hashlib.sha256(target["text"].encode()).hexdigest()
            _require(readback_matches, "native_readback_mismatch")
            # Preserve the actual observation even when later cleanup or validation fails.
            result.update(status="observed", selected_target_index=selected, external_effect=True,
                          readback_matches_selected=True, model_receipt_bound=True,
                          model_policy_respected=not reduced["abstained"],
                          frame_sha256=native["frameSha256"], outcome_digest=native["outcomeDigest"])
            checks = ("exactRetryReused", "changedIntentRejected", "observationAfterClose",
                      "writerCleanupObserved", "observerCleanupObserved", "changedPrincipalRejected")
            lifecycle_ok = (all(native.get(key) is True for key in checks) and
                            type(native.get("finalUseCalls")) is int and native["finalUseCalls"] == 1 and
                            _number(native.get("elapsedMicros")) and native["elapsedMicros"] >= 0)
            result["task_passed"] = (not reduced["abstained"] and exit_code == 0 and not timed_out and lifecycle_ok and
                                     not expected_ood and selected == expected_target)
            if not reduced["abstained"] and not lifecycle_ok:
                result["evidence_error"] = "native_lifecycle_incomplete"
            elif reduced["abstained"]:
                result["evidence_error"] = "native_policy_violation"
        expected_exit = 3 if choice["status"] == "abstained" else 0
        if timed_out or exit_code != expected_exit:
            result["evidence_error"] = "native_process_incomplete"
    except FileNotFoundError:
        result["evidence_error"] = "native_report_missing"
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, OverflowError):
        result["evidence_error"] = "native_report_unreadable"
    except (KeyError, TypeError, IndexError):
        result["evidence_error"] = "native_report_shape"
    except ValueError as error:
        # Only messages from this validator are retained; JSON details stay private.
        reason = str(error)
        result["evidence_error"] = reason if re.fullmatch(r"(?:native|packet)_[a-z_]+", reason) else "native_report_invalid"
    return result
