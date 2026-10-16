# V20 — Independently replay original mmBERT Head training and price the budget search

**2026-10-16 · DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL.** Additive to original V19 PR #2530 HEAD `bab39533fd81f7dd460812664fadd3d3d2bcce29`. No main modification, production serving, NDU, CellSplit, Worker, CAS/CNS, signature/FinalUse or default selected Encoder/Head change.

## Exact real source and training identity

The original pinned artifact is GitHub Actions run 38546717991, artifact **11890616195**, ZIP SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`. It contains genuine pretrained mmBERT-small **cached** 128×384 FP32 features (SHA256 `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`). V19's original 64 TRAIN, 32 historical CAL, 32 **unscored BLIND** input packet is fixed at SHA256 `d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a`.

**This is not a new pretrained Encoder forward.** There is just one AG News public data family; no new source family, independent original publisher attestation, independent future time windows, heldout BLIND scoring or model production permission.

## Independent training proof (new)

The original V19 reader already independently checked source IDs, every learned Head's weight SHA, numerical forward outputs, train-only OOF choices and CAL scores. V20 now adds a truly different **optimizer/gradient implementation**, not just a rehash or inference recomputation.

- Independently implemented standard C++ 32-bit MT19937 and bounded CPU uniform integer sampler in pure Python. Known Torch-CPU sample golden vectors include seeds 10041/1041 and the 624-word twist boundary.
- Independently implemented multi-class FP32 softmax-cross-entropy gradients, minibatch gathers, and Adam moments, bias corrections and updates in **NumPy only**. No import of Torch, the original producer or its optimizer functions.
- Regenerates all source-specific training batches for each seed's four held-TRAIN folds plus full-TRAIN run, physically computes **all 1,200 optimizer updates**, and reconstitutes the **105 checkpoints** from 7 budgets (1/2/4/8/16/32/80) × (4 folds + 1 full fit) × 3 seeds.
- Each original raw checkpoint's SHA and exact case/order bindings must match; in addition, the separately recomputed learned weights and original pretrained-input logits must agree within conservative FP32 tolerances. The independent replayer then recomputes original OOF Brier, historical CAL results, budget selection and actual Head CPU receipt conservation, denying rehashed false weights/logits or fake free pilots.

### Actual original-CPU result

| Independent comparison | Observed maximum absolute difference |
| --- | ---: |
| 105 Head checkpoint weights | 0.000000134110451 |
| Bias parameters | 0.000000074505806 |
| Logits | 0.000004768372 |

Limits: `2e-6` weights/Bias and `2e-5` logits. This is numerical agreement, **not bitwise cross-host/official model reference parity**. Two separately executed original V19 producers (ordinary/`python -O`) are each fully reverified. All 12 source-only mechanism tests and all 12 original material/adversarial tests pass in each interpreter mode; rehashed weight, rehashed logits, wrong source/case identity, duplicated/missing checkpoints, changed optimizer CPU accounting, false future and authority claims are refused.

Independent reconstruction still does **not** prove independent model issuer signatures, OS-hardened label custody or future task utility. Ordinary test failures do not become production permissions.

## Fairer learning-budget investment comparison

The original V19 OOF controller trained four folds to 80 steps and one full model to 80 steps **per seed**, so it paid **400 updates per seed, 1,200 for three seeds**. We compare that complete, already-incurred research expense with **fixed** budgets (cost *counters*, not claims of measured equal-lifecycle deployed CPU time).

| Candidate | Total optimizer updates (3 seeds) | Historical CAL Brier, mean across repeated seeds | Total correct among three evaluations of same 32 questions |
| --- | ---: | ---: | ---: |
| Fixed 4 steps | **12** | **0.328556** | **75** |
| Fixed 8 steps | 24 | 0.334147 | 73 |
| Fixed 80 steps | 240 | 0.436541 | 72 |
| Fourfold TRAIN-only selection + full fit as actually run | **1,200** | 0.345752 | 73 |

The 75 outcomes are **not 75 independent cases**. The same 32 questions and one data family recur across three seeds. The fixed-4 control was considered after the earlier historical calibration study and cannot become an unexposed future-policy winner. Seed 53 individually benefits from the eight-step policy, while Seed 41 suffers at eight steps. Training-only OOF has not established a cost-adjusted advantage over simple fixed-step training.

The original 1,200-step Head-only local training CPU sum (not full service lifecycle) was 0.413634819 seconds for one observed run. Real full system cost must include original Encoder, caching, evaluation, Reader, signing, persistence, recovery, energy, and target-host contention; CPU time from different implementations is not interchangeable.

## Source-only CI and security

`hepta-stem-v20-independent-adam.yml` is a read-only experimental workflow. It must verify exact event HEAD and tested file identities, securely obtain the original GitHub Actions archive without sending repository credentials to the signed redirect host, validate full original ZIP SHA, regenerate the source-only V19 input packet, execute two separate ordinary/optimized actual V19 model trainings, then run pure NumPy independent Adam twice with real source-bound tamper tests. It publishes no raw source, checkpoint tensors, source text, labels, per-case logits or private model-owner secrets.

An Actions run merely queued, in progress or cancelled is **not** evidence of exact-HEAD acceptance. Source-only tests, original material replay and whole-repository blocking CI are separately scoped. This draft must not be merged or promoted until its own terminal CI is verified, and even a pass cannot remove the independent future/authority gates.

## Next science and production prerequisites

1. Freeze genuine new independent task families and prospective calendar windows before evaluation, with independently governed source/label custody.
2. Treat strong unchanged and fixed 4/8-step alternatives as full-budget controls, including search amortization, negative transfer, calibration and complete reader answer utility.
3. Only if net future utility is positive under the real cost and negative-transfer gates, consider Head upgrade or Cell Split.
4. Independently validate secure host authority, signed final-use, complete durable state recovery and 64/256/1024/4096 Cell CPU/RSS/GPU/p95/p99/WAL/energy on target hosts.

**Disposition: RESEARCH_NO_GO_NO_PROSPECTIVE_POLICY.** The shared frozen Encoder and per-Cell small Head remain promising *as a resource architecture*, but this evidence does not justify autonomous selection, model promotion, production serving or automatic Cell fission.
