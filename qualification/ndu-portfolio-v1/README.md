# NDU multimodal portfolio validation

This package implements the four-stage validation order as a reproducible research
reference. The exact finite control environment runs on CPU; the text/image and
audio/video contracts expose missing real evidence rather than declaring success
from internal utility or a fixture. It does not select production Hepta artifacts.

Baseline source is `732e934ba496d90fbe042b8d41d479ef901643e5`. The implementation
instantiates the general joint action/parameter recursion in
`docs/learning/NDU_FBSDE_SPEC.md`, sections 3 and 5. It preserves the distinctions
in `docs/learning/NEURAL_BIOMIMICRY_SPEC.md`: a parameter candidate, numerical
conformance, native integration and independently observed efficacy are separate.

## Run

Use Python 3.11 or newer in an isolated environment:

```bash
python3 -m venv .venv-ndu
.venv-ndu/bin/python -m pip install -r scripts/ndu_portfolio/requirements.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts .venv-ndu/bin/python -m ndu_portfolio.run \
  --output qualification/ndu-portfolio-v1/results
```

The runner executes focused regressions first, then the full seed set `11,29,47`,
120 tabular updates and 80 shared-router updates. `--quick` uses one seed and fewer
steps for CI and labels its output as a smoke run. No model weights are downloaded
or external generation APIs called by either mode.

Outputs are `results.json`, `RESULTS.md`, `tests.log`, and a clearly labelled
transport fixture. The source digest includes Python code/tests, dependency pins,
the experimental protocol and the CI workflow. The runner checks it before and
after execution and rejects a source change. Failed attempts overwrite the run
status and preserve test diagnostics; an earlier result cannot remain the current
successful-looking output.

Run focused tests separately when changing a component:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python -m unittest discover \
  -s scripts/ndu_portfolio -t scripts -p 'test_*.py' -v
```

The required `blocking-ci` aggregate includes `NDU portfolio reference (synthetic
only)`, running the quick protocol on GitHub's prospective merge commit. A green
reference job says nothing about a real multimodal efficacy gate.

## 1. Exact finite control

`nested-entropic-portfolio-v1` declares, for a non-stop action,

```text
X(a,s') = -cost_weight * actual_cost(a)
          + discount ** actual_duration(a) * U(s')
R_eta(X) = -log E[exp(-eta * X)] / eta       when eta > 0
R_0(X)   = E[X]
U_pi(s)  = R_eta over the joint policy-action and successor lottery
U_star(s)= max over legal deterministic actions of R_eta(X)
```

Stop returns the fixed terminal function. Action randomization is inside the
risk lottery, so the gradient includes the action-probability derivative as well
as the risk-weighted continuation derivative. The reverse pass traverses the
reachable state DAG; finite differences check the complete policy objective.
This is a finite discrete profile, not the general continuous-time FBSDE solver.

State records quality of two or three branches, exogenous preference, remaining
budget, elapsed time and verification status. Time and resource units are exact
integers. The exogenous two-state preference transition is composed over the
actual action duration. A generation action always delivers at least a low-quality
toy output; real provider failures are handled by the separate artifact harness.
Actions reserve enough budget and time for every still-missing mandatory branch.

Exact Bellman DP is checked against independent full enumeration of contingent
policy trees on a small problem. A separate integer implementation reproduces the
published `NDU-GV-001` Q32 vector. The latter is a golden-vector check, not evidence
that the native Rust backend was compiled or integrated.

`external_metrics` fixes joint success independently of preference/risk/internal
utility: all required toy outputs must have high quality and a verification step
must survive the final generation action. These are explicitly toy labels, not
human or real-model judgments.

### Compared controllers

| Controller | What it actually does |
|---|---|
| Fixed single pass | One delivery per branch, then verification; cheaper reference |
| Fixed cyclic allocation | Fixed cyclic branch priority spends spare feasible quota and reserves final verification |
| One-step greedy | Optimizes immediate terminal-score improvement after mandatory completion |
| Ordinary learned router | Shared 130-parameter masked router with ordinary expected-utility gradients |
| NDU learned router | Same capacity/initialization/update count with the declared entropic recursion |
| No explicit cross-modal features | Removes minimum/product features, while keeping the original joint reward and verification incentive |
| No dynamic preference | Trains with a static preference process and masks preference changes at evaluation |
| No risk | Identical to the ordinary learned router in this profile |
| Two-step planning | Receding lookahead with exact evaluation of the learned policy as its leaf continuation |
| Exact DP | Optimization oracle, not a deployable performance baseline |

The shared router is fitted on two task configurations. Three other budget/cost/
success-probability configurations are held out from all gradient fitting. The
artifact retains every seed, result and gap. The feature ablation is narrower than
a completely factorized multimodal model and does not establish general necessity
of joint modeling.

Generation budget caps are matched; actual generation expenditure varies. Host
wall-clock controller time is a diagnostic and is not calibrated into toy compute
units. Planning counters cover the exhaustive evaluator's queried states and
exclude work inside leaf recursion. No matched-total-compute or net planning
efficiency advantage is asserted.

An early implementation removed the joint reward in the ablation and used only a
single-pass fixed baseline. Independent review identified those confounds before
the retained protocol run. The retained implementation preserves the reward and
includes the stronger cyclic comparator. The toy procedure is predeclared
engineering validation, not a formally registered clinical/statistical trial.

## 2. Real text/image transport and independent evaluation

`generation.py` provides a frozen model manifest, bounded subprocess JSONL
transport, action budgets, artifact hashes and a complete attempt ledger. The
actions are `reason`, `visual_repair`, `cross_modal_check`, and `stop`.

An explicitly configured command receives a request containing the model-manifest
digest, task/sample/seed, dataset and objective digests, action/sequence, previous
artifacts, output directory, resource reservation and request digest. It must
resolve task content through the pinned dataset and return the same request and
manifest digests, terminal status, actual compute and relative text/image artifact
paths with SHA-256 digests. Commands are never extracted from prompts or outputs.

Use `ModelBinding`, `ActionLimit`, `ProviderManifest`, `SubprocessProvider` and
`Session` to supply the actual backend. `Session.step` accepts measured controller
compute/time, including planning, with `controller_usage_source="measured"`.
Omitted usage is unknown, and default supplied-but-unverified usage is declared.
Both prevent a qualifying real-resource claim.

`evaluation.evaluate` accepts a separately pinned `EvaluatorManifest` and a
callable or `JsonlCommand`. The evaluator receives the task and verified artifacts
without controller label, internal NDU score or critic prediction. Its response
contains observed task success, text/image quality, contradiction count and
missing modalities. Evaluation is single-use and seals the session, including on
failure. Scoring costs persist in the same ledger.

The declared total budget includes generation, reasoning, repair, cross-modal
verification, controller/planning, failures and **independent evaluation**. Actual
overruns are retained rather than clipped to reservations. Late/failed artifacts
cannot replace the active output. Missing modalities prevent joint success.

`panel_report` requires registered paired task/sample/seed/split cases, complete
baseline coverage, identical model/dataset/objective/evaluator/budget bindings,
and disjoint training/evaluation groups. Missing outcomes remain in the expected
denominator: the report returns success bounds and observed-only quality, rather
than a favorable survivor average. Calibration and resource coverage are explicit.
Use `minimum_independent_test_groups=100` for the pilot prerequisite. Repeated
seeds within a task require a grouped statistical estimator, not an independence
assumption. `assessment.assess_panel` implements `paired-group-bootstrap-v1`:
paired seed differences are averaged within immutable task groups, then whole
groups are resampled. It preserves missing-case coverage and identity gates,
requires 100 independent test groups, and reports 95% intervals plus a
Bonferroni-adjusted success interval across the comparison family. A nonpositive
adjusted lower bound is `NO_DEMONSTRATED_GAIN`. Missing provenance, real retention,
calibration, diversity or defined tail evidence keeps the overall status HOLD.

### Provenance limitation

The subprocess boundary verifies artifact bytes and declared identities. It cannot
authenticate the model that actually produced the bytes or establish institutional
observer independence. Therefore real-label-only runs remain `DECLARED_UNVERIFIED`
and `HOLD` until a native owner-path provenance verifier is integrated. Renaming
the synthetic fixture or supplying arbitrary model/evaluator names cannot produce
qualifying evidence. A complete descriptive panel is not an efficacy PASS.

Current main contains native request/provider machinery, but this experiment has
no configured frozen text/image model pair, independently pinned evaluation
dataset/scorer, or verified provider execution binding. A real phase-2 run has not
been executed. `fixture_smoke` only tests the artifact transport and always stays
HOLD.

## 3. Adapter training reference

`adapters.py` trains 50 real NumPy parameters through a frozen base, Cell low-rank
adapter, generator low-rank adapter and allocation/control head. It declares its
own finite-scenario profile, `portfolio-adapter-synthetic-entropic-v1`, with
duration discount, cost, cross-modality errors and entropic risk. It does not
silently substitute this profile for the native Q32 evaluator.

Every trainable scalar is checked by finite differences. Selected tensors are
backed by immutable bytes. Gradient ascent returns a separate candidate, with
backtracking and a trust bound on effective matrices, preserving invariance to
low-rank factor reparameterizations in the bound itself.

The experiment separates synthetic training, heldout and old-base probe rows.
It reports Brier scores, fixed-bin ECE, old-base prediction drift and prediction
spread. The latter two are proxies, not real old-task retention or semantic
diversity. The default candidate improves new-task scores but fails the fixed
0.02 old-base drift limit and is rejected. No current bundle is selected or
mutated, and real phase 3 remains HOLD.

## 4. Streaming invariants

`StreamingLedger` separates exact microsecond compute time from media presentation
time. Atomic `reserve_compute` prevents concurrent tasks from spending the same
remaining budget. `complete_compute` records actual costs, including failures and
overruns; identical retries cannot authorize a second execution. Imported
observations through `charge_compute` are accounting only, not dispatch authority.

Physical work IDs deduplicate shared encoder/compute use. Pending chunks may be
revised; delivered prefixes cannot be rewritten or moved backwards. Delivery must
extend a contiguous prefix and cannot proceed after resource/deadline failure.
Default limits are 4096 physical jobs and 4096 chunks per modality; checkpoint
rollover beyond those bounds needs a separate design.

The fixture aligns 20 ms audio chunks and 40 ms video chunks at an 80 ms frontier.
This proves timestamp coverage and accounting behavior only. It generates no
audio/video content, and does not evaluate lip sync or long-horizon media quality.

## Review and promotion order

The smallest coherent landing unit is the exact control/gradient reference and
its tests. Review subsequent commits as common-observer comparisons; artifact
transport/evaluation; adapter differentiation and streaming; then runner, evidence
and CI wiring. The independent Python package does not alter the production Rust
runtime, selected Cell bundles, control-plane success criteria or deployment.

`preregistration.json` records the future real-efficacy gate and guardrails. Its
initial pilot limits are fixed before any real-generation run, but are engineering
choices rather than a power calculation or established scientific effect size.
Real promotion requires verified execution, paired independent quality gains,
matched total costs, calibration, diversity, retention and tail checks. If the
ordinary router achieves the same outcome, report no demonstrated NDU necessity.
