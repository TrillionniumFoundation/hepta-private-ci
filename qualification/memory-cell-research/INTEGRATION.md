# Hepta integration boundaries for MemoryCell

This package is an executable research prototype under `qualification/`. It
does not register a production cell, modify a Rust wire contract, activate an
organ, or train a pretrained language model. Its numerical model and Python
manifests are research formats. Future product work must supply compatible
owner adapters, durable recovery, a real inference/training backend, and
independent evaluation.

## Inspected architecture

These design bindings refer to the inspected repository `main` snapshot at
[`f8c9419df6ddeb36ff8b522a50219981fb8d9345`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/f8c9419df6ddeb36ff8b522a50219981fb8d9345).
Local links are convenient navigation; use that commit when reproducing the
baseline reading. The research runner records a separate executed-source commit.

- [CNS technical design](../../docs/cns/TECHNICAL.md) defines cells as instances
  within existing module/organ ownership and preserves generation-bound
  composition and owner lifecycle.
- [HNMF technical design](../../docs/hnmf/TECHNICAL.md) distinguishes episodic,
  associative, procedural, and parametric memory, defines the seven functional
  populations, and maps them to existing owners.
- [Neural biomimicry specification](../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md)
  defines bounded cell adapters, selected parameter bundles, and the
  parameter-proposal/artifact boundary.
- [Neuron execution boundary](../../codex-rs/hepta-neuron/EXECUTION.md) and
  [plasticity implementation](../../codex-rs/hepta-neuron/src/plasticity.rs)
  distinguish recurrent state and candidate learning signals from trained-model
  execution, durable publication, and product activation.

Seven population labels are engineering roles. Their presence does not imply
seven trained language models or learned memory semantics. A new MemoryCell type
should be a scoped implementation behind these contracts, with measured behavior
and explicit read/write/forget interfaces.

## Place responsibilities with existing owners

The following is an integration plan, not a claim that these Python operations
are already wired to production. The authoritative ownership map remains
[HNMF section 12](../../docs/hnmf/TECHNICAL.md#12-existing-module-ownership-map)
and the [module guides](../../docs/modules/README.md).

| Responsibility | Existing owner or composition boundary | Required connection |
| --- | --- | --- |
| Scoped cell state and checkpoint | `neuron.runtime` | Freeze selected bundle, scope, predecessor, generation, and resource limits; publish state through its current writer. |
| Authenticated numerical inference | `inference.control` and its admitted worker/backend | Bind actual execution and tensor results to the selected artifact and request; Python predictions are not production receipts. |
| Event revisions and tombstones | `cognitive.store`, `cognitive.read` | Read coherent authorized source cuts and current revisions; preserve source identity and deletion state. |
| Typed readout and evidence contracts | `cognitive.types`, `context.compiler` | Distinguish model predictions from revalidated source evidence through versioned types. |
| Retrieval and typed projections | `memory.retrieval`, `knowledge.graph` | Supply bounded cues and supported relationships; retain exact retrieval as a fallback and comparator. |
| Learning records and credit | `learning.ledger` | Record writes, decisions, observed outcomes, replay membership, support lineage, and costs. |
| Parameter training | `learning.operator` | Execute bounded jobs against frozen examples, optimizer settings, and parent artifacts; emit candidates. |
| Replay and consolidation | `compact.engine` | Schedule bounded replay and consolidation while preserving source ownership and foreground budgets. |
| Immutable model bytes | `learning.artifacts` | Store verified tensors, manifests, predecessors, compatibility identities, and revocation lineage. |
| Split/merge proposals | `learning.plasticity` | Propose bounded structural changes; do not independently activate topology or replace an authoritative writer. |
| Circuit execution and recovery | Existing TaskFlow and organ lifecycle | Drain or migrate work, fence generations, publish coherent routes, and recover or roll back transitions. |
| Acceptance evidence | `learning.eval` | Evaluate hidden tasks, retention, source deletion, routing, ablations, actual costs, and transfer before promotion. |

The network does not need a new central memory authority. A learned route
selects among admitted cells; it cannot create an owner, grant access to source
records, or convert a prediction into an observed fact.

## Parametric output must not become a source fact

[RecallPacketV1](../../docs/hnmf/TECHNICAL.md#46-recallpacketv1) has a specific
meaning: successful recall selects one or more exact event revisions; abstention
selects none. `context.compiler` attaches original source data only after exact
revalidation. Its current
[Rust definition](../../codex-rs/hepta-cognitive-types/src/hnmf_learning.rs)
must retain that interpretation.

A parameter model's class or generated answer is a prediction. Do not put it in
`RecallPacketV1` as a recovered authoritative event or invent an event revision
to satisfy the success shape. A future versioned readout profile should carry
the predicted value or distribution, model/bundle identity, scope and validity,
support references, calibrated-confidence/OOD disposition when available,
abstention, and resource receipt. If original evidence is needed, retrieve and
revalidate it through its source owner. The prototype's raw softmax score is not
calibrated confidence.

## Trained adapters require artifact references

The existing internal `ParameterProposalV2` permits at most 4,096 scalar deltas;
see the
[bounded adapter contract](../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md) and
[implementation types](../../codex-rs/hepta-plasticity/src/types.rs). Keep that
format for bounded local updates. A larger adapter or full model needs a
separately versioned artifact-level delta reference with verified tensor
inventory, shapes, ordering, precision, numerical bounds, parent/target identity,
source lineage, and integrity checks. Do not enlarge the scalar protocol or
treat an arbitrary digest as evidence that a model was trained.

For a language-model backend, the immutable compatibility bundle must also bind
base weights/code, tokenizer and preprocessing, adapter targets, output schema,
state compatibility, and calibration/policy identity. The research
`manifest.json` / `tensors.npz` pair demonstrates artifact verification for this
small NumPy model only. It does not implement that production wire adapter.

Selected shared weights remain immutable during a run. Training emits a new
candidate bundle, and adoption occurs through the existing selector and coherent
generation change. Scoped fast state may evolve under its checkpoint contract;
it must not silently modify another cell's shared weights.

## Maintenance and structural changes

Source corrections create new revisions. A trainer resolves current facts for
its declared source cut and preserves the superseded history as lineage rather
than replaying conflicting labels. Deletion invalidates dependent artifacts and
descendants according to support lineage. Serving guards can block them before
replacement training finishes, but a blocked answer does not demonstrate that
the deleted information has disappeared from tensors.

The prototype separately exposes guard behavior and clean retraining that
excludes removed records. Production erasure requires the owner's complete
deletion/rebuild process, including replay, checkpoints, derived artifacts,
descendants, and restored copies. The research evidence does not certify
statistical unlearning or distributed deletion completion.

A split or merge produces candidate children or a consolidated model, routing
metadata, and a successor artifact lineage. Selection must use a key-disjoint
selection set before hidden test outcomes are read. Adoption must pay for all
candidate training, migration, retained source/replay payload, metadata, and
rollback state. Equal numerical tensor capacity does not equal complete deployed
system cost. The prototype records costs and can reject a structural change;
cell proliferation is not itself an improvement.

Publishing a new route requires a compatible graph generation, admitted target
artifacts, source/deletion watermarks, and recovery semantics. Existing owner
fencing and circuit recovery remain responsible for concurrent work and crashes.
The current supplied graph and deterministic structural candidates demonstrate
bounded mechanisms; they do not demonstrate autonomous topology discovery.

## Evidence needed before product adoption

Use the formal evidence described in [README.md](README.md) to assess the
bounded numerical experiment. A successful six-stage execution is not a product
promotion. Further implementation and evidence must address a real model and
tokenizer, realistic typed write/read contracts, independent natural-language
and task streams, calibrated abstention, source-authority preservation, complete
storage/training/read budgets, deletion lineage, owner crash/recovery, and
admission/rollback of an exact selected-artifact generation.

The fresh-process reader is a controlled file-access experiment, not an OS
security sandbox. Independent synthetic seeds and renamed domains test the same
generator; the pinned module registry tests a small real categorical mapping.
Neither establishes general memory, spontaneous learning of memory types, or
independent future-time efficacy. Those conclusions remain open regardless of
whether a local numerical threshold passes.
