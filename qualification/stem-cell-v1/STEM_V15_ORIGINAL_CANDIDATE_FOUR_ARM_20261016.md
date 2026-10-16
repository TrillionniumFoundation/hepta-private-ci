# V15 — original 135M Reader, four evidence regimes (candidate-only)

**Research SHADOW / DENY_ALL / no production authority / do not merge `main`.**

## What actually ran

An original GitHub Actions archive (`11586991191`, original outer ZIP SHA-256 `07b357cbb3362f484ac4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`) yielded the exact original LoCoMo source (`79fa87e9...`), the original archived BF16 135M / 30-layer Llama-family Reader (`5af571cb...`), and original ByteLevel tokenizer (`9ca9acdd...`). CPU inference uses the existing project `v12_reader_runtime.OriginalCandidateLlama` implementation with original BF16 tensors promoted to FP32. **Official Hugging Face tokenizer/operator parity is unverified.**

The original source contains 10 historical families, 5,882 turns and 1,986 questions. The four retrospective heldout families are `conv-47` through `conv-50`. An independent no-label V14 BM25 single-arm pass ran the original 1,986 questions; the frozen original ranked-source SHA is `b0b38675d2d5458795d0577d5c861b796dfbdf9e7d4cd089838895c419831697`.

## Cohort and arms

**Four source roots × four questions = 16 cases, each four different immutable Reader inputs.** Before any model call, the preparation step takes the originally published **source support annotations**, selects among questions where the *single* publisher-annotated source is missing from BM25 Top-3, and uses the lowest deterministic SHA-256(question ID) per family. Crucially, this is **outcome/annotation-assisted retrospective selection**, not blind or prospective inference. The answer-field text is not accessed in preparation. The completed immutable Reader plan is independently rechecked against the original source only after all model answers are sealed. The four conditions are:

* `none`: no evidence.
* `retrieved`: original BM25 Top-3 evidence.
* `annotated_witness`: the publisher-annotated source plus original BM25 Top-2.
* `witness_lesion`: BM25 Top-2, removing the annotated source from the preceding arm.

**The publisher annotation is not independently human-verified sufficient evidence.** The absence/presence of that annotation is a weak evidence-source measure, not semantic answer truth. Prompts keep the same original system instruction, Reader, tokenizer, deterministic greedy strategy, and maximum 24 output tokens. The actual number of input tokens differs by condition, so **total computation is not matched**. A stronger distinct reference Reader was not available and was **not simulated or substituted**. This is a physical candidate-only supplement to #2400; it does **not** claim completion of #2400's two-Reader protocol.

## Physical execution and observed negative evidence

The first local off-dot isolated CPU run completed all 64 physically original model requests, recording 1,439 true Reader `forward()` invocations, 7,963 input and 1,395 output tokens, **235.999 CPU seconds / 120.026 wall seconds** (within that model child only). The first answer journal and independently decoded all-original token sequence agreed. A second completed independent original-model process repeated all 64 requests / 1,439 forwards, with the same 64 original answer texts, generated token IDs, input counts and source IDs. Second-run CPU **215.398 s** / wall **108.238 s**. Original CPU time fields differ across runs, so the entire first/second journal SHA is deliberately **not** claimed identical; the stable source/request/token/answer digest is documented in `V15_ORIGINAL_CANDIDATE_REPEAT_RECOUNT_20261016.json`. Historical source/model bytes, prompts, per-question routes, publisher target text and raw answers remain PRIVATE and are not committed.

Original publication-weak/source-inclusion and literal answer-only descriptive data:

| Condition | Source witness in Reader | Exact publisher answer text | Publisher answer substring in output | Literal `unknown` |
|---|---:|---:|---:|---:|
| No evidence | 0/16 | 0/16 | 0/16 | 0/16 |
| Retrieved | 0/16 | 0/16 | 0/16 | 0/16 |
| Annotated witness | 16/16 | 0/16 | 3/16 | 0/16 |
| Witness lesion | 0/16 | 0/16 | 0/16 | 0/16 |

All 16 raw Reader answers differed between ordinary retrieved evidence and the witness-injected arm. This merely establishes that this implementation reacts to changed model inputs. It **does not prove that the witness contained adequate evidence, that any answer was semantically correct, or that more training helps**. `0/16` literal `unknown` is a failure to follow an explicit abstention string, *not* a verified hallucination rate. No independent semantic citation entailment or authenticated human evaluator was provided.

The existing #2364 V6 seed41 old-task retention failure remains unresolved. The earlier V13 full historical lexical gain +11/829 remains an unproven cost-adjusted retrieval proxy rather than whole-task utility. This 16-case witness-annotated cohort is selected on missing BM25 supports, so cannot be extrapolated to all 829 heldout cases or to source-independent future windows. The four roots are four correlated independent units at best; 16 questions cannot support 16 independent-family significance claims.

## Reproduction

The code consumes externally SHA-pinned original weights/source. It never downloads artifacts, accesses secrets, or emits raw results in CI. Restore the legitimate original source-only V13 input, V14 unlabelled BM25 ranks, and original LoCoMo file privately. Three non-overwriting stages:

```
python qualification/stem-cell-v1/v15_original_candidate_four_arm.py prepare --source PRIVATE/source-only.json --bm25 PRIVATE/bm25-ranked.json --original PRIVATE/locomo.json --output PRIVATE/v15-plan.json
python qualification/stem-cell-v1/v15_original_candidate_four_arm.py execute --source PRIVATE/source-only.json --bm25 PRIVATE/bm25-ranked.json --plan PRIVATE/v15-plan.json --reader PRIVATE/reader --output PRIVATE/v15-answers.json
python qualification/stem-cell-v1/v15_original_private_recount.py --plan PRIVATE/v15-plan.json --source PRIVATE/source-only.json --bm25 PRIVATE/bm25-ranked.json --answers PRIVATE/v15-answers.json --journal PRIVATE/v15-answers.json.starts.jsonl --reader PRIVATE/reader --out PRIVATE/v15-recount.json
python qualification/stem-cell-v1/v15_original_candidate_four_arm.py score --source PRIVATE/source-only.json --bm25 PRIVATE/bm25-ranked.json --plan PRIVATE/v15-plan.json --answers PRIVATE/v15-answers.json --original PRIVATE/locomo.json --output PRIVATE/v15-sanitized.json
```

The public source-only workflow runs negative/mutation tests under ordinary and optimized Python and audits the sanitized aggregate. It **does not** assert it downloaded or executed a real pretrained model, nor certify original model-host authenticity. Synthetic tests count only as contract coverage.

## Decision

**HOLD / NO-GO.** No independently sufficient witness verification; no stronger original reference model; no independent semantic task/entailment reviewer; no fresh source-family/calendar windows; no official HF parity; no matched train/retrieval/Reader/energy/recovery cost; no 200 independent families; no Cell promotion, automatic fission/fusion, NDU/System2 FinalUse or production qualification. Keep all owner, release and `blocking-ci` gates intact.
