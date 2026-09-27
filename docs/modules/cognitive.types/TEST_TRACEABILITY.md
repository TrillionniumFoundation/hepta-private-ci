# cognitive.types test traceability

| Requirement | Source enforcement | Deterministic tests | Cross-language or adversarial evidence |
|---|---|---|---|
| exact canonical JSON | `wire.rs` | `contract_tests.rs` | Python V1 oracle and V2 Python/Node oracle |
| closed schema/version registry | `registry.rs` | `hardening_tests.rs` | fuzz registry inspection |
| private checked wrapper | `contract.rs::Validated<T>` | hardening and consumer tests | mutation workflow |
| domain-bound digest metadata | `contract.rs` | `domain_golden_vectors_v1.rs` | `golden-vectors-v2.json` |
| Unicode code-point preservation | `contract.rs` | deterministic property test | Python/Node Unicode vectors |
| full write-intent binding | `write_receipt.rs` | hardening and golden-vector tests | Python/Node self-digest recomputation |
| tagged rejection without fabricated record | `write_receipt.rs` | rejection serialization test | golden rejected receipt |
| federation state consistency | `strict.rs` | strict validator tests | mutation workflow |
| relation/weight consistency | `strict.rs` | hardening and property tests | V1 golden compatibility |
| replay caps and empty consistency | `strict.rs` | strict validator tests | fuzz and mutation |
| plasticity caps and sign consistency | `strict.rs` | property and golden tests | V1 golden compatibility |
| topology operation/delta consistency | `strict.rs` | strict validator tests | fuzz and mutation |
| forget caps and nonempty consistency | `strict.rs` | strict validator tests | fuzz and mutation |
| selector existence boundary | `SelectorResolutionContextV1` | hardening test | RFC 6901 generated properties |
| consumer maintainer/schema/direction registry | `consumer.rs` | consumer registry tests | five consumer compile-contract tests |
| exact comparison gate | `ShadowComparisonReceiptV1` | generated property tests | mutation workflow |
| checked store canonical adapter | `hepta-cognitive-store/canonical_adapter.rs` | store consumer/adapter tests | exact qualification workflow |
| real fuzz execution | fuzz target and workflow | bounded pull-request fuzz | scheduled sustained fuzz |
| mutation testing | mutation workflow | pull-request diff mutants | scheduled core mutants |
| exact-head evidence | qualification script/workflow | head job | immutable JSON artifact |
| synthetic-merge evidence | qualification script/workflow | merge job | immutable JSON artifact |

## Evidence rule

A source reference establishes that a check exists. Only the artifact produced for the exact commit, tree and toolchain establishes that it passed. Cancelled, skipped, stale-SHA or unrelated workspace runs are not evidence for this module.
