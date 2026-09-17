# learning.plasticity current implementation status

This document is the source-of-truth status overlay for the broader target architecture in `TECHNICAL.md`. It prevents target requirements from being mistaken for currently composed or activated behavior.

## Status legend

- **Implemented** — native source exists in the declared root and has focused test identity.
- **Composed source** — a named repository caller exists, but this is not production activation evidence.
- **Host responsibility** — the crate deliberately requires a trusted host boundary and cannot prove the fact itself.
- **External gate** — requires independent/operator/target-host evidence outside repository source.
- **Target** — designed but not yet implemented or activated.

## Capability matrix

| Capability | Status | Native/source identity | Notes |
| --- | --- | --- | --- |
| Parameter V2 integrity construction | Implemented | `parameter_v2::propose_v2` | Compatibility API; supplied candidates remain integrity-only. |
| Parameter V2 verification | Implemented | `parameter_v2::verify_parameter_proposal_v2` | Canonical ordering, digest, exact successor and trust-region checks. |
| Native parameter candidate generation | Implemented | `generator::generate_parameter_proposal_v2` | Deterministic ranked signal-to-candidate generation; caller no longer supplies final candidate set on the composed path. |
| Evidence provenance/freshness authentication | Host responsibility + enforced boundary | `trusted::EvidenceVerifier`, `trusted::propose_authenticated_v1` | Production composition cannot treat non-zero digests as authentication. |
| Independent evaluator authentication | Host responsibility + enforced boundary | `trusted::IndependentEvaluatorVerifier` | Unequal ID strings alone are insufficient on the composed path. |
| Durable parameter proposal storage | Implemented | `durable_registry::DurableProposalRegistry` | Compatibility surface supports raw unanchored open. |
| Production anti-rollback reopen | Implemented boundary + host responsibility | `production_registry::ProductionProposalRegistry` | Product path permits only fresh initialization or externally anchored reopen. Host must retain anchor in an independent rollback domain. |
| Product-composable generate/authenticate/append path | Implemented | `engine::generate_authenticate_and_append_v1` | Requires production-safe registry and authenticated verifiers. |
| Named Lane-F caller | Composed source | `codex_hepta_intelligence::run_plasticity_proposal_cycle_v1` | Establishes a real repository caller; does not by itself prove deployed production execution. |
| Topology V2 proposal construction/verification | Implemented | `topology_v2::{propose_topology_v2, verify_topology_proposal_v2}` | Candidate-only, exact-successor, migration/rollback/evidence-bound, deny-all. |
| Topology durable registry/application | Target | none | No current graph mutation, writer handoff or topology activation path. |
| Parameter training/install/application | Target | none | Proposal records never install weights or mutate the current runtime. |
| Selection/acceptance/promotion/release | External gate | none in this module | Must remain independently governed. |
| Production activation | External gate | target-host evidence | Repository source composition is not deployment evidence. |

## Section classification for TECHNICAL.md

The following classification applies when reading the parent guide:

| TECHNICAL.md section | Classification |
| --- | --- |
| 1 Identity/mission/ownership | Implemented governance facts + target mission |
| 2 Source binding/status | Implemented source binding; activation claims remain external |
| 3 Boundary/responsibilities | Implemented deny boundaries + target cross-module composition |
| 4 Internal architecture | Mixed: generator/filter/writer now implemented; external loaders/adapters remain host responsibilities |
| 5 Contracts/compatibility | Mixed: internal Parameter V2 and Topology V2 implemented; canonical external contract activation remains target/external |
| 6 Data authority/persistence | Mixed: durable parameter registry implemented; host path/backup/revocation/deletion remain host responsibilities |
| 7 Runtime/concurrency | Parameter writer implemented; deployed host scheduling remains external |
| 8 Failure/recovery/rollback | Local durable recovery implemented; independent anchor retention and incident recovery remain host responsibilities |
| 9 Security/privacy | Source deny boundaries implemented; key/signature/provider trust remains host responsibility/external review |
| 10 Performance/capacity | Native hard bounds implemented; deployed SLO measurements remain external |
| 11 Observability/operations | Operational policy is in `OPERATIONS.md`; deployed telemetry evidence remains external |
| 12 Verification/qualification | Focused test identities implemented; exact-head CI receipts must be read from the current PR/head |
| 13 Work packages | PLS-1 source substantially implemented; PLS-2 proposal source implemented; structural canary/application remains target |
| 14 Activation/retirement | External gate |
| 15 Completion | Mixed; source completion is distinct from production activation/release |

## Claim boundary

The following claims remain prohibited until separate evidence exists:

- production deployment is active;
- an independent evaluator accepted a proposal;
- generated candidates were selected or applied;
- parameter weights were trained/installed;
- topology was mutated;
- operator acceptance, canary promotion or release completed.
