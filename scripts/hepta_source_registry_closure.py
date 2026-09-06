#!/usr/bin/env python3
"""Normalize and verify source-binding closure for the bounded V8 candidate."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULES_PATH = ROOT / "docs" / "modules" / "MODULES.json"
BINDINGS_PATH = ROOT / "docs" / "modules" / "SOURCE_BINDINGS.json"
WORK_PACKAGES_PATH = ROOT / "docs" / "delivery" / "WORK_PACKAGES.json"
READINESS_GAPS_PATH = ROOT / "docs" / "readiness" / "GAPS.json"
QUALIFICATION_MANIFEST_PATH = ROOT / "qualification" / "gap-closure" / "MANIFEST.json"
AUDIT_PATH = ROOT / "qualification" / "gap-closure" / "PLAN_AUDIT.json"

SOURCE_ROOTS: dict[str, tuple[str, ...]] = {
    "control.engineering": ("tools/hepta-engineering-control",),
    "inference.worker": ("codex-rs/hepta-infer-worker-host",),
    "intuition.policy": ("codex-rs/hepta-intuition",),
    "learning.artifacts": ("codex-rs/hepta-learning-artifacts",),
    "learning.eval": ("codex-rs/hepta-intelligence-eval",),
    "learning.ledger": ("codex-rs/hepta-learning-ledger",),
    "learning.operator": ("codex-rs/hepta-bellman-operator",),
    "learning.plasticity": ("codex-rs/hepta-plasticity",),
    "neuron.runtime": ("codex-rs/hepta-neuron",),
    "objective.compiler": ("codex-rs/hepta-objective",),
    "prompt.optimizer": ("codex-rs/hepta-prompt-optimizer",),
    "prompt.registry": ("codex-rs/hepta-prompt-registry",),
    "ui.control": ("apps/hepta-control-ui",),
    "utility.ndu": ("codex-rs/hepta-ndu",),
}

SOURCE_STATUS = "existing_bound"
SOURCE_INTERPRETATION = "declared_root_is_materialized_but_activation_acceptance_promotion_and_release_remain_separate"
SECTION_TWO_HEADING = "## 2. Source binding and implementation status"
SECTION_THREE_HEADING = "## 3. Boundary, responsibilities and non-goals"
SOURCE_RECEIPT_HEADING = "## 17. Source implementation receipt"


class RegistryClosureError(RuntimeError):
    """Raised when a canonical registry cannot be transformed safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryClosureError(
            f"cannot parse {path.relative_to(ROOT)}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise RegistryClosureError(
            f"{path.relative_to(ROOT)} must contain a JSON object"
        )
    return value


def _records(document: dict[str, Any], key: str, path: Path) -> list[dict[str, Any]]:
    value = document.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RegistryClosureError(
            f"{path.relative_to(ROOT)}.{key} must be a list of objects"
        )
    return value


def _index(
    records: list[dict[str, Any]],
    identity_key: str,
    source_name: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        identity = record.get(identity_key)
        if not isinstance(identity, str) or not identity:
            raise RegistryClosureError(
                f"{source_name} contains a record without {identity_key}"
            )
        if identity in indexed:
            raise RegistryClosureError(
                f"duplicate {identity_key} in {source_name}: {identity}"
            )
        indexed[identity] = record
    return indexed


def _declared_roots(module: dict[str, Any]) -> tuple[str, ...]:
    bindings = module.get("rootBindings")
    if not isinstance(bindings, list):
        raise RegistryClosureError(
            f"module {module.get('id')} has no rootBindings list"
        )
    roots: list[str] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            raise RegistryClosureError(
                f"module {module.get('id')} has invalid root binding"
            )
        path = binding.get("path")
        mode = binding.get("mode")
        if not isinstance(path, str) or not path:
            raise RegistryClosureError(
                f"module {module.get('id')} has invalid root path"
            )
        if mode != "exclusive":
            raise RegistryClosureError(
                f"module {module.get('id')} root {path} is not exclusive"
            )
        roots.append(path)
    return tuple(roots)


def _write_json(
    path: Path,
    document: dict[str, Any],
    *,
    compact: bool = False,
) -> bool:
    if compact:
        rendered = (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
    else:
        rendered = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def _technical_section(module_id: str, roots: tuple[str, ...]) -> str:
    root_lines = "\n".join(f"- `{root}`" for root in roots)
    return f"""{SECTION_TWO_HEADING}

Declared exclusive target roots:

{root_lines}

Existing declared roots at this exact source snapshot:

{root_lines}

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`{SOURCE_STATUS}` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `{module_id}`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.
"""


def _source_receipt(module_id: str, roots: tuple[str, ...], bootstrap: str) -> str:
    root_lines = "\n".join(f"- `{root}`" for root in roots)
    return f"""{SOURCE_RECEIPT_HEADING}

The bootstrap source-location obligation for `{module_id}` is implemented by work package `{bootstrap}` in:

{root_lines}

The source candidate is checked by `.github/workflows/hepta-gap-closure.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
"""


def _normalize_technical_document(
    module_id: str,
    path: Path,
    roots: tuple[str, ...],
    bootstrap: str,
) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RegistryClosureError(
            f"cannot read {path.relative_to(ROOT)}: {error}"
        ) from error

    status_pattern = re.compile(r"(?m)^\*\*Source status:\*\* `[^`]+`$")
    if not status_pattern.search(text):
        raise RegistryClosureError(
            f"source status metadata is missing in {path.relative_to(ROOT)}"
        )
    text = status_pattern.sub(f"**Source status:** `{SOURCE_STATUS}`", text, count=1)

    section_pattern = re.compile(
        rf"(?ms)^{re.escape(SECTION_TWO_HEADING)}\n.*?(?=^{re.escape(SECTION_THREE_HEADING)}\n)"
    )
    if not section_pattern.search(text):
        raise RegistryClosureError(
            f"source binding section is missing in {path.relative_to(ROOT)}"
        )
    text = section_pattern.sub(
        _technical_section(module_id, roots) + "\n", text, count=1
    )

    receipt_pattern = re.compile(rf"(?ms)\n{re.escape(SOURCE_RECEIPT_HEADING)}\n.*\Z")
    receipt = "\n" + _source_receipt(module_id, roots, bootstrap)
    if receipt_pattern.search(text):
        text = receipt_pattern.sub(receipt, text, count=1)
    else:
        text = text.rstrip() + "\n" + receipt

    if not text.endswith("\n"):
        text += "\n"
    current = path.read_text(encoding="utf-8")
    if current == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def _status_counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(record.get(field, "missing")) for record in records)
    return dict(sorted(counts.items()))


def _build_audit(
    modules: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    packages: list[dict[str, Any]],
    readiness_gaps: list[dict[str, Any]],
    bootstrap_packages: dict[str, str],
) -> dict[str, Any]:
    unresolved_bindings: list[dict[str, Any]] = []
    for binding in bindings:
        missing = binding.get("missingDeclaredRoots")
        status = binding.get("sourceStatus")
        if (isinstance(missing, list) and missing) or status in {
            "target_unmaterialized",
            "target_partially_materialized",
        }:
            unresolved_bindings.append(
                {
                    "module": binding.get("module"),
                    "sourceStatus": status,
                    "missingDeclaredRoots": missing
                    if isinstance(missing, list)
                    else [],
                    "bootstrapWorkPackage": binding.get("bootstrapWorkPackage"),
                }
            )
    unresolved_bindings.sort(key=lambda item: str(item.get("module")))

    unresolved_packages = [
        {
            "id": package.get("id"),
            "module": package.get("module"),
            "state": package.get("state"),
            "qualificationProfile": package.get("qualificationProfile"),
        }
        for package in packages
        if package.get("state") != "source_implemented"
    ]
    unresolved_packages.sort(key=lambda item: str(item.get("id")))

    manifest = _load_json(QUALIFICATION_MANIFEST_PATH)
    return {
        "schema": "hepta.v8-gap-closure-plan-audit.v1",
        "schemaVersion": 1,
        "planId": "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN",
        "planVersion": "8.0.0",
        "candidateIdentity": "resolved_by_external_exact_candidate_receipt",
        "implementedModuleCount": len(SOURCE_ROOTS),
        "implementedModules": [
            {
                "module": module_id,
                "sourceRoots": list(SOURCE_ROOTS[module_id]),
                "bootstrapWorkPackage": bootstrap_packages[module_id],
            }
            for module_id in sorted(SOURCE_ROOTS)
        ],
        "moduleSourceStatusCounts": _status_counts(modules, "sourceStatus"),
        "sourceBindingStatusCounts": _status_counts(bindings, "sourceStatus"),
        "unresolvedSourceBindingCount": len(unresolved_bindings),
        "unresolvedSourceBindings": unresolved_bindings,
        "workPackageStateCounts": _status_counts(packages, "state"),
        "unresolvedWorkPackageCount": len(unresolved_packages),
        "unresolvedWorkPackages": unresolved_packages,
        "readinessGapStateCounts": _status_counts(readiness_gaps, "state"),
        "documentationGapsClosed": all(
            gap.get("state") == "closed_specification" for gap in readiness_gaps
        ),
        "externalEvidence": manifest.get("external_evidence", {}),
        "authority": manifest.get("authority", {}),
        "interpretation": (
            "source binding closure is distinct from activation, independent acceptance, "
            "longitudinal efficacy, physical safety, promotion and release"
        ),
    }


def _canonical_documents() -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    modules_document = _load_json(MODULES_PATH)
    modules = _records(modules_document, "modules", MODULES_PATH)
    bindings_document = _load_json(BINDINGS_PATH)
    bindings = _records(bindings_document, "bindings", BINDINGS_PATH)
    packages_document = _load_json(WORK_PACKAGES_PATH)
    packages = _records(packages_document, "packages", WORK_PACKAGES_PATH)
    readiness_document = _load_json(READINESS_GAPS_PATH)
    readiness_gaps = _records(readiness_document, "gaps", READINESS_GAPS_PATH)
    return (
        modules_document,
        modules,
        bindings_document,
        bindings,
        packages_document,
        packages,
        readiness_gaps,
    )


def normalize() -> bool:
    (
        modules_document,
        modules,
        bindings_document,
        bindings,
        packages_document,
        packages,
        readiness_gaps,
    ) = _canonical_documents()
    modules_by_id = _index(modules, "id", "MODULES.json")
    bindings_by_id = _index(bindings, "module", "SOURCE_BINDINGS.json")
    packages_by_id = _index(packages, "id", "WORK_PACKAGES.json")

    bootstrap_packages: dict[str, str] = {}
    technical_paths: list[Path] = []
    for module_id, expected_roots in SOURCE_ROOTS.items():
        module = modules_by_id.get(module_id)
        binding = bindings_by_id.get(module_id)
        if module is None or binding is None:
            raise RegistryClosureError(
                f"canonical module or binding is missing: {module_id}"
            )
        declared = _declared_roots(module)
        if declared != expected_roots:
            raise RegistryClosureError(
                f"declared roots differ for {module_id}: {declared!r} != {expected_roots!r}"
            )
        binding_declared = binding.get("declaredRoots")
        if binding_declared != list(expected_roots):
            raise RegistryClosureError(
                f"source binding roots differ for {module_id}: {binding_declared!r}"
            )
        bootstrap = module.get("bootstrapWorkPackage")
        if not isinstance(bootstrap, str) or not bootstrap:
            raise RegistryClosureError(f"bootstrap package is missing for {module_id}")
        if binding.get("bootstrapWorkPackage") != bootstrap:
            raise RegistryClosureError(f"bootstrap package mismatch for {module_id}")
        package = packages_by_id.get(bootstrap)
        if package is None:
            raise RegistryClosureError(
                f"bootstrap package {bootstrap} is not registered for {module_id}"
            )
        bootstrap_packages[module_id] = bootstrap

        for root in expected_roots:
            if not (ROOT / root).exists():
                raise RegistryClosureError(
                    f"materialized source root is missing: {root}"
                )

        module["sourceStatus"] = SOURCE_STATUS
        module["sourceEvidenceRoots"] = list(expected_roots)
        module["missingDeclaredRoots"] = []

        binding["sourceStatus"] = SOURCE_STATUS
        binding["existingDeclaredRoots"] = list(expected_roots)
        binding["sourceEvidenceRoots"] = list(expected_roots)
        binding["missingDeclaredRoots"] = []
        binding["interpretation"] = SOURCE_INTERPRETATION

        package["state"] = "source_implemented"

        technical_document = module.get("technicalDocument")
        if not isinstance(technical_document, str) or not technical_document:
            raise RegistryClosureError(f"technical document is missing for {module_id}")
        technical_path = ROOT / technical_document
        if _normalize_technical_document(
            module_id,
            technical_path,
            expected_roots,
            bootstrap,
        ):
            technical_paths.append(technical_path)

    changed_paths: list[Path] = []
    if _write_json(MODULES_PATH, modules_document):
        changed_paths.append(MODULES_PATH)
    if _write_json(BINDINGS_PATH, bindings_document):
        changed_paths.append(BINDINGS_PATH)
    if _write_json(WORK_PACKAGES_PATH, packages_document):
        changed_paths.append(WORK_PACKAGES_PATH)

    audit = _build_audit(
        modules,
        bindings,
        packages,
        readiness_gaps,
        bootstrap_packages,
    )
    if _write_json(AUDIT_PATH, audit, compact=True):
        changed_paths.append(AUDIT_PATH)

    for path in technical_paths:
        if path not in changed_paths:
            changed_paths.append(path)

    return bool(changed_paths)


def verify() -> list[str]:
    failures: list[str] = []
    try:
        (
            _modules_document,
            modules,
            _bindings_document,
            bindings,
            _packages_document,
            packages,
            readiness_gaps,
        ) = _canonical_documents()
        modules_by_id = _index(modules, "id", "MODULES.json")
        bindings_by_id = _index(bindings, "module", "SOURCE_BINDINGS.json")
        packages_by_id = _index(packages, "id", "WORK_PACKAGES.json")
    except RegistryClosureError as error:
        return [str(error)]

    bootstrap_packages: dict[str, str] = {}
    for module_id, expected_roots in SOURCE_ROOTS.items():
        module = modules_by_id.get(module_id)
        binding = bindings_by_id.get(module_id)
        if module is None:
            failures.append(f"module registry entry is missing: {module_id}")
            continue
        if binding is None:
            failures.append(f"source binding entry is missing: {module_id}")
            continue
        try:
            declared = _declared_roots(module)
        except RegistryClosureError as error:
            failures.append(str(error))
            continue
        if declared != expected_roots:
            failures.append(f"declared source roots are incorrect: {module_id}")
        if module.get("sourceStatus") != SOURCE_STATUS:
            failures.append(f"module source status is not closed: {module_id}")
        if module.get("sourceEvidenceRoots") != list(expected_roots):
            failures.append(f"module source evidence roots are incorrect: {module_id}")
        if module.get("missingDeclaredRoots") != []:
            failures.append(f"module still declares missing source roots: {module_id}")

        if binding.get("sourceStatus") != SOURCE_STATUS:
            failures.append(f"binding source status is not closed: {module_id}")
        if binding.get("declaredRoots") != list(expected_roots):
            failures.append(f"binding declared roots are incorrect: {module_id}")
        if binding.get("existingDeclaredRoots") != list(expected_roots):
            failures.append(f"binding existing roots are incorrect: {module_id}")
        if binding.get("sourceEvidenceRoots") != list(expected_roots):
            failures.append(f"binding evidence roots are incorrect: {module_id}")
        if binding.get("missingDeclaredRoots") != []:
            failures.append(f"binding still declares missing roots: {module_id}")
        if binding.get("interpretation") != SOURCE_INTERPRETATION:
            failures.append(f"binding interpretation is incorrect: {module_id}")

        bootstrap = module.get("bootstrapWorkPackage")
        if not isinstance(bootstrap, str):
            failures.append(f"bootstrap package is invalid: {module_id}")
            continue
        bootstrap_packages[module_id] = bootstrap
        package = packages_by_id.get(bootstrap)
        if package is None or package.get("state") != "source_implemented":
            failures.append(f"bootstrap source package is not implemented: {bootstrap}")

        technical_document = module.get("technicalDocument")
        if not isinstance(technical_document, str):
            failures.append(f"technical document is invalid: {module_id}")
            continue
        path = ROOT / technical_document
        if not path.is_file():
            failures.append(f"technical document is missing: {technical_document}")
            continue
        text = path.read_text(encoding="utf-8")
        if f"**Source status:** `{SOURCE_STATUS}`" not in text:
            failures.append(f"technical source status is stale: {module_id}")
        if SOURCE_RECEIPT_HEADING not in text:
            failures.append(f"technical source receipt is missing: {module_id}")
        if "Declared roots not yet present:\n\nNone." not in text:
            failures.append(f"technical missing-root section is stale: {module_id}")

    if not AUDIT_PATH.is_file():
        failures.append("qualification/gap-closure/PLAN_AUDIT.json is missing")
    elif len(bootstrap_packages) == len(SOURCE_ROOTS):
        try:
            expected_audit = _build_audit(
                modules,
                bindings,
                packages,
                readiness_gaps,
                bootstrap_packages,
            )
            actual_audit = _load_json(AUDIT_PATH)
        except RegistryClosureError as error:
            failures.append(str(error))
        else:
            if actual_audit != expected_audit:
                failures.append("PLAN_AUDIT.json is stale")

    return failures
