# Residual tensor cells at the native Hepta owner boundary

Status: integration design and source audit, 2026-10-28. The interfaces below
marked **proposed** are not implemented by this document. No held prompts or
held outcomes were opened for this audit. The audited native checkout is based
on `6bdbdf5d783d9acc7553ac4232f80e8cef257e62`; the adapter research files are
separate working-tree additions.

## What exists, and what this study has not yet connected

The native owner already executes learned float32 parameters. Its catalog cell
and V9 byte cell use SHA/SHAKE address features, a tanh hidden layer, and a
catalog or byte-bit output head. Selected models run through the real Agentd
control socket, canonical cognitive SQLite owner, signed artifact publication
and selection, source withdrawal checks, generation fences, and final-use
revalidation. Existing integration tests exercise reads, model/source changes,
closed admission and stopped or replaced nodes. This is real native execution
of those existing profiles, not evidence that the new residual profile runs
there. See [parameter dispatch](../../codex-rs/hepta-neuron/src/memory_parameter_cell_v9.rs),
[byte inference](../../codex-rs/hepta-neuron/src/memory_byte_cell_v9.rs),
[owner reads](../../codex-rs/hepta-agentd/src/memory_cell_runtime.rs),
[control admission](../../codex-rs/hepta-agentd/src/state_control.rs), and
[network stop tests](../../codex-rs/hepta-agentd/src/memory_cell_network_tests.rs).

The new [TensorCell](tensor_cell.py) really trains `A`, `B` and, when enabled,
its output head with Torch/Adam. Its inference equation is

```text
u = x A^T
z = x + u B^T
logits = z H^T + b
```

The shared frozen encoder emits 384 float32 features. The memory checkpoint
contains residual matrices, head parameters and provenance. In this study,
[Owner.memory](owner.py) passes canonical entity/workflow features to the
memory cell; query features separately drive the router. The current owner is
the research `Owner` with its own SQLite schema. Its `stop()` flag, exception
table and four-step interpreter are not Agentd admission or native owner
authority. [PROTOCOL.json](PROTOCOL.json) explicitly separates these levels.

| Boundary | Existing native profile | New research profile | Required bridge |
| --- | --- | --- | --- |
| Input features | SHA256/SHAKE address vector | Pinned multilingual MiniLM features | Explicit embedding identity and input binding |
| Numeric operator | Float32 weights, float64 tanh arithmetic | Float32 residual low-rank adapter and linear head | New numeric profile and decoder |
| Semantic value | `{factor, label}` | Three 4-bit values: reserve, pack, limit | Versioned typed value schema |
| Procedure | `{opcode, bias, limit}`, one of five operations | Four independently predicted operations, seven opcodes including stop | Versioned bounded interpreter |
| Composition address | One entity for event, semantic and procedure | Entity for event/policy; independent workflow for procedure | Two typed keys in the bound plan and dependency verifier |
| Source identity | Owner-derived revision/source IDs and complete cut | Authored research IDs and an `active` flag | Explicit owner import and provenance mapping |
| Stop | Agent lifecycle, current generation and admission checks | Python flag plus an exact exception table | Real native control tests and an owner-backed exception profile |

Both types use float32 storage, but their input, operator and output semantics
differ. Relabeling a checkpoint as `hepta.memory.byte-native.v9`, putting a
three-value policy into `factor`, or representing a four-step program as an old
single `opcode` would not preserve the trained model or this experiment.

## Smallest faithful executable path

Use a new **proposed** residual model profile and a new **proposed** inventory
value/plan profile. Keep the established artifact and owner authority chain.
The first native milestone should be one published semantic cell read through
the real socket, followed by a real admission stop. It still needs the new
semantic value contract: even a single existing semantic checkpoint cannot be
faithfully exposed under the old `{factor, label}` contract.

The work can proceed in bounded stages:

1. Export existing trained checkpoint bytes and establish Python/Rust numeric
   parity without an owner. This verifies a decoder and operator only.
2. Import the corresponding semantic sources through the canonical owner,
   publish and independently select a residual bundle, then run semantic reads
   and lifecycle-stop races through Agentd. This establishes native ownership
   for the new model, but does not establish composition or language routing.
3. Add the four-step typed procedure, independent workflow key, exact exception
   checks and composition dependencies. Only this stage can reproduce the
   research owner's complete execution contract.
4. Connect the pinned learned router/encoder worker, then qualify continual
   updates, split/merge, sleep/wake and migration with these exact new artifacts.
   Existing V9 migration evidence remains evidence for V9 until this is done.

Training a different residual head to emit old V9 values would be a separate,
useful compatibility experiment. It would not install the current checkpoint
or close the integration gap reported here.

### Rust-readable artifact

Add a **proposed** `hepta.memory.residual-native.v1` JSON envelope that remains
compatible with the bundle's exact UTF-8 payload handling. It should contain:

- `kind`, input dimension, rank, ordered output specifications, output profile,
  numeric profile and acceptance policy;
- `A[rank, dimension]`, `B[dimension, rank]`, `head.weight[width, dimension]`
  and `head.bias[width]`, preserving Torch row-major layout;
- the exact original checkpoint/parameter digest, training receipt digest,
  encoder identity digest, feature-input profile, owner source cut, support map
  and complete training lineage;
- explicit parameter, shared-head, feature-cache, support and encoded-byte
  costs. Shared arithmetic does not make duplicated serialized heads free.

A simple exact transport is bounded hex-encoded little-endian IEEE754 float32
bytes with declared shapes. It avoids a Rust Torch dependency, NPZ decompression
and accidental JSON float-rounding changes. JSON arrays are another option only
if a round-trip test proves identical float32 bits. Validate checked shape
products, total byte caps, finite elements, source coverage and all digests
before allocating the runtime model. No pickle, answer catalog or gold output
is needed.

Preserve the current `TensorCell.parameter_digest()` algorithm or record a
separate native-layout digest and an explicit mapping receipt; do not pretend
that a different hash concatenation equals the original parameter identity.
The residual evaluator should retain the factored matrices. Folding `H(I+BA)`
into a dense matrix changes stored cost, floating-point evaluation order and
the ability to test adapter ablation.

The profile must specify arithmetic and tie behavior. Float32 weights alone do
not guarantee bit-identical Torch BLAS and Rust scalar reductions. Compare raw
logits with a declared tolerance, require matching typed outputs on qualified
inputs, and abstain on insufficient selection margins. Do not silently inherit
the catalog softmax or byte model's confidence interpretation.

### Binding pretrained embeddings

Bind the aggregate `base_encoder_sha` from [encoder.py](encoder.py), not just
the ONNX model hash. That identity includes the pinned tokenizer and pooling
files, maximum-token setting, batch-one execution, mean pooling, L2
normalization, dtype and frozen model revision.

For the smallest native memory-read milestone, export a **declared canonical
feature cache** alongside the residual tensors. This matches the current
Python owner's canonical-feature invocation: for each typed address, bind the
canonical input-text digest, encoder identity and exact 384-element feature
digest. The cache contains features, not answers, and its complete stored and
resident cost must be charged. It allows `predict(key)` to remain the native
entry point while the new model profile selects the pinned feature vector.
The owner still validates the key-to-source support independently. A cache
digest proves integrity, not that an encoder actually computed the vector;
export provenance and recomputation by the pinned encoder must establish that.

For live query-derived features, extend the configured resolver/worker boundary
with a **proposed** bound feature object:

```text
request_digest + owner_cut + typed_address + model_profile
encoder_identity + canonical_text_digest + feature_bytes_digest
dimension + finite float32 feature bytes
```

The worker is selected at startup and pinned by its closed import profile. The
wire caller must not supply a supposedly authoritative vector, operation,
source list or expected answer. The host must check the entire object against
the current request, selected model and owner cut before inference. A feature
hash by itself is not authentication. Current `MemoryCellResolvedAddressV1`
contains an operation but no feature object, so live features require an
explicit extension; they cannot be smuggled into an entity string or stored in
a cross-request mutable resolver side channel.

## Native typed values, plans and source migration

Introduce a named inventory profile with versioned records and request/readout
envelopes. Preserve V1 validators and their strict rejection behavior. The new
semantic value is a bounded `{reserve, pack, limit}` object. The procedure is a
bounded sequence of the seven declared opcodes. Define four-step budget,
explicit stop, missing-stop rejection, invalid-opcode rejection, checked
arithmetic and floor-division behavior. Python `//` and Rust integer division
differ for negative operands; either retain Python semantics or explicitly
restrict the new profile's input domain. A predicted program is data for the
registered interpreter, never executable code or effect authority.

A bound composition plan must identify `entity_key` and `workflow_key`
separately. Its required sources are the current event and semantic policy for
the entity, the current procedure for the workflow, and the exact applicable
exception/hold state. The absence of an exception must also be bound to the
owner cut. In the current native code,
`MemoryCellOwnerSnapshotV1::required_sources` and
`memory_cell_execution::predict` always use `request.entity`; changing the
router alone cannot fix this. Changing request contents after routing would
also violate the current request-equality check.

Use the owner writer to import authored development sources as new versioned
records. Preserve the old profile's data and record an explicit mapping from
research source ID, content digest and version to canonical owner memory ID,
revision and source ID. Prefer training/export directly from the new owner's
snapshot. For an existing checkpoint, any provenance rebinding must verify this
mapping and retain the original training receipts; editing `source_ids` to
match an arbitrary owner cut is not valid migration. Research event sequence
numbers `0` and `1` are not native Unix timestamps: the import must define and
record effective times. Import exceptions into a dedicated exact owner-backed
record/profile; they must not be learned away or encoded as adapter confidence.

Native snapshot acquisition currently loads typed record values as well as
source identities. The native prediction path does not replace model output
with those source values, but this is not a claim that no source payload was
read from SQLite. A stricter identity-only inference audit would require a
minimal snapshot view while preserving complete lineage/freshness checks.

## Concrete implementation surfaces

All new names in this table are proposed. Existing names identify audited code.

| File / API | Required change |
| --- | --- |
| `qualification/memory-cell-adapters/tensor_cell.py`; new `export_native.py` | Export exact trained tensors, output schema, canonical feature bindings and provenance; no training or held-set selection in the exporter. |
| `codex-rs/hepta-neuron/src/memory_parameter_cell_v9.rs` | Add a residual variant and delegate kind, digests, supports, lineage, numeric/address profiles, cost and prediction. |
| New `codex-rs/hepta-neuron/src/memory_residual_cell.rs` | Bounded loader, factored residual operator, binary/multiclass head decoding and profile-specific confidence. |
| `codex-rs/hepta-neuron/src/memory_population.rs` and `memory_population_cache.rs` | Admit the new schema explicitly; retain exact support partitions, full population identity and reload checks; handle profile-specific abstention. |
| `codex-rs/hepta-neuron/src/memory_population_cost.rs` | Charge canonical feature cache, residual matrices and heads explicitly, including physical serialization duplication. |
| `codex-rs/hepta-cognitive-types/src/memory_cell_values.rs` and `memory_cell.rs` | Add versioned inventory values, dual-key plans/requests, stop statuses and bounded interpreter. Do not broaden V1 into untyped JSON. |
| `codex-rs/hepta-memory/src/memory_cell_owner.rs` and `memory_cell_write.rs` | New record profile, writer validation, exact source import, dual-key `required_sources`, exception cut and final readout revalidation. |
| `codex-rs/hepta-agent-protocol/src/memory_cells.rs` and `lib.rs` | Add explicit versioned snapshot/read method and payload shapes where required; preserve existing strict framing and size limits. |
| `codex-rs/hepta-agentd/src/memory_cell_client.rs` and `memory_cell_snapshot.rs` | Typed V2 read/export, decode and validate the exact new envelopes without accepting arbitrary claimed owner snapshots. |
| `codex-rs/hepta-agentd/src/memory_cell_bundle.rs` | Decode a new bundle/value profile; validate exact owner coverage; include encoder/address/numeric/output identities in manifest bindings. `bind_manifest` currently hardcodes the SHA/SHAKE normalization profile. |
| `codex-rs/hepta-agentd/src/memory_cell_runtime.rs` and `memory_cell_execution.rs` | Dispatch the new typed plan/model, validate feature bindings if live features are enabled, preserve source/prediction labels and enforce program budget/holds. |
| `codex-rs/hepta-agentd/src/memory_cell_address_worker_wire.rs`, `memory_cell_address_worker_config.rs`, and a new worker profile | Optional live router/feature extension with complete first-party import pins, bounded frames, request/cut hashes and cancellation behavior. No global relaxation of code-pin admission. |
| `codex-rs/hepta-agentd/src/state_control.rs` | Route the new method through the same readiness checks before and after awaited execution. Do not add a fixture-only alternate read path. |

The existing dependency-injection port,
`AgentdMemoryCellRuntimeV1::new(..., Arc<dyn MemoryCellAddressResolverV1>)`, is a
suitable host seam. The current profile registries are closed and must receive
explicit new entries. This is a bounded model/contract extension, not a
configuration-only change. It does not require loosening the security model.

## Publication, authority and stop invariants

Retain `MemoryCellBundleCandidateV1`-style candidate construction from a genuine
owner snapshot, `MemoryCellReleaseHostV1::publish`, independently verified
`install_selected`, authenticated CURRENT and withdrawal-bound admission. The
candidate must not publish or select itself. The new bundle must bind the exact
source cut and every training dependency, including unqueried sources.

On every read, preserve the ordering in
[AgentdMemoryCellRuntimeV1::read_bound](../../codex-rs/hepta-agentd/src/memory_cell_runtime.rs):
acquire owner cut; check selected bundle; resolve and check bound request;
execute native model; revalidate selected release; revalidate current source
owner immediately before exposure. A successful model read remains a
`ModelPrediction`, and composition remains mixed provenance. External effects
still require the existing separate authority/final-use mechanism.

Keep four different stop conditions distinct: Agent lifecycle/admission stop,
source withdrawal, exact policy hold, and the program's normal `stop` opcode.
The real control path already checks `Running`, all readiness gates, open
admission and an unfenced generation before and after `host.read().await`.
A new profile should use those checks rather than introduce a local Boolean as
its authoritative stop control.

## Acceptance evidence required before claiming native integration

- Exported parameter bits and original parameter identity match the checkpoint;
  Torch and Rust logits/typed predictions agree within the declared numeric
  contract, including threshold/tie cases. Drift in any tensor, encoder,
  canonical feature or output profile fails closed.
- A real control-socket read uses the selected trained residual artifact and
  actual SQLite owner. With the owner fixed, an adapter ablation or different
  qualified parameter artifact changes predictions as expected. A constant
  single-class fixture can test infrastructure but cannot establish this claim.
- Both entity and workflow keys affect composition independently. Invalid
  programs, insufficient budgets and exact holds produce no partial successful
  value. Source IDs equal the native owner's required dependencies.
- Stop/drain or generation rotation before and during a paused in-flight read
  prevents exposure; restart requires current admission. Publication rotation,
  correction and withdrawal between inference and final use also reject stale
  output, including changes to an unqueried training source.
- Costs include the shared base, cached features, duplicated heads, adapters,
  routes, source/provenance records, exceptions and owner/runtime work. A finite
  synthetic success does not establish general memory compression or universal
  memory-system emergence.

No new native integration is claimed until these tests run against the new
profile. Python adapter results and existing V9 native results remain separate
evidence in the meantime.
