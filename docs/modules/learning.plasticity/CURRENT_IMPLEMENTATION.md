# learning.plasticity current implementation and operations

This is the current-source companion to [`TECHNICAL.md`](TECHNICAL.md). The technical
guide remains the stable target/development envelope. `CURRENT_STATE.json` is the
machine-readable current-source truth and the block below is generated from it by
`python3 scripts/hepta-plasticity-status.py generate`.

A source capability is not an activation, acceptance, promotion or release claim.
The final exact-head and deterministic synthetic-merge receipts remain CI evidence;
source paths and test names are not pass receipts by themselves.

## Generated current-source state

<!-- BEGIN GENERATED CURRENT STATE -->
| Capability | Current source state | Surface | Source |
| --- | --- | --- | --- |
| `typed_mutation_grammar` | `source_implemented` | `MutationGrammarManifestV1` | `codex-rs/hepta-plasticity/src/mutation_grammar_v1.rs` |
| `parameter_v3_generation` | `source_implemented` | `generate_parameter_candidates_v3` | `codex-rs/hepta-plasticity/src/generator_v3.rs` |
| `parameter_authenticated_admission` | `source_implemented` | `propose_authenticated_parameter_plasticity_v1` | `codex-rs/hepta-intelligence/src/plasticity_product.rs` |
| `parameter_anchor_state_machine` | `source_implemented` | `PlasticityWriterStateV1` | `codex-rs/hepta-intelligence/src/plasticity_product.rs` |
| `agentd_selected_host_surface` | `source_implemented_not_runtime_enrolled` | `AgentdPlasticityHostV1` | `codex-rs/hepta-agentd/src/plasticity_host.rs` |
| `agentd_owner_evidence_binding` | `source_implemented_not_deployment_bound` | `PlasticityOwnerEvidencePolicyV1` | `codex-rs/hepta-agentd/src/plasticity_host.rs` |
| `agentd_anchor_fence_store` | `source_implemented_not_deployment_bound` | `AgentdPlasticityAnchorFenceStoreV1` | `codex-rs/hepta-agentd/src/plasticity_host.rs` |
| `topology_v2_proposal` | `source_implemented_proposal_only` | `propose_topology_v2` | `codex-rs/hepta-plasticity/src/topology_v2.rs` |
| `topology_protected_surface_policy` | `source_implemented` | `TopologyMutationPolicyV1` | `codex-rs/hepta-plasticity/src/topology_governance_v1.rs` |
| `topology_writer_handoff` | `source_implemented_validation_only` | `TopologyWriterHandoffV1` | `codex-rs/hepta-plasticity/src/topology_governance_v1.rs` |
| `topology_durable_registry` | `source_implemented_proposal_only` | `DurableTopologyProposalRegistryV2` | `codex-rs/hepta-plasticity/src/durable_topology_registry_v2.rs` |
| `topology_authenticated_admission` | `source_implemented_not_runtime_enrolled` | `propose_authenticated_topology_plasticity_v1` | `codex-rs/hepta-intelligence/src/plasticity_topology_product.rs` |
| `pls3_bounded_structural_canary` | `source_fixture_implemented_exact_ci_required` | `plasticity_structural_canary` | `qualification/lane-f-shadow/tests/plasticity_structural_canary.rs` |

**Claim boundary:**
- `productionImplementation=false`
- `targetHostExecutionProved=false`
- `independentAcceptance=false`
- `topologyApplicationImplemented=false`
- `weightInstallationImplemented=false`
- `activation=false`
- `promotion=false`
- `release=false`

**Remaining gates:**
- exact-head and deterministic synthetic-merge CI must pass for the final candidate
- selected deployment must bind concrete owner-evidence adapters and place the anchor/fence journal in an independent rollback domain
- independent semantic and security review
- operator recovery exercise and target-host telemetry/SLO evidence
- independent acceptance before any topology application or parameter installation
- activation, promotion and release remain separate external decisions
<!-- END GENERATED CURRENT STATE -->

## 1. Architecture boundary

The converged source uses three explicit layers:

```text
codex-hepta-plasticity
  deterministic, authority-free proposal mechanics
        |
        v
codex-hepta-intelligence
  authenticated generation/evaluation/admission + proposal persistence
        |
        v
codex-hepta-agentd selected-host surface
  authoritative frontier reads + owner evidence resolution + external anchor/fence
```

`codex-hepta-plasticity` intentionally remains dependent only on shared deterministic
primitives. It does not authenticate owners, query learning stores, mint evaluator
independence, or own host anti-rollback state. `codex-hepta-intelligence` composes the
signed learning-evidence and evaluation boundary. Agentd is the selected-host
composition surface: it reads authoritative owner state and invokes the product
adapter, but it does not become the authoritative writer for artifacts, evidence or
plasticity proposal facts.

This resolves the earlier architectural ambiguity between placing artifact/evidence
lookup inside the plasticity core and keeping it at the authenticated product/host
boundary. The latter is the current architecture.

## 2. Stable Parameter V2 record and governed V3 generation

`ParameterProposalV2` remains the stable canonical proposal record. Its existing wire,
golden digest and verification rules are not repurposed as an authentication layer.
Compatibility callers may still construct raw V2 records, but the governed product
path does not accept caller-selected candidates as a completeness proof.

`generate_parameter_candidates_v3` defines the bounded deterministic search profile.
For every declared update scale and parameter signal it computes the checked Q32
plasticity update from eligibility, modulator and learning rate, applies parameter
bounds and the existing per-layer/global trust regions, canonicalizes/deduplicates the
results, binds candidate identity to selected artifact + exact window + canonical
content, and emits one explicit no-change candidate. Completeness means completeness
relative to this exact declared V3 generator profile, not completeness over all
possible model updates.

## 3. Typed mutation policy

`MutationGrammarManifestV1` is the executable parameter mutation policy. It is not a
free-form `grammar_digest` placeholder. It binds one selected artifact, a revision,
explicit `(layer_id, parameter_id)` allow rules with maximum/minimum delta bounds, and
explicit protected parameters classified as authority, evaluation, deletion, privacy,
secret, runtime-topology or provider/tool surfaces.

The governed parameter product path verifies the manifest digest and rejects:

- parameters not present in the allowlist;
- any protected parameter even if the raw V3 generator could construct it;
- layer substitution;
- signal bounds wider than the manifest bounds;
- a grammar bound to a different selected artifact.

The Observer admission signature includes the exact mutation-grammar digest. A stale or
substituted grammar therefore invalidates authenticated admission rather than merely
changing local policy metadata.

## 4. Authenticated parameter proposal path

`propose_authenticated_parameter_plasticity_v1` requires, before durable append:

1. a canonical typed mutation grammar;
2. exact regeneration of the submitted V3 candidate set;
3. a trusted `Generator` signature over the generated set;
4. a trusted `Observer` signature over current artifact/evidence frontiers, exact
   window/generations, dataset/update/modulator/eligibility digests, generator digest
   and mutation-grammar digest;
5. signed independent evaluation for every generated update candidate;
6. one consistent authenticated evaluator identity across those evaluations;
7. exact predecessor and artifact/window slot consistency.

The product adapter derives proposer/evaluator identities from authenticated
principals. It does not treat unequal caller strings as proof of independence.

## 5. Selected-host evidence and artifact frontier

`AgentdPlasticityHostV1` is a non-test selected-host call surface. Before invoking the
product adapter it re-reads the authoritative `learning.artifacts::ArtifactRegistry`
and requires the baseline artifact to be present, lineage-eligible, Parameters/Model
kind, and exactly bound to the supplied objective, generation and content digest. It
also recomputes `artifact_frontier_binding_v1` from the exact registry head.

The host then actively resolves update-rule, modulator, modulator-broadcast,
eligibility and every per-parameter signal evidence digest through
`PlasticityOwnerEvidenceResolverV1`. A resolver implementation must query the owning
store and authenticate the owner receipt. Agentd independently recomputes a canonical
query digest over evidence kind, objective, selected artifact, exact window,
dataset, generation, layer/parameter identity and observation time; the returned receipt must bind
that exact query. `PlasticityOwnerEvidencePolicyV1` also requires an explicit
kind-to-owner allow-policy, so an otherwise valid receipt from the wrong owner is
rejected before proposal persistence. Every returned receipt is checked for non-empty
owner receipt/frontier digests and current validity. All receipts for one proposal
must agree on the exact qualification-evidence frontier that was signed by the
Observer.

The repository supplies the host seam and verification logic, not a fake universal
owner-store implementation. A selected deployment must bind concrete adapters for the
actual owner registries.

## 6. Durable parameter rollback protection

`AnchoredPlasticityWriterV1` now has an explicit lifecycle:

```text
Healthy
   | durable proposal append
   v
AppendPendingAnchor
   | independent anchor persistence succeeds
   v
Healthy

AppendPendingAnchor -- anchor failure --> Poisoned
Indeterminate/poisoned durable write ----> Poisoned
```

No normal read or append is permitted while pending or poisoned. Product success is
returned only after `PlasticityAnchorCommitterV1` acknowledges the exact current
registry anchor.

`AgentdPlasticityAnchorFenceStoreV1` is an append-only, checksum-protected, locked host
journal for monotonic new-registry fence issuance and independently retained anchors.
Its file must be placed by the deployment in a rollback domain independent of the
proposal registry. The source can enforce monotonic journal semantics; it cannot make
two files physically independent by itself.

## 7. Governed topology proposal path

Topology V2 remains proposal-only. It supports bounded typed
Add/Remove/Replace/Split/Merge/Rewire/Retire candidates, exact predecessor/candidate
generations, artifact/window-bound candidate identities, migration/rollback/evidence
bindings and deny-all authority.

`TopologyWriterHandoffV1` turns writer handoff from an opaque digest into a typed
validation record. For every topology update candidate it binds distinct source and
destination writers, source/destination domain digests, exact successor generations,
migration and rollback digests. `verify_topology_writer_handoffs_v1` requires exactly
one matching handoff for every update and returns a canonical handoff-set digest.

`DurableTopologyProposalRegistryV2` persists only topology proposals. It has a
scope/fence-bound header, checksum-chained frames, exact predecessor checks,
artifact/window slot conflict detection, idempotent replay, capacity bounds and
external-anchor recovery. It exposes no apply API.

`propose_authenticated_topology_plasticity_v1` composes trusted Generator and Observer
attestations, signed independent evaluation for every structural update candidate,
typed handoff verification, durable proposal append and external-anchor persistence.
It does not transfer writer authority or mutate the runtime graph.

## 8. PLS-3 bounded structural canary

`qualification/lane-f-shadow/tests/plasticity_structural_canary.rs` is the bounded
source-level PLS-3 fixture. Its success path verifies a typed Rewire candidate and
writer handoff, durably appends the proposal, obtains an external anchor and performs
an anchored reopen. Its abort path changes the rollback handoff and proves that the
handoff gate fails before persistence. The fixture also asserts deny-all authority and
that the selected artifact remains the rollback predecessor.

The canary is executed by the existing Lane F qualification workflow on exact source
and deterministic synthetic-merge candidates. It is not operator acceptance and it
is not topology activation.

## 9. Operations and observability profile

A selected host should emit bounded, non-secret events for at least:
`proposal_attempt`, `grammar_rejected`, `generator_rejected`, `evidence_rejected`,
`evaluation_rejected`, `registry_conflict`, `registry_busy`, `registry_indeterminate`,
`registry_poisoned`, `anchor_commit_failed`, `anchor_mismatch`,
`acknowledged_history_missing`, `proposal_appended`, `topology_handoff_rejected` and
`structural_canary_aborted`.

Raw model parameters, signatures, credentials, dataset records and payload bytes are
prohibited from logs. Digest/ID/count surfaces are sufficient for correlation.

Operational stop rules:

- any anchor mismatch, acknowledged-history loss, corrupt checksum/frame, authority
  grant, trust/signature-context mismatch or failed external anchor commit is an
  immediate stop for new plasticity work;
- any indeterminate durable write or poisoned writer requires handle retirement and
  anchored reconciliation; blind retry is prohibited;
- warn at `>=80%` configured proposal capacity and stop new admission at `>=95%`
  pending explicitly authorized rollover/retention work;
- repeated semantic conflicts above 1% of proposal attempts in a rolling 15-minute
  window are an alert condition;
- the target host p99 for authenticated generation/admission + durable append +
  external anchor commit remains below 2 seconds for the bounded profile; this is a
  target threshold, not measured production evidence.

## 10. Recovery runbook

1. Freeze new plasticity attempts. Do not modify the selected runtime artifact or graph.
2. Preserve proposal-registry bytes, last independently retained anchor, current
   writer fence, trust snapshot and artifact/evidence frontier receipts.
3. Retire any `AppendPendingAnchor`, `Poisoned` or indeterminate writer handle.
4. Reopen acknowledged history only with the independently retained anchor and exact
   scope/fence. Never convert a failed external anchor commit into success from the
   proposal file alone.
5. Re-read the authoritative artifact registry and owner-evidence frontiers before
   rebuilding signatures or evaluations.
6. For topology proposals, revalidate the typed migration/rollback/writer-handoff set.
   Do not fall back to legacy topology writes and do not apply the proposal as a
   recovery shortcut.
7. Resume only after the newly current anchor is durably retained in the independent
   rollback domain and the selected host has re-established a current trust snapshot.

## 11. Qualification and remaining external gates

Source closure still does not establish target-host execution, independent semantic or
security acceptance, operator recovery exercises, measured telemetry/SLOs, parameter
installation, topology application, activation, promotion or release. Those facts stay
false in `CURRENT_STATE.json` until their own evidence exists.

Exact-head and deterministic synthetic-merge CI are mandatory for the final candidate.
The implementation map links native/composed/host operations to their test identities;
CI receipts are separately retained by the repository workflows and must be evaluated
for the exact final head rather than inferred from this document.
