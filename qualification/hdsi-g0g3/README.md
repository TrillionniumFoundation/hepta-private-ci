# HDSI G0–G3: scoped Stem fanout + Cell Head + typed Circuit + linear NDU

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. NO MAIN MERGE, NO MODEL PROMOTION, NO FINALUSE, NO PHYSICAL CELL SPLIT.**

This is an **additive child of the frozen original Stem P0 comparison** in PR #2567. It does not update the native Rust `hepta-neuron`/`hepta-ndu` owners, their selected artifacts, the original Stem experiment, Worker, CNS, CAS, memory, truth, learning ledger, or any external-effect authority. It adds no new NDU subject kind: one evidence Circuit is an optimization unit inside an **Episode** subject.

## Four executable boundaries

| Boundary | Implemented | Explicit nonclaim |
| --- | --- | --- |
| G0 `feature_bus.py` | Exact principal/purpose/generation/epoch/revocation/model/preprocess/modality/bytes-scoped feature key; full authorization revalidation for all borrows including duplicates and cache hits; bounded deduplicated batch, atomic cache publication, 4096 logical borrowers | A trusted authorization service or independently attested model execution |
| G1 `physical_fanout.py` | Physically allocated 6,914-scalar rank-8 gated Head slots at 64/256/1024/4096, 32 active; real differentiable Torch math and controlled SGD on **synthetic vectors** in tests | Trained 4096 Cells, semantic task improvement, complete serving TCO |
| G2 `circuit_ndu.py` | Typed 2–6-hop evidence graph, exact source-digest binding, legal-action/risk filtering, deterministic alternative selection, abstain, finite plan proof replay, immutable objective/edge snapshots, 100k-state solver cap | Learned compositional reasoning, independent source-ground-truth validation |
| G3 `circuit_ndu.py` | Bounded Episode preference state + recursive discounted utility; separate exhaustive ordinary Bellman enumerator; fail if entire action/value/path results disagree; independently reproduce the canonical native Rust NDU-GV-001 Q32 ties-even golden | General continuous-time/stochastic FBSDE, NDU-specific advantage |

The exact Q32 golden is a Python reference matching registered native `codex-rs/hepta-ndu` arithmetic; the native Rust runtime was **not** invoked or modified.

The **real-model research runner** imports the existing SHA-pinned `stem_candidate_v1.py` in the *parent PR branch*, verifies original publisher source selection and exact complete model.safetensors bytes (Granite 97M SHA-256 `f3ea88b230492811046145513710e76b4cc8c2ad49e8708da0e7247e548903be`) before loading original FP32 CPU weights. It uses **32 original label-blind held-out public texts**, batched by 16, across four **separate scoped feature-cache lifetimes** with a **single warmed model instance**. Each size therefore proposes 32 physically unique Encoder sequences / 2 actual model forward batches; the 4096 logical fanout does *not* mean 4096 actual model forwards. The actual forward receipt is process-reported, not externally attested.

A second, clearly labeled **metadata graph** derives `case_id → source_sha → actual feature cache key` for each of the 32 public texts. Its complete two-hop path must produce exactly the same action/value as independently enumerated ordinary Bellman for the same deterministic preference/utility profile. **This is a provenance/reference execution test, not natural-language reasoning.** The reviewer independently reconstructs the scope-specific feature key digests from original model/publisher material and rejects counts, model identities, scope keys, cost claims, unknown fields or authority claims that do not match. It does not independently recompute the model's floating-point tensors or certify timing/energy.

The original-public BANKING77 source-owner process emits only source text with TRAIN labels and *heldout text without heldout labels*, sealed before any model/review step. The separate late reviewer re-downloads original publisher bytes from Git revision `57ec275d8078af65b7731c2a98be812d844a6d6b` and validates original train/test SHA-256 and roster. Run-level and joined metric scopes are explicit. The physical job and independent review require exact branch-push HEAD, never run on an untrusted fork PR, and every workflow action uses read-only `contents` permissions. No generated workflow is given source mutation permissions.

## Locally executable evidence, separate from original models

```sh
cd qualification/hdsi-g0g3
python3 -m unittest -q test_hdsi
python3 -O -m unittest -q test_hdsi
python3 -m compileall -q .
```

Requires Python 3.12+ and CPU Torch for the two genuine **synthetic-feature** Torch Head tests. The stdlib-only subset can run with no external modules:

```sh
python3 -m unittest -q test_hdsi.FanoutTests test_hdsi.CircuitTests test_hdsi.ReviewerTests
```

`hepta-hdsi-g0g3.yml` has four jobs: exact-head model-free source conformance → original-public source owner → genuine original Granite97 physical Encoder/Head CPU experiment → distinct label/source/accounting reviewer. A **queued, cancelled, skipped, failed, or mock-only** job does not provide physical evidence. The actual original-model branch job remains a conditional attempt until a complete exact-HEAD terminal run and sanitized artifact are verified.

## Experiment integrity and negative controls

1. **No baseline laundering:** A finite deterministic linear NDU profile must yield precisely the same preference-aware result as an ordinary whole-tree Bellman enumerator. Its mathematical equality is *not* an incremental NDU advantage. Match the preference/cost profile and resource budget to any later learned policy.
2. **No semantic feature claim:** The real source→feature two-hop graph binds identities, *not* model-extracted relations. An independent source-family/future cohort with evidence-dependent natural multi-hop QA, fixed strong BM25/rules, feature-zero/permutation lesions, label-blind Head training and independently checked human targets is still needed.
3. **No free savings claim:** Separate logical borrows from physical model sequences and actual batched forwards; count cold model load, warm cache, allocating *all* resident Heads, active Head execution, training, inference, peak process RSS and independent timing. Resident physical memory is **not** determined by scalar weight bytes alone. Four cohorts share one warmed model, so peak RSS is process-wide and not four isolated process samples.
4. **No hidden authorities:** The `allow_use` callback in the public-data runner is an **experimental constant** and is not a native capability check; integrating production `VerifiedUse` remains a separate ownership/security task. Cached features are never proof of authorization.
5. **No multimodal or generalized System 2 claim:** This physical trial is text-only. Image/audio/video typed identities are exercised by adversarial source tests only; no actual corresponding encoders or decoders execute. No online NDU gradient/FBSDE is claimed.
6. **No self-promotion:** A successful static source check, exact finite-tree parity, genuine forward, or coherent independent artifact review cannot select a Stem, declare NDU lift, split Cells, alter the topology, activate FinalUse, or permit main merge. Existing `blocking-ci` and architecture gates remain mandatory.

## Next independent scientific qualification

Only if the physical multi-scale workflow succeeds: take the **same exact frozen Granite97 source/model** into evidence-necessary source-disjoint 2–6-hop natural QA, use token-level rather than only mean-pooled vectors, compare a cheap exact/BM25 control, frozen/learned Shared Head, Cell-split rank-8 Head, fixed-depth Circuit, adaptive heuristic, ordinary Bellman and fixed-profile NDU with equal physical end-to-end costs. Freeze train/source/calibration/test **before** inference. Add future time windows, independent reader/verifier and lesion tests. If NDU and Bellman tie, preserve that negative result; require task + cost + retention uplift before selecting any learning/structural proposal.


## V2 local original-MiniLM independent physical control — 2026-10-17

This continuation adds `real_minilm_reference.py`, a **six-layer FP32 BERT CPU
implementation** that requires the exact original archived MiniLM model/vocab/
tokenizer/config and LoCoMo public bytes. The original GitHub Actions archive
artifact ID is `11586991191`, outer ZIP SHA256
`07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
The archive and five inner original source/model SHA256 identities are rechecked;
no model material, raw dialogue or publisher labels are committed. This is the
**historical MiniLM control**, **not Granite97**, official Hugging Face parity,
or the selected production Stem.

`LOCAL_MINILM_ORIGINAL_CPU_20261017.json` contains one actual original-model CPU
run: **160 complete physical six-layer forwards** (4 × 32 independent physical
Encodings + 32 additional full no-cache comparison), 32 distinct source-first
public utterances spanning 9 of 10 available conversation roots, and resident
6,914-scalar FP32 rank-8 Head slots at 64/256/1024/4096 Cells. Each cohort
physically encoded 32 original input strings once, reused those same 32 values
for N scoped logical borrows and verified Head output identities on cache hits.
The additional no-cache 32 original forwards had identical 384D FP32 features.
All numeric CPU/wall/RSS observations are **local whole-process self-reports**;
startup/Head execution and input reuse are not a target-host p95/p99/energy SLA.

An entirely separate model-free source evaluator,
`review_real_minilm.py`, reopens original LoCoMo bytes and independently
reconstructs the source-first 32-case set and all physical work scopes.
`LOCAL_MINILM_INDEPENDENT_REVIEW_20261017.json` records this **limited** review:
it does **not** independently execute pretrained weights or attest hardware.
`LOCAL_MINILM_NUMERIC_PROBE_20261017.json` records another independent
same-host, original-weight six-layer BERT numerical probe: two different
implementations yielded identical CLS+Pooler hashes, but historical
cross-host hashes **differ**; do not claim cross-host bitwise model parity.

Actual unoptimized+optimized local Python suites after V2 are **39/39 each**:
30 inherited G0–G3 methods and nine additional original-source/security
contract tests. The source-only workflow exercises the added nine methods
without accessing model bytes; **it does not execute the real pretrained
MiniLM workload in Actions**. The only scheduled heavy original GH job remains
the separately SHA-pinned Granite97 path, which must actually terminate.

To independently replay the local MiniLM experiment after safely extracting the
original archive and SHA-verifying its member identities into `<ROOT>`:

```sh
cd qualification/hdsi-g0g3
python3 real_minilm_reference.py --original-root '<ROOT>' --output /tmp/hdsi-minilm-original.json
python3 review_real_minilm.py --root '<ROOT>' --receipt /tmp/hdsi-minilm-original.json --output /tmp/hdsi-minilm-review.json
python3 -m unittest -q test_hdsi test_real_minilm_reference
python3 -O -m unittest -q test_hdsi test_real_minilm_reference
```

There is still no prospective relation/QA answer correctness, learned old/new
retention, multimodal necessity, native Rust source-integrated Cell run,
mathematically certified stochastic FBSDE, NDU-vs-Bellman gain, or production
model/CellSplit authorization. **DRAFT / RESEARCH_ONLY / DENY_ALL**.
