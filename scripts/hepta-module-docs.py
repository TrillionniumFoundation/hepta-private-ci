#!/usr/bin/env python3
"""Closed-world validator for Hepta module source bindings and technical guides."""

import argparse, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_KEYS = [
    "runtimeAuthority",
    "productionCaller",
    "productionWriter",
    "modelInvocation",
    "providerDispatch",
    "toolExecution",
    "networkConnect",
    "externalFilesystemMutation",
    "secretOperation",
    "matrixSend",
    "externalEffect",
    "fleetMutation",
    "canonicalSelection",
    "merge",
    "operatorAcceptance",
    "promotion",
    "release",
]
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
    need(not any(value.values()), label + " positive authority")


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
    """Recompute derived bytes/counts/digests without changing claims or scope."""
    specs = [
        ("docs/modules/MODULE_DOCS.json", "modules", True),
        ("qualification/module-execution-dossiers/DETAILS.json", "rows", False),
    ]
    changed = []
    for relative, key, include_metrics in specs:
        document = load(relative)
        for row in document[key]:
            path = ROOT / row["path"]
            need(path.is_file(), "index source missing " + row["path"])
            text = path.read_text(encoding="utf-8")
            updates = {"sha256": sha(text)}
            if include_metrics:
                updates.update(
                    bytes=len(text.encode("utf-8")),
                    words=len(re.findall(r"\b[\w.-]+\b", text)),
                )
            row.update(updates)
        # Preserve each existing index's representation; refreshing derived
        # values must not expand the compact detail index into a formatting diff.
        rendered = (
            json.dumps(document, indent=2, ensure_ascii=False)
            if include_metrics
            else json.dumps(document, separators=(",", ":"), ensure_ascii=False)
        ) + "\n"
        path = ROOT / relative
        if rendered != path.read_text(encoding="utf-8"):
            changed.append(relative)
            if not check:
                path.write_text(rendered, encoding="utf-8")
    need(not check or not changed, "derived index drift: " + ", ".join(changed))
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
    need(modules.get("schema") == "hepta.module-registry.v6", "module schema")
    need(bindings.get("schema") == "hepta.module-source-binding.v1", "binding schema")
    need(docs.get("schema") == "hepta.module-document-index.v1", "document schema")
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
    need(set(bmap) == set(mids), "binding coverage")
    need(set(dmap) == set(mids), "document coverage")
    pkgids = {p["id"] for p in packages}
    for m in mods:
        mid = m["id"]
        b = bmap[mid]
        row = dmap[mid]
        need(m.get("sourceStatus") in ALLOWED_STATUS, mid + " source status")
        need(
            m.get("sourceStatus") == b["sourceStatus"] == row["sourceStatus"],
            mid + " status agreement",
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
        need(text.startswith(f"# {mid} technical development guide\n"), mid + " title")
        need(all(h in text for h in HEADINGS), mid + " required headings")
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
            need(all(item in text for item in items), mid + " guide " + key)
        words = len(re.findall(r"\b[\w.-]+\b", text))
        need(
            row["bytes"] == len(text.encode("utf-8")) and row["words"] == words,
            mid + " guide metrics",
        )
        need(row["sha256"] == sha(text), mid + " guide digest")
        need(row["requiredSections"] == HEADINGS, mid + " heading index")
        verify_local_links(path, text)
    readme = ROOT / "docs/modules/README.md"
    verify_local_links(readme, readme.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_MODULE_DOCS_CLOSED_WORLD",
                "modules": len(mods),
                "technicalDocuments": len(dmap),
                "sourceBindings": len(bmap),
                "validationScope": "registry_digests_paths_and_document_navigation",
                "productExecutionProved": False,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test():
    need(len(HEADINGS) == 15, "heading fixture")
    need("target_unmaterialized" in ALLOWED_STATUS, "status fixture")
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=pairs)
        raise AssertionError
    except DuplicateKey:
        pass
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_MODULE_DOCS_SELF_TEST",
                "cases": ["headings", "statuses", "duplicate_key"],
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
