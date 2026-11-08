# Original generation learning-use readback

`NeuronGenerationRuntimeHandleV2::read_learning_next_use_readback` exports the
existing retained-model observation. The distinct
`read_learning_updated_next_use_readback` method exports use of a selected
candidate after its original model-reset publication. Both are read commands
in the same bounded generation actor. They open no additional journal, dispatch
no work, issue no grant, consume no nonce and write no learning checkpoint.

The caller supplies the existing coordinator and the exact generation intent
retained by the journal. The updated-model method also takes the original
predecessor manifest.
The original `read_next_use` or `read_updated_next_use` verifies these inputs
against the actual publication and guarded journal. The exporter then reads
the actual committed receipt and complete generation observation from that
same journal, checks their linkage, serializes them and performs one final
`require_current()` before returning.

The original journal's `receipt_for_intent` guards correspondence between the
supplied use intent and the committed request/receipt. The exported intent is
not the entire original worker request. An external consumer can pin the exact
intent bytes, but must not claim that hashing that projection reconstructs
`receipt.request_digest` or repeats the native request validation.

## Two decisions, one historical boundary

`retained_model` means the existing evaluated decision retained the original
complete model manifest for the next task. It preserves the legal NoUpdate
path. A new task-owner generation is not a claim that model weights improved.
The exporter neither converts missing evaluation into NoUpdate nor changes the
existing coordinator's accepted decisions. NoUpdate retains the complete
manifest, including weights, runtime, schemas, continuation components and
their limits; equality of only a weight or bundle label would be insufficient.

`adopted_model_reset` means the original publication replaced the complete
manifest and initialized the new task owner under the existing qualified
candidate checks. This profile does not claim state preservation or migration.

The supplied coordinator is after its Selection receipt and before its NextUse
receipt. `learning_head` identifies that exact cut; `learning_decision_head` is
the Selection receipt's predecessor. Neither is a newly completed learning
checkpoint. The host must still authenticate, attest and durably checkpoint the
returned observation under the existing learning-owner protocol.

Successful committed use can still have pending output. The raw observation
preserves pending request/output, actual committed prefix, revision and costs.
Only the original acknowledgement and lifecycle rules establish delivery/drain.
An acknowledged/drained owner can still have `stopped: false`; acknowledgement
does not imply a model STOP or a terminal episode. Conversely, a stopped model
can still have pending delivery. Consumers must inspect the original pending
request, pending output and stopped fields separately.
The export makes no model-quality, training-legality, independent-evaluation,
settlement, cold-download or full automatic-evolution qualification claim.

## Exact bytes and wire identity

The public `AgentdGenerationLearningUseReadbackV1` is serialize-only, with private
fields and no Deserialize implementation. Its outer fields are:

- `schema`: `hepta.agentd.learning-use-readback.v1`.
- `payload_json`: the exact compact native serde JSON string.
- `payload_digest`: SHA-256 of the ASCII domain
  `hepta.agentd.learning-use-readback.v1`, one NUL byte, then the exact UTF-8
  `payload_json` bytes. This is a native 32-byte array, not hexadecimal text.

The payload contains the decision type, original learning operation/head/source
pins, a projection of the typed native learning observation and the exact
retained intent. It also retains these native serde preimages as UTF-8 strings:

| Field | Original value |
| --- | --- |
| `manifest_json` | Complete selected `CellBackendManifestV2` |
| `previous_manifest_json` | Original predecessor manifest for an update; null for retained use |
| `publication_json` | Actual `Published` intent, witness, public signed grant and grant digest |
| `step_receipt_json` | Actual `CellGenerationReceiptV2` returned for the retained intent |
| `generation_observation_json` | Complete `CellGenerationObservationV1`, including pending delivery and costs |

`observation.kind` is `retained_model_next_use` for `retained_model`, with the
original `task_owner_publication` digest and a null `state_cutover_receipt`. It
is `next_use` for `adopted_model_reset`, with the original
`state_cutover_receipt` and a null `task_owner_publication`. Both carry bundle,
state-partition, owner-checkpoint, selection and committed-step digests from the
original typed owner observation. The projection is never accepted as an
input to the learning owner.

The learning source pins are `source_run_id`, `source_task_receipt`,
`source_selected_artifact` and `source_selected_bundle`. The exact retained
intent includes `operation_id`, `task_digest`, `source_frontier`,
`predecessor_digest`, `input_digest` and `deadline_micros`. A consumer must bind
these to independently retained task and version expectations, not derive its
expectations from the submitted export.

External readers should hash these exact UTF-8 preimages. Reordering JSON keys
or replacing arrays, integers, nulls or strings changes native digest identity.
The exporter bounds the manifest, predecessor manifest, step receipt, generation
observation and complete payload to 8 MiB through a writer that refuses growth
beyond the cap. Publication bytes reuse the existing published-record serializer;
the complete payload cap also bounds their inclusion. The escaped outer JSON
envelope may be larger than the payload string. No input/parser is added here.

The publication contains public signing material, not private keys. A signature
or hash alone is not independently trusted custody. A consumer still needs its
own separately retained expected identities, trust, source pins and policy.

## Authority and freshness

`authority()` is always `AuthorityPosture::DENY_ALL`. The payload records
`authority: "DENY_ALL"` and `current_permission: "NOT_EXPORTED"`.
This posture applies to the complete envelope and every embedded JSON record.
Original embedded schemas are preserved; none gains authority by inclusion or
by successful external JSON parsing.

The live original-owner check is mandatory at the end of the read, including
after serialization. That success is not a lease after the check, does not
export a current authority frontier, and cannot revive permission after a later
CURRENT change, withdrawal or revocation. The retained witness describes its
original verification boundary, not the export's later clock. No remote decoder
can reconstruct the sealed Rust value or its authority from these bytes.

## Engineering controls and optional evidence export

The existing retained/adopted actor tests cover missing committed use, wrong
intent/manifest, pending and acknowledged output, cold recovery without another
execution or nonce, and current/withdrawal/revocation refusals. Retained-model
controls preserve both pre-use zero-execution refusals and post-use refusals.

Setting `HEPTA_GENERATION_LEARNING_READBACK_STDOUT` in the test runner retains
four original serialized observations on stdout with the marker
`HEPTA_LEARNING_READBACK_V1`, followed by `retained_pending`, `retained_acked`,
`adopted_pending` or `adopted_acked`, and the compact outer JSON. Recovery compares
the same bytes without printing another success. Collectors must preserve the
original byte ranges and source/log identities instead of rebuilding fields.
These fixtures use synthetic learning evidence, test issuer keys and synthetic
worker output. They are engineering controls, not production or scientific
qualification.
