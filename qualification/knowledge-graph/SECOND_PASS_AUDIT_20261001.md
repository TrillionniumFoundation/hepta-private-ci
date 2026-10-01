# knowledge.graph second-pass audit — 2026-10-01

Reviewed source: `1a75d5f14fe7e66ee108086351917217289d43ac`, the published
follow-up to `1ed1f65ed6bffe5320beedaad4c4e5f387237632`. The main branch remains
`a126987b84737dbc2ee2592442a314117bddb4a2`. This report continues
[FOLLOWUP_AUDIT_20261001.md](FOLLOWUP_AUDIT_20261001.md) and records newly
reproduced defects rather than treating an earlier review as exhaustive.

## Documentation and project ownership

The [technical guide](../../docs/modules/knowledge.graph/TECHNICAL.md),
[implementation dossier](../module-execution-dossiers/detail/knowledge.graph.md),
native implementation map, capacity probes and target-host budget harness provide
detailed development material. Their target contracts are not execution receipts.
KG owns projection, canonical generation and query semantics. Cognitive and prompt
owners retain facts and persistence; consumers cannot acquire mutation authority
from a KG receipt. This audit extends integrity checks in those existing owners
instead of creating another graph fact store.

Agentd already has a canonical portfolio compiler/runtime-stage consumer. It does
not thereby establish the sealed prompt-factor source -> KG projection -> graph
selection route. Compilation freshness and final provider dispatch are separate
boundaries, each requiring current owner evidence.

## Reproduced findings and repairs

| Finding | Reproduction and repair |
| --- | --- |
| Cognitive history qualification cannot compile | Both remote lanes failed with six E0659 ambiguous `assert_eq!` uses. Add the explicit pretty_assertions macro import; preserve the workload and assertions. |
| Adapter and graph tests were never compiled | KG prompt_factor_tests.rs and optimizer graph_tests.rs were not declared as modules. Their stale dependency-private calls would also fail when enabled. Wire real tests using public durable owners and signed final-use admissions, with no exported fixture authority. |
| Memory FTS can diverge from source | A normal FTS UPDATE preserves quick_check and foreign keys while changing lexical recall. Verify every immutable memory revision has exactly one FTS row and that every indexed identity/content matches its source, including superseded and tombstoned history. |
| Historical entity FTS can alter current retrieval ranking | Obsolete entity rows contribute to BM25 corpus statistics but were outside current-generation comparison. Verify the complete retained entity FTS corpus against exact source identities, canonical IDs, types and labels; retain current-generation reconstruction checks. |
| Canonical selection admits candidates outside its complete graph | A graph containing only factor `b` can previously select positive-utility candidate `a`: an unknown seed yields no relation edges. Require every priced candidate to occur in the validated graph before querying; a represented relation-free candidate remains valid. Preserve the generic kernel query's unknown-seed semantics and add the counterexample regression. |
| Relation changes after selection do not invalidate exercise | Registering a governed conflict leaves selected realization bindings unchanged. Retain the enumerated registry digest in the selected portfolio, bind it into the receipt checksum, and reject source/checksum drift at exercise; prove compiler rejection separately. |
| Persisted attachments outlive their source fence | Compilation-time checks do not protect prepare/dispatch after a staged attachment is restored against a changed registry. Persist an attachment-bound registry snapshot and check the shared current owner during prepare and every dispatch claim, including cached prepare/idempotent retry; preserve unresolved-dispatch reconciliation and historical records. |
| Staged deadline can outlive selected-portfolio validity | With unchanged registry source and a longer requested deadline, an expired selection can otherwise remain dispatchable. Cap the attachment deadline at the minimum of request, portfolio validity and realization expiry. |
| A lock waiter can bypass mandatory reopen after uncertain durability | A waiter can pass the first availability check, block on runtime state, then acquire it after another commit has poisoned the owner following rename. Recheck availability after acquiring state in commit and prepare; deterministic waiter regressions must prove no stale read or successor write is admitted. Native validation is pending. |
| Capacity wording overstates canonical cardinality | The 256-write probe contains 4,096 entity/32,768 relation revision occurrences but only 16 canonical nodes and 128 canonical edges. Describe the actual fixture and avoid claiming an executed canonical pilot-size receipt. |

New semantic FTS checks use aggregate SQL and joins. They do not fetch all history
into Rust or issue one query per revision. They still add historical scan and SQL
grouping costs: owner startup is history-dependent and needs retention/startup
budgets. The audit does not remove integrity checks or erase history to claim
bounded startup.

Registry-source invalidation is conservative: owner mutations require reselection
or recompilation even when selected realization bytes remain equal. A receipt
checksum proves binding consistency, not a signature or permission. Every graph,
portfolio and compiler claim retains its original authority boundary.

The runtime fence uses optional metadata in the existing schema-1 staged record,
with no new store or authority. Old unfenced stages remain readable and pending
dispatches can be reconciled; the bound pipeline rejects their prepare/dispatch
without inventing a source binding. Standalone generic qualification-host behavior
is preserved. Older binaries reject populated unknown metadata, so downgrade needs
owner review. Source-fence regressions are wired under
`prompt_runtime::tests::source_fence`; they and the queued-poison regression require
current native execution.

## Executed baseline qualification

[GitHub Actions run 36783032514](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36783032514)
tested both source-head and deterministic base-merge lanes. The source head was
`1a75d5f14fe7e66ee108086351917217289d43ac`; the merge candidate was
`f3b02512169b0c158625afe73c059f4b5cc23a6f` with the same source tree.

| Baseline check | Executed result |
| --- | --- |
| Canonical KG kernel | 31 passed, zero skipped, in each lane |
| Prompt registry | 55 passed, zero skipped, in each lane |
| Prompt optimizer | 32 passed, zero skipped, in each lane |
| Scoped four-owner mapping, harness checks and KG-owned formatting | Passed in each lane |
| Detailed-design conformance | Passed; this is coverage/hash/path/oracle conformance, not product execution |
| Cognitive native tests | Compilation failed with E0659; zero memory tests executed |
| Ignored crash/capacity/history, Agentd profiles and combined strict lint | Skipped after the compile failure |

The previous 118-test receipt cannot cover newly enabled adapter/graph tests or
the new owner and delivery regressions. Local memory builds had separately failed
with ENOSPC. Neither compilation failure is a test pass or evidence that recovery
works.

## Current-candidate validation and completion

Current source tests, formatter/lints, final mapping observations and published
execution receipts are recorded here after they execute. Pending source changes
must not inherit baseline passing claims. The core source inventory expects KG 35,
registry 55 and optimizer 38 tests (128 total), including four newly wired adapter
tests, four newly wired graph-consumer tests and two new canonical regressions.
This is an expected count, not an executed result. Current local native attempts
hit ENOSPC; local Bazel lock regeneration was blocked by JDK trust configuration.
Neither blockage establishes test or dependency-lock success.

Required CI retains the original cognitive recovery, crash, history, performance
and Agentd workloads. It expands scoped source truth to six owners and adds
intelligence compiler delivery, Agentd prompt-runtime library regressions,
dependency-lock consistency, scoped `just fix` and strict lint. Free-space receipts
supplement actual step logs; no workload or integrity check is relaxed to make CI
pass. Full-history FTS, canonical and runtime repairs require current-candidate
source-head and deterministic base-merge execution.

The current documentation passed derived-index freshness, local link/hash checks
and detailed companion conformance, including 49 analytic fixture tests. These
checks establish document consistency; they do not execute the new native code.

The reproduced findings define this audit's scope; further review and native
verification remain open. Outstanding product integration,
canonical large-graph capacity, retention budgets, target-host acceptance and
release gates remain distinct from source implementation. No production,
activation or independent-acceptance claim is promoted by this report.
