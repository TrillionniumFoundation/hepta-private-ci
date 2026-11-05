# Weight-space research update: sources and operational implications

This is a literature and method-scope update for the follow-up to research PR
#4790. It contains no newly measured model-quality result. Source checking began
on 2026-11-04 in America/New_York; the follow-up directory uses its UTC date,
2026-11-05.

## 1. MIT Weight-Space Programming

Primary report:
https://rikiyat.github.io/blog/weight-space-programming/

Released experiment repository:
https://github.com/RikiyaT/lm_understand-logs/tree/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f

The November 2 report separates weight reading, policy construction, and
language-model editing. Tool and feedback budgets differ. Its Qwen result
targets looping; the non-looping Gemma control has no established gain. These
remain author results, not a general capability theorem.

Our observed repository head is unchanged. Earlier MinAtar replay and Qwen
export/load records remain historical. The new short-cache execution qualifies
its stated numerical path only. Complete generated-answer scores, independent
blind discovery, and transfer to Hepta remain unqualified.

Our design implication is to require an executed task-value gate after any
mechanism hypothesis, sparse edit, or local preservation check.

## 2. Steer2Edit: a component edit

Primary v2 paper (March 3, 2026):
https://arxiv.org/abs/2602.09870v2

Full text and author code:
https://arxiv.org/html/2602.09870v2
https://github.com/Trustworthy-ML-Lab/Steer2Edit

The construction is `Delta W_i = lambda_i u_i k_i^T`, with `u_i` parallel to
an output direction `v_i`, and `k_i` parallel to `W_i^T v_i`. Its component
score is `g_i = cos(v_i, W_i mu_i)`, using mean input activation `mu_i`.
For positive `rho` and `0 <= alpha < 1`, the elastic-net alignment objective
has the separable solution

    lambda_i = sign(g_i) max(|g_i|-rho alpha, 0) / [rho (1-alpha)].

This requires defined, nondegenerate directions and statistics. The procedure
uses activations and validation search: avoiding backward passes does not
remove data or selection costs. Its regularizer is not a hard constraint on
actual rounded checkpoint differences, and component-level orthogonal-output
preservation does not guarantee preservation after downstream nonlinear
processing or policy feedback.

We did not execute Steer2Edit on Hepta. Our own acceptance design therefore
separates a proposed numerical edit, authenticated rounded-parameter feasibility,
and executed complete-task value.

## 3. CrispEdit: preservation as a constraint

Primary proceedings:
https://proceedings.mlr.press/v306/ikram26a.html

CrispEdit treats capability preservation as an explicit constraint and uses a
second-order approximation and structured curvature machinery. It is relevant
to designing preservation conditions, but must not be described as a
gradient-free closed-form replacement for the entire training process.

For Hepta, local output bounds, unchanged terminal rows, and norm budgets are
useful executable constraints. They do not by themselves certify full NDU
preservation: an edit may change subsequent observations, costs, stopping, and
the state visitation distribution. Complete policy evaluation remains necessary.

## 4. New Hepta evidence since PR #4790

Primary follow-up:
https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4798

Pinned report:
https://github.com/TrillionniumFoundation/hepta-private-ci/blob/77b24407b9898aa44769502fbb22c24fb7193a58/tools/hcsn/digital_feedback_20261101/REPORT_ZH.md

This report completes the already frozen 32-fit confirmation records. All four
primary familywise-adjusted benefit intervals cross zero, and none of the 256
candidate-by-fit-by-domain entries satisfies all eight quality conditions. The
report explicitly retains acceptance=false. These failures do not demonstrate
equivalence, exact zero effect, or impossibility of future improvement.

The record reconstruction checks arithmetic relationships in retained archives;
it is not a new execution of every model forward, latent random process,
teacher oracle, or optimization run. Its known historical CPU total is a lower
bound because some earlier controller costs were not archived.

The next experiment must therefore avoid repeating a successful-training-loss
narrative. It should identify whether the bottleneck is the model law, the value
target, representation capacity, finite precision, or policy compilation.
Old confirmation outcomes must not be reused as an unseen selection set.

## 5. What global means in the proposed subsystem

There are three distinct optimization scopes:

1. A convex parameter subproblem with fixed data and a hard parameter budget.
   A bounded direct solver can reach a declared numerical KKT tolerance without
   gradient iterations. Actual rounded parameters need a separate feasibility
   check. Numerical KKT checks are not exact-real global certificates.
2. A finite-horizon decision problem under a specified transition and observation
   law. Bellman recursion can solve that model's decision problem when its
   complete successor branches, costs, legal actions, time, and tie rules are
   included. It need not be optimal under the real environment's different law.
3. The complete neural policy and actual task distribution. Compilation into a
   restricted head can lose the Bellman policy, and editing a policy changes the
   distribution of future visited states. Finite training-row agreement cannot
   certify global task optimality.

The current source already contains a supplied-law dynamic-programming engine.
A new follow-up must credit that existing implementation. The proposed research
increment is to use the checkpoint's own identified law for future-value targets
and compare its structured execution with compilation into the same head.

A broader continuous weight-space global planner remains unqualified. An
occupancy-measure optimum is only a policy-space bound unless weight
realizability and the executed argmax semantics are also enforced.

## 6. Runtime admission work is a separate source boundary

The follow-up also read the current description of
https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4812
at observed head `5bf9e9eb7dc49ef56caf5143531f3a705fcd0e52`.
It concerns explicit post-quantum authorization for ordinary model loading and
fresh external-frontier checks at FinalUse effect entry. Its description retains
HOLD / production activation false and identifies an outstanding distributed
admission boundary. This follow-up did not execute or qualify that branch's
tests and does not import its code.

That work does not supply a new model-quality result. It does establish a
relevant integration boundary: a scientifically qualified plan or isolated
weight artifact is not itself an installation or effect authorization. The
native WSP receipts continue to identify their research scope explicitly.

The earlier source refresh inspected the 100 most recently updated open research
repository PRs, through entries last updated on November 3, and found no newer
matching weight/joint/feedback research report than the already pinned #4798.
This is a bounded title-based discovery statement, not an exhaustive audit of
all branches, closed PRs, or unpublished research.

## 7. Later continuation-only and entropic-control source

After the frozen scientific experiment and root reexecution were complete, a
second bounded source check at **2026-11-05 02:04:45 UTC** found
[PR #4819](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4819),
at `943aa1c69dbfd696763f45ef24c5d3d491f56e19`. Discovery metadata and the three
inspected primary file identities are in [SOURCE_REFRESH_FINAL.json](../SOURCE_REFRESH_FINAL.json).
This is a different multimodal V6 family, not a later fit of the renewal task.
We read its design, continuation-head implementation and fixture result; we did
not import its code or rerun its tests.

Its continuation-only labels compare STOP with one action followed by a fixed
suffix. For positive risk aversion they use an exponential-moment difference,
`E[exp(-gamma R_STOP) - exp(-gamma R_action,suffix)]`. This is neither an
unrestricted optimal Q function nor a certificate for repeatedly replanning
under an arbitrary suffix. Its gamma-zero branch uses a mean-return difference.
The retained fixture explicitly uses two synthetic random-pixel cases and an
untrained observer; its two-row native head agreement and fresh-process restore
are engineering evidence. Its recorded decision is **no-update**, with scientific
confirmation and production activation false. These records add no scientific
sample or quality qualification to our frozen study.

The design makes a useful mathematical boundary explicit. An entropic controller
with known current cost propagates exponential moments with an `exp(gamma c)`
factor. If cost and continuation are jointly random, their joint expectation
must remain inside that recursion. Subtracting an expected fee from a
risk-neutral Bellman value cannot implement that objective in general.

Our current Rust `weight_bellman_plan` implements only a **risk-neutral additive
finite DAG**. Its source and protocol are unchanged by this later source read.
The 320-world compatibility result does not qualify entropic risk control,
log-sum-exp recursion, correlated stochastic cost, endogenous preferences or
general NDU/FBSDE. Extending the objective requires a separately typed contract,
law/state sufficiency evidence and a newly frozen efficacy test.

## 8. Latest independent-team replication source

The November 5 source refresh also located
[alan-turing-institute/weights_editing](https://github.com/alan-turing-institute/weights_editing/tree/9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca),
pinned at `9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca`.
Its saved results cover small-network identification and from-zero MinAtar
network programming, with some input/action perturbation controls. Its
[SPEC](https://github.com/alan-turing-institute/weights_editing/blob/9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca/SPEC.md)
explicitly excludes the Qwen editing experiment. Retained descriptions of that
experiment are setup notes, not completed execution.

We inspected source documents and saved run records, not new model executions.
The fifteen reviewed Astra Exp5 records represent three generated networks per
condition and 1,000 evaluation episodes per network; episodes do not become
independent weight-discovery trials. No independently retrained PPO comparison
or Qwen capability confirmation transfers to Hepta from this source.
The bounded review and primary identities are retained in
[TURING_REPLICATION_REVIEW.json](TURING_REPLICATION_REVIEW.json) and
[ROOT_TURING_PRIMARY_READ.json](ROOT_TURING_PRIMARY_READ.json).

## Source and claim policy

Only the primary sources above support technical literature claims in this
note. Author-reported performance is not a follow-up measurement. The prior
frozen experiments, the new protocol, and any newly executed result must retain
separate identities. Failed, cancelled, and resource-rejected attempts belong
in the cost and qualification record.

