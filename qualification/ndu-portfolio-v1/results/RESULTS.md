# NDU portfolio validation: measured results

Overall status: **RESEARCH_ONLY_HOLD**. Finite control and reference contracts run; real multimodal efficacy is unmeasured.

Base source: `732e934ba496d90fbe042b8d41d479ef901643e5`. Exact tested source manifest: `2c8b54b6e3df467ac48c446e83a2443b8f556575510cc6ad3e27eb36517fba33`.
Run mode: **full predeclared toy protocol**. Python 3.12.14, NumPy 2.3.5, float64 CPU.

## Evidence by stage

| Stage | Executed evidence | Decision |
|---|---|---|
| 1: exact control | 63 focused regression tests across the package; DP/enumeration; gradients; learned gaps | PASS for finite reference only |
| 2: real text + image | Artifact transport and independent scoring contracts; synthetic transport fixture | HOLD: no configured frozen real provider, dataset, or independent evaluator |
| 3: adapter training | Actual NumPy updates through 50 parameters; heldout synthetic probes | REJECTED synthetic candidate; real stage HOLD |
| 4: audio/video streaming | Multirate prefix, budget, shared-work and reservation invariants | PASS for ledger reference; real media HOLD |

## Exact control checks

The largest DP versus exhaustive policy-tree discrepancy is 3.33e-16. The largest checked policy-gradient error is 8.65e-12.
The published Q32 NDU-GV-001 arithmetic vector also matches. The native Rust workspace was not compiled in this environment.
The entropic profile includes policy randomization in the risk lottery and discounts by actual action duration. Its zero-risk limit is ordinary expected utility. It is not the general stochastic FBSDE solver.

| Risk | Seed | Learned recursive value | DP optimum | Gap |
|---|---:|---:|---:|---:|
| 0 | 11 | 0.91256667 | 0.91599426 | 0.00342759 |
| 0 | 29 | 0.91256710 | 0.91599426 | 0.00342716 |
| 0 | 47 | 0.91256552 | 0.91599426 | 0.00342874 |
| 0.25 | 11 | 0.90251165 | 0.90611914 | 0.00360749 |
| 0.25 | 29 | 0.90251190 | 0.90611914 | 0.00360724 |
| 0.25 | 47 | 0.90251043 | 0.90611914 | 0.00360871 |
| 2 | 11 | 0.83281613 | 0.83722114 | 0.00440502 |
| 2 | 29 | 0.83281487 | 0.83722114 | 0.00440627 |
| 2 | 47 | 0.83281185 | 0.83722114 | 0.00440930 |

Different-risk rows have different objectives; their raw utilities are not efficacy comparisons.

## Common-observer controller comparisons

All controllers below are scored on the same original toy environment. The shared learned routers have 130 parameters, identical initializations per seed and equal update counts. Test configurations never enter gradient fitting. These are exact model-based routers, not actor-critic training.

### Training configurations

Equal-weight means across configurations and seeds; descriptive toy results, without a real-model significance claim.

| Controller | Joint success | Weakest quality | Compute units | Duration ticks | NDU gap |
|---|---:|---:|---:|---:|---:|
| fixed_single_pass | 0.3029 | 0.6515 | 3.500 | 4.500 | 0.10394 |
| fixed_cyclic_allocation | 0.6752 | 0.8376 | 4.426 | 5.804 | 0.01328 |
| one_step_greedy | 0.5984 | 0.8263 | 4.036 | 5.295 | 0.02044 |
| ordinary_learned_router | 0.6096 | 0.8451 | 4.362 | 5.651 | 0.02062 |
| ndu_learned_router | 0.5876 | 0.8224 | 4.350 | 5.556 | 0.02840 |
| ndu_no_explicit_cross_modal_features | 0.5480 | 0.7917 | 4.314 | 5.404 | 0.03770 |
| ndu_no_dynamic_preference | 0.5119 | 0.7670 | 4.158 | 5.158 | 0.04076 |
| ndu_no_risk | 0.6096 | 0.8451 | 4.362 | 5.651 | 0.02062 |
| exact_dp_oracle | 0.6752 | 0.8718 | 4.364 | 5.748 | 0.00000 |
| ndu_two_step_oracle_continuation | 0.6752 | 0.8718 | 4.356 | 5.742 | 0.00025 |

NDU minus ordinary-router joint success: **-2.193 percentage points**.

### Unseen budget/cost configurations

Equal-weight means across configurations and seeds; descriptive toy results, without a real-model significance claim.

| Controller | Joint success | Weakest quality | Compute units | Duration ticks | NDU gap |
|---|---:|---:|---:|---:|---:|
| fixed_single_pass | 0.3155 | 0.6578 | 3.667 | 4.333 | 0.05263 |
| fixed_cyclic_allocation | 0.4947 | 0.7474 | 4.367 | 4.901 | 0.01183 |
| one_step_greedy | 0.4159 | 0.7485 | 3.899 | 4.734 | 0.01089 |
| ordinary_learned_router | 0.4780 | 0.8044 | 4.434 | 4.950 | 0.02490 |
| ndu_learned_router | 0.4770 | 0.7891 | 4.443 | 4.902 | 0.02779 |
| ndu_no_explicit_cross_modal_features | 0.4686 | 0.7699 | 4.445 | 4.823 | 0.03004 |
| ndu_no_dynamic_preference | 0.4601 | 0.7631 | 4.419 | 4.780 | 0.03244 |
| ndu_no_risk | 0.4780 | 0.8044 | 4.434 | 4.950 | 0.02490 |
| exact_dp_oracle | 0.4630 | 0.7730 | 4.184 | 4.906 | 0.00000 |
| ndu_two_step_oracle_continuation | 0.4630 | 0.7730 | 4.184 | 4.906 | 0.00027 |

NDU minus ordinary-router joint success: **-0.096 percentage points**.

The explicit cross-modal-feature ablation preserves the joint reward; it removes minimum/product features only. A separate fully factorized model has not been tested. No-risk and ordinary router are identical in this profile.
The fixed single-pass run is a cheaper reference. The fixed cyclic schedule uses spare quota before final verification. Equal generation caps do not imply equal actual expenditure or matched total physical computation.
The two-step planner uses oracle model continuation. Its measured host wall time is reported in JSON, but is not charged to toy generation units. Planner expansion counters are exhaustive-evaluator totals and exclude leaf recursion. No net efficiency benefit is established.

## Adapter outcome and retention gate

Training objective: -0.392505637 to -0.324305647. Maximum adapter-gradient error: 8.94e-12.
Heldout Brier scores: [0.3001402201669121, 0.2774233665537409] to [0.1964214087993641, 0.2618541182857523].
Old-base prediction drift: **0.032044365**, with a fixed 0.02 limit. Candidate decision: **REJECTED**. Selected parameters remain unchanged; the candidate is not selected.
These are synthetic probability-prediction probes. Prediction spread is a diversity proxy, and old-base drift is a retention proxy. Neither substitutes for semantic diversity or real old-task evaluation.

## Streaming accounting

The fixture records 39 compute units, with shared encoder work counted once. Controller and verification work remain charged. Delivered audio/video prefixes cover 80 ms at different chunk rates; an attempted delivered-prefix rewrite is rejected.
Only timestamp coverage and ledger behavior were tested. No audio/video content was generated and no perceptual synchronization score was measured.

## Concrete remaining qualifications

1. Bind actual frozen text/image model revisions and weights, task dataset, provider execution path, and independent evaluator provenance.
2. Run every registered baseline on paired real tasks at equal total budgets, including controller/planning, verification, failures and evaluation.
3. Collect independent task quality, contradictions, omissions, critic calibration, tail failure, OOD performance, diversity and old-task retention.
4. Train real Cell/control/generator adapters only as candidate snapshots, then apply the frozen independent gates.
5. Bind real audio/video decoders and evaluate long-horizon streaming, content synchronization and delivery latency.

Increasing internal NDU or lowering numerical residuals alone does not close these qualifications. The present evidence does not establish that NDU is necessary or superior to an ordinary controller.
