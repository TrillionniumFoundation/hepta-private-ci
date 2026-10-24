# Native CPU owner continuity

This module connects the original Root authority, Fleet/Supervisor, protected
writer recovery and HOS2 owner to the restricted kernel successor factory. It
does not create another delivery counter, outcome ledger, signer, consumer
frontier or Current publisher. Native qualification requires execution of the
actual same-source owner ELF; host compilation and parser tests alone do not
qualify either scenario described here.

## Ownership and finite lifetimes

The initial bootstrap remains version 3 with Root, Manager, Workload and
Recovery. A later kernel factory receipt identifies actual new final images;
their version 4 bootstrap carries the actual PID, local capability namespace
and kernel launch generation. Each Host opens its own HOS2 descriptor in that
same Process before dropping to UID/GID 60001. Workload remains UID/GID 60002.

The original Supervisor allocates Agent lifecycle/spawn generations, owns the
actual child and reaps it. Kernel launch generation and original local writer
generation are separate values. Neither is substituted for the other. The
native driver consumes each original initial/successor slot once and cannot
create authority through an ordinary fork or exec.

Every Host retains the original 120-second session bound. Every writer is
issued a new 20-second lease. Each handoff opens the same canonical issuer with
a new 120-second Root lease, after revoking the previous lease in the same
original lease registry. The issuer key, original head, sequence, consumer
frontiers and signed writer registration remain in their existing stores.
Previously issued leases are never extended. Kernel Manager grants remain
300 seconds, Recovery grace remains 30 seconds and the independent kernel
watchdog remains 5 seconds.

The renewal acceptance campaign has its own 600-second outer deadline. This
deadline does not enter a Root/Host lease, authority feed, final-use grant,
kernel grant, watchdog, descriptor timeout or recovery grace. The original
four scenarios and the history-only scenario retain their 120-second outer
bound.

## Successful release is independently observed

The native command ingress closes admission and joins work through its
existing runtime. Unresolved queued or indeterminate work prevents successful
drain. The original writer publishes its release transaction and bound
Current, returning the actual `ProductionLeaseReceipt`. The native runtime
then closes the same SQLite pools and returns that receipt; it does not reopen
the database to fabricate a release summary.

The still-live Host sends this complete receipt over a separate bounded
observation connection authenticated with the original Root peer guard and
held pidfd. This connection uses the same five-second I/O timeout and finite
Host session. Root independently reads Current through its original service,
verifies the exact writer binding and publisher lifetime, and retains the
actual physical Current image. Root acknowledges the receipt's exact SHA-256
and the actual complete Current. Only after this acknowledgment may the Host
return normally.

Root subsequently requires the original Supervisor's actual successful
exit-zero event, actual reap, original retired-publisher observation and an
unchanged physical image. A sent stop request, readable pidfd, deadline or
closed connection is insufficient. The next protected writer factory consumes
this original material and signed predecessor proof. It advances local writer
generation and owner epoch through the existing owner APIs and verifies both
complete FinalUse frontiers before releasing the new Host.

The same release observation also guards final cleanup in the original four
scenarios. Their event schemas do not change: no continuity events are added
to their transcripts.

## Restricted factory, Root persistence and exact policy

The existing driver obtains `HOS2LRES` and `HOS2LWDR` directly from the actual
Root-only kernel launcher. Before child activation, it saves the full launch
and retirement bytes with their boot identity and generation using the
original `RootAuthorityDirectory` primitives. It verifies the same retained
file, including file/directory sync, and only then acknowledges the exact
kernel retirement receipt. Failed save or acknowledgment retains that same
pending transaction and blocks a new launch.

This Root record is an observation of a completed kernel transaction. It
does not represent a writer Current, local D/K, final-use grant or CPU effect
terminal. It can be saved before any newly launched Host becomes Ready.

The original protected source directory is:

```
/state/hepta-native/protected-source/authority/native-launch-observations
```

The bind-mounted protected path names the same files. Each record is at most
16 KiB, has Root UID, mode 0600 and one link; its directory has mode 0700. The
observation ID is `native-launch:<boot-32-lowerhex>:<generation-16-lowerhex>`.
The filename is `observation-v1-<sha256-of-id-utf8-lowerhex>.json`.

The complete original envelope is:

```
{schema_version: 1, observation_id: string, payload: byte_array}
```

The payload is the exact UTF-8 JSON encoding of:

```
{schema_version: 1,
 operation: "kernel.g2.launch-observation.v1",
 boot_id: [16 bytes],
 launch_generation: u64,
 launch_receipt: [128 bytes],
 retirement_receipt: [128 bytes]}
```

Saving the same ID and bytes is idempotent and resyncs the actual inode.
Different bytes for the same ID are refused. Disk/full/I/O failures stop
advancement. Cross-boot observation files confer no authority.

For an actual fresh Manager/Recovery pair, Root replaces exactly the two
preceding original HOS2 namespace policies using the canonical issuer store's
existing CAS. The expected old scopes must equal the two namespaces in the
actual policy-retirement receipt. The new scopes derive from the two fresh
kernel namespaces; both must differ from the previous ones. This uses the
actual registered writer boundary and original retained signed proof. It
does not reset an issuer head or consumer frontier. Exact already-retained
new policies are accepted idempotently; unexpected policy sets are refused.

A history-only image receives the original writer/checkpoint/consumer feeds
but no effect-admission policy. The native command boundary rejects Prepare,
Dispatch, DispatchCopyout and Window, and its monitor does not reauthorize
pending effects. It may observe and retire original retained D values. Its
Inspect and reconciliation usage fields are null; no ReadUsage, heartbeat or
live-workload test is used to establish its authority.

## Acceptance scenarios

`successor-renewal-v1` repeatedly completes an actual original Manager effect,
terminal Current, history retirement and a real usage window across at least
two CPU periods, then successfully releases and
reaps Manager and Recovery through the original Supervisor. Fresh pairs come
from the restricted factory. Each Manager is held until twelve seconds after
its actual writer issue time, leaving eight seconds of the finite 20-second
lease for drain, release, independent Current observation and exit. A slow or
failed drain fails acceptance instead of extending the issued lease.

The endpoint requires an actual new Manager `Applied.effective_ns` strictly
greater than the initial actual `ReadUsage.sample_boottime_ns + 330e9`, with at
least two distinct fresh pair generations. The same boot, workload, CPU
stable identity and original revision history are retained. Sleep duration,
host wall time, a new PID, an elapsed grant or a success boolean cannot satisfy
this condition. At most 64 Manager cycles are attempted.

`history-only-after-both-owner-exit-v1` leaves an actual Manager terminal
unretired, kills both initial privileged images through held pidfds and
observes actual SIGKILL exit using WNOWAIT. The factory must return EBUSY both
while those images are live and while they are zombies. The original
Supervisor reaps Manager and attempts its already-dead initial Recovery slot;
the original child guard reaps that slot. Only that independently verified
driver failure is accepted. Root waits for the actual persisted old writer
lease expiry, retaining the independent watchdog and original physical cut.

The next original Supervisor start receives the actual history-only image.
Its initial Current/material and both consumer frontiers must match the
original handoff. It queries the same retained D, retains the same local event
and terminal, and retires that history through the original durable prefix.
After an independently observed successful release/reap, the factory may
produce a fresh pair; a new original Manager must then produce a real Applied
CPU effect and a real usage window across at least two periods. No
history-only process is treated as a CPU issuer.

## Transcript contract

The existing `HEPTA_G2_EVIDENCE_V1` envelope, nonce and monotonically emitted
event sequence are unchanged. Only the two scenarios above use these extra
events. Complete original DTOs retain their native serde representation;
SHA-256 digest wrappers are lower-case hex strings and FinalUse frontier
`state_sha256` is a 32-byte array.

| Event | Exact payload keys |
| --- | --- |
| `kernel_launch_saved` | `boot_id`, `launch_generation`, `launch_receipt`, `retirement_receipt`, `observation_id`, `durable_payload_json`, `durable_payload_sha256` |
| `continuity_owner` | `role`, `pid`, `kernel_bootstrap`, `supervisor`, `root_lease`, `writer`, `writer_proof`, `current`, `material_sha256`, `device_frontier`, `notes_frontier`, `usage` |
| `owner_released` | `pid`, `peer_lifetime`, `receipt`, `current`, `material_sha256`, `device_frontier`, `notes_frontier` |
| `owner_stopped` | `pid`, `peer_lifetime`, `release_generation`, `supervisor` |
| `renewal_origin` | `initial_usage`, `after_boottime_ns`, `initial_root_lease`, `initial_writer` |
| `renewal_endpoint` | `initial_sample_boottime_ns`, `after_boottime_ns`, `actual_terminal_json`, `occurrence_key`, `delivery`, `fresh_kernel_generations`, `root_lease`, `writer` |
| `launch_refused` | `stage`, `expected_generation`, `errno`, `launch_receipt` |
| `initial_owner_retired` | `role`, `peer_lifetime`, `pidfd_revents`, `wait_kind`, `wait_value`, `signal` |
| `history_watchdog` | `first_cpu_stat`, `second_cpu_stat` |
| `initial_recovery_reaped` | `peer_lifetime`, `registry`, `driver_fault`, `supervisor` |
| `history_only_complete` | `old_delivery`, `old_occurrence_key`, `actual_terminal_json`, `fresh_delivery`, `fresh_occurrence_key`, `kernel_launch_generation` |

`material_adopted`, `local_lease_retired`, prepared/native-result/source-terminal,
recovered-terminal, history acknowledgment, usage-window and final completion
use their
existing schemas. `kernel_bootstrap` is the complete actual 200- or 240-byte
page payload, not a selected subset. `root_lease`, `writer`, `writer_proof`,
`current`, `receipt` and both frontiers are complete original DTOs.

Each `supervisor` contains exactly `active`, `healthy`, `runtime_generation`,
`spawn_generation`, `process_system_id`, and `events`. Each event contains
`generation`, `kind`, and `details`, transcribed from the original snapshot.
Known lifecycle/exit events carry the actual state or exit code; other retained
events include their original Debug detail rather than a fabricated result.

A repeated `kernel_launch_saved` for Manager and Recovery names the same
immutable launch transaction and file. It is not a second launch. The host
oracle must independently read and compare the retained filesystem record,
including the complete payload and identifier hash. Unrelated authority keys
need not be extracted.

The renewal success transcript has at most 957 events at cycle 64; a failing
bounded prefix has at most 965. Only `successor-renewal-v1` may use a 1024-event
parser limit. The other scenarios retain 128 events. The existing 128-KiB
single-event and 8-MiB total serial bounds remain unchanged.

## Verification gates

Changes require the original scoped `just test` suites, including Supervisor,
Agentd, Contracts and Memory, with retries disabled for qualification. The
native runner must build the actual same-source/default-feature static ELF,
enforce the original 8-MiB file and 16-MiB LOAD limits, run the reviewed G2
kernel image and retain the real state disk and raw QEMU exit status. Each new
scenario needs its own strict transcript and retained-file oracle acceptance.

These source paths and the two scenarios are not a claim that all daemon,
cross-boot or fault blockers are closed. A partial activation, unresolved
Current, failed physical recovery or authority mismatch fails closed and
remains a qualification failure. The complete original daemon/F1 workload and
the existing live-copyout/crash scenarios keep their independent gates.
