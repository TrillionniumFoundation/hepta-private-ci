# Bounded checker dispatch and recovery

`DispatchJournal` computes the existing advisory scheduler from typed inputs.
Freeze risk/checker model identities, the complete effects-model body and actual
scheduler source identity. The host must bind the supplied manifest digest to
the original prospective roster; the digest alone does not authenticate it.

The dispatcher commits the original operation before calling a registered host
checker. Pending work blocks new operations on the same snapshot and is never
replayed. Recovery authenticates exact original reply, request and configuration
identities. Use `status(operation_id)` to reconcile a lost reply.

Configuration is read-only. Each snapshot retains its original prediction,
action losses, observed history and budget. Duplicate checker attempts cannot
evade charges by changing operation IDs. Measured overruns remain charged.
Stale state, malformed replies and callback exceptions never create usable
observations. Host permission/schema/original-owner gates remain compulsory.

Read-only callbacks and state-readback truth are host obligations, not a sandbox
provided by this module. No check result authorizes acceptance, repair or payment.
Nine behavior tests passed. Complete-cost independent real-task utility remains
unqualified; the accompanying subprocess experiment is controlled engineering.
