# Native owner research adapter

This adapter executes bounded local retrieval tasks through the existing native
`codex_hepta_neuron::NeuronRuntime` and the retained first-passage native NDU
bridge. It leaves the original owner algorithms and APIs unchanged. It is a
serial, trusted research runner; production TaskFlow activation is false.

The original source revision is
`71b4305c6619ed9faff98062f0ff7f932f4abfd0`.
`SOURCE_IDENTITY.json` binds the Git blob identities of the 64 original files
used by the isolated build. `owner-Cargo.lock` freezes its Cargo resolution.
The build verifies original source bytes before compiling, records hashes of
all four adapter Rust sources and the executable, and uses the repository's
`just test` entry point. It adds no new registry dependency kinds to the
underlying Hepta crates.

## State and ownership

| Surface | Actual owner and contract |
| --- | --- |
| First-passage diffusion, natural events, reset, refractory phase, random stream | Existing Python `FirstPassageCell`; the full versioned checkpoint payload is retained and hashed |
| Research task clock, read-attempt budget, terminal state | Rust `ExecutionState`; post-I/O state is stored in immutable research task sidecars |
| Sparse model checkpoint, admission journal, independent anchor witness | Existing native `NeuronRuntime`, `SparseJournal`, and `FileAnchorWitnessStore` |
| Candidate selection and recursive utility | Existing retained native NDU bridge; original request and evaluation receipts are retained |
| Bounded source access | Actual native file open/read, at most 65,536 bytes, constrained to the declared task directory |

Every request carries three distinct clocks: a host monotonic timestamp, a
physical event clock in microseconds, and a decision sequence. The original
owner's NDU snapshot digest commits to the NDU receipt, admitted state, full
request and full FPT checkpoint digest. Its admission is durable before the
source read. It does not represent the post-I/O result as already known.

Each later request must match the prior recorded post-I/O task state, native
anchor and FPT predecessor. Full FPT payload checks cover its SHA-256, typed
field set, parameter domain, physical time, event count and refractory phase.
The first selected model is supplied by the trusted Python simulator. Native
continuation additionally compares actual parsed parameter objects from the
previous immutable request, so retaining an old model digest cannot authorize
new drift, diffusion or weights. The native bridge does not independently
recompute the Python model digest from cross-language floating-point JSON.

The observed event list is produced by the existing FPT sampler. Native guards
check event order, window bounds, refractory spacing and checkpoint agreement;
they do not statistically certify the sampler or infer a crossing from a
forecast probability. The initial physical state and observations belong to
the trusted research fixture.

Read cost is charged once when a physical file-open attempt begins, including
an invalid-UTF-8, oversized or failed-read outcome. A path guard rejection
before opening a source consumes no read unit. STOP, cancellation, exhausted
budget and refractory guards run before source access. A completed retry
returns the stored response only when the current native anchor agrees, with
zero additional source reads and zero new charged attempts.

If admission committed but the outcome is missing, the operation remains
indeterminate. Inspection can recover the original native anchor, but retrying
must not repeat an uncertain read. Partial sidecars and inconsistent
predecessors fail closed. This is not a crash-atomic transaction spanning the
owner and filesystem, does not provide concurrent exactly-once execution,
and has not been qualified for directory persistence under power loss.

## Reproduce

From a complete checkout of the pinned repository sources, restore only the
existing native NDU archive; no old scientific trajectories need regeneration:

```bash
python -m experiments.first_passage_cell.evidence.audit_helpers.restore_archives \
  --only experiments/first_passage_cell/evidence/native/hepta-first-passage-ndu.gz
python -m experiments.first_passage_cell.restore_native
```

The retained NDU executable is Linux x86_64 with SHA-256
`83326cf07a435ab3bb5b72075feedf38237d90bcaac80a60d44337c7a9fdf5bf`.
Its original manifest, source identities and every evaluation receipt are
checked by the existing `NativeNduPort`.

Install the repository's Rust 1.96.0 toolchain, `just` and `cargo-nextest`, then
choose writable build and fresh evidence directories:

```bash
FPT_TOOLCHAIN_BIN=/absolute/path/to/rust-1.96.0/bin
FPT_TOOLS_BIN=/absolute/path/to/just-and-nextest/bin
FPT_BUILD=/absolute/path/to/native-owner-build
FPT_EVIDENCE=/absolute/path/to/new-native-execution-evidence

python -m experiments.first_passage_adaptive.native_build \
  --source-root "$PWD" --output "$FPT_BUILD" \
  --toolchain-bin "$FPT_TOOLCHAIN_BIN" --tools-bin "$FPT_TOOLS_BIN"
python -m experiments.first_passage_adaptive.native_execution \
  --owner-build "$FPT_BUILD/NATIVE_BUILD.json" --output "$FPT_EVIDENCE"
```

The Rust source passed nine native tests via `just test`: real commit/recovery,
STOP without sources, cancellation and budget guards, refractory/event clocks,
predecessor rejection, retry and budget continuity, lost-reply inspection,
indeterminate outcome rejection, read-attempt accounting, and physical-model
parameter substitution rejection (some tests cover several related cases).
The original `just fmt` gate and scoped `just fix` gate also passed. These
counts identify the checked finite suite, not a universal correctness claim.

The runner executes seven fixtures and ten mechanistic checks, with 15 actual
native NDU evaluations. They cover answer-then-STOP, budget STOP, cancellation,
initial refractory holding, risk STOP, deadline STOP and a naturally sampled
first-passage event followed by reset, refractory WAIT and subsequent READ.
Each logical tick uses a fresh native process. Each final full FPT checkpoint
is restored in a fresh Python process and compared with an uninterrupted deep
copy of the live cell, including the restored state, next transition and
random-stream continuation. These probes do not resume a terminated task's
actions or enter its reward ledger. Full probe evidence is saved in each
fixture's `EXECUTION.json`.

The checks are mechanical execution and recovery evidence. Fixture rewards
are not a statistical efficacy experiment or evidence of a general Hepta,
SNN, or optimal-control improvement. The native model port executes a frozen
numeric projection, and its broad research calibration bounds are explicitly
uncertified.

## Production work that remains separate

The complete FPT state remains a strongly bound research sidecar. Production
adoption requires an approved canonical FPT owner profile or explicit state
adoption bridge, integration with the authorized product TaskFlow action
owner, real model selection and calibration, and qualification of concurrency,
target-host recovery and durability. The present bounded local reads are real
executions, but they do not activate the product TaskFlow backend or expand its
authority. The adapter reports `production_activation: false` and
`calibration_certified: false` in its receipts.
