# ui.control external qualification

Repository tests prove the client, browser shell, protocol fixture, and deterministic merge candidate. They do **not** prove a real Agentd/backend deployment or authorize production.

## Stage model

`UI_CONTROL_MANIFEST.json` owns the seven stage definitions. `scripts/ui-control-status.mjs` projects them into `STATUS.md` and `GATE_MAP.json`; source-head and synthetic-merge jobs emit `hepta.ui-control.qualification-receipt.v2` receipts from the same manifest.

The stages are deliberately separate:

1. design defined;
2. code present;
3. source tests passed;
4. browser tests passed;
5. merge tree passed;
6. real backend passed;
7. production deployment approved.

No later stage is inferred from an earlier stage.

## Real deployment security probe

`deployment-security.mjs` runs only against an externally authenticated HTTPS deployment. It checks observed TLS routing, CSP, HSTS, CORS rejection, CSRF-before-connect, authenticated session establishment, Secure/HttpOnly/SameSite cookie issuance, coherent view access, mutation CSRF precheck, and authenticated close. It never performs a runtime mutation.

Required environment:

```text
HEPTA_UI_CONTROL_BASE_URL
HEPTA_UI_CONTROL_COOKIE
HEPTA_UI_CONTROL_CSRF_TOKEN
```

Run after building the exact candidate:

```bash
npm ci --prefix apps/hepta-control-ui --ignore-scripts --no-audit --no-fund
npm run build --prefix apps/hepta-control-ui
node qualification/ui-control/deployment-security.mjs ui-control-deployment-security-receipt.json
```

A passing receipt observes deployment security for one endpoint and artifact. It does not prove runtime semantics, independent accessibility acceptance, or production approval.

## Real Agentd/backend semantics probe

`real-backend-contract.mjs` performs mutations and therefore requires disposable qualification identities and a disposable target. It verifies:

- concurrent identical operation identity resolves to one durable record;
- the same identity with changed semantics returns conflict;
- a request rejected before admission creates no durable record;
- an accepted acknowledgement discarded by the client is recovered by immutable operation ID;
- a second authenticated identity cannot read the first identity's operation;
- terminal facts remain discoverable through lookup;
- revocation immediately removes session authority.

It also requires retained crash/restart evidence matching `AGENTD_CHAOS_EVIDENCE_SCHEMA.json` for:

- crash before admission commit;
- crash after admission but before dispatch;
- crash after dispatch but before terminal observation;
- restart and terminal reconciliation.

Required environment:

```text
HEPTA_UI_CONTROL_BASE_URL
HEPTA_UI_CONTROL_COOKIE
HEPTA_UI_CONTROL_CSRF_TOKEN
HEPTA_UI_CONTROL_SECONDARY_COOKIE
HEPTA_UI_CONTROL_SECONDARY_CSRF_TOKEN
HEPTA_UI_CONTROL_TARGET_ID
HEPTA_UI_CONTROL_CHAOS_EVIDENCE
HEPTA_UI_CONTROL_ALLOW_MUTATION=I_UNDERSTAND_THIS_USES_A_DISPOSABLE_QUALIFICATION_TARGET
```

Optional settings are `HEPTA_UI_CONTROL_ACTION` (`request_reconcile`, `request_start`, or `request_stop`) and `HEPTA_UI_CONTROL_TERMINAL_TIMEOUT_MS`.

## Independent acceptance and production approval

`INDEPENDENT_ACCEPTANCE_SCHEMA.json` binds the candidate commit/tree, asset manifest, real backend deployment, browser/OS/assistive-technology versions, independent verifier, cases, and raw evidence digest. Chrome, Firefox, Safari, keyboard-only, and screen-reader evidence must be retained against the same backend and candidate.

Even complete repository, backend, deployment-security, and independent-acceptance receipts do not themselves authorize production. The final stage requires explicit deployment and release authority.