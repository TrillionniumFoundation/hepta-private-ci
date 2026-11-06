# NDU blocker disposition — current candidate NO_GO

This checkpoint records what was repaired, what the experiments rejected, and
what remains unestablished. **It does not claim that every scientific blocker is
closed.** The current finite plug-in candidate fails the same-data strong-baseline
and primary lifecycle gates. Large-scale training is not justified by this work.
Real frozen-LLM confirmation remains **NOT_RUN**.

The checkpoint date is 2026-11-05 in America/New_York; execution receipts use UTC
and therefore include 2026-11-06. The code and protocol freeze is local before
data generation, not an independently timestamped external preregistration.

## Decisions supported by the evidence

| Question | Disposition | Evidence and limits |
| --- | --- | --- |
| Are the identified target-semantics and manuscript claims repaired? | Internally corrected in a draft PR | [NDU #1](https://github.com/TrillionniumFoundation/NDU/pull/1) withdraws the endogenous inventory-pressure claim and narrows regularity, representation and stationarity statements. It has not received external mathematical review. |
| Can the finite JAC optimization gap to the same-data DP be closed? | Yes, in the audited empirical finite models | [Gap study](../ndu_jac/evidence/gap_study.validation.json). Policy improvement reaches the same-bank DP value; empirical optimization does not guarantee true-model improvement or runtime superiority. |
| Are paid information, duration observations and legal stopping represented? | Qualified finite references | [Known-law reference](../ndu_identification/) and [clock runtime](../ndu_walltime/). These are distinct from a real LLM experiment. |
| Can unknown, state-changing joint kernels be estimated under explicit access? | Conditional finite contract and bounds established internally | [Theory](../ndu_learned_stateful/THEORY.md) assumes paid labeled/reset calibration, a known support/prior and atomic completion. It does not solve arbitrary unlabeled POMDP learning. |
| Does the current candidate beat the same-data myopic baseline? | **NO_GO** | **0 wins / 143 ties / 1 loss** across the 144 fixed cells. |
| Does the primary full-cost endpoint justify deployment? | **NO_GO** | **0/144** cells pass at the fixed primary deployment volume of 1,000; every absolute lifecycle lower bound is negative. |
| Is near-information-cost-bound efficiency proved for a new learned stateful algorithm? | **NOT_ESTABLISHED** | The prior classical known-law SPRT example cannot establish this claim for the learned, stateful candidate. A KL chain rule and a value-transfer upper bound are not such an optimality proof. |
| Do the actual external-data tools execute under the real clock? | Engineering smoke qualified | [Pinned Chinook/CPython tools](../ndu_llm_confirmation/external_smoke/): 5 checks and 8 scripted tasks, only 2 source clusters, zero real LLM calls. The runtime source is now bound to the receipt. |
| Is frozen-model/billing/confirmation plumbing qualified within its declared contract? | Internal engineering checks passed | [Confirmation package](../ndu_llm_confirmation/) and [independent internal review](../ndu_llm_confirmation/independent_review/). Its scientific gate remains HOLD. |
| Have independent real-LLM gains been demonstrated? | **NOT_RUN; required inputs absent** | [Available inputs](AVAILABLE_INPUTS.json) and [confirmation status](../ndu_llm_confirmation/status.json). No model/provider result is inferred from scripted fixtures. |
| Has independent external mathematical or scientific review been obtained? | **NOT_OBTAINED** | Separate agent implementations and adversarial reviews are internal checks. |
| Is a new general RL contribution established? | **NOT_ESTABLISHED** | [Primary-neighbor audit](../ndu_learned_stateful/PRIOR_ART.md). Joint design/stopping, physical state, cost-aware identification and simulation lemmas have direct predecessors. |

The failure dispositions close the decision to scale this particular candidate.
They do not convert failed scientific criteria into successful confirmations.

## The new finite unknown-kernel experiment

The [frozen study](../ndu_learned_stateful/README.md) has four locally prespecified
worlds, two calibration seeds, three sample counts and six deadline/fee conditions.
Hidden hypothesis, observable state, response label, duration and next state are
kept distinct. A query may repair or damage the state. A completed failure can
change the state; a timeout cannot expose an unfinished next state. This is an
explicit atomic-completion model, not a universal cancellation law.

| Samples per joint-kernel row | Observed maximum row-TV range | Frozen simultaneous TV radius | Maximum true-oracle regret |
| ---: | ---: | ---: | ---: |
| 16 | 0.24425–0.40726 | 1.00000 | 0.11430125 |
| 256 | 0.08258–0.13823 | 0.20653 | 0.01232977 |
| 8192 | 0.01639–0.02116 | 0.03319 | 0.00064350 |

Improved estimation reduces oracle regret in this finite model. It does not
establish a useful algorithmic advantage: the same-data myopic policy wins the
only non-tied comparison. Two small-data cells are worse than prior STOP.
The 24 observed row-bound events, 144 regret inequalities and 576 comparative
inequalities hold in these banks; finite simulation is not a proof of coverage.

The full raw banks and per-task utilities are retained in
[registered_v1](../ndu_learned_stateful/evidence/registered_v1/). The directory
name does not imply external preregistration. Result SHA-256:

```text
5e3c479a257da5776219227690cdaeef03ee7fb33ee3b0a8c8f69040f1f9d221
```

The independent internal [audit](../ndu_learned_stateful/evidence/validation.json)
uses a separately written unnormalized-mass trajectory calculation and DP. Values
agree to 1.11e-16 and paired raw means to 3.20e-14. Floating posterior arithmetic
can change a fitted terminal tie: the observed alternative-arithmetic true-value
difference is at most 0.00047817. The accepted frozen policy was not rewritten.

## Acquisition costs are part of the result

| Resource actually generated/executed | Count or declared cost |
| --- | ---: |
| Labeled calibration samples | 524,288 |
| Confirmation policy episodes | 3,538,944 |
| Paid query launches during confirmation | 1,229,038 |
| Failed query completions | 83,994 |
| Cancellations | 378,604 |
| Calibration cost | 6,290.148 score units |
| Confirmation cost | 82,576.630 score units |
| Total research acquisition cost | **88,866.778 score units** |

These are declared **synthetic prices**, not provider bills. Hardware and
engineering costs remain unpriced; the primary net-benefit failure already holds
under this optimistic omission. The actual compute timer is separate from
simulated durations. Each tested controller is charged the full collected maximum
calibration bank, including unused prefixes, plus its confirmation allocation.
The total research bill is larger than a single controller's setup allocation.

The secondary 10,000-deployment endpoint can improve absolute amortization but
cannot manufacture a gain over myopic VOI. It does not replace the failed primary
endpoint. Increasing deployment volume after observing failure is not a rescue.

## Execution-layer review and acceptance

The first 19 transport/task/gate tests passed, but independent internal review
found additional counterexamples. Their original qualification receipt is retained.
The concrete defects repaired were:

1. Boolean values or missing required fields could pass parts of the external
   evidence reader despite a stricter schema.
2. A successful model call with missing observed identity could be filled from an
   expected identity copied into an invoice.
3. Different full-policy callbacks could share a method digest that bound only
   the adapter and settings.
4. A worker could execute before the ledger had a durable request intent.

Final qualification verifies strict structure, observed successful identity,
actual callback artifact binding, and durable intent/terminal matching. An
unfinished intent remains HOLD; missing final costs remain unknown. Later
counterexamples also repaired impossible dispatch timestamps and verification
before final model generation. A slow intent write consumes the original request
and episode deadlines; exhausted admission cannot launch a worker.

The implementation's 39 tests pass. The separately authored gate positive control
passes, with 121/121 gate checks and 23/23 local worker/callback checks. These
checks use their own fixtures and do not reuse the implementation's synthetic
bundle or statistical calculations. The initial 113/114 failed independent
review remains unchanged beside the final receipts. All accepted receipts bind
the same stable source. They are internal engineering checks, not independent
experimental observations or an external scientific review.

The final [integrated receipt](evidence/verification-final.json) records **150
unique unittest cases actually run, with zero failures, errors or skips**. The
run started at 2026-11-06T03:57:12 UTC and finished at 03:57:34 UTC. It includes
the earlier 96 cases, 10 stateful cases, 39 confirmation-package cases and 5
external-tool cases. The separate 84 finite mathematical assertions match the
stored theory receipt. Sources and bound evidence were unchanged throughout.
The 121 and 23 independent-review checks are verified as existing source-bound
receipts; they are not counted again as newly executed unittest cases.
Unit-test PASS is not a scientific-confirmation PASS.

The external-tool smoke was separately re-executed to bind the actual imported
clock runtime. Both original and updated receipts remain available. Their timing
differences do not constitute a performance comparison.

## Repository delivery and CI boundary

The [remote stack audit](evidence/remote-stack-audit.json) verifies all 13 draft
PR heads, base branches and full trees in this round. The final implementation
and independent-review files were read back from the immutable top commit and
matched byte-for-byte. The [published-range inventory](evidence/published-range.json)
also matches all 79 files added since the earlier clock-runtime checkpoint to
their Git blob identities; each stored file is below the 512,000-byte limit.
The three large scientific artifacts and pinned SQL input use lossless gzip
storage. Reconstruction checks preserve every original raw-data hash. No size
allowlist or workflow policy was weakened.

Remote CI is **not green**. Inspected full-repository jobs report spelling
findings in existing regex/identifier text; Windows checkout fails on long
existing paths; a macOS dependency fetch reports an HTTP/2 error. The older
blob-policy job failed in its network-isolation setup before running the size
check, and the contract gate rejects two legacy development-plan paths outside
the NDU directories. These are recorded as observed blockers, not inferred
native-code regressions or passing checks. Other jobs remain pending. A one-line
NDU mathematical notation edit spells the product as `n * D`; it changes no
formula, frozen source, evidence or result. The historical CI receipts remain
historical failures. Local scoped spelling and file-size checks do not replace
required full-repository CI. No main branch merge was performed.

The implementation is split into reviewable draft units:

| Work | Draft PRs |
| --- | --- |
| Current primary neighbors and actual tools | [#4905](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4905), [#4906](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4906) |
| Finite theory, frozen reference and negative evidence | [#4908](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4908), [#4909](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4909), [#4911](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4911) |
| Actual runtime source binding | [#4912](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4912) |
| Contracts, transport, gate, callbacks and qualification | [#4914](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4914), [#4915](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4915), [#4916](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4916), [#4917](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4917), [#4918](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4918) |
| Independently authored internal gate and runtime review | [#4919](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4919), [#4920](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4920) |

## Requirements that cannot be supplied by a code patch

A real confirmation still needs a callable authorized model or local weights;
verifiable immutable model identity and decoding; final usage and billing
materials, including failures/timeouts; an enforceable hard cost cap; a complete
candidate implementation and qualified strong baselines; and untouched independent
source clusters with frozen task/verifier/split/order manifests. Source IID,
semantic near-duplicates and billing/identity authenticity require substantive
review; self-consistent hashes alone do not establish them.

There are no real LLM calls, real provider performance numbers or reconciled model
invoices in this checkpoint. No large training framework is launched. A new
candidate would require a new prospective protocol and fresh confirmation data,
while preserving this negative result. External review and a defensible original
algorithmic increment remain separate requirements.

## Reproduce the scoped acceptance

Run the accompanying verifier from the repository root, writing a fresh receipt:

```bash
python experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_blocker_closure_20261106/verify_evidence.py \
  --output /tmp/ndu-scoped-acceptance-new.json
```

It restores lossless evidence when necessary, then checks frozen sources/raw-bank manifests, evidence bindings and the unique
scoped Python tests without rerunning the research or making external API calls.
The 84 finite theory checks are reported separately from unittest cases.
This is not full-repository Rust CI, formal proof or external peer review.
