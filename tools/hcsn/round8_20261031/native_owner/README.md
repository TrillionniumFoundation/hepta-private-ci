# Round 8 native finite-cell owner

## Recovered delivery and full content-cost qualification

The current delivery index is `DELIVERY_MANIFEST_CURRENT.json`; the unchanged
`DELIVERY_MANIFEST.json` is the superseded `456a` release record. See
`REVALIDATION_20261031.md` for the fresh source build, nine Rust tests, repeated
numerical qualification and the new actual-file/FullHX content-cost experiment.
The new experiment preserves one decode per public endpoint for both schedules,
includes content output durability and restart, and retains the ordinary
event-aware baseline. The analytic Rust source and its build digest are unchanged.
Public endpoints schedule decoder calls; native signals do not gate that content
work. Restarts replace the native child and reconstruct the ContentAdapter while
the Python host loop remains alive. The content report's `passed` field validates
equivalence and call counts; CPU reduction is a separate measured outcome.

This package implements a Rust owner for physical cell state and the actual
`codex_hepta_neuron::NeuronRuntime`. It advances the cell in Rust, executes the
physical query and fixed readout inside `NeuronModelPort::execute`, consumes
those outputs in the native sparse runtime, and durably pairs the native
checkpoint with the complete physical state. No production interface or frozen
bridge is changed. Every native receipt retains `DENY_ALL` and
`production_activation=false`.

The frozen main implementation is pinned to
`732e934ba496d90fbe042b8d41d479ef901643e5`; `SOURCE_IDENTITY.json` records the
Git blob identities of all 60 source/manifest files used by the three native
crates. The finite physical law follows
`e67a5e13ba82768a25858153452c15e76670b641`,
`tools/hcsn/task_value_factorial_20261030/{cells,propagation}.py`.

## What is implemented

The analytic family is an explicitly declared five-state continuous-time
Markov chain: three active spatial states, an upper firing transition, two
Erlang refractory phases, and a reset mixture. Its lower boundary reflects.
The generator depends on the bounded driver and six bounded coefficients.
Distribution propagation uses positive uniformization of an augmented
generator, including the expected number of repeated firing events. A separate
killed generator supplies the probability of at least one future firing. Its
firing flux enters a positive absorbing accumulator, avoiding subtraction of
nearly equal survival probabilities. Uniformization uses absolute and
accumulator-relative truncation criteria, with geometric Poisson remainder
estimates for the declared nonnegative finite kernel in exact arithmetic.
Those estimates do **not** certify accumulated floating-point error across
parts. Qualification compares the result with independent SciPy matrix
exponentials and short-time integral Taylor series.

The sampled family draws the same finite Markov law using an explicitly named
SplitMix64 simulation stream with open-interval, 52-bit midpoint uniforms.
It preserves the remaining integrated exponential hazard when an interval is
split or the driver changes. Querying the future is read-only and consumes no
random draws. A task reset occurs after the interval and resets the active
mixture and hazard; it is distinct from a latent firing and its refractory
recovery. This RNG contract is deliberately distinct from NumPy PCG64.

The ordinary comparator advances two elapsed-time gates in closed form.
It receives the same public driver, duration, query horizon, task resets,
endpoint observations, native runtime, durable records and restart obligation.
Both event-aware and dense versions are executed for all three families.

The fixture contains eleven fixed coefficients: six physical/gate coefficients
and a five-coefficient sigmoid readout of four physical features. These are
numerical qualification parameters, not newly trained task weights. The native
signal is the actual runtime's width-five, top-one Q24 output from these five
features. The new calibrated task-value head in the sibling research track is
not connected to this owner, and no task-utility claim follows from this
fixture.

Scheduling occurs at public input/observation boundaries. Within a sampled
interval the Rust kernel visits every latent Markov jump and returns its time
and state change. Distribution propagation integrates those events. This
experiment does not require native commits or external actions at each latent
jump. Skipping intermediate commits is valid for the registered piecewise
constant inputs and endpoint obligations; tasks requiring observations or
external actions inside an interval need an additional scheduling contract.

## Durable state and recovery

`cell.rs` snapshots the model identity, family, logical sequence, elapsed
microseconds, probability vector, ordinary gates, cumulative event count,
sampled state, RNG state/draw count and remaining hazard. Floating-point values
are stored as canonical hexadecimal binary64 bits. Model identity binds the
declared law, family and all eleven coefficient bit patterns.

`owner.rs` pairs that snapshot with the real native checkpoint and the complete
native/research source digest. On restart the caller supplies its previously
acknowledged pair digest. The owner verifies the pair, model/source identity,
native witness frontier and native journal recovery before accepting another
interval. The witness and journal use the real runtime's exclusive-owner
behavior. Invalid input or stale sequence is rejected before physical/RNG
publication and journal mutation.

A step commits the actual native journal/witness, writes and syncs a temporary
physical checkpoint, renames it, and syncs its directory. Any failure after the
native commit poisons the current owner. A restart with an older acknowledged
pair rejects a mismatched native suffix. This is detection and fail-closed
recovery, **not** a claim of atomic two-file commit or automatic repair after
every crash. A filesystem containing a newer physical pair also requires the
matching externally acknowledged digest.

The research envelope is finite: coefficients in `[-3,3]`, driver in `[-1,1]`,
positive owner durations/query horizons up to 128 seconds, at most 1,024 owner
commits, a clock and RNG draw-count envelope of `2^52`, and a bounded latent
event loop. Failed state validation leaves the physical candidate unpublished.

## Verification and measured result

The release source digest is
`58c5acd47498d5536293ae8223ed1b28ae8f87a21efd0467c801e46f4298d89b`.
The release binary SHA-256 is
`6cfe7b61662d5c74272594bfc5de0b0aaa2f9cb9b1df3c5ca7dabef7e6298109`.
`evidence/BUILD_RELEASE_TAILFIX.json` and
`evidence/qualification-release-tailfix/REPORT.json`
are the authoritative build and qualification records. Earlier attempts and
their source identities remain available; results below use only the release.

All nine current-source Rust tests pass. They exercise rare first-hit tails,
retained hazard under interval splitting, bit-exact restart continuation, read-only queries,
distribution/ordinary semigroups, actual native recovery and signals,
precommit rejection, acknowledged-state corruption/native loss, interruption
between commits, model binding and exclusive ownership.

The independent qualification uses four registered seeds, three cell families,
twelve two-second public intervals, two task resets, and one actual process
restart per run. Dense execution subdivides every public interval into sixteen
native commits; event-aware execution performs one. All twelve paired
family/seed comparisons have matching endpoint native signals, physical
features within the `2e-10` tolerance, and matching sampled jump histories
within the registered time tolerance. The largest independent reference
feature/state error is `1.942890293094024e-15`; the largest event-count error is
`5.329070518200751e-15`, and the largest probability-mass error is
`3.885780586188048e-15`.

These checks cover the fixed coefficient fixture and registered schedules;
accepting bounded inputs does not certify numerical accuracy throughout the
whole parameter envelope. An additional tail check covers all five initial
states at 1 and 10 microseconds and compares the positive-flux computation with
an independent six-term integral Taylor series, formed by finite powers of the
killed generator rather than an exponential or survival subtraction. The
maximum relative difference over those ten cases is
`4.3298697960381105e-15`, against a registered `1e-12` tolerance. All five
0.75-second probes also agree with both independent exponential flux and the
well-resolved survival formula. The checks and analytic Taylor truncation
bounds are retained in `TAIL_CHECK.json`; the bounds exclude floating-point
coefficient and arithmetic errors.

| Initial active state 0 | Old `1 - survival` | New positive flux | Independent Taylor series |
|---|---:|---:|---:|
| 1 microsecond | 0 | 1.513661543302131e-19 | 1.5136615433021308e-19 |
| 10 microseconds | 1.1102230246251565e-16 | 1.5136504124978502e-16 | 1.51365041249785e-16 |

The accumulator-relative criterion is applied only after a nonzero flux has
appeared, preventing truncation before its first reachable path. Each state in
this declared model can reach a firing. The physical query preserves these
small binary64 values, but the native Q24 feature channel rounds probabilities
below half of one Q24 unit to zero. This is a numerical-kernel improvement,
not evidence that the sparse output communicates arbitrarily small tails.
There is no whole-envelope relative-tail or floating-point error certificate.

A separate 20,000-seed pure-physics ensemble passes the registered six-standard-
error distribution and repeated-event-count gates. It is explicitly marked
`native_owner_used=false`; it supports numerical sampling validation and is
not counted as native integration evidence.

The following means cover the whole twelve-interval execution, including one
restart, and use four seeds per row. They are debug-build measurements from
one host, not a stable ranking of implementations.

| Cell | Schedule | Native commits | Full CPU seconds | Wall seconds | Serialized durable record bytes |
|---|---|---:|---:|---:|---:|
| Ordinary gates | Event-aware | 12 | 0.014354 | 0.025832 | 14,123 |
| Ordinary gates | Dense | 192 | 0.170787 | 0.337711 | 226,174 |
| Distribution | Event-aware | 12 | 0.015567 | 0.027942 | 14,171 |
| Distribution | Dense | 192 | 0.186535 | 0.367849 | 226,942 |
| Sampled | Event-aware | 12 | 0.015879 | 0.026853 | 14,122.25 |
| Sampled | Dense | 192 | 0.179586 | 0.353653 | 226,154.25 |

The cost loop excludes the SciPy oracle and includes Python client CPU plus
actual child user/system CPU from `wait4`: process startup, model parsing,
physical propagation/query/readout, native signal generation, IPC, native
journal and witness writes, physical checkpoint publication, receipt
retention, restart and shutdown. Wall time includes the actual sync calls.
Durable byte counts are serialized application-record bytes, not filesystem
write amplification or physical storage traffic. The port's fixed allocation
and resident-byte declarations are research envelope inputs; they are not
measurements of total process memory.

These measurements establish fewer complete native executions when empty
ticks are omitted under the stated observation contract. The ordinary
event-aware baseline receives the same benefit. They do not establish an
intrinsic analytic-cell advantage, physical energy savings, better task
decisions, continuum accuracy, or a production-qualified runtime.

## Build provenance and reproduction

### Fresh checkout, without the previous session's build directory

`bootstrap.py` prepares all required harness inputs from a pinned source checkout
and the unchanged bridge build helper already present in base
`3a0e62c61b595576f16313c9b6016ec62cf8088b`. It verifies every upstream Git blob,
copies the owner's recovered frozen lock, and records `BOOTSTRAP.json`. It neither downloads nor
compiles dependencies. Fresh input preparation has been executed and recorded in
`evidence/BOOTSTRAP_REVALIDATION_20261031.json`; a clean Cargo build is a separate
gate, not implied by that receipt.

For a fresh checkout, create the source worktree at the exact upstream commit,
then run the following with actual new paths. Rust 1.96.0, genuine `just` and
`cargo-nextest` executables are required by this harness. The source worktree
also provides its unchanged `codex-rs/justfile` and test scripts.

```bash
git -C /path/to/research-checkout worktree add --detach \
  /path/to/pinned-main 732e934ba496d90fbe042b8d41d479ef901643e5
python tools/hcsn/round8_20261031/native_owner/bootstrap.py \
  --source-root /path/to/pinned-main \
  --existing-build /path/to/new-native-inputs \
  --cargo-cache /path/to/genuine-cargo-cache
CARGO_HOME=/path/to/new-native-inputs/cargo-home \
  /path/to/rust-1.96/bin/cargo fetch --locked \
  --manifest-path /path/to/new-native-inputs/Cargo.toml
python tools/hcsn/round8_20261031/native_owner/build.py \
  --build /path/to/new-native-owner-build \
  --existing-build /path/to/new-native-inputs \
  --workflow /path/to/pinned-main/codex-rs \
  --toolchain /path/to/rust-1.96 \
  --tools /path/to/genuine-just-and-nextest \
  --report /path/to/new-native-build-report.json
```

Cargo verifies and downloads authentic locked archives under the configured
network policy. Offline reproduction needs those archives already available.
The base bridge lock does not identify this owner's tested dependencies. Its
historical versions differ from the owner's successful Cargo build. The exact
owner lock is restored byte-for-byte from `BUILD_ATTEMPT_05.json` into
`native-Cargo.lock`, with SHA-256
`6bbac28b4ea02636d97d28db3ede87a2fe096e764f5434395b755180505e15bf`.
The initial mismatch check is retained in
`evidence/BOOTSTRAP_REVALIDATION_ATTEMPT01.json` and the recovery in
`evidence/NATIVE_LOCK_RECOVERY.json`.
`build.py` now uses this pinned lock directly with `--locked`; the former
unnecessary `generate-lockfile` step has been removed to avoid transitive
dependency re-resolution. The owner lock is copied without changing its bytes.
The prior helper is preserved in `evidence/source-tailfix-original/build.py`.
This build-helper correction does not change the frozen Rust source digest.

The new content runner is `qualify_content.py`. `CONTENT_SOURCE_IDENTITY.json`
lists all six content dependencies with path, Git blob, SHA-256 and their
unchanged relationship to the pinned base. The FullHX checkpoint and table are
already in that base; there are no additional downloaded content weights.

`build.py` verifies all 60 upstream Git blob identities and compiles an isolated
harness without editing the production workspace. With the locked registry
archives available, it runs Cargo offline and then the repository's actual
`just test`/nextest workflow. `BUILD_ATTEMPT_05.json` retains a successful
Cargo build and all eight tests under that workflow.

Afterward, disk recovery removed cached registry archives while leaving the
extracted sources and compiled target intact. Cargo's later offline rebuild
therefore failed; `BUILD_FINAL.json` retains that failure. No vendor checksums
were invented and no fresh registry-archive verification is claimed.

The release uses `direct_build.py`: it verifies the same 60 upstream files,
requires the preserved Cargo binary to match the successful prior report,
matches its direct dependency fingerprints, hashes every available rlib,
rmeta and proc-macro shared object, compiles the exact current sources with
the same Rust 1.96.0 compiler, runs all nine newly compiled Rust tests, and
verifies dependency artifacts did not change during compilation. The actual
repository `just fmt` was rerun on the final Rust sources. The release test
execution is explicitly a direct-rustc test run; it is not described as a new
Cargo/just gate. The complete numerical qualification was then rerun against
that exact release binary. The earlier `456a78fe...` release remains a history
entry; its exact five Rust and four Python files are preserved under
`evidence/source-release-456a` against their recorded hashes. Its measurements
are not substituted for the final tail-fix measurements.

Example using the preserved session build inputs:

```bash
python tools/hcsn/round8_20261031/native_owner/direct_build.py \
  --build /tmp/hepta-r8-native-owner-tailfix \
  --existing-build /tmp/hepta-native-task-v2-c135db76929c/build \
  --toolchain /tmp/pq-r3-rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu \
  --prior-report tools/hcsn/round8_20261031/native_owner/evidence/BUILD_ATTEMPT_05.json \
  --prior-fingerprint /tmp/hepta-native-task-v2-c135db76929c/build/target/debug/.fingerprint/codex-native-event-owner-r8-a4d96abc5f2365f4/bin-codex-native-event-owner-r8.json \
  --report /tmp/native-rebuild-report.json
OPENBLAS_NUM_THREADS=1 python tools/hcsn/round8_20261031/native_owner/qualify.py \
  --binary /tmp/hepta-r8-native-owner-tailfix/native-owner-final \
  --out /tmp/native-new-qualification \
  --build-sha 58c5acd47498d5536293ae8223ed1b28ae8f87a21efd0467c801e46f4298d89b
```

For a fresh environment, materialize the pinned sources and locked Cargo
dependencies and use `build.py`; the direct fallback requires the preserved
Cargo artifacts, not just this repository's source files. Raw requests,
receipts, model fixtures, public schedules, physical checkpoints and actual
native journal/witness files accompany each qualification. Python versions and
qualification source hashes for the fresh rerun are recorded in
`evidence/EXECUTION_CONTEXT_REVALIDATION_20261031.json`.
The recovered tail-fix context explicitly identifies the absence of a
contemporaneous Python environment capture; no historical version record was
invented. `evidence/RAW_NATIVE_EVIDENCE_TAILFIX.tar.gz` contains the final
historical tail-fix run. `evidence/RAW_NATIVE_EVIDENCE.tar.gz` retains the three
earlier runs and the previous release's exact source snapshot;
member paths are relative to `native_owner/evidence` and are individually
hashed in their corresponding raw-record manifests. The release and prior-run
`REPORT.json`, `PROTOCOL.json`, `ENSEMBLE.json` and final `TAIL_CHECK.json` can
also be read directly.

This finite CTMC implementation does not establish the continuum He-Xiong
solution, the assumptions of a Hölder-space Q-learning theorem, or a new
multilayer SNN. Boundary/reset/refractory behavior is explicitly implemented
and tested under its own declared finite contract.
