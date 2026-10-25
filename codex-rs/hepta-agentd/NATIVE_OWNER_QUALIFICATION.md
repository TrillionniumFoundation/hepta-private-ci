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

Existing state refuses startup. Cross-boot adoption, real process crashes and
old-history Unknown/no replay still need retained-Current qualification. Wrapper
reply loss is neither a kernel copyout fault nor physical power loss. Source,
static linking and the disk probe alone never constitute native owner success.
Record final source/lock/ELF LOAD and MEMSZ, kernel/profile, disk identities/hashes,
raw serial markers, original readiness, SQLite/Root terminal and retirement,
every failed attempt and these scope limits with the actual result.
