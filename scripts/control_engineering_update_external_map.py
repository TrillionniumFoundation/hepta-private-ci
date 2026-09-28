#!/usr/bin/env python3
"""Augment the control.engineering map with real external-provider composition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed: {result.stderr[-2000:]}")
    return result.stdout.strip()


def object_id(root: Path, path: str) -> str:
    value = git(root, "rev-parse", f"HEAD:{path}")
    if _SHA1.fullmatch(value) is None:
        raise RuntimeError(f"invalid Git object for {path}: {value!r}")
    return value


def mapped_operation(
    root: Path,
    name: str,
    design: str,
    symbol: str,
    delegated: tuple[tuple[str, str, str], ...],
) -> dict[str, object]:
    source = (
        "tools/hepta-engineering-control/control_engineering_v2/"
        "production_external_composition.py"
    )
    return {
        "operation": name,
        "designOperation": design,
        "nativeSymbol": symbol,
        "sourcePath": source,
        "state": "source_implemented_external_evidence_required",
        "authority": "none",
        "tests": [
            {
                "path": (
                    "tools/hepta-engineering-control/"
                    "test_production_external_convergence.py"
                )
            }
        ],
        "sourcePathExists": True,
        "mappingClass": "owner_native_external_provider",
        "delegatedCallees": [
            {"path": path, "symbol": callee, "role": role}
            for path, callee, role in delegated
        ],
        "sourceBlob": object_id(root, source),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    args = parser.parse_args(argv)
    root = args.repository.resolve()
    path = args.map.resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("module") != "control.engineering":
        raise ValueError("unexpected implementation map")

    operations = value.get("operations")
    if not isinstance(operations, list):
        raise ValueError("implementation operations missing")
    by_name = {
        row.get("operation"): row
        for row in operations
        if isinstance(row, dict) and isinstance(row.get("operation"), str)
    }
    definitions = (
        mapped_operation(
            root,
            "verify_external_production_controls",
            "real_distributed_fence_audit_and_key_custody_composition",
            "ProductionExternalControlClient.verify_controls",
            (
                (
                    "tools/hepta-engineering-control/control_engineering_v2/"
                    "external_runtime.py",
                    "ExternalReceiptClient.invoke",
                    "certificate_pinned_provider_transport",
                ),
                (
                    "tools/hepta-engineering-control/control_engineering_v2/"
                    "external_controls.py",
                    "verify_production_controls",
                    "signed_receipt_verifier",
                ),
            ),
        ),
        mapped_operation(
            root,
            "observe_external_completion",
            "non_fixture_independent_completion_observation",
            "ProductionExternalControlClient.observe_completion",
            (
                (
                    "tools/hepta-engineering-control/control_engineering_v2/"
                    "product_runtime.py",
                    "EngineeringControlProduct.observe_completion",
                    "durable_product_owner",
                ),
            ),
        ),
        mapped_operation(
            root,
            "observe_external_integration_terminal",
            "non_fixture_integration_terminal_observation",
            "ProductionExternalControlClient.observe_terminal",
            (
                (
                    "tools/hepta-engineering-control/control_engineering_v2/"
                    "product_runtime.py",
                    "EngineeringControlProduct.reconcile_integration",
                    "durable_product_owner",
                ),
            ),
        ),
    )
    for row in definitions:
        by_name[row["operation"]] = row
    value["operations"] = [by_name[name] for name in sorted(by_name)]

    product_callers = value.get("productCallers")
    if not isinstance(product_callers, list):
        product_callers = []
    callers = {
        row.get("sourcePath"): row
        for row in product_callers
        if isinstance(row, dict) and isinstance(row.get("sourcePath"), str)
    }
    source = (
        "tools/hepta-engineering-control/control_engineering_v2/"
        "production_external_composition.py"
    )
    callers[source] = {
        "sourcePath": source,
        "nativeSymbol": "ProductionExternalControlClient",
        "state": (
            "real_provider_composition_requires_external_signed_receipts_"
            "and_grants_no_authority"
        ),
    }
    value["productCallers"] = [callers[name] for name in sorted(callers)]

    source_objects = value.get("sourceObjects")
    if not isinstance(source_objects, list):
        source_objects = []
    objects = {
        row.get("path"): row
        for row in source_objects
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    for current in (
        source,
        "tools/hepta-engineering-control/test_production_external_convergence.py",
    ):
        objects[current] = {"path": current, "object": object_id(root, current)}
    value["sourceObjects"] = [objects[name] for name in sorted(objects)]

    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
