# intelligence.control: implementation design

Parent: `docs/modules/intelligence.control/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: canonical seven-owner composition source and named Agentd product caller are implemented; exact-candidate execution, target-host qualification and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Owner root: `codex-rs/hepta-intelligence`. Named product caller: `codex-rs/hepta-agentd/src/intelligence_product.rs`.
Packages: `INTELLIGENCE-A0-Q0.63`, `INT-2-AGENTD-CODEX-COMPOSITION`, `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`.

The canonical product facade is `prepare_intelligence_run`. `run_read_only_vertical`, `run_shadow_pipeline{,_v2}` and `run_evaluated_shadow_v1` remain compatibility/reference and qualification surfaces; they are not parallel product control planes. Preserve existing owner stores and execution spines; the facade owns no objective, utility, neural, prompt, intuition, context, evaluation or learning fact.

## 2. Public operations and contract details

Implemented canonical operations:

- `build_legal_candidates(request) -> LegalActionCandidateSetV1` validates the bounded set, canonicalizes order and publishes an authority-free candidate-set digest.
- `prepare_intelligence_run(request, owner_ports, freshness_oracle) -> CanonicalRunOutcomeV1` is the single product composition entry. It orders objective -> utility.ndu -> neuron -> prompt -> intuition -> context -> independent evaluation and emits `IntelligenceHostEnvelopeV1` only for a selected, fully admitted run.
- `decide_boundary(run, candidate_set, intuition_receipt) -> AdvisoryDecisionReceiptV1` converts only the authenticated intuition receipt into selected/abstain/slow-path advisory state.
- `assemble_context(decision, context_receipt) -> ContextAssemblyReceiptV1` binds a selected decision to the source-aware context receipt.
- `validate_current_snapshot(snapshot, oracle)` rechecks current owner generation, implementation digest, key digest/epoch, authority epoch and revocation frontier immediately before product use.

`IntelligenceHostEnvelopeV1` carries bounded receipt references and no effect authority. `LegalActionCandidateSetV1` and intuition's calibrated-completeness digest remain distinct protocol domains; Agentd proves candidate identity closure while each owner verifies its own digest grammar.

## 3. State records and transaction design

The facade owns ephemeral orchestration only: run identity, frozen owner bindings, candidate-set identity, per-stage predecessor/output digests and advisory decision/context bindings. Each frozen owner binding includes generation, implementation digest and current-key identity. The snapshot additionally binds authority epoch, revocation frontier, body generation and configuration digest.

Agentd owns the product-call lifetime but not the facts. The seven owner APIs are invoked directly from their authoritative crates. A successful cognition worker has no dispatch or ledger capability; after it returns, Agentd performs another full currentness check before publishing a dispatch-proposal digest. Decision and Outcome are appended only through the existing sealed `DurableLearningJournal`.

Ledger append uncertainty never becomes success. `Indeterminate` or ambiguous I/O returns `PendingIntelligenceLedgerAppendV1`, preserving the exact event and original predecessor. Reconciliation requires a freshly recovered journal and exact replay.

## 4. Deterministic algorithm and scheduling

1. Validate canonical budget, frozen snapshot and bounded legal candidate set.
2. Before and after every owner call, reread current owner/key/authority/revocation state.
3. Admit and compile the exact objective through `objective.compiler`; its compiled semantic digest must equal the frozen objective digest.
4. Evaluate the complete owner contributions through policy-bound `utility.ndu::evaluate_candidates_with_policy`. The V2 evaluation digest is a first-class stage output.
5. Run `neuron.runtime::sparse_tick`; the tick must bind the objective and exact NDU predecessor digest.
6. Run `prompt.optimizer::optimize` over its registered prompt snapshot.
7. Run `intuition.policy::decide_calibrated_v2`; retain the exact positive propensity for a selected candidate. Abstain/slow-path terminates before context/evaluation/dispatch.
8. Compile context through `context.compiler::compile` bound to the canonical snapshot/objective.
9. Admit the selected candidate through `learning.eval::evaluate`; non-eligible dispositions stop the product path.
10. Revalidate every owner again, return an authority-free `IntelligenceHostEnvelopeV1`, then let Agentd perform one further final-use currentness fence before deriving a dispatch proposal.
11. Only after that boundary may Agentd append the durable Decision. Independently observed terminal Outcome is a separate ledger event.

Each real owner call is measured with a monotonic `Instant` and rejected when it exceeds its stage budget. The entire cognition run also has a total timeout around an isolated blocking worker. Late worker results have no effect/ledger capability and are discarded.

## 5. Capacity and performance profile

Canonical legal candidates are bounded to 128. The canonical snapshot requires exactly seven owners: objective, utility.ndu, neuron, prompt, intuition, context and evaluation. Each stage has a non-zero microsecond budget and the sum may not exceed the total cognition budget.

These are enforcement bounds, not target-host measurements. The blocking worker protects effect publication, not a claim that an arbitrary synchronous Rust call can be asynchronously killed mid-instruction. Current owner calls are bounded local/read-only algorithms; any future I/O-bearing adapter requires a process/driver boundary with its own kill/reconcile semantics.

## 6. Concrete verification cases

Source tests now include:

- `codex-rs/hepta-intelligence/src/canonical_tests.rs`: seven-owner order with first-class NDU, abstention truncation, post-call generation drift, key rotation, wrong-owner receipt and duplicate candidate rejection.
- `codex-rs/hepta-agentd/src/intelligence_product_tests.rs`: real objective/NDU/neuron/prompt/intuition/context/evaluation APIs, Agentd dispatch proposal, real durable Decision -> independent terminal Outcome, acknowledged reopen and idempotent retry.
- The Agentd product tests also cover missing current owner, final-use revocation-frontier race and total-budget timeout before any ledger capability is exposed.
- Existing vertical/evaluated-shadow tests remain compatibility regression coverage.

These are executable source tests. They become exact-candidate evidence only when the repository workflows execute them on the exact head and deterministic merge candidate. Target-host resource evidence remains a separate receipt.

## 7. Integration, rollback and capability ceiling

The product topology is now explicit: Agentd is the product caller; `intelligence.control` is an in-process composition facade; the seven facts remain with their owners; dispatch remains a proposal until the existing runtime/effect boundary authorizes and observes it.

Currentness is final-use, not admission-only. Key rotation, owner generation drift, authority-epoch drift or revocation-frontier drift invalidates the frozen run before publication. An exact durable Decision/Outcome retry may replay after restart only when currentness still permits use.

This source grants no model/provider/tool/effect authority, no production activation, no selection/promotion/release authority and no independent acceptance. C1 prompted-memory retrieval remains a distinct planned capability and is not closed by the basic product composition.

## 8. Current native implementation

- **Canonical entrypoints:** `build_legal_candidates`, `prepare_intelligence_run`, `decide_boundary`, `assemble_context`, `validate_current_snapshot` in [codex-rs/hepta-intelligence/src/canonical.rs](../../../codex-rs/hepta-intelligence/src/canonical.rs).
- **Named product caller:** `AgentdIntelligenceProductRunnerV1` in [codex-rs/hepta-agentd/src/intelligence_product.rs](../../../codex-rs/hepta-agentd/src/intelligence_product.rs), with concrete adapters to objective, NDU, neuron, prompt, intuition, context, evaluation and the sealed learning ledger.
- **Compatibility/reference entrypoints:** `run_read_only_vertical`, `run_shadow_pipeline`, `run_shadow_pipeline_v2`, `run_evaluated_shadow_v1` and the bounded `compose` helper. They retain their historical receipt domains but are not the product facade.
- **State and recovery:** no new intelligence store. File-backed Agentd freshness state is reread for every currentness query. Learning durability remains in `DurableLearningJournal`; ambiguous append returns an explicit pending exact-replay object.
- **Source tests:** [codex-rs/hepta-intelligence/src/canonical_tests.rs](../../../codex-rs/hepta-intelligence/src/canonical_tests.rs), [codex-rs/hepta-agentd/src/intelligence_product_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_product_tests.rs), plus existing vertical/evaluated-shadow suites.
- **Operating references:** [codex-rs/hepta-intelligence/EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md) for the legacy evaluated-shadow surface and this dossier for the canonical product path.
- **Remaining work:** current exact-head and deterministic-merge execution receipts; target-host latency/RSS/cancellation measurements; activation wiring into the selected live Agentd/App Server deployment profile; independent semantic/security acceptance; and the separate C1 prompted-memory retrieval milestone. Live provider/model/effect execution is outside this facade.
