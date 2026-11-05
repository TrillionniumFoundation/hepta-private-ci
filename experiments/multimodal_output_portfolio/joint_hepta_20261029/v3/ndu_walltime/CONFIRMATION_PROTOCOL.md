# Frozen-LLM confirmation design — DRAFT, NOT PREREGISTERED

Date: 2026-11-05. This specifies decisions that can be made before execution. No real LLM
confirmation run, model selection, task-bank freeze or price freeze
is claimed. Replace every UNFROZEN field below and publish the complete protocol
hash before opening confirmation outcomes. Existing fixture receipts qualify
execution behavior only; they are not observations for this study.

## 1. Fixed external score and complete accounting

For each task, freeze an independently checkable quality rule Q in [0,1], its
method-blind verifier/version, answer format, legal actions, delivery deadline and resource
caps. Quality cannot depend on the method's internal preferences or its own
confidence. Missing, cancelled, expired, invalid or unverified delivery earns
Q=0. STOP alone does not earn quality; verification must finish by the deadline.

The primary service utility is U=Q-C_attempt-lambda*T_envelope. Use monotonic measured time from episode admission through controller, tools, waiting,
verification, process cleanup and dispatch, including the current adapter's
setup subtotal. Stage durations are components, never additional time charges.
Attempt costs include model input/output/cache charges, tools, failed launches,
retries, failures and cancellations. Remote work admitted before cancellation
must have its eventual bill reconciled; unknown charges are not recorded as zero.
Freeze the currency-to-score conversion and delay price lambda before results.
Provider charges and delay disutility are distinct; do not price one invoice or
one time subtotal twice. No post-hoc clipping of negative utility or large costs.

Report measured preparation, fitting, allocation search, validation, provisioning
and report-writing costs separately from service costs. Freeze a deployment
volume N_deploy and amortization rule before confirmation. The lifecycle contrast
is D_life=U_full-U_baseline-(K_full-K_baseline)/N_deploy, where K includes all
method-specific costs outside the service envelope in the same utility units.
Report both service and lifecycle results; shared costs need an explicit common allocation.
Estimated future costs require a frozen conservative bound, not a favorable plug-in estimate.
A favorable service result alone cannot pass the scaling gate.

## 2. Task separation and frozen methods

Separate development and confirmation by independent source/task families; near-duplicate instances, shared templates, repository revisions and common
latent scenarios stay in one split. Freeze provenance, hashes, inclusion rules,
verifiers and sampling weights before method selection. Development may choose
prompts, budgets, predictors, stopping thresholds and hyperparameters once.
Confirmation data cannot tune them or select a winning subset or endpoint.

Use the same immutable model revision, decoding contract, initial information,
legal tool access and admissible resource caps for every applicable arm. Freeze
controller/critic parameters after development; reset within-task learned state
between independent confirmation units. Any persistent cache or shared state
must be declared, costed and initialized comparably. Internal-task adaptation
may use only that task's legally obtained observations.

## 3. Required comparisons

| Arm | Frozen rule |
| --- | --- |
| Direct STOP | Produce the initial answer with no extra acquisition; charge its model call and verifier. |
| Fixed budget | Best development-selected fixed call/time schedule; no confirmation-based budget choice. |
| One-step VOI | Buy only when estimated one-query net improvement is positive; freeze estimator and tie rules. |
| Strong same-information planner | Exact planning when feasible; otherwise a development-selected strong feasible planner with its approximation/budget stated. |
| Full method | Paid identification, joint timing likelihood and stopping, with every learning/planning call charged. |

Required mechanism ablations remove paid identification, omit timing from the posterior while retaining the real execution clock, and replace duration-aware
planning with fixed-step accounting. They still pay actual costs. Predeclare
which contrast supports each mechanism claim. Any oracle or admissible bound
with additional knowledge is diagnostic and separately labeled; it cannot
replace the feasible same-information baseline or be supplied to the learner.
If no credible strong baseline can be executed, the broad superiority gate stays
at HOLD.

## 4. Paired execution and retained failures

Run every arm on the same confirmation task instances. Randomize arm order within predeclared execution blocks; freeze concurrency, cache, hardware and
provider settings. Use paired randomness only where the interface supports it;
matching seed labels do not imply identical provider outcomes. Freeze the repeat
count. Repeats are averaged within task, not counted as independent tasks.
Retain each task/arm/repeat score, terminal reason, all attempted fees, observed
timestamps, timeout/cancellation status, model/worker identities and source hashes.
Publish paired task differences, including losses. A failed attempt remains in
the intention-to-run analysis; any permitted infrastructure retry follows a
frozen rule and retains the original costs. Missing invoices or unexecuted arms
make the relevant comparison incomplete, not a zero-cost successful record.

## 5. Confidence and multiplicity rules

The inferential unit is a predeclared independent task/source cluster. Average repeats within task and tasks within cluster using frozen weights; the primary
estimand equally weights clusters. Report per-task results as well. Shared
execution shocks must be covered by the cluster/block design, not ignored.

Set familywise alpha=.05. Register every confirmatory baseline, task-family and
mechanism contrast in one family of size M, including absolute full-method
utility when claimed. Use one-sided Bonferroni allocation alpha/M. Freeze hard,
enforceable total service-cost bounds C_max before data, so U lies in [-C_max,1].
For n independent cluster contrasts D in [-B,B], B=1+C_max, the primary lower
bound is mean(D)-B*sqrt(2*log(M/.05)/n). Subtract the predeclared lifecycle charge
to obtain the lifecycle lower bound. For absolute U, the radius is
B*sqrt(log(M/.05)/(2*n)); subtract K_full/N_deploy for absolute lifecycle utility.
These conservative finite-sample bounds require the
stated independence and genuine bounds; a cap breach or unresolved charge
invalidates qualification rather than being clipped. No Gaussian assumption is
silently substituted. Additional bootstrap intervals are descriptive only.

Freeze precision h>0 and choose n>=ceil(2*B^2*log(M/.05)/h^2) for each primary
paired family comparison; this is a precision rule, not a power guarantee.
No outcome-dependent early success stop, unregistered sample extension or
post-hoc comparison removal. Unregistered follow-ups are separate exploratory work.

## 6. Adoption and unresolved freeze fields

Freeze a practically meaningful gain g_min>=0 before confirmation. Require the
simultaneous lifecycle lower bound to exceed g_min against every required strong
baseline, and the absolute full-method lifecycle utility lower bound to exceed
zero. Require this on at least two predeclared, source-independent confirmation
families before a broad framework/scaling claim. Preserve null/negative family
results and all costs; an inconclusive or incomplete gate remains HOLD.

UNFROZEN: model/provider/revision evidence; decoding; task bank/split/verifiers;
source-cluster/block definitions; method implementations; actual prices and
conversion; lambda; deadlines and cost caps; N_deploy; K accounting; g_min;
precision h; M; sample/repeat counts; cache/hardware/concurrency and retry rules.
Until these are fixed, this is a draft design, not a preregistered study or real-LLM evidence.
