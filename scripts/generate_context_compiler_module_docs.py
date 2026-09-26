#!/usr/bin/env python3
"""Generate the context.compiler technical truth set from one manifest."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/modules/context.compiler/MODULE_MANIFEST.json"


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def manifest_digest(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def render_status_table(manifest: dict[str, Any]) -> str:
    labels = {
        "coreImplementation": "Core implementation",
        "productComposition": "Product composition",
        "v2ProviderClosure": "V2 provider closure",
        "currentHeadQualification": "Current-head qualification",
    }
    rows = ["| Dimension | State | Evidence-based interpretation |", "|---|---|---|"]
    for key, label in labels.items():
        state = manifest["status"][key]
        rationale = manifest["statusRationale"][key]
        rows.append(f"| {label} | **{state}** | {rationale} |")
    return "\n".join(rows)


def render_sequence(manifest: dict[str, Any]) -> str:
    labels = [step.replace('"', "'") for step in manifest["sequence"]]
    lines = ["flowchart TD"]
    for index, label in enumerate(labels):
        lines.append(f'    N{index}["{label}"]')
        if index:
            lines.append(f"    N{index - 1} --> N{index}")
    return "\n".join(lines)


def render_byte_table(manifest: dict[str, Any]) -> str:
    rows = [
        "| Object | Owner | Exact material | Digest / witness | Security meaning |",
        "|---|---|---|---|---|",
    ]
    for entry in manifest["byteIdentities"]:
        rows.append(
            "| {name} | {owner} | {material} | `{digest}` | {securityMeaning} |".format(
                **entry
            )
        )
    return "\n".join(rows)


def render_technical(manifest: dict[str, Any], digest: str) -> str:
    surface = "\n".join(f"- `{entry}`" for entry in manifest["publicSurface"])
    roots = "\n".join(f"- `{entry}`" for entry in manifest["sourceRoots"])
    commands = "\n".join(
        f"{index}. `{command}`"
        for index, command in enumerate(manifest["qualification"]["commands"], start=1)
    )
    open_items = "\n".join(f"- {entry}" for entry in manifest["knownOpenItems"])
    return f"""<!-- GENERATED FILE: edit MODULE_MANIFEST.json and run {manifest["generatedBy"]} --write. -->
# `context.compiler` technical development guide

## 1. Provenance and implementation state

- Module: `{manifest["module"]}`
- Reviewed base SHA: `{manifest["reviewedBaseSha"]}`
- Working branch: `{manifest["branch"]}`
- Source manifest: `docs/modules/context.compiler/MODULE_MANIFEST.json`
- Canonical manifest SHA-256: `{digest}`
- Generator: `{manifest["generatedBy"]}`

{render_status_table(manifest)}

The state words above are deliberately independent. A complete core library does not imply that
the product host has supplied exact final-request bytes, a qualified tokenizer, durable terminal
composition, or a successful receipt for the current Git SHA.

## 2. Scope and trust boundary

`context.compiler` selects admitted context under a deterministic budget, verifies the realized
selected bytes, emits a canonical context payload, rechecks a monotonic admission snapshot
immediately before dispatch, and authenticates provider terminal evidence. It does not own network
I/O, provider credentials, model execution, or the provider-specific request encoder.

The strict V2 boundary treats admission verifiers, provider framing policies, exact tokenizers and
provider evidence verifiers as qualified host capabilities. Missing capabilities and identity
mismatches fail closed. Candidate-level registered token costs may guide preselection, but they are
not accepted as proof of the final provider request token count.

## 3. Authoritative source locations

{roots}

Public strict-path surface:

{surface}

## 4. End-to-end target sequence

```mermaid
{render_sequence(manifest)}
```

The current product source reaches compilation, attachment staging and provider-policy dispatch.
The strict path intentionally remains marked **partial/incomplete** until the host constructs
`VerifiedProviderRequestV2`, runs a profile-bound `ExactProviderRequestTokenizerV2`, submits those
attested bytes without reconstruction, and persists the resulting `ContextDeliveryReceiptV2`.

## 5. Byte and digest identity model

{render_byte_table(manifest)}

These four identities must never be collapsed:

1. The canonical context bundle is a compiler-owned binary payload with complete segment coverage.
2. Prompt fragments are a product projection used during host composition.
3. The provider final request is the exact byte string submitted to the provider and tokenized.
4. The wire semantic digest binds canonical send semantics and is not a byte-for-byte request hash.

`verify_provider_request_coverage_v2` requires one and only one canonical-context segment. Every
other byte must belong to an approved typed-framing segment; offsets must be contiguous, nonempty
and cover the request exactly, and every segment digest is recomputed.

## 6. Core invariants

### 6.1 Admission and snapshot succession

- Admission records and snapshots are accepted only through a verifier identity.
- `VerifiedAdmissionSnapshotSuccessorV2` binds its predecessor digest and current verification
  digest.
- Reset snapshots, stale observation times, revocation-epoch rollback, revocation resurrection and
  authority-domain changes are rejected.
- `prepare_delivery_from_successor_v2` accepts the typed successor, not an unrelated independently
  verified snapshot.

### 6.2 Canonical serialization

- `CanonicalContextSerializerV2` is compiler-owned and deterministic.
- Its identity is derived from the canonical serializer domain, template digest and tool-schema
  digest.
- The payload contains a canonical envelope, typed item headers and exact selected item bytes.
- `CanonicalContextCoverageV2` covers byte zero through the final byte with no gaps or overlaps.
- Each selected item appears exactly once and carries its item ID, role and content digest.
- The low-level arbitrary prepared-payload pattern is not used by the strict API.

### 6.3 Exact final-request tokenization

`ProviderTokenizerIdentityV2` binds:

- provider identity;
- provider model identity;
- tokenizer binary digest;
- tokenizer version digest;
- vocabulary digest;
- normalization-policy digest.

`FinalProviderRequestTokenizationV2` additionally binds the final request digest, request coverage,
wire-semantic digest, model-profile digest, exact token count and exact request byte length. The
tokenizer identity digest must equal the profile tokenizer digest. A missing tokenizer, a digest
mismatch, zero tokens or a count above the model limit blocks dispatch.

### 6.4 Provider evidence and durability

The existing V2 observer validates `ProviderInvocationReceipt`, provider/model identity, exact
ephemeral input binding, provider witness and terminal disposition before minting
`ContextDeliveryReceiptV2`. Product completion requires Agentd to persist the preparation and
receipt as the sole serving/terminal path. A parallel V1 runtime digest may remain for migration,
but it is not sufficient to mark V2 provider closure complete.

## 7. Failure model

All strict APIs are fail-closed. Representative rejection classes are:

- unverified, stale, reset or rollback admission snapshots;
- selected-byte mismatch, duplicate realization or oversized content;
- noncanonical serializer identity;
- segment gaps, overlaps, digest mismatches or unapproved framing;
- provider/model/tokenizer identity mismatch;
- tokenizer failure, zero count or final-request budget overflow;
- provider receipt without an exact input binding or terminal evidence;
- any proof object carrying non-deny authority.

No error path silently falls back to approximate token counting.

## 8. Test strategy

The focused suite includes:

- canonical serializer golden behavior;
- Unicode, embedded control-byte and large-input cases;
- mutation-based adversarial payload and segment-map rejection;
- framing gap, overlap, duplicate-context and unapproved-kind rejection;
- tokenizer binary/version/vocabulary/normalization identity mismatch;
- final-request budget overflow;
- typed snapshot reset, rollback and revocation-frontier checks;
- deterministic generated-corpus property coverage;
- existing compile, attachment, delivery and provider-evidence tests.

## 9. Qualification and immutable receipt

Workflow: `{manifest["qualification"]["workflow"]}`

Artifact: `{manifest["qualification"]["receiptArtifact"]}`

Qualification commands:

{commands}

The workflow writes a JSON receipt that is bound to `GITHUB_SHA`, records every command and exit
status, hashes the generated truth set, and uploads the receipt even on failure. Documentation must
continue to say `currentHeadQualification: absent` until an exact-head artifact shows every required
command succeeded.

## 10. Known open product items

{open_items}
"""


def implementation_map(manifest: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
        "schemaVersion": 3,
        "module": manifest["module"],
        "generated": {
            "manifest": "docs/modules/context.compiler/MODULE_MANIFEST.json",
            "manifestSha256": digest,
            "generator": manifest["generatedBy"],
            "reviewedBaseSha": manifest["reviewedBaseSha"],
            "branch": manifest["branch"],
        },
        "status": manifest["status"],
        "statusRationale": manifest["statusRationale"],
        "sourceRoots": manifest["sourceRoots"],
        "publicSurface": manifest["publicSurface"],
        "proofObjects": [
            "CanonicalContextCoverageV2",
            "CanonicalSerializedContextProofV2",
            "VerifiedAdmissionSnapshotSuccessorV2",
            "VerifiedProviderRequestV2",
            "FinalProviderRequestTokenizationV2",
            "ContextDeliveryPreparationV2",
            "ContextDeliveryReceiptV2",
        ],
        "byteIdentities": manifest["byteIdentities"],
        "targetSequence": manifest["sequence"],
        "productComposition": {
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
        "qualification": manifest["qualification"],
        "knownOpenItems": manifest["knownOpenItems"],
    }


def render_dossier(manifest: dict[str, Any], digest: str) -> str:
    open_items = "\n".join(
        f"{index}. {entry}"
        for index, entry in enumerate(manifest["knownOpenItems"], start=1)
    )
    return f"""<!-- GENERATED FILE: edit MODULE_MANIFEST.json and run {manifest["generatedBy"]} --write. -->
# Execution dossier: `context.compiler`

## 1. Evidence identity

- Reviewed base: `{manifest["reviewedBaseSha"]}`
- Working branch: `{manifest["branch"]}`
- Manifest SHA-256: `{digest}`
- Generator: `{manifest["generatedBy"]}`
- Qualification workflow: `{manifest["qualification"]["workflow"]}`
- Receipt artifact: `{manifest["qualification"]["receiptArtifact"]}`

## 2. Current truth matrix

{render_status_table(manifest)}

This dossier does not infer release qualification from source presence or a historical workflow.
Only a successful receipt whose `headSha` equals the reviewed commit may change the fourth state.

## 3. Implemented controls

- Verified admission records and complete revocation snapshots.
- Deterministic context selection with mandatory trusted/schema floors.
- Compiler-owned canonical serialization and complete byte coverage.
- Typed snapshot succession for the immediate pre-dispatch recheck.
- Exact provider-request coverage with one canonical context segment and approved typed framing.
- Tokenizer attestation bound to provider, model, binary, version, vocabulary and normalization.
- Existing provider-receipt validation and terminal disposition mapping.
- Deny-all authority on every newly minted proof.

## 4. Product composition finding

The source product path is real rather than hypothetical: prompt registry compilation feeds
`hepta-intelligence`, Agentd stages a runtime attachment, and the provider-policy extension observes
physical dispatch and terminal state. The composition remains **partial** because the current host
ABI exports semantic/request digests but not a qualified exact tokenizer over the final request
bytes. The strict API therefore blocks rather than treating registry token costs as final-request
proof.

## 5. Byte-identity audit

{render_byte_table(manifest)}

The acceptance criterion is byte identity, not merely semantic similarity. The provider send must
consume the request represented by `VerifiedProviderRequestV2`; rebuilding from fragments after
tokenization invalidates the attestation.

## 6. Required execution order

```mermaid
{render_sequence(manifest)}
```

## 7. Test evidence expected from the exact head

The qualification receipt must show successful formatting, focused compilation, strict clippy,
unit/adversarial/generated-corpus tests, cargo-deny, Bazel and repository source/readiness checks.
The workflow records failures instead of deleting or rewriting them and uploads the receipt with
`if: always()` semantics.

## 8. Remaining closure items

{open_items}

## 9. Reviewer decision

The core design is complete and materially stronger than the prior trusted-serializer/registered-
count path. Product release remains blocked on host exact-tokenizer composition, sole-path durable
V2 terminal accounting and an all-green receipt for the exact reviewed SHA.
"""


def render_all(manifest: dict[str, Any]) -> dict[Path, str]:
    digest = manifest_digest(manifest)
    return {
        ROOT / manifest["artifacts"]["technical"]: render_technical(manifest, digest),
        ROOT / manifest["artifacts"]["implementationMap"]: (
            json.dumps(
                implementation_map(manifest, digest),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ),
        ROOT / manifest["artifacts"]["executionDossier"]: render_dossier(
            manifest, digest
        ),
    }


def check_or_write(outputs: dict[Path, str], write: bool) -> int:
    failed = False
    for path, expected in outputs.items():
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
            continue
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual == expected:
            print(f"ok {path.relative_to(ROOT)}")
            continue
        failed = True
        print(f"out of date: {path.relative_to(ROOT)}")
        diff = difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=f"{path.relative_to(ROOT)} (actual)",
            tofile=f"{path.relative_to(ROOT)} (generated)",
            lineterm="",
        )
        for line in diff:
            print(line)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest = load_manifest()
    return check_or_write(render_all(manifest), args.write)


if __name__ == "__main__":
    raise SystemExit(main())
