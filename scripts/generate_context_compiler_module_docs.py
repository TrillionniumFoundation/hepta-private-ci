#!/usr/bin/env python3
"""Generate the context.compiler truth set from one machine-readable manifest."""

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


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def status_table(manifest: dict[str, Any], key: str = "status") -> str:
    labels = {
        "coreImplementation": "Core implementation",
        "productComposition": "Product composition",
        "v2ProviderClosure": "V2 provider closure",
        "currentHeadQualification": "Current-head qualification",
    }
    rows = ["| Dimension | State | Evidence-based interpretation |", "|---|---|---|"]
    for field, label in labels.items():
        state = manifest[key][field]
        rationale = (
            manifest["statusRationale"][field]
            if key == "status"
            else "Review baseline before this closure branch."
        )
        rows.append(f"| {label} | **{state}** | {rationale} |")
    return "\n".join(rows)


def sequence_diagram(manifest: dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    for index, raw in enumerate(manifest["sequence"]):
        label = raw.replace('"', "'")
        lines.append(f'    N{index}["{label}"]')
        if index:
            lines.append(f"    N{index - 1} --> N{index}")
    return "\n".join(lines)


def byte_table(manifest: dict[str, Any]) -> str:
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


def bullets(values: list[str], code: bool = False) -> str:
    if code:
        return "\n".join(f"- `{value}`" for value in values)
    return "\n".join(f"- {value}" for value in values)


def render_technical(manifest: dict[str, Any], digest: str) -> str:
    return f"""<!-- GENERATED FILE: edit MODULE_MANIFEST.json and run {manifest["generatedBy"]} --write. -->
# `context.compiler` technical development guide

## 1. Provenance and state model

- Module: `{manifest["module"]}`
- Reviewed base SHA: `{manifest["reviewedBaseSha"]}`
- Integration branch: `{manifest["integrationBranch"]}`
- Source manifest: `docs/modules/context.compiler/MODULE_MANIFEST.json`
- Canonical manifest SHA-256: `{digest}`
- Generator: `{manifest["generatedBy"]}`

### Review baseline

{status_table(manifest, "baselineStatus")}

### Candidate source state

{status_table(manifest)}

The four dimensions are intentionally independent. Source-complete composition does not self-grant
release qualification, deployment authority, provider credentials, or acceptance authority. The
checked-in truth therefore keeps `currentHeadQualification: absent`; only the external exact-head
receipt may establish that fact for one immutable commit.

## 2. Scope and trust boundary

`context.compiler` selects admitted context under a deterministic token budget, verifies the
realized bytes, emits a compiler-owned canonical context bundle, revalidates a monotone admission
snapshot immediately before physical dispatch, proves the exact encoded provider request, and
maps verified provider terminal evidence into a durable `ContextDeliveryReceiptV2`.

The module does **not** own provider credentials, network authority, model execution, deployment
approval, or release acceptance. Admission verifiers, provider framing policies, exact tokenizers,
and provider terminal verifiers are qualified host capabilities. Their absence or an identity
mismatch fails closed. Registered candidate token costs may guide deterministic selection, but they
are never accepted as proof of the final provider request token count.

## 3. Authoritative source map

{bullets(manifest["sourceRoots"], code=True)}

Strict product surface:

{bullets(manifest["publicSurface"], code=True)}

Construction-closed proof objects:

{bullets(manifest["proofObjects"], code=True)}

## 4. End-to-end provider-bound sequence

```mermaid
{sequence_diagram(manifest)}
```

The order is security-significant:

1. The selected registry projection is serialized by the compiler, not by an arbitrary caller.
2. The fresh typed snapshot successor is obtained immediately before final use.
3. The provider host finishes canonical request construction before exact tokenization.
4. A qualified provider/model framing verifier accepts all non-context request bytes.
5. Agentd durably claims the exact attempt before transport receives the body.
6. Terminal evidence is reconciled against the same preparation and final-request proof.

## 5. Byte and digest identity model

{byte_table(manifest)}

These identities must never be collapsed:

- **Canonical context bundle** proves the compiler-selected context bytes.
- **Prompt fragments** are a product projection and migration aid.
- **Provider final request** is the exact encoded HTTP body before compression or signing.
- **Wire semantic digest** binds secret-free transport semantics and terminal accounting.

The final request proof carries complete contiguous segment coverage, exactly one canonical context
segment, qualified framing identity, the byte digest, the wire-semantic digest, and an exact
tokenization receipt. A semantic digest is not a substitute for a byte digest; a fragment digest is
not a substitute for either.

## 6. Security invariants

{bullets(manifest["invariants"])}

### 6.1 Compiler-owned canonical serialization

The strict path calls `record_canonical_context_bundle_v2`. Selected item IDs, roles, content
digests, and exact UTF-8 content are encoded in a deterministic compiler-owned envelope. The
legacy generic serializer trait can remain for compatibility and testing, but product V2 closure
does not certify a caller-provided prepared payload.

### 6.2 Qualified provider framing

Complete byte coverage alone is insufficient: it can show where the context occurs without proving
that the other bytes belong to an allowed provider grammar. `FinalRequestFramingVerifierV2`
therefore validates the exact JSON request, provider/model binding, typed model-input fields, and a
one-and-only-one decoded context occurrence. Its identity digest is included in
`FinalProviderRequestProofV2`.

### 6.3 Exact final-request tokenization

`FinalRequestTokenizerIdentityV2` binds:

- provider identity;
- provider model identity;
- declared profile tokenizer;
- tokenizer executable digest;
- tokenizer version digest;
- vocabulary digest;
- normalization-policy digest.

Agentd hashes the configured executable and vocabulary, invokes the tokenizer as a bounded child
process, writes the exact encoded request to standard input, accepts only a strict positive decimal
count, and binds that result to the exact request digest. Estimates, candidate-cost sums, and
post-hoc provider usage are not accepted as pre-dispatch budget proof.

### 6.4 Typed snapshot succession

`VerifiedAdmissionSnapshotSuccessorV2` binds the attachment snapshot as predecessor and rejects
time rollback, revocation-epoch rollback, authority-domain changes, stale observations, and revoked
admission resurrection. `prepare_delivery_from_successor_v2` consumes this typed lineage object
rather than an unrelated freshly verified snapshot.

### 6.5 Durable dispatch and crash recovery

The exact-body observer runs after canonical JSON encoding and before compression/signing. Agentd
performs final-use revalidation, framing verification, tokenization, and an atomic durable pre-send
claim before the callback returns and transport may send the body. The send uses the same encoded
body object; rebuilding from fragments after proof is prohibited.

A durable pre-send without a terminal remains **indeterminate** after restart and blocks blind
replay. A terminal callback is idempotent only when its normalized terminal observation digest
matches the durable receipt. A different terminal for the same attempt is a conflict, not a retry.

### 6.6 Provider terminal evidence

Provider intent binds thread, turn, attempt, provider configuration, model, endpoint, request kind,
transport, logical request, wire semantics, and optional ephemeral input witnesses. Terminal
evidence is accepted only against the active preparation and final-request proof, then persisted as
a deny-all `ContextDeliveryReceiptV2`.

## 7. Failure model

Strict APIs fail closed for, among other cases:

- missing, stale, reset, rollback, or revoked admission state;
- selected-byte mismatch, duplicate realization, or oversized content;
- arbitrary serializer output on the strict product path;
- absent, ambiguous, duplicated, gapped, overlapping, or unqualified final-request segments;
- provider/model/tokenizer/framing identity mismatch;
- tokenizer absence, timeout, malformed output, zero count, or budget overflow;
- failure to durably claim the attempt before send;
- unresolved pre-send recovery, duplicate-attempt conflict, or terminal mismatch;
- provider evidence that does not bind the exact admitted attempt.

There is no approximate-token fallback and no V1 receipt accepted as V2 closure evidence.

## 8. Test strategy

{bullets(manifest["testMatrix"])}

Property tests exercise deterministic complete coverage and fail-closed mutations over generated
request shapes. Golden tests include Unicode, JSON escapes, control bytes, large payloads, and a real
subprocess tokenizer fixture. Product tests cover registry compilation, immediate revocation,
exact-body observation, crash recovery, terminal idempotency, and durable receipt reconciliation.

## 9. Exact-head qualification

Workflow: `{manifest["qualification"]["workflow"]}`

Receipt artifact: `{manifest["qualification"]["receiptArtifact"]}`

Required command set:

{bullets(manifest["qualification"]["commands"], code=True)}

The workflow checks out the exact candidate SHA, records every command, exit code, duration and log
digest, hashes this manifest and all generated truth files, verifies a clean worktree, and uploads the
receipt even when a command fails. The artifact name contains the head SHA. Historical green runs
or source presence do not qualify a different commit.

## 10. Operational requirements and open items

{bullets(manifest["knownOpenItems"])}

## 11. Change discipline

Edit `MODULE_MANIFEST.json`, regenerate all three truth artifacts, and commit them together. Direct
manual edits to this file, `IMPLEMENTATION_MAP.json`, or the execution dossier are rejected by the
qualification gate. Any change to the provider encoder, tokenizer ABI, framing policy, snapshot
authority, durable state schema, or terminal mapping requires a new exact-head receipt.
"""


def implementation_map(manifest: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
        "schemaVersion": 4,
        "module": manifest["module"],
        "generated": {
            "manifest": "docs/modules/context.compiler/MODULE_MANIFEST.json",
            "manifestSha256": digest,
            "generator": manifest["generatedBy"],
            "reviewedBaseSha": manifest["reviewedBaseSha"],
            "integrationBranch": manifest["integrationBranch"],
        },
        "baselineStatus": manifest["baselineStatus"],
        "status": manifest["status"],
        "statusRationale": manifest["statusRationale"],
        "sourceRoots": manifest["sourceRoots"],
        "publicSurface": manifest["publicSurface"],
        "proofObjects": manifest["proofObjects"],
        "byteIdentities": manifest["byteIdentities"],
        "targetSequence": manifest["sequence"],
        "invariants": manifest["invariants"],
        "testMatrix": manifest["testMatrix"],
        "productComposition": {
            "state": manifest["status"]["productComposition"],
            "singlePhysicalPath": (
                "codex-api exact encoded body -> qualified framing/tokenizer -> "
                "Agentd durable pre-send -> same-body HTTP send -> terminal receipt"
            ),
            "legacyEvidencePolicy": (
                "V1 records may be retained for migration and audit but do not satisfy "
                "V2 provider closure."
            ),
        },
        "qualification": manifest["qualification"],
        "knownOpenItems": manifest["knownOpenItems"],
    }


def render_dossier(manifest: dict[str, Any], digest: str) -> str:
    return f"""<!-- GENERATED FILE: edit MODULE_MANIFEST.json and run {manifest["generatedBy"]} --write. -->
# Execution dossier: `context.compiler`

## 1. Evidence identity

- Reviewed base SHA: `{manifest["reviewedBaseSha"]}`
- Integration branch: `{manifest["integrationBranch"]}`
- Manifest SHA-256: `{digest}`
- Generator: `{manifest["generatedBy"]}`
- Qualification workflow: `{manifest["qualification"]["workflow"]}`
- Receipt artifact: `{manifest["qualification"]["receiptArtifact"]}`

## 2. State transition

### Review baseline

{status_table(manifest, "baselineStatus")}

### Candidate source state

{status_table(manifest)}

The transition from partial/incomplete to source-complete is justified by the exact encoded-body
observer, compiler-owned serialization, qualified framing, real tokenizer execution, durable
pre-send fencing, provider terminal reconciliation, and crash-recovery tests. Qualification remains
absent until a receipt for the exact candidate SHA is green.

## 3. Implemented controls

{bullets(manifest["invariants"])}

## 4. Product-path finding

The product path is no longer a parallel V1 reconstruction:

```mermaid
{sequence_diagram(manifest)}
```

The codex-api endpoint encodes the canonical JSON body once. The observer receives that exact byte
buffer, Agentd completes fresh final-use verification and durable proof, and the endpoint submits
the same encoded object. The terminal callback carries the exact provider attempt into
`observe_final_provider_delivery_v2` and the durable V2 receipt store.

## 5. Byte-identity audit

{byte_table(manifest)}

Acceptance is byte-identity based. The canonical bundle, fragments, final request, and wire
semantics remain distinct objects with distinct owners and digest domains.

## 6. Crash, retry, and terminal audit

- Pre-send evidence is persisted and fsynced before transport release.
- A process restart does not reconstruct authority from a stored digest.
- An unresolved durable pre-send blocks blind replay for the attempt and turn.
- A repeated terminal callback is idempotent only for an identical normalized observation.
- A conflicting terminal or re-armed terminal attempt fails closed.
- Durable state is bounded, schema-checked, private, locked, atomically replaced, and directory
  synced.

## 7. Expected exact-head test evidence

{bullets(manifest["testMatrix"])}

The exact-head receipt must include the command line, working directory, exit status, duration, log
SHA-256, source/tree identity, toolchain versions, truth-file hashes, and clean-worktree result for
every required command.

## 8. Remaining operational conditions

{bullets(manifest["knownOpenItems"])}

## 9. Reviewer decision

The source candidate closes the previously identified serializer, framing, tokenizer, snapshot
lineage, physical-send, crash-retry, and terminal-receipt gaps. It is suitable for protected-branch
review. It is **not** represented as release-qualified until the external exact-head artifact passes
and branch-required CI and architecture checks are green.
"""


def render_all(manifest: dict[str, Any]) -> dict[Path, str]:
    digest = canonical_sha256(manifest)
    return {
        ROOT / manifest["artifacts"]["technical"]: render_technical(manifest, digest),
        ROOT / manifest["artifacts"]["implementationMap"]: (
            json.dumps(implementation_map(manifest, digest), ensure_ascii=False, indent=2)
            + "\n"
        ),
        ROOT / manifest["artifacts"]["executionDossier"]: render_dossier(manifest, digest),
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
        for line in difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=f"{path.relative_to(ROOT)} (actual)",
            tofile=f"{path.relative_to(ROOT)} (generated)",
            lineterm="",
        ):
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
