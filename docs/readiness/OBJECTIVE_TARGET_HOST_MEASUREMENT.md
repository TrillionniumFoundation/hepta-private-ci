# objective.compiler target-host measurement

This document defines the repository-owned measurement harness for the external
`LANE-D-EXT-HOST-MEASUREMENT` gate. Running the harness does not activate,
accept, promote or release a candidate.

## 1. Exact-source requirement

Measurements are valid only for one clean exact commit and tree. Run from a
checkout of the candidate that will be evaluated:

```bash
python3 scripts/hepta-objective-target-measure.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --host-profile-id <registered-host-profile-id> \
  --ordinary-samples 1000 \
  --conflict-samples 64 \
  --product-samples 32 \
  --execution-samples 4 \
  --output /path/to/objective-target-host.json
```

The output and retained logs must be outside the source checkout. The recorder refuses a dirty tree or source SHA mismatch before measurement and
rechecks the same commit/tree and cleanliness after all fixtures. It records the
exact commit/tree, workflow/run identity when available, the operator-supplied
host profile identifier, platform/machine, Rust/Cargo versions and release build
profile.

V2 evidence additionally binds the exact Cargo-produced test executable, other
emitted package executables, their SHA-256 digests and sizes, the Cargo artifact
messages, exact selected test and its listing, and the execution transcript.
Artifact identities are checked both before and after execution. A missing,
ambiguous, symlinked or changed executable is an error, not a zero-cost sample.
This is native Rust fixture identity, not independent FFI qualification.

## 2. Separately measured paths

### Static profile validation and request-local compilation

The ordinary fixture measures the canonical owner path used by Agentd rather
than the lower-level compatibility wrapper:

```text
cold ValidatedAdmissionProfileV1::new(raw_profile)

process-generation ValidatedAdmissionProfileV1
+ ObjectiveSourceEnvelopeV1
+ fresh ObjectiveAdmissionContextV1
-> admit_validated_objective_v1
-> compile_validated_objective_v1
-> encode_proof_bearing_objective_function_v1
-> decode_objective_function_v1
```

It publishes separate p50/p95/p99 distributions for:

- cold profile validation and index/collision construction;
- warm authenticated admission using the frozen profile;
- native deterministic compilation;
- proof-bound canonical protocol encoding;
- strict canonical protocol decoding.

The result binds the exact static reuse key—profile digest, profile revision and
compiler-contract digest—and states `dynamicAuthorizationCached: false`.
Authentication, source identity, scope, freshness, deadline, current trust,
revocation, generation, fence and final-use authority are not part of the reused
profile result. The compatibility convenience wrapper
`admit_and_compile_objective_v1` and the raw-profile publication façade are not
the normal Agentd measurement surface.

### Maximum conflict work

The conflict fixture executes a 256-hard-atom scalar conflict that requires the
maximum 257 feasibility-oracle calls. Its timer surrounds
`check_feasibility_v1`; fixture cloning occurs before the timed interval.
Ordinary-path latency may not be reused as conflict-extraction latency.

### Product owner path

The product fixture is the real Unix Agentd process test
`objective_product_e2e::measurement_signed_objective_daemon_round_trip`. It
starts Supervisor and Agentd with private AuthBus trust, an independently
retained AuthBus checkpoint, the selected objective profile and an external
run-start checkpoint.

The fixture records distributions for signed ingress and for compiled objective
execution. The phase
`signedIngressCompileDurableAppendCheckpointAndAgentdHandoff` deliberately
keeps the destination-owner append, external checkpoint CAS and Agentd handoff
inside the observable atomic boundary. The recorder must not invent separate
success or timing claims for internal operations that are not independently
committed. It additionally records compiled publication/handoff, context
attachment, and current final-use/provider/terminal-observation phases.

Compiled executions attach the exact daemon-issued identity to a trusted fixture
context, acquire a current signed final-use grant through the Unix authority
socket, send one physical App Server request to a local controlled HTTP/SSE
model endpoint, and observe the terminal state. The fixture closes and reopens
the inference journal before exact replay and requires the original result
without another grant or physical send. It separately measures Supervisor
restart-to-readiness and checks generation non-resurrection.

The product record includes requested and actual sample counts, physical sends,
terminal observations and the durable checkpoint sequence. The recorder rejects
Boolean/fractional counters, mismatched sample counts, non-monotone latency
distributions, incomplete phase sets, a split atomic-owner declaration and
incomplete worst-case conflict work.

## 3. Resource observation semantics

Each workload is built first with `cargo test --locked --release --no-run` and
Cargo JSON artifact output. The selected prebuilt native test is then launched
below a fresh Python resource helper, with its exact fully qualified test name,
`--ignored --exact --nocapture --test-threads=1`. Cargo compilation is outside
the resource sample. The helper reports one
`hepta.objective-command-resource-observation.v1` record containing:

- the OS-reported waited-child peak resident set size;
- user and system CPU nanoseconds;
- wall nanoseconds;
- minor and major page faults;
- voluntary and involuntary context switches.

A fresh helper prevents `RUSAGE_CHILDREN` from accumulating earlier fixtures in
the recorder process. However, its `ru_maxrss` value is not a sampled sum of all
simultaneously live descendants and must not be described as aggregate
process-tree peak memory. It is also not an allocation profile for an internal
Rust phase. These distinctions apply separately to each supported host OS.

Phase latencies are measured inside the fixture; resource values are isolated
per ordinary, maximum-conflict and product fixture. In particular, the product
resource observation covers the combined append/checkpoint/handoff boundary
rather than pretending to assign memory to non-separable owner substeps.
Detailed allocator, I/O and simultaneous-process-tree profiling may be attached
by the selected host profile as additional evidence, but may not replace the
bounded workload and prebuilt artifact identities.

The compiler fixtures are normal Rust tests marked `#[ignore]`. Repository CI
compiles, formats and lints them but does not treat source presence as target-host
evidence. The recorder explicitly executes them in release mode and parses
structured measurement rows. Parser and negative tests run in both objective
admission qualification and the dedicated target-measurement workflow.

## 4. Filesystem and evidence boundary

This is process-level development evidence with a controlled model and trusted
context fixture. The controlled fixture disables plugin provisioning to avoid
unrelated network startup work. The recorder includes the actual temporary
filesystem mount/type; memory-backed and disk-backed runs must not be pooled
into one storage qualification result. Filesystem identification and successful
timing do not grant storage qualification.

The V2 measurement output is consumed by
`scripts/hepta-objective-evidence-project.py` together with the static
`CURRENT_STATE.json`. The resulting projection binds source commit/tree,
workflow/run identity when available, native fixture identities and the
measurement artifact digest. Every measurement retains the Cargo artifact
messages, exact test listing, fixture output and resource-helper process output
under `native-fixtures/` next to the receipt. The projector verifies their actual
hashes, the fixed workload/package/target/test mapping, and reparses distributions,
sample counts, maximum-conflict work and product send/terminal/checkpoint counters.
It also binds the resource counters and fixture wall time to the process output;
receipt-shaped metadata with missing or changed logs cannot claim an observation.
Checked-in source does not hand-edit a target-host pass field. Exact-execution projection additionally checks the complete command
inventory from the existing runner, candidate commit/tree, deterministic merge
identity and the actual retained log bytes; digest-shaped labels alone do not
constitute successful execution evidence.

This verification establishes artifact consistency and observed fixture output.
The relying authority must independently authenticate the workflow artifact's
provenance and the claimed host/issuer. A self-consistent receipt or user-supplied
host label cannot establish an independently accepted measurement.

A GitHub-hosted runner remains qualification/development evidence, not selected
deployment-host acceptance. Closing `LANE-D-EXT-HOST-MEASUREMENT` requires the
external qualification owner to bind the artifact to the selected host profile,
resource policy and storage configuration.

The product fixture covers normal signed ingress, Unix socket round-trip,
RunStart fsync, exact replay, final-use authorization, one controlled physical
model send, terminal observation and restart recovery. Segment saturation,
rotation, compacted-prefix rewrite and power loss remain destructive
qualification scenarios rather than latency-loop operations. The selected
filesystem profile must separately qualify active-frame fsync, segment rename
and successor creation, compacted-summary atomic replace, external-checkpoint
atomic replace and sidecar-lock ownership at every documented crash cut. Unix
source synchronizes the relevant containing directories; non-Unix source makes
no equivalent receipt without host-specific evidence.

## 5. Acceptance boundary

No universal latency or memory threshold is declared in source. p95/p99 and
resource budgets belong to the selected host profile and must be evaluated by
the target-host qualification owner. Failure, overload or exhaustion cannot
weaken a hard constraint, expand the legal action set or convert an unavailable
result into a compiled objective.

The output is measurement evidence only. Independent semantic review, deployed
caller authentication, operator acceptance, activation, promotion and release
remain separate gates.
