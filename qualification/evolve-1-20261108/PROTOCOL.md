# EVOLVE-1: evaluation and adoption Cell

## Scope and source identity

This work adds a component-transfer accounting layer and an executable, bounded
replay-policy pilot to `research/cell-causal-abcde-20261108-cf0` at
`1e9c2890fef92ea63dab472e1bdb0c444c9656b5` (tree
`20f0836afc9c790fee23ddd150817a6d11550598`). It reuses that revision's
`causal_improver.compare_improvers`. These scripts are research code, not a
default-production learning or adoption entry point.

The separately inspected native owner contracts are from
`6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5`. They are not silently assumed to be
integrated with this Python experiment branch. The default branch observed in
this audit was `732e934ba496d90fbe042b8d41d479ef901643e5`.

## Research questions

**E7a** asks whether an update rule improves the joint adaptation, retention and
cost outcome. A better replay ratio is an update-rule result, not evidence that
the process discovering future rules has improved.

**E7b** asks whether a descendant improver produces the next useful improvement
more effectively from the same solver starting state and under the same complete
budget. The measured improver remains frozen during each ignition run. Search
state may evolve according to its fixed algorithm, but it cannot cross run
boundaries or silently modify the measured improver.

| Cell | Solver start | Improver | Meaning |
| --- | --- | --- | --- |
| S0-I0 | Initial | Initial | Reference |
| S0-I1 | Same initial | Descendant | Improver contribution at S0 |
| S1-I0 | Descendant | Initial | Solver-start contribution |
| S1-I1 | Same descendant | Descendant | Combined effect and interaction |

The primary E7b contrast is I1 minus I0 within S0. The same contrast at S1 and
the difference between the two row contrasts are reported separately. Comparing
only S1-I1 with S0-I0 changes both factors and cannot identify improver progress.

## What is executable here

`evolve1.py` validates four-arm blocks, source-group and data-digest separation,
retention binding, immutable improver identities, complete registration and
history-cost separation. It reuses the existing registry, budget, unknown-result,
retry and selection-before-holdout checks.

`evolve1_reference.py` is a NumPy logistic reference learner, atomic checkpoint
writer and local timer. `evolve1_pilot.py` runs independent improver-discovery
seeds, then transfers each frozen proposal distribution across two solver starts.
It searches replay ratios {0, .25, .5, .75} and learning rates {.03, .12}; each
candidate has 64 updates of batch size 32. Candidate selection uses acceptance
data. The selected candidate is then measured once on separate utility and
retention samples. Selection is retained before that measurement.

The pilot uses generated Gaussian inputs, with generated uniform inputs for
final evaluation. It is **synthetic**, uses a **reference learner rather than
HeptaCore**, and has a local byte-binding verifier rather than an independent
native evaluator. S1 comes from a declared fixed preparation update; it is not
claimed to be a naturally evolved solver. These choices test the execution and
measurement plumbing. They do not establish real-task or general RSI benefits.

Named random streams bind `(lineage seed, purpose)`. Source declarations include
improver-discovery data as well as candidate training/selection/final data.
Different display names cannot make the same data digest independent.

## Commands

From the repository root, with Python >=3.10 and NumPy installed:

```bash
python -m unittest scripts.ndu_real_runtime.test_evolve1 \
  scripts.ndu_real_runtime.test_evolve1_pilot -v
python -m scripts.ndu_real_runtime.evolve1_pilot \
  --output /absolute/path/to/new-evolve1-run
```

The output directory must be new. The runner refuses to overwrite a prior
campaign. Preregistration includes all expected run IDs, parameters, source-file
hashes and Python/NumPy versions. Journal snapshots contain the available plan,
registry, attempts, evaluation originals and initial solver/improver artifacts.
An interrupted run remains incomplete; the pilot does not advertise production
restart/adoption semantics or automatically resubmit unresolved work.

## Qualification and accounting

The pilot freezes minimum useful gain `delta=0.05` and maximum retention loss
`epsilon=0.15` before dispatch. These are engineering pilot thresholds, not
validated production effect sizes.

`effect_criterion_met` requires a successful, non-rolled-back selected candidate,
its bound final evaluation, gain >= delta and retention loss <= epsilon.
`qualified` additionally requires resolved attempts and complete reported cost.
Neither flag grants scientific or adoption authority. NoUpdate is never counted
as improvement, including when an evaluator reports a noisy positive score.

The four cells each retain all registered run denominators. Missing outcomes
produce bounds, not dropped observations. The bounds are **missing-evidence
bounds, not confidence intervals**. Episode counts are not independent improver
formation counts. Child digest uniqueness is a necessary structural check, not
proof of independent formation.

Online costs include all admitted attempts, not only the selected candidate.
History costs for discovering an improver and preparing S1 are separate and not
silently amortized. The effective-improvement cost is all online cost divided by
the effective-improvement count; zero successes or unresolved counts yield null.
The current inherited ledger records 12 stages and wall time, CPU time, energy
and provider charges. GPU/token extensions require a new reviewed meter profile
before any experiment using those resources.

The CPU pilot measures wall and CPU time. Energy and provider charges remain
unknown. Per-run envelope residuals retain measured hashing/scoring/bookkeeping
work not assigned to a narrower stage. Driver totals include additional setup
and accounting. Imports and final output publication need external metering.
Candidate dispatch is cooperatively stopped near the time limit; this is not an
OS-enforced hard quota. Any observed over-budget campaign is retained and rejected
by the comparison contract. Complete economic superiority therefore stays HOLD.

## Native handoff still required

The native coordinator's stages are Experience, Dataset, Training, Evaluation,
Proposal, Selection and NextUse. NoUpdate also needs Selection and
RetainedModelNextUse. Rejection alone does not complete the learning iteration.

The actual integration must use `LearningIterationOwnerPortsV1` to authenticate
owner-produced records. A candidate cannot mint evaluator, selector or next-use
authority by changing IDs or signing its own declarations. Bundle lineage binds
the source model, update rule, data, evaluator and state schema. An adapter change
requires an admitted Reset/Migrate decision, not an automatic Preserve.

Selection and next-use are read-only observations of the existing owners. Exact
generation/epoch and predecessor checks, anchored checkpoints, cancellation and
uncertain-effect reconciliation must remain in that owner domain. This research
runner neither writes production selection nor manufactures successor receipts.

Before a confirmatory EVOLVE-1 run, freeze real source/episode-group registries,
independent evaluator access, a native full-bundle consumer and a complete meter
profile. Add matched tuned-fixed/random-search baselines and independently formed
improvers. Set effect size, retention margins, sample size, multiplicity and stop
rules using development-only pilot evidence, then use fresh confirmation data.
Evaluator candidates require a separate frozen reference. Repeatedly querying a
retention panel makes it development feedback; preserve a final unseen panel.

## Primary research sources checked on 2026-11-08

- [SpikES / Confavreux et al., PLOS Computational Biology (2025-04-24)](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1012910): local plasticity-rule search also exhibits complex-objective and degenerate-solution limitations. It motivates a small initial search space plus independent retention checks.
- [DiscoRL, Nature (2025)](https://www.nature.com/articles/s41586-025-09761-x): distinguish discovering a learning rule from training agents with the frozen rule. Discovery cost and downstream efficiency are separate accounts.
- [Hyperagents v2, Appendix D.5 and F](https://arxiv.org/pdf/2603.19461v2): task/meta 2x2 transfer freezes the measured meta agent. Its five-run, 50-step transfer evidence uses iteration budgets; the authors explicitly identify matched token/compute/cost evaluation as further work. arXiv v2 is dated November 1; the manuscript title page says November 3.
- [AIDE2 v1, section 3.6](https://arxiv.org/html/2609.26457v1): both ignition arms start at AIDE47; each has three seeds and 50 steps. Means 0.780 and 0.782 do not establish that the descendant is a stronger or more sample-efficient improver. The plotted min-max bands are not confidence intervals.
