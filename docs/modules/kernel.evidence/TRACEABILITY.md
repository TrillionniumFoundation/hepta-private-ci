# kernel.evidence closure traceability

Canonical machine-readable matrix: [TRACEABILITY.json](TRACEABILITY.json).

This table distinguishes repository-controlled implementation closure from
external independent acceptance. A source/test link is not an execution
receipt, and an exact-candidate CI receipt is not an independent semantic
decision.

| Requirement | Source | Native test | Exact-candidate execution evidence | Independent evidence |
|---|---|---|---|---|
| KE-EVID-001 authenticated append/idempotency | `src/qualification.rs`, migration 0011 | signed append + conflict tests | Lane A source-head / merge traceability receipt | native invariant; separate review not required |
| KE-EVID-002 exact candidate/tree query | `query_claim` | exact-tree + expiry test | Lane A exact-candidate receipt | native invariant |
| KE-EVID-003 predecessor/global hash chain | `verify_predecessor_chain`, reopen verifier | reopen integrity test | Lane A exact-candidate receipt | native invariant |
| KE-EVID-004 independent-role separation | `verify_chain` | one-principal/two-role rejection | Lane A exact-candidate receipt | native invariant |
| KE-EVID-005 expiry/revocation | state resolver + security-authority revocation | expiry + revocation tests | Lane A exact-candidate receipt | native invariant |
| KE-EVID-006 `IndependentDecisionReceiptV1` | typed prepare/append + immutable projection | typed decision reopen test | Lane A exact-candidate receipt | **pending external exact-candidate signer** |
| KE-EVID-007 anti-rollback/replacement | store instance + external checkpoint verifier | replacement/backward frontier test | Lane A exact-candidate receipt | **pending operator-owned external checkpoint retention observation** |
| KE-EVID-008 authenticated product writer | `hepta-evidence-writer` | underlying writer/rollback primitives + all-target compile/clippy | Lane A native receipt | **pending target-host execution observation** |
| KE-EVID-009 exact source/merge identity | Lane A workflow + traceability verifier | exact SHA/tree verifier | `kernel-evidence-source-head.json`, `kernel-evidence-merge-candidate.json` | **pending external semantic decision** |
| KE-EVID-010 no self-accept/release | implementation map + technical guide | traceability fail-closed verifier | traceability receipt | **pending external acceptance; activation/release false** |

## Independent-review handoff

Lane A also emits an independent-review request beside each exact-candidate
receipt. The request binds the candidate SHA/tree and SHA-256 of the complete
execution-evidence receipt. A distinct reviewer uses the reviewed trust policy
and `hepta-evidence-writer prepare-independent` /
`append-independent` flow to produce the actual signed
`IndependentDecisionReceiptV1`.

No repository-generated artifact may set `independentAcceptance=true`.
That transition requires the externally held signing identity and is intentionally
outside the generator's authority.

## Rollback boundary

The SQLite hash chain alone is integrity evidence, not an anti-rollback oracle.
Production admission must use an independently retained checkpoint generation.
Checkpoint bootstrap is allowed only on an empty qualification chain; later
writers verify the previous generation before mutation and create a new
checkpoint file after commit.
