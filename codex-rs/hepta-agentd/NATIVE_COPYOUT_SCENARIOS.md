# Original native CPU copyout scenarios

This module connects the existing actual `FileTransport` fault arm to the
original native Root, writer, FinalUse consumer, Supervisor and recovery
owners. Source review and compilation are prerequisites. Only a successful
original-entry guest run of the named scenario qualifies its behavior. Host
parser tests, the Linux ABI probe and the existing C control probe do not
qualify these Rust writer scenarios.

## Scope and unchanged owners

`native_cpu_commands.rs` accepts plans over its existing authenticated Root
RPC. The new commands carry an existing occurrence key and a Boolean fault
mode. They do not carry a raw address, errno, capability, lease, authority,
checkpoint, outcome or substitute transport. The exact queued payload is
decoded through `Hos2InstallBudgetV1` and passed to
`AgentdHos2Device::arm_native_copyout_fault` before the original grant/dispatch
path runs. The one arm is accepted only before that process's first Install.

The original FileTransport selects the complete 96-byte Install frame and
changes only the response address to its own inaccessible mapping. It retains
the original 128-byte capacity, makes one real ioctl, immediately captures its
return and errno, and drops the mapping before the optional callback. Only
actual `-1/EFAULT` invokes the callback. The writer receives the original
transport error. No retry or Applied result is manufactured.

`ReconcileCopyout` calls the existing destination-scoped, observer-only
reconciler once. It verifies the original immutable request and durable
terminal against an independent history observation, acknowledges the original
owner cut, and checks that its FileTransport Install count did not change.
The background monitor remains enabled. It may have already reconciled the
same D before this command begins.

## Scenarios

| Scenario | Fault and recovery | Required original outcome |
| --- | --- | --- |
| `lost-copyout-live-v1` | One real EFAULT returns to the same writer. Its original Indeterminate dispatch receipt is retained, then the original observer recovers D. | One actual Applied revision, one Install, a durable source terminal and Current, original prefix retirement, and observed workload accounting. |
| `manager-exit-before-terminal-v1` | The real EFAULT callback reports over the already authenticated RPC and remains inside the synchronous dispatch for at most two seconds. Root captures the independent Current/material/consumer frontiers and kills the same Manager using its held pidfd. | Actual pidfd exit and SIGKILL status, original Supervisor reaping and restart, expired old local lease, original material adoption, an early recovered Indeterminate row, observation of the old D without another Install, then source terminal/Current/retirement. |

The original `steady-state-v1` and `manager-exit-after-terminal-v1` event
schemas and checks remain unchanged. Their owner-ready transcript omits the
additional inspection fields used by these two new scenarios.

## Crash boundary

The callback consumes the current Root RPC, reports only the actual syscall
diagnostic and fixed occurrence key, and waits for process death. A Root reply,
EOF, expired boundary, I/O failure or any return from this dispatch is a failed
qualification. The callback never calls a FinalUse frontier, checkpoint,
writer or reconciler. The original HOS2 dispatch guard and lock-only SQLite
effect-entry barrier remain held naturally during the synchronous call.

Root checks the actual peer and the one outstanding key, reconstructs the
fixed wire identity for comparison, and uses
`HostAuthorityService::capture_public_bootstrap` to read the existing protected
consumer backends. It does not reopen a fenced consumer or recurse into the
Host's held FinalUse state. The reported Current must equal that protected
capture and name the same actual retained publisher. Its physical material is
verified through the existing retained-material API.

The shared `recover_after_crash` path is extracted from the original
after-terminal ceremony. It preserves held-pidfd SIGKILL, poll readiness,
`waitid(WNOWAIT)` observation, Supervisor-exclusive reap, real lease expiry,
canonical proof rotation and physical material installation. Only the new
boundary supplies `kill_before`; Root checks real BOOTTIME before signaling
and again after the actual successful syscall, recording that completion time.
The five-second kernel watchdog is unchanged. Its
later immutable restoration receipt remains separate from the older D's
Applied receipt.

## Early recovery observation

Immediately after the original protected writer factory returns, and before
target attachment or monitor startup, Host calls the bounded read-only
`retained_pending_hos2(16)` API. That API discovers original nonterminal HOS2
rows and revalidates each through `retained_operation`. Host copies only
`occurrence_key`, `topic`, `payload_json` and actual `state` into
`Owner.startup_retained`. No event, D, Current, lease or terminal is created.

The crash scenario later requires exactly the prepared K/D with state
Indeterminate in this saved startup observation. This is not a claim that the
live row remains Indeterminate after the monitor has started. The recovery
descriptor must still report zero Install calls before and after observation
of the old D. The live scenario preserves the original returned Indeterminate
dispatch receipt instead; it does not infer Unknown from a later Current.

## Transcript contract

All records use the existing `HEPTA_G2_EVIDENCE_V1` envelope, source scenario,
host nonce and strictly increasing sequence. Each scenario has one prepared
operation with cap 25,000,000 ns and period 100,000,000 ns.

The live event suffix after the original roles/state/boundary/owner-ready
prefix is:

1. `prepared`, using the existing exact payload.
2. `copyout_indeterminate`.
3. `copyout_reconciled`.
4. Original `source_terminal`, `history_ack`, `usage_window`, `complete`.

The crash suffix is:

1. `prepared`.
2. `copyout_boundary`.
3. Original `manager_retired`, with an additional actual `kill_boottime_ns`.
4. Original `watchdog`, `local_lease_retired`, `material_adopted`, and Recovery
   `owner_ready`.
5. `copyout_recovery_startup`.
6. `copyout_reconciled`.
7. Original `source_terminal`, `history_ack`, `usage_window`, `complete`.

`complete.operation_count` is exactly one for both new scenarios.

| New event | Exact payload fields |
| --- | --- |
| `copyout_indeterminate` | `operation`, `pid`, `occurrence_key`, complete original `receipt` (`ProductionDispatchReceipt`), `before`, `after`, `copyout` |
| `copyout_boundary` | `operation`, `pid`, `occurrence_key`, canonical `request_json`, original `payload_sha256`, `before`, `diagnostic`, `observed_boottime_ns`, `pending_until_boottime_ns`, original `current`, physical `material_sha256`, `device_frontier`, `notes_frontier` |
| `copyout_recovery_startup` | `pid`, `occurrence_key`, `capture_point` equal to `original_recovery_before_monitor`, `captured` (one original startup row), `copyout` |
| `copyout_reconciled` | `operation`, `pid`, `occurrence_key`, canonical `request_json`, original `receipt` (`ProductionOutcomeReceipt`), `terminal_json`, `usage`, `before_state`, `before_payload_json`, `reconciled_count`, `copyout` |

Every `copyout` snapshot has exactly `install_ioctl_count`,
`selected_ioctl_count`, `efault_count`, `armed` and `last`.
Every non-null `last`, and the boundary `diagnostic`, has exactly
`install_ioctl_count`, `selected_ioctl_count`, `efault_count`,
`request_sha256` (32 bytes), `request_bytes`, `response_capacity`,
`syscall_return` and `errno`.

The Manager's selected observation requires counts 1/1/1, 96 request bytes,
128 response bytes, return -1, errno EFAULT, and the exact complete frame hash.
Its post-reconciliation snapshot remains 1/1/1, unarmed, with the same
diagnostic. The new Recovery descriptor instead requires 0/0/0, unarmed and
null `last`; its old-D query cannot spend an Install. No error or timeout may
be interpreted as a successful fault observation.

The crash oracle must also require
`observed_boottime_ns <= kill_boottime_ns < pending_until_boottime_ns`, a
positive boundary width no greater than two seconds, and the original actual
pidfd/SIGKILL evidence. The old D's terminal revision remains its one earlier
Applied revision even when the watchdog has since advanced current usage.
Both original FinalUse frontiers survive adoption and observer-only recovery.

## Integration and acceptance

This source requires the original memory owner's bounded pending snapshot
API, the Host startup capture, the shared recovery helper and the finite plan
allowlist additions in the accompanying glue. No additional authority API or
kernel opcode is introduced. The full original entry must still pass the
existing 8 MiB ELF and 16 MiB LOAD limits before either guest scenario runs.

Actual acceptance must retain raw guest output, source/build hashes, the
unchanged original image bounds and all failed attempts. The four scenarios
must execute from the complete original Rust entry; no thin C replacement,
fake transport, reset database, extended initial grant or test retry can
substitute for these outcomes.
