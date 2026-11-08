# VERIFY-1: verification and risk Cell

This package executes a bounded SQLite experiment and provides native typed
reports, a fixture checker, and an Agentd evidence integration qualification.
The four-policy runner is separate from the retained model pilot described below.
It does not install a production Cell or grant effect authority. The original Hepta host continues to own authorization,
deterministic constraints and actual effect readback.

## Run

Python 3.10 or later and its standard library are sufficient. Run from the
repository root. Each output directory is create-only; retain failed originals.

```sh
python -B -m unittest discover -s experiments/verification_cell_verify1 -t . -v
python -B -m experiments.verification_cell_verify1.experiment --output /tmp/verify1-new-run --groups 4
```

The experiment freezes source hashes, all planned attempts, split assignments,
four executable policies and their budgets before effects begin. Twelve training
trajectories fit a two-bin historical frequency table. Twelve separate calibration
trajectories measure its initial-risk Brier score under the fixed-check policy.
Four confirmation groups contain 24 cases, each executed under four policies:
96 confirmation trajectories, and 120 trajectories including training/calibration.
These are repeated engineering templates, not 120 independent real tasks.

## Three distinct reports

| Report | Binding and meaning | Does not establish |
| --- | --- | --- |
| `RiskPrediction` | Exact task/attempt/subject/state/event/domain/horizon, predictor and evidence; a probability | Permission, correctness, calibration or proof |
| `CalibrationReport` | Predictor, selection policy, data digest, disjoint declared groups, empirical metric, drift state and assumptions | Validity on a changed policy/model/distribution or a trajectory coverage guarantee |
| `VerificationReceipt` | Exact subject/property/assumptions/checker/version/evidence/frontier and `proved/refuted/unknown` | Current host authority or an unexamined property |

JSON parsing rejects unknown/missing/duplicate fields, nonfinite values and bool
probabilities. `assert_bound` requires the exact expected report type and exact
scope. An `unknown` result retains its unresolved obligations. A claimed report
can be parsed without authenticating it: parsing is never a capability constructor.

`select_check` returns only `check`, `defer` or `blocked`. Optional checks use the
declared risk, loss and cost. A mandatory check with insufficient budget is
blocked. This function cannot return `accept` or bypass the host.

## Actual effects and the five faults

Every effect runs in a fresh Python process against a real SQLite database. The
owner commits its intent before the effect and records ACK separately. Repeating
an operation ID reads the original intent; an unresolved effect is never blindly
reissued. The controller's initialized goal is retained and compared in every
execution, readback, reconciliation and acceptance transaction.

| Injection | Actual fixture operation | Expected boundary |
| --- | --- | --- |
| Stale read | Change a value after an earlier successful snapshot | The old snapshot cannot override current state |
| Missing receipt | Commit an effect but omit its ACK | Return unknown; resolve by readback without repeating the effect |
| Semantic error | Store a well-typed but wrong target value | A successful write does not prove the goal |
| Partial success | Commit the first component and omit the second | Refute the complete goal; do not collapse item statuses |
| Common misjudgment | Store the wrong target under a distinct injected fault label | Exercise an external contradiction; actual multi-model agreement is not simulated as evidence |

Terminal acceptance performs a fresh goal/readback check in the same exclusive
SQLite transaction as acceptance. It accepts no serialized receipt or risk score
as authority. The owner, controller goal and SQLite transaction are trusted
fixture assumptions. A process able to rewrite the database is outside this
fixture's isolation scope.

The four executed policies are deterministic ACK rules, a historical frequency
table, a fixed check at step 3, and an external check at every step. They receive
the same optional-check opportunity cap (0.6 declared units, 0.2 per check) and a
separately reserved mandatory terminal check. Actual spending can differ. The
declared scheduling units are not measured dollars, energy or latency.

Within this original four-policy SQLite runner, single-step neural self-evaluation,
shared-base roles, different adapters and different bases are registered as
`NOT_RUN`, with zero inference receipts and missing artifact identities. Naming a fault `common_misjudgment` does not execute
an ensemble. No simulated model voting result is reported as a real-model result.

## Measurements and retained records

`plan.json` contains the full roster before execution. `attempts.jsonl` retains
starts, completions and failures; failed training/calibration yields a HALTED
result with all unstarted planned attempts. Worker stdout/stderr are retained,
including original bytes on failure/timeout. The runner does not auto-retry an
uncertain process. A hard process kill is not claimed to have a completed ledger.

`rows.jsonl`, `predictions.jsonl`, `receipts.jsonl`, `recoveries.jsonl` and the
databases retain actual observations. The engineering gate requires exact planned
and observed identities, known labels, correct clean/recovered completions,
detected faults, matched effect logs/meters and actual terminal checks. Rejecting
everything cannot pass.

Metrics separate actual policy acceptance from descriptive risk-threshold
selection across all trajectories. Zero acceptance gives an undefined error rate.
Unknown labels produce missing-label bounds, not confidence intervals. The risk
curve uses the frozen initial prediction; it is not a retrospectively selected
per-step maximum. Detection delay retains undetected cases; lead is measured
against the scheduled step-4 decision horizon, including early stops.

`compare_votes` accepts original per-voter records and reports base/adapter
provenance, paired error correlation and common failure clusters. Different
identities never imply independent errors. This original four-policy runner executes no neural
voters; the separate model pilot below has its own execution and source identity. `summarize_costs` rejects duplicate physical operation IDs and preserves
failed/cancelled work. Controller CPU and operation wall times are measured;
child CPU and energy remain unmeasured. Summed nested durations are not elapsed
time. `full_physical_cost_complete` therefore remains false.

The intervention artifact changes only the risk input or the declared check cost
to the scheduling function, with the same evidence digest. It tests this policy
function, not a neural activation intervention or an optimal decision theorem.

## Calibration and native evidence integration

`split_conformal_threshold` handles the finite-sample quantile using an exact
integer rank. When the required rank exceeds the sample count, it reports an
unavailable nontrivial threshold (`null` means positive infinity), rather than
clamping to the sample maximum. Its event is score-threshold exceedance;
exchangeability, distribution stability and any actual-error bound remain
unestablished. A zero score-miscoverage example can still have all outcomes wrong.

`kernel_payload` prepares bounded, versioned JSON payloads for the existing
`QualificationEvidenceEnvelopeV1`. It binds the inner record's exact encoding
and independently pinned digest. This serialization layer does not sign an
envelope, register a trusted issuer, execute Agentd ingress or authenticate a
queried payload. `kernel.evidence`'s `Supported` is not a property proof.

Separate native code validates the `hepta.verify1.report` namespace and implements
`check_verify1_sqlite(path, trusted_goal, expected_scope)`. The checker reads one
SQLite snapshot and recomputes the pinned fixture property; imported verdicts are
not checker inputs. Generic evidence append validates the report namespace but
does not automatically run this checker.

The [native qualification](../../qualification/verify1-native-20261108/README.md)
records a Linux run with 131 evidence-crate tests passing, one existing ignored
test, and four selected Agentd integration tests passing. The Agentd test starts
the actual daemon with ephemeral fixture trust and exercises signing, append,
query, replay, expiry, tampering, and current-trust revocation. Six Python fixture
cases produced seven native checks; missing ACK remained unknown until owner
readback, and no database acceptance rows were added.

Those observations bind the exact base plus source overlay and the distinct
tested/formatted hashes in
[SOURCE_BINDING.json](../../qualification/verify1-native-20261108/SOURCE_BINDING.json).
They are not a rerun of the eventual publication commit, a whole-workspace or
Bazel result, or a registration of a production signer/caller. The retained
[RESULT.json](../../qualification/verify1-native-20261108/RESULT.json) keeps
`model_inference=false`, `production_caller_registered=false`, and
`production_adoption=false` for this native qualification capsule. These fields do
not describe all VERIFY-1 experiments.

## Separately retained real-model pilot

The [run-v2 provenance and independent audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f25124815a9832af9b00652a4741d794a744df06/qualification/cell-research-stages-20261108/followthrough-20261108/README.zh-CN.md)
retained in PR #5346 describe a separate native model execution: 108 completed
policy trajectories, 652 actual model forwards, and three trained frozen-feature
logistic readouts. Its [audit result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f25124815a9832af9b00652a4741d794a744df06/qualification/cell-research-stages-20261108/followthrough-20261108/VERIFY1_AUDIT.json)
passed 43 checks by independently recomputing the retained originals, without
rerunning inference or training. These observations are distinct from both the
four-policy runner above and the native evidence/checker qualification capsule.

The model execution is bound by its source capsule and manifest. The retained
`published_model_source_commit` is `null`; the audit does not claim that its new
`model_*` files belong to the observed phase-1 PR #5351 head. Three frozen-feature
readouts are not base-model finetunes or independent natural-task trials. All
seven primary arms accepted 4 of 12 trajectories with zero accepted errors under
mandatory host readback; selector superiority remains unestablished. Equal voting
opportunities do not establish equal physical cost, and the pilot retains
scientific admission **HOLD** and production authority **NONE**.

See [INTEGRATION.md](INTEGRATION.md) for the original base audit, the native
extension, and the remaining owner integration, and
[STUDY_PROTOCOL.md](STUDY_PROTOCOL.md) for the real-model experiment.

Scientific acceptance, full physical cost, Agentd production integration and
real-model superiority remain **HOLD** even when this engineering gate passes.
