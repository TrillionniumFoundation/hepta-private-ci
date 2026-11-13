# Root review: first admission of original Material

Status: STATIC_SOURCE_REVIEW_ONLY. No format, compile, test, host execution, source ref movement or runtime authority is asserted by this review.

## Exact reviewed originals

All source identifiers below were fetched as complete Git blob text. Relevant implementations and public interfaces were inspected. This review does not claim a new full-repository gate.

- production.rs: af3990dfed96acafa7ea8a874c3d416c80a730c4.
- model.rs: ebdec3db9e6c28a7abacffc332d37c0fd6e2e22d.
- ledger.rs: d043d06c49312f75a023f8d0766ea088fbdc60db.
- durable.rs: eff97d826d794fdba519e862b96f644a41a61049.
- durable_codec.rs: 29773833806142d8c6967cd2ac94d48958d90b2e.
- checkpoint.rs: 14c908e13440b340095aaeaed10080ed15acf9e7.
- journal.rs: 8883b0ab6990257fabd86550958d70cbed5e87e3.
- lib.rs: c9bfc876390e1c7e5fea4b3f3af535f2c56fd245.
- Trusted-material control preparation: f8a645d5ce03d348a3b9f6cc3ce4d9f0e788f92e.
- Earlier Root complete-trust/material review: 3154dc0af47b2e684a9e57de7c4d18646fd68033.

## Findings

The original dataset_freeze_signing_payload_v2 first calls derive_dataset. That function rejects an empty ledger, replays the complete LedgerSnapshot through LearningLedger::from_snapshot, derives the eligible authenticated decision episodes for the exact objective, and includes actual outcomes, correction and revocation cuts. The signing payload includes the fixed v2 domain, snapshot ID, objective digest, inclusion-policy digest, ledger head, eligible frontier, outcome watermark, correction cut, revocation cut, and the count and sorted digests of selected source records. Checking only a head or a trust digest is not equivalent to reconstructing this payload.

LedgerSnapshot is Clone/Debug/Eq/PartialEq. Its records field is crate-private; the public API exposes records() and head_digest. It has no Serde derivation or public record constructor in the reviewed source. The public encode/decode_dataset_snapshot_v1 functions belong to a different protocol type. They are not a codec for this LedgerSnapshot. The canonical durable frame encoder and event decoder are crate-private. The ledger checkpoint module builds and verifies an index against an existing full snapshot; its index is not a replacement for source events.

LearningLedger::new, append and snapshot provide pure in-memory replay without opening a writer. from_snapshot compares every complete reconstructed LedgerRecord and append disposition, then the head. A new bounded transfer using these APIs would still have to transfer and validate the complete original events, authenticate the original evidence and bind the preselected Root contract. Pure semantic replay does not itself establish the authority of child-supplied events or signatures.

inspect_ledger is explicitly for a closed, fully witnessed ledger through an independently opened read-only File. It acquires a shared lock and rejects Busy, incomplete tails, unwitnessed complete suffixes and anchor mismatches. Locked aliases are unsupported. It returns a historical snapshot, not continuing revocation or use authority. It cannot be used to inspect the still-exclusive live A writer or to create a second writer.

The existing ParentMaterialControl proposal is a bounded replay/comparison of original typed inputs and full trust already held by the parent. Its complete freeze signature and payload comparisons are useful, but it does not implement first admission from child A. No claim of first admission, public-provider closure, real authorized A or real task outcome follows from those tests.

## Required next boundary

Retain Root-selected objective/profile, deployment components, budget, protocol and full trusted signer/controller/epoch state before the report. Reconstruct and verify the exact original freeze from complete bounded original evidence, using the existing canonical signing logic. A child cannot select a new trust state or authorize a replacement original task by sending its own config or digest. Do not re-sign a reconstructed report and describe it as the original A. Preserve one live writer and the source's original owner. If a bounded canonical transfer interface is added, review and qualify it explicitly rather than silently substituting a different snapshot protocol.

This establishes an implementation requirement, not completed execution. Real qualified A → T → B → decision → C → daemon/Root cold-recovery chains remain zero.
