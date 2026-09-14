"""Derive navigation indexes from canonical module/domain/contract registries.

This module changes no owner registry, capability, production claim or source.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path, PurePosixPath
import re

BINDINGS = "docs/modules/SOURCE_BINDINGS.json"


def load_registry(root: Path, path: str) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    return json.loads(
        (root / path).read_text(encoding="utf-8"), object_pairs_hook=unique
    )


def project_indexes(
    root: Path, modules: list[dict], index: dict
) -> tuple[dict, dict, str]:
    """Rebuild derived rows, including module additions/removals, before writing."""
    bindings = load_registry(root, BINDINGS)
    contracts = load_registry(root, "docs/contracts/CONTRACTS.json")["contracts"]
    protocols = load_registry(root, "docs/contracts/PROTOCOL_SCHEMAS.json")["protocols"]
    domains = load_registry(root, "docs/data/DATA_AUTHORITY.json")["domains"]
    packages = load_registry(root, "docs/delivery/WORK_PACKAGES.json")["packages"]
    threats = load_registry(root, "docs/security/THREAT_MODEL.json")["threats"]
    index = copy.deepcopy(index)
    old_docs = {row["module"]: row for row in index["modules"]}
    old_bindings = {row["module"]: row for row in bindings["bindings"]}
    if len(old_docs) != len(index["modules"]) or len(old_bindings) != len(
        bindings["bindings"]
    ):
        raise ValueError("duplicate projection row")
    if not modules or len({module["id"] for module in modules}) != len(modules):
        raise ValueError("module coverage mismatch")
    docs, sources, guides = [], [], []
    for module in modules:
        mid = module["id"]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,127}", mid):
            raise ValueError("invalid module identity")
        expected_path = f"docs/modules/{mid}/TECHNICAL.md"
        if module["technicalDocument"] != expected_path:
            raise ValueError("technical document path mismatch")
        declared = [binding["path"] for binding in module["rootBindings"]]
        for relative in declared:
            path = PurePosixPath(relative)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or not (root / relative).resolve().is_relative_to(root.resolve())
            ):
                raise ValueError("source root outside repository")
        existing = [path for path in declared if (root / path).exists()]
        present = module["source_root_present"]
        production = module["production_implementation"]
        if type(present) is not bool or type(production) is not bool:
            raise ValueError("module status facts must be booleans")
        if present != bool(existing) or production and not present:
            raise ValueError("canonical module source-root fact disagrees with source")
        common = {
            key: module[key]
            for key in (
                "sourceStatus",
                "source_root_present",
                "production_implementation",
                "bootstrapWorkPackage",
            )
        }
        source = copy.deepcopy(old_bindings.get(mid, {"module": mid}))
        source.update(common)
        source.update(
            lifecycle=module["lifecycle"],
            declaredRoots=declared,
            existingDeclaredRoots=existing,
            missingDeclaredRoots=[path for path in declared if path not in existing],
            sourceEvidenceRoots=module["sourceEvidenceRoots"],
            technicalDocument=expected_path,
        )
        source.setdefault(
            "interpretation", "source_navigation_only_not_activation_or_acceptance"
        )
        sources.append(source)
        row = copy.deepcopy(old_docs.get(mid, {"module": mid}))
        row.update(common)
        row["path"] = expected_path
        produced = sorted(item["id"] for item in contracts if item["producer"] == mid)
        consumed = sorted(item["id"] for item in contracts if mid in item["consumers"])
        touched = set(produced + consumed)
        row.update(
            producedContracts=produced,
            consumedContracts=consumed,
            protocols=sorted(
                item["id"] for item in protocols if item.get("contractId") in touched
            ),
            ownedDomains=sorted(
                item["id"] for item in domains if item["authoritativeWriter"] == mid
            ),
            readDomains=sorted(
                item["id"] for item in domains if mid in item.get("readers", [])
            ),
            workPackages=sorted(
                item["id"]
                for item in packages
                if item["module"] == mid or mid in item.get("coOwnerModules", [])
            ),
            threats=sorted(item["id"] for item in threats if item["owner"] == mid),
        )
        docs.append(row)
        guides.append(
            f"- [`{mid}`]({mid}/TECHNICAL.md) — `{module['sourceStatus']}`, bootstrap `{module['bootstrapWorkPackage']}`."
        )
    readme = (root / "docs/modules/README.md").read_text(encoding="utf-8")
    readme, count = re.subn(
        r"(?ms)(^## Guides\n).*?(?=^## |\Z)",
        lambda match: match[1] + "\n" + "\n".join(guides) + "\n\n",
        readme,
    )
    if count != 1:
        raise ValueError("README Guides section missing or ambiguous")
    index["modules"] = docs
    bindings["bindings"] = sources
    return index, bindings, readme
