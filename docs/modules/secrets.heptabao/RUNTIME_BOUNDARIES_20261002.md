# Protected runtime boundary audit — 2026-10-02

## Source selection and ownership

The review baseline is product integration commit
`5b2452d75f3d011e0a5223ffbb759b37408811fe` (draft #1303). Frozen module draft
#1275 and audit draft #1297 remain separate historical candidates. The product
integration is not a descendant of #1297 and is not assumed to inherit its
qualification receipts. Its concrete services and refactored owners are the
source being repaired here; no wholesale branch merge is part of this change.

The normal `serve-runtime` entry point composes `SecretsRuntimeOwner`, the
existing `SqliteBaoOwnerV1`, `SqliteBaoProductRuntimeV1`, AuthBus and final-use
authority. Independent issuer/operator/consumer roles own their original
private state and signatures. Agentd's optional Root-enrolled client addresses
this same runtime; it does not create a second credential owner.

- `runtime_service.rs` owns original-operation sequencing and peer-bound IDs
- `local_service.rs` owns bounded framing, connection admission and physical
  task drain for all four service roles
- `runtime_clock.rs` projects independently verified time into a bounded local
  monotonic sample; it is not a time issuer
- SQLite consumption state owns recovery claims, immutable results and CAS
- AuthBus owns original quota reservation and settlement
- The registered consumer owns original authentication and signed ACKs

Provider-native dynamic issue/renew/revoke remains closed. Metadata lease
transitions are not evidence that those external provider operations exist.

## Findings and corrected behavior

### Connection timeout phases

The old outer timer fenced the complete owner whenever a connection timed out,
including incomplete inbound frames and blocked writes of completed responses.
A peer with socket access could therefore make legitimate later work fail even
though its own request had never reached a state owner.

The cancellation fence now spans only the actual owner handler future. A drop
or panic during that future preserves uncertain-write fencing. An explicit
handler return, including an error, ends the wrapper fence; owner-local commit
fences remain responsible for classifying their own returned storage failures.
No new retry or outcome inference is introduced. A partially delivered reply
remains unknown to its recipient, which must query the same original identity.

### Absolute request deadlines

The prior relative timeout began when the accepted task was first scheduled,
renewing time already spent waiting. A ready request could enter a handler after
the original deadline. The transport now uses the accept-time absolute deadline
and checks it immediately before owner entry, including after the second peer
check. A second check after handler completion withholds late replies without
fencing or rewriting the completed result. Frame caps, four in-flight slots and
peer checks remain unchanged.

### Recovery clock freshness

The old Recover preflight fetched valid independent time through the bare
evidence client but did not refresh the clock used by SQLite recovery claims.
After an idle interval, nonterminal recovery could fail before claiming work.
Recover now uses the same `RuntimeEvidence` adapter as forward processing.
Recovery still has no provider or credential redispatch port; it retains the
original operation, observation and reservation.

### Clock rollback floor

A slow time response previously cleared the whole sample. This erased the
accepted revision/wall-time floor as well as freshness, allowing a subsequent
older sample through the first-sample path. Slow-response rejection now retains
the old floor. Age checks still reject stale use. Replayed or regressing time
and failed evidence still fail closed; refreshing time cannot clear a permanent
fence or mint new final-use authority.

## Verification classes

Native regressions cover inbound stalls, completed-response backpressure,
entered-handler cancellation and panic, denied/changed peers, queued expiry,
same-poll expiry, idle sample refresh, slow-response floor preservation and
permanent-fence preservation. Framing phase tests use Tokio in-memory duplex
streams through the same production helper. They do not establish Unix kernel
peer authentication or service-manager behavior.

The two framing defects and clock-floor regression failed before their fixes.
The idle-clock reproducer models the old Recover preflight at the component
boundary; it is not a protected multi-UID runtime execution receipt. The
ordinary consumer subprocess regression now requires new legitimate work and
original Status to survive a partial-frame timeout.

Local Rust 1.96.0 results for the repaired source:

| Check | Result |
| --- | --- |
| `just fmt` | Passed |
| Package-scoped `just fix`, locked | Passed |
| Locked, all-target strict Clippy | Passed, no warnings |
| `just test -p codex-hepta-bao-adapter --locked --test-threads=2 --retries=0` | 139 passed, 6 failed, 2 original ignored subprocess fixtures |
| Included focused service/clock cases | All 16 passed |
| Existing TCP/TLS fixtures and 26-cut SIGKILL matrix | Passed; synthetic credentials only |
| Module-scoped canonical source-identity and closed-world binding checks | Passed, 37 paths; production implementation remains false |
| Whole-repository implementation-map and module-doc verification | Failed on other modules' historical anchors/current-source drift; not claimed green |

The six failures occur before the Unix consumer subprocess reaches readiness;
they are retained failures, not skips or passes. One of the two ignored fixture
entry points is invoked by the passing SIGKILL matrix. The other is the consumer
entry point used by the blocked subprocess tests. Real TCP/TLS fixture execution
does not establish an installed provider or multi-UID consumer composition.

The execution environment rejects AF_UNIX socket creation with EPERM, including
an approved local-only escalation attempt. Consequently actual consumer
subprocess, Unix service and protected multi-UID caller acceptance require an
environment that permits those sockets. No real credentials were read, no
production provider was contacted, and no installation, deployment or persistent
permission change was performed. Exact final-head hosted checks remain separate
from local source tests; historical installed-host claims were not requalified.

## Remaining product boundaries

This is a scoped transport/clock/recovery repair, not universal completion.
Final installed Agentd operation, independently governed provider and storage
qualification, same-source upgrade/recovery, target-device power-loss and
restore, independent operator acceptance and activation retain their existing
gates. No production, activation, merge or release claim is increased.
