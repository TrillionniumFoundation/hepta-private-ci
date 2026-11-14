#!/usr/bin/env python3
"""Generate context.compiler status/provenance sections from one manifest.

This generator is deterministic. It never claims that a candidate executed:
exact SHA/tree execution identity belongs only in immutable qualification receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs/modules/context.compiler/CURRENT_STATE.json"
TECHNICAL_PATH = REPO_ROOT / "docs/modules/context.compiler/TECHNICAL.md"
MAP_PATH = REPO_ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json"
DOSSIER_PATH = REPO_ROOT / "qualification/module-execution-dossiers/detail/context.compiler.md"

BEGIN = "<!-- BEGIN GENERATED CONTEXT.COMPILER CURRENT STATE -->"
END = "<!-- END GENERATED CONTEXT.COMPILER CURRENT STATE -->"


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "hepta.context-compiler-current-state.v1":
        raise ValueError("unsupported context.compiler state manifest schema")
    if manifest.get("module") != "context.compiler":
        raise ValueError("state manifest is not for context.compiler")
    targets = set(manifest.get("generatedTargets", []))
    required = {
        "docs/modules/context.compiler/TECHNICAL.md",
        "docs/modules/context.compiler/IMPLEMENTATION_MAP.json",
        "qualification/module-execution-dossiers/detail/context.compiler.md",
    }
    if targets != required:
        raise ValueError("generatedTargets must name exactly the three governed outputs")
    return manifest


def status_table(manifest: dict[str, Any]) -> str:
    labels = (
        ("Core implementation", "coreImplementation"),
        ("Product composition", "productComposition"),
        ("V2 provider closure", "v2ProviderClosure"),
        ("Current-head qualification", "currentHeadQualification"),
    )
    meaning = manifest["statusMeaning"]
    rows = ["| Dimension | State | Meaning |", "|---|---|---|"]
    for label, key in labels:
        rows.append(f"| {label} | `{manifest['status'][key]}` | {meaning[key]} |")
    return "\n".join(rows)


def byte_table(manifest: dict[str, Any]) -> str:
    rows = [
        "| Object | Owner | Contents | Required digest | Tokenization rule | Rebuild after binding |",
        "|---|---|---|---|---|---|",
    ]
    for item in manifest["byteIdentities"]:
        rebuilt = "yes" if item["mayBeRebuiltAfterBinding"] else "**no**"
        rows.append(
            f"| {item['object']} | {item['owner']} | {item['contents']} | "
            f"`{item['requiredDigest']}` | {item['tokenization']} | {rebuilt} |"
        )
    return "\n".join(rows)


def sequence_diagram(manifest: dict[str, Any]) -> str:
    actors: list[str] = []
    for step in manifest["sequence"]:
        if step["actor"] not in actors:
            actors.append(step["actor"])
    aliases = {actor: f"A{index}" for index, actor in enumerate(actors, 1)}
    lines = ["```mermaid", "sequenceDiagram"]
    for actor in actors:
        lines.append(f"    participant {aliases[actor]} as {actor}")
    for previous, current in zip(manifest["sequence"], manifest["sequence"][1:]):
        lines.append(
            f"    {aliases[previous['actor']]}->>{aliases[current['actor']]}: "
            f"{current['id']}. {current['action']}"
        )
    lines.append("```")
    return "\n".join(lines)


def render_technical(manifest: dict[str, Any]) -> str:
    source = manifest["provenance"]["sourceBase"]
    tokenizer = "\n".join(f"- `{field}`" for field in manifest["requiredTokenizerBinding"])
    coverage = "\n".join(f"- {rule}" for rule in manifest["serializerCoverage"]["requirements"])
    gaps = "\n".join(f"- {gap}" for gap in manifest["repositoryControlledGaps"])
    allowed = ", ".join(f"`{kind}`" for kind in manifest["serializerCoverage"]["allowedSegmentKinds"])
    return f"""{BEGIN}
## Machine-generated current state and byte identity

This section is generated from `{manifest['provenance']['generatedFrom']}` by
`{manifest['provenance']['generator']}`. Manual edits inside the markers are rejected by the drift check.

**Manifest SHA-256:** `{manifest_digest(manifest)}`

**Provenance base:** commit `{source['commit']}`, tree `{source['tree']}`
(`{manifest['provenance']['sourceBaseMode']}`). This is integration provenance, not an execution claim.
{manifest['provenance']['qualificationIdentityRule']}

### Current implementation state

{status_table(manifest)}

### End-to-end provider-bound target sequence

{sequence_diagram(manifest)}

### Digest and byte identity

{byte_table(manifest)}

The four objects above are deliberately not aliases. A canonical context-bundle digest cannot stand in
for the provider-final-request digest, and a provider wire semantic digest cannot stand in for
final-request tokenizer evidence.

### Required final-request tokenizer binding

{tokenizer}

### Serializer segment coverage contract

Allowed segment kinds: {allowed}.

{coverage}

### Repository-controlled gaps

{gaps}
{END}"""


def render_dossier(manifest: dict[str, Any]) -> str:
    source = manifest["provenance"]["sourceBase"]
    gaps = "\n".join(f"- {gap}" for gap in manifest["repositoryControlledGaps"])
    return f"""{BEGIN}
## Generated current-state observation

**Manifest:** `{manifest['provenance']['generatedFrom']}`  
**Manifest SHA-256:** `{manifest_digest(manifest)}`  
**Provenance base:** `{source['commit']}` / `{source['tree']}`

{status_table(manifest)}

The dossier records source-complete core primitives, partial named-product composition, an open V2
provider-bound closure, and no exact-current-head qualification receipt. It must not infer provider
execution or release readiness from source presence.

### Open repository-controlled closure

{gaps}
{END}"""


def replace_block(text: str, block: str, *, heading: str) -> str:
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError(f"{heading}: malformed generated-state markers")
        start = text.index(BEGIN)
        finish = text.index(END, start) + len(END)
        return text[:start].rstrip() + "\n\n" + block + "\n\n" + text[finish:].lstrip()
    lines = text.splitlines()
    if not lines:
        return block + "\n"
    insert_at = 1 if lines[0].startswith("#") else 0
    lines[insert_at:insert_at] = ["", block, ""]
    return "\n".join(lines).rstrip() + "\n"


def render_map(existing: str, manifest: dict[str, Any]) -> str:
    value = json.loads(existing)
    source = manifest["provenance"]["sourceBase"]
    state = manifest["status"]
    value["sourceBase"] = source
    value["productionImplementation"] = state["coreImplementation"] == "complete"
    value["productCallerState"] = "verified_v2_partially_product_composed_provider_closure_incomplete"
    value["productionWriterState"] = "not_applicable_stateless_runtime"
    value["currentStateManifest"] = manifest["provenance"]["generatedFrom"]
    value["generatedState"] = {
        "schema": manifest["schema"],
        "manifestSha256": manifest_digest(manifest),
        "coreImplementation": state["coreImplementation"],
        "productComposition": state["productComposition"],
        "v2ProviderClosure": state["v2ProviderClosure"],
        "currentHeadQualification": state["currentHeadQualification"],
        "byteIdentityObjects": [item["object"] for item in manifest["byteIdentities"]],
    }
    value["repositoryControlledGaps"] = manifest["repositoryControlledGaps"]
    boundary = value.setdefault("claimBoundary", {})
    boundary["nativeSourceMappingComplete"] = True
    boundary["sourceRootPresent"] = True
    boundary["productionImplementation"] = True
    boundary["productExecutionProved"] = False
    boundary["independentAcceptance"] = False
    boundary["activation"] = False
    boundary["release"] = False
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def expected_outputs(manifest: dict[str, Any]) -> dict[Path, str]:
    return {
        TECHNICAL_PATH: replace_block(TECHNICAL_PATH.read_text(encoding="utf-8"), render_technical(manifest), heading=str(TECHNICAL_PATH)),
        MAP_PATH: render_map(MAP_PATH.read_text(encoding="utf-8"), manifest),
        DOSSIER_PATH: replace_block(DOSSIER_PATH.read_text(encoding="utf-8"), render_dossier(manifest), heading=str(DOSSIER_PATH)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite governed outputs")
    mode.add_argument("--check", action="store_true", help="fail when governed outputs drift")
    args = parser.parse_args()
    manifest = load_manifest()
    outputs = expected_outputs(manifest)
    check = args.check or not args.write
    drift: list[str] = []
    for path, expected in outputs.items():
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            drift.append(str(path.relative_to(REPO_ROOT)))
            if not check:
                path.write_text(expected, encoding="utf-8")
    if check and drift:
        print("context.compiler generated documentation drift:", file=sys.stderr)
        for path in drift:
            print(f"  - {path}", file=sys.stderr)
        print("run: python3 scripts/generate-context-compiler-docs.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
