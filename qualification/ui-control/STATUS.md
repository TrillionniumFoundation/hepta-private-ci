# ui.control verification status model

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`. This file defines stage meanings; it does not cache mutable CI or deployment outcomes.

## Evidence semantics

- **Observed outcome:** A concrete check ran and emitted a pass or failure observation for one exact subject. A later failure does not erase an earlier observation.
- **Accepted evidence:** A receipt was validated against its exact candidate, tree, deployment, and authority rules. Accepted stage evidence is monotone within an evidence bundle.
- **Overall acceptance:** The bundle is accepted only when every required stage, five distinct assurance principals, evidence-before-approval chronology, and the final production approval are accepted. A failed bundle may retain earlier accepted stage evidence without authorizing production or release.

| Stage | Repository state | Observation authority | Acceptance authority |
|---|---|---|---|
| `designDefined` | `defined_by_manifest` | tracked manifest and generated projections at the candidate tree | exact candidate tree plus generated-artifact drift check |
| `codePresent` | `present_in_authoritative_candidate` | source roots observed in the exact candidate tree | exact candidate tree and package-boundary qualification |
| `sourceTestsPassed` | `not_stored_as_source_truth` | exact-SHA workflow outcomes for dependency, lint, unit, contract, build, Lane B, and documentation checks | validated hepta.ui-control.qualification-receipt.v2 bound to the exact source commit and tree |
| `browserTestsPassed` | `not_stored_as_source_truth` | exact-SHA Chromium, Firefox, WebKit, keyboard, focus, and axe outcomes | validated source-head qualification receipt with browserTestsPassed and exact build-manifest digest |
| `mergeTreePassed` | `not_stored_as_source_truth` | deterministic synthetic-merge workflow outcomes | validated synthetic-merge qualification receipt bound to source, base, evaluated merge commit, and tree |
| `realBackendPassed` | `external_evidence_absent` | real Agentd probe plus retained chaos and authority evidence | validated hepta.ui-control.real-backend-receipt.v2 bound to the exact candidate and deployment digest |
| `productionDeploymentApproved` | `external_authority_absent` | deployment-security, real-backend, independent accessibility, independent security, operational exercise, and production approval receipts | non-expired production approval bound to all prerequisite evidence digests, five distinct review and approval principals, evidence-before-approval chronology, and an accepted external-evidence bundle |

A later stage never upgrades an earlier stage by implication, and a later failure never rewrites an earlier accepted stage to false. In particular, code presence is not a test pass, a source-head observation is not an accepted receipt, a source-head receipt is not a merge-tree receipt, and repository qualification is not real-backend or production-deployment approval.
