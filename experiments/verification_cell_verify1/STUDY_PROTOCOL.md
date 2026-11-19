# VERIFY-1 real-model protocol

Status: prospective design. No real-model fitting, inference matrix or independent
task evaluation is established by the SQLite engineering experiment.

## Primary event and study unit

The primary event is at least one preregistered goal error in an accepted complete
trajectory, adjudicated by an independent outcome checker. The study unit is a
task source or episode group. Multiple steps, retries, roles and repeated draws
from one model do not create independent training or task samples.

Before confirmation, freeze the exact task source manifests, train/development/
calibration/confirmation/retention groups, predictor artifacts, model loaders,
rubric, checker version, thresholds, budgets and analysis code. Group materials
from the same source together. Tune only on permitted development data. Keep a
complete attempt roster, including unstarted, failed and unresolved work.

## Required arms

| Arm | What must actually execute | Required provenance |
| --- | --- | --- |
| Deterministic rules | Host rules over exposed observations | Rules/checker version and consumed evidence |
| Single-step self-evaluation | One model's original risk output | Base/adapter/prompt/decoder/seed and inference receipt |
| Historical statistics | A fitted history-only predictor | Training groups, parameters and fitting costs |
| Same-budget voting | The registered voter calls before aggregation | Each original output plus full call costs |
| Fixed check timing | A preregistered schedule | Same available checkers and budget envelope |
| Learned check selector | Learned/admitted risk and cost inputs | Frozen policy, training history and all planning costs |
| External checks | Actual tool/host/readback checkers | Checker identity, effect state and uncertainty |

The voting factorial is shared base with distinct roles, one base with different
adapters, and different bases. Record shared training material, retrieval,
memory, prompts and communication rules where known. Blind the voters' original
outputs before aggregation; communicating ensembles are a separate condition.
Different base hashes are an experimental factor, not proof of independence.

Do not replace a missing model with a named stub, copy one output into several
voters, or construct oracle labels from the risk score. A tool-returned hash can
prove bytes were observed; it does not independently establish semantic success.

## Faults and authentic host enforcement

Inject stale observations, missing receipts, semantic errors, partial success and
shared errors into frozen multi-step tasks. Preserve uninjected controls and
the exact injection point. Record when a fault becomes externally observable.
The injector must be hidden from the predictor interface. The outcome checker
must inspect all trajectories, including rejected or interrupted ones.

Existing host permission, revocation, ownership, deterministic invariants and
effect readback gates remain mandatory in every arm. Vary optional checks while
preserving those gates. Any cost-driven omission of a mandatory check yields a
blocked/deferred task, never an automatic success.

## Metrics and statistical interpretation

Report started trajectories, accepted trajectories, accepted confirmed errors,
accepted unknown outcomes and complete unknown/failed/unstarted denominators.
With accepted count N, errors E and unresolved labels U, [E/N,(E+U)/N] describes
label uncertainty only. N=0 has no estimated selective error rate.

Freeze the risk–coverage threshold set and final selection policy before
confirmation. Report the whole curve, including zero/low coverage and ties.
An always-abstain policy cannot establish useful reliability. The engineering
templates and repeated episodes cannot establish independent task count.

Measure injection-to-detection delay and detection-to-effect/acceptance lead
separately. Retain undetected/censored cases. Report common error clusters,
pairwise error correlations, unnecessary interruptions, recovery success and
the complete cost envelope. Include model loading, encoding, inference,
planning, checks, synchronization, failures, retries and recovery. Unknown
energy/provider charges stay unknown; avoid summing overlapping parent/child
cost envelopes twice.

Use inference methods appropriate to the frozen group structure and sampling
design. Pilot variance and effect size should determine a prospectively frozen
confirmation sample size; no sample-size or efficacy claim is made here.
Any confidence bound must name its event, unit, sampling/selection assumptions,
finite-sample conditions and drift limits. Per-step score coverage and a chosen
alpha-spending sequence do not create unconditional trajectory correctness.

## Intervention experiments

1. Hold evidence bytes, state, outcome, seeds and budget fixed; change only the
   admitted risk signal. Check that optional computation responds while current
   permissions and required effect readback remain unchanged.
2. Hold evidence and risk fixed; change only the declared checker cost. Compare
   decisions with the registered objective. Record declared cost separately
   from actual measured cost.
3. Perturb a confidence representation only when the model/artifact supports an
   actual activation intervention. A hand-written probability edit is not this
   experiment, and behavioral sensitivity alone does not show calibration.

## Research sources and scope

- Vivar-Lazo and Fetsch, *Neural basis of concurrent deliberation toward a choice
  and confidence judgment*, online 2025-11-18, Nature Neuroscience 2026.
  <https://pubmed.ncbi.nlm.nih.gov/41254284/>. A task-specific neuroscience result;
  it motivates parallel monitoring but does not certify agent risk prediction.
- Kumaran et al., *Causal evidence that language models use confidence to drive
  behaviour*, Nature Machine Intelligence 2026, arXiv v3 2026-09-18.
  <https://arxiv.org/html/2603.22161v3>. Confidence can change abstention behavior;
  this is separate from correctness and calibration.
- Ning et al., *Per-Step Conformal Calibration Does Not Transfer to Agent
  Trajectories*, EMNLP 2026.
  <https://aclanthology.org/2026.emnlp-main.1808/>. Its score-threshold union event
  must not be relabeled as actual task error; drift and sampling assumptions
  remain part of a trajectory guarantee.
- Morante and Romero García-Rubio, *Correlation limits the reliability of
  ensemble decision making with large language models*, 2026-11-04.
  <https://link.springer.com/article/10.1007/s44564-026-00040-z>. Its benchmark
  correlations cannot be transferred numerically to Hepta without measurement.
- Wang, Poskitt and Sun, *AgentSpec: Customizable Runtime Enforcement for Safe
  and Reliable LLM Agents*, ICSE 2026; arXiv v3 2025-07-31.
  <https://arxiv.org/html/2503.18666v3>. Actual triggers, predicate implementation
  and host enforcement determine what its rules cover.
