# Frozen paired-outcome critic for bounded System2 continuation

Remote parent: `8ff4c64f99ebab72865dc10d1845fad6ae3b918e` (PR #1753).
Tested Python commit: `a97a3e2a9ca19513a712e35bc0643e5e3143aad2`.
Delivery branch: `research/shared-stem-frozen-paired-critic-20261014`.
Research only. No main merge, selected-model mutation or native deployment.

## Actual implementation

The previous System2 controller consumed caller-provided scenario values. The new
`paired_critic.py` fits a small tabular estimator from a complete predeclared set
of paired stop/one-more-segment outcome records. `empirical_continuation.py` then
connects its frozen artifact to the EXISTING `system2_execution.run_reasoning`.
The result is data fitted, not a neural critic or trained generator. No alternative
runtime is introduced, and no NDU arm in the nine-arm model matrix is enabled.

Before observing outcomes, the operator freezes case fingerprints, group IDs,
fitting/calibration group partitions, candidate/feedback byte-length bins, all
utility coefficients, the error budget, minimum group counts, calibration-gap
threshold and resource envelope. At most 8192 paired attempts and 16 bins are
supported. A registered pair cannot disappear, be reordered, acquire a future
outcome, or move to another group during fitting. Case fingerprints must use the
provided case_fingerprint convention. Owner-supplied descriptors and receipt hashes
are NOT proof that the producer actually observed or computed them truthfully.

Each record must supply both the current candidate's stop utility and the utility
at the end of ONE additional propose/verify segment, as assessed by the fixed
external objective. Verifier acceptance is not used to generate these targets.
Failed/timed-out continuation has zero delivered utility under this fail-closed
estimand, but its work and time remain charged. Missing resource observations or
an observed envelope violation block the whole fit; expensive failed rows are not
filtered. The source experiment must retain the blocked fit and its costs, too.
This does not estimate a service that falls back to a previous selected model.
An adapter from authenticated real-owner trajectories to these records remains
needed; the tests supply explicitly synthetic paired outcomes.

## What is fitted and what the bound actually means

For paired record i, the target is

    Z_i = exp(-r*t_i_seconds)*U_continue_i - U_stop_i
          - c_work*work_i - c_time*t_i_ns.

Time, work and utility stay jointly paired; the code does not multiply separately
averaged variables. Rows are averaged inside each source group/bin first, then
groups are equally weighted. Repeating a group's rows cannot increase the number
of independent calibration groups. The fitting groups yield the fitted mean.
A disjoint calibration group set yields a conditional one-sided lower bound.
The emitted lower estimate is the smaller of the fitted mean and that bound.
Insufficient samples, an unobserved bin or excessive fitted/calibration mean drift
produce unsupported output rather than an optimistic point estimate.

Let C=c_work*work_upper+c_time*time_upper and K be the FULL predeclared bin count.
The target lies in [-1-C,1] only if the resource envelopes genuinely hold. For n
independent calibration group means in a bin, Hoeffding and a K-way union bound
provide radius

    (2+C) * sqrt(log(K/alpha)/(2*n)).

The calculation is conditional on bounded, independent groups with the matching
stationary within-bin distribution. Different IDs, data timestamps, length bins
and numerical checks do not establish those hypotheses. This is a BIN-AVERAGE
quantity, not pointwise confidence about a particular problem, uniform subgroup
retention, protection against distribution shift, or a final efficacy result.
The length features are intentionally simple; they are not claimed sufficient
for general reasoning. Across releases, repeated fitting/selection on the same
calibration material needs additional experimental control. Floating-point
calculations are not rigorously outward-rounded interval arithmetic.

Primary inequality reference inspected:
https://www.tandfonline.com/doi/abs/10.1080/01621459.1963.10500830

## Frozen runtime contract and costs

Opt-in reasoning policy V2 binds the empirical protocol ID. This profile permits
exactly max_rounds=2 and max_calls=5: initial proposal/verification, one critic
call, and at most one more proposal/verification. It does not pretend to estimate
an arbitrary multistep continuation. Old V1 policy bytes and scenario behavior
remain unchanged when empirical_protocol_id is omitted.

FrozenPairedCritic copies its fitted summaries, checks the external artifact ID,
and binds the exact proposer/verifier callable objects and their declared owner
profile. At invocation it reads only the fixed task/candidate/feedback and decision
context; it does not open outcome files, refit, or ingest final labels. Reusing a
known fitting/calibration case returns unsupported. Changing the objective,
coefficients, critic cutoff, horizon, callback object or artifact identity rejects.
This is not a sandbox, signed provenance system or guarantee about callback internals.

A separate EmpiricalEstimate type names conditional group-mean net gain. It is
not quietly converted to the previous deterministic branch-support type. Since Z
already includes discount and marginal segment cost, those terms are not charged
again. The already-spent critic invocation is not subtracted twice either. The
next segment must fit resources remaining AFTER the critic runs, and existing
post-segment checks fence actual envelope violations even if the verifier accepted.
The envelopes are preregistered, not learned sample maxima. Cooperative checks
cannot interrupt running kernels or prove a hard OS-level time/resource limit.

Offline fitting reports actual Python elapsed and CPU time, but leaves arithmetic
and energy counts missing. Runtime fitting/lookup consists of Python work: a zero
ATen arithmetic contribution does NOT mean free CPU, memory or energy. Existing
reasoning records continue to list Python/external-work/evaluation accounting gaps.
No arithmetic registry or CI/scientific gate is relaxed in this increment.

## Reproduction and actually observed tests

The unmodified parent source slice passed 279 tests. The exact seven uploaded
Python blobs passed 314 DISTINCT tests twice, zero failures/errors/skips: 279
retained + 13 fit/group/bound tests + 14 actual control tests + 8 release tests.
The two final exact-source logs are final-remote1.log and final-remote2.log in the
package. Earlier 312/314 runs and focused tests are retained as development logs.
Compileall and diff whitespace checks passed. Existing CI discovers these test
files; no hosted CI result or full-repository qualification is claimed.

Five extra diagnostics fit actual tables from SYNTHETIC observations and invoke
real CPU tensor/procedural callbacks. Supported data leads to 5 calls; low observed
gain, insufficient calibration and insufficient remaining budget each stop at 3.
A deliberately excessive second segment stops as continuation_support_violated
with 5 calls. Formula totals are respectively 12, 6, 6, 6 and 113. These are not
pretrained-model task quality, independent calibrated support or full-system costs.
Repeating every observation four times leaves the fitted table and group radius
unchanged. Decisions can be replayed from their retained typed inputs.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
```

The explicit OFFLINE fitting CLI consumes operator-prepared canonical JSON:

```sh
python qualification/stem-cell-v1/paired_critic.py \
  --protocol critic-protocol.json --protocol-id "$RETAINED_PROTOCOL_ID" \
  --rows paired-outcomes.json --dataset-id "$RETAINED_CANONICAL_DATASET_ID" \
  --output new-critic-directory
```

IDs use next_round_matrix._digest canonical JSON, not a raw file checksum.
The output directory is exclusive; FAILED excludes a successful release. Before
runtime, validate critic.json against its externally retained artifact_id and
construct FrozenPairedCritic with the admitted actual callbacks. The tested usage
is in test_empirical_continuation.py; its data/IDs are fixtures, not study defaults.

The independent HF attempt still failed at import (Transformers absent), so none
of its three checks ran or is counted in 314 passes. Direct GitHub/model/package
DNS failed in this session. GitHub source publication used the connected API.
No real pretrained models, approved paired outcomes, project-cloud/GPU/native,
full-repository/Rust or hosted-CI success were obtained. The local tree is a CPU
source slice; just and the full codex-rs tree are not available for repository fmt.

Remaining: actual admitted paired trajectories, authenticated objective/observers,
credible cohort features and distribution checks, independent final task outcomes,
same-total-cost baselines, complete energy/memory/work and native owner integration.
This turn adds no learned text/image/audio/video generator, general FBSDE solver,
multigeneration retention, 1024/4096-Cell validation or 10T/100T equivalence.
