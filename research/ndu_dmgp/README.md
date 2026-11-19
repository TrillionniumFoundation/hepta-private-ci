# NDU-DMGP research qualification: A0–A5

Status: **shadow-only reference / NOT production qualified**.
Owner: existing `utility.ndu`, `learning.eval`, `neuron.runtime`,
`learning.artifacts` and CNS owners. No new subject class, execution
authority, production model dispatch or live weight mutation.

## Invariants

- Freeze objective J, hard feasibility, observer, outcome metric, resource
  normalization, base model, decoder, dataset split, compute budget, and
  registered scalarization **before** evaluating any arm.
- No raw critic reward may relabel a measured external task result. Dataset
  rows include source digest, observation time, episode identifier, modality
  spans, tool/model version, sampling policy/joint propensity and censoring.
- Split by episode, principal and observation time. Keep correlated outputs,
  stochastic seeds and all stages of the same trajectory within one split.
  Training critic and evaluation observer must be separate artifacts.
- Reject hard violations before Pareto/scalarization. Retain abstain/no-change.
  Local Cell credit is an *estimate*; only terminal circuit observation can
  certify realized NDU. Preserve registered NDU owner semantics, Q24/Q32
  conventions and next-generation artifact promotion.
- No covariance from separately sampled marginal outputs. Require
  same-condition joint candidate samples, predeclared shrinkage, SPD/condition
  checks, supported sample size, out-of-time covariance calibration. Unsupported
  covariance => use canonical deterministic NDU, not identity covariance.
- Cross-modal verification must bind shared scene/entity identity, factual
  provenance, output timebase, voice/speaker identity where appropriate,
  and token/frame/audio-span alignment. Pair forward checks with
  reconstruction/cycle probes; agreement of two learned judges is not truth.
- Test compressed-state Markov closure using held-out next-state/outcome
  prediction with/without extra history under matched feature and compute
  budgets. If historical information improves prediction beyond a
  preregistered tolerance, enrich state or use history-aware control.
- Always compare total real wall time, GPU active time, actual peak RSS/VRAM,
  measured energy when instrumented, decoder FLOPs/tokens/steps and controller
  overhead. Synthetic counters are only a regression fixture.

## A0–A5 paired experimental arms

| Arm | Controller | What it isolates |
| --- | --- | --- |
| A0 | Frozen encoder + one decoder | Baseline task quality/cost |
| A1 | Deterministic rules and fixed budget | Benefit of scheduling |
| A2 | Learned Top-k/MoE routing, equal train budget | Benefit of routing alone |
| A3 | Frozen NDU one-step advantage | Benefit of NDU signal |
| A4 | A3 + *supported* conditional joint covariance portfolio | Benefit of risk allocation |
| A5 | Recursive NDU + continuation/stop + cross-modal constraints | Long-horizon joint control |

Use paired seeds/input groups and **identical underlying pretrained models**
across A0–A5. Count critic/controller training, evaluation, and deployment
overheads separately. When an arm cannot run on equal budgets, report an
unmatched comparison and do not declare superiority.

## Blocker closure / required external receipts

| ID | Closure evidence | Initial state |
| --- | --- | --- |
| DMGP-01 reward validity | Frozen objective and independent outcome observer; held-out future-window NDU LCB > no-change UCB | OPEN |
| DMGP-02 multimodal consistency | Registered semantic/time/entity schema; independently labeled cross-modal and cycle violations; measured task success | OPEN |
| DMGP-03 covariance | Joint conditional samples; shrinkage/low-rank benchmark; SPD/conditioning, stability and temporal support certificate | OPEN |
| DMGP-04 compute | Host/model/device-bound measured controller, decoder, p50/p95/p99 latency and peak memory; equal-quality cost frontier | OPEN |
| DMGP-05 learning stability | Frozen critic/behavior propensities, trust-region update, recovery, approved next snapshot and old-task degradation <=2% | OPEN |
| DMGP-06 global credit | Causal/joint propensity support, local-vs-terminal utility reconciliation, held-out leave-one-cell-out tests | OPEN |
| DMGP-07 state closure | Held-out history augmentation/interventions and residuals; supported state sufficiency or declared fallback | OPEN |
| DMGP-08 integration | Versioned protocol, production-owned consumer, durable receipts, real decoder execution and independent gate | OPEN |

Until independently produced receipts meet the canonical
`docs/learning/NDU_FBSDE_SPEC.md` thresholds, no item above is closed.

## Reference conformance tests

```sh
python3 -m unittest discover -s research/ndu_dmgp -p 'test_*.py' -v
```

`reference.py` is only a small **deterministic** proof-of-interface of
hard filtering, coupled covariance shrinkage, quadratic surrogate checks
and hidden-history regression. It does **not** estimate causal advantage,
certify covariance, solve FBSDE, simulate real decoders or certify any
performance improvement. All scoring quantities must be independently
supplied in a real experiment. Real integration must call the canonical
Rust NDU evaluator rather than this reference selector.

## Next implementation dependencies

1. Freeze A0–A5 experiment manifest, source dataset/observer and paired
   episode splits in the canonical experiment registry under its owner.
2. Introduce new versioned `GenerationPortfolioProposal` and
   `GenerationPortfolioReceipt` contracts after consumer admission.
   Keep high-dimensional decoder tensors at inference Worker; pass only
   bounded decision features to a scoped Cell.
3. Integrate real decoder workers and event-clock-aligned output verification.
4. Train frozen critic, cross-fitted counterfactual advantage, bounded actor
   and covariance model with the required provenance.
5. Run out-of-time evaluation, support and closure audits, full host performance
   profiling, rollback and preservation tests before any activation.
