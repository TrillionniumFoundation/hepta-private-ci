# E3 same-source five-arm: content-bound model input + native token budget + physical identity

**2026-10-15. Research / Draft / DENY_ALL.** This is an additive descendant of [#2336](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2336) exact starting HEAD `27482cee43ae13e75c555cf7a8b6868a56d6f42b`, itself stacked on original [#2332](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2332) and [#2325](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2325). It imports the independently authored, immutable no-truncation research code from sibling [#2329](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2329), without force-rewriting or changing that original branch.

## Concrete integration

1. Preserve the original **196 original source-file byte-identity** input view and two independent **before / after** OCR and Gemma2 source-tree receipts. The `hepta.e3-path-byte-sha256.v2` hashes relative path **and actual file bytes**, not just file names; test/candidate-answer sources are still segregated.
2. Preserve the **TRAIN/CAL-only label access** in physical OCR and native model jobs. TEST labels and their target digest are absent until separately held scoring, and no raw original images or pretrained weights are uploaded in artifacts.
3. Copy `e3_gemma2_native_budget.py` plus **18 original adversarial tokenizer tests** byte-for-byte from [#2329](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2329). Require the original frozen Gemma tokenizer with `truncation=False` for each literal text, joint text + image, and answer choice before **any** `model.encode()` forward. Bound the 8,192 input context, reserve 280 nominal image tokens and 128 miscellaneous tokens, and explicitly set `actual_model_image_token_count_attested=false` since the tokenizer is not a true media-token meter.
4. Bind its `preencode_text_image_budget` receipt into the actual native physical producer output; the original 64-row composer refuses absent, malformed, unbounded or falsely attested media-token receipts. Preserve the corrected physical call `physical(native, NATIVE, GEMMA, "physical_joint_encode_batches")` and its strict repo/revision/digest and positive physical-forward counter checks. The originally observed **19/28** hosted test failures from the missing fourth argument must not recur.
5. Retain all 28 original five-arm tests, four sibling token-budget/attestation regression methods, and the advanced correct-model substitution regression = **33 source-declared five-arm unittest methods**, plus the 18 standalone tokenizer tests. This is a *test inventory*, not proof of successful completion.
6. Update both existing E3 five-arm workflows to watch this exact research branch, preserve source-only contracts under PR and **push-only actual OCR/Granite + Gemma2 and independent label-owner scoring**, fail-fast unchanged. Require the actual token budget tests in both normal Python and `-O` **before expensive model jobs**. The source contract's branch-selection test now parses the explicit four-branch JSON list, requiring the previous merged/byte/arity child and this current child, not a broad pattern or a relaxation to main.
7. Add a small separate exact-SHA (`source_head` / `synthetic_merge`) token-budget research workflow and preserve the original source+physical workflows' per-`github.ref` supersession policy. Prior queued runs are neither manually rewritten nor counted as passed.

## Exact remote source integrity checked

| Path | Git blob SHA-1 on this branch |
| --- | --- |
| `e3_model_entry_ledger.py` | `c41d93955cb679da76193fed6d0ae7c5495ce6c4` |
| `e3_five_arm_historical.py` | `351d903844918d6fd522465e9a824181e8e5ee73` |
| `e3_gemma2_native_budget.py` | `a5109f1d51cd110d6e848b77d05f36acf935974c` |
| `e3_gemma2_native_physical.py` | `a76827cbad178bf4274d289409bcc88730d6bc34` |
| `test_e3_five_arm_historical.py` | `a0e58a180bdc5d210caca4e2d5c40adc7afafc0e` |
| `test_e3_gemma2_native_budget.py` | `4e6b5ba15a610ab3c0be30ce28fa19976a07cc64` |

Every touched new/modified file was read back from the GitHub child branch and source content matched submitted bytes. A separate static source audit confirmed 196-file profile retention, native model identity, pre-forward tokenizer call order, no fake media attestation, 33+18 test-method inventories, exact child-only workflow branch allowlists, push-only physical jobs, no escaped GitHub expressions and `DENY_ALL`.

## Mandatory empirical gates — **not yet demonstrated**

The exact new branch's normal and optimized tests, genuine external original OCR+Granite and original EmbeddingGemma2 physical forward, both byte-bound pre/post filetree receipts and a full 64-case held-human-label independent five-arm score **must actually complete** in GitHub Actions. Only true exact-HEAD positive observations qualify those mechanics; no synthesized result, queued job, or skipped model step is a pass. Even completion does NOT prove that native multimedia beats frozen vision, that image/video/audio generation exists, that the selected physical model is production ready, or that independent future1/2/3 groups or full-lifecycle cost parity are satisfied.

No original V1/Q24, Worker, CNS, NDU, signed FinalUse, model selection or protected main changes. **DRAFT / DENY_ALL / NO_MODEL_PROMOTION / NO_PRODUCTION / NO_10T_100T_EQUIVALENCE.**
