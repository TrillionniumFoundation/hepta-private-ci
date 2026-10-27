# Trusted original Root production assembly

`attach_root_production_host` consumes the trusted launcher's original public
bootstrap, five fixed-purpose connected streams and a separately retained Root
pidfd. It installs the recovered original owner and runtime operation configuration
together only after every check succeeds. The default process-environment entry
still grants no production capability. An embedding must explicitly supply this
assembly and retain its attachment through original daemon shutdown.

The entry rejects a root consumer, a different PID/start/boot, a different Agentd
identity or spawn, a non-Current checkpoint, an alternate signer, aliased consumer
directories, malformed time bounds, and conflicting configuration. The original
Root writer proof and live feed must agree. Both original FinalUse consumers open
their existing private journals against their separate original Root frontier
lanes. The same issuer key, protected clock and revocation feed are retained; no
local issuer, clock, frontier or recovery-cut fallback exists.

The actual Root `read_head` response supplies the opaque checkpoint token. The
response schema, correlation ID and complete head must match the trusted
bootstrap. The factory never synthesizes that token from a local digest. Exact
recovery binds the original SQLite commit hook, read-only observer and fixed
Current publisher before exposing a writer. Ordinary FinalUse publication uses
`hepta-memory/ORIGINAL_CURRENT_BOUNDARIES.md`.

The attachment provides the original typed issuer, original consumer handles,
checkpoint and recovered host to trusted embedding code. It does not attach a
fake default destination. Original Agentd runtime attaches dispatchers from the
installed operation configuration without reopening a store. Direct embeddings
can use the same existing `attach_target` API on a wrapper clone over that same
writer. The primary consumer selection does not widen Root policy: Root's original
lease still checks exact subject, destination, scope and payload digest, and the
signed grant binds the complete original request at final entry.

Ordinary initialization failure after the database opens awaits the original pool
close barrier before releasing the owner guard. State already advanced in Root or
an original consumer is retained after failure. It is never deleted or reset for
retry. Initialization and close must be awaited to completion; they are not
externally cancellation-safe. Release the daemon/config and external host clones
before `AgentdRootProductionAttachment::close`. The Root session remains live
until the owned host's pool-close barrier completes.

The independently executed privileged qualification uses a new root-owned bind
mount and an actual UID 60001 client with all capabilities cleared and NNP set.
The client calls this factory, prepares through the original SQLite writer,
requests a real typed grant from the original Root issuer, consumes it through
the original FinalUse owner, withholds an explicit fixture target's reply, then
uses independent observation to settle and retire its receipt. The parent Root
process separately compares its retained Current head with the original writer's
reported complete cut. Root state and consumer/SQLite state are in separate
permission domains. No existing service or private key is used.

This qualification is explicitly `production_ready: false`,
`real_application: false`, and `native_hos2: false`. Its destination is a controlled
application-receipt fixture, not a GUI or kernel proof. Native Asterinas execution,
actual application control and cross-boot publisher adoption have separate gates.
The full Agentd library passed 301 tests with 26 skipped qualifications. The actual
Root/SQLite composition passed in 3.164 seconds (`root-composition-actual-root-02`).
The first attempt was denied because the fixture lease's payload digest differed
from its real request; only that fixture input changed. Original policy checks
were preserved. Keep both attempts as evidence of the exact binding boundary.

For development, build the original Root/client binaries with the locked graph;
run the owning Agentd suite through `just test`. The ignored
`root_five_lanes_compose_original_writer_and_publish_current_before_receipt_retirement`
qualification requires a fresh isolated Root bind, all five lanes and the original
peer qualification executable. Never target an existing authority directory.
Finish with scoped `just fix -p codex-hepta-agentd` and `just fmt`.

## Observation concurrency

The original 500 ms age limit includes the request's start, response validation
and consumer synchronization. An expired sample, clock rollback, malformed or
changed identity, poisoned lock, lost Root lifetime or uncertain stream still
closes authority. No timeout or lease is extended by local scheduling delays.

Cache acceptance and current reads now sample BOOTTIME after acquiring the
retained-state lock. Sampling before the lock allowed a delayed reader's earlier
sample to arrive after another reader had advanced `last_checked_ns`, falsely
classifying a monotonic clock as backward. Real backward samples still fence.
Synchronous authority reads remain nonblocking: lock contention returns Busy,
and an incomplete consumer barrier returns Updating. Neither returns an authority
observation. The post-accept refresh check tolerates only Busy, keeping the feed
alive for its next bounded refresh; it does not accept Updating, stale evidence,
poison or any other Unavailable result. Caller failure does not retry an effect.

Deterministic tests check that both real sampling callbacks execute while the
cache mutex is held, that a contended reader never samples or gains authority,
and that the actual Root session's post-refresh check preserves the feed only
for Busy. Backward clocks, clock failure and poisoned locks remain permanently
fenced alongside the existing expiry and revocation tests.

### Application executor independence

After the original bootstrap proof and first observation, the session moves its
already connected Unix stream to one dedicated `hepta-root-feed` thread with a
current-thread Tokio reactor. It duplicates the original held pidfd for that
reactor; both descriptors refer to the original Root process. This transfer
does not reconnect, repeat identity discovery, renew the session lifetime or
change the request-start refresh schedule. The synchronous verifier keeps its
original held pidfd and checks it directly. Transfer or startup failure fences
the cache before returning an error.

The read feed therefore does not need an application executor worker to wake
its timer, service its socket or observe the original pidfd. It still requires
OS scheduling and the original Root service to make progress. The existing
500 ms cache and exchange bounds can still refuse under those delays. A
successful later reply cannot revive an expired earlier observation.

Session destruction fences authority synchronously, then sends cancellation
to the dedicated reactor without joining on the caller's executor. Cancellation
also interrupts an in-flight exchange and drops the original channel. An
unexpected worker exit fences the cache. Startup owns the cancellation guard
before awaiting readiness, so abandoning async bootstrap requests shutdown.
Already running consumer synchronization may finish its existing blocking
work after cancellation, but cannot clear the permanent authority fence.

Development regressions in `src/root_observation_isolation_tests.rs` use the
existing same-UID synthetic-key peer and original durable owners. They block
both application executor workers while the peer continues on its own thread,
check freshness beyond the original 500 ms window, and check immediate fencing
and channel closure on session destruction. All blocking fixture threads have
finite escape bounds and are released before assertions. Run the owning suite
with `just test -p codex-hepta-agentd --lib --test-threads 2 --retries 0`.
These fixtures do not qualify production deployment or the native guest.

The progress regression holds the original activation/refresh serial barrier
until a diagnostic confirms that the dedicated feed is actually waiting there.
It retains the original 650 ms stall, 500 ms age refusal and frozen first-failure
assertions. After releasing the barrier it waits for an actual late reply before
checking that authority stays fenced. The former application-worker starvation
fixture is obsolete because application work no longer owns the feed reactor;
its earlier failing run remains evidence rather than a qualified result.
The owning Agentd library passed 306 tests with 26 skipped qualifications in
44.364 seconds for this stage. That includes the five new concurrency regressions;
it is not a rerun of the privileged Root or native guest qualification.

The earlier `root-launch-actual-root-01` failure remains unclassified: it logged
only `root writer observation is unavailable or fenced`, without the failing
phase, sample age or cache reason. Its successful `02` comparison used the same
test executable but a different client-helper ELF. These fixes establish two
reachable concurrency defects; they do not retrospectively establish either as
the cause of that particular failure. Preserve both original runs.


## Bounded authority failure diagnostics

The original observation cache and stream retain one first-published refusal
record in a shared `OnceLock`. The record contains a static stage plus optional
scalar clock samples, failed exchange duration, OS error kind/code and pidfd poll result.
It contains no request/response body, key, policy, grant, path or account identity.
There is no hot-path log output or diagnostic I/O. The original writer's refusal
text includes this bounded record; cleanup cannot overwrite it. The cache publishes its fence before recording its own failure. Stream and
lifetime failures retain their original rejection and session cleanup order. An atomic first-publisher
claim prevents diagnostic contention from blocking; a preempted publisher may
temporarily leave the record absent. Concurrent failures do not establish global
causal order.
The writer also labels initial open, final open and recovered-host verification
errors without changing the original error variant or verification call order.

This is evidence for debugging refusal, not an alternate authority state. The
500 ms maximum age, 100 ms refresh interval, Root lifetime checks, irreversible
fence, no-reconnect rule and all original proof/revocation checks are unchanged.
`Busy` and `Updating` neither supply authority nor claim a fatal first-failure
record. A new sample still cannot revive an expired previous sample. Deterministic
cache regressions retain the exact failing times and verify that later cleanup
and attempted acceptance cannot overwrite the first refusal.
