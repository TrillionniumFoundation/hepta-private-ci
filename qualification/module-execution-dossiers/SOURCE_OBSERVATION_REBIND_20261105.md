# R5 source-observation rebind — draft

This change rebinds source navigation for the selected implementation maps through the existing `hepta-implementation-maps.py migrate` command. Qualification must use the original `qualification` profile on the exact committed result. It checks source identity and declared evidence; it does not execute the modules.

The 19 selected maps retain all 189 operations, their tests, delegates, authority and state descriptions, the 32 named callers, repository gaps and external evidence gates. `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation` and `release` remain false. A source rebind supplies no new product execution, independent acceptance, activation or release evidence.

## Retained historical records

The following nested records describe earlier observations. The migration does not renew their execution status or maintain their custom source-selection rules.

| Maps and retained field | Retained identity | Interpretation after the source rebind |
| --- | --- | --- |
| `runtime.agentd.currentSourceEvidence` and `learning.ledger.currentSourceEvidence` | `cbb3cee084a4caf4702dd4e575cae5504486c176`, tree `e22806b086240bb2015344dfb545734342c7fdb3` | Historical module-local observations. Their named source paths have since changed; they do not qualify the new candidate. |
| `objective.compiler.exactSourceCandidate` | `e946a7ed08814881f9986d813c5b8cd821241f99`, tree `5c62cf98768ee7f99c55e80c3b4430bcfddd41e7` | Historical Objective source candidate. The existing newest-touching-source declaration is not regenerated or checked by the generic map migrator. |
| `objective.compiler.productCompositionSourceCandidate` | `e603e7ac675843e69f6cfd741e42180b2d5437ed`, tree `6de843d2ddf162869e4aff0ebb84642d4b2c26c3` | Historical product-composition source candidate. Its original workflow and target-host gates remain required for a new candidate. |
| `memory.federation.headAttestation` | `395244ed716934c0e63a4a01dbe708a8c989276e`, tree `64951a030a3642179408aa1b821fe60a07002ebe` | Historical branch observation with its original pending-execution status. References to current main inside that retained record describe the recorded observation, not the new candidate. |

Existing `sourceObservationRebind` links to the 2026-10-27 ledger remain historical provenance. Their previous-map blobs and old receipts are retained unchanged.

The new candidate's source identity is established separately by the migrated source associations and the actual exact-commit/tree qualification receipt. That receipt must be added only after the final source is frozen, the reviewed documentation commit exists, and the original verifier completes successfully. Neither this draft nor mechanical migration establishes that the full documentation has been semantically requalified or that runtime tests have passed.
