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
| Shared BP | Named logical ValueKernel Cells share one PyTorch graph and task MSE; gradients reach earlier cells and time samples | This CPU adapter supports A only. A derivative check is not a scientific quality result. |
| Population B | Rust planner admits only aligned, bounded fixed-grid substeps | No arbitrary-dt B refractory-state migration or B shared-graph worker is claimed. |
| Control graph | One worker request processes every numerical interval internally; one final clock checkpoint per completed coarse block | Ordinary NeuralCircuit/TaskFlow production handler registration remains separate. A compiled control graph is not a tensor tape. |
| Learning semantics | Only `task_mse_bp_v1` can enter this worker; native handoff tags distinguish BP, eligibility and NDU credit | Gradient evidence does not prove NDU gain or independent evaluation. |
| Publication | Native byte/identity checks delegate to the existing fenced `LearningArtifactOwnerService`, withdrawal frontier and immutable payload store | Publication leaves a candidate. Evaluation, selection, deployment and production trust are not granted. |

## Time and state semantics

`HcsnTimeProfileV1` uses integer microseconds in an independently identified
monotonic clock epoch. A numerical interval is `[start, end)`: external input is
sampled on the left, held over the interval, and readout is on the right. The
forecast horizon identifies the task target; it is not elapsed time and does not
replace the learned HX financial maturity.

Each logical cell after the first consumes its predecessor's **previous-boundary
memory** for the interval. All new states commit together at the right boundary.
This explicitly frozen-coefficient scheme is not an exact solution of a coupled
nonlinear ODE, and no resampling-invariance claim follows from its exponential
subupdate.

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
directory is refused, including after failure. A production dispatcher must bind
the operation to that same durable directory/job and query an unknown attempt;
choosing a new directory is not a recovery protocol. The shared worker does not
claim process supervision, timeout cancellation or a global retry lock.

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

The receipt records all declared optimization steps and per-cell gradient norms.
CPU and wall measurements identify their actual observation ranges. Physical
energy is missing, and the diagnostic/handoff publication overhead is not presented
as measured complete campaign cost. No placeholder power or TDP estimate is used.

## Verification

Use the repository's ordinary Rust runner for the affected packages:

```sh
just test --locked -p codex-hepta-neuron -p codex-hepta-learning-artifacts
python -m unittest qualification.hcsn_training.test_joint_graph -v
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
fresh-process owner readback → fresh-process state continuation. It uses fixture
signing keys and an isolated store. Its source, binary, dependency, runtime and
raw output identities must remain in the evidence directory. This acceptance is
separate from the original CUDA science matrix and does not spend its identities.

The archived [2026-11-06 development evidence](evidence/20261106/status.json)
retains both cross-language attempts, their raw files and hashes, the native test
log, independent boundary review, and dated campaign observations. The final
formatted fixture used two logical Cells and all 172 trainable parameters. Its
fresh-process restored output and complete state exactly matched uninterrupted
candidate continuation. Its 8.391-second wall measurement covers that small CPU
fixture, including native executable compilation; it is not a campaign or
production latency measurement.

The framework already has reusable authorized TaskFlow effect-driver and lookup
ports. This bridge does not register an HCSN production implementation of those
ports. The pure clock commit function creates successor metadata; the actual
host still owns durable fencing, job identity, unknown-outcome lookup and final
checkpoint persistence. A worker output-directory guard alone does not provide
global at-most-once execution.

## CUDA and scientific status

The single existing desktop controller is `1a1acdd69f2-fc05-5757`, rooted at
`/data/hcsn-cuda-170run-20261105-r1`. The read-only observation on 2026-11-06
07:44:50 UTC still showed `waiting_for_pinned_runtime`, `stages=[]`, and 0/170.
The completed download had failed before pip installation because a suffix-only
wheel metadata selector counted setuptools' vendored distributions as top-level
metadata. Another existing repair owner is addressing that environment; this
bridge task did not start a second installer or training campaign.

The original 170 identities, 400 optimizer steps, batch/sequence/hidden width 64,
seeds, B policy gates, failed observations and unknown costs remain unchanged.
Hosted CPU qualification, this bridge's tests, dependency download and candidate
publication cannot substitute for the pending target CPU/CUDA gates, the full
matrix, B convergence audits, physical energy or end-to-end benefit. Keep the
research and integration candidates unactivated until their actual gates pass.
