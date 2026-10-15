# AMCN independent semantic-review intake — original Reader and source protection

Research profile: `hepta.amcn.original-blind-two-reviewer-handoff.shadow.v1`. This is an **implementable private review handoff**, not a claim that any independent reviewer has evaluated LoCoMo. PR #2085 remains DRAFT / SHADOW / DENY_ALL.

## Why this is needed

Historical Reader observations contain 20/20 no-evidence calls that did **not** produce a recognizable abstention, and only 27/96 outputs with any citation marker. A syntactically valid `[E1]` proves neither factual entailment nor correctness. Publisher weak-support, answer substring or Top-3 Hit are not independent whole-task success.

The existing nine-arm `amcn_causal_task_audit.py` can ingest bound judgments, but its self-consistent `review_receipt_sha256` is **not a reviewer signature**. The new `amcn_original_blind_review.py` makes an explicit private, double-signed intake path; it never mints an independent decision or stores original answers in Git.

## Local offline workflow

1. On the authorized private evaluation host, provision a **cryptographically random 32-byte blind seed** and preregister `SHA256(seed bytes)` in an independent, timestamped record **before** Reader executions are scored. Store the actual seed in a `0600` file; do not publish it or pass it in a command-line argument.
2. Use the exact frozen original nine-arm `plan.json` and `answers.json` with **out-of-band SHA-256 file pins**. Run `blind-export`; it rechecks every source/answer/citation and will not omit a failed Reader call. It creates a private review-ticket file and a separate **secret arm-to-ticket mapping**. Reviewer tickets do not contain explicit arm IDs, case IDs, type labels, or publisher answers, but the passage and output themselves may still give clues.
3. Give private reviewer tickets to **two genuinely independent, credentialed reviewers**, together with separately authenticated access to the **full original source** for fact-checking. A few source excerpts, publisher annotation, or a model-generated explanation are **not** sufficient evidence on their own. Reviewers must determine factual correctness, delivered-evidence sufficiency, and citation entailment. Each must sign the exact fixed ticket/decision with their own Ed25519 key; **never** circulate private signing keys.
4. Pin the public-key registry and full-original-source hash **outside** this code and obtain independently witnessed reviewer identities/roles. Run `verify-reviews`; it checks distinct public keys, exact answer/source/ticket SHA, signatures, complete **two-reviewer census**, and agreement. Missing reviews, forged signatures, reviewer disagreement and model failures credited as correct all **fail closed**. Disagreements require a separately adjudicated process; this version does not vote away hard cases.
5. Keep tickets, private map, original dialogue, signed review rows, reviewer credentials, and adjudicator records **private**. Only aggregate, negative-authority receipts should be considered for publication, after confidentiality review.

Example (all paths are **private**; no actual reviewers have been supplied):

```sh
export PYTHONPATH=qualification/amcn-v1
python3 qualification/amcn-v1/amcn_original_blind_review.py blind-export \
  --plan /private/exact-nine-arm-plan.json --plan-sha256 "$EXTERNAL_PLAN_FILE_SHA" \
  --answers /private/exact-Reader-answers.json --answers-sha256 "$EXTERNAL_ANSWERS_FILE_SHA" \
  --private-seed-file /private/registered-32-byte-seed.hex \
  --externally-registered-seed-sha256 "$BEFOREHAND_TIMESTAMPED_SEED_SHA" \
  --tickets /private/create-only-review-tickets.json \
  --private-map /private/create-only-arm-index.json

python3 qualification/amcn-v1/amcn_original_blind_review.py verify-reviews \
  --tickets /private/create-only-review-tickets.json --tickets-sha256 "$TICKET_FILE_SHA" \
  --private-map /private/create-only-arm-index.json --private-map-sha256 "$INDEX_FILE_SHA" \
  --reviews /private/all-signed-review-rows.json --reviews-sha256 "$REVIEW_ROWS_SHA" \
  --registry /private/externally-registered-reviewer-public-keys.json --registry-sha256 "$KEY_REGISTRY_FILE_SHA" \
  --reference-original-full-source-sha256 "$OWNER_FULL_SOURCE_SHA" \
  --output /private/create-only-two-reviewer-signed-judgments.json
```

**Signature envelope**: a review is `{ticket_id, ticket_sha256, reviewer_id, verdict, signature_hex}`, where verdict contains `independently_consulted_full_source: true`, `reference_source_sha256`, `factually_correct: bool`, `citation_entailment: bool`, `delivered_evidence_sufficient: bool`. Sign canonical JSON `{"domain":"hepta.amcn.original-blind-two-reviewer-handoff.shadow.v1.ed25519-review.v1","review_bundle_sha256":"...","signed":{ticket_id,ticket_sha256,reviewer_id,verdict}}`. The public-key registry must have schema `hepta.amcn.original-blind-two-reviewer-handoff.shadow.v1.reviewer-key-registry.v1` and `public_keys: {reviewer_id: 32-byte-public-key-hex}`. Refer to source implementation for exact canonical byte representation and domain.

## What verification does NOT establish

Ed25519 proves that **two cryptographically distinct registered keys** signed the statements, not that their owners are independent people, were supervised, actually read the full source, or scored truthfully. Commitments prove bytes, **not their registration time**. The resulting `judgments` may be passed to the existing nine-arm paired audit, but its status, and the handoff's own, remain **real-world reviewer independence unverified / source truth unverified / production_accepted=false** until outside review-owner attestation is actually available.

Synthetic tests deliberately generate temporary signing keys, sign 54 **synthetic** nine-arm Reader attempts with 108 fake review signatures, and attack swapped answers, forged signatures, omission, reviewer duplication, key rotation, invalid sources and disagreement. **Those are contract tests, not original Reader inference or independently reviewed semantic judgments.** The dedicated GitHub Actions workflow runs these source-only contracts with `cryptography==50.0.2`. Original 96 Reader journals and original pretrained model material are NOT downloaded or executed by this lane.

Separately, the zero-evidence research guard now rejects blank/whitespace-only questions and evidence text; such nonempty source-ID lists cannot bypass abstention. This is a pre-dispatch correctness and security fix, **not** new learning, evidence entailment, Source Owner authority, or changed archival answers.

Next genuine gates remain exact original Hugging Face forward/tokenizer parity, independent reviewers with authenticated source access, a stronger Reader sufficiency comparison under equal cost, real prospective windows, and `blocking-ci`/Architecture. NO selected model, no auto Cell split/fuse, no main merge, no FinalUse.
