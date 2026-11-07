# Opt-in signed kernel Final-use for a witnessed Neuron Tick

The new `AgentdNeuronOwner::tick_with_signed_final_use_v1` reuses the
existing `kernel.authority` FinalUseAuthority / SignedFinalUseGrant and
the long-lived Agentd Neuron owner. No new signer, trust store or runtime is
created by this feature. The caller provides a REAL independently issued
grant and the authority validates its signature, trust distribution,
revocation head, expiry and durable single-use nonce.

Before requesting a grant, Agentd rereads the actual local
NeuronRuntime/Journal/Witness binding and rejects missing/unacknowledged
checkpoints, wrong subject-scope, Objective, body Generation, feature digest
or next sequence. The request digest commits the WHOLE local immutable
model/config/calibration/resource/checkpoint identity plus the exact
NeuronTickInputV1 semantic digest. Destination
`hepta.agentd.neuron.tick.v1` cannot be substituted with runtime.codex
or another provider.

The kernel uses `with_verified_effect` at the synchronous physical Tick
entry, protecting the already claimed grant against an interleaved revocation
for the duration of this synchronous execution. An authority denial, stale
checkpoint, altered Q24 vector or different Scope prevents model dispatch.
An unknown physical terminal still requires native inference.control WAL
reconciliation, not a retry with a reused grant.

**Non-production limitations:** This is an opt-in source-level ingress.
Existing `tick`, `tick_with_observation_v1` and the lower-level
`NeuronRuntime::tick` remain compatibility/qualification paths. Therefore
this patch DOES NOT establish that the daemon enforces the signed route.
It intentionally refuses an empty bootstrap checkpoint; only a separately
admitted startup/first-tick owner can solve that without bypassing Witness
semantics. There is still no proven real CNS-selected Neuron route, physical
Laya-backed ModelPort admission, Artifact CAS load, live Agentd activation
or independent production no-change. Current CI tests validate the exact
binding/rejection logic; they do not invent private authority credentials
or true production rollout approvals.

Production promotion remains DENY_ALL and PR #1494 remains Draft.
