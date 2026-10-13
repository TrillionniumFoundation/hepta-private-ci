# Externally authorized dual-signature Reader gate (research-only)

This hardens the full 768-position shared Stem/Cell matrix admission gate.
The former operator-supplied SHA256 of a self-described review manifest and a
string reviewer ID were not cryptographic evidence of independent assessment.
They must no longer enable neural rows by themselves.

## New fail-closed verification

All of the following are necessary before any matrix row can be marked
`planned_neural_execution`:

1. An exact Reader-gate v2 receipt binds the 20+ reviewed items, four evidence
   conditions, all fixed answer/refusal counts, model weights, tokenizer, prompt,
   dataset, revision, decoding budget, and requested modality/inference scope.
2. The reviewed-content SHA256 matches a separate *review manifest*, and the
   manifest SHA256 matches the out-of-band owner pin
   `HEPTA_READER_TRUST_SHA256`. The original four-arm >=75% grounded and
   >=90% refusal thresholds, and strict ordinary-retrieval comparison, remain.
3. A distinct operator-authorized reviewer roster with schema
   `hepta.reader.authorized-reviewers.v1` is supplied; its complete canonical
   JSON SHA256 must match **both** the review manifest field
   `authorized_reviewer_roster_sha256` and a second out-of-band owner pin
   `HEPTA_REVIEWER_ROSTER_SHA256`. Neither a roster fetched from the
   self-reviewed model artifact nor a SHA printed by that artifact is an
   out-of-band authority.
4. At least two distinct *authorized public keys* from that pinned roster
   each verify an Ed25519 signature over the exact reviewed-content SHA256.
   Message bytes: ASCII `hepta.reader-gate.v2.ed25519`, a NUL separator, then
   the 32 decoded digest bytes. Each roster entry must identify an approved,
   currently authorized reviewer separately vetted by the operator as
   independent of the model and dataset owners. Repeated identities/keys,
   missing signatures, revoked reviewers, invalid signatures, mismatched pins,
   absent pinned cryptographic verification, or unsupported capabilities
   fail closed.

The code cannot magically attest that someone is independent: human identity,
conflicts of interest, key custody and the two out-of-band SHA pins **must be
verified by an external owner**. Do not hard-code or commit reviewer private keys.
The test suite generates ephemeral Ed25519 keypairs only in memory; it is a
cryptographic implementation control, not actual human adjudication.

## Invocation

When independently approved review material exists:

```sh
export HEPTA_READER_TRUST_SHA256=<externally_approved_review_manifest_sha256>
export HEPTA_REVIEWER_ROSTER_SHA256=<externally_approved_public_roster_sha256>
python scripts/memory_cell/full_cell_matrix.py /new/output \
  /path/to/four-arm-reviewed-reader-gate.json \
  /path/to/independent-review-manifest.json \
  /path/to/authorized-reviewer-roster.json
```

Omit these files and pins in normal CI. It must retain **768/768 blocked rows**,
zero neural calls and null accuracy/FLOP/energy estimates. The separate hosted
matrix workflow installs a pinned `cryptography==46.0.4` into a venv to verify
the ephemeral *test* signature path; it does not stage private keys or produce
human reviews. Full repository `blocking-ci` and production checks are not
modified.

## Limits

A signed synthetic fixture or a capable frozen Reader does not establish
general NDU/FBSDE superiority, 10T/100T parameter equivalence, future-world
performance or multimodal accuracy. The completed 200-call Qwen TAG binary
call/stop menu had no learned headroom beyond the frozen source check
(121/200), and the closed-grammar parser's 200/200 is NOT learned reasoning.
Current real signed independent natural-task reviews are unavailable; this
change is a safety/precondition fix, not a new model experiment or promotion.
