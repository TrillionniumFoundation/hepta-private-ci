# MemoryCell next gate — original-source strong Reader reference (Qwen3-0.6B)

**Research only · DRAFT · HOLD_NO_GO · DENY_ALL · NO MAIN · NO FINALUSE.**

This is an additive child of [MemoryCell six-arm original Reader #2532](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2532), not a new memory authority, inference serving selector, or automatic CellSplit. Nothing installs a production Reader or enables trained graph weights. This source **does not** claim a new physical Qwen inference result until a pinned original-weight job actually completes and its sanitised review is checked.

## Why this is the next experiment

The original SmolLM2-135M (local custom FP32 profile) generated **118/120** planned original LoCoMo six-arm requests (two publisher-annotated evidence plans were explicitly unavailable), **0/118** emitted required `[E...]` citations; at a common 14 scorable-question denominator, the previous source-bound temporal graph had mean diagnostic token-F1 **0.053300862** versus **0.066847328** for simple temporal adjacency, with no independent advantage. Publisher-annotated evidence had mean **0.128420581** but its source *sufficiency* was never independently certified.

A stronger Reader is the necessary diagnostic before investing in more neuron memory-cell weights, a larger learned meta-graph or NDU System 2. Improvements from changed pretrained Reader, tokenizer or chat template must be recorded as **Reader capacity / model-stack gains**, never as MemoryCell parameter learning, graph structure, NDU or System2 gains.

## Model and source identities

- **Original** LoCoMo corpus SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`, earlier GitHub archived producer run `37862780268`, artifact `11586991191`.
- **Question and evidence**: same frozen 20 SHA-selected historical questions across 10 source families, same six conditions (`empty`, `bm25`, `temporal_window`, `graph`, `annotated`, `annotated_lesion`) and original source snippets as #2532, up to 120 actual attempts. A sealed public plan `plan.json` + `plan-seal.json` is the only data readable by the strong Reader worker; it is re-derived independently at review.
- **Historical baseline**: source-plan SHA-256 `a7ad39c6548b06dc0fd752cd77149deaeb46875b3307696fe2857ef0cd1fc3e9`; genuine old Smol135 original journal SHA-256 `0797d8b1a4d9b9e3d7d68925bf4001666f253191d2bac46d90a0af11c78f0d76`. A historical paired comparison is valid only for these identical sealed identities; it preserves genuine old answer bytes and explicit old failures.
- **Strong reference**: official `Qwen/Qwen3-0.6B`, publisher revision `16706fc57485378d4ffaf54139b29ccc66ae08fa`. Reuses the separately reviewed [V19 Qwen3 material owner #2523](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2523) at exact pinned Git commit `aa807d61edd0f5e88178ab9812e59eabe2613f20`, material-owner blob `e7269a61ab8d03269de5b9a042d6552fadfae285`, rather than introducing a second model downloader. Publisher Git OIDs/LFS SHA256, byte size, regular-file staging, manifest and immutable whole-model snapshot checks are mandatory; no mutable tag or unverified model fallback.

## Worker and review separation

1. `memory_reader_strong_reference.py preflight` checks a closed-world six-arm source-only plan. It rejects role delimiters and unexpected model input shapes, and emits no answers.
2. The strong worker **only** receives the sealed plan and Qwen3 staged source. The same logical question/evidence JSON bytes are used as the existing 135M experimental condition, but Qwen tokenizes with the **native** pinned chat template and `enable_thinking=False`.
3. The worker writes a fsynced **before-effect intent** for each physical model call. After actual `generate()` success it seals 120 records with input IDs digest, raw generated token IDs, decoded answer, timestamps and pinned source identity. A crash or missing/corrupt result has **no successful seal**; it must not be silently replayed and passed as completed research. The original request order, plan digest, evidence addresses and raw output decode are independently checked. Outputs never have invented citation markers inserted.
4. The independent review reconstructs the full original dataset and public source graph **after the worker process has exited and sealed**, re-derives the sealed plan, verifies Qwen publisher bytes/tokenizer, checks all results, then opens publisher target answers for string-overlap diagnostics. This is process-stage isolation and **not** physical independent reviewer authority or attested hardware custody.
5. Report citation emission, valid *addresses* among actually delivered labels, foreign/hallucinated label count, original-token-F1 and strict exact matches as **separate** metrics. A syntactically valid `[E1]` is never automatically an entailed answer. Source-only and publisher privileged arms are not mixed into an unconstrained RAG efficacy claim.

**Important scientific limitation:** The V19 pinned model source profile declares 24 new-token greedy output, while the historical Smol135 cohort allowed up to 32. Models also use different tokenizers, model sizes and compute costs. The new report permanently sets `native_tokenization_and_generation_budget_matched_to_135m=false`. Even if the stronger Reader appears better, it is a non-cost-matched Reader-stack diagnostic, **not an equal-budget proof**. The publisher's annotated sources are retrospective and not independently human-certified sufficient; 10 correlated dialogue families are not 200 independent prospective populations. No human semantic citation entailment test is completed here.

## Local source validation (not a Qwen inference claim)

The newly implemented strong reader and protocol tests ran **13/13 local unittest cases**. These include the *actual original* sealed 120-call source-plan SHA and historical journal SHA, foreign/duplicate/relabelled inputs, unknown model-spec, forbidden chat role tokens, invalid foreign citations, original output-token/answer mismatch, forged success/unavailability, restart-before-effect intent and synthetic-score denial. **Zero new native Qwen model forwards were executed on the local development host**: immutable Qwen weights are not present there. A complete physical result must come from the newly configured pinned-weight CI job, with original source reverified and sanitised review; queued/failed jobs cannot be passed off as success.

## Hosted executable path

`.github/workflows/hepta-memory-reader-strong-reference.yml` executes inexpensive source/protocol tests for the draft PR, and schedules a **single separately conditioned full Qwen3 attempt on initial research-branch workflow addition** rather than auto-repeating 120 model calls with every source edit. The source producer runs independently, uploads only answer-free plan, and the strong worker downloads official fixed-revision weights with a pinned model-material verification implementation. Only *after* the raw strong worker has sealed its output is the original historical corpus downloaded again for postseal reviewing. The workflow uploads **only sanitised numerical/digest reports**: not model weights, private raw answers, original corpus, or unredacted questions.

Before activating any memory/graph/CellSplit, require (a) actual original Qwen success with full receipts; (b) sufficient-evidence verification by an independent reviewer and true answer/citation entailment; (c) matched benchmark costs and same-model per-arm controls; (d) independent source-family/future-window benefits; and (e) original owner security, revocation, rollback, independent acceptance and global `blocking-ci` / Architecture completion. All such gates remain **NO-GO** until actually satisfied.


## V2 — Original source admission and Qwen before-effect custody (2026-10-16)

**DRAFT / HOLD_NO_GO / DENY_ALL.** This source-level fix does not claim that the queued Qwen3 job completed.

The earlier source-contract unit suite contained two optional environment-gated checks for the actual historical 120-request plan and the 135M original-answer journal. Without these files both were SKIPPED, not PASSED. The physical workflow now includes a mandatory exact-original-plan check after source preparation; the historical 135M response journal remains a locally authenticated baseline rather than a fabricated hosted replay.

On the local research host, original answer-free plan SHA256 a7ad39c6548b06dc0fd752cd77149deaeb46875b3307696fe2857ef0cd1fc3e9 and frozen old 135M original journal SHA256 0797d8b1a4d9b9e3d7d68925bf4001666f253191d2bac46d90a0af11c78f0d76 were actually mounted. **21/21 local tests passed** in both normal Python and python -O: 13 original tests plus eight new strict before-effect custody tests. Lightweight hosted source tests must retain truthful SKIPPED counts when original research files are absent.

A new research-only module, scripts/memory_cell/memory_reader_strong_custody.py, requires one actual-model start intent per succeeded Qwen generation. Each record is fsynced before inference, written using no-follow 0600 file opening, and binds exact request ID, frozen plan SHA, pinned Qwen material identity, message digest, input token count and native input-token SHA. Any missing, duplicate, reordered, truncated, preplanted or changed start denies the complete journal. Unavailable original source or over-budget inputs cannot acquire a successful model-call intent.

The physical worker verifies these records before writing its final seal. Its separate postseal reviewer checks them again against all raw Qwen token IDs and answer text. The workflow writes a sanitized, original-answer-free custody receipt **before** original publisher answers are available; this receipt must match the final postseal report. Internal consistency does NOT certify external model-host attestation, semantic entailment, independently sufficient evidence or a deployed capability.

The Actions workflow additionally checks out the **exact PR source head** in preparation and physical Qwen jobs instead of silently using a GitHub synthetic PR merge commit. The separately pinned V19 Qwen model-material owner at aa807d61edd0f5e88178ab9812e59eabe2613f20 remains unchanged.

**No production use, Cell Split, learned Meta-Graph, NDU System 2 promotion or CI bypass.** Any Qwen performance claims still require actual terminal model-run evidence, independent semantic review, source-root separation and complete cost comparisons. Old queued executions of earlier SHAs do not validate these changes.

## Physical Qwen3 V4 — observed loader failure and pinned repair (2026-10-17 UTC)

**Original actual run:** [GitHub Actions #38985380451](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38985380451), exact isolated push source `aa8ba657851a7172702832f57f3a9c018f40494f`. Its original-source 20×6 preparation and source-contract jobs **passed**. The actual publisher-pinned Qwen3-0.6B material stage loaded **seven model-source files** and verified sealed publisher model identity `e748e2efe1880f9e312eb31e8929e0fff8e46a575cbcf6788f9399960748d273`. The physical-worker job **FAILED BEFORE FIRST MODEL GENERATION**:

```
TypeError: Qwen3ForCausalLM.__init__() got an unexpected keyword argument 'dtype'
```

The frozen `transformers==4.53.3` loader accepts the `torch_dtype` keyword in `from_pretrained`, whereas `dtype` was forwarded to the model constructor. This is a real compatibility blocker, **not a model quality result**. No physical generation, reference answer, citation score, or user-facing task result was produced by this run, and postseal gold retrieval/review were correctly skipped.

**Minimal V4 fix:** One bounded factory, `load_frozen_qwen`, now forwards `torch_dtype=torch.float32` (via its `precision` argument) while preserving `local_files_only=True`, `trust_remote_code=False`, `use_safetensors=True`, `attn_implementation="eager"`, and model `.eval()`. No model version change, dynamic dependency update, fallback, source/citation rewriting, or production selection was introduced.

Three new tests check the exact 4.53.3 constructor-argument behavior with a strict rejecting fake API, require no remote/network or untrusted-code model loading, and verify failed pinned-model initialization remains a hard failure. These tests are protocol/factory tests, **not real pretrained Qwen3 inference**. The existing 30 original evidence/custody/citation cases and these three new tests executed locally on unchanged original LoCoMo (SHA256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`), original 120-request sealed plan `a7ad39c6548b06dc0fd752cd77149deaeb46875b3307696fe2857ef0cd1fc3e9`, and 135M historical journal `0797d8b1a4d9b9e3d7d68925bf4001666f253191d2bac46d90a0af11c78f0d76`: **33/33 PASS in ordinary Python and python -O, no skipped tests**. Exact source/test file Git blob identity is checked separately. Hosted source and actual physical worker remain independently required.

**Disposition:** fix the confirmed loader compatibility first, then execute a distinct exact-head dedicated-branch Qwen trial and inspect the terminal output. Do not relabel the failed physical run or rerun its old SHA as the new experiment. `blocking-ci`, Architecture, immutable owner/permission gates, human semantic support/entailment and matched Reader resource costs are still required. **DRAFT / RESEARCH / HOLD_NO_GO / DENY_ALL / NO MAIN / NO FINALUSE / NO AUTOMATIC CELL SPLIT.**
