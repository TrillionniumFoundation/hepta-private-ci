# Supervisor-owned active Neuron module observation (diagnostic only)

The Supervisor's existing `RuntimeModuleSupervisorV1` owns the **in-process** module lifecycle registry, active generation, topology digest and selected lifecycle evidence. Do not infer its selected `neuron.runtime` entry from the currently live `runtime.status` CNS route, a local Neuron checkpoint, or a signed Artifact descriptor.

`read_neuron_active_candidate_v1(expected_generation, expected_candidate_artifact_digest)` reads **this Supervisor instance**, requires the exact active `neuron.runtime` generation and bounded candidate identity, and requires its already admitted evolution selection. A bootstrap module (which lacks that independent evolution selection), a Shadow/Canary-only candidate, a different artifact or generation all fail closed. `revalidate_neuron_active_candidate_v1` reopens the **same Supervisor instance**, checks the complete current topology and compares every selected field, rejecting old views after unrelated topology changes, quarantine or retirement. The output has `AuthorityPosture::DENY_ALL` and a recomputable domain-separated field digest. No second selection registry or writer is created.

**Boundary:** the `candidate_artifact_digest` in RuntimeModule ABI can denote a topology/implementation candidate, and is not automatically the SHA-256 of the separate small Model descriptor. Neither this read nor the previous Agentd model-descriptor/Checkpoint binding establishes that both came from the same actual deployment. An independently authenticated production composition must map those identities and verify real CNS route publication, signed ArtifactLoadReceipt/physical weights, generation fences, host/process identity and crash recovery. The Supervisor registry is an in-memory working set, not a crash-durable, externally attested route election.

New qualification tests exercise missing Active Neuron, bootstrap without selection, Shadow/Canary without promotion, selected and initialized stateful module, wrong generation/artifact, output tampering and same-owner currentness. They also demonstrate that a stale self-consistent diagnostic digest cannot pass fresh Supervisor revalidation after topology change, quarantine or retirement. The selected state uses the test-only `register_shadow_for_test`; no private production keys or real deployment are exercised. This candidate observation cannot authorize model use, NDU, canary, production switching or a rollout.

Run on exact SHA: `cargo fmt --package codex-hepta-supervisor -- --check`, `cargo check --locked -p codex-hepta-supervisor --lib`, `cargo test --locked -p codex-hepta-supervisor --lib read_neuron_active_candidate_v1`, and correctness Clippy. PR remains Draft; no production Neuron activation is claimed.

### Process-liveness correlation (diagnostic)

The Supervisor's existing lifecycle monitor can now correlate its real
\`Supervisor<ProcessDriver>\` agent process snapshot with a selected ACTIVE
\`RuntimeModuleSupervisorV1\` Neuron under the strict **same AgentId as
module owner_id** profile. The new
\`Supervisor::read_current_neuron_agent_process_v1\` refuses unstarted,
awaiting-health, drained, unhealthy, fenced, restarting and release-changing
agents. It includes the exact process runtime generation, spawn generation,
system ID, process incarnation, current release, control revision and module
topology/selection digest in a non-authorizing receipt. The module generation
is separate: it is never compared numerically to a process restart generation.

\`revalidate_current_neuron_agent_process_v1\` rereads BOTH existing
in-process owners; a changed process incarnation/release/generation or
stale module topology makes the prior receipt unusable. A matching AgentId
is a deliberately narrow namespace constraint; multi-Agent module owners
must have a separately authenticated mapping and cannot silently opt out.
No second process registry, additional heartbeat, or production writer exists.

The live process test uses the existing \`Supervisor\` fixture with its
actual FleetRegistry and fake process driver. It first rejects Active-without
Agentd and AwaitingHealth, then accepts the observed Running generation,
rejects another Agent, forged process IDs, and a prior receipt after restart.
Its selected module uses the explicitly test-only selection helper; these
are NOT production release/route proofs.

This is still not proof that Agentd loaded the descriptor model, that the
physical model weights were rehashed, that a Neuron CNS route is published,
or that final-use authority was issued. Neither model selection nor
production NDU is unblocked.
