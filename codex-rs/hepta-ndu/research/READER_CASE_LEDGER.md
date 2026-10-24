# Source-bound per-question Reader review gate

Research-only PR #1546. This is a stricter prerequisite for the 768-position
shared Stem/Cell matrix, not a model result or production switch.

## Why the dual-signature aggregate is insufficient

The previous gate checked two authorized Ed25519 signatures over four
aggregate Reader scores, an independently pinned review-manifest digest,
and a separately pinned reviewer-key roster. Aggregates do not reveal WHICH
original question, evidence span, exact model output or citation a reviewer
examined. A summary-only review can conceal missing work and source errors.

An aggregate-only signed v2 receipt is NO LONGER sufficient to unblock rows.

## Mandatory individually reviewed cases

The Reader gate now requires exactly four reviewed cases per original
question ID: no_evidence, ordinary_retrieval, human_sufficient, and
critical_premise_removed. Each case is a signed-content object with exactly
these fields:

- item_id: the original question identity
- condition: one of the four registered interventions
- question_sha256: digest of the original question record
- prompt_input_ids_sha256: digest of the original encoded model input
- raw_answer_sha256: digest of the unaltered generated response
- delivered_source_sha256: ordered array of original byte/span fingerprints
- cited_source_sha256: original source fingerprints actually cited
- grounded_and_cited: Boolean independent human verdict
- exact_refusal: Boolean independent human verdict

Every digest is lowercase SHA256. The review owner must independently
authenticate those fingerprints against immutable original questions, source
bytes, exact prompts and model answer archives. Passing string/hash
validation alone does not prove authentic data or semantic correctness.

The ledger checker requires one unique row for every question/condition;
stable question identity across all four conditions; distinct delivered
and cited source fingerprints; citations attached to actually delivered
sources; and an observed cited source for each positive grounded verdict.
A grounded verdict and exact refusal cannot both hold. No-evidence must
contain no sources. Human-sufficient must contain sources. Critical-premise
removed must actually exclude a formerly sufficient source; the checker
rejects any claim that this missing-premise condition is grounded.

For every arm, the published grounded/refusal totals are recomputed from
the individual reviewed cases. Missing/duplicate rows, invalid data types,
a mismatched aggregate or altered source linkage fail closed.

## Signature and trust boundaries remain in force

The ENTIRE case list now participates in the signed reviewed-content digest.
Two different verified authorized reviewers must sign it with the same
domain-separated Ed25519 verification process; owner-approved independent
review-manifest SHA256 and public reviewer-roster SHA256 pins remain required.

Test fixtures use ephemeral cryptographic keys IN MEMORY solely to validate
verification behavior. They are not human reviews or keys to use in production.
The software cannot attest genuine human identity, conflict-of-interest
independence, reviewer diligence or semantic evidence support. The external
operator must verify the original source archive, authorize reviewer identities
and provide authentic blinded judgments and both pins before enabling a row.

No Reader/Encoder training or inference, NDU/Riccati/FBSDE API change, or
production configuration is part of this hardening. The prior adequacy gates
of at least 75 percent grounded responses with sufficient evidence and
90 percent no-evidence/missing-premise refusals remain required.

Default CI has NO reviewer material and must report 768 blocked rows, zero
planned neural executions, zero neural calls and production_accepted false.
CI runs the signature and case-ledger tests plus scoped Ruff F/E9 lint.

## Non-confounded premise-removal contract

The `critical_premise_removed` source-fingerprint set must be a **strict subset**
of the *same question's* `human_sufficient` set. The comparison rejects any
additional or replacement source, not just a missing necessary source. It is
not sufficient for the new set to omit one source while silently inserting
another: doing so changes both the intervention and the available evidence.
This check still cannot independently judge semantic sufficiency.
