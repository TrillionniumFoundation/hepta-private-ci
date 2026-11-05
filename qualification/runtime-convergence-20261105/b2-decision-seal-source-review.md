# Independent review: complete product-qualification decision binding

Reviewed base: `4e31abc907f09740d402d1ddef7a1d2fe0a366a6`.
Reviewed standalone B2 patch: `adaptive/receipt-seal/qualification-decision-seal.patch`.
Patch SHA-256: `2006d579dd72d758e0a992b19b6526227c6253e5efbd8eb4ba12318974f692ef`.

## Result

No source-level blocking finding. The four changed files and their recorded Git blobs/SHA-256 values match the manifest. `git apply --check` against the retained base files passed. This is an independent static review, not a native compilation/test result.

## Complete semantic coverage

`IndependentEvaluationDecisionV1` has exactly seven fields: `evaluation_id`, `candidate_id`, `baseline_id`, `disposition`, `failed_metrics`, `evidence_digest`, and `authority`. B2 adds the first five to the product-qualification digest; the existing evidence digest and authority encoding are retained. `SignedEvaluationDecisionV1` contains that decision plus `trust_digest` and `authentication_digest`, both already retained in the enclosing digest.

The enclosing product receipt continues binding its temporal execution, candidate, evaluator, generator, objective, dataset, snapshot IDs, claim scope, publication, and authority. Both principals' full seven-field identities are encoded by the existing `push_principal`. The public evidence digest is checked against its recomputation and included in the private receipt seal. `AuthorityPosture` at this exact source is a unit-backed deny-only type (`_deny_all: ()`), so there is no omitted alternative constructible authority state.

The exhaustive disposition encoding rejects future incomplete extensions at compile time. Stable IDs and ID lists use the existing length-prefixed encoders. `failed_metrics` order/content is bound exactly; no lossy summarization or permissive normalization was introduced.

## Actual consumer path

`run_evaluated_shadow_v1` performs the following source-level sequence:

1. Validate product qualification integrity.
2. Bind and verify `evaluated_candidate_signing_payload_v2` against the same qualification and candidate bytes.
3. Clone the public signed decision and directly read its disposition.
4. Admit only `EligibleForIndependentSelection` to the shadow pipeline.
5. Invoke the host's seven proposal ports and append the durable production Decision through `LedgerWriter`.

The old product receipt seal and candidate-signing payload both omitted the decision label's semantic binding. Changing only an authentic Ineligible receipt's public disposition can therefore pass the old checks without changing signatures or evidence digests. B2 makes that mutation change the recomputed enclosing evidence digest, causing rejection before any host port or Decision append. This finding concerns shadow eligibility and durable Decision recording; it is not evidence of external effect authorization or production-release bypass.

The new consumer regression generates an authentically signed Ineligible decision by raising a frozen primary-superiority margin to ONE. It first proves the unmodified receipt receives the expected Ineligible refusal, then changes only the public disposition while retaining failed metrics, signatures, and digests. It calls the real `run_evaluated_shadow_v1`, checks zero port calls, no records, and byte-for-byte unchanged durable journal after owner drop. The original code should reach seven ports and append a Decision under the same fixture; native red/green execution remains required to establish that observation. The existing eligible-path integration test remains intact.

## Compatibility

The product evidence domain changes from v3 to v4 and the private receipt seal domain from v1 to v2. This is an intentional semantic identity change. Consequently the outer `evidence_digest` and the candidate-signing payload that commits to it change, and candidate signatures must be recomputed against the new valid receipt.

The inspected `ProductQualificationReceiptV1` has no serde/codec and its seal is private. The publication sink receives the unchanged temporal execution digest and `SignedEvaluationDecisionV1`; neither its API nor the ledger encoding changes. This does not prove that no external system stores a digest/reference. External references must remain source/version-bound, and old receipts must not be accepted via a v3 fallback. Migration must not consume or evaluate a used final holdout again merely to refresh this seal. No automatic receipt migration or compatibility fallback is supplied by this patch.

## Compilation review

All added imports resolve against existing re-exports and dependencies. The production match covers all three disposition variants. The nine capture-free mutation closures coerce to the declared function-pointer array. Test helper visibility, the FixedQ32 argument, existing module inclusion, Debug/Eq/PartialEq bounds, fixture borrowing, and journal-owner drop before independent Windows reads are consistent with the existing code. No Cargo/Bazel dependency change is required. Original package tests and formatting on the combined candidate remain necessary.
