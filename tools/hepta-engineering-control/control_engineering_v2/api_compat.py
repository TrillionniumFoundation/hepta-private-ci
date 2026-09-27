"""Check the committed additive public API contract for control.engineering."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("public_api_contract_object_required")
    return value


def verify_public_api(contract_path: str | Path) -> dict[str, object]:
    contract = _load(Path(contract_path))
    if contract.get("schema") != "hepta.control-engineering-public-api.v1":
        raise ValueError("public_api_contract_schema")
    if contract.get("module") != "control.engineering":
        raise ValueError("public_api_contract_module")
    required = contract.get("requiredExports")
    forbidden = contract.get("forbiddenExports")
    if (
        not isinstance(required, list)
        or not required
        or any(not isinstance(item, str) or not item for item in required)
        or len(required) != len(set(required))
        or not isinstance(forbidden, list)
        or any(not isinstance(item, str) or not item for item in forbidden)
        or len(forbidden) != len(set(forbidden))
    ):
        raise ValueError("public_api_contract_exports")

    package = importlib.import_module("control_engineering_v2")
    exported = getattr(package, "__all__", None)
    if (
        not isinstance(exported, list)
        or any(not isinstance(item, str) or not item for item in exported)
        or len(exported) != len(set(exported))
    ):
        raise ValueError("public_api_package_exports")
    exported_set = set(exported)
    missing = sorted(set(required) - exported_set)
    present_forbidden = sorted(set(forbidden) & exported_set)
    unresolved = sorted(item for item in exported if not hasattr(package, item))
    allow_additional = contract.get("allowAdditionalExports") is True
    additional = sorted(exported_set - set(required))
    if missing:
        raise ValueError("public_api_missing:" + ",".join(missing))
    if present_forbidden:
        raise ValueError("public_api_forbidden:" + ",".join(present_forbidden))
    if unresolved:
        raise ValueError("public_api_unresolved:" + ",".join(unresolved))
    if additional and not allow_additional:
        raise ValueError("public_api_additional:" + ",".join(additional))
    canonical = json.dumps(
        {
            "requiredExports": sorted(required),
            "forbiddenExports": sorted(forbidden),
            "observedExports": sorted(exported),
            "allowAdditionalExports": allow_additional,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": "hepta.control-engineering-public-api-check.v1",
        "module": "control.engineering",
        "requiredExports": len(required),
        "observedExports": len(exported),
        "additionalExports": additional,
        "apiDigest": hashlib.sha256(canonical).hexdigest(),
        "compatible": True,
        "authorityGranted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = verify_public_api(args.contract)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
