# R9 native content and physical owner

R9 moves the frozen FullHX decoder into the same Rust process and acknowledged
checkpoint as the R8 physical cell and real `NeuronRuntime`. Packet reads,
feature construction, FullHX recurrence, ridge solve, physical propagation,
readout and publication run in Rust. Python supplies public requests and
measures the process; its decoder is only an independent offline oracle.

This closes the **unified owner and acknowledged process recovery** gate for
the registered finite task. It does **not** close the separate gate that a
learned probability boundary autonomously reduces content calls.

## Source and owned state

The experiment initially used base `333fb9b036b80cf5d892aed222a1aac7aad80e53`,
which did not contain the R8 native owner. The recovered source was subsequently
published in `00b94d54a9b85f285298d1a964777bdecfa85385`. `SOURCE_IMPORT.json`
records all eight original files, verified byte-for-byte against Git blob
identities at that published commit. R9 leaves frozen production crates and
R8 sources/evidence unchanged.

The physical law remains the R8 five-state finite chain, two refractory
phases, reset mixture, positive first-passage accumulator and persistent
sampled hazard/RNG. This is not a new continuum solver. The content model is
the inherited width-62, key-width-16 FullHX model, using binary32 recurrence
and the same binary32 Hermite gate table as NumPy, with a binary64 Cholesky
ridge solve. No native model retraining is claimed.

The v2 paired checkpoint contains physical state, native checkpoint/source
identity, content model identity, completed read count and last output, with
exact binary32 logit bits and the actual packet digest. Native input binding
includes content state. A packet is a bounded regular file, opened without
following symlinks, validated and decoded before any interval commit.

Missing packets, changed packet digests and stale acknowledgements leave the
journal, witness and paired checkpoint byte-identical. Corrupted content
state and changed model digests fail recovery. Publication retains R8's
fail-closed handling of interruption between the native commit and paired
checkpoint; arbitrary-crash atomicity and automatic repair are not claimed.
R8 v1 checkpoints are not silently migrated. Each packet starts a fresh
FullHX recurrence, exactly as in the original adapter; completed outputs
survive restart, but partial-token resumption is not implemented.

## Verification

`evidence/BUILD_FINAL.json` is the canonical current-source build. It verifies
60 upstream Git blobs, preserved Cargo dependency artifacts and the matching
compiler, then compiles current sources with Rust 1.96.0 at optimization
level 2. This is a cached-artifact `rustc` rebuild, not a clean Cargo build.

`evidence/NEXTEST_FINAL.json` records **11/11 tests** through the original
repository `just test`/`run-nextest.py` entry point and genuine nextest, using
explicit reuse metadata for the newly compiled test binary. The original
`just fmt` also passed in an isolated copy of the unchanged workflow.

`evidence/qualification-final/REPORT.json` contains 48 runs: three families,
four seeds, two schedules, and continuous versus restarted execution. A
restart closes and waits for the **entire Rust process**, then launches a new
one using only its model and acknowledged pair digest. All 24 resumed pairs
match physical/content snapshots, native checkpoints, signals and sampled
histories exactly. Python reconstructs no content state.

All 48 distinct nominal packets match NumPy observations. Maximum logit
difference is `3.5762786865234375e-6`, below the preregistered `5e-5` tolerance.
Nominal label accuracy is 100%. Eight separate probes in `evidence/port-checks`
cover lengths 2, 7, 32 and 128 and irregular time gaps `exp(U[-3,3])`.
Observations match; maximum logit difference is `1.3113021850585938e-5`.
These are registered fixture/probe results, not whole-envelope error bounds
or open-language quality evidence.

## Scheduling and measured complete execution cost

The client sends one public interval per required endpoint. Rust performs
either one native propagation/commit or sixteen dense subcommits. Duration
remainders are retained exactly, resets occur on the final subcommit and
content is decoded once per endpoint. All families, including ordinary gates,
receive both schedules and the same inputs and observation obligations.

The following means use eight runs per row, including continuous and resumed
runs. Costs include parent IPC/receipt fsync, child startup, model loading,
actual file reads, content/physics/native execution, journal/witness/checkpoint
writes, restart and shutdown.

| Cell | Schedule | Propagations | Host requests | Decodes | CPU seconds | Wall seconds | Durable bytes |
|---|---|---:|---:|---:|---:|---:|---:|
| Ordinary | Public interval | 12 | 12 | 12 | 0.077377 | 0.096010 | 17,858 |
| Ordinary | Dense | 192 | 12 | 12 | 0.210571 | 0.417517 | 283,264 |
| Distribution | Public interval | 12 | 12 | 12 | 0.074050 | 0.093602 | 17,906 |
| Distribution | Dense | 192 | 12 | 12 | 0.205064 | 0.421001 | 284,032 |
| Sampled | Public interval | 12 | 12 | 12 | 0.075263 | 0.096034 | 17,857.25 |
| Sampled | Dense | 192 | 12 | 12 | 0.212960 | 0.459746 | 283,244.25 |

All 24 schedule pairs have equal content/native signals, sampled histories
within the registered tolerance, and physical feature errors below `2e-10`.
Native propagation/commit reduction is 93.75%; decoder and host-request
reductions are **zero**. Observed full CPU reduction is about 63–65% on this
shared host and public-observation contract. It is not an isolated-host
performance certificate or an intrinsic analytic-cell advantage. Durable
bytes mean serialized application records. Energy is `null`; CPU time is
not used as an energy measurement.

## Probability-controlled decode remains an open gate

The actual interface is `Interval.content: Option<{path, sha256}>`. The caller
supplies a required endpoint read. `Owner::interval` decodes it **before**
physical/native commits; `CellPort::execute` subsequently produces physical
features and signals. Those signals do not decide whether to decode.
`subdivisions=1` versus `16` compares public schedules; it is not learned
probabilistic event gating. The explicit report field
`probability_gate_content_savings` is false, and actual decode counts are
12 versus 12.

A future task-value policy must execute before content access, with the same
public information/budget as ordinary and direct-Q controls, and choose
READ/WAIT/FIRE under declared deadline/pending-content obligations. Its
belief, budget, pending request, permitted wake time and value-head identity
must join the checkpoint. Acceptance requires fewer actual decoder calls
with preserved/improved utility and action regret. Applying an unrelated
risk threshold to omit required FullHX observations cannot pass that test.

## Reproduction

`prepare_content.py --hcsn-source <verified tools/hcsn> --output <new weights.json>`
checks both frozen NPZ hashes and exports the binary32 fixture.
`build_cached.py` takes explicit `--build`, `--upstream`, `--toolchain`,
`--prior-report` and `--report` paths; its prior report must contain verified
R8 dependency artifacts. Published R8 bootstrap/build commands reconstruct
those inputs on a clean machine. A clean Cargo build is a separate gate.

`qualify.py --binary <owner> --weights <weights.json> --hcsn-source <verified tools/hcsn> --out <new directory>`
runs the main experiment; `port_checks.py` accepts the same arguments.
They refuse to overwrite prior results. Raw records are retained with
per-file SHA-256 manifests and compressed archives. All runtime receipts
retain `DENY_ALL` and `production_activation=false`.
