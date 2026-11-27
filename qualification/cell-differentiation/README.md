# Cell roles, population accounting and demand-driven differentiation

This package makes the seven-role engineering proposal executable as bounded
capability contracts, population accounting, a proposal-only differentiation
study, and a CPU learning experiment. Seven is an initial functional taxonomy.
It is not an experimentally optimal number of types, experts, instances,
models, processes or organs.

## Source and scope

Development base: main at `732e934ba496d90fbe042b8d41d479ef901643e5`.
The complete neuron, plasticity and shared-types Git subtrees are identical
at integration candidate `07378034e060f23259bc99c7367f12b1284140f3`:

| Subtree | Exact Git tree |
| --- | --- |
| codex-rs/hepta-neuron | c8a74a3012db3798b0a0c938ec60f60e136ad493 |
| codex-rs/hepta-plasticity | 63cc049c0e680b4a7c6b52c2b19c5c038047c6e1 |
| codex-rs/hepta-types | ee71d3c1aa9bceae6bab9f304fc75e115dc49297 |

The independent feature branch imports no unrelated integration commits. Its
native modules belong to the existing neuron.runtime and learning.plasticity
owners. They contain no dispatcher, publisher, credential, database, model
server or external-effect handle. The existing public Cell admission and
artifact/structure lifecycle remain authoritative.

## Initial roles and learning boundaries

| Role | What may be learned | Existing integration owners |
| --- | --- | --- |
| Perception and encoding | Relevant features, events and missing-input signals | Modality adapters, inference.control, context input |
| Memory and association | Retrieval, association, compression, replay and source relevance | HNMF, retrieval, KG, context |
| Prediction and simulation | State transitions, tool-result predictions, risk and future observations | World-model backend, learning.operator |
| Decision and coordination | Routing, activation, resource allocation, continue/stop and organ coordination | Intuition, NDU, Circuit policy |
| Action and generation | Answer, code, plan and action candidates, tool-argument proposals | Generators, skills, tool adapters |
| Verification and metacognition | Contradictions, calibration, failure attribution and evidence sufficiency | learning.eval, metacognition |
| Learning and development | Curriculum, replay, training configuration, specialization and structural proposals | learning.operator, learning.plasticity, engineering |

A critic's confidence remains advisory. Independent owners establish final
task outcomes. Development cells produce candidates; existing lifecycle owners
publish parameters and migrate state after their own gates.

Resource/homeostasis and authority/effect support are separate deterministic
categories. Existing owners retain quotas, backpressure, deadlines, recovery,
identity, authorization, transactions, deduplication and effect confirmation.
Learned policies may request work inside those limits; their predictions do
not change the governing rules.

The existing 40 ownership modules, 24 CNS organs and seven HNMF engram groups
describe different decompositions. None supplies a Cell type count.

## Four population measurements

| Measurement | Identity counted | Rejected inflation |
| --- | --- | --- |
| Capability types | Distinct input/output/state schemas and behavior contracts | Renaming an identical contract or changing only its role/revision |
| Expert versions | Immutable capability-bound parameter bundles | Another name for the same complete bundle |
| Runtime instances | Independent scoped state slots and their owners | Repeated instance IDs or the same slot under a different owner |
| Active instances | Bounded available instances at the observed generation/version | Duplicate, unknown, cross-scope, stale, retired or quarantined entries |

Different experts can share a base model. Different instances can share an
immutable expert while retaining separate state. The native test inventory
has two types under one role, three versions sharing one base, four instances
and two active observations: 2 / 3 / 4 / 2.

The inventory is immutable and scope-local. Retired or quarantined slots remain
in retained-instance and reserved-byte accounting. Actual schema resolution,
artifact authentication, physical slot ownership and scheduling belong to the
existing owners. A census is an observation check, not an activation command.
Its authority is always DENY_ALL.

## Demand and study protocol

1. Freeze the parent/version/contract, trigger, observation windows, diagnosis,
   thresholds, complete task panels, comparison protocols, retention slices,
   cost profile, identities, isolation and migration requirements.
2. Establish either a persistent task partition or persistent error over
   multiple adjacent nonoverlapping windows. Require a specified diagnosis
   of negative transfer, capacity shortfall or routing confusion. Repeated
   tasks or source observations cannot manufacture persistence.
3. Train a compatible child from the pinned parent in an isolated nursery.
   Preserve the serving parent, state schema, exact version lineage and
   separate namespace.
4. Compare six arms: unchanged parent, continued parent, expanded single
   model, fixed experts, random grouping and the differentiated candidate.
   Every arm observes the same preregistered new-task and old-task panel.
5. Keep all requested tasks. Known failures remain in the denominator;
   pending outcomes retain HOLD. Include training, evaluation, inference,
   routing, storage and migration costs under the frozen metering profile.
6. Check every old-task slice against the unchanged parent. After migration,
   also check the candidate's own pre-migration improvements. Require the
   original checkpoint on rollback and no remaining predecessor writers,
   unresolved effects or replayed external effects.
7. Require a measured net improvement over every comparator under the frozen
   policy. Otherwise retain the parent or record the missing evidence.

The Rust study works with bounded integer scores and costs. The thresholds
and every policy field are content-bound before observation. Receipts are
immutable and may return only HOLD or RecommendForOwnerReview, always with
DENY_ALL. These are fixed-panel research conclusions, not statistical efficacy
or production acceptance.

Known principal, signing-key, credential-chain and controller collisions are
rejected pairwise among generator, evaluator and observer. These collision
checks and content digests do not authenticate identities. The product owner
must still validate the actual provenance and independently observed outcomes.

## Connection to the existing proposal owner

The complete topology-request bridge binds the study to its exact parent
artifact, baseline and successor generation, rollback predecessor, actors,
study/window, evaluation evidence and single intended split. It invokes the
existing topology-proposal constructor, which retains its no-change candidate,
RequiresIndependentAcceptance status and DENY_ALL authority.

The existing path still provides:

| Responsibility | Existing owner |
| --- | --- |
| Frozen evaluation plans and independent outcomes | ProductEvaluationRunnerV1 |
| Durable one-time final holdout consumption | FencedFinalHoldoutOwnerV1 |
| External provenance and identity authentication | Agentd topology product admission |
| Governed proposal persistence | DurableTopologyProposalRegistryV1 |
| Registered-candidate structural canary | StructuralCanaryControllerV1 |
| Artifact publication and coordinated adoption | Learning artifact and runtime lifecycle owners |
| Writer exclusivity and effect reconciliation | Existing store, effect and recovery owners |

The bridge is exported for existing owners and exercised by the new test fixtures.
This change does not wire a production service into that bridge. Authenticating
runtime observations and qualifying live adoption remain separate work.
No new code in this package can bypass the existing owner chain.

## CPU research experiment

The NumPy FP64 experiment trains actual small regression models on a controlled
two-task problem. It includes conflicting-task and redundant-specialization
scenarios, five fixed seeds, and distinct pretrain/train/monitor/validation/test
streams. All six arms share the same starting parent. Task identity is supplied
to the experiment; routing is not a learned multimodal recognizer.

The expanded single-model baseline includes task-feature interactions. Fixed
experts use a preassigned partition; random grouping uses a seeded request hash.
A differentiated candidate can outperform a shared parent and still remain
HOLD because another comparator performs as well. The thresholds and seeds
must not be changed after seeing test results.

The report retains individual requests, model parameters, source/data/plan
digests, before/after migration behavior and stage costs. A migration is not marked
verified when either observation population is incomplete. Verification rebuilds
the synthetic data from the frozen seed, checks model predictions, recalculates
demand decisions and checks the expected cost-stage populations. The source
manifest is checked against the actual Python source bytes. A caller-declared
Git commit is metadata until separately verified against those source bytes.

Floating-point operation estimates, routing decisions, hash bytes, parameter
bytes and measured elapsed time retain separate units. They are not GPU
measurements, physical-energy counters or production-throughput assessments.
Serialization replay is an in-process experiment, not a live state migration.

The Python decision uses MSE gains and compute/storage caps; the Rust decision
uses bounded integer scores, metering and net-gain policy. This experiment does
not execute or establish behavioral parity with the Rust policy implementation.
It does not establish seven semantic neural organs or recursive self-improvement.

## Reproduction

Python 3.12 and NumPy 2.3.5:

```bash
python3 -m unittest discover -s qualification/cell-differentiation -p 'test_*.py' -v
python3 qualification/cell-differentiation/run_study.py --output /tmp/cell-study.json
```

Native tests, from codex-rs with the repository-pinned toolchain:

```bash
just test --locked -p codex-hepta-neuron -p codex-hepta-plasticity
```

The dedicated workflow checks out the exact source SHA, runs the original
native package-test entry point and the separate CPU study, checks scoped lint
and formatting, and retains raw results including failures. Source-stage
commits make the changes independently reviewable.

## Qualification status

See VALIDATION.md for actual results and the exact published source identity.
A source implementation, authored test, queued workflow or synthetic result
does not establish native execution, authenticated acceptance, live adoption
or RSI efficacy. Missing outcomes and unavailable execution remain visible.
