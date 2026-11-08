# HCSN shared training graph and native candidate handoff

This is an opt-in engineering bridge on top of research source
`f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b` (PR #4873), whose Rust base is
`732e934ba496d90fbe042b8d41d479ef901643e5`. It does not change the frozen
`qualification/hcsn/` sources, original research configurations, or the deployed
170-run CUDA campaign. It does not activate a model or establish research benefit.

## Boundaries

| Concern | Implemented boundary | Remaining scope |
| --- | --- | --- |
| Physical time | Rust microsecond profile and actual integer timestamp differences; seconds in the tensor backend; bounded coarse blocks; separately bound forecast horizon | Original sparse Q24 profiles retain fixed-step semantics. |
| Shared BP | Named logical A or B Cells share one PyTorch graph and task MSE; gradients reach earlier cells and time samples | CPU derivative and small continuation fixtures are engineering evidence, not scientific benefit. |
| Population B | The shared graph executes aligned, bounded fixed-grid microsteps and retains all five state slots | No arbitrary-dt refractory-state migration is claimed; the original fixed-grid policy is preserved. |
| Control graph | A native authorized TaskFlow driver uses a pinned process supervisor; the worker executes all numerical intervals internally | Production host registration and actual trust are still explicit host responsibilities. A compiled control graph is not a tensor tape. |
| Learning semantics | Only `task_mse_bp_v1` can enter this worker; native handoff tags distinguish BP, eligibility and NDU credit | Gradient evidence does not prove NDU gain or independent evaluation. |
| Publication | Native byte/identity checks delegate to the existing fenced `LearningArtifactOwnerService`, withdrawal frontier and immutable payload store | Publication leaves a candidate. Evaluation, selection, deployment and production trust are not granted. |

## Time and state semantics

`HcsnTimeProfileV1` uses integer microseconds in an independently identified
monotonic clock epoch. A numerical interval is `[start, end)`: external input is
sampled on the left, held over the interval, and readout is on the right. The
forecast horizon identifies the task target; it is not elapsed time and does not
replace the learned HX financial maturity.

For A, each logical cell after the first consumes its predecessor's
**previous-boundary memory** for the interval. All new states commit together at the right boundary.
This explicitly frozen-coefficient scheme is not an exact solution of a coupled
nonlinear ODE, and no resampling-invariance claim follows from its exponential
subupdate.

For B, a coarse interval contains an integral number of the admitted fixed-grid
microsteps. External input is held throughout that interval; every logical cell
reads its predecessor's previous-microstep trace, and all cells commit together
on each microstep. Splitting one held-input interval into aligned groups preserves
the exact recurrence. Trace, active population, refractory queue, recovery and
escaped mass are checkpointed. The adapter preserves the research kernel's
ceiling rule for refractory queues and records the effective duration; it does
not reinterpret a fractional queue slot as a continuous-time state.

The Rust batch planner derives every interval from one real outer checkpoint.
It advances only the integer time cursor while preparing the block, without
inventing intermediate tensor states. The worker preserves all intermediate
tensors in memory; the owner can commit one final complete state after successful
execution. Partial work, cancellation or unknown outcomes must leave the old
acknowledged anchor intact. Restoring clock metadata requires the independently
retained checkpoint digest and exact profile/model/scope/clock/writer identity.

Training changes the model parameters. The returned final numerical state belongs
to the candidate model, not the base model. A candidate checkpoint must receive its
own explicitly admitted model identity before state continuation; it cannot be
silently committed as the base model's active state. The acceptance fixture uses
synthetic trust and demonstrates publication/readback, not production adoption.

Request schema 2 makes initialization explicit: `fresh` requires a model-only
checkpoint and sequence-zero clock; `resume` requires complete saved numerical
state, exact ending time and an authenticated outer clock checkpoint. The worker
recomputes the native clock digest and complete state digest before training.
Every SGD evaluation starts from the same detached admitted state. A state-bearing
legacy schema-1 request is rejected, so it cannot silently reset a candidate's
state to zero. Candidate metadata retains its predecessor binding as provenance;
the next request binds the candidate's own byte hash as its model identity.

## Worker and authoritative native handoff

The standalone worker CLI entry is:

```sh
python -m qualification.hcsn_training.worker --request request.json --output new_result_directory
```

The request binds a stable operation, complete time profile, one outer clock
anchor, model checkpoint bytes, scope, clock epoch, writer epoch, candidate
generation, task inputs/targets, forecast target time, optimizer steps and resource
limits. The requested model digest must equal the base checkpoint's actual byte
hash. Duplicate JSON keys, nonfinite values, unsupported mechanisms, exceeded
limits, disconnected gradients and mutated bases are rejected.

`started.json` reserves one output directory before optimization. A reused output
directory is refused, including after failure. The supplied Linux supervisor
binds the authorized provider key, exact request bytes, job ID and output ID in a
private durable store before launch. Repeated starts only observe that reservation.
Lost replies and partial reservations remain recoverable observations or UNKNOWN;
choosing a new directory is not a recovery protocol. Its identity and process
supervision boundary is documented in [HOST_INTEGRATION.md](HOST_INTEGRATION.md).
It does not claim a cross-host global retry lock.

Success emits `candidate.pt`, `receipt.json`, and `handoff.bin`. The checkpoint
contains safe-loadable model tensors, the SGD configuration, complete final
numerical state and its ending time. The original checkpoint is immutable.
`load_training_checkpoint` returns model, state and metadata; the caller still
checks its own acknowledged identity. SGD here has zero momentum, so there are no
omitted momentum tensors. This is a completed-block candidate, not an in-flight
optimizer-step recovery implementation.

The 439-byte handoff is authoritative for native identity checks. It consists of
the exact `hepta.hcsn.task-bp-handoff.v1\0` magic, a rule byte, eleven 32-byte
digests and seven big-endian u64 fields. The ordered digests are operation ID,
request, training source, runtime tuple, graph, time profile, base checkpoint,
dataset, candidate checkpoint, aggregate gradient record and diagnostic JSON.
The ordered integers are target generation, planned optimizer steps, logical
cells, trainable parameters, completed steps, gradient cells and gradient
parameters.

The native boundary decodes those bytes itself and compares them against the
host's **pre-dispatch** expected binding, the actual candidate/diagnostic bytes,
and the admitted manifest. It does not accept caller-entered outcome fields as a
substitute. The full binary handoff and diagnostic hashes enter artifact lineage.
The diagnostic JSON is hash-bound rather than independently interpreted as a
second native protocol. Neither a hash nor a worker claim proves a derivative;
correct-source execution and independent gradient tests remain necessary.

The receipt records all declared optimization steps, per-cell and per-parameter
gradient norms, and separate connected/nonzero counts. A connected zero derivative
is not relabelled as nonzero learning.
CPU and wall measurements identify their actual observation ranges. Physical
energy is missing, and the diagnostic/handoff publication overhead is not presented
as measured complete campaign cost. No placeholder power or TDP estimate is used.

## Verification

Use the repository's ordinary Rust runner for the affected packages:

```sh
just test --locked -p codex-hepta-neuron -p codex-hepta-learning-artifacts
just test --locked -p codex-hepta-automation
python -m unittest discover -s qualification/hcsn_training -t . -p 'test_*.py' -v
```

The small CPU tests check actual elapsed-time sensitivity, cross-cell and input
finite differences, deliberate detach rejection, immutable base weights, exact
SGD updates, bounded and authenticated checkpoint loading, separate-process
state continuation, and stable output-directory reuse rejection. Native tests
cover time/identity drift, checkpoint anchors, grid alignment, malformed handoffs,
wrong mechanisms, incomplete gradients, actual fenced publication/reopen and
dataset withdrawal between preparation and publication.

`verify_bridge.py` compiles the real native libraries' acceptance executable and
runs Rust planning → separate Python worker → native candidate publication →
fresh-process owner readback → fresh-process state continuation, for either A or B.
With `--supervised`, the actual native process transport launches and reconciles
the actual Python supervisor and worker. A separate native integration test uses
the real signed authority and SQLite store with a labelled supervisor double;
these are distinct coverage boundaries. The fixture uses
signing keys and an isolated store. Its source, binary, dependency, runtime and
raw output identities must remain in the evidence directory. This acceptance is
separate from the original CUDA science matrix and does not spend its identities.

A second training block starts from the published candidate and its complete
clock/state. Two SGD updates, candidate weights and final states are compared
with an independently written autograd calculation; a deliberate zero-state
calculation must differ. This is an explicit alternative training branch from
the candidate anchor, separate from the inference continuation branch. It does
not advance an already-committed inference anchor backwards.

For supervised acceptance, first build all four native packages with the original
lockfile and retain Cargo's successful JSON artifact stream. Pass that stream via
`--cargo-artifacts`; this selects the libraries from that exact build even when
the target directory contains older feature variants. The workflow runs both
backends with separate evidence directories and retains failed/partial outputs.

The archived [2026-11-06 development evidence](evidence/20261106/status.json)
retains both cross-language attempts, their raw files and hashes, the native test
log, independent boundary review, and dated campaign observations. The final
formatted fixture used two logical Cells and all 172 trainable parameters. Its
fresh-process restored output and complete state exactly matched uninterrupted
candidate continuation. Its 8.391-second wall measurement covers that small CPU
fixture, including native executable compilation; it is not a campaign or
production latency measurement.

`HcsnTaskFlowDriver` now implements the existing authorized effect-driver and
lookup ports. Start and cancel use separate signed final-use authorizations;
lookup is observational and never fabricates a proof of absence. The pure clock
commit function still creates successor metadata, while the actual host owns
durable state fencing, adopted model identity and final checkpoint persistence.
The adapter is opt-in and has no automatic production handler registration.

## CUDA and scientific status

The single existing desktop controller is `1a1acdd69f2-fc05-5757`, rooted at
`/data/hcsn-cuda-170run-20261105-r1`. The retained read-only observation on
2026-11-06 at 09:24:50–09:25:17 UTC showed the original controller running its `full`
stage, with 0/170 completed identities registered and global qualification still
open. Zero registered completions does not describe any unregistered in-flight
work. The earlier failed B full-shape observation remains retained. This task
has not started another installer, retry or training campaign.

The original 170 identities, 400 optimizer steps, batch/sequence/hidden width 64,
seeds, B policy gates, failed observations and unknown costs remain unchanged.
Hosted CPU qualification, this bridge's tests, dependency download and candidate
publication cannot substitute for the pending target CPU/CUDA gates, the full
matrix, B convergence audits, physical energy or end-to-end benefit. Keep the
research and integration candidates unactivated until their actual gates pass.
