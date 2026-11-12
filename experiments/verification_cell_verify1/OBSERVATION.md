# VERIFY-5: observe information before fitting the risk scheduler

This research candidate extends VERIFY-4 at
`88deb8a490565fd9b55851ba4581c9516fd1029f`. It keeps deterministic property
checking, risk prediction and actual host acceptance as different operations.
Scientific admission remains **HOLD** and production authority **NONE**.

## Incremental paid-information attribution

The initial ACK and later readback comparison changes both observation time
and available ACKs. `all_effect_acks` is derived from acknowledgements already
held after effect 3; it is not information bought by the SQL query. Therefore
the original Brier difference is not an isolated paid-readback effect.

After the consistency gate, analyze the original saved probe events with:

```sh
python -B -m experiments.verification_cell_verify1.observation_attribution --input RUN_DIRECTORY --output NEW_ATTRIBUTION.json
```

The nested views are first ACK, all three individually retained ACKs, and those
same ACKs plus paid resource presence. Exact rational arithmetic decomposes
sample conditional-probability variance, with per-source and task-weighted
summaries. In the original train/cal/confirm cohorts, resolutions are 0,
4/45 and 7/72; the paid conditional increment is 1/120. All are zero in shift.
This retrospective sample description fits/predicts nothing and adds no tasks.
It establishes neither a held-out predictive gain nor causal policy/net benefit.
The full ACK tuple is a richer free control than its `all_effect_acks` aggregate.
Unknown labels refuse attribution; repeated policy arms are not extra samples.

## Claims and available information

| Claim or input | Observable facts | First available point | Cost / wrong-verdict treatment |
| --- | --- | --- | --- |
| Initial ACK view | Actual first-effect acknowledgement | After effect 1 | Effect is metered; no terminal label or hidden fault in predictor input |
| Partial readback view | Current epoch/tick and resource names; all observed ACKs | After a paid readonly transaction following effect 3 | Separate read cost; resource values and fault identity are excluded |
| Optional property check | Actual two-field values, intents and current readback evidence | When the deterministic checker returns | Full check cost; result does not accept an operation |
| Mandatory acceptance | Fresh trusted goal/epoch/property check, with ACK reconciliation where required | Terminal host transaction | Paid in every arm; a risk probability never satisfies this gate |
| Terminal value label | Separate SQL transaction against actual values and the trusted goal | After mandatory acceptance/rejection | Independently queried, but same database/host and simple rubric; not independent real-task adjudication |

The Python SQLite fixture runner is not an additional Rust checker or Agentd
owner integration qualification. Its goal, selected database and host remain
trusted. The deterministic predicate is not replaced by a learned classifier.

## Frozen experiment

`python -B -m experiments.verification_cell_verify1.observation_smoke --output NEW_DIRECTORY`
creates a run once and refuses to overwrite it. It retains PLAN, MODEL,
DIAGNOSTICS, RESULT, operation costs, observation events, terminal records and
the actual SQLite databases. Failures retain the full planned denominator,
NOT_STARTED versus UNKNOWN, and already observed acceptance with an unknown
label. Recovery never relaunches a prior run automatically.

The plan has 60 probe trajectories in 10 template groups: train 3, calibration
2, confirmation 3, shift 2; six cases per group. The confirmation phase also
executes all four arms on separate databases for every one of its 18 cases,
giving 132 planned trajectories. These are controlled fixtures from one
generator, not 132 independent real tasks or ten independently sampled sources.

The initial ACK is recorded after effect 1. The partial readback sees only
`all_effect_acks`, `left_present`, `right_present`; it never sees values, fault
names, task IDs, source IDs or terminal truth as model features. A training-only
conditional-probability-resolution diagnostic precedes fitting the existing
content-bound RiskTable v2. The ACK baseline is a constant training prior.
The fitted frequency model is a transparent reference, not an LLM or a
calibration guarantee. Calibration, confirmation and shift execute later and
their labels are not fitted. Prediction precedes each terminal-label query.
Every view retains the model identity that actually existed at observation time.

The four actual arms are `no_optional_check`, `fixed_readback`,
`risk_triggered`, and `oracle_information`. All have the same maximum of three
optional operations; reads, frequency prediction and property checks each use
one declared operation. Physical wall and calling-process CPU costs are
measured separately. Mandatory checks are retained in all arms.

The oracle reads the actual values after effect 3 under a frozen continuation
that never changes those values. Its information query is physically charged.
It is an information control, not an upper bound on total policy utility.
Optional checks in this experiment do not repair or change state, so any
prediction improvement must not be promoted to terminal policy improvement.

## Statistics, drift and costs

The diagnostic projection permits only a frozen sequence of bool/unknown
signals and rejects late observations, cross-phase source reuse and inconsistent
case labels. It reports complete supplied denominators, unknowns, fixed-bin
reliability, Brier/ECE, per-source metrics and equal-source versus task-weighted
Brier separately. A source name does not prove independence. No new sign-flip
p-value, confidence guarantee or scientific admission is produced.

Feature-cell accuracy and conditional-probability resolution are optimistic
sample descriptions. Singleton separability is not generalization. Diagnostic
`decision` fields are shadow threshold summaries; actual executed checks are
counted only from the four-arm trajectory receipts. Checks on later-clean cases
are not causal false rejections. The reported terminal-value rejection count
also does not adjudicate independent owner/authorization obligations.

Model/schema changes or incomplete calibration/current observations block reuse.
Otherwise `recalibration_required` is unknown, not false: Brier/ECE differences
and feature total variation are descriptive, with no statistical drift decision.
The shift phase changes the declared fixture mixture to five clean cases and
one semantic error per group. It does not update or adopt the frozen model.

Costs include initialization, effects, partial readback, inference, optional and
mandatory checks, reconciliation, terminal labels, training and probe collection.
Training/probe costs are reported separately and are not silently amortized
away. Overall wall covers phase execution/reporting after PLAN is written;
meter totals omit logging overhead. Energy, provider pricing, deployment costs
and complete physical loss remain unmeasured. A lower single-run wall value
does not establish a speedup or net benefit. The learning decision is NoUpdate.

## Reply integrity and real-source adapter boundaries

The companion dispatch repair revalidates complete CheckerReply fields and
compares canonical bytes across authentication and snapshot callbacks. A changed
reply leaves the original operation pending; the checker is not redispatched.
This changes the scheduler content identity. Historical journals keep their
original identities and are not silently rebound to the new code.

The qualification directory also retains real GitHub Actions readbacks for six
run attempts and sixteen jobs. Those reads have no pre-terminal snapshots or
observed initial ACK and no independently adjudicated business labels. They
demonstrate a real-source readback contract only. They cannot be joined to the
fixture confirmation denominator or used to claim prospective policy benefit.
