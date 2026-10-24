# Native successor capability and observation boundary

The G2 successor adapter accepts only the separate `HOS2BOOT` v4 layout produced
by the frozen-image kernel factory. Initial v3 and the legacy G1d v2 layout keep
their existing meanings. This module is part of the original Agentd/Supervisor
composition; a bootstrap page does not allocate Registry identity, issue writer
authority, or promote a process to Ready.

| Image role | Current CPU capability | Retained history |
| --- | --- | --- |
| Manager, role 1 | Observe 1:1, manage 2:1, finite original bounds | Its Manager namespace, slot 3:1 |
| Recovery, role 3 | Observe 1:1, manage 2:1, finite original bounds | Original Manager and Recovery namespaces, slots 3:1 and 4:1 |
| History-only, role 5 | None | The exact original two namespaces, slots 3:1 and 4:1 |

Each final Process opens its own control descriptor before dropping to the
existing Host UID. `QueryAbi` must match that image's fresh local CapSpace. A
role-5 local space differs from both retained history spaces. Its old requests
still bind to their original manage slot 2, generation 1, 50 ms maximum and
100 ms period. Those constraints validate old bytes; they grant no current CPU
authority. Role 5 refuses ReadUsage, request preparation and dispatch before
transport. Its history work does not require the old workload to remain alive.
Only the original writer can construct the retirement permit.

## Root factory transport

`RootKernelLauncher` opens only in the original PID-1 Root image and uses the
kernel's private 128-byte ioctl. The kernel authenticates Process and image on
every call. The API takes an actual immutable launch receipt as the Advance
predecessor; there is no executable path, raw PID or scope input. Ordinary fork
and exec receive no native authority. The original Supervisor still owns each
Agent identity, generation, process lease, health promotion and reaping.

The four commands are Query, Advance, ReadRetirement and AckSaved. A lost ioctl
copyout is returned to the caller; no hidden retry creates an additional child.
The caller may query or replay the exact old expected generation to retrieve the
kernel's saved launch receipt. A new Advance must wait for actual child reaping
and the previous retirement acknowledgement.

The retirement record is the original watchdog terminal captured under the same
CPU lock that replaces a policy. A pair transition with status 0 and flags 1
means an untriggered policy was retired. A history-only transition with status 0
and flags 0 leaves the old policy alive. The distinction is retained verbatim,
including `Some(0)` versus unavailable evaluation time.

Before AckSaved, the trusted composition must persist the full verified boot
identity, launch generation, complete 128-byte launch receipt and complete
128-byte retirement record through the original Root protected administration
path, with file and directory fsync. This step precedes releasing the new Host:
a Host that dies before Ready must not prevent the next recovery attempt. These
bytes are kernel observations. They do not manufacture a CPU D/K, a writer
terminal, a Root Current witness or authority in a later boot.

## Acceptance

The parser tests exercise foreign boot/space, role confusion, changed old
request constraints, malformed capability/PID/generation fields, and loss of
watchdog receipt fields. They use inert byte vectors and are not native evidence.
The original native owner must additionally prove live/unreaped-child EBUSY,
actual copyout loss and exact replay, original durable save before AckSaved,
role-5 query/retire with ReadUsage/InstallBudget refused, and continued original
writer/FinalUse recovery across a newly allocated generation.

The finite initial entry and its two scenarios remain separately qualified.
Adapter or codec tests alone do not establish persistent control, long-lived
Root session renewal, cross-boot recovery, a complete native daemon, or a binary
within the unchanged trusted-image bounds.
