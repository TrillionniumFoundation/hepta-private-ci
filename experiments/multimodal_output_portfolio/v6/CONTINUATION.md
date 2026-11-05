# Continuation-only learning and conservative artifact updates

This additive research stage starts at repository commit
`18dac3ccd30317893ad922792c12400390522f00` (draft PR #4442).
It reuses the existing V6 text/image encoder, recurrent generator, actual PNG
and autoregressive UTF-8 decoder, source contracts and control backends. It does
not change the historical runner, policy census, requirements or result files.
V3 is a related four-output experiment, not a renamed V6 version.

**Selection remains `no-update`.** The new executable fixture establishes
training, inference, serialization and recovery mechanics. Its random pixels
and untrained observer cannot establish semantic quality or policy efficacy.
The requested dedicated Codex execution is blocked by unavailable environment
visibility in the currently exposed identity. A direct-host CPU preflight and
the separate hosted-CI workflow are not that deployment.

## What this stage implements

| Component | Implemented behavior | Qualification boundary |
| --- | --- | --- |
| `encoder_only` | Bypass the existing two-step initialization plan and return the actual base snapshot/state | Decoding, file I/O and observation still incur cost |
| `ContinuationHead` | Four fitted continuation coordinates; STOP reference exactly zero | Fixed suffix only, not optimal Q or repeated-replanning Q |
| State features | Shared, image, text and context tensors, plan identity and nine resource/version fields | Learned information state, not proved sufficient belief |
| Paired data | Same parent; actual four continuations and STOP; real decoder/observer callback; frozen source/model/cost/objective binding | Callback must provide its complete actual cost and external score |
| Native head | Same standardized double-precision linear map as Torch | Does not port the encoder, recurrent generator or decoder |
| Measured cost | Whole-request CPU/elapsed time, explicit owned residency, service charges, reuse/recompute counters and failed-work attribution | No inferred GPU time/energy; no whole-process memory claim |
| Admission | Fixed source census, bounded entropic margin test, hard resource checks, qualification-evidence binding | External acquisition/qualification reports are required; hashes do not establish their truth |
| Selection/rollback | Compare-and-swap ACTIVE, retained content-addressed artifacts, verified loads, monotone revisions and process-death lock recovery | Local file selection; not Agentd output/outbox ownership or optimizer/session rollback |

`continuation_head.py` accepts existing `NeuralSnapshot`, `ConditionedSnapshot`
and `ControlledSnapshot`. Audio/video and unknown input grammars are explicitly
unsupported. `public_features` preserves individual modality tensors instead
of averaging away their identity. Its feature dimension is `4*hidden + 14`.
The fitted min/max feature box is a narrow empirical support check. It does
not establish semantic OOD rejection, distribution calibration or coverage of
a deployed multi-step policy.

## Objective and known terminal structure

The runtime never receives target labels or the audit scorer. A known terminal
payoff rule does not make hidden content correctness known. The current V6
terminal forecast remains a learned quality distribution, explicitly separate
from the fixed STOP action structure. No new free STOP-Q head is introduced.

For risk aversion `gamma > 0`, the continuation labels are

`D(s,a) = E[exp(-gamma R_STOP) - exp(-gamma R_(a,fixed_suffix)) | public state]`.

A positive conditional expectation has the direction of a positive entropic
certainty-equivalent improvement. Its numerical value is **not** the CE
difference. `gamma=0` is an explicitly distinct mean-return difference profile.
Stable `expm1` branches avoid subtracting nearly equal exponential moments.
The return interval, gamma, source state, costs, suffix and checkpoint identity
are bound into the JSON artifact. Nonfinite/out-of-support outcomes are rejected,
not clipped. Common sunk prefix cost is excluded from both continuation labels
and must be charged once in the outer episode account.

Changing the suffix to repeated replanning changes the target policy. Such a
change requires new on-policy coverage and paired data; calling this head at
every step does not by itself validate the resulting multi-step strategy.

## Cost and admission scope

`CostMeter` records an entire serial request. Stage measurements are attribution
and are not added to the whole-request totals. Explicit candidate/cache object
identities accrue byte-seconds until release or finish. Child CPU must come from
actual reaping; asynchronous devices need their own real telemetry. A zero
tariff excludes a dimension from the objective; it does not turn missing energy
or GPU measurements into measured zeros. The final receipt write, training,
calibration, offline DP solving and archiving are outside the request meter and
require an outer ledger. Extra training cost is amortized at a frozen deployment
count by the admission protocol. Historical abstract work units are preserved.

`safe_update.assess` checks the exact source/draw census, matching information
hashes and budgets, preregistered bounded net returns and every endpoint. For
gamma greater than zero its source-level test variable is a positive constant
multiple of

`exp(-gamma R_base) - exp(gamma * minimum_effect - gamma R_candidate)`.

Its positive expected value implies `CE(candidate)-CE(base)>minimum_effect`.
The implementation shifts by the return lower bound and uses stable `expm1`
branches. It applies a one-sided Hoeffding bound and Bonferroni allocation over
the frozen endpoints. Draws within a source are averaged and do not increase
the independent sample count. This is conservative and conditional on valid
return bounds and independent source/measurement clusters. Independent images
alone do not remove correlated shared-host load; real experiments need frozen,
randomized execution order and an appropriate collection-block analysis.

`select` preserves ACTIVE bytes on `no-update`. Prospective confirmation is
consumed locally by both original-source content SHA-256 and input-information
SHA-256, so renaming a source cannot reuse it. The collector must verify these
hashes from actual bytes. `collected_at` means original input/world acquisition,
not the time an old example was rescored. The local selection ledger does not
replace a project-wide historical source registry or an external acquisition
attestation. A new directory is not a scientific reset.

Qualification flags and their digest bind an external report; they do not run
the calibration, state-coverage or OOD experiment themselves. The current
fixtures deliberately have no scientific confirmation or promotion authority.

## Recorded direct-host preflight

The retained [evidence](continuation_evidence/20261104/) records the final
direct-host CPU engineering preflight with Torch `2.6.0+cpu` and Rust `1.95.0`.
Dedicated project Codex execution and hosted-CI execution require their own
separate results; this record establishes neither.

| Observation | Recorded result |
| --- | --- |
| Contract suite | 35 tests passed; unittest reported 8.350 seconds; the test subprocess took 12.7646 seconds wall time |
| Retained media | Two synthetic input cases, five executed branches each, producing 10 actual PNG/caption bundles |
| Fitted head | 78 standardized features, four continuation outputs, fixed STOP value 0 |
| Torch/Rust comparison | Maximum absolute difference 0.0 on the two retained feature rows; `atol=rtol=1e-10` |
| Fresh-process reload | Saved generator and head reloaded, input re-encoded, and initial-state inference matched exactly |
| Update disposition | `no-update`; no scientific confirmation and no production activation |

The two cases are a seeded random-pixel input and its complement. In the
retained fixture the generator and observer are untrained; only the
continuation head is fitted. These cases are not independent semantic tasks,
and neither their scores nor the test count demonstrate a quality improvement.
The zero numerical difference covers the tested four-output linear map. The
fresh-process result covers checkpoint reload and deterministic initial-state
recreation, not an arbitrary in-progress generation session. The timings
describe this contract run rather than a production latency qualification.

## Reproduce the engineering scope

Use an isolated Python 3.12 environment with `continuation_requirements.txt` and
Rust 1.95.0. These pins are separate from the historical V6 environment.

```bash
rustc --edition 2021 -C opt-level=2 experiments/multimodal_output_portfolio/v6/continuation_native.rs -o /tmp/hepta-continuation-native
export HEPTA_CONTINUATION_NATIVE=/tmp/hepta-continuation-native
python -B -m unittest experiments.multimodal_output_portfolio.v6.test_safe_update experiments.multimodal_output_portfolio.v6.continuation_head_tests experiments.multimodal_output_portfolio.v6.neural_tests experiments.multimodal_output_portfolio.v6.plan_training_tests experiments.multimodal_output_portfolio.v6.test_control -v
python -B -m experiments.multimodal_output_portfolio.v6.continuation_fixture --output /tmp/hepta-continuation-fixture --native-binary "$HEPTA_CONTINUATION_NATIVE"
```

The fixture saves real PNG/text bytes, paired records, the generator checkpoint,
the fitted continuation JSON, native comparison and exact new-process restore.
Its labels are explicitly engineering fixtures. Tests for admission include
real process termination, preserved ACTIVE on no-update, stale writers,
retained rollback bytes, invalid costs and source-renaming attacks.

## Requirements still open

The general design and complete evaluation plan are in `CONTINUATION_DESIGN.md`.
The following are not established by this stage:

- Dedicated project Codex environment training/inference/rollback execution.
- Full seven-way comparison on newly frozen independent worlds: encoder-only,
  static allocation, fixed steps, light control, same-information exact finite
  DP, dynamic policy and separately labeled hindsight oracle.
- Matched training-time and execution-time factorial with robust full-cost gain.
- Belief/selected-action calibration, deployed-state coverage and semantic OOD.
- Chronologically new raw samples with complete historical-content exclusions.
- Real external READ/WAIT/REPAIR/SUBMIT dispatch and event-driven information gain.
- Optional output-modality set selection; V6 still requires both text and image.
- Full Torch/Rust encoder/decoder equality, production owner integration and GPU/energy qualification.
- Actual synchronized audio/video decoders; four-slot schema remains an extension interface.

These items stay open even if every engineering test passes. Retain the fixed
baseline or `no-update` until the full preregistered acceptance contract passes.
