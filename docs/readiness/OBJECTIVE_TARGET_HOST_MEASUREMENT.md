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

The recorder refuses a dirty tree or source SHA mismatch before measurement and
rechecks the same commit/tree and cleanliness after all fixtures. It records the exact
commit/tree, the operator-supplied host profile identifier, platform/machine,
Rust/Cargo versions and release build profile.

## 2. Separately measured paths

The ordinary fixture executes the canonical source-owned product path with a
frozen authenticated context and admission profile:

```text
admit_objective_v1
-> opaque AdmittedObjectiveV1
-> compile_admitted_objective_v1
-> encode_authenticated_objective_function_v1
-> exact canonical JSON plus semantic decode/round-trip validation
```

The measurement timer surrounds authenticated admission, deterministic compile
and canonical `ObjectiveFunctionV1` projection/validation. It does not include
Cargo startup. The compatibility convenience wrapper
`admit_and_compile_objective_v1` is not used as the target-host measurement
surface.

The conflict fixture executes a 256-hard-atom scalar conflict that requires the
maximum 257 feasibility-oracle calls. Its timer surrounds
`check_feasibility_v1`; fixture cloning occurs before the timed interval.
Ordinary-path latency may not be reused as conflict-extraction latency.

The compiler fixtures are normal Rust tests marked `#[ignore]`. Repository CI
compiles, formats and lints them but does not run them as qualification evidence.
The target-host recorder runs them in `--release` and parses their structured
`OBJECTIVE_MEASUREMENT=...` records.

The product fixture is the real Unix Agentd process test
`objective_product_e2e::measurement_signed_objective_daemon_round_trip`. It starts
Supervisor and Agentd with private AuthBus trust, an independently retained AuthBus
checkpoint, the selected objective profile and an external run-start checkpoint.
It records separate distributions for signed intrinsic-abstain admission and
compiled objective execution. Compiled executions attach the exact daemon-issued
identity to a trusted fixture context, acquire a current signed final-use grant
through the Unix authority socket, send one physical App Server request to a local
controlled HTTP/SSE model endpoint, and observe the terminal state.

The fixture closes and reopens the inference journal before exact replay and
requires the original result without another grant or physical send. It separately
measures Supervisor restart-to-readiness and checks generation non-resurrection.
Its single `OBJECTIVE_PRODUCT_MEASUREMENT=...` row includes requested and actual
sample counts, physical sends, terminal observations and the durable checkpoint
sequence. The recorder rejects non-integer/Boolean counters, mismatched sample
counts, non-monotone latency distributions and incomplete worst-case conflict work.

This is process-level development evidence with a controlled model and trusted
context fixture. The controlled fixture disables plugin provisioning to avoid unrelated network
startup work. The recorder includes the actual temporary-filesystem mount/type;
memory-backed and disk-backed runs must not be pooled into the same storage
qualification result. Neither successful timing nor filesystem identification
grants storage qualification. It is not evidence of a live model service, autonomous assembly
of all seven canonical owner inputs, or recovery of an unpersisted canonical
owner handoff. Those remain separate product/deployment qualification boundaries.

## 3. Evidence semantics

Each path publishes sample count and p50/p95/p99 latency in nanoseconds. The
conflict path additionally publishes constraint count and oracle calls per
sample. The recorder also records total harness wall time, which includes Cargo
and test-process overhead and must not be substituted for the algorithm
percentiles.

A GitHub-hosted CI runner is development evidence only. Closing
`LANE-D-EXT-HOST-MEASUREMENT` requires the target-host qualification owner to
bind this output to the selected deployment host profile, resource policy and
candidate identity and to retain any additional CPU/RSS/IO observations required
by that host profile. The product fixture covers normal signed ingress, socket
round-trip, RunStart fsync, exact replay, final-use authorization, a controlled
physical model send, terminal observation and restart recovery. Segment saturation,
rotation, compacted-prefix rewrite and power loss remain destructive qualification
scenarios rather than latency-loop operations. The selected filesystem profile must
therefore also qualify active-frame fsync, segment rename and successor creation,
compacted-summary atomic replace, external-checkpoint atomic replace and sidecar-lock
ownership at every documented crash cut. Unix source synchronizes the relevant
containing directories; non-Unix source makes no equivalent receipt without
host-specific evidence.

## 4. Acceptance boundary

No universal latency threshold is declared in source. p95/p99 budgets belong to
the selected host profile and must be compared by the target-host qualification
owner. Failure, overload or resource exhaustion cannot weaken a hard constraint,
expand the legal action set or convert an unavailable result into a compiled
objective.

The output is measurement evidence only. Independent semantic review, deployed
caller authentication, operator acceptance, activation, promotion and release
remain separate gates.
