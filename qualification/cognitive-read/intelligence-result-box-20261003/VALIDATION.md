# Agentd pre-release Rust payload ownership migration

## Explicit compatibility boundary

This stage changes the Rust source API of three exported Agentd V1 enums:
`AgentdIntelligenceProductOutcomeV1::Ready`, the `prepared` field of
`AgentdIntelligenceAdmittedOutcomeV1::Ready`, and
`AgentdIntelligenceLedgerError::Indeterminate` now own boxed payloads.
Constructors use Box::new; consuming a payload as its prior by-value type uses
`*prepared` or `*pending`. Ordinary borrowed field access still dereferences.
This is not Rust-source-compatible for downstream constructors/type annotations.

The Agentd package is configured publish=false at workspace version0.0.0. The
tracked Rust consumer inventory is confined to Agentd; no supported published
external consumer or specific stable by-value promise for these three types
was found in the checked contracts. The source-level migration was reviewed as
an isolated pre-release change, not a claim that unknown external Git consumers
cannot exist. The upstream intelligence `CanonicalRunOutcomeV1` and its explicit
public by-value contract are untouched. None of the three changed enums derives
Serialize/Deserialize. Protocol declarations, canonical envelope, receipts,
ledger events, digest preimages and persisted formats are unchanged.

## Caller and behavior checks

All named declarations, exports, constructors and matches are inventoried.
Actual construction changes are two Box allocations in the existing runner;
normalizing those wrappers and checked single-expression match-arm formatting reproduces its entire prior body. Both admitted
constructors forward the prepared box without another allocation. Existing
state/objective consumers preserve their readiness/abstain/slow-path behavior.
No authority, currentness, budget or ledger validation is removed.

The existing selected signed real-owner test explicitly consumes the admitted
box, replays the exact persisted decision through an owned pending box and the
existing by-value reconcile API, and requires an idempotent receipt plus exactly
unchanged ledger bytes. This checks the ownership/replay contract; it does not
claim an injected I/O failure. The existing revocation test also consumes the
prepared box before proving currentness rejection. These tests remain selected
by the existing cognitive qualification gate. No test selector or minimum is
relaxed and no lint allowance is introduced.

Scoped formatting, source-body/caller review and Python checks are local evidence.
Fresh Rust/strict-owner execution is pending hosted qualification; the preceding
0842 source/merge passes are not relabeled as this source. The crate-private
Automation result box is a separate predecessor commit with its own two snapshot
conversion tests. Remaining browser/plasticity findings, paused AuthBus lints,
Darwin release-install failures and the distinct retained runtime generation
handoff are unchanged. No merge, deployment, trust provisioning or activation.

Published source stages: private Automation `32ff1a2b90d60a6c5f0d05f38d758346fa809b74` (tree `ff2142a81e340077beb44762b23daadbb7a2528e`); Agentd Intelligence `916785e374ea69e62a2c7f57f491ad0e815b2edf` (tree `cf4852c0e79fcce605a3af49e12284a5b4ffd5b6`). These are isolated source stages in the current observation lineage. All228 previous paths remain; 231 exact objects include the additional Automation host, converter tests and Intelligence result declarations. Every historical identity, claim flag and unrelated map is unchanged. Local Python results:105 passes with3 existing skips, then26 passes.

Follow-up source `5fd6c05889d4b0ef357997d4322e40ca52ee8d7b` corrects a test-only undeclared pretty_assertions import by using the existing standard assertion macro. No Cargo input changes. The current231-path observation binds this corrected source; no successful Rust result is attributed to the intermediate head.
