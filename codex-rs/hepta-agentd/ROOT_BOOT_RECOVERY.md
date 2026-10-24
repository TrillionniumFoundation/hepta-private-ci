# Root retirement of a publisher from a previous boot

`HostCognitiveCheckpoint::observe_previous_boot_for_root` is a separate trusted
administration boundary. It reads the actual complete original protected head,
checks the independently retained physical last-Current image, and obtains
the actual current Root lifetime through the existing bootstrap process
checks. The concrete `HostAuthorityClock` must first admit this actual boot
under its retained wall-time highwater rule. No supplied boot string, exit
flag, replacement token or locally rebuilt cut can create this evidence.

The returned `RetiredCheckpointPublisher` is not serializable. Its prior-boot
variant fixes the actual Root lifetime and exact predecessor token. Reuse
rechecks that same Root process and boot. It proves that the former process
lifetime cannot continue in the current boot; it grants no authority and does
not establish the result of any old HOS2 effect.

The preceding `retained_head_for_root` read selects material using the actual
whole protected head and its original token under the original publication
lock. This private observation deliberately provides no live, retirement or
physical-integrity claim. It cannot repair a malformed record. Root uses the
returned last-Current cut only to locate an existing retained archive image,
then separately calls the retirement/physical API above. Missing material is
an error; the current mutable database is never substituted for that image.

## Preserve the existing owners and gates

The public `RetiredCheckpointPublisher::observe` method still requires the
original same boot and uses the existing pidfd/start-time observation. The
clean-Current adoption APIs reject prior-boot evidence. Only the existing
physical-material adoption can consume it, after the original canonical
registry and signed writer checks. The entire old head remains the CAS
predecessor. Counter, publisher epoch and local writer generation advance
strictly by one; the exact last-Current cut is carried forward.

The original registry must independently prove the complete old authority
lease revoked, expired, or pruned after actual expiry. A new boot cannot stand
in for that proof, bypass an epoch mismatch, reset the issuer key/counter, or
extend an old lease. The original FinalUse device and notes frontiers continue
from their complete retained values. A partial activation after the boot
change follows the same unactivated-proof versus committed-checkpoint split
as same-boot recovery.

On Asterinas, procfs boot UUID and HOS2 QueryAbi/bootstrap bytes originate in
the same kernel `util::boot_identity::boot_id`. Procfs emits the 16 bytes in
order with UUID hyphens; it does not reinterpret byte order. The native entry
still must read both actual interfaces and compare them. A serialized boot
identifier by itself is never a capability.

## Preserve unresolved old effects

The original device observer refuses an old delivery whose boot differs from
its actual current boot before choosing a history capability. It cannot send
an old-boot query through a fresh namespace. This real observation failure
leaves the original local operation Indeterminate. Recovery must preserve the
complete old K, D, canonical request, claimed FinalUse frontier and absence of
a source terminal. It must not re-dispatch that request, create a terminal
from current CPU usage, or acknowledge retirement of an unobserved old D.

Pending inspection still counts this old Indeterminate operation. It cannot
produce a successful drain or release. Any subsequent owner handoff with this
forensic uncertainty must preserve original Current and physical material,
observe actual process termination, and pass original local/authority lease
retirement before a new cold factory opens. Graceful release stays a distinct
path. New effects require a fresh actual boot/namespace and the original
Root policy authority; the old unknown operation receives no new capability.

## Actual qualification protocol

The isolated Linux Root test
`root_previous_boot_observation_refuses_same_boot_after_actual_process_death`
uses real original owners and exited UID 60001 children. It proves that
process death and registry revocation cannot impersonate another boot. This
negative does not qualify positive boot recovery.

Positive acceptance requires two real kernel boots with one state disk:

1. Preserve the physical disk identity and hash before the first boot. Use the
   actual original Host writer and FileTransport to enter an effect and incur
   real copyout EFAULT. Before the synchronous transport returns, Root retains
   its actual pre-effect Current, physical material and consumed FinalUse
   frontiers, and emits the bounded cut observation after durable storage.
2. The host terminates the actual QEMU process at that observed boundary. Keep
   the raw exit record and disk hash. This is a guest VM process failure,
   not a claim that the physical host lost power.
3. Start the second kernel on that exact disk without mkfs, copying a logical
   database, resetting protected state, or replacing the original issuer.
   Read the actual new proc boot and HOS2 QueryAbi. Reopen existing Root owners
   and observe the prior-boot checkpoint through this API.
4. Retire the old lease in the original registry and use the existing strict
   writer/checkpoint/material factories. Before the monitor starts, inspect
   the original retained operation. The old K/D/request must be exactly the
   same and Indeterminate, with no source terminal.
5. Invoke the original observer. Record its real boot-mismatch refusal and
   unchanged local operation. The FileTransport must send neither old Install
   nor old Query, and neither a false terminal nor a retirement ACK may appear.
   A separately authorized new namespace must not be used to retry old work.

These interfaces do not by themselves implement or qualify native cold-open
assembly. The existing six native scenarios keep their own source pins,
limits and result gates. The two-boot runner and positive original-owner
activation must be implemented and run before cross-boot recovery is closed.
