# Hepta NDU P2: source-paired terminal-loss covariance (research-only)

This is a follow-up to the **completed, negative** [grounded-generation pilot PR #3213](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3213). It does not change the frozen 768 final predictions, source roster, evaluation protocol or reported results.

## Problem this isolates

The v1 controller's 4×4 matrix describes **token-logit Cell residual disagreement**, not the covariance of mistakes in the final output. During development, the preselected risk-weight grid tied and chose lambda=0, leaving the explicit penalty inactive. No terminal-risk benefit was demonstrated. Pretending v1 logit covariance is terminal error dependence, or using v1's incomplete exploration trajectories to invent arm-level counterfactual outcomes, is prohibited.

Here, each asset is a **frozen, immutable individual Cell proposal** evaluated through a completed generation against the same source and random seed as no-change and the other four Cell arms. We estimate the paired terminal-loss improvement of each arm relative to no-change:

g_i(s) = L_nochange(s) - L_i(s)

For each original-image source, repeated seeds are averaged; the 4×4 covariance is then estimated **across independent source groups** with prespecified diagonal shrinkage. This reduces, but does not eliminate, sampling uncertainty and dependence. It is not a covariance matrix for nonlinear combinations of Cell actions.

## Source-bound input contract

A caller constructs one strict JSON file per role. Top-level keys are schema = hepta.ndu-terminal-risk-cohort.v1; split = train/dev/test; cohort_digest/model_digest/objective_digest (pinned nonzero 64-hex identities); budget_seconds (positive finite); and rows.

Every row must contain exactly:
- source_id and image_digest (one immutable source identity and original-image digest)
- seed (nonnegative integer)
- arm (nochange, semantic, horizontal, vertical, completion)
- proposal_digest (constant within each arm, distinct across all arms)
- loss in [0,1], covered boolean, measured positive wall_seconds, overrun boolean.

The source, seed and arm roster must form a complete five-arm matrix. Each source has at least two seeds. A default fit requires at least 32 independent source groups. All invalid, abstained or over-budget results must have terminal loss 1; overrun must agree with actual duration. Duplicated source/seed/arm rows, disguised duplicate immutable proposals, malformed or hidden fields, all-zero hashes, cross-source image duplication and incomplete rosters fail closed. The loader also rejects repeated JSON member names and NaN/Infinity constants.

**Hashes are deterministic integrity identifiers, not external attestations or signatures.** A source custodian still has to independently attest original images, full run receipts, evaluation labels, model checkpoints, licenses and exclusions from previous training/test data.

## Fit, evaluate and control

1. Use fit(train_batch) **only on train**. It computes paired source-macro mean gains, shrunk PSD covariance, mean arm cost and coverage. The output retains training image identities and immutable proposal digests for split-overlap checks.
2. Use evaluate_frozen(fit_receipt, dev_batch) on a disjoint DEV source set. No refitting occurs; model/objective/budget/proposal mismatches, training source reuse or a modified fit receipt are refused. The same function can evaluate previously frozen TEST results, **but TEST cannot be passed to fit**.
3. surrogate_portfolio enumerates nonnegative four-arm weights on a bounded simplex, includes no-change residual, a nonnegative risk coefficient and a **fixed switching cost charged once per admitted Cell**, not per fractional weight. This is a **linear surrogate**, not observed mixture output. Do not call the result a verified efficient frontier or a Merton/FBSDE solution.

The previous pilot's data **cannot qualify this estimator**: it did not execute complete nochange+four-individual-Cell outcomes across identical train/dev source-and-seed rosters. In particular, the actor must not receive a reference-derived correction, and unexecuted hypothetical arms cannot substitute for observed terminal loss. A new pre-registered cohort with real generation, complete cost/coverage receipts, and untouched blind holdout is required.

## Local checks

On Python with NumPy installed:

    python -m unittest discover -s qa/ndu-terminal-portfolio -p 'test_*.py' -v

Nine tests use **synthetic values only**. They prove schema, custody, covariance math and fail-closed behavior; they do **not** constitute quality-risk improvement evidence. Source-level readiness is distinct from scientific or production readiness.

Status: **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. No production authority, Cell Split, model promotion, tool effects, independent trust/signature claim or global efficient frontier claim.
