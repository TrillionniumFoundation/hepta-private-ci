# intelligence.control: implementation design

Parent: `docs/modules/intelligence.control/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: canonical seven-owner composition source, a named Agentd product runner, and an authenticated daemon `ObjectiveStart` route now exist for the configured canonical profile; exact physical App Server execution and durable product-learning recovery remain pending. Exact-candidate execution, target-host qualification and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Owner root: `codex-rs/hepta-intelligence`. Named product-runner source: `codex-rs/hepta-agentd/src/intelligence_product.rs`; daemon routing is owned by `objective_runtime.rs` / `state.rs`, with seven-owner inputs supplied only by the host-owned invocation-provider seam.
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

Agentd owns the product-call lifetime but not the facts. The seven owner APIs are invoked directly from their authoritative crates. `AgentdIntelligenceProductRunnerV1::prepare_and_admit` combines canonical composition with Agentd `RunStart` and exact `ContextAttached`, so callers cannot promote a merely prepared envelope into a physical-turn binding. A successful cognition worker has no dispatch or ledger capability; after it returns, Agentd performs another full currentness check before publishing a dispatch-proposal digest. Currentness comes from an Ed25519-signed manifest whose verifier key is configured outside the manifest and whose signed domain includes the authority epoch, revocation frontier and all seven owner generation/implementation/key identities.

The daemon-owned `AgentRunCoordinator` freezes the exact prepared envelope into a typed run snapshot plus context attachment. runtime.codex accepts that binding only at the exact `ContextAttached` revision, persists its native dispatch identity, advances Agentd to `Dispatched`, and only then calls App Server `turn/start`. Decision and independently observed Outcome are appended only through the existing sealed `DurableLearningJournal`.

Ledger append uncertainty never becomes success. `Indeterminate` or ambiguous I/O returns `PendingIntelligenceLedgerAppendV1`, preserving the exact event and original predecessor. Reconciliation requires a freshly recovered journal and exact replay. Physical after-send uncertainty is also explicit: lost turn/start acknowledgement or a cancellation/deadline grace window without terminal provider evidence transitions the same Agentd run to `Indeterminate`; no automatic redispatch is permitted.

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
10. Revalidate every owner again, return an authority-free `IntelligenceHostEnvelopeV1`, then let Agentd perform one further final-use currentness fence before deriving a dispatch proposal and freezing the exact envelope into `ContextAttached`.
11. runtime.codex rechecks that exact Agentd run/context/envelope revision, persists its native dispatch write-ahead, advances the run to `Dispatched`, and only then crosses App Server `turn/start`.
12. Provider terminal observation returns to the same run revision. Lost turn-start acknowledgement, transport loss or no-terminal cancellation grace becomes `Indeterminate`, never safe replay.
13. Durable Decision and independently observed terminal Outcome remain separate learning-ledger events and still require currentness at append/reconcile time.

Each real owner call is measured with a monotonic `Instant` and rejected when it exceeds its stage budget. The entire cognition run also has a total timeout around a blocking worker. Late worker results have no effect/ledger capability and are discarded; this is effect isolation, not a claim that `spawn_blocking` can kill a running synchronous Rust instruction.

## 5. Capacity and performance profile

Canonical legal candidates are bounded to 128. The canonical snapshot requires exactly seven owners: objective, utility.ndu, neuron, prompt, intuition, context and evaluation. Each stage has a non-zero microsecond budget and the sum may not exceed the total cognition budget.

These are enforcement bounds, not target-host measurements. The blocking worker protects effect publication, not a claim that an arbitrary synchronous Rust call can be asynchronously killed mid-instruction. Current owner calls are bounded local/read-only algorithms; any future I/O-bearing adapter requires a process/driver boundary with its own kill/reconcile semantics.

## 6. Concrete verification cases

Source tests now include:

- `INTEL-01`: `codex-rs/hepta-intelligence/src/canonical_tests.rs`: seven-owner order with first-class NDU, abstention truncation, post-call generation drift, key rotation, wrong-owner receipt and duplicate candidate rejection.
- `INTEL-02`: `codex-rs/hepta-agentd/src/intelligence_product_tests.rs`: real objective/NDU/neuron/prompt/intuition/context/evaluation APIs, Agentd dispatch proposal, real durable Decision -> independent terminal Outcome, acknowledged reopen and idempotent retry.
- `INTEL-03`: The Agentd product tests also cover missing current owner, signed-currentness substitution, final-use revocation-frontier race, exact admit/context/dispatch/terminal lifecycle and total-budget timeout before any ledger capability is exposed.
- `INTEL-04`: Agent protocol tests cover strict bounded run-lifecycle DTO round trips with owner-controlled admission time.
- `INTEL-05`: Native inference source binds physical turn dispatch and terminal/indeterminate reconciliation to the exact Agentd intelligence run; a real-process App Server E2E for the exact candidate remains required before `productExecutionProved` can become true.
- `INTEL-06`: Existing vertical/evaluated-shadow tests remain compatibility regression coverage.

These are executable source tests. They become exact-candidate evidence only when the repository workflows execute them on the exact head and deterministic merge candidate. Target-host resource evidence remains a separate receipt.

## 7. Integration, rollback and capability ceiling

The product topology now has a daemon routing edge: Agentd owns the composition-runner source; authenticated `ObjectiveStart` invokes it only when the host-owned invocation provider is installed; `intelligence.control` remains an in-process composition facade and the seven facts remain with their owners. `AppServerModelDriver::run_intelligence` can consume the resulting exact run/context binding. This source routing is not evidence of a live provider or target-host exercise. Dispatch is not a model success claim: it is a durable/Agentd transition that precedes the physical App Server effect boundary.

Currentness is final-use, not admission-only. Key rotation, owner generation drift, authority-epoch drift or revocation-frontier drift invalidates the frozen run before publication. The currentness manifest itself must verify under the separately configured signer key, so rewriting JSON fields cannot substitute a new current key. An exact durable Decision/Outcome retry may replay after restart only when currentness still permits use.

This source grants no model/provider/tool/effect authority, no production activation, no selection/promotion/release authority and no independent acceptance. C1 prompted-memory retrieval remains a distinct planned capability and is not closed by the basic product composition.

## 8. Current native implementation

- **Canonical entrypoints:** `build_legal_candidates`, `prepare_intelligence_run`, `decide_boundary`, `assemble_context`, `validate_current_snapshot` in [codex-rs/hepta-intelligence/src/canonical.rs](../../../codex-rs/hepta-intelligence/src/canonical.rs).
- **Named runner implementation:** `AgentdIntelligenceProductRunnerV1` in [codex-rs/hepta-agentd/src/intelligence_product.rs](../../../codex-rs/hepta-agentd/src/intelligence_product.rs), with concrete adapters to objective, NDU, neuron, prompt, intuition, context, evaluation and the sealed learning ledger. Configured Agentd `ObjectiveStart` invokes it through the host-owned provider and freezes the prepared context in the daemon run lifecycle; compatibility mode does not.
- **Named physical caller:** `AppServerModelDriver::run_intelligence` in `codex-rs/hepta-infer-worker-host/src/native_run_control.rs`, backed by the real App Server driver and exact Agentd run-lifecycle RPCs. The `hepta-infer-worker` binary exposes the same binding through all-or-none intelligence arguments.
- **Compatibility/reference entrypoints:** `run_read_only_vertical`, `run_shadow_pipeline`, `run_shadow_pipeline_v2`, `run_evaluated_shadow_v1` and the bounded `compose` helper. They retain their historical receipt domains but are not the product facade.
- **State and recovery:** no new intelligence fact store. The currentness manifest is reread and signature-verified for every query. Agentd owns ephemeral run lifecycle state; runtime.codex owns its existing durable native dispatch journal; learning mutations remain behind the canonical authenticated `LedgerWriter` over its durable backend. Ambiguous ledger append preserves an exact pending replay object, while ambiguous physical dispatch is an Agentd `Indeterminate` run and is never redispatched automatically.
- **Source tests:** [codex-rs/hepta-intelligence/src/canonical_tests.rs](../../../codex-rs/hepta-intelligence/src/canonical_tests.rs), [codex-rs/hepta-agentd/src/intelligence_product_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_product_tests.rs), plus existing vertical/evaluated-shadow suites.
- **Operating references:** [codex-rs/hepta-intelligence/EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md) for the legacy evaluated-shadow surface and this dossier for the canonical product path.
- **Remaining work:** complete the physical App Server product execution from the daemon-prepared binding and make ambiguous Decision/Outcome append recovery durable across Agentd process loss; obtain current exact-head and deterministic-merge execution receipts; run exact-candidate real-process Agentd/App Server intelligence-bound E2E including lost-ack/restart/revocation races; collect target-host latency/RSS and hard-termination measurements; obtain independent semantic/security acceptance; and complete the separate C1 prompted-memory retrieval milestone. Source integration of the physical model route does not itself prove a live provider, target host, activation, promotion or release.

Native source admission commits the intelligence run, revision, context and envelope. Only a newly committed, non-idempotent Agentd dispatch may enter a physical model request. Unknown results remain reconcile-only. The same bounded generation/fence-aware coordinator owns preparation and admission.


## 9. Product-closure amendment

The current source candidate adds one RunStart-derived physical identity, one
fence constructor, composition-bound admission, a concrete host-owned invocation
provider, an atomic runner/provider profile API, canonical selected-candidate
membership checks, formal `LedgerWriter` Decision/Outcome APIs, a durable
`kernel.operations` outbox with exact restart replay, physical-terminal Outcome
binding, bounded telemetry and an opt-in hard-timeout Agentd process fence.

These source facts supersede earlier statements that durable product learning
or a provider implementation was wholly absent. They do not prove that the
ordinary CLI composes a provider, that a live provider/App Server path has been
exercised, or that target-host, independent-acceptance, activation, promotion or
release gates are closed. Exact status and test classification come from the
generated module JSON and its CI exact-head artifacts.
