# cognitive.read qualification closure

Status: source candidate; exact source-head and deterministic merge execution are required;
`activation=false`.

This supplement closes repository-controlled gaps without changing the module's ownership or
authority model. Durable facts remain with the existing memory owner. Read results, prepared
views, canonical shadows, benchmark output and qualification receipts remain deny-all evidence.
None grants model use, provider access, mutation, activation, promotion or release authority.

## Preserved design

The convergence keeps four boundaries unchanged:

1. one physical durable owner; `cognitive.read` does not open a second database or retain a
   second authoritative history;
2. exact-ID reads are all-or-error and do not silently prefix-truncate;
3. the complete canonical result budget is checked before projected records and citations are
   cloned; and
4. final-use currentness is reacquired from the owner and cannot be satisfied by a prepared
   structural index or prior receipt.

`PreparedReadSnapshotV1` therefore remains borrow-scoped to one immutable owner cut inside one
request. It reuses structural validation and the current-head index only. It stores no
principal, grant, scope authorization, clock result, lease or revocation decision.

## Revision-bound canonical shadow

The V1 canonical shadow remains byte- and behavior-compatible. Legacy V1 citations contain
only source ID and digest, so V1 continues to disclose partial provenance equivalence.

`adapt_authoritative_read_to_revision_bound_canonical_shadow_v2` is an additive local Rust
surface. For every legacy citation it requires an explicit owner-issued
`CanonicalSourceRevisionBindingV2` containing source ID, source revision and source digest. The
adapter verifies:

- the exact legacy record ID, revision and record digest;
- citation ID/digest equality with the revision bridge;
- bridge ID/revision/digest equality with `MemoryEventV1` provenance;
- live/tombstone lifecycle compatibility;
- the canonical event digest; and
- one V2 domain-separated shadow binding over the source revisions and read receipts.

Missing, zero, duplicate or substituted revisions fail closed. The V2 shadow is not a wire
protocol and is not sufficient for physical model-request attachment. Product composition must
still reacquire the owner cut and perform final-use validation.

## Exact execution gates

The read-only qualification runner records the complete command, log, exit code and elapsed time
for every gate. In addition to package, lint, format and existing product gates, it requires:

- `revision-shadow-tests`: the exact revision bridge success and tamper cases;
- `owner-currentness-e2e`: validity-expiry/scope filtering and old-valid-backup rollback
  detection on the SQLite owner;
- `stale-generation-e2e`: stale Agentd spawn generation rejected before store access;
- `native-final-use-e2e`: fresh physical worker acceptance plus correction and tombstone races
  rejected after durable dispatch and before `TurnStart`;
- eight consumer package/extension gates and the authenticated multi-owner intelligence product
  fixture; and
- `sqlite-capacity`: one exact 512-record/512-ID/32-iteration SQLite owner workload.

A positive package count is not enough for the named semantic gates. The validator requires the
actual nextest PASS row for every exact case. Source-head and deterministic merge receipts are
separate and bind their own commit, tree, ordered parents, commands, logs and measurement files.

## Consumer evidence boundary

[`CONSUMER_EXECUTION.json`](CONSUMER_EXECUTION.json) maps the seven registered consumers to exact
package and normal-product gates. The receipt records each gate status separately. This does not
normalize all consumers to one state:

- `compact.engine` has an exact-owner candidate API and fixtures, but no normal
  product caller or durable checkpoint publication;
- `context.compiler` retains legacy V1 product composition; verified revision-bound
  V2 ingress is implemented locally while provider-bound product use is pending;
- `memory.federation` retains local owner/extension composition without claiming cross-host
  authentication;
- `memory.retrieval` exercises the existing owner/Agentd/native-worker path;
- `neuron.runtime`, `objective.compiler` and `utility.ndu` exercise their authenticated
  intelligence product owners while their distinct lifecycle or production-composition gaps
  remain visible.

Every row keeps `v2_migration_proved=false`. A passing source audit or package test cannot turn a
registered port into a completed product migration.

## SQLite and host measurements

The capacity gate uses the real `CognitiveStore`, seeds 512 verified active revisions with owner
citations, acquires the durable Lane C cut, constructs the request-local prepared index, resolves
512 exact IDs, and revalidates the cut. It reports p50/p95/p99 microseconds for each phase,
SQLite file/page/row measurements. Process user/system CPU, elapsed wall time and
maximum RSS cover the entire `just test` command, including any compilation,
fixture setup and test-runner overhead; they are not isolated read-phase resource
measurements. The separately timed Rust phase distributions cover owner acquisition,
index construction, read and revalidation.

The result is tied to the exact candidate and current GitHub runner. It is a qualification
measurement, not a universal performance guarantee. Production target-host acceptance still
requires the operator-selected host class and external acceptance process.

## Completion boundary

A candidate passes repository qualification only when every required command and measurement
passes on both the exact source head and deterministic merge candidate. Even then the
implementation map remains:

```text
productionImplementation = false
productExecutionProved = false
independentAcceptance = false
activation = false
release = false
```

Those flags change only through their independently governed acceptance, canary, promotion and
release processes. CI source edits and schema migrations cannot activate this module.
