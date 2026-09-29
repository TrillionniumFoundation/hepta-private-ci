"""Inspect retained OpenClaw observations without reading credentials or retrying.

Connectivity evidence never grants data-use rights, artifact selection, effect
permission or provider qualification. This is a package-local diagnostic reader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

MAX_BYTES = 262144
MODEL_REF = re.compile(r"[a-z0-9-]+/[A-Za-z0-9._:/-]{1,160}\Z")
NONCE = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


def strict_json(raw: bytes) -> Any:
    if len(raw) > MAX_BYTES:
        raise ValueError("response exceeds diagnostic bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("non-finite JSON value")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=invalid_constant)


def inspect_response(*, catalog: bytes, response: bytes, diagnostics: bytes,
                     expected_model: str, nonce: str) -> dict:
    if not MODEL_REF.fullmatch(expected_model) or not NONCE.fullmatch(nonce):
        raise ValueError("invalid model reference or nonce")
    if any(len(raw) > MAX_BYTES for raw in (catalog, response, diagnostics)):
        raise ValueError("retained observation exceeds diagnostic bound")
    models = catalog.decode("utf-8").splitlines()
    if len(models) > 4096 or any(not MODEL_REF.fullmatch(v) for v in models):
        raise ValueError("catalog is not the plain model-list representation")
    report = {
        "schema": "hepta.teacher-connectivity-observation.v1",
        "requested_model": expected_model, "request_nonce": nonce,
        "catalog_sha256": hashlib.sha256(catalog).hexdigest(),
        "response_sha256": hashlib.sha256(response).hexdigest(),
        "diagnostic_sha256": hashlib.sha256(diagnostics).hexdigest(),
        "configured_model_observed": expected_model in models,
        "connectivity_verified": False, "provider_qualified": False,
        "training_rights_verified": False, "training_data_admitted": False,
        "tool_isolation_verified": False, "operator_acceptance": False,
        "production_activation": False, "external_effect_qualified": False,
        "status": "response_unavailable", "gateway_run_id": None,
        "observed_provider": None, "observed_model": None,
    }
    # Keep a returned run identity even on failure: an accepted remote run may
    # still exist. Missing replies or local process exit never prove NotApplied.
    if response:
        value = strict_json(response)
        if not isinstance(value, dict):
            raise ValueError("gateway response must be an object")
        run_id = value.get("runId")
        if run_id is not None:
            if not isinstance(run_id, str) or not NONCE.fullmatch(run_id):
                raise ValueError("invalid gateway run identity")
            report["gateway_run_id"] = run_id
        if value.get("ok") is False or value.get("error") is not None:
            report["status"] = "gateway_error_reconcile_before_retry"
            return report
    elif expected_model not in models:
        report["status"] = "requested_model_not_configured"
        return report
    else:
        return report
    result = value.get("result", value)
    if value.get("status") not in (None, "ok", "completed"):
        report["status"] = "gateway_not_terminal"
        return report
    if not isinstance(result, dict):
        raise ValueError("gateway result must be an object")
    meta = result.get("meta", {})
    if not isinstance(meta, dict) or meta.get("aborted") is not False:
        report["status"] = "completion_not_confirmed"
        return report
    if meta.get("error") is not None or result.get("error") is not None:
        report["status"] = "provider_error"
        return report
    agent = meta.get("agentMeta", {})
    if not isinstance(agent, dict):
        raise ValueError("invalid provider observation")
    provider, model = agent.get("provider"), agent.get("model")
    if not isinstance(provider, str) or not isinstance(model, str):
        report["status"] = "provider_identity_unobserved"
        return report
    if not MODEL_REF.fullmatch(provider + "/" + model):
        raise ValueError("invalid observed model reference")
    report.update(observed_provider=provider, observed_model=model)
    if provider + "/" + model != expected_model:
        report["status"] = "provider_model_mismatch"
        return report
    payloads = result.get("payloads")
    if not isinstance(payloads, list) or len(payloads) != 1:
        report["status"] = "unexpected_reply_shape"
        return report
    item = payloads[0]
    if not isinstance(item, dict) or not isinstance(item.get("text"), str):
        report["status"] = "unexpected_reply_shape"
        return report
    expected = {"schema": "hepta.teacher-connectivity.v1", "nonce": nonce,
                "advisory_only": True, "training_authorized": False}
    payload = strict_json(item["text"].encode("utf-8"))
    if payload != expected or type(payload.get("advisory_only")) is not bool or type(payload.get("training_authorized")) is not bool:
        report["status"] = "reply_binding_mismatch"
        return report
    if item.get("isError") not in (None, False) or item.get("mediaUrl") is not None:
        report["status"] = "unexpected_reply_shape"
        return report
    if expected_model not in models:
        report["status"] = "requested_model_not_configured"
        return report
    report.update(status="connected_advisory_only", connectivity_verified=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def bounded_read(path):
        with path.open("rb") as stream:
            return stream.read(MAX_BYTES + 1)
    report = inspect_response(catalog=bounded_read(args.catalog),
        response=bounded_read(args.response), diagnostics=bounded_read(args.diagnostics),
        expected_model=args.expected_model, nonce=args.nonce)
    report["validator_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    data = json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    with args.output.open("xb") as stream:
        stream.write(data)
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "sha256": hashlib.sha256(data).hexdigest()}, sort_keys=True))
    return 0 if report["connectivity_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
