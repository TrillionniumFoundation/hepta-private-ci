# Canonical source, branch and base-drift policy

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness
**Parent plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0
**Status:** documentation-ready; no selection, merge, promotion or release authority

## 1. Scope and authority boundary

This specification removes branch-name ambiguity in source qualification and runtime coordination. A branch name, pull-request number, generated status file, cached CI result or human phrase such as “latest” does not identify immutable source bytes. A coordinator-admitted envelope is valid only when it binds an exact repository, base commit and tree, source commit and tree, document-set digest, observation time and bounded freshness policy through `CanonicalSourceReceiptV1`.

Ordinary authorized implementation follows `docs/DEVELOPMENT.md` and `PARALLEL_DEVELOPMENT.md`: identify the actual Git baseline, owned paths, relevant contracts, tests and dependencies, then perform the work. CI derives source and merge identities from its event. A separately handwritten receipt, expiring lane envelope or deployment decision is not an additional permission requirement for editing, testing or merging authorized repository changes. The stricter receipt and freshness rules below still apply when a runtime coordinator admits an envelope or a qualification consumer accepts evidence.

The base used to author this overlay is `d75a857bff625fb79663eb16544ebc7f74093859` with tree `b2528aad39cbd6362e12504adca2140549063c69`. That identity is provenance, not a claim that the resulting overlay commit is selected. Dynamic Git, CI, review and repository-administration facts remain external receipts.

## 2. Source identity model

Every source-qualification or coordinator-admission attempt consumes one immutable tuple:

```text
(repository_id, repository_full_name,
 base_commit, base_tree,
 source_commit, source_tree,
 optional_merge_commit, optional_merge_tree,
 document_set_digest, observed_at, ttl_seconds)
```

The tuple is canonical only when every Git object resolves, the tree matches its commit, the document-set digest covers all paths in `docs/governance/DOCUMENT_SYSTEM.json`, and the observation is within the configured TTL. A source receipt never grants write or execution authority. It only identifies bytes.

`docs/CURRENT.json` may store stable repository and baseline policy, but a live pull-request number is resolved by an external exact-candidate receipt rather than cached as a durable fact. Teams record the receipt digest in every `ParallelLaneEnvelopeV1`, benchmark, fixture and candidate artifact.

## 3. Branch classes and purpose manifests

Branches are classified as `canonical_candidate`, `implementation_package`, `integration`, `diagnostic`, `evidence`, or `archive`. Each non-canonical branch must carry a `BranchPurposeManifestV1` in its work envelope with base identity, allowed paths, expiry and zero authority delta.

- `canonical_candidate`: one bounded, reviewable candidate intended for the selected line.
- `implementation_package`: a module or integration package with exact write paths and predecessors.
- `integration`: deterministic composition of already identified package candidates.
- `diagnostic`: read-only or throwaway investigation; never imported as authority.
- `evidence`: immutable evidence bytes and manifests; no source mutation.
- `archive`: ancestry preservation only; never a coding base without a new source receipt.

A branch may change class only by issuing a new manifest. Archive, diagnostic and evidence branches cannot be silently reused as implementation bases.

## 4. Exact-source and merge-candidate algorithm

For pull-request evaluation:

```text
1. fetch the declared base and source commits;
2. verify source parent policy required by the repository gate;
3. verify source tree and canonical document-set digest;
4. run source-head validation at the exact source commit;
5. construct a deterministic merge tree from ordered base and source parents;
6. create an ephemeral merge commit with fixed identity metadata;
7. run the same validation at the merge candidate;
8. emit source and merge CanonicalSourceReceiptV1 records;
9. retain receipts as immutable CI artifacts.
```

GitHub’s convenience merge SHA is not accepted as the sole merge identity because it may be stale or reconstructed. Parent order is always base then source. A merge tree mismatch is a hard failure.

## 5. Base drift and freshness

Any change to base commit, base tree, canonical registry, required workflow, contract digest, module ownership or readiness overlay invalidates outstanding coding envelopes. The response is `BASE_DRIFT`; teams rebase, regenerate receipts and rerun all mandatory checks. Results are never transplanted from an old tree by assertion.

Freshness uses the `dynamicObservationPolicy` in `docs/CURRENT.json`. Future timestamps beyond skew, expired observations and receipts with a different repository identity are rejected. CI success is attached to an exact commit and does not float with a branch ref.

## 6. Failure semantics

| Code | Condition | Required disposition |
|---|---|---|
| `SRC-E001` | Git object missing | reject |
| `SRC-E002` | commit/tree mismatch | quarantine evidence and reject |
| `SRC-E003` | document-set digest mismatch | reject and regenerate inventory |
| `SRC-E004` | stale or future observation | reject |
| `SRC-E005` | source parent policy violated | recast candidate or restack |
| `SRC-E006` | merge parent order or merge tree mismatch | reject |
| `SRC-E007` | branch purpose absent or expired | reject coordinator envelope admission |
| `SRC-E008` | base drift after evaluation | invalidate all dependent receipts |

No failure may be converted into “probably current.”

## 7. Security controls

Receipts contain safe identifiers and digests, not credentials. Checkout uses read-only permissions and `persist-credentials: false`. Generated candidates cannot modify the workflow, verifier or evidence that judges the same candidate unless a separately scoped governance package and independent review are present. Symlink, case-folding and path-normalization checks run before allowed-path comparison.

## 8. Verification fixtures

Mandatory fixtures include a valid direct-child source, wrong source tree, stale receipt, future timestamp, reordered merge parents, altered canonical path inventory, diagnostic branch without a manifest, archive branch reused as a base, and base drift after successful tests. Only the valid source and deterministic merge pair pass.

Property tests assert that changing any tuple member changes the semantic digest, branch renames do not change source identity, and identical bytes at different commits remain separately attributable. The global and readiness workflows execute source-head and synthetic-merge validation.

## 9. Coding-entry checklist

Begin an authorized coding task once its source baseline, owned paths and relevant contract/dependency boundaries are identified. Review affected consumers when semantics change; unrelated lanes can continue. A runtime coordinator admitting `ParallelLaneEnvelopeV1` must additionally validate the current `CanonicalSourceReceiptV1`, `BranchPurposeManifestV1`, allowed paths, contract/document digest, expiry and base-drift checks. Selection, merge, promotion and release remain distinct decisions; repository merge does not itself activate a runtime or deployment boundary.

## Appendix A. Closed gap and protocol mapping

This appendix is a closed-world traceability projection. Each identifier is normative in `READINESS.json`, `PROTOCOLS.json` or `GAPS.json`; this Markdown file does not redefine the registry record.

Protocols:

- `BranchPurposeManifestV1`
- `CanonicalSourceReceiptV1`
- `IntegrationCheckpointV1`

Closed documentation gaps:

- `RDY-GAP-SRC-001`
- `RDY-GAP-SRC-002`
- `RDY-GAP-SRC-003`
- `RDY-GAP-SRC-004`

Bound work packages:

- `DOC-0-CANONICAL-DOCUMENT-CONSOLIDATION`
- `DOC-1-V8-SEMANTIC-UPGRADE`
- `DOC-2-DEFAULT-BRANCH-SELECTION`
- `DOC-3A-SOURCE-BINDING-RECONCILIATION`
- `DOC-3B-MODULE-TECHNICAL-DOCUMENTS`
- `DOC-3C-MODULE-DOC-CLOSED-WORLD`
- `DOC-3D-ADAPTIVE-ALGORITHM-DOC-CLOSED-WORLD`
- `DOC-3E-PRECODING-READINESS-CLOSED-WORLD`
- `DOC-REGISTRY-CLOSED-WORLD`
- `ECP-1-ENGINEERING-CONTROL-PLANE`
- `P0.7A-RUNTIME-BOOTSTRAP`
- `P0.8B-READINESS`
- `P0.8C-RESOURCE-BUDGETS`
- `P0.9-EXTERNAL-GATES`
- `SELF-1-CODE-CANDIDATE-PIPELINE`
