#!/usr/bin/env python3
"""Lane E entrypoint: preserved contract checks plus blob-bound writer audit.

The unmodified base verifier is retained as hepta_lane_e_contract.py. This
entrypoint extends its closed operation/case inventory and replaces only the
writer audit; no contract finding is filtered or converted into a success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import tomllib
from pathlib import Path

import hepta_lane_e_contract as contract

ROOT = Path(__file__).resolve().parents[1]
EXCEPTIONS = "qualification/lane-e/LEGACY_WRITER_EXCEPTIONS.json"
FEATURE = "qualification-legacy-learning-write"
MANIFEST = "codex-rs/hepta-agentd/Cargo.toml"
FORBIDDEN = {
    r"\bDurableLearningJournal\b": "legacy durable journal trait",
    r"\bLedgerEvent\s*::\s*Decision\b": "raw V1 Decision append",
    r"\bLedgerEvent\s*::\s*Outcome\b": "raw V1 Outcome append",
    r"\bLedgerEvent\s*::\s*Credit\b": "raw V1 Credit append",
    r"\bLedgerEvent\s*::\s*Revocation\b": "raw V1 Revocation append",
}
# These additions synchronize the established matrix and trace, not remove
# operations from the required set. The contract library is otherwise intact.
contract.EXPECTED_CASES.update({"OP-05", "OP-06"})
contract.EXPECTED_OPERATIONS["learning.operator"].update({
    "validate_applicability_with_signed_evidence_v2",
    "admit_operator_regularity_with_signed_evidence_v2",
    "verify_tabular_operator_plan_v2", "fit_tabular_operator_verified_v2",
    "verify_world_model_dataset_v2", "fit_transition_model_verified_v2",
})


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def isolated_feature(manifest: str) -> bool:
    """Resolve the default feature closure, including dependency forwarding."""
    try:
        features = tomllib.loads(manifest).get("features", {})
        if not isinstance(features, dict) or FEATURE not in features:
            return False
        todo, seen = ["default"], set()
        while todo:
            value = todo.pop()
            if value in seen:
                continue
            seen.add(value)
            if value == FEATURE or "qualification-legacy-write" in value:
                return False
            edges = features.get(value, [])
            if not isinstance(edges, list) or not all(isinstance(x, str) for x in edges):
                return False
            todo.extend(edges)
        return True
    except (tomllib.TOMLDecodeError, TypeError):
        return False


def verify_product_writer_exclusivity(findings, root: Path = ROOT) -> None:
    try:
        document = json.loads((root / EXCEPTIONS).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        findings.add("legacy_writer_exception_document", str(error))
        return
    if not isinstance(document, dict):
        findings.add("legacy_writer_exception_schema", "writer audit must be an object")
        return
    findings.require(document.get("schema") == "hepta.lane-e-legacy-writer-exceptions.v2",
                     "legacy_writer_exception_schema", "expected blob-bound writer audit v2")
    findings.require(document.get("authorityDelta") == "none", "authority_delta",
                     "writer exceptions cannot grant authority")
    pins = document.get("reviewedBlobs", {})
    records = document.get("exceptions", [])
    if not isinstance(pins, dict) or not isinstance(records, list):
        findings.add("legacy_writer_exception_records", "invalid pins or exception records")
        return
    exceptions = {}
    for record in records:
        if not isinstance(record, dict):
            findings.add("legacy_writer_exception_record", "exception must be an object")
            continue
        path, description = record.get("path"), record.get("finding")
        if (not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts
                or description not in FORBIDDEN.values()
                or record.get("classification") not in
                {"read_only_runstart_bridge", "qualification_feature_only"}
                or not record.get("owner") or not record.get("rationale")):
            findings.add("legacy_writer_exception_record", f"invalid audit record: {record!r}")
            continue
        key = (path, description)
        if key in exceptions:
            findings.add("legacy_writer_exception_duplicate", repr(key))
        exceptions[key] = record
    expected_pins = {path for path, _ in exceptions} | {MANIFEST}
    findings.require(set(pins) == expected_pins, "legacy_writer_exception_pin_set",
                     "audit must pin exactly the excepted source files and feature manifest")
    for relative in sorted(expected_pins):
        try:
            data = (root / relative).read_bytes()
        except OSError:
            findings.add("legacy_writer_exception_source", relative)
            continue
        findings.require(blob_sha(data) == pins.get(relative), "legacy_writer_exception_source_drift",
                         f"source changed; re-audit required: {relative}")
    try:
        feature_ok = isolated_feature((root / MANIFEST).read_text(encoding="utf-8"))
    except OSError:
        feature_ok = False
    seen = set()
    allowed_roots = {"codex-rs/hepta-learning-ledger", "codex-rs/hepta-shadow-qualification"}
    for path in sorted((root / "codex-rs").rglob("*.rs")):
        relative = path.relative_to(root).as_posix()
        if any(relative.startswith(prefix + "/") for prefix in allowed_roots):
            continue
        if "/tests/" in relative or path.name.endswith(("_tests.rs", "_test_support.rs")):
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, description in FORBIDDEN.items():
            if re.search(pattern, text) is None:
                continue
            key = (relative, description)
            record = exceptions.get(key)
            if record is None:
                findings.add("legacy_learning_writer_product_bypass", f"{relative}: {description}")
                continue
            seen.add(key)
            markers = record.get("requiredMarkers")
            findings.require(isinstance(markers, list) and bool(markers)
                             and all(isinstance(x, str) and x in text for x in markers),
                             "legacy_writer_exception_marker", repr(key))
            if record["classification"] == "qualification_feature_only":
                findings.require(feature_ok and f'#[cfg(feature = "{FEATURE}")]' in text,
                                 "legacy_writer_exception_feature", repr(key))
            else:
                forbidden = record.get("forbiddenMarkers")
                findings.require(isinstance(forbidden, list) and bool(forbidden)
                                 and all(isinstance(x, str) and x not in text for x in forbidden),
                                 "legacy_writer_exception_write", repr(key))
    for key in sorted(set(exceptions) - seen):
        findings.add("legacy_writer_exception_stale", repr(key))


def run_self_test():
    findings = contract.Findings()
    findings.items.extend(contract.run_self_test())
    for variant in ("Decision", "Outcome", "Credit", "Revocation"):
        pattern = next(p for p in FORBIDDEN if variant in p)
        for separator in ("::", " :: "):
            findings.require(re.search(pattern, f"LedgerEvent{separator}{variant}(value)") is not None,
                             "self_test_writer_positive", variant)
        findings.require(re.search(pattern, f"LedgerEvent::{variant}Digest(value)") is None,
                         "self_test_writer_negative", variant)
    manifest = '[features]\ndefault=["product"]\nproduct=[]\n' + FEATURE + '=["ledger/qualification-legacy-write"]\n'
    findings.require(isolated_feature(manifest), "self_test_feature_positive", "forwarded feature rejected")
    findings.require(not isolated_feature(manifest.replace('product=[]', 'product=["' + FEATURE + '"]')),
                     "self_test_feature_negative", "transitive default bypass accepted")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        relative = "codex-rs/hepta-agentd/src/product.rs"
        text = '#[cfg(feature = "' + FEATURE + '")]\nfn append_decision() { LedgerEvent::Decision(value); }\n'
        for name, content in ((relative, text), (MANIFEST, manifest)):
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        record = {"path": relative, "finding": "raw V1 Decision append", "owner": "fixture",
                  "rationale": "isolated self-test only", "classification": "qualification_feature_only",
                  "requiredMarkers": ["fn append_decision"]}
        document = {"schema": "hepta.lane-e-legacy-writer-exceptions.v2", "authorityDelta": "none",
                    "reviewedBlobs": {relative: blob_sha(text.encode()), MANIFEST: blob_sha(manifest.encode())},
                    "exceptions": [record]}
        target = root / EXCEPTIONS
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding="utf-8")
        checks = contract.Findings()
        verify_product_writer_exclusivity(checks, root)
        findings.require(not checks.items, "self_test_audit_positive", repr(checks.items))
        (root / relative).write_text(text + "// changed\n", encoding="utf-8")
        checks = contract.Findings()
        verify_product_writer_exclusivity(checks, root)
        findings.require(any(x.code == "legacy_writer_exception_source_drift" for x in checks.items),
                         "self_test_audit_drift", "changed audited blob accepted")
        (root / relative).write_text("fn append_decision() {}\n", encoding="utf-8")
        checks = contract.Findings()
        verify_product_writer_exclusivity(checks, root)
        findings.require(any(x.code == "legacy_writer_exception_stale" for x in checks.items),
                         "self_test_audit_stale", "stale audit accepted")
        (root / relative).write_text(text + "\nLedgerEvent::Outcome(value);\n", encoding="utf-8")
        checks = contract.Findings()
        verify_product_writer_exclusivity(checks, root)
        findings.require(any(x.code == "legacy_learning_writer_product_bypass" for x in checks.items),
                         "self_test_audit_new_writer", "unregistered writer accepted")
    return findings.items


def verify():
    findings = contract.Findings()
    matrix = contract.load_json(contract.MATRIX_PATH, findings)
    trace = contract.load_json(contract.TRACE_PATH, findings)
    modules = contract.verify_matrix(matrix, findings)
    contract.verify_traceability(trace, modules, findings)
    contract.verify_learning_eval_production_boundary(findings)
    verify_product_writer_exclusivity(findings)
    contract.verify_authority_posture(findings)
    contract.verify_workflow(findings)
    for relative in (".github/workflows/learning-operator-p0-materialize.yml",
                     "scripts/learning-operator-p0-materialize.py",
                     ".github/workflows/learning-operator-writer-verifier-fix.yml"):
        findings.require(not (ROOT / relative).exists(), "temporary_workflow_present", relative)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "self-test"), nargs="?", default="verify")
    args = parser.parse_args()
    findings = run_self_test() if args.command == "self-test" else verify().items
    print(json.dumps({"schema": "hepta.lane-e-closure-verification.v1", "command": args.command,
                      "ok": not findings, "findingCount": len(findings),
                      "findings": [x.__dict__ for x in findings]}, indent=2, sort_keys=True))
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
