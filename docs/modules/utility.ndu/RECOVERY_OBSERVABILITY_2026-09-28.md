# NDU recovery and operational acceptance — 2026-09-28

## Source and evidence boundary

This follow-up inherits candidate `9c70d28ecacd5b95d5267ef42ca92305e1622285`
from `work/utility-ndu-abcd-convergence-20260928` and does not modify that branch.
The baseline main read for this work was
`a126987b84737dbc2ee2592442a314117bddb4a2`. The existing run `36338190108`
passed all twelve source-head/synthetic-merge suites and its aggregate.
The aggregate artifact SHA-256 is
`0ef34bf846c0c8dbced0b0fbf5e0ebe063d68dd4413b9877618f913ebe86916b`.
Those bytes were downloaded and independently revalidated against all retained
logs and native receipts. They are **inherited evidence, not qualification of
this follow-up's changed source**.

Each new run freezes main once, commits actual normalized source and its typed
object map, and tests that resulting SHA in twelve independently executed jobs.
The trigger SHA and resulting source SHA are explicitly distinct if formatting
or a generated map changed. The source-head checkout equals the resulting source
SHA; the synthetic checkout equals the deterministic two-parent merge SHA.
No document attempts to embed its own final commit SHA. Exact values, trees,
parents and every command exit status live in the sealed execution receipts.

## Recovery acknowledgement closure

A valid hash chain read from the page cache establishes visibility, not a durable
acknowledgement. A process can die after journal rename but before parent fsync.
Previously reopening could return an authoritative handle, after which an exact
identity replay intentionally performed no I/O. This could acknowledge an image
whose directory durability had never been established.

`ProjectionPersistenceV1::confirm_recovered` now synchronizes the opened journal
and its parent before `open_durable` returns an existing image. A failed recovery
barrier returns `Indeterminate`; no handle, authoritative read, backup or replay
is admitted. Mutation cuts and recovery cuts are separately injectable. Tests
cover both recovery barriers, a real rename with injected lost acknowledgement,
unchanged journal bytes on rejected recovery, and corruption rejected before
recovery confirmation. These are process/filesystem tests, not physical power-loss
certification for an arbitrary storage stack.

The owner-binding file now uses the same no-follow/nonblocking, single-link,
owner-UID and no-other-writer checks as the journal. New bindings are mode 0600;
existing bindings also cross file and directory recovery barriers. Hard-linked
or group/world-writable bindings cannot be adopted on restart. The private-root
and same-owner threat model remains unchanged; this does not supply an off-host
rollback witness.

## Read-only operational integration

`scripts/hepta_ndu_observer.py` is an executable Linux companion to the existing
private Agentd control socket. It sends only `metrics_v2` and `metrics_v1`, checks
kernel peer UID/PID/start time/boot identity, and requires exact agent, spawn,
current and NDU generations. A restart between the two reads rejects the sample.
The collection deadline covers both requests. Each newline JSON frame is bounded
at 65,536 bytes; duplicate/foreign fields, bool-as-u64, overflow, malformed bucket
arrays, substituted identities and unsafe paths fail closed.

The observer exports evaluation/persistence latencies, convergence, uncertainty
bins, veto reasons, busy/indeterminate/reopen/restore/corruption counters, journal
bytes, memory fallback and readiness. It is diagnostic, never authorization.
It does not infer qualified backing storage from `storage_ready`, nor manufacture
an independently acknowledged backup age. Unknown readiness and backup age have
explicit `*_known=0` signals and no fabricated value.

Counter labels include an owner-instance digest so process-local resets cannot
silently blend two owner lifetimes. Source non-cumulative latency bins become
cumulative second-based histogram buckets. Uncertainty remains explicitly labeled
non-cumulative raw-Q32 bins. Snapshots are approximate, not cross-counter atomic.
The two telemetry versions are read from the same owner but not the same instant.

Textfile publication uses an exclusive temporary file, fsync, directory-relative
atomic replacement and parent fsync. No TCP listener or new control privilege is
created. A failed probe replaces old healthy samples with `observer_up=0`, not
zeroed counters. Failed publication exits nonzero; the retained sample timestamp
must trigger the stale-collector rule. Symlink and hardlink output aliases reject.

The shared `ndu-observer-wire.json` fixture round-trips through the actual Rust
protocol types and is consumed by Python tests. The normal Agentd process test
runs the shipped Python observer against the real UDS before and after restart.
Protocol changes therefore require explicit consumer updates rather than silently
missing a new field.

### Deployment and alert enrollment

Review the `.service.example`, `.timer.example` and `ndu-alerts.yml` under
`operations/` before copying them to an approved host. Supply the real canonical
Agent UUID, absolute socket and supervised generation in the environment file.
Run under the Agentd UID; the socket must be private and directories must not be
writable by other principals. The textfile directory must be owner-writable and
readable by the existing node exporter. Configure that exporter's textfile
collector explicitly; keep its existing scrape access controls.

Install a separate enrollment textfile containing
`hepta_ndu_observer_expected{agent="<real UUID>",generation="<supervised generation>"} 1`
for every expected target. This allows the missing-observer rule to detect a timer
that never started. Change enrollment with the supervised generation; do not infer
it from a stale successful scrape. Review Prometheus job/instance matching when
combining multiple exporters. Test failed probes, stopped timers, missing output,
unknown readiness and restart counter separation on the target deployment.

The supplied timer and rules are deployment artifacts, **not evidence of an
installed service, configured Prometheus, or a delivered live alert**.
Reference semantics: Prometheus exposition/histogram documentation and the
prometheus/node_exporter textfile-collector documentation.

## Evidence-publication acknowledgement closure

S3 publication retains `If-None-Match: *` and never overwrites. A timeout, 412, or
acknowledgement lacking a version no longer makes safe repeated publication
permanently unusable. It reads the original key's identified version and verifies
its bytes, version ID, approved KMS key and encryption metadata. Success requires
that exact readback. There is at most one PUT per invocation; unresolved outcomes
are `NDU-PUB-003`, conflicts are `NDU-PUB-004`. Preserve the original key and source
bytes for reconciliation; never hide uncertainty by switching keys. Per-attempt
private readback directories are cleaned and do not block exact retries.

A version ID is not a retention or WORM guarantee. Object Lock, deletion policy,
bucket retention, approved IAM/OIDC enrollment and live readback remain separate
operator-controlled requirements. The test doubles exercise acknowledgement loss
and conflicts but are not AWS connectivity or publication evidence.

## Remaining acceptance gates

The inherited feature-provenance, actor coverage, integer-oracle, veto and signed
learning lifecycle tests remain mandatory. No threshold is weakened and no
historical fixture is substituted for an actual current candidate run.

The selected V1 store retains its 4,096-record envelope and reserved revocation
capacity; it is not silently migrated or prefix-truncated. The additive
`NduProjectionEpochJournalV1` source candidate now supplies the reviewed semantic
transition that was previously missing: bounded active epochs, compact identity
replay, explicit recorded/revoked/selected state, lossless archive chaining and
acknowledgement-bound local retention planning. Retention binds the transition
identity, complete archive checksum, external object version, restore-drill receipt
and exact current monotonic checkpoint frontier.

The planner performs no deletion, and this source candidate is not an activated
durable epoch store. Until target-filesystem crash qualification and real off-host
retention execution exist, keep V1 capacity monitoring and explicit backpressure;
do not clear a live journal.

Production enrollment of the protected clock and independent CAS frontier,
target-filesystem power-loss/backup-restore drills, live encrypted publication,
installed alerts, and accepted-learning/policy rollout remain externally evidenced
acceptance gates. A green candidate is not production activation.

## Current requalification request

The recovery branch has been advanced only to request a fresh exact-source and
ordered-parent synthetic-merge execution after the recovery-acknowledgement and
observer additions. The branch-scoped workflow must materialize any generated
map changes, publish the resulting descendant SHA, execute all twelve suites, and
seal the aggregate before this source can replace the previously qualified head.
This request is not itself evidence of success and grants no activation authority.
