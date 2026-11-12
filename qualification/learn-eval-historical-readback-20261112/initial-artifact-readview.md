# Original Initial Artifact read access

This is a source implementation stage, not an ordinary A completion, a learning
decision, an independent B evaluation, a C update, or a full cold recovery pass.

## Authority boundary

`AgentdGenerationUpdateAuthoritiesV1::new` still requires the original concrete
Artifact writer. The new internal enum has exactly that writer branch and an
opaque original Root Initial read branch. No caller-defined reader or authority
callback is accepted. All update, forward-recovery and local Initial preparation
entry points explicitly require the writer branch before preparing state.

Only the already authenticated `RootGenerationInitialClient` can construct the
read branch. It checks the actual five-lane verifier object, the original local
FinalUse consumer, and the complete Artifact pin retained in the Root Initial
profile. That pin covers the original root, owner trust, storage binding, signed
CURRENT floor, withdrawal floor, signed selection and selector trust. The same
concrete `LearningArtifactReadViewV1` opens and rechecks physical CURRENT and
withdrawal records; no writer lease is opened or manufactured.

The opaque read branch holds a Weak reference to that actual client Arc and the
complete profile and mode. Every use requires the same live client object before
and after physical Artifact revalidation. Consequently it cannot authorize a
local CURRENT owner or a later C publication. The Weak reference also avoids a
cycle with the CURRENT owner retained by the task and terminal capture hook.

The existing Initial publication still claims and dispatches the original
FinalUse grant, verifies its consumed witness, and performs the exact Root
CURRENT transition. Live task validation still checks Root CURRENT on both sides
of Artifact and FinalUse validation. The read view adds no issuer or new grant.

## Verification scope

The new explicit UID0/UID60001 component test is
`neuron_generation_current::initial_root_tests::root_initial_readview_keeps_original_writer_locked_and_binds_live_session`.
It reuses the original Root enrollment, five lanes, dedicated child, real files
and existing signed fixture material. Root retains the actual Artifact writer
and its OS lock for the entire lifecycle. The child first observes the specific
`WriterFenceBusy` refusal, then uses the actual Initial client's read branch.
The test checks changed storage pin refusal without a FinalUse claim, refusal of
the writer branch, original publication and readback, lost publication ACK,
retired-session rejection, and sticky target-corruption refusal after restoring
bytes. Existing upstream phase-close and live-retirement synchronization remains
in place. Fixture model and role keys remain component fixtures.

`just fmt --base d95c8993b5a80d1636aa74f369586e5b75ef420e` completed successfully
on 2026-11-12. Native tests and scoped agentd Clippy were not run: the local
workspace had approximately 191 MB available and the parent stopped further
native builds after the earlier ENOSPC failure. This stage needs exact-source CI
compilation and the explicit privileged test roster. Earlier reader test results
do not validate this postimage.

The production CLI loader is a separate next stage. A method and a component
test do not establish that ordinary `main` has supplied original model, task,
AuthBus or Objective inputs, or that an actual runtime produced experience.
