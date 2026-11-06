# STRICT as-of stem rank direction — independent immutable audit

This is an **observational development audit**, not learned policy selection,
semantic citation judgment, model training or a production qualification.

## Why this audit exists

The preregistered six-arm MemoryCell experiment reached **576/576 successful
policy attempts** under the as-of Reader/source gate, but the independent
read-only decision audit did **not** identify a learned native source-choice
gain over the original frozen ranker on test or transfer.

The earlier label-free score geometry already stores the original frozen
Encoder winner, adapter-only Encoder winner, combined Head winner, score
margins and the **infimum nonnegative scaling factor** of the actual learned
residual that could reverse the original top-1. This audit asks a narrower
mechanical question before proposing any more training:

* **Residual direction impossible:** No nonnegative scale of the recorded
  residual can reverse the frozen winner. More training steps amplifying
  that exact direction are not enough.
* **Residual direction viable but weak:** The lowest flip scale is greater
  than 1 on a matched candidate pool. The trained residual points somewhere
  capable of outranking the frozen winner but is too small at scale 1.
* **Observed top-1 flip:** Already happened at the actual checkpoint. Its
  evidence correctness must be separately evaluated using pinned native
  documents and a blinded semantic reviewer.

A numerical equality boundary is **not** itself a deployed policy and lexical
ties may still select the original winner. No coefficient is chosen from held-out
labels, no Reader invocation is triggered, and no current inference action
is changed.

## Pinned source and integrity checks

* Strict generator: `cb9e98365b5f46e00fb2693f548a7215b1ed1145`.
* Strict source tree: `022c9aa8abc095c91ef744644329aaed12564859`.
* Exact Actions artifact: `11702192907`, transported ZIP SHA256
  `be3393f448993451c7860e8867e28a79f5fb7f95d5773f79ed55b30d12a84776`.
* Complete internal `SHA256SUMS` is verified by the existing bounded,
  non-extracting `PinnedArchive`.
* Verify all **576** originally registered policy records, **72** stage/phase/arm
  geometry groups and their original generated summary counts. Reject any
  missing or duplicate question, route drift, changed generator receipt,
  invalid scale, contradicted winner, source-family shift or a fake residual
  attached to the frozen control.

Run via `hepta-memory-stem-rank-direction.yml`: it executes synthetic
negative tests and a *read-only, model-free* archive audit. All reports, errors,
source code and checksums are saved. The audit does not include source texts,
native answers, held-out gold labels or fresh model-generated responses.

## Decision gates

Even if some residuals could hypothetically flip with larger amplitude, it
would be unsound to rescale them based on current evaluation labels. The
registered TRAIN-only validation protocol, independent source-family holdout,
fixed frozen Reader and human-reviewed evidence sufficiency/citation
entailment remain prerequisites for accepting a learned Cell.

The historical 16 test/transfer questions represent only three native
source-family groups and cannot establish independent generalization by
repeating checkpoint observations. A frozen source-only RRF grid also
returned no source rescue in the earlier pinned run; that negative result
cannot be declared a victory for a Head. Current evidence remains
`semantic_citation_precision=null`, `production_accepted=false`.

If the audit reveals wrong-direction residuals or large frozen margins,
prioritize genuinely distinct, independently support-reviewed contrastive
training source families and candidate coverage before increasing the count
of small Cell heads.

## Forward-only score-vector receipts for independent recalculation

The immutable historical ZIP contains derived rank scores, winner identities,
margin totals, and a digest of its original three score vectors, **but not
those complete numeric vectors themselves**. The historical rank-direction
audit consequently verifies all source-pinned **saved counts and internal
relations**, not the original floating-point calculations from raw logits.
This distinction must not be omitted in any claim.

The future native six-arm runner now emits one **pre-Reader**
`selection-score-journal.jsonl` row for each actually reached source
selection. Every row contains the original frozen Encoder, the potentially
adapted Encoder and the saved Head's **candidate logits**, original candidate
identity hashes and immutable pool/feature SHA-256s, plus the actual
selection and geometry digest. It retains the separate null logit without
using it to change the original forced-top1 decision. No evidence excerpts,
answers, benchmark target labels, revoked contents, or secret keys are
inserted into this score-vector journal.

A separately implemented standard-library
`stem_score_replay.py` recomputes **all winner identities, original/adapter/
Head score gaps, numerical residuals and scale infima from the stored raw
logits**, verifying that they match the unchanged original geometry and
policy records. It checks every journal row against a canonical policy
identity, and rejects fabricated score hashes, invalid adapter attribution,
nonfinite values, duplicate rows and missing receipts. Reader failures
cannot erase a selection already recorded: the selection and journal
are persisted before evidence materialization and Reader generation.
The replay is attempted even after model-run failure when usable receipts
are available and remains explicitly nonqualifying.

This is a reproducibility and attribution safeguard, **not** authority to
amplify residual scores on held-out data, a semantic evidence review, an
improvement in learning, or a production deployment gate.
