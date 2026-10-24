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

## Additional original JSON FILE pin and unambiguous parsing

The original-source attestation now distinguishes TWO different SHA256 values:

1. **Exact original-file bytes**, independently operator pinned as
   `HEPTA_READER_ORIGINALS_FILE_SHA256`. Compute this with `sha256sum` on the
   actual UTF-8 JSON file obtained from the authenticated producer. This hash
   covers whitespace, literal Unicode encoding, key ordering and ALL raw input
   bytes. It must not be taken from inside the file or from an untrusted review.
2. **Canonical parsed ORIGINALS object**, previously pinned as
   `HEPTA_READER_ORIGINALS_SHA256` and repeated in the signed trust manifest's
   `originals_sha256`. Canonicalization is sorted-key, compact JSON,
   `ensure_ascii=False`, UTF-8, with nonfinite values forbidden. For example,
   `reader_originals_attestation.canonical_sha(parsed_object)` produces this
   digest. The file pin and canonical pin are intentionally distinct.

A CLI invocation with an original source file but NO separate original-file
pin fails *before admission*, without creating a neural result. JSON inputs
are bounded and decoded as strict UTF-8; nested or top-level duplicate keys,
NaN/Infinity, non-object roots, symlinks and unknown oversized files fail.
This disallows the old ambiguity in which different raw JSON files could
parse to the same object under the canonical trust digest. Non-ASCII source
bytes and escaped Unicode strings with identical parsed content do NOT share
an identical **file** SHA, while a canonical object SHA remains stable.
The programmatic `evaluate_reader_gate` API still expects externally
authenticated dict objects; use the pinned CLI for provenance of real files.

A successful parser, four separate operator pins, two valid authorized Ed25519
signatures and complete per-case original evidence only establish mechanical
concordance. They do not establish authentic producer identity, genuine
reviewer independence, correctness or grounded semantics. The CI still
supplies NO real keys, no external originals and no human verdicts; all
768 experiment rows remain blocked.

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

## Cross-condition original-source immutability

Within each exact scope, an original source `identity` reused by any reviewed
question/condition must keep the same root, session/version, observed timestamp,
and **full original UTF-8 content bytes**. Distinct byte windows on the same
immutable original are permitted. A change to the source's original bytes or
owner/version under the same identity rejects the complete review census, even
if individual per-arm hashes and reviewer rows were recomputed consistently.
This is an identity-consistency check, not proof that the externally supplied
owner records or human assessments are authentic.

## Machine-verifiable exact refusals and canonical citations (research v1)

The frozen Reader prompt registers the **literal** response
`I do not have enough evidence.` for evidence-insufficient questions. It is
not a semantic or reviewer-discretionary category. Original-source audit now
checks both directions: `exact_refusal=true` requires exactly those original
UTF-8 output bytes, and an actual exact refusal cannot be labeled false.
A signed reviewed ledger and matching answer digests do **not** override this
raw-text invariant. Other quoted, case-changed or trailing-content responses
are not exact refusals; unknown/failed model work stays unknown.

Only the actually delivered `[E1]`, `[E2]` citation syntax can be bound to
original source fingerprints; ambiguous padded labels such as `[E01]` no
longer alias `[E1]`. This remains a **syntax/provenance** test, not independent
semantic judgment of grounded claims.

Same-case duplicate, invalid scope and future-time errors retain their
existing deterministic rejection semantics. Cross-condition reuse of a source
identity with different original bytes or owner metadata remains a separate,
fail-closed rejection. Local replay from the exact GitHub source blobs plus
the reviewer test fixture passed 59 focused tests; hosted full regression and
signed-source checks remain the admission gates. No independent human review
or approval is thereby created; 768 neural rows stay blocked by default.

## Citation-only raw outputs cannot satisfy a grounded verdict

The original frozen Reader often echoed `E1`, `E2` source labels instead of
answering. Before this added check, a human-review row marking a raw `"[E1]"`
as `grounded_and_cited=true` could survive mechanical source review if the
response hash and signed cited-source fingerprint were internally consistent.
That output has **no substantive answer text**; the citation alone is not an
answer. The source auditor now rejects a **positive** grounded verdict when,
after removing genuine `[E#]` citations and bare `E#` echoes, no alphanumeric
answer content remains, or the remaining output is exactly the registered
no-evidence refusal sentence. Cases marked ungrounded are retained intact for
review and failure accounting; numeric answers such as `42 [E1]` and Unicode
answers such as `设备已核验 [E1]` are not rejected on formatting grounds alone.

This is a strictly **necessary mechanical-format check** on a claimed positive
reviewer verdict. It is NOT sufficient evidence of answer correctness, citation
semantic support, adequate source sufficiency or independent human judgment.
The existing four source/manifest pins, independently authorized signatures,
full case-level review ledger, strict exact-refusal check, and >=75%/90% Reader
thresholds remain mandatory. Default CI still has no operator-approved human
source material: all 768 prospective neural rows remain blocked.
