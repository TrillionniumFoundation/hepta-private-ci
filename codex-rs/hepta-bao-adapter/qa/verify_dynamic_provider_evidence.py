#!/usr/bin/env python3
"""Check provider receipt structure; independent authentication remains unproved.

Neither a signedAttestation boolean nor reviewer names and digest strings prove
real provider execution. Until independently governed signature and retained
evidence verification is integrated, --require-qualified always fails closed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "hepta.secrets-dynamic-provider-acceptance.v1"
REQUIRED_SCENARIOS = {
    "tls_ca_validation",
    "kv_v2_exact_read",
    "dynamic_issue",
    "lease_renew",
    "lease_revoke",
    "provider_timeout",
    "dns_failure",
    "tls_handshake_failure",
    "http_429",
    "http_5xx",
    "token_expired",
    "policy_revoked",
    "provider_success_then_local_crash",
    "consumer_success_response_lost",
    "restart_query_reconcile",
}
REQUIRED_REVIEW_ROLES = {"secrets_security", "product_caller", "operations_sre"}
AUTHENTICATION_BLOCKER = (
    "independent authentication is unavailable: receipt claims, evidence digests "
    "and reviewer attestations have not been verified against a trusted authority"
)


def is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and value != "0" * length and all(
        char in "0123456789abcdef" for char in value
    )


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def evaluate_structure(receipt: dict[str, Any], expected_source_sha: str) -> tuple[bool, list[str]]:
    """Check a claimed acceptance structure; this result grants no qualification."""
    errors: list[str] = []
    if receipt.get("schema") != SCHEMA:
        errors.append("unexpected schema")
    if not is_hex(expected_source_sha, 40) or receipt.get("sourceHeadSha") != expected_source_sha:
        errors.append("sourceHeadSha does not match exact candidate")
    if not is_hex(receipt.get("sourceTreeSha"), 40):
        errors.append("sourceTreeSha must be a full Git tree ID")
    if receipt.get("providerProduct") != "OpenBao":
        errors.append("providerProduct must be OpenBao")
    if not nonempty(receipt.get("providerVersion")):
        errors.append("providerVersion is required")
    if receipt.get("syntheticService") is not False:
        errors.append("synthetic service evidence cannot prove dynamic provider E2E")
    if receipt.get("adapterExercised") is not True:
        errors.append("the secrets.heptabao adapter must be exercised end to end")
    if receipt.get("secretMaterialRetained") is not False:
        errors.append("evidence must not retain secret material")

    scenarios = receipt.get("scenarios")
    scenarios_valid = True
    if not isinstance(scenarios, dict) or set(scenarios) != REQUIRED_SCENARIOS:
        errors.append("dynamic provider scenario set is incomplete or contains unknown scenarios")
        scenarios_valid = False
    else:
        for name, result in scenarios.items():
            if not isinstance(result, dict):
                errors.append(f"{name}: scenario result must be an object")
                scenarios_valid = False
                continue
            if result.get("passed") is not True:
                errors.append(f"{name}: scenario did not pass")
                scenarios_valid = False
            if not is_hex(result.get("evidenceSha256"), 64):
                errors.append(f"{name}: evidence digest is invalid")
                scenarios_valid = False

    reviewers = receipt.get("independentReviewers")
    reviewers_valid = True
    roles: set[str] = set()
    principals: set[str] = set()
    if not isinstance(reviewers, list):
        errors.append("independentReviewers must be a list")
        reviewers_valid = False
    else:
        for reviewer in reviewers:
            if not isinstance(reviewer, dict):
                errors.append("reviewer entry must be an object")
                reviewers_valid = False
                continue
            role = reviewer.get("role")
            principal = reviewer.get("principal")
            roles.add(str(role))
            normalized_principal = principal.strip() if isinstance(principal, str) else ""
            if not normalized_principal or normalized_principal in principals:
                errors.append("review principals must be non-empty and distinct")
                reviewers_valid = False
            else:
                principals.add(normalized_principal)
            if not is_hex(reviewer.get("attestationSha256"), 64):
                errors.append(f"{role}: reviewer attestation digest is invalid")
                reviewers_valid = False
        if roles != REQUIRED_REVIEW_ROLES:
            errors.append("all dynamic-provider review roles must attest")
            reviewers_valid = False

    signed = receipt.get("signedAttestation") is True
    computed = not errors and scenarios_valid and reviewers_valid and signed
    if receipt.get("dynamicLeaseExecutionProved") is not computed:
        errors.append("dynamicLeaseExecutionProved does not equal computed evidence state")
        computed = False
    if receipt.get("productionAuthority") is not False:
        errors.append("dynamic-provider evidence cannot grant production authority")
        computed = False
    return computed, errors


def evaluate_receipt(receipt: dict[str, Any], expected_source_sha: str) -> tuple[bool, list[str]]:
    """Fail closed: structural completeness cannot authenticate provider execution."""
    _, errors = evaluate_structure(receipt, expected_source_sha)
    return False, [*errors, AUTHENTICATION_BLOCKER]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()

    if not is_hex(args.expected_source_sha, 40):
        parser.error("expected source SHA must be 40 lowercase hexadecimal characters")

    if args.receipt is None:
        status = {
            "schema": "hepta.secrets-dynamic-provider-gate.v1",
            "sourceHeadSha": args.expected_source_sha,
            "receiptPresent": False,
            "receiptStructureComplete": False,
            "independentAuthenticationVerified": False,
            "dynamicLeaseExecutionProved": False,
            "errors": ["no real dynamic-provider acceptance receipt supplied"],
        }
        exit_code = 1 if args.require_qualified else 0
    else:
        try:
            receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            status = {
                "schema": "hepta.secrets-dynamic-provider-gate.v1",
                "sourceHeadSha": args.expected_source_sha,
                "receiptPresent": False,
                "receiptStructureComplete": False,
                "independentAuthenticationVerified": False,
                "dynamicLeaseExecutionProved": False,
                "errors": [f"cannot read receipt: {error}"],
            }
            exit_code = 1
        else:
            if not isinstance(receipt, dict):
                structure_complete, structure_errors = False, ["receipt must be a JSON object"]
                qualified, errors = False, ["receipt must be a JSON object"]
            else:
                structure_complete, structure_errors = evaluate_structure(receipt, args.expected_source_sha)
                qualified, errors = evaluate_receipt(receipt, args.expected_source_sha)
            status = {
                "schema": "hepta.secrets-dynamic-provider-gate.v1",
                "sourceHeadSha": args.expected_source_sha,
                "receiptPresent": True,
                "receiptPath": str(args.receipt),
                "receiptStructureComplete": structure_complete,
                "independentAuthenticationVerified": False,
                "dynamicLeaseExecutionProved": qualified,
                "errors": errors,
            }
            exit_code = 1 if structure_errors or (args.require_qualified and not qualified) else 0

    status["validationReasons"] = status["errors"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
