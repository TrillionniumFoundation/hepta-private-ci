# Acceptance review and maintenance correction

This review answers the three original work-package acceptance criteria. It
preserves the registered methods and outcomes. The post-publication change is
one development-test assertion plus documentation and new maintenance evidence;
there is no new screening, confirmation, threshold selection or scientific owner
run.

## Acceptance by work package

| Work package | Delivered evidence | Acceptance and limits |
| --- | --- | --- |
| Mathematical operators | One-shot and repeated-reset stopping solutions; independent root and optimizer references; implicit sensitivities; degeneracy handling; deterministic moving-boundary checks | All 20 registered numerical gates pass. Analytic global verification applies to the stated constant-coefficient, affine-payoff models and eligible interior policies. Constrained threshold-family and mesh-convergence claims retain their narrower scope. |
| Task and learning | Causal sequential evidence; six boundary-by-surrogate arms; raw-belief DP and myopic references; frozen seed and statistical protocol; 90 fits and independent checkpoint audits | All registered arms and seeds are present. Both primary boundary comparisons pass. First-passage surrogate superiority is not established. The boundary comparison identifies a model-informed stopping module, not a unique geometric or SNN benefit. |
| Hepta execution and accounting | Versioned profile; original owner/runtime/journal/witness; 168 episodes; applied stop decisions; cold recovery and complete audit | Functional execution passes, with 56/56 DP path parity and 127 fewer actual ticks than fixed boundaries. Declared runtime/recovery/audit work is counted. Historical setup and build CPU were not measured; exact historical replay is not yet portable without the original binary. |

The research work packages are delivered within these stated domains. This is
not a production qualification, a measurement of total project cost, or a claim
that every repository CI check passes.

## Correction to the historical test claim

Review reproduced a failure in
`LearningTests.test_failed_attempt_preserves_completed_and_trained_checkpoints`.
The runner writes `seed_900001_fixed_first_passage_checkpoint.json`, while the
test expected the old `seed_900001_fixed_fpt_checkpoint.json` name. Only that
expected filename was corrected.

The old preflight receipts report 46 passing tests, but do not bind the tested
source to the final sealed inventory. The final sealed test file contains the
stale assertion. Those receipts therefore cannot substantiate an unqualified
claim that all 46 tests passed on the original published revision. The original
receipts, failure and correction are retained rather than replaced.

Current maintenance validation is explicit:

- [Final full test receipt](results/maintenance001/all_tests_final.json):
  **46/46** passing development fixtures on the final formatted inputs, with
  their complete inventory and exact native-binary hash. Earlier maintenance
  runs below remain available as intermediate checks.
- [Learning test receipt](results/maintenance001/learning_tests.json): the old
  failure followed by **10/10** passing learning development tests.
- [Remaining test receipt](results/maintenance001/remaining_tests.json):
  **36/36** passing mathematical, native owner, audit and provenance fixtures,
  with the full current input inventory and exact native-binary hash.
- [Source comparison](results/maintenance001/source_comparison.json): all 105
  original sealed inputs match both the original scientific source commit and
  the published evidence commit. The corrected working revision differs in
  exactly the one test file; the other **104/105 inputs are unchanged**.

These tests use development fixtures, not the scientific seeds. Their timing
is recorded as maintenance validation and is not added to the original
experiment's runtime or used as a new scientific outcome.

## Separate source identities

The original scientific source is
`95b0d6668892868a4a19268a2fb707f2dca586ba`. Its evidence was published at
`c32392367b7587d09806ca5cbc74678a168b4e16`. The original
[source seal](results/SOURCE_SEAL.json) is unchanged, with SHA-256
`5876ab602e03e4c1f324342f8e046246c2162d4e9a07d1016d7d2edfcffa162c`.

That seal correctly rejects the corrected test file. The verifier has not been
weakened or given an exception. Historical audits must use the original
source/evidence checkout, as described in the [runbook](README.md).

The [maintenance seal](results/maintenance001/SOURCE_SEAL.json) identifies the
corrected, committed inputs. It was made after the original outcomes and must
never be described as preregistration of those outcomes. A fresh scientific run
requires a new attempt and unused evidence destinations. The archived 90 fits,
20 numerical gates, checkpoint audits, 168 owner episodes and final owner audit
retain their original identities.

## Interpretation retained after review

The two adjusted 97.5% confirmation intervals for OOD free-minus-direct utility
remain `[0.05554642, 0.10014108]` with the standard surrogate and
`[0.02827160, 0.08433484]` with first passage. Both lower limits exceed the
registered 0.005 effect threshold. All three descriptive first-passage versus
standard intervals include zero, and the raw-belief DP mean exceeds all neural
arms. [Confirmation statistics](results/learning/confirmation_summary.json)

All arms share causal observations and visible task context. The free method
also uses the known task law to solve its stopping rule; raw-belief references
make that model knowledge explicit. The experiment does not separately identify
pure boundary geometry from this computational prior. The surrogate comparison
covers both spike and action gates, and different boundary methods jointly
influence their trained readouts. These are limits on attribution, not evidence
of access to hidden labels or future observations.

The actual owner uses a separate finite Gaussian MDP readout. Learned SNN
readouts, joint drift/noise/cancellation fitting, Organ Credit feedback and
continuous-time Q-learning are not implemented results of this study.

## Costs and replay qualification

Execution and independent audit account for 10,932 original-kernel executions,
70.618441 CPU seconds and 78.649521 wall seconds. Five Cargo invocations add
35.090618 recorded wall seconds. Historical build CPU, dependency acquisition,
toolchain and workspace preparation were not timed; no retrospective estimate
is inserted into the original ledger. No hardware energy measurement exists.
[Cost scope](REPORT.md), [build timing](results/owner/build/history/README.md)

The original 2,649,608-byte native executable is present locally and its SHA-256
still matches the historical receipts. It is not committed under the repository
blob limit. The recorded owner replay has passed, while another machine needs
that exact binary or a proven byte-identical build to replay the same identities.
A source rebuild with a different hash supports a new reproduction. Identity
checks and permissions are not relaxed to make historical replay appear portable.

## Repository CI

The published evidence revision's completed checks and baseline comparison are
recorded in [CI status](results/maintenance001/CI_STATUS.md) and its linked
diagnostics. Research validation and repository-wide merge gates are separate.
The PR remains a draft; successful local checks do not override failed or
cancelled repository jobs.
