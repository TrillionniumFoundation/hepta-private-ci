# Original writer succession and whole-owner acknowledgement

Fleet process generation and local writer lease generation are independent.
Fleet advances generation on lifecycle transitions: Starting1 -> Failed2 ->
Starting3 is a valid successor whose local lease generation is2. The protected
host fixes process generation from AgentdConfig; the original live Root verifier
checks that exact process binding, local lease ID and local generation against
the proof-verified current registration. Default verifier implementations retain
their existing equal-generation policy. A writer accessor cannot grant a new
process identity.

The original local lease still requires the same ID, generation exactly+1,
a previously unused grant-bound fencing token and a strictly newer lexicographic
authority/owner epoch. Revoking a Root grant or observing process exit does not
expire that local lease. Unresolved Pending/Unknown prevents voluntary release.

The trusted launcher must use this order:

1. Retain independently authenticated Current and establish old publisher exit
   through the Root process-lifetime boundary.
2. Complete legal local release with the complete Current acknowledgement, or
   wait until the actual old local lease expiry. Only then obtain the canonical
   successor proof for the actual Fleet spawn and exact next local generation.
3. Adopt the exact Root-protected Current cut under the original retired/live
   authorization boundary. Do not derive a replacement cut from local SQLite.
4. Call the original protected factory once with that exact receipt and binding.
   It binds the whole-pool checkpoint, expires/acquires the original local lease
   and recovers the original owner. Pool mutation changes Root Current to Dirty.
5. Construct the sender from that installed original host and call
   `ProductionObjectiveSender::acknowledge_owner_cut`. This reuses original
   transaction serialization, complete-cut capture, live verifier, checkpoint
   and whole-owner cancellation gate. It creates no Objective, ticket, event,
   cancellation or send permission. Confirm the exact resulting Current.

Calling the factory before old local expiry can fail after its checkpoint bind
already made Root Dirty. That is an actual retained failure state; it does not
permit retry from the old Current. A host must enforce step2 before binding.
Unknown/cancelled started publication permanently fences the whole owner. Later
readback can settle evidence but cannot reopen that generation or replay effects.

Historical Objective records retain their original independent process and
local lease bindings. PermitIssued must match the request's full retained
binding, not merely a generation number. Successor authority does not create
permission to resend a historical request.

[The Root checkpoint contract](HOST_COGNITIVE_CHECKPOINT.md) and
[canonical issuer rotation](ROOT_AUTHORITY_CLIENT.md#trusted-writer-succession)
define independent prerequisites. The
[54-test component qualification](acceptance/2026-10-23-local-writer-handoff/README.md)
uses explicit Root fixtures and actual original local owner APIs. It does not
qualify a complete production/reboot recovery, Dirty promotion, Notes metadata
retirement, HOS2 effect recovery or a native executable.
