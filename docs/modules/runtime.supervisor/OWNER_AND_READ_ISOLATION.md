# Supervisor owner lifetime and observation isolation

## Scope and source boundary

This continuation builds on PR #1057 at
`eb3d65c02352efc8cd1abf7158c6ca449c3cb722`, based on main
`a126987b84737dbc2ee2592442a314117bddb4a2`. It preserves the earlier
Agentd build prerequisite, recovery signer, typed operator caller, strict CI
fan-in, and exact source/base-merge receipt work. It does not import other
modules' unmerged convergence branches.

This is source remediation, not production acceptance. The new Rust tests have
not been compiled or run in the editing environment. No production keys have
been generated or installed. No independent operator approval, deployment,
activation, release, force-push, or branch-protection exception is asserted.

## 1. Keep the kernel owner until every possible writer is gone

The previous outer function owned the instance lock separately from the
`Arc<DaemonState>` retained by connection/ticker tasks. Returning from or
cancelling that function did not prove every possible writer had stopped.
The daemon now retains the exact lock descriptor as the last field of shared
state. State destruction drops the supervisor before releasing that lock.

Connections belong to a `JoinSet`: completed entries are reaped during service;
normal shutdown stops accepting and drains accepted requests; error shutdown
aborts and reaps them. Dropping the server future aborts its task set. A drop
guard cancels the ticker when the enclosing daemon future is dropped.

A cancelled response waiter is not evidence that a synchronous mutation has
stopped. Each blocking owner operation owns both its state reference and its
single execution permit until the actual callback returns. An already-running
operation can therefore finish after a client timeout, while preventing a new
daemon from acquiring the same owner. The client must inspect durable state;
it must not treat timeout as terminal non-application or blindly retry.

A worker panic poisons the execution lane, invalidates observations and cancels
the daemon before returning capacity. Queued work checks poison/cancellation
before running. Normal daemon completion reports an error after owner failure.

### Lock file rules

`daemon_owner.rs` opens with `O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`, checks the
opened descriptor's regular-file type, effective-user ownership and single
link, and acquires `flock` before changing mode or contents. It verifies the
path still names the same device/inode. Mode changes and PID writes use the
held descriptor. A losing contender does not chmod or truncate the live owner.
The lock file is never unlinked on release: replacing it would create a second
lock domain. The containing directory remains trusted and owner-controlled;
this is not a sandbox against an attacker who can replace that directory.

## 2. Separate observation reads from serialized lifecycle I/O

`daemon_read_view.rs` stores an immutable, bounded `Arc` observation behind a
short read/write lock. The view includes at most the supported roster bound.
`Health`, `Roster` and `Snapshot` clone that observation without acquiring the
lifecycle mutex or reading the filesystem. Serialization/copying happens after
the observation lock is released. This is not a lock-free implementation.

The capture timestamp is taken before registry I/O. Views older than two
seconds, future-dated views, a poisoned view lock and failed refreshes return
`control_state_unavailable`; a failed capture cannot extend a previous view's
freshness. A captured recovery-required view reports `ready = false`.

Observations are deliberately not atomic authority reads. They can lag a
concurrent transition within the freshness bound. `ReleaseSelection`,
`ProductionMutationStatus` and every mutation still use the live owner path.
A cached fence does not authorize anything: the original live CAS, signature,
release, generation and recovery checks remain unchanged. The two-observation
operator inspection from `PRODUCTION_CONTROL_RUNBOOK.md` remains only a
consistency check; the daemon performs the decisive live validation.

### Bounded execution and scheduling

`daemon_execution.rs` offloads synchronous steady-state lifecycle work to the
Tokio blocking pool. One retained permit serializes the existing owner; there
is no unbounded queue of submitted mutation callbacks. Incoming connection
capacity bounds FIFO semaphore waiters. Admission waits at most 250 ms before
returning a busy rejection with no operation admitted. Cancellation of a
waiting acquisition does not reserve or start an operation. A FIFO wait also
avoids letting an overdue ticker continuously overtake waiting requests.

The existing release resolver can run its read-only nested blocking task while
the owner operation is awaiting it; this does not create another lifecycle
writer. Started owner callbacks are not made cancellable by a timeout.
`spawn_blocking` does not provide that guarantee. Stuck kernel/filesystem I/O
may hold ownership beyond the connection deadline; host-level termination
and subsequent durable recovery remain separate operational actions.

Startup registry loading/recovery is still synchronous. Mutations and tick
still share one lifecycle mutex and a whole-fleet view refresh. This patch is
not per-Agent actor isolation, a short-only global commit coordinator, or proof
of cross-Agent mutation latency. Those remain mandatory before claiming the
complete concurrency stage. No new public crate API or Cargo feature is added.

### Telemetry

At most once per five seconds of completed ticks, bounded diagnostic lines
report mutex acquisition count, cumulative/max wait and hold microseconds,
completed owner callbacks, busy rejections and maximum scheduled tick delay.
These aggregates are diagnostic only: they are not latency histograms,
p95/p99 SLO receipts, durable audit records or authorization evidence.

## 3. Protect provisioned public verifier material

The existing `hepta-supervisord` grant/H7 verifier CLI is retained. Public keys
are loaded only from absolute regular-file paths using a bounded read from the
opened descriptor. On Unix the loader refuses symlinks, multiple hard links,
group/world writable files and ownership other than root/effective user. It
checks device/inode on open and checks metadata stability after reading.
`O_NONBLOCK` avoids waiting on a FIFO substituted at the final component.

The maximum input is 128 bytes; the existing 32-raw-byte and 64-hex-character
formats remain supported, including bounded surrounding whitespace for hex.
The loader does not rewrite key files. Parent directories and the external
provisioning ceremony must remain protected. Descriptor checks are not a
cryptographic distribution or live revocation service.

Rotate grant and H7 verifier configuration as a controlled operator action,
with independently authenticated signer IDs/epochs and public-key digests.
Restarting the daemon changes the supervisor epoch; obtain new evidence and
freshly signed decisions for the replacement. A changed file does not silently
hot-reload the in-memory trust root. Do not manufacture signer material in a
qualification job and call it an independently provisioned production key.

## 4. Qualification contract

The fixed `products` plan now also runs `--bin hepta-supervisord`, so the public
key loader's six binary tests execute rather than merely compiling under lint.
Both library profiles require the 15 new owner, cancellation, FIFO admission,
shutdown and read-view tests. Receipt assembly verifies their exact `PASS`
names in addition to the existing exact candidate/context/command/log and exit
checks. Aggregate passing counts cannot cover missing, skipped, failed or
similarly named replacements. Parent commands omitting binary tests cannot be
reused for this candidate.

The known ignored paired-child helper is not a qualified product scenario;
its existence is not a mandatory test pass. No blanket acceptance of skipped
required tests, retries, `continue-on-error` or fabricated success is added.
The source binding already includes the entire supervisor directory and this
document. Keep `IMPLEMENTATION_MAP.sourceBase` as provenance: the current
commit/tree belongs in externally emitted execution receipts, not inside the
same self-referential source commit.

### Executed locally

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v scripts.test_hepta_supervisor_ci`
passed **20 tests, zero failures, zero skips**. These are Python receipt-policy
and filesystem-reader tests with synthetic runner output. They are not Rust,
daemon, cryptographic, target-host, capacity or performance qualification.

The editing environment has no Rust/Cargo/rustfmt toolchain. Rust compilation,
formatting, Clippy and the 21 new Rust tests are pending real Linux/macOS
source-head and synthetic-merge execution. The 256-observation Rust test is an
in-memory addressability test, not 256 running Agents or a mixed-load SLO run.

## 5. Remaining acceptance work, in order

| Gate | Required evidence |
| --- | --- |
| Trusted main | All applicable exact-head and ordered-parent synthetic-merge checks terminal green, then merge without bypass and recheck exact main. Resolve remaining dependency, feature-policy, lint and projection failures rather than hiding them. |
| Production control | Execute real operator caller -> pinned-verifier daemon -> process -> durable intent/release state -> audit observation; provision independent keys; close writer API/permission inventory and authenticated rotation/revocation. |
| Concurrency | Split per-Agent ownership without weakening global registry/release CAS; retain a short shared commit boundary; remove whole-fleet I/O from unrelated Agent mutation waits; obtain mixed-load measurements and actual histograms. |
| Target-host faults | Final deployment binaries, pinned platform/filesystem and raw receipts for every row below; CI runner smoke or source fixtures are insufficient. |
| Independent acceptance | Separately identified security reviewer and operator, authenticated current-candidate/artifact approval, successful recovery drill, bounded canary/rollback and explicit release decision. The patch author cannot issue independent approval. |

### Target-host matrix still requiring execution

| Scenario | Required invariant / retained evidence |
| --- | --- |
| SIGKILL at spawn, lease and intent boundaries | No duplicate effect or unsafe PID adoption; recovered generation, intent digest and exact observed process identity. |
| ENOSPC, torn write, rename and directory fsync failure | Never claim commit from an uncertain publish; preserve/quarantine exact predecessor and acknowledged journal boundary. |
| PID reuse, stale lease and permissions/artifact replacement | No signal to unrelated process; verify executable digest and ownership before use. |
| Flapping and durable-work drain | Durable bounded restart budget; no false drain acknowledgement with outstanding work or unknown effects. |
| Upgrade / rollback at each durable phase | Unique terminal reconciliation; old epoch/generation/intent/release substitutions rejected. |
| Daemon cancellation with live callbacks | Instance lock remains held through callback/destructor completion; replacement cannot overlap the writer. |
| Service manager restart | Observed old-process termination or exact adoption; fresh epoch and release artifact binding. |
| 256 real Agent pairs with slow/failing peers | Actual health/status/mutation latency, tick delay, CPU/RSS and cross-Agent isolation, not generated data. |
| Sustained soak and restore | Monotone counters, bounded metadata, no resource/descriptor leaks, authenticated restore and auditable recovery. |

Do not set deployment qualification, independent acceptance, activation or
release to true until those independently retained receipts exist. The
repository can define and test these gates; it cannot create evidence for an
unexecuted host experiment or self-appoint an independent accepting operator.
