# Main-process exit finalization retry

## Scope

This follows `fc9fd29dd86bb1d4e55a1b00f50cdc5a8f30bd46` in PR #1057.
It repairs main-process exit finalization within the existing owner lifetime;
it does not introduce a new durable writer, lease format or authority protocol.
It updates the corresponding remaining-work entry in the adoption-control
amendment without certifying the earlier candidate.

## Failure and repair

`remove_lease` verifies a lease, unlinks it, then synchronizes its directory.
Previously, an error after unlink (directory sync or the later lifecycle CAS)
retained the runtime but discarded the cleanup progress. The next tick attempted
strict removal again and failed permanently because the lease was missing.
It also polled an already observed terminal process again, allowing a later probe
error to hide a known exit.

The Agent slot now keeps two bounded pieces of local state until finalization
succeeds: the immutable exact `ProcessExit` observation, and a private
`ProcessLeaseRemoval`. The latter binds the expected complete lease and run-root
path. Its `unlinked` bit is set only after this witness's own successful unlink,
before directory sync is attempted.

Before that successful unlink, missing, malformed or changed leases still fail.
Afterward, the same witness can retry directory sync while the lease remains
absent. Any reappearing lease, including one with identical serialized identity,
rejects without deletion. A different expected generation/identity or root path
also rejects. A newly created witness cannot infer unlink success from absence.
The existing strict `remove_lease` used by other recovery paths is unchanged.

The exact exit observation survives finalization errors. Subsequent ticks retry
only the failed durable cleanup, not signalling or process polling. Runtime
ownership remains retained and unhealthy until completion. Both local values
are cleared only after the lifecycle finalization completes, before replacement
processing can proceed. A failed synchronization is never acknowledged as success.

## Regression sources

`lease::removal::tests` adds eight tests over real temporary lease files with an
explicitly injected directory-sync error. They cover retry after unlink, every
retry's synchronization requirement, initially absent leases, fresh-witness
rejection, changed process identity, identical-identity reappearance, changed
root/generation and malformed recreated data.

`tick::exit_tests::exact_exit_survives_cleanup_failure_without_repolling_or_resignalling`
adds one native-library test source with two constructed cut cases: before unlink
and after the same witness's unlink but before registry finalization. It uses a
real FleetRegistry and lease, with a deterministic ProcessDriver. An unexplained
absent lease first forces failure; after restoring the exact lease and optionally
advancing the removal witness, a later tick must complete without another poll
or signal. The assertions require exactly one process poll, no signals, one
handle drop, a Stopped lifecycle and no pending restart.

These are nine Rust test functions (one with two cut cases), not nine successful
executions. No Rust compiler/formatter was available locally. Original source
blobs and uploaded bytes were checked, and the scoped patch passed Git whitespace
checks. Existing CI must compile, format, lint and execute this exact candidate.

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib lease::removal::tests
just test --locked -p codex-hepta-supervisor --lib tick::exit_tests
```

## Limits and required qualification

The witness is deliberately non-serializable local progress, not a durable
operator decision or anti-rollback record. A daemon crash loses it and must go
through the existing startup recovery, not reconstruct it from an absent file.
The injected sync error and constructed cuts are not host power-loss, ENOSPC,
kill-9, filesystem rename-race or physical durability measurements.

This uses the existing serialized owner and protected fleet-path assumptions.
The root binding here is a path binding, not a newly established directory-inode
or descriptor-relative filesystem security boundary. Matrix lease cleanup,
competing external writers, directory substitution, durable restart cancellation,
cross-daemon cleanup recovery and signed release-transaction completion still
need independent review and corresponding execution evidence.

The five-stage program remains incomplete. This patch makes no change to required
checks, their failure policies, feature gates, trust roots, production writer
permissions, independent acceptance, activation or release status.
