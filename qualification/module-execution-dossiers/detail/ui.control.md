# ui.control execution dossier

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`.

## Candidate identity

- authoritative development branch: `work/ui-control-authoritative-closure-20260927`
- convergence baseline: `a126987b84737dbc2ee2592442a314117bddb4a2` / `a22fd0074c45ae6f3cef2092cd6e273bf9c26c30`
- exact candidate SHA/tree: derived by the qualification workflow
- release authorization: absent

## Implemented repository boundary

- framework-free ESM client core and explicit package exports;
- typed session, permission, transport, stale-view, snapshot-drift, and ambiguity failures;
- atomic pending reservation and concurrent duplicate promise sharing;
- durable recovery-state export/restore without authority claims;
- same-origin CSRF-protected HTTP adapter with no mutation retry;
- semantic HTML browser shell with start/reconcile/stop confirmation, operator identity visibility, and deterministic DOM redaction for correlation identifiers;
- Chromium, Firefox, WebKit, axe-core, keyboard, focus, stale-revision, duplicate-activation, accepted-timeout, storage-denial, and privacy-redaction tests;
- single-manifest generated technical guide, implementation map, status/gate projections, and this dossier.

## Evidence matrix

| Case | Repository evidence | Expected result |
|---|---|---|
| UI-01 coherent view | `runtime-client.test.js` | generation/revision/digest projection accepted |
| UI-02 same-revision drift | `runtime-client.test.js` | `UI_CONTROL_SNAPSHOT_DRIFT` |
| UI-03 concurrent duplicate | `runtime-client.test.js` | one transport call, shared result |
| UI-04 pending capacity race | `runtime-client.test.js` | reservation prevents oversubscription |
| UI-05 accepted-timeout | unit and browser E2E | indeterminate, then operation lookup |
| UI-06 semantic conflict | unit and server fixture | fail closed / HTTP 409 |
| UI-07 stale confirmation | browser E2E | backend 412 surfaced, no operation created |
| UI-08 accessibility | Playwright + axe-core | zero automated violations; focus restored |
| UI-09 package boundary | `api-surface.test.js` | explicit exports; deep imports rejected |
| UI-10 Lane B cross-owner | `test_hepta_lane_b_path_guard.py` | canonical cross-lane map accepted; escapes rejected |
| UI-11 browser privacy | `control-console.spec.mjs` | full session/operation/audit/digest material and unknown exception text remain absent from the DOM |

## Qualification commands

- `npm ci --prefix apps/hepta-control-ui --ignore-scripts --no-audit --no-fund`
- `npm run lint --prefix apps/hepta-control-ui`
- `npm test --prefix apps/hepta-control-ui`
- `npm run test:contract --prefix apps/hepta-control-ui`
- `npm run build --prefix apps/hepta-control-ui`
- `npm run test:e2e --prefix apps/hepta-control-ui`
- `node scripts/ui-control-artifacts.mjs --check`
- `node scripts/ui-control-truth.mjs`
- `python3 scripts/hepta-lane-b-path-guard.py self-test`
- `python3 -m unittest scripts/test_hepta_lane_b_path_guard.py`
- `python3 scripts/hepta-lane-b-path-guard.py verify`

## Evidence and receipt semantics

- **Observed outcome:** A concrete check ran and emitted a pass or failure observation for one exact subject. A later failure does not erase an earlier observation.
- **Accepted evidence:** A receipt was validated against its exact candidate, tree, deployment, and authority rules. Accepted stage evidence is monotone within an evidence bundle.
- **Overall acceptance:** The bundle is accepted only when every required stage, five distinct assurance principals, evidence-before-approval chronology, and the final production approval are accepted. A failed bundle may retain earlier accepted stage evidence without authorizing production or release.

- `repositoryReceipts`: `hepta.ui-control.qualification-receipt.v2`
- `realBackend`: `hepta.ui-control.real-backend-receipt.v2`
- `deploymentSecurity`: `hepta.ui-control.deployment-security-receipt.v2`
- `independentAcceptance`: `hepta.ui-control.independent-acceptance-receipt.v2`
- `independentSecurity`: `hepta.ui-control.independent-security-review-receipt.v1`
- `operationalExercise`: `hepta.ui-control.operational-exercise-receipt.v1`
- `productionApproval`: `hepta.ui-control.production-approval-receipt.v1`
- `assuranceChain`: `hepta.ui-control.assurance-chain.v1`
- `externalEvidenceBundle`: `hepta.ui-control.external-evidence-bundle.v1`

The CI repository receipt records exact SHA/tree, runner/Node identity, check outcomes, and browser build-manifest digest. It sets production deployment, identity-provider, deployed CSP, independent acceptance, and release authorization to false unless separately observed and accepted. The tracked repository does not pre-claim those facts.

## Remaining non-repository evidence

- production identity-provider and permission-revision integration
- deployed backend operation-id uniqueness and durable lookup evidence
- deployed CSP/CSRF/TLS/reverse-proxy observation
- production monitoring, alert routing, and rollback exercise
- independent assistive-technology and operator acceptance signature
- five-principal review/approval separation and evidence-before-approval chronology
