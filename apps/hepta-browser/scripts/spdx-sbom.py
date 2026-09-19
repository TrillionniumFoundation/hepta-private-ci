#!/usr/bin/env python3
"""Emit a deterministic minimal SPDX-2.3 JSON SBOM from Cargo metadata."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import quote


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def spdx_id(name: str, version: str, source: str) -> str:
    material = f"{name}\0{version}\0{source}".encode()
    return "SPDXRef-Package-" + hashlib.sha256(material).hexdigest()[:24]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-date-epoch", required=True, type=int)
    parser.add_argument("--servo-pin", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    lock_digest = sha256(args.lock)
    binary_digest = sha256(args.binary)
    created = dt.datetime.fromtimestamp(args.source_date_epoch, tz=dt.timezone.utc)
    created_text = created.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    namespace_material = (
        f"{args.source_sha}\0{lock_digest}\0{binary_digest}\0{args.servo_pin}"
    ).encode()
    namespace = hashlib.sha256(namespace_material).hexdigest()

    packages = []
    relationships = []
    seen = set()
    for package in sorted(
        metadata.get("packages", []),
        key=lambda item: (item.get("name", ""), item.get("version", ""), item.get("source") or ""),
    ):
        name = package["name"]
        version = package["version"]
        source = package.get("source") or "workspace"
        package_id = spdx_id(name, version, source)
        if package_id in seen:
            continue
        seen.add(package_id)
        entry = {
            "SPDXID": package_id,
            "name": name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:cargo/{quote(name, safe='')}@{quote(version, safe='')}",
                }
            ],
            "comment": f"cargo_source={source}",
        }
        packages.append(entry)
        relationships.append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": package_id,
            }
        )

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "hepta-servo-worker",
        "documentNamespace": f"https://trillionnium.foundation/spdx/hepta-servo-worker/{namespace}",
        "creationInfo": {
            "created": created_text,
            "creators": ["Tool: hepta-browser-spdx-sbom-v1"],
        },
        "comment": (
            f"source_sha={args.source_sha} servo_pin={args.servo_pin} "
            f"cargo_lock_sha256={lock_digest} worker_sha256={binary_digest}"
        ),
        "packages": packages,
        "relationships": relationships,
    }
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
