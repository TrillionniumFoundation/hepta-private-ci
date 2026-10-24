# Independent review of the frozen retention experiment

Review date: 2026-10-24. Reviewer: Codex architecture/adapter lane.

**Disposition: no blocking implementation or preregistration defect found in the reviewed candidate.** This is a source review of the bounded study, not an empirical efficacy result or a production activation approval. This lane did not encode the corpus, fit an empirical arm, read the new final-label payload, or invoke the scorer on actual experiment data.

## Exact reviewed identity

| Artifact | SHA256 |
| --- | --- |
| `cell_field_retention_experiment_protocol.json` | `5f963295e4e49a64cde085aa2a4dde92c291df3b0450d768f986264e482d3832` |
| `EXPERIMENT_FREEZE_CANDIDATE.json` | `a2baf8ed6c7602e642c6da0beb592e709f037ab9bb9c039b467e6ef3ad894e09` |
| Existing fixture verification log | `d61a51095da5edd2bb110b7c0f0f8a1682f8e24ebc1c7c55e281376485a32a74` |
| Prepared cohort receipt, pinned by the protocol | `7af61dfa851583d6d31c0163b5d9453841e21bef106058206731870d706364df` |

All eleven runtime-source hashes and the scorer hash match the frozen manifest. The existing verification receipt and its matching log report 58 successful constructed-fixture tests, with warnings treated as errors. I inspected those tests and verified the log hash; I did not independently rerun them. Source-selection commit `eebec960513dc9f58b830a8674a924a605fa532e` and the three registered exposure inventories remain the source-admission evidence owned by the science lane.

Candidate sources are in `neuron-audit/retention-runner/patch/qa/stem-bakeoff`; original owner implementations are in `neuron-audit/current-science` and `neuron-audit/retention-fix/base`. The separately reviewed immutable optional solver is in `neuron-audit/retention-fix/patch/qa/stem-bakeoff`.

## Findings

### 1. The deployed optimizer and reference remain the original ones

`cell_field_retention_run.py::_validate` requires the actual `CellTrainingState` and `Reference`, exact original complete-state identity, a matching selected current-training context, and an exact replay of the original no-control trajectory and observations. The original old-probe anchor must equal the warmup endpoint's observed old loss. It cannot be reset at a suffix or recovery point.

Each hinge decision measures the actual full-state displacement from the original reference and solves a suffix of the original `A/E/C` arrays and targets. It then calls the unchanged `CellTrainingState.advance`. That owner updates theta, Adam moments, counters and sampler state; the parameter intervention is added after the ordinary Adam update. `Reference.action_matrix` already contains `dt`, and the deployed physical intervention is `dt * B @ action` exactly once. The supplied tests check bitwise original zero/quadratic parity, moment preservation, masks, physical scaling, and an independent actual-state suffix calculation.

The quadratic comparator is full-state Riccati feedback, not an open-loop frozen action list. Its precomputed feedback is the original quadratic suffix solution evaluated at the observed state. The nonlinear deployment is nevertheless only the application of the declared tangent-model policy. The source correctly does not claim that the affine optimum guarantees a nonlinear optimum or a hard old-loss constraint.

### 2. New final labels are separated from the fitting path

`cell_field_retention_experiment.py::execute` obtains only training/probe labels from the original `_inputs` helper. The projection is generated from a fixed Gaussian matrix and QR signs without labels. Workers receive the sealed reference, its training/probe arrays, the complete warmed state, and prediction inputs; their request contains no final-label payload.

The new final-label hash is copied from the previously prepared cohort receipt, rather than recomputed by opening the gold file during fitting. The original `_deny_final_labels` hook also refuses opens whose basename is `final_labels.json`. This is a guard against accidental access by the reviewed trusted Python code. It is not an adversarial filesystem sandbox, and it does not establish that labels were unknown during source selection: the source-only preparation necessarily used raw categories for class-balanced allocation and conflict rejection.

`cell_field_retention_score.py::score` validates the externally supplied seal, protocol/scorer source, complete condition census, every finite normalized prediction, and source ordering before its first new final-label read. A failed condition yields `blocked_incomplete_conditions` without requiring the gold file to exist. Exact key census validation also rejects missing conditions or duplicate/replaced identities. There is no complete-case subset scoring path.

### 3. Failure and recovery claims match the implemented boundary

All eighteen slots are retained. Numerical or magnitude failures preserve the actual applied prefix, incurred solve work, failed status and no final objective score. Hard worker termination produces a failed condition with an explicitly unknown post-checkpoint prefix. It never becomes a zero-effect or successful result.

Each empirical arm is a fresh sequential CPU worker. Its outer process CPU limit is 15 seconds, wall limit 75 seconds, and the inner controller checks its 10-second CPU / 60-second wall limits cooperatively between bounded operations. The parent terminates that worker PID; the implementation explicitly invokes no condition subprocesses. These limits are not a general process-tree sandbox, do not bound acquisition or encoding, and do not by themselves impose one overall deadline on the common warmup/reference stage. The execution owner should retain its separate whole-job deadline and resource record.

Full-state and serving-head save/reload checks are part of every completed empirical arm and charged to its worker. Interrupted mid-trajectory replay is tested separately using a paused checkpoint, exact action replay, frozen contract and original anchor. The final frozen protocol explicitly says this is not an extra empirical arm or an empirical recovery/net-cost result. This resolves the more expansive recovery wording in the earlier draft. Local checkpoint publication is checksummed and exclusive, with no fsync/power-loss guarantee claimed.

### 4. The estimands and claims are appropriately limited

The primary future contrast is hinge minus legacy NLL, averaged across the three fixed seeds within each source component, then equally weighted across June and July. The old-test retention contrast is hinge minus the **original warmed head**, with a 0.02-nat margin. A degraded legacy comparator cannot make an actually degraded warmup-retention result pass.

The scorer uses the same 2,000 category-stratified paired source-component resamples for arms, seeds and heads. Each of the two predeclared heads must satisfy both its future and retention gates at the stated one-sided 97.5-percentile upper bound. The documented Bonferroni treatment across heads and intersection of the two gates are coherent with the stated approximate bootstrap inference. The interval is conditional on these fixed fits and this balanced historical source design; it does not estimate uncertainty across arbitrary training seeds, task families, future traffic or model pretraining exposure.

The source-selection shortage and the June/July amendment were explicit before new model outputs. Registered-source disjointness is limited to the three pinned inventories and their story/title closure. The code and protocol do not promote this into exhaustive novelty, agent-task success, cell splitting, learned network topology, general intelligence, or deployment benefit.

### 5. Cost evidence must remain disaggregated

The experiment records common warmups/references, actual worker elapsed and reaped CPU, nested controller/phase costs, persistence and reload costs, and worker/owner process high-water RSS. Nested costs must not be added twice. Earlier acquisition, closure, preparation and encoding costs remain separate stages. Worker RSS high-water observations do not establish simultaneous total memory, incremental memory per arm, or energy use. Passing either a probe objective or the statistical gates cannot alone certify net benefit.

## Reporting requirements after execution

- Retain this exact protocol and source identity before encoding/fitting. A changed source or setting is a new reviewed protocol, not an unreported retry.
- Preserve every failed or incomplete condition and its logs. If the complete census fails, keep gold unopened and report that outcome.
- Report the original-warmup retention contrast and both predeclared heads, including all seeds and months, alongside the legacy-relative secondary contrast.
- Report empirical costs with the separate preparation/encoding and common-reference records; do not substitute only suffix-solver time.
- Describe any successful result as evidence for this bounded optional retention policy on this historical classification family. Broader cell/network and native-agent claims still need separate experiments.

The scorer's `scored_once` status denotes one immutable output publication. Exclusive creation prevents overwriting that output path; it is not a global single-use authorization or a filesystem restriction against rerunning the same deterministic scorer to a different path.
