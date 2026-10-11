#!/usr/bin/env python3
"""Read-only, exact-Git module/organ/writer deployment handoff inventory.

This is a source inventory, not a deployment detector or an authority receipt.
It reads committed blobs only; dirty checkout files cannot change the result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

REGISTRIES = {
    "modules": "docs/modules/MODULES.json",
    "organs": "docs/cns/CNS_ARCHITECTURE.json",
    "domains": "docs/data/DATA_AUTHORITY.json",
}
MAX_BYTES = 16 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}\Z")


class InventoryError(ValueError):
    """A source, ownership or identity invariant was not established."""


def unique(rows: list[dict], label: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        identity = row.get("id")
        if not isinstance(identity, str) or not identity or identity in result:
            raise InventoryError(f"invalid or duplicate {label} identity")
        result[identity] = row
    return result


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts
            or str(path) != value or "\\" in value or "\x00" in value
            or any(ord(char) < 32 for char in value)):
        raise InventoryError("noncanonical source path")
    return value


def duplicate_keys(items: list[tuple]) -> dict:
    out = {}
    for key, value in items:
        if key in out:
            raise InventoryError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
        raise InventoryError("Git read failed or exceeded inventory budget")
    return result.stdout


def build_mapping(modules: list[dict], organs: list[dict], domains: list[dict],
                  files: dict[str, dict]) -> dict:
    """Project canonical owners without promoting source facts to runtime facts."""
    mmap, omap, dmap = (unique(modules, "module"), unique(organs, "organ"),
                        unique(domains, "domain"))
    writers = {identity: [] for identity in mmap}
    for identity, domain in dmap.items():
        for key in ("schemaOwner", "authoritativeWriter"):
            if domain.get(key) not in mmap:
                raise InventoryError(f"unknown {key} for {identity}")
        writer = domain["authoritativeWriter"]
        if writer in domain.get("forbiddenWriters", []):
            raise InventoryError(f"writer is forbidden for {identity}")
        if any(reader not in mmap for reader in domain.get("readers", [])):
            raise InventoryError(f"unknown reader for {identity}")
        writers[writer].append(identity)
    module_organs = {identity: [] for identity in mmap}
    special = {"hnmf.reference": "qualification/hnmf-reference"}
    organ_rows = []
    for identity, organ in sorted(omap.items()):
        bindings = organ.get("moduleBindings", [])
        if len(bindings) != len(set(bindings)):
            raise InventoryError(f"duplicate organ binding: {identity}")
        for dependency in organ.get("dependencies", []) + organ.get("fallbackOrgans", []):
            if dependency not in omap:
                raise InventoryError(f"unknown organ edge: {identity}")
        qualified = []
        for module in bindings:
            if module in mmap:
                module_organs[module].append(identity)
            elif module in special:
                prefix = special[module] + "/"
                qualified.append({"id": module, "root": special[module],
                                  "sourcePresent": any(p.startswith(prefix) for p in files),
                                  "scope": "qualification_only_not_production_module"})
            else:
                raise InventoryError(f"unknown organ module: {module}")
        organ_rows.append({"id": identity, "moduleBindings": sorted(bindings),
                           "qualificationBindings": qualified,
                           "declaredImplementationState": organ.get("implementationState"),
                           "declaredActivationState": organ.get("activationState"),
                           "observedHostInstances": [], "runtimeVerified": False})
    rows = []
    for identity, module in sorted(mmap.items()):
        if not module.get("owner") or not module.get("deputy"):
            raise InventoryError(f"missing owner/deputy: {identity}")
        roots = []
        for binding in module.get("rootBindings", []):
            source = relative_path(binding["path"])
            matches = [p for p in files if p == source or p.startswith(source + "/")]
            ordinary = [p for p in matches if files[p]["mode"] in ("100644", "100755")]
            manifests = [{"path": p, "blob": files[p]["sha"],
                          "package": files[p].get("package")}
                         for p in sorted(ordinary) if p.endswith("/Cargo.toml")]
            roots.append({"path": source, "bindingMode": binding.get("mode"),
                          "ordinarySourcePresent": bool(ordinary),
                          "fileCount": len(ordinary), "cargoManifests": manifests,
                          "nonordinaryEntries": sorted(set(matches) - set(ordinary))})
        rows.append({"id": identity, "owner": module["owner"], "deputy": module["deputy"],
                     "sourceStatus": module.get("sourceStatus"), "roots": roots,
                     "organs": sorted(module_organs[identity]),
                     "schemaDomains": sorted(d for d, v in dmap.items() if v["schemaOwner"] == identity),
                     "writerDomains": sorted(writers[identity]),
                     "technicalDocument": module.get("technicalDocument"),
                     "bootstrapWorkPackage": module.get("bootstrapWorkPackage"),
                     "hostBinding": None, "productionCallerVerified": False,
                     "handoffRequired": ["named_host_and_entrypoint", "compiled_port_and_consumer",
                                         "schema_migration_and_recovery", "authenticated_observer",
                                         "measured_resource_profile", "independent_acceptance"]})
    return {"modules": rows, "organs": organ_rows,
            "dataDomains": [{"id": d, "schemaOwner": v["schemaOwner"],
                             "authoritativeWriter": v["authoritativeWriter"],
                             "readers": sorted(v.get("readers", [])),
                             "physicalStoreBinding": None}
                            for d, v in sorted(dmap.items())],
            "counts": {"modules": len(mmap), "organs": len(omap), "domains": len(dmap)}}


def inventory(root: Path, base: str) -> dict:
    if SHA.fullmatch(base) is None:
        raise InventoryError("base must be an explicit full commit SHA")
    head = git(root, "rev-parse", "HEAD^{commit}").decode().strip()
    if SHA.fullmatch(head) is None:
        raise InventoryError("invalid source identity")
    git(root, "merge-base", "--is-ancestor", base, head)
    tree = git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    files = {}
    for entry in git(root, "ls-tree", "-r", "-z", head).split(b"\x00"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, sha = metadata.decode().split()
        path = relative_path(raw_path.decode("utf-8"))
        files[path] = {"mode": mode, "kind": kind, "sha": sha}
    data, inputs = {}, {}
    for label, path in REGISTRIES.items():
        raw = git(root, "show", f"{head}:{path}")
        data[label] = json.loads(raw, object_pairs_hook=duplicate_keys)
        inputs[path] = {"gitBlob": files[path]["sha"],
                        "sha256": hashlib.sha256(raw).hexdigest()}
    for path, entry in files.items():
        if path.endswith("/Cargo.toml") and entry["mode"] in ("100644", "100755"):
            raw = git(root, "show", f"{head}:{path}")
            entry["package"] = tomllib.loads(raw.decode()).get("package", {}).get("name")
    result = build_mapping(data["modules"]["modules"], data["organs"]["organs"],
                           data["domains"]["domains"], files)
    result.update({"schema": "hepta.deployment-handoff-inventory.v1",
                   "scope": "committed_source_only_not_live_deployment",
                   "baseCommit": base, "sourceCommit": head, "sourceTree": tree,
                   "registryInputs": inputs, "canonicalSelection": False,
                   "allGapsClosed": False, "runtimeAuthority": False})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--base", required=True, help="explicit full ancestor commit SHA")
    args = parser.parse_args()
    try:
        value = inventory(args.root, args.base)
    except (InventoryError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"inventory rejected: {error}\n")
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
