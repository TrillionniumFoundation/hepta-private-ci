# Five original Root lanes and two original consumers

The exact no-effect component source, recorded by the original tracked-input
snapshot and live-source SHA256, passed 41 original scoped tests and both real
Root/UID60001 SSD compositions. One original independent-handle CAS race failed
its first attempt and passed its runner retry; the complete failure remains.
This is not a zero-retry or whole-workspace qualification.

The Root positive case passed in 3.41s test time (3.562s wrapper), with actual
writer-proof reading at 25ms and feed reading at 11ms. The same Root PID served
all five fixed lanes. Two actual original FinalUseAuthority consumers used the
same canonical signer and separate Root directories/local journals. Exact
distinct nonce/sequence claim, enter, replay refusal, full consumer frontier CAS
and Root readback passed. The original checkpoint acknowledged Current1,
Dirty2 and Fenced3, duplicate ACK and stale-CAS refusal. The expired-consumer
case retained the original two-second authorization and three-second wait,
emitted no response prefix and left both frontiers and Current1 unchanged.

The previous checkpoint-only `74e8ef667` phase's 41-test scope, actual positive
initialization failure, 141ms diagnostic followed by failure, and expired-writer
negative success remain as separate historical records. Private syscall trace
files and private state are excluded; the metadata-only I/O summary remains.
The new SSD fixture is a fresh Root0700 namespace on device2050, distinct from
build/data device2067. No previous authority was reset or migrated. The fixture
bind is not installed for automatic restart after reboot.

Scoped fix passed, followed by the original default and explicit committed-range
formatter/check. The final code leaves are `8d5172d73` and `f02d0a259`; original
test bytes and later mechanical formatting are separately recorded. No semantic
test followed that finish phase. This source-scope evidence does not transfer
to a later combined integration tree without its own required validation.

The included public bootstrap example is byte-identical to the actual Root
fixture output, including its original complete Current cut, proof, public key,
two same-signer consumer owners and five paths. That fixture has exited and the
example cannot authorize deployment. Its controlled stdin transport is not the
production sealed-FD loader. No actual Notes/HOS2 effect, native five-lane service,
complete Prepare/Commit writer publication, dynamic operation admission, cold
writer recovery or Dirty recovery is qualified here.

See [the complete manifest](publication.json),
[the consumer module contract](../../HOST_CONSUMER_FRONTIERS.md) and
[the checkpoint module contract](../../HOST_COGNITIVE_CHECKPOINT.md).
