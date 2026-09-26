# ui.control execution dossier

> Generated from `qualification/ui-control/UI_CONTROL_MANIFEST.json`.

## Candidate identity

- authoritative development branch: `work/ui-control-full-convergence-20260926`
- convergence baseline: `7cba86aff6e6d035ce0355d72d08896248cb04a5` / `7718bf09154a845a82b4b04d8a3c7fda15757b13`
- exact candidate SHA/tree: derived by the qualification workflow
- release authorization: absent

## Implemented repository boundary

- framework-free ESM client core and explicit package exports;
- typed session, permission, transport, stale-view, snapshot-drift, and ambiguity failures;
- atomic pending reservation and concurrent duplicate promise sharing;
- durable recovery-state export/restore without authority claims;
- same-origin CSRF-protected HTTP adapter with no mutation retry;
- semantic HTML browser shell with start/reconcile/stop confirmation and audit identity display;
- Chromium, Firefox, WebKit, axe-core, keyboard, focus, stale-revision, duplicate-activation, and accepted-timeout tests;
- single-manifest generated technical guide, implementation map, and this dossier.

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

## Qualification commands

- `npm run lint --prefix apps/hepta-control-ui`
- `npm test --prefix apps/hepta-control-ui`
- `npm run test:contract --prefix apps/hepta-control-ui`
- `npm run build --prefix apps/hepta-control-ui`
- `npm run test:e2e --prefix apps/hepta-control-ui`
- `node scripts/ui-control-artifacts.mjs --check`
- `python3 scripts/hepta-lane-b-path-guard.py self-test`
- `python3 -m unittest scripts/test_hepta_lane_b_path_guard.py`
- `python3 scripts/hepta-lane-b-path-guard.py verify`

## Receipt semantics

The CI receipt records exact SHA/tree, runner/Node identity, check outcomes, and browser build-manifest digest. It sets production deployment, identity-provider, deployed CSP, independent acceptance, and release authorization to false unless separately observed. The tracked repository does not pre-claim those facts.

## Remaining non-repository evidence

- production identity-provider and permission-revision integration
- deployed backend operation-id uniqueness and durable lookup evidence
- deployed CSP/CSRF/TLS/reverse-proxy observation
- production monitoring, alert routing, and rollback exercise
- independent assistive-technology and operator acceptance signature
