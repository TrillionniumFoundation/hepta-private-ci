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
  --output /path/to/objective-target-host.json
```

The recorder refuses a dirty tree or source SHA mismatch. It records the exact
commit/tree, the operator-supplied host profile identifier, platform/machine,
Rust/Cargo versions and release build profile.

## 2. Separately measured paths

The ordinary fixture executes the complete source-owned path
`admit_and_compile_objective_v1` with a frozen authenticated context and
admission profile. The measurement timer surrounds admission plus deterministic
compile, not Cargo startup.

The conflict fixture executes a 256-hard-atom scalar conflict that requires the
maximum 257 feasibility-oracle calls. Its timer surrounds
`check_feasibility_v1`; fixture cloning occurs before the timed interval.
Ordinary-path latency may not be reused as conflict-extraction latency.

Both fixtures are normal Rust tests marked `#[ignore]`. Repository CI compiles,
formats and lints them but does not run them as qualification evidence. The
target-host recorder runs them in `--release` and parses their structured
`OBJECTIVE_MEASUREMENT=...` records.

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
by that host profile.

## 4. Acceptance boundary

No universal latency threshold is declared in source. p95/p99 budgets belong to
the selected host profile and must be compared by the target-host qualification
owner. Failure, overload or resource exhaustion cannot weaken a hard constraint,
expand the legal action set or convert an unavailable result into a compiled
objective.

The output is measurement evidence only. Independent semantic review, deployed
caller authentication, operator acceptance, activation, promotion and release
remain separate gates.
