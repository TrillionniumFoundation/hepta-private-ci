# Original HOS2 adapter: explicit G2 image attachment

The original `AgentdHos2Device` now has separate entry points for the two
management-image discovery profiles supplied by the desktop kernel. They
reuse the existing device transport, immutable install request, observation,
history query and retirement-permit path. They do not construct a writer,
issuer, Registry record, Supervisor generation or FinalUse grant.

| API on the existing Linux-exported `AgentdHos2Device` | Accepted discovery record |
| --- | --- |
| `from_bootstrap` | Original G1-d HOS2BOOT version 2, declared size 192; existing behavior retained |
| `from_g2_initial_bootstrap` | G2 initial Manager or Recovery, version 3, declared size 200 |
| `from_g2_successor_bootstrap` | G2 management successor, version 4, declared size **240** |

The API selection is explicit. The old constructor does not automatically
recognize new profiles. G2 constructors take the already-open control `File`
of the current image and the sealed bootstrap discovery bytes. They check the
actual `getpid`/`getppid`, Root PID 1, distinct valid role PIDs, exact original
slot/generation layout, 50 ms write ceiling, 100 ms period and finite 300 s
initial grant. Version 4 additionally checks the actual self PID, local
capability space, nonzero launch generation and zero reserved bytes 232–239.
Both reject nonzero padding and records exceeding the 4096-byte page bound.

After those checks the original QueryAbi exchange must match this image's
namespace, boot identity, bounds and five operations. No management operation
is sent during attachment. The kernel still checks the actual `Process` and
image epoch on every ioctl; copying a page or receiving a file from another
process never grants a capability. QueryAbi is not an attestation of a build
profile or proof of a durable Hepta transaction. A real run must also bind its
kernel source/profile, embedded original ELF and actual guest evidence.

Root role 4, Workload role 2 and version-4 history-only role 5 are rejected by
both management constructors. In particular, a history successor has its own
local namespace at offset 208 while offsets 112/128 refer to retained old D
namespaces; those old namespaces must not be treated as new effect authority.
A separate history-only composition remains necessary. The kernel launch
generation is also not the original Supervisor's Registry generation, and a
launcher receipt is not proof that Root persisted it before `AckSaved`.

## Implementation and validation

The new profile checks live in [hos2_device_bootstrap.rs](src/hos2_device_bootstrap.rs),
called from the existing [device adapter](src/hos2_device.rs). The
[regressions](src/hos2_device_bootstrap_tests.rs) exercise that real adapter with
a bounded QueryAbi transport. They cover matching initial/successor Manager
and Recovery, unchanged immutable install requests, wrong actual process or
parent, aliased PIDs, wrong slots, profile confusion, 232 versus 240 bytes,
truncation, extra bytes, reserved fields and mismatched QueryAbi namespaces.
Invalid discovery does not reach the transport. These tests are library
regressions and cannot establish that the kernel or an original owner ran.

Run the owning crate with the original Rust 1.96.0 environment and original
dependency graph:

```sh
cd codex-rs
just test -p codex-hepta-agentd --lib hos2_device
just fmt
```

The finite G2 executable still needs to compose the original Supervisor,
Registry, protected Root Current/issuer, durable writer, synchronous FinalUse
device and actual retained storage. This interface change is a prerequisite;
the old peer qualification example and a successful ReadUsage probe cannot
replace that executable or its native writer/recovery evidence.

## Original Root process credential contract

The shared Root `verify_process` factory now receives both the configured UID
and GID. It requires all four kernel-reported real/effective/saved/filesystem
UIDs and GIDs to match those inputs, together with the existing exact boot and
start identity, empty supplementary groups, empty capability sets and
`NoNewPrivileges`. Both the authority service and native launch checks use
this same factory. This closes a missing GID assertion in those checks; it is
not a claim that a process could bypass the remaining pidfd, proof, lease,
Root bind or protected channel checks.

The explicit privileged regression creates only two temporary child
processes, drops their credentials with `setpriv`, and observes their actual
`/proc` status. Each correct UID/GID is accepted and the same UID with the
other expected GID is rejected. Its registration generation comes from the
original temporary Fleet Registry `Starting` transition. It does not start
an authority service or create a writer. Run it separately as Root in the
isolated validation environment; a default skipped test is not evidence:

```sh
just test -p codex-hepta-agentd --lib --run-ignored only original_owner_process_rejects_same_uid_with_different_gid
```

This Linux host regression still does not qualify native G2 execution.

## Root handoff from original registered state

`PreparedHostAuthoritySession` fills the production gap between the original
Root service and its existing sealed public descriptor. Its single open-only
factory reads the Root0600 service/registration files, verifies the retained
actual daemon pidfd, and retains the original service. `seal_bootstrap` reads
that same service's issuer, clock, checkpoint and consumer objects, including
their locks and closed state. It never reopens those objects by file path.
`serve` consumes the same non-Clone handle to serve the original fixed lanes.
The public `serve_with_text(text_file, ui_pidfd)` method consumes that same
handle for the original native text path, including its profile, identity and
socket validation; a launcher must not reopen another session after capture.
The established `serve_host_authority_session` entry delegates to this same
factory; its optional native-text sibling retains the original text path.
The original `AuthorityLeaseRegistry` retains its exclusive file lock in
`Store::_lock`; verifier clones share the same `Arc<Inner>`. Both the retained
issuer and writer keep that original verifier alive. A second open is refused
as `StateLocked`, and capture must not work around that original owner lock.
It requires the existing writer, protected Current and both original consumer
frontiers. It never initializes a missing record, signs a proof, invents a
writer identity, or resets a nonce journal.

Inside the original writer's live lease fence it reads the retained canonical
proof, issuer revocations, exact Current and two retained frontiers. The
existing backend checks and post-I/O time/owner checks remain in force. It
seals the original public data and rereads those heads before returning the
descriptor; observed changes or Dirty/Publishing/Fenced state fail closed.
The two local journal paths come from the explicitly supplied original
daemon-owned private parent. No journal is created by capture.
The capture and actual listener bind share the original read-only runtime
path validation: distinct absolute lane names, one Root:peer-gid parent with
mode 02710, and Root-owned ancestors without group/other write access. Capture
checks before sealing and before returning; serving repeats admission before
binding. This observation neither reserves names nor creates sockets.

This bounded capture is a handoff observation, not an atomic transaction across
all stores or a live grant. After receiving it, the original Root session,
protected checkpoint client and FinalUse owners must still validate live
currentness. The producer must retain its own actual pidfd for the daemon and
serve the original five fixed lanes. The G2 Root entry still has to perform
that FD transfer and full finite writer/device/recovery sequence.

The existing explicit privileged five-lane service qualification now captures
and serves with this same prepared handle, compares its bytes with an independent readback
oracle, and rejects wrong daemon pidfd and same UID/wrong expected GID. The
same test requires a second valid session open to fail with the original
`AuthorityLeaseError::StateLocked`, not an unrelated admission error. The
retained capture also rejects an actual wrong runtime group, writable runtime
mode and writable ancestor with the specific custody errors; those checks do
not open a second owner and cannot be masked by its lifetime lock. The
backend qualifications also check that capture refuses a Dirty checkpoint and
cannot revive a closed consumer. These checks need their existing explicit
Root/data-bind environment and must actually run; compilation or ignored
test discovery alone does not establish passage.

## Fresh original state before releasing a daemon

`FreshHostCognitiveState::prepare` accepts the original registered identity,
requires the exact Registry `Starting` record and immutable manifest/layout,
and admits only an empty cognitive directory still under Root0700 custody.
It holds the original Agentd writer lock, opens the original CognitiveStore,
captures its coherent cut and awaits complete SQLite pool shutdown. The
non-Clone result retains that original lock and has no public cut constructor.
Wrong generation, peer-writable custody, existing bytes or concurrent writer
ownership cannot fall back to initialization. Failed or partial state is kept.

After the original administrative factories have created the issuer/clock and
registered the actual writer lease/proof, the Root entry can consume this
preparation in `PreparedHostAuthoritySession::initialize_fresh`. This shares
the ordinary registered writer factory, derives the checkpoint binding through
the original signed proof, and creates only absent, distinct direct children
of protected state. Original Current and both original consumer-frontier
backends are initialized inside the existing live writer lease fence and then
retained for capture and serving. Registry and actual pidfd/UID/GID/lifetime
are checked again before returning. No nonce journal or runtime authority is
inferred from these new protected heads; the real daemon still has to open
its original FinalUse owners and protected recovery writer.

The explicit five-lane Root qualification now uses this original fresh
preparation and head publication path. The additional real Registry/SQLite
regression is `original_fresh_state_retains_writer_lock_and_refuses_nonempty_or_changed_registry`;
run it with `just test -p codex-hepta-agentd --lib --run-ignored only`
and that exact test filter, as Root with an explicit Root-owned
`HEPTA_CHECKPOINT_TEST_ROOT`. It checks the actual writer lock, refusal of a
second fresh preparation, unchanged original cut, and Registry transition
fencing. These host tests still do not qualify the native G2 finite sequence.

## Initial protected writer receipt

The public bootstrap carries the complete original head, not its opaque Root
token. `AgentdUnixCognitiveCheckpointTransport::into_protected_inputs` consumes
the sole already authenticated Root lane, reads its original `ReadHead` ACK,
requires exact equality with that trusted Current head, and preserves the
server's token bytes. It does not compute a token from public JSON. Its output
can enter `AgentdProductionWriterHost::open_with_protected_recovery` with the
original live Root session's authority/verifier and writer lease identity.
That original factory still performs exclusive exact-cut recovery, authentic
whole-owner binding and another Current check before creating the writer.
Any bootstrap mismatch, refusal, malformed response or cancellation drops the
consumed lane; no retry or reconnect is added. Framing regressions use explicit
same-UID protocol peers and do not claim live Root or native G2 qualification.
