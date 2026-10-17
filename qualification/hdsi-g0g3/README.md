# HDSI G0–G3: scoped Stem fanout + Cell Head + typed Circuit + linear NDU

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. NO MAIN MERGE, NO MODEL PROMOTION, NO FINALUSE, NO PHYSICAL CELL SPLIT.**

This is an **additive child of the frozen original Stem P0 comparison** in PR #2567. It does not update the native Rust `hepta-neuron`/`hepta-ndu` owners, their selected artifacts, the original Stem experiment, Worker, CNS, CAS, memory, truth, learning ledger, or any external-effect authority. It adds no new NDU subject kind: one evidence Circuit is an optimization unit inside an **Episode** subject.

## Four executable boundaries

| Boundary | Implemented | Explicit nonclaim |
| --- | --- | --- |
| G0 `feature_bus.py` | Exact principal/purpose/generation/epoch/revocation/model/preprocess/modality/bytes-scoped feature key; full authorization revalidation for all borrows including duplicates and cache hits; bounded deduplicated batch, atomic cache publication, 4096 logical borrowers | A trusted authorization service or independently attested model execution |
| G1 `physical_fanout.py` | Physically allocated 6,914-scalar rank-8 gated Head slots at 64/256/1024/4096, 32 active; real differentiable Torch math and controlled SGD on **synthetic vectors** in tests | Trained 4096 Cells, semantic task improvement, complete serving TCO |
| G2 `circuit_ndu.py` | Typed 2–6-hop evidence graph, exact source-digest binding, legal-action/risk filtering, deterministic alternative selection, abstain, finite plan proof replay | Learned compositional reasoning, independent source-ground-truth validation |
| G3 `circuit_ndu.py` | Bounded Episode preference state + recursive discounted utility; separate exhaustive ordinary Bellman enumerator; fail if entire action/value/path results disagree | General continuous-time/stochastic FBSDE, NDU-specific advantage |

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
