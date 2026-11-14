# Ordinary CLI assembly: remaining concrete gates

## Qualification

**Production acceptance remains HOLD. The ordinary CLI is not fully wired.**
The candidate supplies an opt-in, single-iteration composition inside the
ordinary runtime. Actual providers and the trusted launcher handoff are still
missing from `main.rs`. A successful composition test does not establish
production custody, independent evaluation, model adoption, or learning gain.

## Source integration completed in this candidate

- `learning_iteration_checkpoint_ports.rs` composes original stage ports with
  either the registered Root checkpoint owner or its existing Root UDS client.
  Restore requires original-stage recovery validation; the worker separately
  reauthenticates receipts. The adapter creates no owner, signer, or capability.
- `learning_iteration_delivery_runtime.rs` retains the original learning channel
  and supervises delivery of one exact request through `run_with_shutdown`.
- `state_circuit_task.rs` and `objective_learning_outbox.rs` enqueue and recover
  completion pointers only for the explicitly configured source run. Ordinary
  tasks without that configuration, and unrelated tasks, do not fill the queue.
- Durable claims select submission versus readback. ACK requires an authenticated
  completed iteration, including distinct next-task use for NoUpdate. New work
  checks full ordinary admission; uncertainty never grants resubmission rights.

These changes close the corresponding adapter and runtime-consumer wiring gaps.
They do not supply the concrete production services listed below.

## Concrete components still required by the CLI

### 1. Actual learning stage owners

`learning_iteration_ports.rs::LearningIterationStageOwnerPortsV1` specifies the
stage contract. Its concrete implementation in the inspected candidate is
`learning_iteration_checkpoint_ports_tests.rs::StageOwners`, a test fixture.
The non-test `CheckpointedIterationPorts` delegates stage work; it does not
implement training, independent evaluation, proposal preparation, or attestations.

### 2. Independent evaluation input and execution provider

`neuron_cell_evaluation.rs::CellEvaluationRunnerV1` and
`hepta-intelligence-eval/src/product_runner.rs::ProductEvaluationRunnerV1` exist.
`hepta-intelligence-eval/src/fenced_holdout_file.rs::LockedFileFinalHoldoutCasStoreV1` is real file-backed CAS.
Concrete `FinalHoldoutProviderV1` implementations are in tests/test support.
The ordinary daemon still lacks the actual holdout provider and its independently
admitted evaluation execution and identity. Existing CAS does not establish them.

### 3. Original-owner learning receipt attestation

`learning_iteration_auth.rs` verifies signatures, roles, and actor separation.
`hepta-learning-ledger/src/signed_evidence.rs` supplies evidence encoding and
verification. Non-test `receipt_attestation` in this composition only delegates.
No assembled service reads actual stage-owner results and supplies their current
authorized attestations. `plasticity_process_bootstrap.rs::build_verifier` loads
verification configuration; it does not construct a training/evaluation signer.

### 4. Ordinary Circuit invocation and input providers

`config_circuit_task.rs::with_circuit_task_bootstrap` accepts existing providers.
`AgentdCircuitTaskInvocationProviderV1` is implemented by the ingress test fixture;
`CircuitTaskInputProviderV1` implementations are in driver and ingress tests.
There is no existing non-test provider assembly for `main.rs` to instantiate.

### 5. Trusted delivery of the original Root learning capability

`LearningIterationCheckpointOwnerV1::from_registered`,
`AgentdLearningCheckpointClientV1::from_root_stream`, and
`HostAuthorityService::serve_learning_checkpoint` are existing production APIs.
They have no non-test learning assembly caller in the inspected candidate.
`root_production_inputs.rs::AgentdRootProductionInputs` and its receive function
retain the original five lanes, including Cognitive checkpoint and Device/Notes;
they do not carry a learning lane. The real launcher must register or recover the
exact learning owner and transfer its dedicated stream and original Root pidfd.
A descriptor, writable pathname, or unrelated capability cannot substitute.

### 6. Published generation recovery

`main.rs` calls `load_neuron_generation_process_bootstrap_v1`, which reaches
`neuron_generation_runtime.rs::neuron_generation_channel_v2` with `Unpublished`.
`ReadyAgentdGenerationUpdateV1::into_runtime` supports a real published owner,
but the CLI does not recover its original CURRENT publication and guarded journal.
The candidate does not relabel ordinary generation as published.

### 7. Durable training and continuing operation

`terminal_learning.rs::AgentdTerminalLearningOwnerV1` performs a narrow native fit
using authorized Ledger/Memory owners. Its job cache lasts for the owner process;
it is not a complete durable training/evaluation/proposal/selection composition.
The delivery request must already bind the completed task receipt. Claimed work
without a complete checkpoint stays readback-only. Arbitrary request creation,
multi-operation registration, safe interrupted-work continuation, and retirement
of the outbox's 256 retained identities remain open engineering requirements.

## Acceptance boundary

There is no ready, non-test, admitted assembly that can honestly close the CLI
gap by adding one call to `main.rs`. The missing providers, launcher composition,
and publication recovery must be implemented and exercised with their actual
original identities and durable owners. Test-only research owners stay test-only.
Q24 retains its stateless, Reset-only, one-forward-per-task scope. Validation
commands, exact source identities, results, and exclusions belong to the separate
candidate evidence record; this document claims no additional execution result.
