# NDU RL validation: semantics, structural probes and real-tool attribution

This research extends the exact online reference and factorial accounting in
#4830/#4831. It supplies executable tests and experiments for the four-stage
validation request. Finite-model correctness, learned-critic behavior, real tool
execution, novel-method benefit and production qualification remain distinct.
Original V3 results and failed semantic/model experiments are unchanged.

## What each stage establishes

| Stage | Executed implementation | Claim boundary |
| --- | --- | --- |
| Semantic kernel | Random duration, admission costs, STOP, Bellman/tree enumeration, exact actor gradients and risk-zero limits | A bounded known public-state model; no approximate-critic or neural-policy efficacy |
| Structural intervention | Actual linear/quadratic/neural critic fitting on shared noisy value observations; eleven panels | One-decision supervised probe; effective capacity and actual CPU are reported, not matched |
| Real tools | Frozen repair rules plus actual Python CHECK/REPAIR/ORACLE subprocesses | Real local tools on known affine-code templates; no frozen LLM or multimodal generator |
| Training × inference | Flat entropic score versus recursive derivative; fixed versus learned dynamic execution | Deliberate equivalence/null control; the fixed column does not consume trained parameters |

Read SEMANTICS.md, STRUCTURE.md and TOOLS.md for the exact objectives, information
sets, lawful actions, differentiation rules and experimental limits. The
registered settings live in PROTOCOL.json; SOURCE_MANIFEST.json binds every new
executable, test and relevant inherited dependency by Git blob and SHA-256.

## Two different discounted risk objectives

For an admission cost c, duration tau and continuation V, the registered
fixed-risk recursion applies the entropic certainty equivalent to
`-c + exp(-rate*tau) * V`. Both the policy draw and the environment draw are inside
the risk aggregation. STOP is terminal and has no bootstrap term.

This differs from taking one fixed-eta certainty equivalent of the complete
discounted trajectory return. That static objective needs continuation risk
`eta_next = eta * exp(-rate*tau)`. The code checks each definition against its
own independent reference and retains their discrepancy when discounting is
nontrivial. Ordinary expected-return GAE is an objective-mismatch control for
the entropic task, not a fair competing learner under the same objective.

## Reproduce the registered run

Use the exact published source commit named in the evidence receipt. A complete
repository checkout is supported; the authoring environment used a GitHub-blob-
verified source subset. Python 3.12 and NumPy are sufficient for the new studies.
The inherited whole-process meter requires Linux `wait4`. It records the child
interpreter, imports, all waited descendants, serialization and process exit.
BLAS/OpenMP thread limits are fixed to one for the registered child processes.

```bash
python -m unittest discover -s experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/rl_audit -t . -p 'test_*.py' -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.run --source-commit EXACT_PUBLISHED_SHA --output /tmp/ndu-rl-new-run
```

The output must be a new directory. The parent uses an isolated Python process
and the verified repository path, so a different working directory or PYTHONPATH
cannot substitute a same-named package. Both parent and child check source
identities. Exit zero alone cannot qualify a run: missing results, retained
failure, altered shards, omitted cases or duplicate records are rejected.

`REGISTRATION.json`, `COMPLETION.json`, each process receipt and the original
process log remain together. Per-case and per-episode shards preserve the whole
roster while keeping individual repository objects bounded. The separate GitHub
publication/readback receipt binds the command's source SHA to its actual tree;
the local subset's git HEAD is never substituted for that source identity.

## What costs mean

Task fees are registered research utility units. CPU seconds, wall seconds and
RSS are physical observations and have separate scopes. Imports, model fitting,
calibration, exact reference construction, verification and failed work cannot
be inferred from a selected action's short timer. Whole-process envelopes and
their enclosed subtotals must never be added together.

The inherited meter also reports its historical illustrative tariff; it is not
measured money or a deployment price. Unsupported resource observations stay
null. Abnormal parent exits can miss unreaped descendant CPU and remain lower
bounds, as the original meter states. Provisioning, acquisition, external
qualification and publication costs are not silently treated as free.

A deployment break-even count requires the same observed quality, a positive
per-service saving in the same unit, and complete incremental one-time costs.
These studies do not satisfy all of those conditions. A descriptive CPU-only
quotient, if present, is explicitly limited to the measured components; the
qualified complete-cost break-even field remains null.

## Novelty and remaining decisive experiments

The repository already contains an entropic score learner and conditional
log-moment critic. Its normalized population CE direction and unnormalized
moment direction are proportional; a different algebraic implementation of the
same exact update does not demonstrate a new learning algorithm.

The next efficacy experiment must consume a genuinely distinct, mathematically
specified update under equal information, lawful actions and external objective.
It must compare the existing Hepta learner, an appropriate ordinary actor–critic,
and a faithfully pinned rsEAC baseline with matched capacity and compute. Both
inference columns must consume the learned component if the training contrast is
to be identified. A separate implementation and an independent evaluation task
are needed before claiming gains from an approximate internal sensitivity.

Still open: sampled multi-step RL, general nonlinear recursive utility, learned
state sufficiency, full-rank/noise-subspace identification in an actual BSDE,
matched-resource comparisons, real frozen-model tool/multimodal control,
independent semantic evaluation, new tasks and future time windows, production
tail/resource behavior, and full-cost net benefit. A negative result is retained
as a research result; these gates do not close because a harness executes.

## Primary sources and existing implementation

- Existing NDU contract: `docs/learning/NDU_FBSDE_SPEC.md` at main
  `732e934ba496d90fbe042b8d41d479ef901643e5`, blob
  `d7ecc62df03eb1cf9456787b5cc7d916c414b258`.
- Existing Hepta `joint_hepta_20261029/learning.py` and `oracle.py` at the frozen
  #4831 base `29243f8fd1e17ff9c74d606163a862bd7ecae48d`.
- [Granados and Pacheco, Risk-Sensitive Exponential Actor Critic (2026)](https://arxiv.org/abs/2602.07202).
- [Official rsEAC implementation](https://github.com/AlonsoGranados/rsEAC).
- [Schulman et al., Generalized Advantage Estimation](https://arxiv.org/abs/1506.02438).

rsEAC already treats entropic policy gradients and stable exponential-critic
updates. This package has not executed its official continuous-control training;
neither a fresh name nor a local formula resemblance is counted as a reproduction.
