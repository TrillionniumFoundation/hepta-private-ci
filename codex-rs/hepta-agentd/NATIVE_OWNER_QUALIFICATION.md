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
New-boot native resource state must remain at its initial revision. Root then
independently rechecks the full unchanged protected head and the observer report.

The host entry point is the separately pinned `run-native-owner-history.py`
qualification runner, using the same bounded G2 build/ELF checks as the complete
chain. Its output must bind both raw serial logs, pre-kill retained head, exact
SIGKILL/reap result, original disk inode and hashes, and unchanged source/artifacts.
Host parser examples are not guest evidence. This source addition does not by
itself establish native or cross-boot qualification; actual runs remain required.
