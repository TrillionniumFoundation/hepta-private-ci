# Ordinary daemon Root learning handoff — 2026-11-09

## Status

Production acceptance remains **HOLD**. This change supplies the explicit Root
registration, retained checkpoint connection and ordinary startup handoff for
one prebound learning iteration. It does not assemble deployed training or
evaluation owners, produce independent evidence, or publish a model generation.
The previous ordinary-runtime composition remains the consumer of those owners.

## Actual source path

1. The trusted launcher creates `HostAuthorityLearningProfileV1` from the exact
   agent identity, original writer-proof digest, request and stage-owner identities.
   It stores the serialized profile as a Root-owned mode-0600 file. The profile
   has no configurable storage path, signer key or permission to execute stages.
2. `register_host_learning_checkpoint` opens the existing registered writer,
   validates its live lease, protected bind mount, original daemon pidfd and
   profile, and creates the fixed `state_dir/learning-checkpoint` registration.
   The fixed store owner is `root-learning-checkpoint-v1`; creation is one-time.
3. `PreparedHostAuthoritySession::with_registered_learning` opens that existing
   owner. Missing, partial or different-scope state is refused.
   Runtime recovery neither creates a new owner nor resets checkpoint history.
4. `seal_learning_bootstrap` captures the same Root and consumer lifetimes,
   registered identity, writer proof, exact empty request scope and fixed socket.
   It reads the original checkpoint before and after sealing the descriptor.
5. The prepared session binds `learning-checkpoint-v1.sock` beside the original
   five lanes, then its ready callback sends the sealed descriptor and held Root
   pidfd through a separate Root-created anonymous datagram pair.
6. `AgentdProductionStartup` accepts `--root-learning-handoff-fd` only as part of
   a complete original production launch. The typed learning handoff has its own
   marker; the original five-lane V1 marker and public schema remain unchanged.
7. `RootLearningHandoffV1::connect` compares the learning bundle with the original
   five-lane bootstrap, verifies the fixed lane and actual Root peer, retains the
   pidfd, and performs a real checkpoint restore before retaining the inputs.
8. `AgentdConfig::with_root_learning_stage_owners` consumes the retained inputs
   beside actual stage owners and the pinned evidence verifier. It constructs
   the learning worker and the existing Circuit delivery for the exact request.
   Pending inputs cause ordinary runtime startup to fail until that assembly exists.

The new listener calls the existing writer-guarded `serve_learning_checkpoint`.
The actual Root owns FileCas. The daemon receives a purpose-bound UDS connection.
Public snapshot bytes and successful checkpoint storage do not authorize stages.

## Trusted launcher CLI shape

These commands describe the existing Root launcher's inherited descriptors.
Every descriptor variable below must already refer to its actual retained object;
the commands do not create a pidfd, private socket pair, writer lease or grant.
`OWNER_PIDFD` pins the already-created dedicated-UID daemon process. Root retains
its own pidfd and creates both handoff pairs before launching that child.

```sh
hepta-authority-host register-learning \
  --config "$ROOT_CONFIG" --registration "$AGENT_REGISTRATION" \
  --learning-profile "$ROOT_LEARNING_PROFILE" \
  --owner-pidfd-stdin <&"$OWNER_PIDFD"
```

For a fresh session, the same retained Root process uses the existing fresh
filesystem and original handoff flow, with the separate learning inputs added:

```sh
exec hepta-authority-host serve-fresh-session \
  --config "$ROOT_CONFIG" --registration "$AGENT_REGISTRATION" \
  --root-handoff-fd "$ROOT_HANDOFF_FD" --root-pidfd "$ROOT_PIDFD" \
  --learning-profile "$ROOT_LEARNING_PROFILE" \
  --root-learning-handoff-fd "$ROOT_LEARNING_HANDOFF_FD" \
  --owner-pidfd-stdin <&"$OWNER_PIDFD"
```

The daemon launch adds `--root-learning-handoff-fd "$DAEMON_LEARNING_HANDOFF_FD"`
to its complete Android, Notes or Desktop production arguments and may set
`--root-production-lifetime-ms 300000`. Ordinary agent, original application,
control and App Server inputs remain required. The daemon-side descriptor is the
other end of the learning pair, not the Root-side descriptor number.
For open-only recovery, `serve-session` accepts the learning profile, separate
learning handoff and original Root pidfd; it does not manufacture a fresh
five-lane bootstrap or original application capability.

## Bounds and recovery

- Learning exchange timeout is at most 500 ms; session lifetime is at most 300 s.
  Ordinary startup shares its original bootstrap deadline. The learning connect
  receives only the remainder of the original production session budget.
- Scope is one registered iteration and one exact source run. There is no new
  request factory, continuous campaign rotation, automatic resubmission or lease renewal.
- A refused or uncertain UDS exchange consumes that connection. Recovery needs
  the original launcher, live writer and same registered checkpoint scope.
- Registration refuses an existing directory. Reopen preserves original CAS
  history, and unknown outcomes must be reconciled rather than replaced with genesis.
- Partial or duplicate daemon CLI inputs are rejected before descriptor ownership
  transfer. Received handoff descriptors have CLOEXEC and distinct purpose checks.

## Qualification and remaining gates

Native outcomes and exact source identities belong in the accompanying validation
record. No test count or execution success is asserted by this README.
The Root storage tests exercise actual Root-owned CAS and original history;
the cross-process handoff test uses actual Root and a dedicated-UID child.
The direct UDS fixture does not establish a deployed writer service or training.

Still required: admitted host stage-owner implementations and recovery; bounded
real data/training jobs; independent evaluation and signed attestations; the
ordinary Circuit runtime/invocation providers and governed plasticity assembly;
and production qualification of the complete registered writer/listener path.
Published generation recovery additionally requires the original protected
CURRENT, Control FinalUse authority and guarded journal/owner assembly. The
ordinary `Unpublished` generation is unchanged. Q24 remains stateless, Reset-only
and one forward per task; this work does not establish a general LLM execution ABI.
