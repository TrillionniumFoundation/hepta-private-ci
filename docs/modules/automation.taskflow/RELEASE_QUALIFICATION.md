# automation.taskflow release qualification

Canonical source declarations: [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md).
The current store schema is 22. V1 TaskFlow and provider identities are unchanged.
A source-present test, read-only gate definition or signed intent is not evidence
that the exact candidate executed successfully.

## Repository-controlled gates

The repository has durable schedules/occurrences, the TaskFlow causal chain,
fenced recovery sweeps, cancellation-aware batching, error categories, Calendar
V2 control and a configured authorized-effect host. It also has limited Circuit
and cross-host manifest adapters. Their product limits remain explicit.

Required qualification retains check-only formatting, locked compile, strict
Clippy, native/structural/migration tests, Agentd product tests and Bazel targets.
Both exact source-head and deterministic-merge execution must reach terminal
success. The command recorder retains actual records, working directory, tree,
time, output digest, toolchain output and nonzero minimum test observations.
`not_run`, running, interrupted, failed or missing records cannot count as success.

The canonical contract checker validates facts and generated projections without
requiring unfinished capabilities to become `true`. A passing source-fact check
is not whole-module completion. Its output keeps native/product execution and
release false. Developer `render`/`observe` commands are not CI repair steps.

## Remaining repository source/product work

Schema-22 durable Circuit ingress, activation, recorded choices, reservations and
Wait/Effect checkpoints are source-present. They still require a normal Agentd
product port with real owners and process-cut recovery evidence that does not
recompute an outcome in the test process. The cross-host manifest still needs an
operated source fence, transport/controller integration and a two-host exercise.
TaskFlow startup materialization is page-bounded, but selected-runtime behavior and
long-retention latency/RSS/I/O capacity must still be measured.
These are source obligations, not merely externally supplied signatures.

The checkpoint CLI provides consistent backup and staged restore without changing
schema, epoch, occurrence, provider or authority state. Its Python SQLite identity
and child-process tests do not prove native migration or physical source fencing.

## Selected-host qualification lane

`.github/workflows/automation-taskflow-selected-host.yml` identifies an immutable
candidate, target profile and explicitly selected host. Its current metadata-only
identity fields and source fixtures are insufficient to close the actual-use
binding requirement. Do not count a tzdb directory hash as proof that Calendar V2
consumed its transition profile, or Python's SQLite version as native SQLx identity.

The finished lane must bind loaded provider endpoint/contract, terminal observer,
final-use trust, current revocation frontier, used timezone profile and native
runtime implementation to the same actual execution. It must also retain DST,
concurrent scheduler, restore, real cross-host and capacity outcomes for that
configuration. A successful source test remains its own evidence class.

## Independent acceptance and deployment

An acceptance envelope must bind exact commit/tree, successful focused and
selected-runtime receipts, target profile, provider/observer identities, trust
roots and current revocation frontier. The acceptance principal and provisioned
key must be independent of the implementation principal. A CI environment
approval, self-authored document or implementation signature is not a substitute.

Externally provisioned trust/credentials, physical fencing and independent
operational acceptance remain required in addition to the repository source work.
Independent acceptance does not silently activate, promote or release anything.
Until the exact evidence chain is verified, source-state projections retain:

```text
deploymentQualificationComplete = false
productExecutionProved = false
independentAcceptance = false
activation = false
promotion = false
release = false
```
