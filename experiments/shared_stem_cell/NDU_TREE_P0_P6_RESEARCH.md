# Shared Stem → Cell Head → NDU System 2 → finite-tree BSDE: P0–P6 increment

**Research/SHADOW only; no authority; stacked upon Draft #1885.** This increment does not install a second Encoder, Reader, durable NDU owner or production Neuron runtime. It does not rewrite #1550, #1760, #1775, #1794, #1897, or #1826.

## What executes in this source

- `ndu_tree_global.py`: exact-rational **finite-public-information** belief DAG with OR actions and a mandatory cost-free `stop`, AND bottleneck obligations, and public binary CHANCE events. For each CHANCE node, compute `Sigma=p(1-p)`, `Z=U_right-U_left`, and `B=Z*Sigma`; reject incompatible conditional laws. Backward values are independently checked with a separate fixed-policy forward enumeration. No hidden-world IDs or future observation values can act as inputs to a pre-observation decision. The cheap exact expectation control is intentional: there is **no claim that the finite BSDE improves upon probability algebra**.
- `audit_piecewise_global` checks the *entire* specified deterministic FBSDE (`dX=Y dt`, `dY=0`, `X0=x0`, `YT=g XT`), including each local dynamic equation, both `X` and `Y` at every segment interface, elapsed horizon, terminal condition, and global regular-field admission. The mandatory #1550 obstruction at `x0=1,g=1,T=1` has **no** global solution even though both short segments can have unique locally reset terminal BVPs, zero local residual and zero last-terminal residual. At `x0=0` and `gT=1` global solutions are nonunique. At `gT>1` the algebraic boundary may be unique but the registered regular decoupling field crosses a pole and remains **unsupported**.
- `ndu_cell_distill.py`: train-only actual PyTorch AdamW fitting of the **existing #1885** `StateGatedCellHead` using externally supplied feature rows and teacher action labels; future prediction without labels; separately sealed and checked future scoring; cross-group/time rejection, physical step/wall metering and Head-weight tamper rejection. A held-out **toy** task demonstrates fitting; an opposing-task evaluation demonstrates severe negative transfer. This is **not** a pretrained reasoning result or an old-task retention certificate.
- `ndu_p0p6_receipts.py`: strict four-arm snapshot/Reader/task/initial-Head/budget parity preflight for Laya421, Granite97, mmBERT-small and EmbeddingGemma2, complete 64/256/1024/4096 **self-reported numeric** cell-scale census with observed percentile math (no invented energy), and explicit P0–P6 mechanism-vs-independent-qualification blockers. Byte IDs and declared counters are *not* external attestation, so all resulting reports have `production_accepted=false`.

Run (within the #1885 research base, with pinned installed CPU Torch):

```bash
PYTHONPATH=experiments/shared_stem_cell python3 -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_ndu_*.py' -v
```

The dedicated read-only workflow records current exact SHA, tree and dependency inventory, retains raw failure logs and reports stage nonpromotion. Original #1885 multimodal alignment, fan-out, scope and local Head tests remain separate and must continue to pass.

## P0–P6 dependency/acceptance matrix (NONE independently accepted here)

| Gate | Reuse before extending | Independent evidence needed |
|---|---|---|
| P0 | #1775 EmbeddingGemma real-text canary, #1718 ModernBERT canary, #1897 Granite control, existing Laya arms | Four *actually loaded* pinned checkpoints, same Reader/cohort/objective, fair CPU/GPU and total training budgets, independent ground truth |
| P1 | #1885 shared features and 9,744-parameter Head, #1794 measurement contracts | Physical Worker and Neuron Q24 execution, real shared buffers, 64/256/1024/4096 actual Cells, concurrency, p50/p95/p99, true GPU/RSS/energy where observed, WAL and recovery |
| P2 | #1885 fit/predict/evaluate, #1775, #1838 audio, #1875 video | Real image/audio/video towers, source-disjoint heldouts, contradictions/donor swaps, old-modality retention, cost-adjusted external task improvement |
| P3 | #1760 / #1754 bounded propose/verify/revise and paired critic, #1697 Group search | Same model/proposer/Verifier, genuine no-search/fixed-depth/vanilla-tree/critic controls, true per-arm resource census and external success labels |
| P4 | #1550 exact obstruction and finite belief tree plus new local tests | Whole-horizon terminal, exact interfaces, nonanticipativity, covariance `Z Sigma = B`, global decoupling-field regularity and numerical error/stability independently witnessed |
| P5 | Existing native `utility.ndu` deterministic recursion, #1826 matrix-free tests | Qualified coupled coefficient manifests, independent stochastic solver/covariance, same-task cheap Bellman controls, real outcome gain greater than all solver costs |
| P6 | Existing lightweight Cell Head; `ndu_cell_distill.py` candidate fitting | Source-disjoint future successes, prior-task retention/nonregression, head split/merge and rollbacks, actual cost/quality Pareto gain and independent selected artifact admission |

## Explicit limitations

1. **Finite-tree BSDE ≠ coupled stochastic FBSDE.** The analytic obstruction check is deterministic and exact for a single special coupled family. There is no proof of arbitrary global solvability or neural-language reasoning.
2. **A node is a public belief state, not an arbitrary token or Transformer layer.** `AND` uses an explicitly registered *bottleneck* utility, not silent additive rewards. History/state/filtration and policy semantics must be separately qualified before generalizing to merged DAGs.
3. **Decoder/Reader/Verifier are not provided here.** Real natural-language proposals, evidence entailment and citations are upstream/downstream independent owners; this contribution never claims new multimodal or generative capability.
4. **No source auth inferred from SHA.** Self-reported model/host counters and self-reported outcomes cannot be promoted; independent production signers, artifact storage, Q24 native port, worker dispatch and target-host tests remain external.
5. Keep the research worktree stacked. Do not cherry-pick other candidate branches blindly, force-merge, bypass `blocking-ci`, select CURRENT, or reinterpret any historical failed/queued workflow as a pass.

Any positive efficacy report must freeze tasks and controls **before** running, seal all predictions before independently opening future labels, preserve failures, and compare observed quality/cost including real physical Encoder calls. `phase_blockers` deliberately cannot set `independent_acceptance=true`.
