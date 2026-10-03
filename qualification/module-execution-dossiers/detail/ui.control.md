# ui.control: implementation design

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`.

## 1. Source and work envelope

Roots: `apps/hepta-control-ui`. Work package: `UI-V5`. Lane: `LANE-B-RUNTIME`.

### Candidate identity

- authoritative development branch: `work/ui-chat-convergence-20261002`
- convergence baseline: `a126987b84737dbc2ee2592442a314117bddb4a2` / `a22fd0074c45ae6f3cef2092cd6e273bf9c26c30`
- exact candidate SHA/tree: derived by the qualification workflow
- release authorization: absent

## 2. Public operations and contract details

- Actual Robrix-derived Makepad widgets shared by native and WASM; source provenance and MIT notices recorded.
- Existing Rust authority-free control/chat/owner contracts; no new execution or durable recovery owner.
- Fenced local room/draft actions and bounded observed timeline projection.
- Default-denied send, honest unknown/queue states; external principal/signer/bridge absent.
- Console exists as an internal tab; operational widgets remain unported.
- Strict-CSP packaging with a source-bound WASM clock patch and static ABI generation.
- Explicit historical Node oracle and semantic-DOM compatibility checks, excluded from product exports.

The [technical guide](../../../docs/modules/ui.control/TECHNICAL.md) distinguishes retained owner adapters from the unqualified Makepad host composition. Source presence and old controller/DOM checks do not establish a production chat or Console operation.

## 3. State records and transaction design

Rust owns presentation state and local room/draft actions. Chat drafts are transient; they are not a durable recovery claim. Retained control adapters hold bounded pending/recovery identities, while authenticated backend owners retain authorization, durable operation uniqueness and terminal facts. A local queue acknowledgement, timeout or disconnect cannot establish successful external execution.

## 4. Deterministic algorithm and scheduling

The shared Rust widgets render conversation navigation, the observed timeline and the composer. Fenced local actions update presentation state; send remains denied without the external principal/signer/bridge. Console is an internal tab with unported operational widgets. Generated Makepad JavaScript is platform/ABI glue, not a second application or execution owner.

## 5. Capacity and performance profile

Use the bounded Rust owner/timeline contracts and source-bound host qualification plan. Host frame/resize observations and drawing-buffer dimensions are diagnostic evidence, not calibrated GPU measurements or platform capacity acceptance. Native display, OS IME, assistive technology, mobile input and target-host performance remain unqualified.

## 6. Concrete verification cases

- UI-01: incompatible protocol versions must block mutating controls with an explicit explanation.
- UI-02: stale confirmation must not authorize a changed target, payload or revision.
- UI-03: reconnect must reconcile pending identities without duplicate requests or inferred success.
- UI-04: keyboard-only and screen-reader users must be able to inspect uncertainty, request an authorized stop and recover focus after errors.

These remain product test designs, not executed-test receipts. Retained adapter tests can cover only their recorded subjects; the Makepad host and external composition require their own exact-input/output, oracle and independent acceptance evidence.

### Evidence scope

The existing controller/DOM unit, transport, recovery, axe and Lane-B cases qualify
only their recorded subjects. They do not establish Makepad host behavior.
New presentation tests, actual WASM/schema extraction, source-bound package
manifests and hosted browser screenshots are separate evidence. Browser startup
smoke still requires human pixel review and additional input, IME, accessibility,
scroll, reconnect and live owner-composition acceptance. No percentage or full
completion claim is inferred from source presence.

### Qualification commands

- `npm ci --prefix apps/hepta-control-ui --ignore-scripts --no-audit --no-fund`
- `npm run lint --prefix apps/hepta-control-ui`
- `npm test --prefix apps/hepta-control-ui`
- `npm run legacy:test-contract --prefix apps/hepta-control-ui`
- `npm run build --prefix apps/hepta-control-ui`
- `npm run test:e2e --prefix apps/hepta-control-ui`
- `node scripts/ui-control-artifacts.mjs --check`
- `python3 scripts/ui-control-source-map.py`
- `python3 scripts/hepta-lane-b-path-guard.py self-test`
- `python3 scripts/hepta-lane-b-path-guard.py verify`

## 7. Integration, rollback and capability ceiling

Integration must preserve the shared Rust authority boundary and all external gates. A host rollback must preserve compatible owner contracts and authenticated identity/revision fencing; it cannot substitute legacy DOM results for Makepad acceptance or introduce another recovery/runtime owner.

### Evidence and receipt semantics

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

### Remaining non-repository evidence

- production identity-provider and permission-revision integration
- deployed backend operation-id uniqueness and durable lookup evidence
- deployed CSP/CSRF/TLS/reverse-proxy observation
- production monitoring, alert routing, and rollback exercise
- independent assistive-technology and operator acceptance signature
- five-principal review/approval separation and evidence-before-approval chronology
