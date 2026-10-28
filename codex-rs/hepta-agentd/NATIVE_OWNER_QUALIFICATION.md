# Original owner in a sealed native guest

`qualification-native-owner` explicitly enables the
`hepta-native-owner-qualification` binary. Default Agentd gains no bootstrap.
Build with locked normal dependencies; no example/dev feature unification or
legacy learning-writer qualification feature is required.

The same immutable static ELF supplies all original HOS2BOOT v2 roles. Its
read-only kernel auxiliary page selects the role and must match the actual PID:
1 is original Root, 3 is original Agentd/AppServer, 2 is the UID 60001 workload.
Arguments/environment do not select authority. Native slots retain their
original Process/image binding; fork, exec and userspace digests cannot transfer it.

Role 3 initially has root credentials. In that same image, before threads or IPC,
it opens root0600 native control and retains the actual Root pidfd, then clears
supplementary groups, bounding/ambient caps, locks securebits, changes all IDs to
60002, clears remaining capabilities and enables NNP. Independent readback checks
the envelope. This short startup belongs to the TCB; it is not nonroot kernel birth.
Native MAC N0 does not yet admit this complete startup and five-lane connection.

A fresh private ext2 disk supplies the root0700 bind and separate UID 60002
SQLite/fleet and consumer namespaces. Root coherently captures a fresh original
SQLite genesis before handing it to Agentd, initializes its original protected
signer/lease/checkpoint/frontiers, pins the actual peer and exports the public
bootstrap. The ordinary factory installs the original writer and SQLite commit hook.

Root first reads the actual native resource revision and checks its boot identity,
cap and period against the sealed bootstrap. Kernel bootstrap may legitimately
advance that revision while configuring the resource; revision one is not an
admission requirement. Root selects the original request with that observed
precondition and the role-3 delivery space. Its private, root-owned intent file
retains those exact bytes alongside the public bootstrap. Agentd independently
reads the resource and requires its original request constructor to reproduce
the exact intent before opening the production attachment. A changed precondition,
zero or exhausted revision fails closed; the intent file grants no authority.

The fixed K/D and Root lease bind exact native scope/payload. A wrapper performs
the actual ioctl once and withholds its returned reply; it cannot fabricate an
Applied receipt. Independent native query observes D; the original outbox commits
the terminal and publishes Root Current before its durable-prefix proof retires
history. Native query must then report retirement, and separate Root compares
its complete Current cut. Wrong-scope grant refusal must cause zero device entry.

The original daemon/AppServer must start and report promotion_ready. This fixture
does not run Supervisor or promote fleet Starting to Running. It performs no
model inference, networking or third-party device action. Its newly initialized
Root is an isolated qualification instance; production_ready remains false.

Ordinary startup refuses existing state. The separate VM-crash case below admits
only read-only historical observation; it never adopts a cross-boot writer.
Wrapper reply loss is neither a kernel copyout fault nor physical power loss.
Source, static linking and the disk probe alone never constitute native owner success.
Record final source/lock/ELF LOAD and MEMSZ, kernel/profile, disk identities/hashes,
raw serial markers, original readiness, SQLite/Root terminal and retirement,
every failed attempt and these scope limits with the actual result.

## VM-crash historical case

The isolated trusted initramfs may contain a root-owned regular
`/.hepta-native-case.json` with the exact JSON string `"crash_after_applied"`.
This selects failure injection, not a kernel role or an authorization scope.
Without it the complete fresh chain above remains the default. A caller cannot
select historical admission directly; Root requires its preceding protected
receipt on the same independently retained disk.

After the real ioctl and withheld reply, Agentd queries its own native D, joins
the original daemon, verifies the outbox remains Indeterminate, and obtains a
complete acknowledged cut through its original writer's `checkpoint_current`.
It publishes a private candidate and stops its process. Root observes two stable
all-stopped task enumerations, compares the full protected Current and actual
peer lifetime, and reads the native resource's revision/cap/period independently.
Root has no role-3 delivery-history slot; it does not borrow that process's FD
or claim its resource observation is a D receipt. The separate Agentd history
observation and Root resource observation are retained explicitly.

Only after the original Current, candidate and private Root receipt are durable
does Root print `HEPTA_NATIVE_VM_CRASH_READY`. The host qualification runner must
SIGKILL its own QEMU, reap that exact child, retain exclusive ownership of the
same newly generated disk inode, and start a second QEMU with the same ELF and
kernel. A new boot UUID alone is not predecessor-death or disk-exclusivity proof.
This tests VM process failure with host storage still running, not power loss.

On that second boot, Root loads its full old protected head and requires exact
equality with its independent pre-crash receipt: Current, no proposal, no unknown
acknowledgement repair. It publishes only a read-only admission. UID 60002 uses
the original active WAL-copy readonly recovery and complete Root cut to validate
the old K, exact payload, old D and Indeterminate row. It does not connect the
issuer, open a writer, register a successor, renew a lease or retire history.
The original HOS2 adapter rejects the old boot before issuing an ioctl, yielding
Unavailable/Unknown; this is not a kernel-returned HistoryLost observation.
Root and Agentd independently read the new-boot native resource and require the
same boot identity, actual revision, cap and period. Neither resets a revision nor
assumes the bootstrap performed zero updates. Root then
independently rechecks the full unchanged protected head and the observer report.

The host entry point is the separately pinned `run-native-owner-history.py`
qualification runner, using the same bounded G2 build/ELF checks as the complete
chain. Its output must bind both raw serial logs, pre-kill retained head, exact
SIGKILL/reap result, original disk inode and hashes, and unchanged source/artifacts.
Host parser examples are not guest evidence. This source addition does not by
itself establish native or cross-boot qualification; actual runs remain required.


## Refusal diagnosis

A native failure before `HEPTA_NATIVE_DAEMON_READY` is not a daemon execution or
terminal-state result. The original authority verifier preserves a bounded first
failure record, described in `ROOT_COMPOSITION.md`, and writer-open errors label
initial, final and recovered-host checks. Retain the complete error and its exact
source/ELF along with the original serial log. A generic unavailable/fenced error
without these details cannot establish that a particular clock, freshness bound,
thread scheduler or transport caused the refusal. A later Root peer error alone
cannot establish which side first became unavailable.

The native Root launcher also labels the original initialization, ownership
handoff, writer registration, consumer-frontier creation and bootstrap capture
errors. Authority initialization labels protected clock and original lease
stages. These are static operation names attached to existing errors; they
carry no policy, signing key or authority payload and never retry a failed step.
A generic pre-service refusal from an earlier artifact remains unclassified
until a corrected, source-bound artifact actually executes.

The native Agentd entry binds the process Codex home to the original registered
layout before creating its runtime, as the normal Agentd entry does. The
AppServer's required-SQLite-home comparison and shared original connection gate
remain active. If the original daemon finishes before readiness, qualification
awaits its actual result and retains at most 4096 diagnostic characters rather
than dropping the startup error. An earlier generic exit does not by itself
prove that home resolution was its first cause.

The native Agentd now uses the normal `arg0_dispatch_or_else` path rather than
empty `Arg0DispatchPaths`: it retains real current-image and helper paths for
the original AppServer and uses the ordinary runtime stack setup. The sealed
entry dispatches only original hidden helpers before requiring its bootstrap;
an ordinary qualification invocation still requires its sealed role. Helper
modes do not create a new Root, writer or HOS2 capability. The original dispatcher
remains the sole helper implementation, with no dummy executable or substituted
AppServer. The exact e537 guest exposed the previous missing executable-path
error; its failed readiness and private disk remain historical evidence.

The diagnostic stage changes no 500 ms bound, authority proof, policy, lease,
cache recovery rule or effect retry rule. Source review and host regressions do
not turn a failed native run into a success; the corrected evidence-bearing
artifact must still complete the actual native chain before the VM-crash case.

The read feed schedules its next serial exchange 100 ms from that exchange's
actual start, after acquiring the consumer-synchronization lock. A response or
consumer sync taking longer than 100 ms starts one next exchange immediately,
then re-anchors the deadline to that new start. There are no accumulated ticks,
overlapping reads or reconnects. BOOTTIME remains the authority clock; the Tokio
instant only schedules work. All response age, previous-sample continuity,
revocation synchronization and permanent fencing checks remain unchanged.
Real-clock Unix-stream regressions retain a pre-fix failure for 210 ms replies
and require 260 ms replies to fence specifically on the expired previous sample,
even though each reply meets the 300 ms transport limit. They do not establish
which native Root substage incurred delay or prove native qualification.

### Public failure phases after channel release

Root diagnostics use closed client/lane/operation/error enums and scalar timing,
OS-error and progress fields. They exclude arbitrary error Display text, stage
strings, request bodies, grants, signatures and key material. Each synchronous
Root `serve` owns an explicit local collector; the observation handler records
only its first closed writer-failure metadata. No collector is shared between
lanes or reused across connections, and recording does not change authority.

The public `serve` calls an inner function that owns the original stream,
channel and pidfd. Early checkpoint/constructor errors and exchange errors
return through that inner ownership boundary. Only after those resources have
been released, including the original exchange's permanent shutdown on error,
does the outer call print at most one writer line and one lane error line and
return the unchanged result. Synchronous diagnostic output has no bounded-time
guarantee; it cannot delay that original shutdown or resource release. The
collector cannot clear a failure, restore authority, retry or reconnect.

This diagnostic successor is source-only, pending review, the original 939-case
host qualification and a newly built exact static ELF/native guest. The real
9fb26ed5/e7ed68e6 exact guest exited 65 without timing out after 56.626 seconds;
its Root and owner errors were generic Unavailable, with no complete report.
The retained source-bound failure does not establish a particular cache,
reactor, transport, clock or storage root cause. Neither this documentation nor
the diagnostic source changes the original 500 ms bounds or 100 ms cadence.
