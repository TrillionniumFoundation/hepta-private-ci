# Analytic event runtime and original Hepta integration

This experiment has two executable owners. `runtime.py` persists a recurrent
stochastic pulse cell and its receipt ledger. `native_head.rs` implements the
original `NeuronModelPort` trait and executes the original `NeuronRuntime`,
`SparseJournal`, and independent `FileAnchorWitnessStore`. The latter is a local
research owner, not an Agentd dispatch owner. Neither owner grants selection,
promotion, delivery, or other effect authority.

The trained filter/readout, the pulse cell, the native probability head, and the
legacy runtime confidence are separate objects. A successful port integration
does not establish a calibration result or a policy improvement. The task
experiment evaluates those claims separately.

## 1. Event, observation, and time contract

`EventRuntime.step` takes a conditional Gaussian mean and variance supplied by
its caller, a physical conditioning `timestamp`, and an explicit
`target_timestamp`. The latter defaults to the conditioning time: that default
means a simultaneous posterior, not an unspecified future forecast. To consume
a forecast at time `t + h`, pass `timestamp=t, target_timestamp=t+h` and the
already propagated mean and variance at that target. This owner does not infer a
drift or propagate a supplied distribution on its own.

The three mutually exclusive events are, in array order:

| Channel | Event at the declared target |
| --- | --- |
| put | `X_target <= lower` |
| neutral | `lower < X_target <= upper` |
| call | `X_target > upper` |

The ordering also defines largest-remainder quantization tie resolution. At
positive variance, boundary mass is zero. At zero variance, the inequalities
above determine the exact deterministic category. These are terminal state
probabilities under the caller's conditional law. They are neither discounted
prices nor first-passage probabilities. No financial risk-neutral assumption is
introduced by the runtime.

`input_digest` binds the conditioning information, including any measurement
mask or upstream history. Each receipt carries that digest, the mean, variance,
two thresholds, conditioning time, target time, observation kind, and event
semantics. The owner validates scalar domain and identity; the caller remains
responsible for supplying the claimed conditioning information and for binding
`model_digest` to the actual frozen trained artifact.

Physical time is nonnegative and nondecreasing. Logical sequence starts at one
and advances exactly once per accepted tick. Thus a repair measurement can have
the same physical time as the previous measurement while remaining a distinct
logical tick. Target time cannot precede conditioning time.

`observation_kind="observed"` denotes a posterior conditioned on an available
measurement. `"prediction_only"` denotes a tick without a new measurement, using
the explicitly propagated conditional distribution. A raw `"missing"` label is
rejected; it cannot silently become a neutral event. A missing observation, a
sampled neutral category, and zero emitted pulse are three different facts.

The trained pulse feature path in `learners.py` uses the simultaneous posterior
after each occupied history tick. On a masked tick the filter propagates time
without a measurement update, and the pulse still samples that conditional
posterior. Forecast readouts subsequently predict the registered future
horizons from the resulting recurrent state.

## 2. Recurrent pulse semantics

The shared pure functions are `pulse_initial_state`, `pulse_transition`,
`pulse_features`, and `counter_uniform`. Training imports these functions;
durable execution uses the same transition.

For a sampled category `s in {-1,0,+1}` at a logical tick, the default cell uses

```
h_candidate = 0.65 * h_previous + s
eligibility = 0.8 * eligibility_previous + s
```

If the cell is not refractory and `abs(h_candidate) >= 1.25`, it emits the sign
of `h_candidate` and resets potential to zero. Otherwise it emits zero and
retains the candidate potential. A refractory counter suppresses emission while
potential and eligibility still integrate. A firing tick installs the configured
refractory duration; subsequent refractory ticks decrement it. The default
duration is zero. These decays are per logical observation tick, not continuous
time decay rates.

The state holds potential, eligibility, upper and lower emitted counts, age
since the last emission, last emitted sign, refractory counter, and steps.
Every public pure transition validates finite continuous state, nonnegative
integer counters, count/age bounds, and valid emitted sign. Eligibility here is
a trace of sampled evidence; it is not presented as a parameter gradient.

For `n=max(steps,1)`, the eight readout features are:

```
[potential, eligibility, upper_count/n, lower_count/n,
 age/n, last_output, (upper_count+lower_count)/n, 1]
```

Two preregistered mechanism controls share this state and feature interface.
`mode="mean_drive"` substitutes `p_call-p_put` for the categorical draw while
retaining the threshold, emission counts, and reset rule. It is a deterministic
drive control, not the exact expectation of a nonlinear random reset process.
`reset_enabled=False` retains potential after threshold emission. Default
durable execution is `mode="sample", reset_enabled=True`; changing either is a
configuration identity change, not a silent migration.

### Counter RNG

The random mark is derived from SHA256 of the domain prefix
`hepta.aen.rng.v1\0` followed by canonical JSON `[seed, trajectory_id, tick]`.
The high 53 bits of the first eight digest bytes are divided by `2**53`.
This produces an exactly reproducible mark in `[0,1)`, independent of execution
order or array batching. It supplies a numerical random stream, not a security
or independent entropy guarantee. The learning code preserves the base
trajectory identity when appending repair/wait stage suffixes, so an already
observed prefix retains its random marks.

The owner binds the RNG seed and counter together with model, dataset, subject,
generation, complete configuration, event time, request digest, predecessor
checkpoint, and recurrent state. Two configurations can deliberately use common
random numbers while still having different checkpoint identities.

## 3. Durable Python owner

`EventRuntime(directory, config)` requires SHA256 model/dataset identities,
subject identity, positive generation, seed, and ordered finite event thresholds.
The format is `hepta.analytic-event.pulse-owner.v1`; the complete configuration
is part of its identity. The bounded ledger defaults to at most 4096 ticks.

One transaction contains the next state, RNG counter, logical and physical
clock, checkpoint digest, and complete tick receipt. The owner serializes to a
temporary file in the same directory, flushes and fsyncs it, atomically replaces
the checkpoint, and fsyncs the directory on POSIX. An advisory file lock
serializes cooperating owners. A receipt is returned only after that commit.
The `fail_after_commit` test hook loses the acknowledgement after the durable
write; retrying returns the already stored receipt.

An exact duplicate tick ID and request returns its original receipt without
advancing state or RNG, even if later ticks already exist. A changed payload,
including a changed prediction target, under an existing ID is rejected.
Nonduplicate transitions require the next logical sequence, nonregressing
physical time, and—when supplied—an exact caller-held `expected_checkpoint`.

The checkpoint checksum detects accidental modification. It is not a signature,
and a writer who can replace all owner files can forge a new checksum or restore
an older valid file. Caller-held anchors detect rollback relative to an
acknowledged checkpoint; a checksum alone cannot do that. The native owner adds
an independently retained durable witness. Neither mechanism claims security
against an actor who can replace both journal and all independent anchors.

The implementation rewrites the bounded Python ledger on every tick, so total
write volume grows quadratically with the number of retained receipts. This is
a transparent, inspectable prototype, not a throughput claim. The Python
receipt's `compute_ns_before_commit` excludes fsync, while the external owner
wall time must include commit cost. POSIX durability and restart were exercised;
the Windows locking branch is not qualified by this Linux run.

## 4. Original sparse history baseline

`Native.sparse_features(observations, times, mask, case, obs_var=...)` uses one
persistent JSON-lines Rust process. It does not start a process per tick and
does not reimplement `sparse_tick` in Python. Every occupied history position
executes the original pinned Rust function, with state carried to the next
position. It returns the original final ten activations plus ten eligibility
values, divided by `2**24`, as the 20 readout features. No target or hidden state
is accepted by the native history API.

The frozen ten-channel drive is:

| Index | Public input before clipping and Q24 conversion |
| --- | --- |
| 0, 1 | positive and negative parts of observed value |
| 2 | physical time since the previous history tick |
| 3 | observation mask |
| 4 | constant `1/4` |
| 5, 6 | positive and negative change from the last observed value |
| 7 | logical index, starting at one, divided by fixed capacity scale eight |
| 8 | absolute observed value |
| 9 | public measurement variance |

A masked value contributes zero to value and delta channels, while time, mask,
index, constant, and the known measurement variance remain explicit. It does
not update the previous observed value. Components are clipped to `[-8,8]` and
rounded ties-to-even into Q24. The public history domain permits 1–128 ticks,
finite values, nonnegative finite measurement variance, and nondecreasing
physical times in `[0,1_000_000]`. Default measurement variance is `0.64` only
for backward compatibility; the experiment always passes actual public values.

The fixed index scale avoids changing historical drives when new observations
are appended. Every original input digest binds that tick's history prefix,
including reliability and masks. Prefix checkpoint identities therefore remain
unchanged after appending a same-time repair. Logical microseconds are physical
microseconds plus the one-based tick index, ensuring strict native ordering
even for equal physical times.

The original width-ten, top-two sparse configuration is retained from the
existing feedback probe: temporal decay `3/4`, inhibition gain `1/4`, the same
two inhibitory edges, adaptive activity thresholds, and eligibility decay
`1/2`. This deliberately retains the original mechanism's inductive bias and
compression. Its features are not probability estimates, and a learned readout
is required for the task. The `tick_pair` endpoint also preserves the original
feedback-probe request semantics and exact semantic receipts.

## 5. Actual typed analytic head and journal

`Native.typed(case, directory, mean, variance, lower, upper,
expected_checkpoint=...)` is a local integration exercise:

```
NeuronTickInputV1 -> NeuronModelPort::execute
                 -> NeuronRuntime::tick
                 -> SparseJournal::commit
                 -> FileAnchorWitnessStore::compare_and_swap
```

The new trait implementation executes an actual analytic Gaussian head through
Linux libm `erfc`, conserves the three-event Q24 mass, and places the resulting
probabilities into the first three drive channels. Original Rust code performs
the sparse state update, checkpoint commit, witness commit, model-binding
validation, resource receipt, and abstention behavior. The model receipt binds
the adapter source tuple, compiler identity, numeric encoder, analytic head,
normalization, and platform identity. The outer Python adapter also verifies the
actual executable's SHA256 against the fresh-build receipt before launching it.

This typed numeric adapter has fixed analytic constants; it does not claim to
contain the experiment's trained filter or readout weights. Mean and variance
are its actual numeric inputs. It also uses synthetic logical microseconds for
the port exercise, not the task's physical prediction horizon. The full
conditioning/target time contract resides in the upstream task and Python
owner. Deploying that complete trained path through an Agentd owner requires
an additional owner adapter and explicit state/version migration review.

All four input parameters must be finite within `[-8,8]`; variance is zero or
at least `2**-24`, and at most eight. Input parameters themselves are rounded
ties-to-even to Q24. Distinct thresholds that collapse after this conversion
are rejected. The output reports both original FP64 parameters and decoded Q24
parameters, allowing input-quantization error and output-probability
quantization error to be measured separately. Positive variance below the
supported range is explicitly rejected rather than silently becoming an atom.

The probability head is distinct from the original runtime's
`confidence_ppm`. No empirical calibration or OOD artifact has been fitted for
that legacy confidence calculation. The adapter therefore uses a deliberately
unqualified profile whose validity starts at sequence 1025, outside this
1024-record owner lifetime. Required legacy `measured_*` fields contain the
conservative unknown upper bound of one million ppm; they are explicitly
labelled as unknown bounds, not measurements. Every executed output is checked
to abstain, report zero legacy confidence, and retain `DENY_ALL`. An analytic
probability of 0.9 consequently cannot become a fabricated 90% calibrated
success confidence.

The original journal and independent witness are recovered from disk for each
typed request. The optional caller checkpoint is passed into the original
runtime's CAS check. Unlike the Python receipt ledger, this low-level endpoint
does not promise automatic request-ID deduplication; a stale checkpoint rejects
instead of appending. Separate-process restart, stale CAS, wrong subject scope,
and acknowledged journal rollback were exercised. Original crate tests also
exercise the existing journal/witness failure paths. Rollover exists in the
original implementation, but this experimental endpoint stops at one bounded
1024-record segment.

The model receipt measures process RSS from `/proc/self/status` and head
execution time; allocation bytes explicitly cover output vector capacity only.
They do not purport to be a whole-process peak allocator measurement. The typed
result separately records total tick wall time, original journal bytes written,
checkpoint bytes, and witness/journal file sizes. Process and libm/platform
qualification in this run is Linux x86_64; other backends remain unqualified.

## 6. Source identity, build, and validation

The build uses original source commit
`0acfd9b27db910c180b0d8911f39aea469b7f864` of
`TrillionniumFoundation/hepta-private-ci`. Each of the 83 files from
`hepta-types`, `hepta-infer-core`, and `hepta-neuron` was checked against the
remote Git blob SHA in `NATIVE_SOURCE_MANIFEST.json`. Those production files and
their Cargo manifests are unmodified. The full original `codex-rs/Cargo.lock`
constrains the exact name/version/source/checksum tuple of every resolved
external dependency.

`prepare_native.py` requires a fresh build directory. It creates an isolated
workspace with exact dependency versions, uses offline vendored sources, runs
the local `just fmt`, `just build`, and `just test` recipes, and hashes sources,
compiler/tools, lockfiles, logs, executable, and the independently compiled old
feedback adapter. No unknown precompiled `rlib` is imported. Debug info and
incremental compilation are disabled in the isolated development profile to
bound scratch disk use; production manifests and profiles remain unchanged.

Example reproduction, with tool and vendor locations supplied by the caller:

```sh
python -m experiments.analytic_event_neuron.prepare_native \
  --destination /tmp/aen-fresh-build \
  --cargo /path/to/cargo --rustc /path/to/rustc \
  --rustfmt /path/to/rustfmt --just /path/to/just \
  --vendor /path/to/lock-matching-vendor

python -m experiments.analytic_event_neuron.validate_runtime \
  --native-binary /tmp/aen-fresh-build/target/release/examples/analytic_event \
  --native-receipt /tmp/aen-fresh-build/BUILD_RECEIPT.json \
  --output /tmp/aen-runtime-validation
```

The final qualification build is v6, executable SHA256
`b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179`.
`evidence/native/BUILD_RECEIPT.json` preserves its original commands, paths, and
tool/source identities. Copies of the two executables, build/test/format logs,
isolated Cargo files, and justfile are retained beside that receipt.

Observed results from the final runtime audit:

| Check | Result |
| --- | --- |
| Original three-crate test suite | 170 passed, one explicitly ignored real-filesystem long-history benchmark |
| Runtime integration assertions | 147 passed |
| Original feedback-adapter semantic parity | All ten sign/reset cases matched complete semantic tick receipts |
| Native erfc vs independent SciPy probability reference | Maximum absolute error `1.3878e-16`, 88 cases |
| Native probability output Q24 error | Maximum absolute error `3.6552e-8` at quantized parameters |
| Parameter Q24 error in that separate fixture | Maximum probability change `1.9115e-8`; not a global bound |
| Python simplex Q24 conversion | Exact mass, maximum error `3.9272e-8`, 2000 distributions |
| Pure recurrence | Finite at 4096 steps; not a multi-day retention claim |

`evidence/runtime/RUNTIME_VALIDATION.json` contains the per-check results.
`TYPED_SAMPLES.json`, `NATIVE_HISTORY_SAMPLE.json`, the Python checkpoint, and
actual native journal/witness files retain raw evidence. The audit includes
restart and lost-ack parity, historical duplicate idempotence, changed payload
and target rejection, seed/subject/model/dataset/generation mismatch, physical
clock and sequence rules, explicit simultaneous/future targets, prediction-only
missing ticks, reset/refractory behavior, state corruption, caller-anchored
rollback, bounded capacity, original native CAS, and separate-process recovery.

Calibration quality, low-bit generalization, high-load latency, multi-day
retention, adversarial filesystem ownership, production Agentd integration,
and cross-platform recovery require their own evidence. The present artifacts
make those remaining limits inspectable instead of assigning them a pass from
the algebra or from a successful trait call.
