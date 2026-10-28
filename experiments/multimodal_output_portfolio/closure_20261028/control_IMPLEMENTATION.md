# Actual NDU host decisions, complete execution costs, and tail limits

This package moves the NDU action into the actual native execution path. At the
semantic boundary a frozen host actor chooses `keep` or a fresh full-bundle
`swap` by minimizing the estimated complete selected-action exponential moment.
The original owner still checks its expiry, media allowance, abstention, and
`DENY_ALL` authority. Its readout weights, kernel implementation, and authority
are unchanged. The host decision is therefore executable without making the
new estimator an authorization authority.

The common immutable `NduProfile` schema is reused. This is a **new profile** for
these host episodes. The numerical fullpath tariff study and the stronger
natural semantic study have different task and execution contracts; sharing a
schema does not make their profile hashes interchangeable.

## Execution and estimator

`control_episode.execute_episode` is the shared train, calibration, and
execution entrypoint. The caller captures `episode_started_cpu = cpu_seconds()`
at its own `complete()` entry, before adapter, RNG, public context, and binding
construction. It supplies `prepare`, `emit`, and post-stop `terminal_score`
callbacks. The emitter registers each realized sample density before encoding,
advances the episode RNG for a retry, and writes through the bounded writer.
Actual PNG, WAV, FFV1 video, and UTF-8 files are reopened. A failed codec retains
its realized density, partial writes, elapsed work, and failed terminal return.
Private target scoring starts after the owner has closed.

For fixed gamma and finite undiscounted horizon the actor fits

\[
M(s,a)=\mathbb E[\exp(-\gamma R)\mid s,a],\qquad
R=U(\text{actual delivered files})-\sum_j C_j.
\]

Random physical costs remain inside the exponential. The gamma-zero control
uses a positive affine transform of negative complete return. The log-link
actor minimizes the proper mean-moment objective; the later lower-capacity
actor uses equal original-source weight within each observable stratum and
action. Neither actor presents its estimate as a confidence bound or a global
optimum. Fits reject development/calibration rows and conditional profiles
cannot silently pool distinct contexts.

The deployed table uses only arrived transport feedback, original-owner
abstention, and remaining media slots. The port also accepts sixteen public
features for the log-link actor; target labels and terminal observer scores are
excluded. Source-paired training physically executes both interventions, with
common initial random numbers declared as a comparison design. They are not
counted as independent source observations.

## What is actually charged

The enclosing self-plus-reaped-children CPU interval includes per-episode
preparation, all binding checks, planning, owner calls, neural emissions,
serialization, retries, failed attempts, and post-stop scoring. It is charged
once. Actual generator calls, deliveries, refused proposals, original kernels,
and cumulative file bytes have separate frozen prices. Partial failed writes
are not removed from the ledger. One-time corpus/model loading, optimizer
updates, and research reporting are recorded outside the deployment interval.

Two emissions, cumulative bytes, public-state size, and seventeen original
kernels have executable work limits. The ten CPU-second rule only prevents
admitting another emission after the threshold is reached. It does not cap or
clip physical CPU already consumed. With the declared tariffs the discrete
work part has an upper cost of `0.044088608`; positive-price CPU remains outside
that support bound.

## Preserved attempts and actual results

[ATTEMPTS.json](control_results/ATTEMPTS.json) records every attempt and file
hash. Earlier evidence remains intact.

| Attempt | Scope and status |
| --- | --- |
| Host 001 | First real episode then a NumPy JSON serialization failure; retired before fitting or development. |
| Host 002 | Log-link actor; development CE 0.211305 versus always-retry 0.265160. Negative result retained. |
| Host 003 | Source-uniform table chosen from training evidence; development CE 0.267918 versus always-retry 0.265046. |
| Host 004 | Same table protocol with the caller-entry preparation timer repaired; complete-cost execution checks passed. |

Attempts 002 and 003 have an explicit billing-review notice: caller adapter and
case assembly preceded their timer. They are not accepted as complete-billing
evidence. Attempt 004 changes that boundary only, without tuning on additional
qualification data.

[HOST_TABLE_FINAL_RESULT.json](control_results/HOST_TABLE_FINAL_RESULT.json)
contains 32 actual training interventions and 24 development episodes, 72
fresh emissions, 952 original kernels, and 20 failed terminal episodes. The
host decision differed from the legacy readout proposal on four of eight
selected-policy development events. All ten mechanism checks passed. Complete
episode CPU was 35.079658 seconds. Descriptive development CE was 0.268179 for
the host table, 0.265239 for always-retry, and 0.178524 for always-keep. This small
comparison on consumed development sources is not a capability qualification;
its advantage is largely avoiding infeasible retry proposals and refusal fees.

## Independent selected-policy calibration

The separate
[FRESH_SOURCE_ALLOCATION.json](control_results/FRESH_SOURCE_ALLOCATION.json)
reserved sixteen original videos before media access. It excludes both the old
natural sources and every source in the stronger task's frozen 768-source
allocation. The final Host 004 profile, actor, source list, seeds, threshold,
alpha, and normal-transport scenario were fixed first. This cohort does not
consume the stronger natural study's policy-calibration or qualification roles.

[FRESH_SELECTED_POLICY_TAIL.json](control_results/FRESH_SELECTED_POLICY_TAIL.json)
reports sixteen actual selected-policy episodes, thirty-two fresh emissions,
272 original kernels, and 11.933429 CPU seconds. All actual selected swaps
executed. One complete return fell below zero and remains in the joint law.
The empirical CE is 0.349728. With simultaneous alpha 0.05 split across the two
predeclared binomial events, the exact upper limits are:

- `P(complete net return < 0) <= 0.302321` from one violation in sixteen sources;
- `P(CPU admission threshold exceeded) <= 0.205907` from zero in sixteen.

These bounds require independent source draws under the frozen execution law.
Participant independence and independence of shared-host execution-cost noise
are not established by source disjointness. The binomial formulas are exact
under their independent-trial sampling assumptions; this run does not prove
an unconditional future deployment guarantee. This normal-transport cohort does
not certify the injected-fault mixture, a different generator, or the stronger
natural task. Source IDs are registered for exclusion from later studies.

The average predicted selected moment was 0.714949, while the actual
source-average exponential moment was 0.496855. The latter is a finite-sample
diagnostic, not an error-certified calibration of each conditional action
value. The estimator is bound to the executed policy, but accurate point
valuation and an upper-tail certificate are separate questions. See
[SELECTED_MOMENT_INTERPRETATION.json](control_results/SELECTED_MOMENT_INTERPRETATION.json).

**The strict physical-cost NDU tail blocker remains open.** A binomial bound on
a threshold event cannot upper-bound the magnitude of unobserved cost beyond
that threshold. Thus `ndu_moment_upper` and `ndu_ce_lower` are deliberately
`null`. A data-only finite exponential-moment bound is impossible over all
unbounded cost distributions: an arbitrarily rare, sufficiently large cost can
leave all observed samples unchanged while exceeding any proposed bound. The
behavior tests include this counterexample. A future certificate needs an
independently justified cost support or exponential-tail envelope, or a real
contract that bounds the charged economic loss while reporting physical work
separately. Sample maxima, clipping, and relabeling physical cost are not such
justifications.

## Separate process-tree budget experiment

`control_supervisor.py` launches a dedicated job session, uses a Linux child
subreaper, tracks descendants including orphans, applies process CPU/file
limits, kills only its own job, and reaps all descendants with `wait4` usage.
The supervisor's own full process CPU is also included. The four final reports
cover a normal completion, CPU-bound child tree, orphan, and actual FFmpeg.
All known descendants were reaped and usage reconciled; measured child CPU
overshoots of roughly 0.020--0.040 seconds were retained.

This is an isolated operational diagnostic, not an integrated native-episode
sandbox or a proved future CPU support bound. The earlier strict accounting
assertion failed on operating-system microsecond rounding; that failed attempt
is retained separately. The final comparisons allow documented rounding, not
unbilled work. Linux's documented CPU limit delivery and cgroup controls do not
establish a deterministic bound on this supervisor's future overhead or kill
latency: [getrlimit](https://man7.org/linux/man-pages/man2/getrlimit.2.html) and
[cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html).

## Reproduction and stronger-task port

From the repository root, using the environment with Torch and codecs:

```sh
python -m unittest experiments.multimodal_output_portfolio.closure_20261028.control_tests -v
python -m experiments.multimodal_output_portfolio.closure_20261028.control_study \
  --binary /path/to/original/owner_host --checkpoint /path/to/ndu_neural.pt \
  --assets /path/to/original/natural_assets --output /new/research/run \
  --actor-kind source_table
```

The eight behavior tests cover risk/mean action reversal, correlated costs,
source-uniform weighting, strict profile and source roles, actual selected
policy identity, retained catastrophic costs, and the impossibility witness.
Fresh calibration must be run from its sealed source plan; it is not recreated
by reusing the sixteen consumed sources as new independent evidence.

The stronger natural port implements the same callbacks and public boundary
schema, with two-second larger outputs and independently qualified semantic
observers. It must fit and freeze its own complete-action moments and calibrate
its actual selected policy under its own profile. Reusing the old table's
numerical valuations for that different generator would not close valuation
or capability blockers.
