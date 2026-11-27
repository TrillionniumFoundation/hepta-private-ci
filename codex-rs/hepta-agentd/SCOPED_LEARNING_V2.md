# Frozen medium-cadence learning scope V2

## Explicit profile and native entry

`learning_iteration_channel_scoped_v2` opts a host into a frozen component
boundary before the first learning command. `FrozenLearningScopeV2::freeze`
commits the complete original request and owner set, selected component
identities, Cell or Organ scope, and the exact training update-rule digest.
The request already contains its budget, evaluation profile, selected bundle,
operation and expiry. Changing any of these requires a separate admitted
operation; a trainer receipt cannot replace them.

The Agentd dispatcher verifies that the supplied owner ports advertise the
same protected checkpoint binding. It checks each new authenticated Training
observation before recording it, before publishing a checkpoint and before
dispatching Evaluation. Restoring a later checkpoint rechecks every retained
Training observation. A later `NoUpdate` cannot make an earlier out-of-scope
candidate valid.

The existing opt-in native SmolLM runner in
`src/neuron_generation_real_learning_tests.rs` now uses the scoped entry for
both its first invocation and cold learning-owner recovery. Its update rule
is the original prepared training-source digest. This wiring remains a
research harness: ordinary product hosts must explicitly adopt the new
profile with their original registered Root owner. It supplies no production
activation or independent-evaluator qualification.

## Three cadences

| Cadence | This profile's boundary |
| --- | --- |
| Fast inference, routing, private state, STOP | Existing local owners, budgets and permissions continue; this API introduces no chain-finality wait. |
| Medium Cell or Organ learning | Frozen scope is checked before evaluation; the original independent owner identities, budget checks, proposal, selection and actual-next-use path still apply. |
| Slow base or representation release | `BaseRelease` returns `SlowReleaseRequired` at freeze time. There is no caller-provided qualification Boolean or activation digest that admits it through this owner. |

Both medium scopes retain the named base, encoder, tokenizer, normalizer,
numeric profile, output schema, state schema and state-semantics identities.
Cell scope additionally retains the organ adapter; Organ scope additionally
retains the cell adapter. The selected local state partition remains bound by
the complete request and the existing original-owner checks.

Heads, calibration and composition identities can change alongside the
permitted adapter. An implementation can preserve shared tensors, use
`B(Ax)`, route sparsely and cache merged weights. This profile does not require
dense expansion, private copies of shared weights or a training update per
inference step. A new representation, tokenizer, state meaning or base needs
the separate slow-release process and explicit migration/recovery qualification;
that process is not implemented here.

## What the component comparison proves

This gate constrains **named component identities**. It does not inspect all
model bytes or prove that a composition artifact obeys its declared references.
Composition remains variable because it may bind a newly produced adapter,
heads or calibration. A loader that can select another base through opaque
composition bytes still needs a complete reference-to-material check by its
existing artifact and adoption owners. A scope binding grants no such authority.

The native dispatcher continues through
`learning_iteration_proposal::submit_iteration_proposal_v1`, which binds the
candidate, evaluation, dataset, update rule and original proposal admission.
For the existing external-trained-artifact research path,
`learning_iteration_research_external_material.rs` verifies the full selected
baseline components, pinned worker/model configuration and actual adapter
material. It reconstructs the entire expected candidate and compares it with
the coordinator candidate; that concrete research profile also requires the
candidate composition contract to equal the original parent's. The generation
selection and actual-next-use owner still bind the selected candidate to the
loaded material. These existing checks are separate from the V2 name comparison
and do not establish general production tensor isolation.

`NoUpdate` continues through the existing retained Selection and NextUse
branches. It is not an error, a requirement to mutate weights, or permission to
skip evaluation, retain missing evidence or widen the original scope. Service
settlement, improvement awards and consensus work credits are separate owners;
this change creates none of those credits.

## Protected recovery and V1 compatibility

The inner checkpoint encoding remains `HEPLCP02` and original receipt signing
bytes are unchanged. The scoped Root record has outer `schema = 2` and a
domain-separated binding to the frozen scope. The host registers
`LearningIterationCheckpointRecordV1::vacant_scoped_v2` and opens it through
`LearningIterationCheckpointOwnerV1::from_registered_scoped_v2`.

The original V1 channel and schema-1 owner retain their original semantics and
receive no V2 qualification. V1 ports cannot silently enter the scoped channel;
the V1 channel refuses ports advertising the new binding. A schema-2 owner
refuses an existing schema-1 record, a schema-1 owner refuses schema 2, and
changing Cell to Organ or changing any frozen input refuses on recovery.
These refusals do not rewrite or re-register the old protected record. An
explicit new operation and owner admission are required.

The Root CAS still reconciles a lost acknowledgement by reopening the exact
committed checkpoint. A bare `HEPLCP02` export is insufficient evidence of V2
scope: its protected outer record and original host admission must accompany
any scoped qualification claim.

The registered-owner stage adapter preserves this scope binding. A dedicated
Root stream selects V2 explicitly with
`AgentdLearningCheckpointClientV1::from_root_stream_scoped_v2`: both peers bind
schema 2, `runtime.learning.checkpoint.v2`, and the original frozen-scope digest.
V1/V2 substitution and a changed scope are refused without rewriting the Root
record. The original peer, process lifetime, sequence and uncertain-connection
checks still apply. Readback revalidates every retained Training observation;
ordinary delivery also checks its exact request before enrollment. These
interfaces do not construct production stage owners or authorize resubmitting a
claimed operation whose checkpoint is missing or incomplete.

Ordinary original-Root startup can now retain this profile end to end.
`HostAuthorityLearningProfileV1::new_scoped_v2` creates an explicit schema-2
Root0600 configuration containing the Cell/Organ scope, update-rule digest and
recomputed frozen binding. Registration creates the schema-2 protected record;
open-only recovery refuses a different scope or a legacy record. The separate
sealed bootstrap uses `runtime.learning.bootstrap.v2`, retains the same original
writer proof, Root pidfd, process identity and fixed learning socket, and selects
the scoped client and runtime when consumed. Missing scope, scope on schema 1,
operation/version mismatch and modified scope/rule/binding are rejected. No
existing record is migrated or replaced to make a profile match.

Receiving a checkpoint capability still does not assemble the actual stage
owners. Ordinary startup fails closed until those owners, pinned evidence trust,
Circuit providers, selected material and publication authority are supplied.
The actual-Root CAS/descriptor regression uses synthetic operation metadata and
does not establish a production task, independent evaluation or scientific gain.

## Native regression entry

The existing Agentd process qualification workflow runs:

```sh
just test --locked --lib -p codex-hepta-learning-artifacts -p codex-hepta-agentd \
  -E 'test(learning_iteration)' --test-threads=1 --no-tests fail --retries 0
```

The added cases exercise all frozen component fields, exact training-rule and
request binding, live refusal before evaluation/checkpoint, legal retained
selection, all terminal decision checkpoint sequences, cold reopen, profile
downgrade refusal, and real file-CAS lost-ACK reconciliation. Native fixtures
are distinct from actual model execution. The two ignored actual SmolLM tests
still require their pinned materials and original finite execution budget;
historical model results do not qualify this new source.
