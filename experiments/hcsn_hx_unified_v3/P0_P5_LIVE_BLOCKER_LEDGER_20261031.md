# HCSN P0–P5 live blocker ledger — 2026-10-31

**Admission invariant:** `RESEARCH_ONLY / DENY_ALL / NO_GO`; `production_activation=false`; `all_scientific_blockers_closed=false`. This ledger is a cross-PR status snapshot, not a claim that independently stacked drafts have been merged, run together, or admitted.

## Current evidence chain

| Gate | Latest research | Evidence already obtained | Still blocking |
|---|---|---|---|
| P0 financial HX | [#4499 PDE + discrete certificate](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4499), [#4508 conditional debt interval](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4508), [#4496 independent density obstacle](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4496) | Independent maturity PDE and first-hit density methods; finite-grid rational Bellman residual certificate; conditional uncertainty propagation; retained high-liquidity extra-STOP witness | Real certified enclosures for every debt cashflow and far-field boundary (including maturity/default corner); resolve 101-node vs refined mesh disagreement; self-consistent bond/equity/default boundary fixed point; global continuum obstacle/domain; true financial FP32/BF16/GPU and active-set gradient enclosure |
| P1 Call/Risk/Margin | [#4500 eight-arm pilot](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4500) | 8 arms, 2 tasks, 5 paired seeds, 80 trainings; local anchor value/signed-slope matching; Holm correction | 14/14 adjusted tests p=1.0; global feature/information matching absent; actual total CPU not strictly equal; raw 80-record result not losslessly stored in GitHub; dynamic full-HCSN and independent blinded positive replication |
| P2 event memory | [#4501](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4501), [#4503](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4503), [#4506](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4506), [#4507](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4507) | Trainable content GRU, physical timestamp FIRE migration, checkpoint replay, 12 CPU-matched exploratory runs, independent auditor and future create-only recorder | Copy OOD strongly degrades under physical-time arm; MQAR OOD inconsistent; historic mutable-output provenance mismatch unresolved; exploratory pilot unblinded; standard MQAR, broader lengths/overwrite/irregular time and real independent confirmation; actual host crash/fsync power-loss semantics |
| P3 multimodal | [#4362 six-stage evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4362) | Real audiovisual subset and finite paired studies | Distinct genuine text/image/audio/video encoders; paired heldout cross-modal retrieval, temporal alignment, corruption/noise OOD; full end-to-end costs and generalization |
| P4 native compute | [#4493 native R9](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4493), [#4362](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4362) | Rust owner/content execution, subprocess restart samples, source-bound receipts | Full clean Cargo/bootstrap reproducibility; GPU native differentiable event/content kernels; 64/256/1024/4096 real Cells; p95/p99/RSS/transfer/queue/energy; actual host/power-loss recovery and no CPU fallback ambiguity |
| P5 Hybrid scaling | [#4159](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4159), [#4182](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4182), [#4362](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4362) | Bounded comparisons against ordinary gates, SSM/Mamba and Transformer | Blocked until P1–P4 show positive quality-cost net benefit; new same-data/tokens/FLOPs/training CPU/inference CPU/RSS/energy matched study and heldout confirmation |

## Exact next execution order

1. **P0-A — real-input conditional error budgets:** run the #4508 exact-rational conditional gate against every #4499 PDE grid. Do not invent debt or far-field error bounds from solver disagreement. First derive independent residual/rounding/time/space/tail bounds; if any term is not bounded, emit `UNRESOLVED`.
2. **P0-B — coupled equilibrium:** jointly iterate the candidate boundary and debt/equity obstacle, preserve multiple roots/nonexistence, and require cross-method agreement at 101/201/401 plus independent wider domains. No finite-grid result alone closes the continuum claim.
3. **P0-C — precision/gradients:** add interval or outward-rounded financial kernel reference for FP64/FP32/BF16; active-set crossing must return ambiguous/refuse; finite-difference checks do not substitute for derivative enclosures.
4. **P1 confirmation:** preserve #4500 as exploratory/negative. Register a fresh confirmatory protocol with sufficient paired seeds, globally matched feature/information/cost, all eight arms and ordinary tuned recurrent/Transformer/SSM controls; archive raw outputs create-only before evaluation. No positive claim without multiplicity-adjusted OOD benefit and noninferiority.
5. **P2 repair:** resolve source of Copy OOD degradation and mutable writer provenance; use the new create-only recorder from the first byte of every fresh training run; full standard MQAR plus overwrite/irregular clocks and real process kill/restart.
6. **P3/P4 parallel:** freeze real encoder revisions and licenses; pair text/image/audio/video samples; add corruption/temporal split. In parallel, build native Rust/GPU kernels and measure complete end-to-end queue/transfer/compute/checkpoint costs at 64–4096 Cells.
7. **P5 last:** only after P1–P4 positive gates, run same-data/token/FLOP/total-CPU inference-budget backbone comparisons. Otherwise retain NO_GO and stop scaling.

## Reporting rules

- Every test is scoped to its exact source SHA and runtime/hardware. Local reconstructed subsets are not full repository CI.
- Finite-grid exact rational certificates apply only to the quantized finite system. Conditional certificates do not validate their external uncertainty hypotheses.
- Cross-method disagreement is a blocker, not a vote to select the favorable solver.
- Missing energy, latency, GPU, or recovery metrics remain null/unknown.
- Historical negative records and failed provenance are append-only; no deletion, relabeling or threshold relaxation.
- PRs remain draft/unmerged and production authority remains denied until independent review and all admission criteria are actually satisfied.
