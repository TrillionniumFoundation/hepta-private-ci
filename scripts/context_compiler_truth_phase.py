#!/usr/bin/env python3
"""Upgrade context.compiler generated truth to the current product path."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/modules/context.compiler/MODULE_MANIFEST.json"
GENERATOR = ROOT / "scripts/generate_context_compiler_module_docs.py"
QUALIFIER = ROOT / "scripts/context_compiler_qualification.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path.relative_to(ROOT)}: expected one anchor, found {count}: {old[:120]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def update_manifest() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["schemaVersion"] = 2
    manifest["branch"] = "codex/context-compiler-v2-full-closure-20260927"
    manifest["workPackage"] = {
        "id": "CTX-1-CONTEXT-COMPILER",
        "state": "integration_in_progress",
    }
    manifest["artifacts"]["currentProductPath"] = (
        "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md"
    )
    manifest["statusRationale"]["productComposition"] = (
        "The named registry/intelligence/Agentd path, durable stage owner and Core exact-encoded-body "
        "observer are composed in source. Strict preparation and V2 terminal accounting are not yet "
        "the sole default serving path."
    )
    manifest["statusRationale"]["v2ProviderClosure"] = (
        "Core can now fail closed on the exact encoded request body, while the strict compiler owns "
        "canonical serialization and exact-tokenizer attestations. A qualified concrete tokenizer, "
        "authoritative admission owner and sole-path preparation/terminal composition remain open."
    )

    roots = manifest["sourceRoots"]
    for root in [
        "codex-rs/hepta-context-compiler/src/provider_bound.rs",
        "codex-rs/hepta-context-compiler/src/provider_delivery.rs",
        "codex-rs/hepta-intelligence/src/provider_bound_prompt.rs",
        "codex-rs/hepta-agentd/src/provider_bound_prompt_runtime.rs",
        "codex-rs/codex-api/src/dispatch_metadata.rs",
        "codex-rs/codex-api/src/endpoint/responses.rs",
        "codex-rs/core/src/model_provider_policy/attempt_owner.rs",
        "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs",
    ]:
        if root not in roots:
            roots.append(root)

    manifest["productCallers"] = [
        {
            "phase": "registry compile",
            "sourcePath": "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
            "nativeSymbol": "compile_prompt_registry_v2",
            "state": "legacy-compatible source composed",
        },
        {
            "phase": "strict canonical compile",
            "sourcePath": "codex-rs/hepta-intelligence/src/provider_bound_prompt.rs",
            "nativeSymbol": "prepare_provider_bound_prompt_v2",
            "state": "source composed; not yet the default ingress",
        },
        {
            "phase": "named product owner",
            "sourcePath": "codex-rs/hepta-agentd/src/prompt_runtime.rs",
            "nativeSymbol": "AgentdPromptPipelineOwner",
            "state": "legacy compile/stage owner active",
        },
        {
            "phase": "strict durable stage",
            "sourcePath": "codex-rs/hepta-agentd/src/provider_bound_prompt_runtime.rs",
            "nativeSymbol": "AgentdProviderBoundPromptRuntimeV2",
            "state": "durable source composed; not sole serving owner",
        },
        {
            "phase": "exact encoded body",
            "sourcePath": "codex-rs/core/src/model_provider_policy/attempt_owner.rs",
            "nativeSymbol": "LeaseFinalRequestObserver",
            "state": "physical pre-transport gate composed",
        },
        {
            "phase": "provider lease ABI",
            "sourcePath": "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs",
            "nativeSymbol": "observe_final_request",
            "state": "exact-body callback composed",
        },
        {
            "phase": "V2 terminal observation",
            "sourcePath": "codex-rs/hepta-context-compiler/src/provider_delivery.rs",
            "nativeSymbol": "observe_provider_bound_delivery_v2",
            "state": "source composed; terminal product adapter remains partial",
        },
    ]
    manifest["adapterTruth"] = {
        "admissionVerifier": (
            "Strict APIs require a verifier identity, but the current named product path still "
            "constructs provisional registry-bound admissions inside the same trust domain."
        ),
        "tokenizer": (
            "Strict APIs tokenize actual canonical/final bytes and bind provider/model/binary/"
            "version/vocabulary/normalization identities; a concrete independently qualified "
            "production executable is not yet selected."
        ),
        "serializer": (
            "CanonicalContextSerializerV2 is compiler-owned and does not accept caller-supplied "
            "final payload bytes."
        ),
        "providerRequest": (
            "Core observes the exact encoded body immediately before transport and fails closed "
            "when a required observer is absent."
        ),
        "deliveryEvidence": (
            "Canonical provider receipt validation exists; Agentd has not yet made the V2 receipt "
            "the sole durable terminal record."
        ),
    }
    manifest["roleSupport"] = [
        {
            "role": "DeveloperInstruction",
            "state": "supported by the current runtime projection",
        },
        {
            "role": "SystemInstruction",
            "state": "fail closed: no exact typed provider slot",
        },
        {
            "role": "UserTemplate",
            "state": "fail closed: no exact typed provider slot",
        },
        {
            "role": "ToolSchemaFragment",
            "state": "fail closed: no exact typed provider slot",
        },
    ]
    manifest["legacyPath"] = {
        "state": "compatibility path still compiled and currently active",
        "cutoverCondition": (
            "Enable the strict path by default only after authoritative admission, exact-body "
            "pre-dispatch preparation and V2 terminal persistence are composed and qualified."
        ),
    }
    manifest["sequence"] = [
        "authoritative registry/admission snapshot",
        "verify_admission_snapshot_v2 + verify_admission_v2",
        "compile_v2",
        "compiler-owned canonical serialization over realized bytes",
        "exact tokenizer over canonical context",
        "build_attachment",
        "typed current snapshot successor",
        "prepare_delivery_from_successor_v2",
        "host materializes and byte-covers the provider request",
        "exact tokenizer over final provider request bytes",
        "Core observes the exact encoded body",
        "durable dispatch claim before transport",
        "physical provider effect",
        "canonical provider terminal receipt",
        "independent delivery verifier + observe_provider_bound_delivery_v2",
        "durable ContextDeliveryReceiptV2",
    ]
    manifest["qualification"]["commands"] = [
        "python3 scripts/generate_context_compiler_module_docs.py --check",
        "cargo fmt --all -- --check",
        "cargo test --locked -p codex-hepta-context-compiler",
        "cargo clippy --locked -p codex-hepta-context-compiler --all-targets -- -D warnings",
        "cargo deny --locked check bans licenses sources",
        "cargo deny --locked check advisories (recorded non-blocking repository audit)",
        "bazel test //codex-rs/hepta-context-compiler:all",
        "python3 scripts/hepta-readiness.py verify",
        "python3 scripts/hepta-docs.py verify",
    ]
    manifest["knownOpenItems"] = [
        "Move admission issuance and current revocation snapshots to a construction-closed registry authority owner.",
        "Select and independently qualify the concrete provider/model tokenizer executable and artifacts.",
        "Run prepare_delivery_from_successor_v2 from the exact-body pre-transport callback, not only before staging.",
        "Make ContextDeliveryReceiptV2 the sole durable terminal accounting path and reconcile Indeterminate attempts.",
        "Feature-gate the V1 runtime path after strict-path product qualification.",
        "Produce exact-head, synthetic-merge, target-host benchmark and independent security-review evidence.",
    ]
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def update_generator() -> None:
    replace_once(GENERATOR, "import json\nfrom pathlib", "import json\nimport subprocess\nfrom pathlib")
    anchor = '''def render_status_table(manifest: dict[str, Any]) -> str:
'''
    block = '''def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def source_anchor(manifest: dict[str, Any]) -> dict[str, Any]:
    paths: set[str] = set()
    for root in manifest["sourceRoots"]:
        candidate = ROOT / root
        if candidate.is_dir():
            output = git_output("ls-files", "--", root)
            paths.update(line for line in output.splitlines() if line)
        elif candidate.is_file():
            paths.add(root)
        else:
            raise RuntimeError(f"missing source root: {root}")
    for caller in manifest["productCallers"]:
        path = caller["sourcePath"]
        candidate = ROOT / path
        if not candidate.is_file():
            raise RuntimeError(f"missing product caller: {path}")
        if caller["nativeSymbol"] not in candidate.read_text(encoding="utf-8"):
            raise RuntimeError(
                f"missing product caller symbol {caller['nativeSymbol']} in {path}"
            )
        paths.add(path)
    objects = [
        {"path": path, "blob": git_output("hash-object", "--", path)}
        for path in sorted(paths)
    ]
    canonical = json.dumps(
        objects, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "objects": objects}


def render_product_callers(manifest: dict[str, Any]) -> str:
    rows = [
        "| Phase | Source | Symbol | Current state |",
        "|---|---|---|---|",
    ]
    for caller in manifest["productCallers"]:
        rows.append(
            f"| {caller['phase']} | `{caller['sourcePath']}` | "
            f"`{caller['nativeSymbol']}` | {caller['state']} |"
        )
    return "\\n".join(rows)


def render_role_support(manifest: dict[str, Any]) -> str:
    rows = ["| Registry role | Product state |", "|---|---|"]
    for entry in manifest["roleSupport"]:
        rows.append(f"| `{entry['role']}` | {entry['state']} |")
    return "\\n".join(rows)


def render_status_table(manifest: dict[str, Any]) -> str:
'''
    replace_once(GENERATOR, anchor, block)

    replace_once(
        GENERATOR,
        '- Canonical manifest SHA-256: `{digest}`\n- Generator:',
        '- Canonical manifest SHA-256: `{digest}`\n'
        '- Source fingerprint SHA-256: `{source_anchor(manifest)["sha256"]}`\n'
        '- Work package: `{manifest["workPackage"]["id"]}` / '
        '`{manifest["workPackage"]["state"]}`\n- Generator:',
    )

    replace_once(
        GENERATOR,
        '''The current product source reaches compilation, attachment staging and provider-policy dispatch.
The strict path intentionally remains marked **partial/incomplete** until the host constructs
`VerifiedProviderRequestV2`, runs a profile-bound `ExactProviderRequestTokenizerV2`, submits those
attested bytes without reconstruction, and persists the resulting `ContextDeliveryReceiptV2`.
''',
        '''The current product source reaches compilation, durable staging and the physical exact-encoded-body
provider-policy gate. The strict path intentionally remains marked **partial/incomplete** until
current authoritative admission is refreshed in that same pre-transport ceremony and Agentd makes
the resulting `ContextDeliveryReceiptV2` the sole durable terminal record.
''',
    )

    replace_once(
        GENERATOR,
        '''def implementation_map(manifest: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
''',
        '''def implementation_map(manifest: dict[str, Any], digest: str) -> dict[str, Any]:
    anchor = source_anchor(manifest)
    return {
''',
    )
    replace_once(
        GENERATOR,
        '''        "status": manifest["status"],
        "statusRationale": manifest["statusRationale"],
''',
        '''        "status": manifest["status"],
        "statusRationale": manifest["statusRationale"],
        "workPackage": manifest["workPackage"],
        "sourceAnchor": anchor,
''',
    )
    old_product = '''        "productComposition": {
            "callers": [
                "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
                "codex-rs/hepta-agentd/src/prompt_runtime.rs",
                "codex-rs/ext/hepta-prompt/src/lib.rs",
                "codex-rs/core/src/model_provider_policy",
            ],
            "current": "partial",
            "closureCondition": (
                "The host supplies exact final request bytes and a qualified profile-bound "
                "tokenizer, dispatch consumes the attested request without reconstruction, and "
                "Agentd durably persists ContextDeliveryReceiptV2."
            ),
        },
'''
    new_product = '''        "productComposition": {
            "callers": manifest["productCallers"],
            "adapterTruth": manifest["adapterTruth"],
            "roleSupport": manifest["roleSupport"],
            "legacyPath": manifest["legacyPath"],
            "current": "partial",
            "closureCondition": (
                "Authoritative admission, exact-body preparation, physical dispatch and V2 terminal "
                "persistence execute as one qualified sole path."
            ),
        },
'''
    replace_once(GENERATOR, old_product, new_product)

    replace_once(
        GENERATOR,
        '''The source product path is real rather than hypothetical: prompt registry compilation feeds
`hepta-intelligence`, Agentd stages a runtime attachment, and the provider-policy extension observes
physical dispatch and terminal state. The composition remains **partial** because the current host
ABI exports semantic/request digests but not a qualified exact tokenizer over the final request
bytes. The strict API therefore blocks rather than treating registry token costs as final-request
proof.
''',
        '''The source product path is real rather than hypothetical: prompt registry compilation feeds
`hepta-intelligence`, Agentd owns durable staging, and Core now observes the exact encoded body before
transport. Composition remains **partial** because the authoritative admission owner, qualified
concrete tokenizer and sole-path V2 terminal persistence are not yet all active in one effect-bound
ceremony. The strict API fails closed rather than falling back to registry token costs.
''',
    )

    insert_before = '''def render_all(manifest: dict[str, Any]) -> dict[Path, str]:
'''
    current_path_fn = '''def render_current_product_path(manifest: dict[str, Any], digest: str) -> str:
    anchor = source_anchor(manifest)
    adapters = "\\n".join(
        f"- **{name}:** {value}" for name, value in manifest["adapterTruth"].items()
    )
    open_items = "\\n".join(
        f"{index}. {entry}"
        for index, entry in enumerate(manifest["knownOpenItems"], start=1)
    )
    return f"""<!-- GENERATED FILE: edit MODULE_MANIFEST.json and run {manifest["generatedBy"]} --write. -->
# `context.compiler` current product path

## Current status

{render_status_table(manifest)}

- Manifest SHA-256: `{digest}`
- Source fingerprint SHA-256: `{anchor["sha256"]}`
- Source objects in fingerprint: `{len(anchor["objects"])}`
- Work package: `{manifest["workPackage"]["id"]}` / `{manifest["workPackage"]["state"]}`

## Actual product callers

{render_product_callers(manifest)}

## Actual call graph

```mermaid
{render_sequence(manifest)}
```

The physical exact-body observer is now present. The remaining architectural distinction is that
strict compilation/staging is not yet the default sole path and the current admission snapshot plus
V2 terminal receipt are not yet both resolved inside the same provider-attempt lifecycle.

## Concrete adapter truth

{adapters}

## Supported roles

{render_role_support(manifest)}

Unsupported roles remain fail closed. They must not be silently projected into the developer slot.

## Legacy path

- Current state: {manifest["legacyPath"]["state"]}
- Cutover condition: {manifest["legacyPath"]["cutoverCondition"]}

Legacy V1 receipts are compatibility evidence only and are never promoted into the V2 proof chain.

## Proof steps not yet closed

{open_items}

This document records source composition only. It grants no independent acceptance, activation,
promotion or release authority.
"""


def render_all(manifest: dict[str, Any]) -> dict[Path, str]:
'''
    replace_once(GENERATOR, insert_before, current_path_fn)
    replace_once(
        GENERATOR,
        '''        ROOT / manifest["artifacts"]["executionDossier"]: render_dossier(
            manifest, digest
        ),
''',
        '''        ROOT / manifest["artifacts"]["executionDossier"]: render_dossier(
            manifest, digest
        ),
        ROOT / manifest["artifacts"]["currentProductPath"]: render_current_product_path(
            manifest, digest
        ),
''',
    )


def update_qualifier() -> None:
    replace_once(
        QUALIFIER,
        '''    ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json",
    ROOT / "qualification/module-execution-dossiers/detail/context.compiler.md",
''',
        '''    ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json",
    ROOT / "docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md",
    ROOT / "qualification/module-execution-dossiers/detail/context.compiler.md",
''',
    )


def main() -> int:
    update_manifest()
    update_generator()
    update_qualifier()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
