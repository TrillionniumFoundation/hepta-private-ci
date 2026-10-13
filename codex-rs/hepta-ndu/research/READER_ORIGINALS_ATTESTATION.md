# Reader case ledger: verify pinned original bytes before admitting a Cell experiment

Research-only continuation of PR #1546. The previously added two independently
pinned Ed25519 reviewer signatures and signed **per-question, four-condition**
verdict ledger remain mandatory. They were insufficient to establish whether
reviewers saw the original question, exact Reader input IDs, unmodified output
or originally delivered source bytes. This increment adds a **third**,
independently operator-pinned observed-source manifest as a mandatory condition
for a *passing* Reader gate. No owner approval, human judgment, production
activation or model inference is supplied here.

## Source manifest contract

Supply a JSON object with exactly `schema`, `cohort`, `model_binding` and `items`.
Schema: `hepta.reader.originals.v1`. Cohort/order and frozen Reader model
binding must equal the independently signed review payload. There must be
exactly four records per question: no_evidence, ordinary_retrieval,
human_sufficient, critical_premise_removed. The rows contain exactly:

- `item_id`, `condition` (existing IDs and arm names)
- `question_record`: the original unmodified object with identity, family,
  scope, content and ISO-8601 timezone-aware observed_at
- `input_ids`: exact ordered original integer token IDs, never re-tokenized
- `raw_answer`: exact original nonempty Reader-generated UTF-8 text
- `delivered_sources`: zero to 64 exact source records. Each record has identity,
  root, scope, session, observed_at, **full original UTF-8 content** and the
  exact start/end **byte offsets** of the excerpt supplied to the Reader.

The validator recomputes original question, input IDs, raw answer, delivered
source and **parsed [E1] citation** fingerprints. A source fingerprint binds
its owner/root/scope/session/time, original full-content digest, source byte
window and selected excerpt. The citation list is derived from the actual raw
answer and original delivered order, not accepted from a reviewer assertion.
It rejects a citation to an absent E-label, duplicated sources, malformed
UTF-8 offsets, cross-scope and future-dated evidence, mismatched original
cohorts/readers, oversized cases or missing conditions. Only strict bracketed
`[E#]` syntax is recognized; unbracketed E-label echo is NOT a citation.

**External trust** is essential: the operator MUST obtain the immutable source
manifest from an independently authenticated producer, check original bytes,
and configure `HEPTA_READER_ORIGINALS_SHA256` **outside the reviewed payload**.
The separately externally pinned trust manifest must contain the same
`originals_sha256`; the review packet and reviewer keys retain their
independent prior pins. Self-supplied SHA strings and test fixtures must NOT
be treated as independent human evidence.

The CLI allows the additional optional positional argument for the exact
originals manifest *after* the existing Reader gate, review manifest and
reviewer roster. Absence of this file or its external pin keeps every one of
the 768 planned Cell/Stem positions BLOCKED with zero neural calls. The gate
revalidates the raw-source concordance only after verifying the two signatures,
case ledger and previous thresholds. It never uses gold answers as model input
or credits model predictions as human judgments.

## Security and science boundaries

Verification of an externally pinned source package is a necessary provenance
check, NOT proof that the operator chose authentic data, that sources are
semantically sufficient, that human reviews are independent, or that reviewer
verdicts are true. Operator authorization and real independent adjudication
remain absent. All tests use synthetic source records and ephemeral keys only
for testing. No keys or fake signed reviews are shipped as qualification.

No Reader/Encoder weights, NDU/Riccati/FBSDE math, production serving,
full-regression blocking-ci, or independent natural-task results change.
`production_accepted=false`, `human_review_available=false`,
`neural_calls=0` in default CI. Full 768-row matrix remains blocked.
