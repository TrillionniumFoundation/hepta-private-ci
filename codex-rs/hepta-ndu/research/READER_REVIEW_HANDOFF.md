# Offline handoff for independent Reader case review

Research-only companion to the case-ledger and raw-source attestation in draft PR #1546.
**No human reviewers, owner approval, reviewer keys, verdicts or neural results
are manufactured by this command.** It only packages already-observed source
bytes so that separately authorized humans can review them.

## Input contract

The operator obtains a genuine ORIGINALS manifest from an authenticated
source owner, independently checks the exact file and supplies its SHA256
through a separate trusted channel. Supply that file, its raw byte SHA256
and an UNUSED output directory to the offline Python command:

```sh
sha256sum /private/reader-originals.json
python scripts/memory_cell/reader_review_handoff.py \
  /private/reader-originals.json /private/new-review-handoff \
  --original-file-sha256 <INDEPENDENTLY_VERIFIED_64_HEX_SHA>
```

The command does **not** acquire that SHA from the untrusted file or make
any authenticity assertion itself. It checks the raw input bytes, rejects
ambiguous JSON, validates all four positions for each question, exact
original UTF-8 source windows, as-of time/scope, source fingerprints and
references in the unmodified model answer. It also checks identical
question hashes across all four conditions and that the critical-premise
removed arm is structurally different from the sufficient-evidence arm.
That difference is NOT a semantic sufficiency proof.

## Private files and human review

Create the new output directory with mode 0700 and its files with 0600:

- `review-questions.jsonl`: one ticket per original model answer with the
  original question, observed answer, delivered evidence excerpts in their
  original E-label order and citations *extracted* from that answer. The
  registered arm, original question ID, gold reference and reviewer verdict
  are NOT included in the blind view.
- `reviewer-blank-form.jsonl`: null verdicts for grounded/cited, exact
  refusal and semantic support. Every item needs actual independent review.
- `operator-private-map.jsonl`: ticket-to-original-question/condition map
  and mechanical source/prompt/answer fingerprints. This is for the
  authorized operator only; do not distribute it with the blind review view.
- `handoff-receipt.json`: raw source file pin, canonical object SHA, case
  count, hashes of the generated files and explicit ZERO reviewer verdicts,
  ZERO reviewer signatures and ZERO model calls.

Ticket IDs are generated with a private random salt. This limits easy
linkage to question IDs but **cannot blind reviewers to evidence semantics**.
The human reviewers must independently judge citation support and refusal
appropriateness. The operator must separately approve the roster, collect
authentic reviews, reconcile all required entries and obtain two genuine
authorized signatures over the resulting case ledger. Only then can the
existing trust manifest and model gate evaluate any prospective admission.

**Confidentiality:** real review input may contain private conversations.
Never commit or upload source packets or the operator mapping to GitHub,
CI artifacts, public links or model training data. CI executes only the
hermetic generated fixture tests, **not** this exporter on natural sources.
Do not publish a completed verdict form unless explicit source-owner and
reviewer permissions allow it.

## What this does NOT establish

A verified input file and successful packet generator are mechanical
provenance controls, not a human evaluation, an independent corpus, a
Reader performance improvement or learned NDU/FBSDE reasoning. The live
experiment remains blocked by default with **768 planned but blocked
positions and zero new neural calls** until independently authorized source
and signed review material actually exists.

Tests exercise fake local source objects without gold scoring, private
output permissions, blank verdicts, time/scope, UTF-8 windows, missing
premises, absent evidence, forged citations, file hashes and overwrite
refusal. No signing keys or real verdicts are written to repository files.

## Machine-only refusal check before blind review

The original-byte auditor correctly requires the **final signed review ledger**
with `exact_refusal` matching the literal bytes `I do not have enough evidence.`.
The blank-review handoff is a different stage: reviewer verdicts have not been
collected and **must not be fabricated**. During source validation only, the
handoff builds a temporary in-memory copy of each provenance row with this
mechanically decidable refusal predicate computed from the original Reader
answer. This copy is never written to a review packet, independent verdict,
trust manifest, or neural gate. All exported human verdict fields remain `null`;
output rows have zero reviewer signatures and do not authorize execution.

This fixes a reproducible fail-closed integration regression in which the new
exact-refusal audit rejected legitimate blank-review handoffs for missing
verdict fields. The final `audit_originals` and signed Reader gate are still
strict: passing the handoff **does not** satisfy their verdict requirements.
Tests include a real `E1` echo as a non-refusal case and explicitly show that
unsigned blank handoff rows fail strict final admission. The operator must
still obtain independently approved human reviewers and owner-attested raw
source bytes before any production or research matrix eligibility.

## Directory-file-descriptor output binding

Private handoff generation creates the destination exclusively with mode `0700`,
opens its directory through a no-symlink POSIX directory-descriptor walk and
retains that **same descriptor for all four files**. New file creation is
relative to that descriptor with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`,
file `fsync` and directory `fsync`. This closes a path-replacement window
where another process could rename the output directory after `mkdir` and
point the pathname at a different directory before source bytes were written.
An output leaf symlink cannot redirect the exclusive write.

The mechanism is deliberately POSIX-only and fails closed if the required
flags are unavailable. A trusted operator must still protect the parent
directory against unauthorized renaming and authenticate all original bytes:
directory FDs cannot defeat a compromised filesystem, an attacker already
operating as the same account or a malicious privileged operator. The
generated receipt remains unsigned, with zero authorized reviewers or
production privileges. Hermetic tests replace output paths both immediately
before directory opening and immediately before the first file write.
