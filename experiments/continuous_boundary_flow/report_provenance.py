"""Validate report provenance without relaxing the frozen scientific auditor.

A derived view is accepted only with exact-byte derivation validation, the
preserved original strict rejection, and a new passing frozen-auditor receipt.
Engineering stays bound to the original manifest; it is never relabeled.
"""

from decimal import Decimal
import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    def reject(value):
        raise ValueError(f"Nonfinite provenance JSON in {path}: {value}")

    return json.loads(Path(path).read_text(), parse_constant=reject)


def validate_report_provenance(
    run_dir, audit, engineering, original_run=None, audit_receipts=None
):
    """Return qualified audit status and a complete reporting provenance ledger."""
    root = Path(run_dir).resolve()
    manifest_hash = digest(root / "manifest.json")
    require(
        audit.get("integrity_passed") is True
        and audit.get("manifest_sha256") == manifest_hash,
        "Report requires a passing audit bound to its exact input manifest",
    )
    derivation_path = root / "DERIVATION.json"
    if not derivation_path.is_file():
        require(
            (original_run is None or Path(original_run).resolve() == root)
            and audit_receipts is None,
            "Original-only audit cannot accept unrelated derivation arguments",
        )
        require(
            engineering.get("manifest_sha256") == manifest_hash,
            "Engineering study belongs to another original manifest",
        )
        return {
            "audit_mode": "strict_original",
            "original_run_directory": str(root),
            "audited_input_directory": str(root),
            "original_manifest_sha256": manifest_hash,
            "audited_manifest_sha256": manifest_hash,
            "original_strict_rejection": None,
            "correction_count": 0,
            "maximum_absolute_cpu_correction_seconds": 0.0,
            "maximum_absolute_cpu_correction_seconds_decimal": "0",
            "total_cpu_correction_seconds_decimal": "0",
            "primary_task_records_byte_identical": True,
            "inputs_sha256": {"report_provenance_tool": digest(__file__)},
        }

    require(
        original_run is not None and audit_receipts is not None,
        "Derived audit reporting requires explicit original-run and audit-receipts paths",
    )
    original, receipts = Path(original_run).resolve(), Path(audit_receipts).resolve()
    require(original != root, "Derived view must be distinct from original run")
    from . import cost_audit_view

    validation = cost_audit_view.validate_derivation(original, root)
    derivation = read_json(derivation_path)
    paths = {
        "derivation": derivation_path,
        "original_manifest": original / "manifest.json",
        "original_costs": original / "costs.jsonl",
        "original_strict_audit_result": receipts / "ORIGINAL_AUDIT_RESULT.json",
        "derived_audit_result_receipt": receipts / "DERIVED_AUDIT_RESULT.json",
        "derivation_validation_receipt": receipts / "DERIVATION_VALIDATION.json",
        "cost_view_status": receipts / "COST_VIEW_STATUS.json",
        "cost_derivation_helper": Path(cost_audit_view.__file__),
        "report_provenance_tool": Path(__file__),
    }
    hashes = {key: digest(path) for key, path in paths.items()}
    require(
        hashes["original_strict_audit_result"]
        == derivation["original_audit_result_sha256"],
        "Original strict-rejection receipt digest differs from derivation",
    )
    rejected = read_json(paths["original_strict_audit_result"])
    require(
        rejected.get("integrity_passed") is False
        and rejected.get("exception_type") == "AuditError"
        and rejected.get("error") == "completed_child_cpu_seconds: negative value",
        "Original rejection was not the explicitly allowed strict cost-roundoff rejection",
    )
    require(
        hashes["derived_audit_result_receipt"]
        == derivation["derived_audit_result_sha256"]
        == digest(root / "AUDIT.json"),
        "Derived audit receipt and input-view audit differ",
    )
    require(
        read_json(paths["derived_audit_result_receipt"]) == audit,
        "Loaded audit differs from the preserved derived-audit receipt",
    )
    status = read_json(paths["cost_view_status"])
    require(
        status.get("status") == "original_rejected_derived_passed"
        and status.get("view_created") is True
        and status.get("derivation_sha256") == hashes["derivation"]
        and status.get("derived_audit_result_sha256")
        == derivation["derived_audit_result_sha256"],
        "Completed cost-view status is not bound to this derivation and audit",
    )
    require(
        read_json(paths["derivation_validation_receipt"]) == validation
        and all(status.get(key) == value for key, value in validation.items()),
        "Stored derivation validation differs from fresh byte-level validation",
    )
    require(
        engineering.get("manifest_sha256")
        == derivation["original_manifest_sha256"]
        == hashes["original_manifest"],
        "Engineering study is not bound to the unchanged original manifest",
    )
    amounts = [
        Decimal(row["correction_seconds_decimal"]) for row in derivation["corrections"]
    ]
    maximum, total = max(amounts), sum(amounts, Decimal(0))
    return {
        "audit_mode": "explicit_cost_roundoff_view",
        "original_run_directory": str(original),
        "audited_input_directory": str(root),
        "audit_receipts_directory": str(receipts),
        "original_manifest_sha256": derivation["original_manifest_sha256"],
        "audited_manifest_sha256": derivation["derived_manifest_sha256"],
        "original_strict_rejection": {
            **rejected,
            "artifact": str(paths["original_strict_audit_result"]),
            "sha256": hashes["original_strict_audit_result"],
        },
        "correction_count": len(amounts),
        "maximum_absolute_cpu_correction_seconds": float(maximum),
        "maximum_absolute_cpu_correction_seconds_decimal": str(maximum),
        "total_cpu_correction_seconds_decimal": str(total),
        "corrections": derivation["corrections"],
        "policy": derivation["policy"],
        "primary_task_records_byte_identical": True,
        "scientific_audit_source_unchanged": True,
        "engineering_bound_to_original_manifest": True,
        "validation": validation,
        "inputs_sha256": hashes,
        "scope": "Only whitelisted negative child-CPU cost tokens and the manifest cost digest changed. Primary/task records, protocol, seeds, profiles, source seal and historical costs are byte-identical. The passing verdict applies to the explicit derived view; the original strict rejection is retained.",
    }


def audit_opening(summary):
    provenance = summary["audit_provenance"]
    if provenance["audit_mode"] == "strict_original":
        return "The independent strict audit passed on the original inputs."
    return (
        "**The unchanged scientific auditor passed the explicit cost-roundoff-normalized input view. "
        "The original strict audit rejected the original ledger at its child-CPU nonnegativity check.** "
        f"Exactly {provenance['correction_count']} negative `completed_child_cpu_seconds` tokens in the allowed [-1e-12, 0) second range became `0.0`; "
        f"the maximum absolute correction was {provenance['maximum_absolute_cpu_correction_seconds_decimal']} seconds "
        f"and their sum was {provenance['total_cpu_correction_seconds_decimal']} seconds. "
        "Fresh byte-level validation verified that only those cost tokens and the manifest's cost digest changed. "
        "Primary/task records, model profiles, protocol, seeds, scientific source and historical costs are unchanged. "
        "The original rejection and both manifest identities are preserved; engineering remains bound to the original manifest."
    )
