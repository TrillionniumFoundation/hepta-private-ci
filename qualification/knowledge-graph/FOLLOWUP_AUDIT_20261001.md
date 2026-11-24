# knowledge.graph follow-up audit — 2026-10-01

Reviewed baseline: `1ed1f65ed6bffe5320beedaad4c4e5f387237632`.
This follow-up continues [AUDIT_20261001.md](AUDIT_20261001.md); the committed
candidate and qualification artifacts bind the final source identity. It records
additional reproducible findings, source-boundary corrections and pending checks,
without repeating the first audit's implementation or capacity analysis.

## Findings and source corrections

| Finding | Correction or remaining boundary |
| --- | --- |
| Unchanged publication compared graph/profile/vector but omitted source snapshot | Require the same source snapshot; reject a first-publication receipt claiming Unchanged |
| Full-scan no-match queries reserved output slots proportional to unrelated graph edges | Grow result storage only when an edge is selected; empty/unknown seeds, unmatched kind and expired-edge cases preserve indexed/reference receipt equality with zero retained result capacity |
| Entity FTS reopen comparison omitted entity_key | Compare the complete selected entity identity; malformed extra or mismatched FTS rows fail closed |
| Technical guide omitted registered HNMF contracts and current typed retrieval consumers | List the contracts as target inputs; document GraphOneHop, Causal, Procedural and ContradictionSupport with their owner limits |
| Native implementation profile still described existing SQLite publication/query composition as unimplemented | Bind current kernel, indexed view, SQLite writer, read adapter and focused test sources; preserve pending execution/deployment claims |
| Publication replay bounds were generalized to complete startup | Distinguish current/predecessor publication reconstruction from retained fact-set and historical owner integrity scans |
| Sealed prompt relations had no durable owner registration or restored relation records | Existing atomic owner now persists/restores validated V2/V3 relation metadata; five new restart/revocation/fault and malformed-state tests passed |
| KG qualification trigger paths omitted composition dependencies | Include Cargo manifests/lock and shared type/authority dependencies in the dedicated qualification workflow |
| KG mapping claimed current exact observations with path-only identity semantics | Make exact-blob observation explicit while retaining the immutable source base and ancestry requirements |
| Dedicated KG qualification was blocked by unrelated non-ancestor module anchors | Add explicit owner-module selection; preserve default global verification, selected-source checks, repository cleanliness and hidden-index checks |
| KG workflow used `runner.temp` in job-level env, where runner context is unavailable | Initialize the evidence directory in the first runner step and export its path through GITHUB_ENV; the previous invalid workflow created no executable jobs |

The registered HNMF event, engram, synapse, cross-modal and forget contracts do not
prove native adapters or learned dynamics. Existing KG kernels project supported
symbolic relations; their facts remain owned by the cognitive or prompt owners.

The legacy graph optimizer is a library consumer. The canonical optimizer also
supports prerequisites and dominates/redundant/supersedes exclusions, but the
sealed prompt source currently produces only complements/substitutes/conflicts.
Numeric pair utility requires authenticated evidence. No named Agentd prompt
relation delivery route is established by these library APIs.

## Completion and practical limits

| Layer | Current source state | Outstanding evidence or implementation |
| --- | --- | --- |
| Kernel and cognitive product read/write composition | Implemented, including indexed/reference query paths; core Rust regressions passed | Cognitive-owner tests, ignored crash/history tests and Agentd execution |
| Prompt relations | Durable owner registration/restore, sealed source and library projection/consumer; restart/fault tests passed | Named product caller and end-to-end delivery qualification |
| Documentation | Detailed guide, dossier and current native mapping; derived hashes checked | Committed candidate verification |
| Startup/performance | Per-scope current projection limits; complete generation rebuild selected | Retention, complete startup memory/time budgets and target-host qualification |
| Deployment | Existing qualification harness and claim boundaries | Independent review, operator acceptance, activation, promotion and release |

Scope limits do not bound all retained revisions. Ordinary cognitive-owner open
checks historical fact-set digests and other integrity rows in addition to current
KG publication reconstruction. The finite history probe therefore cannot certify
history-independent startup or indefinite retention. A performance optimization
must retain these integrity properties or replace them with an owner-reviewed,
evidence-backed recovery design.

## Validation status

| Check | Result |
| --- | --- |
| `just test --locked -p codex-hepta-kg -p codex-hepta-prompt-registry -p codex-hepta-prompt-optimizer --no-tests=fail` | 118 passed, zero skipped: KG 31, registry 55, optimizer 32; includes all five new durable-relation tests |
| `just fmt`, scoped core `just fix`, strict core Clippy with `-D warnings` | Passed; unrelated formatter changes were reverted; fixes/lints introduced no further source changes |
| Scoped implementation-map regressions and existing map fixture tests | 5 new plus 86 existing tests passed |
| Four-owner mapping verification | Passed for knowledge.graph, prompt.registry, cognitive.store and memory.retrieval on a clean committed candidate |
| Budget/measurement checks and target-measure self-test | Nine regression tests and the self-test passed |
| Derived indexes and detailed-design companions | Checks passed; 49 analytic fixture tests passed |
| Cognitive-owner native test build | Two attempts exhausted the shared disk before tests executed; a third attempt was prevented by the free-space guard |
| Ignored crash/history tests, Agentd integration and remote exact-head/synthetic-merge qualification | Not executed locally; require dedicated CI evidence |

Remote publication additionally exposed a pre-existing Actions context error in
the dedicated workflow. GitHub rejected its job-level `runner.temp` expression
before creating jobs. The directory now uses RUNNER_TEMP in a runner step;
ordinary YAML parsing alone cannot establish GitHub expression-context validity.

The [core JUnit receipt](evidence/core-tests-junit.xml) records executed tests.
The tested core source blobs remained unchanged through formatting, scoped fixes
and strict lints. This local receipt does not replace remote exact-head or
synthetic-merge qualification. No cognitive-owner test pass is inferred from a
successful SQL reproduction, test source, or a disk-exhausted compilation.

Default global mapping verification remains blocked by seven unrelated module
anchors that are not ancestors of this candidate: objective.compiler,
utility.ndu, cognitive.read, learning.ledger, learning.artifacts,
automation.taskflow and control.engineering. Global implementation-bundle
validation also reports the existing unrelated `kernel.operations`
source/deployment claim mismatch. These claims and anchors were not rewritten;
no global pass is claimed.

The focused allocation regression is
[`query_allocation_tests.rs`](../../codex-rs/hepta-kg/src/query_allocation_tests.rs);
owner persistence regressions are
[`durable_relations_tests.rs`](../../codex-rs/hepta-prompt-registry/src/durable_relations_tests.rs).

Independent follow-up reviews rechecked publication source-cut identity, FTS
entity identity, request bounds, no-match allocation, indexed/reference equality,
durable relation restart/revocation and current owner/consumer mapping. No further
reproducible defect was found in those reviewed surfaces after the repairs.
Outstanding execution, product-delivery and target-host boundaries above remain
open. This finite iteration does not claim global optimality or confer deployment
authority.
