#!/usr/bin/env python3
"""Closed-world validator for Hepta module source bindings and technical guides."""

try:
    from scripts.hepta_metadata import AUTHORITY_KEYS
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    from hepta_metadata import AUTHORITY_KEYS

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADINGS = [
    "## 1. Identity, mission and ownership",
    "## 2. Source binding and implementation status",
    "## 3. Boundary, responsibilities and non-goals",
    "## 4. Internal architecture and component decomposition",
    "## 5. Contracts, ports and compatibility",
    "## 6. Data authority, persistence and migrations",
    "## 7. Runtime, concurrency and transaction model",
    "## 8. Failure semantics, recovery and rollback",
    "## 9. Security, privacy and threat controls",
    "## 10. Performance, capacity and hot-path policy",
    "## 11. Observability and operations",
    "## 12. Verification and qualification",
    "## 13. Implementation sequence and work packages",
    "## 14. Activation, compatibility and retirement",
    "## 15. Definition of module completion",
    "## 17. Source implementation receipt",
]
ALLOWED_STATUS = {
    "existing_bound",
    "existing_partially_bound",
    "existing_legacy_aggregate",
    "existing_declared_unbound",
    "target_materialized",
    "target_partially_materialized",
    "target_unmaterialized",
    "external_with_adapter_target",
}
STATUS_FACT_FIELDS = ("source_root_present", "production_implementation")


class DuplicateKey(ValueError):
    pass


def pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise DuplicateKey(k)
        out[k] = v
    return out


def die(msg):
    raise SystemExit("FAIL_HEPTA_MODULE_DOCS: " + msg)


def need(ok, msg):
    if not ok:
        die(msg)


def load(path):
    p = ROOT / path
    try:
        return json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        die(f"{path}: {exc}")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def false_authority(value, label):
    need(
        isinstance(value, dict) and set(value) == set(AUTHORITY_KEYS),
        label + " authority key closure",
    )
    need(
        all(type(flag) is bool and flag is False for flag in value.values()),
        label + " positive authority or invalid authority type",
    )


def verify_local_links(path, text):
    """Keep native-source, test, operating-guide and shared-rule links usable.

    This checks navigation, not source compilation or semantic completeness.
    """
    for target in re.findall(r"\]\(([^\s)]+)\)", text):
        if "://" in target or target.startswith("mailto:"):
            continue
        relative, _, anchor = target.partition("#")
        destination = (path.parent / relative).resolve() if relative else path
        need(destination.is_relative_to(ROOT), str(path) + " link outside repository")
        need(destination.is_file(), str(path) + " missing link " + target)
        if anchor and destination.suffix == ".md":
            headings = re.findall(r"^#+ (.+)$", destination.read_text(), re.M)
            anchors = {
                re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
                for heading in headings
            }
            need(anchor in anchors, str(path) + " missing anchor " + target)


def refresh_indexes(check):
    """Refresh generated module projections and document presentation metrics.

    MODULES.json owns duplicated module status/bootstrap/path facts. Contract,
    protocol, domain, work-package and threat lists are derived from their
    canonical registries. SOURCE_BINDINGS keeps only its genuinely independent
    evidence/lifecycle/interpretation fields as human-maintained data.
    """
    modules = load("docs/modules/MODULES.json")
    bindings = load("docs/modules/SOURCE_BINDINGS.json")
    docs = load("docs/modules/MODULE_DOCS.json")
    contracts = load("docs/contracts/CONTRACTS.json")["contracts"]
    protocols = load("docs/contracts/PROTOCOL_SCHEMAS.json")["protocols"]
    domains = load("docs/data/DATA_AUTHORITY.json")["domains"]
    packages = load("docs/delivery/WORK_PACKAGES.json")["packages"]
    threats = load("docs/security/THREAT_MODEL.json")["threats"]

    module_map = {row["id"]: row for row in modules["modules"]}
    changed = []

    for row in bindings["bindings"]:
        module = module_map[row["module"]]
        declared = [binding["path"] for binding in module["rootBindings"]]
        existing = [item for item in declared if (ROOT / item).exists()]
        row.update(
            lifecycle=module["lifecycle"],
            sourceStatus=module["sourceStatus"],
            source_root_present=module["source_root_present"],
            production_implementation=module["production_implementation"],
            declaredRoots=declared,
            existingDeclaredRoots=existing,
            missingDeclaredRoots=[item for item in declared if item not in existing],
            bootstrapWorkPackage=module["bootstrapWorkPackage"],
            technicalDocument=module["technicalDocument"],
        )

    rendered_bindings = json.dumps(bindings, indent=2, ensure_ascii=False) + "\n"
    bindings_path = ROOT / "docs/modules/SOURCE_BINDINGS.json"
    if rendered_bindings != bindings_path.read_text(encoding="utf-8"):
        changed.append("docs/modules/SOURCE_BINDINGS.json")
        if not check:
            bindings_path.write_text(rendered_bindings, encoding="utf-8")

    for row in docs["modules"]:
        module_id = row["module"]
        module = module_map[module_id]
        doc_path = ROOT / module["technicalDocument"]
        need(doc_path.is_file(), "index source missing " + module["technicalDocument"])
        text = doc_path.read_text(encoding="utf-8")
        produced = sorted(c["id"] for c in contracts if c["producer"] == module_id)
        consumed = sorted(c["id"] for c in contracts if module_id in c["consumers"])
        touched = set(produced + consumed)
        row.update(
            path=module["technicalDocument"],
            sourceStatus=module["sourceStatus"],
            source_root_present=module["source_root_present"],
            production_implementation=module["production_implementation"],
            bootstrapWorkPackage=module["bootstrapWorkPackage"],
            sha256=sha(text),
            bytes=len(text.encode("utf-8")),
            words=len(re.findall(r"\\b[\\w.-]+\\b", text)),
            requiredSections=HEADINGS,
            producedContracts=produced,
            consumedContracts=consumed,
            protocols=sorted(p["id"] for p in protocols if p.get("contractId") in touched),
            ownedDomains=sorted(d["id"] for d in domains if d["authoritativeWriter"] == module_id),
            readDomains=sorted(d["id"] for d in domains if module_id in d.get("readers", [])),
            workPackages=sorted(
                p["id"]
                for p in packages
                if p["module"] == module_id or module_id in p.get("coOwnerModules", [])
            ),
            threats=sorted(t["id"] for t in threats if t["owner"] == module_id),
        )

    rendered_docs = json.dumps(docs, indent=2, ensure_ascii=False) + "\n"
    docs_path = ROOT / "docs/modules/MODULE_DOCS.json"
    if rendered_docs != docs_path.read_text(encoding="utf-8"):
        changed.append("docs/modules/MODULE_DOCS.json")
        if not check:
            docs_path.write_text(rendered_docs, encoding="utf-8")

    details = load("qualification/module-execution-dossiers/DETAILS.json")
    for row in details["rows"]:
        detail_path = ROOT / row["path"]
        need(detail_path.is_file(), "index source missing " + row["path"])
        row["sha256"] = sha(detail_path.read_text(encoding="utf-8"))
    rendered_details = json.dumps(details, separators=(",", ":"), ensure_ascii=False) + "\n"
    details_path = ROOT / "qualification/module-execution-dossiers/DETAILS.json"
    if rendered_details != details_path.read_text(encoding="utf-8"):
        changed.append("qualification/module-execution-dossiers/DETAILS.json")
        if not check:
            details_path.write_text(rendered_details, encoding="utf-8")

    need(not check or not changed, "generated module projection drift: " + ", ".join(changed))
    print(json.dumps({"updatedIndexes": changed, "checkOnly": check}))
    return 0


def verify():
    modules = load("docs/modules/MODULES.json")
    bindings = load("docs/modules/SOURCE_BINDINGS.json")
    docs = load("docs/modules/MODULE_DOCS.json")
    contracts = load("docs/contracts/CONTRACTS.json")["contracts"]
    protocols = load("docs/contracts/PROTOCOL_SCHEMAS.json")["protocols"]
    domains = load("docs/data/DATA_AUTHORITY.json")["domains"]
    packages = load("docs/delivery/WORK_PACKAGES.json")["packages"]
    threats = load("docs/security/THREAT_MODEL.json")["threats"]
    need(modules.get("schema") == "hepta.module-registry.v7", "module schema")
    need(bindings.get("schema") == "hepta.module-source-binding.v2", "binding schema")
    need(docs.get("schema") == "hepta.module-document-index.v2", "document schema")
    for label, value in [("modules", modules), ("bindings", bindings), ("docs", docs)]:
        need(
            value.get("planId") == "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
            and value.get("planVersion") == "8.0.0",
            label + " plan",
        )
        false_authority(value.get("authorityFlags"), label)
    mods = modules["modules"]
    mids = [m["id"] for m in mods]
    need(bool(mids) and len(set(mids)) == len(mids), "module IDs")
    bmap = {b["module"]: b for b in bindings["bindings"]}
    dmap = {d["module"]: d for d in docs["modules"]}
    need(len(bmap) == len(bindings["bindings"]), "duplicate binding")
    need(len(dmap) == len(docs["modules"]), "duplicate document")
    need(set(bmap) == set(mids), "binding coverage")
    need(set(dmap) == set(mids), "document coverage")
    pkgids = {p["id"] for p in packages}
    for m in mods:
        mid = m["id"]
        b = bmap[mid]
        row = dmap[mid]
        need(m.get("sourceStatus") in ALLOWED_STATUS, mid + " source status")
        for record, label in ((m, "module"), (b, "binding"), (row, "document")):
            need(
                all(
                    key in record and type(record[key]) is bool
                    for key in STATUS_FACT_FIELDS
                ),
                mid + " " + label + " status facts",
            )
            need(
                record["production_implementation"] is False
                or record["source_root_present"] is True,
                mid + " production implementation without source root",
            )
        need(
            m.get("sourceStatus") == b["sourceStatus"] == row["sourceStatus"],
            mid + " status agreement",
        )
        need(
            m["source_root_present"]
            == b["source_root_present"]
            == row["source_root_present"],
            mid + " source-root presence agreement",
        )
        need(
            m["production_implementation"]
            == b["production_implementation"]
            == row["production_implementation"],
            mid + " production implementation agreement",
        )
        need(m.get("bootstrapWorkPackage") in pkgids, mid + " bootstrap")
        need(
            m["bootstrapWorkPackage"]
            == b["bootstrapWorkPackage"]
            == row["bootstrapWorkPackage"],
            mid + " bootstrap agreement",
        )
        expected_path = f"docs/modules/{mid}/TECHNICAL.md"
        need(
            m.get("technicalDocument")
            == expected_path
            == b["technicalDocument"]
            == row["path"],
            mid + " stable doc path",
        )
        need(m.get("documentationReady") is True, mid + " documentation readiness")
        declared = [x["path"] for x in m["rootBindings"]]
        existing = [x for x in declared if (ROOT / x).exists()]
        missing = [x for x in declared if not (ROOT / x).exists()]
        need(
            b["declaredRoots"] == declared
            and b["existingDeclaredRoots"] == existing
            and b["missingDeclaredRoots"] == missing,
            mid + " declared roots",
        )
        need(
            m["source_root_present"] == bool(existing),
            mid + " source-root presence truth",
        )
        need(
            all((ROOT / x).exists() for x in b["sourceEvidenceRoots"]),
            mid + " evidence root",
        )
        status = b["sourceStatus"]
        if status in {"existing_bound", "target_materialized"}:
            need(len(existing) == len(declared), mid + " materialized")
        if status in {
            "existing_declared_unbound",
            "target_unmaterialized",
            "external_with_adapter_target",
        }:
            need(not existing, mid + " unbound")
        if status == "existing_partially_bound":
            need(existing and missing, mid + " partial bound")
        if status in {"existing_legacy_aggregate", "target_partially_materialized"}:
            need(b["sourceEvidenceRoots"] or existing, mid + " aggregate evidence")
        path = ROOT / expected_path
        need(path.is_file(), mid + " guide missing")
        text = path.read_text(encoding="utf-8")
        # Prose is navigation, not an authenticated artifact or a second registry.
        # A normal explanation edit must not require a new word count, digest or
        # verbatim heading/contract inventory. Machine ownership and coverage
        # checks below, source existence and local links remain enforced.
        need(bool(text.strip()), mid + " empty guide")
        produced = sorted(c["id"] for c in contracts if c["producer"] == mid)
        consumed = sorted(c["id"] for c in contracts if mid in c["consumers"])
        touched = set(produced + consumed)
        proto = sorted(p["id"] for p in protocols if p.get("contractId") in touched)
        owned = sorted(d["id"] for d in domains if d["authoritativeWriter"] == mid)
        reads = sorted(d["id"] for d in domains if mid in d.get("readers", []))
        work = sorted(
            p["id"]
            for p in packages
            if p["module"] == mid or mid in p.get("coOwnerModules", [])
        )
        own_threats = sorted(t["id"] for t in threats if t["owner"] == mid)
        expected = {
            "producedContracts": produced,
            "consumedContracts": consumed,
            "protocols": proto,
            "ownedDomains": owned,
            "readDomains": reads,
            "workPackages": work,
            "threats": own_threats,
        }
        for key, items in expected.items():
            need(row[key] == items, mid + " index " + key)
        verify_local_links(path, text)
    readme = ROOT / "docs/modules/README.md"
    verify_local_links(readme, readme.read_text(encoding="utf-8"))
    # Every registered module must expose a source navigation map.  The map
    # records the distinction between a source root being present and a
    # production implementation being composed; it never upgrades claims.
    maps = subprocess.run(
        ["python3", "scripts/hepta-implementation-maps.py", "verify"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    need(
        maps.returncode == 0,
        "implementation maps: " + (maps.stderr.strip() or maps.stdout.strip()),
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_MODULE_DOCS_CLOSED_WORLD",
                "modules": len(mods),
                "technicalDocuments": len(dmap),
                "sourceBindings": len(bmap),
                "validationScope": "registry_ownership_paths_and_document_navigation",
                "productExecutionProved": False,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test():
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=pairs)
        raise AssertionError
    except DuplicateKey:
        pass
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_MODULE_DOCS_SELF_TEST",
                "cases": ["duplicate_key"],
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["verify", "self-test", "refresh-indexes"])
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    if args.command == "refresh-indexes":
        return refresh_indexes(args.check)
    if args.check:
        p.error("--check applies only to refresh-indexes")
    return verify() if args.command == "verify" else self_test()


if __name__ == "__main__":
    raise SystemExit(main())
