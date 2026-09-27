# ui.control verification status model

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`. This file defines stage meanings; it does not cache mutable CI or deployment outcomes.

| Stage | Repository state | Pass authority |
|---|---|---|
| `designDefined` | `defined_by_manifest` | tracked manifest and generated status projection |
| `codePresent` | `present_in_authoritative_candidate` | exact candidate tree |
| `sourceTestsPassed` | `not_stored_as_source_truth` | exact-SHA qualification receipt |
| `browserTestsPassed` | `not_stored_as_source_truth` | exact-SHA Chromium/Firefox/WebKit and axe receipt |
| `mergeTreePassed` | `not_stored_as_source_truth` | deterministic synthetic-merge receipt |
| `realBackendPassed` | `external_evidence_absent` | real Agentd/backend qualification receipt |
| `productionDeploymentApproved` | `external_authority_absent` | deployment and release authority |

A later stage never upgrades an earlier stage by implication. In particular, code presence is not a test pass, a source-head test pass is not a merge-tree pass, and repository qualification is not real-backend or production-deployment approval.
