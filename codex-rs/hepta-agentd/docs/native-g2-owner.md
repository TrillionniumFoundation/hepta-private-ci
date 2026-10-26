# Native original-owner entry

`hepta-g2-native-owner` is a tracked binary in the original
`codex-hepta-agentd` package. It keeps that package's default
`production-cognitive-write` feature and original release profile. It is a finite
CPU-control composition of the actual original owners. It does not start an
App Server, model turn, native Notes UI or a deployment-ready desktop.

Implementation existence, Cargo target selection and formatting are source
preparation. Compilation, packaged ELF size and each actual source-bound guest
run require their own retained results. This document supplies no execution
receipt. The Desktop `tests/workloads/hepta_cpu_control/NATIVE_OWNER_RUNBOOK.md`
and `NATIVE_OWNER_EVIDENCE.md` remain the acceptance contract.

## Module boundaries

All implementation files are in `src/native_g2_entry/`.

| Module | Development responsibility and original technical boundary |
| --- | --- |
| `boot.rs` | Read the actual initial auxiliary-vector page, verify v3/200-byte discovery and actual PID/parent/initial UID; Root independently authenticates its kernel image through the existing launcher query. A copied page grants no role. |
| `paths.rs` | Mount the new attached ext2 disk at Root0700 `/state`; refuse existing/partial state. Bind only original Agent data/control views outside that private ancestry. Keep the five original lanes under Root:60001 mode02710. |
| `ipc.rs` | Admit only exact kernel-selected process connections. Existing peer-channel, pidfd, frame and exchange-deadline checks remain mandatory. Waiting for a future pre-created child to be selected does not extend the original handoff's exchange deadline. |
| `supervisor.rs` | Pass the actual already-created children, command, held pidfds and late descriptor pairs to `PrecreatedProcessDriver`, `Supervisor::recover` and `Supervisor::start`. Never fork an alternative owner or infer its spawn generation. |
| `provision.rs` | Explicit fresh Root administration through original Fleet register, authority initializer and writer-registration factories. Derive policies from this boot's actual native namespaces. No plan-supplied key, lease or grant is accepted. |
| `activation.rs` | Use `prepare_fresh_with_physical_material` before genesis, then the same Prepared object's filesystem handoff, sealed bootstrap, fixed writer-FD export and original five lanes. |
| `owner.rs` | Open this image's actual device, drop original credentials before runtime threads, receive the original SpawnSpec and purpose-bound three-FD handoff, configure the original writer, then attach the original native operation host. Root commands invoke original preparation, FinalUse dispatch, Current acknowledgement, consumer reads and retirement. |
| `native_observer.rs` | While Recovery waits for selection, answer only actual `read_usage`. It cannot prepare, sign, dispatch, retire or manufacture a source result. |
| `workload.rs` | Run actual CPU work in the kernel-created UID60002 session and update a shared atomic heartbeat. Return actual signal/path/device-denial observations to Root. |
| `boundary.rs` | Make bounded negative Root management/history calls and retain their actual correlated permission-denial responses. |
| `evidence.rs` | Bound the Root0400 plan, read actual proc credentials/capabilities/session/birth, and serialize the exact original-owner evidence envelope from Root alone. |
| `cycle.rs` | Preserve exact canonical K/D request and terminal bytes. After actual dispatch, require the writer's authenticated Current to equal Root's independent physical Current before source evidence; retire through the original source-owned permit. |
| `root.rs` | Retain the same Prepared service while serializing actual observations. Complete the original privileged kernel poweroff only after the finite sequence. Ordinary PID1 exit, error or timeout cannot substitute for success. |
| `recovery_process.rs` | Observe the held Manager pidfd, signal-nine `waitid` status with WNOWAIT, original watchdog `cpu.stat`, actual workload membership and real lease expiry. Original Supervisor remains sole reaper. |
| `recovery_registration.rs` | Capture the actual next Supervisor Starting generation, create private successor administrative inputs and call the original same-key/counter writer-rotation factory. No re-registration or fresh genesis. |
| `recovery.rs` | Install independently retained material, adopt original Current, start the actual selected Recovery and read both original durable terminal and retained native history. Never redispatch the old K/D. |

The kernel's native CPU leaf retains its existing `hepta-g1d-<nonce>` internal
name even for this G2 profile. The observer selects it by actual singleton
workload membership, not by treating that name as authority or prior evidence.

## Startup and storage

Root is actual PID1 and the actual parent of all three initial children.
Manager and Recovery open their own kernel-bound device before dropping to
UID/GID60001 with the original credential-drop body. They have no supplementary
groups, capabilities or privilege-restoration route. Workload is the actual
kernel-created UID/GID60002 process in its own session. Root reads those values
from `/proc`; role labels and argv do not stand in for them.

The fresh Fleet and workspace reside on the attached state disk. Root creates
separate actual bind views `/hepta-fleet` and `/hepta-workspace`; `/state` and
its authority/material descendants stay Root0700. This lets the original data
handoff release only Agent data while Root retains Registry, generation state,
writer-lock path and independent recovery material. Fresh startup refuses an
existing disk rather than repairing partial state or interpreting it as genesis.

The existing two-FD Root purpose remains unchanged and rejects the new purpose.
Native startup transfers exactly the original sealed bootstrap, the same actual
Root pidfd and the original registered Root0600 read/write writer descriptor.
The sender consumes its exported File. Root retains no clone of that OFD that
could keep the child's original flock alive after exit. The recipient receives
an opaque non-clonable descriptor and consumes it into the original config,
which repeats actual identity, Starting, custody, inode and live-authority checks.
A serializable observation cannot obtain that descriptor.

## Finite operations and recovery

`steady-state-v1` authorizes lower=25 ms, pause=0 and resume=50 ms within the
unchanged 100 ms native period. Each D comes from the original durable namespace
prefix. A Root command cannot provide its own next sequence or terminal.
Unknown native outcomes are errors; the entry has no dispatch retry loop.

`manager-exit-after-terminal-v1` stops after a real durable terminal and before
history retirement. Root sends SIGKILL through the original Supervisor, checks
its held pidfd and real wait status, then observes the original five-second
watchdog's immutable receipt. The old local and canonical authority leases must
actually expire. The entry's explicitly provisioned finite writer TTL is 20 s,
so this handoff can occur inside the unchanged 30 s native recovery grace; it
never extends the watchdog, grace, grant, guest timeout or exchange deadlines.

The local durable writer retains its lease ID and increments its generation.
The canonical successor authority lease uses a distinct ID at revision one; the
original expired authority lease remains intact. The shared original successor
validation runs before Root can write the new canonical lease.

Root rotates only the exact old registration/proof into the actual successor
Starting generation using the existing issuer/key/counter. A lost rotation
reply may reconcile that exact already retained successor through the original
factory; it cannot reserve another generation or register a new issuer.

Physical recovery accepts no caller digest, cut, image path or reset input.
The original factory reads and verifies existing Root material, installs into
only the registered store, adopts the original Current, opens original consumer
heads and releases the installed data to the registered UID. An interrupted UID
handoff is a separate same-Current reconciliation; it cannot adopt again.

Recovery reads the old original terminal/event from the actual recovered
SQLite ledger and compares it with the actual retained native D history.
Current CPU usage may reflect the later watchdog effect and is never used as
the old D's result. Original consumer frontiers and the original event ID stay
unchanged. Only then does the original writer authorize history retirement.
The next finite Recovery operation must record the actual consumed-allowance
refusal, rather than inventing or reapplying an effect.

## Validation and remaining work

Use the original locked/offline/default-feature release builder and original
symbol-archive/strip packaging. Preserve the <=8 MiB packaged ELF and <=16 MiB
LOAD-map limits, static ET_EXEC shape, non-executable stack and source review.
Do not substitute the old Root/peer ELF, a fixture package, profile/feature
removal, another loader or a larger guest limit if the new entry fails.

The source includes original-component tests for exact terminal readback and
Root-only transport tests for OFD release and strict purpose separation. Run
these on the final combined source through the repository test workflow. Tests
using fixture authority/SQLite or transport-only seal bytes are component
evidence; they do not qualify the native entry.

After successful actual build and shape inspection, freeze the exact Desktop
and Hepta source pair and build the product kernel from that same source with
the packaged entry embedded. Run both altered-loader controls, the original
entropy-not-ready control and each requested positive scenario. Keep every
failed attempt's own raw logs and receipts. A changed source requires new
compilation and execution; old driver, N0, OSTD or Root test results do not
transfer to it.

Even a pass in both finite scenarios leaves after-effect/before-terminal crash,
old-boot Unknown preservation, cross-boot recovery, repeated replacement,
grant/session renewal, power loss, physical hardware and full G2 product
readiness unverified. Close those through the original owners and source-bound
cases rather than changing result flags.
