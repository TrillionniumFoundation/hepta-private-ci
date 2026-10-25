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
