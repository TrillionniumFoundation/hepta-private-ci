# cognitive.store threat model and test map

## Assets

Memory/source payload, citations, fact sets, tombstone frontier, writer generation, current-cut witness, authority state/token, signing trust, active-generation pointer, production receipts and deletion/export evidence.

## Trust boundaries

- external current-cut and authority signer;
- Agentd product host;
- `hepta-cognitive-store` semantic façade;
- `hepta-memory` physical SQLite owner;
- filesystem/database/WAL and backup owners;
- downstream projection, learning, artifact and external destination owners.

## Threats and controls

| Threat | Control | Required test/evidence |
|---|---|---|
| Product bypasses sealed writer | default-hidden raw alias plus repository architecture verifier | boundary receipt on exact SHA |
| Dead source escapes compilation | closed-world top-level Rust module reachability check | orphan negative fixture |
| Cross-Agent/workspace write | owner/scope binding in access, stable id and authority lease | mismatch tests |
| Stale predecessor overwrites correction | SQLite/V2 CAS and exact expected revision | concurrent writer one-win/one-conflict |
| Tombstone resurrection | terminal lineage rule and current tombstone frontier | reopen/backup restore tests |
| Old valid backup accepted | independently signed exact-current-cut witness | stale-cut recovery rejection |
| Symlink/path/TOCTOU replacement | canonical external paths, regular-file/link/mode/identity checks and descriptor recovery | hostile filesystem tests |
| Authority self-minting | Agentd has no signing key; external signed state and opaque token required | missing/forged signature/token tests |
| Live revocation ignored | state re-read before every write; monotone revision/predecessor check | signed revocation blocks next mutation |
| Authority rollback/replay | exact next state revision/digest and fresh writer generation | regressed/skipped/equal-revision-drift tests |
| Token disclosure | separate 0600 file; digest-only receipts/debug | canary secret scan |
| Partial source/Memory/fact/provenance commit | one `BEGIN IMMEDIATE` transaction | injected semantic failure leaves identical cut |
| Response loss causes duplicate mutation | stable operation identity and committed occurrence query | response-loss/restart duplicate test |
| Pointer rename ambiguity laundered | `Indeterminate`, preserve candidate, no ordinary-open fallback | publication fault injection |
| Projection becomes authority | immutable fact subledger and deterministic rebuild | full/incremental oracle equivalence |
| Oversize/DoS input | byte/count/page/recovery bounds before allocation/publication | max+1 tests and perf profiles |
| Sensitive payload in logs/evidence | digest/redaction policy; bounded command artifacts | secret/provider leakage scan |
| Logical delete misreported as erasure | lifecycle taxonomy and per-owner delete dispositions | runbook review and restore drill |
| Derived model retains deleted source | source-support revocation and separate unlearning claim | artifact/model owner receipt or explicit unsupported disposition |

## Residual risks

- Host root compromise can replace externally trusted files and storage; hardware/OS attestation is outside this module.
- A valid signed witness proves equality to the signed cut, not that the signer selected the globally latest state; signer governance must establish currentness.
- SQLite `FULL` and fsync behavior depend on the selected filesystem/device profile.
- Tombstones cannot guarantee third-party deletion or model unlearning.

## Review triggers

Security review is mandatory for new write entrypoints, scope meanings, authority fields, migrations, archive/backup paths, network exports, model training use, token handling or recovery publication semantics.
