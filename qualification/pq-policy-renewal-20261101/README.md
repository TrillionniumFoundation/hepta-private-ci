# PQ owner-policy binding at the actual delivery renewal

## Fixed source and scope

The source parent is Hepta PR #4552 commit
`0f7c63418a7eec6cff5e4348e8cdc733850f8386`, tree
`fd1a3f42c9b85c98b45f304bf19d3de309a80d2a`.
Its policy rollback repair, real text-product observations, earlier failures and
whole-system qualification limits remain unchanged. Its test results are not
observations of this successor.

This change concerns the real Agentd signed-text dispatcher and its original
Evidence SQLite owner. RunStart/ObjectiveStart V1 and ordinary Cell integration
are outside this implementation. No signing key, issuer enrollment, clock,
external checkpoint, deployment credential or installation authority is created.

## Remaining stale-policy window in the parent

`authbus_dispatch::deliver` first refreshes the owner file and checks the selected
thread permission, then awaits `renew_authbus_delivery` before sending the actual
queue request. The parent renewal takes `BEGIN IMMEDIATE` and rechecks the current
issuer, key, epoch, revocation, signed request and lease. It does not compare the
owner-policy revision or commitment used to authorize that thread.

A legitimate concurrent owner update can remove the thread while keeping the
same issuer, key and epoch. If that newer policy commits while renewal is waiting,
the old issuer tuple still passes the parent renewal. Checking permissions again
after the queue response cannot retract a request that already crossed the
transport boundary. This is a source-derived interleaving finding; no native
exploit reproduction is claimed in this initial record.

## Change and linearization boundary

The new policy-bound renewal compares the exact expected policy revision and
commitment with the persisted floor inside the existing write transaction. The
same transaction verifies the current issuer and lease and requires the existing
external-checkpoint transition to be complete. A stale revision, wrong
commitment, future revision or absent snapshot cannot renew a policy-bound
domain. The legacy renewal remains available for domains without a policy floor
and refuses to bypass a populated floor.

The actual Agentd PQ dispatcher passes the snapshot from its final permission
check to this method. Classical dispatch retains its existing explicit path.
No record format, migration, dependency version, lockfile or request deadline is
changed.

The linearization point is this renewal transaction. A later revocation can still
race a request already released to another process; this patch does not claim
distributed atomic revocation, cancellation of an already accepted remote effect,
or protection when all externally retained trust state is rolled back together.
Evidence receives an opaque policy commitment: the trusted caller must still
check the actual operation permission before presenting its snapshot.

## Added native controls and required execution

Two tests extend the existing signed SQLite lifecycle fixtures:

- A bound PQ domain rejects renewal through the legacy API without changing its
  lease; the real dispatcher subsequently completes the legitimate request.
- A same-key policy update fences an older revision, a wrong commitment and an
  uninstalled future revision. Removed permission prevents transport. An
  explicitly newer policy restores the normal signed request and durable Ack.

The independent `Hepta PQ policy renewal` workflow runs all **12** original and
new dispatcher controls plus all **3** existing real Agentd/App Server product
controls, on x64 and ARM, for source-head and the exact prospective merge. Every
lane executes even if two trees are identical. It retains the existing toolchain
1.96.0, lockfile, just/nextest entry points, process prerequisites, test-profile
settings and source-identity wrappers. Every selected test must be observed by
its exact name once; filtering unrelated tests is not counted as selected-test
success or a selected skip. Retries are disabled for this observation.

The tests precede the original scoped `just fix` and `just fmt --base` commands.
The original command wrapper treats any change to the tested source as failure.
The new workflow has no dependency on a separate Chain pressure job, so a retained
failure there cannot prevent collection of these authorization observations.

## Initial validation status

The four changed Rust files have been parsed and formatted with the available
Rust 1.95 rustfmt. This is **not** the required repository 1.96 build, native test,
scoped lint or `just fmt` result. The workflow YAML and embedded Python parse.
Seven synthetic reader controls pass: one complete record is accepted; omission,
duplication, an ignored selected case, wrong log hash, wrong count and a failed
command record are refused. Those reader controls execute no application code.

Native locked compilation and the new native controls are **pending** until
their actual CI records are retained. The current local checkout is a selected
source recovery, and direct Git transport could not reach its configured proxy;
no alternate dependency graph or successful native result is inferred from that
environment. `source-manifest.json` binds the exact original and candidate blobs.

Whole-chain PQ, ordinary Cell V2/FinalUse integration, RunStart/ObjectiveStart
migration, independently operated trust services, old-asset migration, full
rollback, WAN service and quantum work qualification remain unaccepted.
