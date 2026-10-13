# Private returned Reader review forms: reconcile, never self-approve

Research-only, strictly **offline** continuation of the original-byte Reader review handoff in PR #1546. This tool does not issue signatures, v2 Reader gates, source-owner attestations, reviewer authorizations, semantic ground truth or neural results. It leaves all **768 unreviewed matrix positions blocked**.

## Prerequisites

An authorized operator must first have a real, independently authenticated original Reader case packet and must have created a private handoff using `reader_review_handoff.py`. The handoff contains `review-questions.jsonl`, `reviewer-blank-form.jsonl`, `operator-private-map.jsonl` and `handoff-receipt.json`, all in a private directory. Reviewers must be independently authorized by the source/data/model governance process; names provided on the command line **cannot authenticate identity**. A self-generated SHA is not proof of a trusted producer.

Each of two separately returned private reviewer JSONL files must preserve the **exact** tickets and the blank-form schema. The three values `grounded_and_cited`, `exact_refusal`, and `cited_semantically_supported` may be true/false or null if unfinished. No signatures, fake reviewer keys, simulated scores or authorization flags belong in those files. The operator must separately obtain and verify the raw-byte SHA256 of the handoff receipt and both returned forms over approved private channels. Reviewer-submitted source text is treated as untrusted data.

Run on a private, trusted machine, never in public CI with real review forms:

```sh
python scripts/memory_cell/reader_review_intake.py \
  /private/blank-handoff \
  /private/reviewer-a-filled.jsonl \
  /private/reviewer-b-filled.jsonl \
  /private/unused-reconciliation-dir \
  --handoff-receipt-sha256 <AUTHENTICATED_RECEIPT_SHA256> \
  --first-form-sha256 <AUTHENTICATED_A_FORM_SHA256> \
  --second-form-sha256 <AUTHENTICATED_B_FORM_SHA256> \
  --first-reviewer <OPERATOR_VERIFIED_A_ID> \
  --second-reviewer <OPERATOR_VERIFIED_B_ID>
```

All files must be owner-only (`0600`), the handoff folder `0700` and output folder **new**. The tool checks symlinks in paths, bounded UTF-8/JSONL, duplicate JSON fields, negative/tampered pins, four-condition original question census, each original E-label and cited-source fingerprint, and equality with the handoff's immutable answer/provenance receipt. Review files must match every issued ticket exactly. The original gold target and operator mapping are not sent to blinded reviewers. Source privacy and independent access permissions remain the operator's responsibility.

## Outputs

The new private `0700` output directory contains only two `0600` files:

- `operator-private-comparison.jsonl`: a per-ticket side-by-side record of the **claimed** review fields and `agreed`, `disputed` or `incomplete`. It contains the private original question ID/arm and must **never** be published.
- `reconciliation-receipt.json`: counts, source/receipt/form digests, the result file's SHA256, and explicit false values for approval, independent reviewer authentication and production acceptance.

An incomplete or disputed ticket is retained, never voted away or silently converted to a negative answer. An exactly agreed Boolean is **not** a verified human judgment or a validated model answer: two identical returned files can even have identical SHA256 values, and operator-claimed reviewer IDs do not demonstrate independence. The tool correctly accepts two distinct file paths with identical content, **but still marks reviewers as unauthenticated**. Impossible claims such as grounded-and-cited with no citation, cited support with no citation, or a false exact-refusal judgment on a literal registered refusal fail closed before output creation.

This stage **does not export a signed gate JSON** and never supplies `reviewer_signatures`, `authorized_reviewer_roster` or a trust-manifest approval. Actual owner-approved reviews, external roster verification, reconciliation of disagreement, original-source raw-byte pins and two genuine Ed25519 signatures must be completed separately, then checked by the existing `full_cell_matrix.py` gate. A successful dry-run here remains an **unapproved, unsigned** research artifact.

The GitHub workflow executes only **hermetic synthetic tests**, plus the existing original-source, ledger, signature and `768/768` blocked checks. It never opens real private review forms or publishes the operator map in an Action artifact.

**Limits:** Best-effort `fsync` and exclusive `0600` file creation are not protection against privileged operators, a compromised filesystem or TOCTOU attackers. The input pins must arrive through independent trusted channels; file hashes do not authenticate their sender. No Reader, NDU, FBSDE or cross-modal reasoning gain is claimed.
