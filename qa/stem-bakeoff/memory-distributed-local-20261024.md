# Distributed memory controls: local evidence, 2026-10-24

The local mechanism work is executable. The separately registered hosted
two-runner experiment has not run at the time this evidence was sealed.
No general-memory, future-task, net-compression or production acceptance gate is
closed by this report.

## Source and evidence identity

- Baseline: `429894ac8e0818102cfdea4ad47a56e4583b2902`.
- Evidence: `evidence/memory-distributed-local-20261024.tar.gz`.
- Archive SHA-256: `7d816d18758ef23fd7c14f60393bb584a01ea4149d04ed00318660cabe5e9b79`.
- Archive size: 99,421 bytes; 46 retained files.
- The archive contains raw success/failure logs, exact pre-format source copies,
  a separate RPC directory-fsync source supplement, and source byte/AST receipts.
- Ruff 0.15.13 and the repository's `just fmt` completed. Python ASTs match the
  final pre-format source receipt. No local tests ran after final formatting.

## Executed behavior

The frozen composed suite passed all **16 tests in 95.699 seconds**. It exercises
real signatures, SQLite transactions, independent replica processes and actual
mTLS sockets. The final RPC journal parent-directory fsync addition passed its
three focused contract tests separately. The tiny-decoder relay wiring test uses
simulated artifact delivery and runner identities, and is not multi-host proof.

The existing network regression suite initially passed **7/8** cases. Its source
service case returned `indeterminate` while the workspace disk was exhausted.
The same behavioral case passed alone in **28.767 seconds** after space returned;
the only test change adds the existing raw response to assertion diagnostics.
The available first-run receipt does not establish a definitive root cause.
The original failure remains in the archive. All **24 distinct local cases** now
have a passing execution, with this initial instability explicitly retained.

Earlier attempts are also preserved: the first unprivileged TLS tests were
blocked by the sandbox's socket restriction; authorized actual-socket runs
passed. A tiny relay fixture first requested four updates, below the existing
three-fact/four-template full-pass requirement, and was corrected to twelve
before it passed. This changed only the wiring test, not the registered hosted
256-update experiment. The first `just fmt` attempt used a read-only default UV
cache; the successful retry used a task-specific writable cache.

## Mechanisms established locally

- A responding majority can read the newest certified state with one replica
  offline. Losing a majority refuses admission.
- Independent process termination/restart preserves votes and committed state.
  A prepared majority can be recovered, and a lagging replica can replay a
  continuous certified history.
- A replica cannot vote for two proposals at one sequence. Forged signatures,
  duplicate votes, wrong membership, older database restore and missing database
  fail closed within the documented durable-storage fault model.
- Certificate grants distinguish reader/publication operations and scopes.
  Evidence reads require an exact root and reject correction/withdrawal.
- A live source change blocks a stale certified placement without another write
  to the replicas. Source outage and authority minority block before callbacks;
  a change during a callback suppresses the returned result.
- Legacy actual-checkpoint transfer, fresh decoder, parent-death cleanup,
  migration, restart and withdrawal behavior remains exercised.

## Limits retained as open

All actual socket/process behavior in this local report ran on one host. The
authority is fixed-membership, single-writer and crash-fault oriented. There is
no leader election, Byzantine protocol, dynamic membership or full-volume/key
rollback recovery. The canonical source remains an online single-writer
dependency, and its research ingress is not native authorization.

RPC cost records distinguish application payload bytes from unmeasured TLS/TCP
traffic. The hosted protocol separately records two physical base copies,
checkpoint copies, raw generation, 32 serial cold-worker requests and source
evidence. Artifact relay cannot prove direct cross-host mTLS behavior or an
instantaneous withdrawal guarantee before delivery. Accuracy is scored separately
from transfer and lifecycle gates, with raw answers preserved.
